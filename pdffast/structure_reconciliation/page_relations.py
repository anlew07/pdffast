"""Read-only decisions about adjacent pages, without document ownership or ranges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .preview import ReconciledStructurePreview, RecoveredDocumentAnchor


_STRONG_CONTINUITY = frozenset({
    "CONFIRMED_DOCUMENT_INTERNAL_PAGE_SEQUENCE",
    "VERIFIED_SAME_DOCUMENT_IDENTIFIER",
    "CONFIRMED_CROSS_PAGE_CONTENT",
    "VERIFIED_LOCAL_HEADER_FOOTER",
})
_STRONG_BOUNDARY = frozenset({
    "RECOVERED_DOCUMENT_ANCHOR",
    "VERIFIED_INDEPENDENT_DOCUMENT_START",
    "VERIFIED_DIFFERENT_DOCUMENT_IDENTIFIER",
    "CONFIRMED_INTERNAL_PAGE_RESTART",
})
_WEAK_BOUNDARY = frozenset({"NATIVE_OBSERVED_HEADING", "LAYOUT_CHANGE"})
_CONTEXT_ONLY = frozenset({
    "SAME_PROVIDER", "PACKAGE_PAGE_NUMBER_SEQUENCE", "WEAK_LAYOUT_SIMILARITY",
    "ABSENCE_OF_HEADING", "SAME_FALLBACK_ROUTE", "SIMILAR_OCR_CONFIDENCE",
    "COMMON_WATERMARK", "ADJACENT_TASK_IDS", "PHYSICAL_PAGE_ADJACENCY",
})
_KNOWN_KINDS = _STRONG_CONTINUITY | _STRONG_BOUNDARY | _WEAK_BOUNDARY | _CONTEXT_ONLY


@dataclass(frozen=True)
class PageRelationEvidence:
    kind: str
    left_page: int
    right_page: int
    refs: tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in _KNOWN_KINDS:
            raise ValueError(f"unsupported page relation evidence: {self.kind}")
        if self.right_page != self.left_page + 1:
            raise ValueError("page relation evidence requires adjacent pages")
        if not self.refs or any(not ref for ref in self.refs):
            raise ValueError("page relation evidence requires source refs")


@dataclass(frozen=True)
class PageRelationDecision:
    left_page: int
    right_page: int
    decision: str
    continuity_evidence: tuple[PageRelationEvidence, ...]
    boundary_evidence: tuple[PageRelationEvidence, ...]
    context_evidence: tuple[PageRelationEvidence, ...]
    conflicts: tuple[str, ...]
    reason: str
    evidence_refs: tuple[str, ...]


def decide_adjacent_page_relation(
    preview: ReconciledStructurePreview,
    left_page: int,
    right_page: int,
    *,
    corroborating_evidence: Iterable[PageRelationEvidence] = (),
) -> PageRelationDecision:
    """Classify one edge from explicit, traceable evidence only.

    External CONFIRMED / VERIFIED categories must already have been checked
    against their source; package-level numbering and provider identity cannot
    be promoted by this function. A section heading alone is not a document
    boundary. An accepted document anchor is a boundary cue, not page ownership.
    """
    if right_page != left_page + 1:
        raise ValueError("page relation decision requires adjacent pages")
    pages = {int(page["page_number"]) for page in preview.native_pages}
    if left_page not in pages or right_page not in pages:
        raise ValueError("both pages must exist in the Native preview")

    evidence: list[PageRelationEvidence] = []
    for anchor in preview.recovered_anchors:
        if isinstance(anchor, RecoveredDocumentAnchor) and anchor.page_number == right_page:
            evidence.append(PageRelationEvidence(
                kind="RECOVERED_DOCUMENT_ANCHOR", left_page=left_page,
                right_page=right_page,
                refs=(anchor.anchor_id, anchor.proposal_id, *anchor.candidate_refs),
                detail="accepted recovered document boundary anchor on right page",
            ))
    for section in preview.native_sections:
        if int(section.get("anchor_page") or 0) == right_page:
            evidence.append(PageRelationEvidence(
                kind="NATIVE_OBSERVED_HEADING", left_page=left_page,
                right_page=right_page, refs=(str(section["section_id"]),),
                detail=str(section.get("title") or "observed Native heading"),
            ))
    for item in corroborating_evidence:
        if (item.left_page, item.right_page) != (left_page, right_page):
            raise ValueError("corroborating evidence belongs to another edge")
        evidence.append(item)

    continuity = tuple(item for item in evidence if item.kind in _STRONG_CONTINUITY)
    boundary = tuple(item for item in evidence if item.kind in _STRONG_BOUNDARY | _WEAK_BOUNDARY)
    context = tuple(item for item in evidence if item.kind in _CONTEXT_ONLY)
    strong_boundary = tuple(item for item in boundary if item.kind in _STRONG_BOUNDARY)
    if continuity and strong_boundary:
        decision, reason = "CONFLICT", "opposed strong continuity and boundary evidence"
    elif strong_boundary:
        decision, reason = "BOUNDARY", "strong document boundary evidence"
    elif continuity:
        decision, reason = "CONTINUITY", "positive confirmed document continuity evidence"
    else:
        decision, reason = "INSUFFICIENT", "no decisive document relation evidence"
    refs = tuple(dict.fromkeys(ref for item in evidence for ref in item.refs))
    conflicts = refs if decision == "CONFLICT" else ()
    return PageRelationDecision(
        left_page, right_page, decision, continuity, boundary, context,
        conflicts, reason, refs,
    )


def decide_page_relations(
    preview: ReconciledStructurePreview,
    *,
    corroborating_evidence: Iterable[PageRelationEvidence] = (),
) -> tuple[PageRelationDecision, ...]:
    """Classify existing adjacent pages; EOF never becomes a synthetic page."""
    evidence_by_edge: dict[tuple[int, int], list[PageRelationEvidence]] = {}
    for item in corroborating_evidence:
        evidence_by_edge.setdefault((item.left_page, item.right_page), []).append(item)
    pages = sorted({int(page["page_number"]) for page in preview.native_pages})
    return tuple(
        decide_adjacent_page_relation(
            preview, left, right,
            corroborating_evidence=evidence_by_edge.get((left, right), ()),
        )
        for left, right in zip(pages, pages[1:]) if right == left + 1
    )
