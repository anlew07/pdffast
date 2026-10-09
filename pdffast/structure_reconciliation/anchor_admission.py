"""Confirm a recovered document title region without assigning page ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .adjudication import RecoveredSectionProposal
from .heading_candidates import RecoveredHeadingCandidate
from .preview import ReconciledStructurePreview, RecoveredDocumentAnchor


@dataclass(frozen=True)
class DocumentAnchorAdmissionDecision:
    proposal_id: str
    page_number: int
    anchor_ref: str | None
    status: str
    reason: str
    candidate_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    bbox_coordinate_space: str | None
    conflicts: tuple[str, ...]


def _candidate_ref(index: int, candidate: RecoveredHeadingCandidate) -> str:
    # E4C assigns refs by input order. Admission only resolves those refs;
    # it does not rerun heading detection or proposal grouping.
    return f"p{candidate.page_number:04d}:{candidate.task_id}:{index:04d}"


def _coherent_visual_title(
    proposal: RecoveredSectionProposal,
    candidates_by_ref: Mapping[str, RecoveredHeadingCandidate],
) -> tuple[RecoveredHeadingCandidate, ...] | None:
    refs = proposal.candidate_refs
    if (proposal.structure_strength != "STRONG"
            or proposal.reason != "adjacent_visual_title_lines"
            or len(refs) < 2
            or len(set(refs)) != len(refs)
            or proposal.signals.get("candidate_count") != len(refs)
            or len(proposal.title_parts) != len(refs)):
        return None
    matched = tuple(candidates_by_ref.get(ref) for ref in refs)
    if any(item is None for item in matched):
        return None
    candidates = tuple(item for item in matched if item is not None)
    if (len({item.task_id for item in candidates}) != 1
            or proposal.task_ids != (candidates[0].task_id,)
            or len({item.prediction_reference for item in candidates}) != 1
            or not candidates[0].prediction_reference
            or tuple(item.text for item in candidates) != proposal.title_parts):
        return None
    boxes = []
    for item in candidates:
        if (item.page_number != proposal.page_number
                or item.task_type != "PAGE_FALLBACK"
                or item.evidence_kind != "OCR_VISUAL_LINE"
                or item.bbox_coordinate_space != "PROVIDER_INPUT_IMAGE"
                or not isinstance(item.raw_bbox, Mapping)):
            return None
        try:
            box = {key: float(item.raw_bbox[key]) for key in ("x0", "top", "x1", "bottom")}
        except (KeyError, TypeError, ValueError):
            return None
        if box["x1"] <= box["x0"] or box["bottom"] <= box["top"]:
            return None
        boxes.append(box)
    for left, right in zip(boxes, boxes[1:]):
        if right["top"] <= left["top"]:
            return None
        min_height = min(left["bottom"] - left["top"], right["bottom"] - right["top"])
        gap = right["top"] - left["bottom"]
        if not (-.15 * min_height <= gap <= 1.5 * min_height):
            return None
    return candidates


def admit_recovered_document_anchors(
    preview: ReconciledStructurePreview,
    proposals: Iterable[RecoveredSectionProposal],
    candidates: Iterable[RecoveredHeadingCandidate],
) -> tuple[DocumentAnchorAdmissionDecision, ...]:
    """Admit only an unopposed, coherent document title group on its own page."""
    candidates_by_ref = {
        _candidate_ref(index, item): item for index, item in enumerate(candidates)
    }
    anchors = {
        anchor.proposal_id: anchor for anchor in preview.recovered_anchors
        if isinstance(anchor, RecoveredDocumentAnchor)
    }
    native_owner = {
        int(page["page_number"]): page.get("section_id")
        for page in preview.native_pages
    }
    decisions = []
    for proposal in proposals:
        anchor = anchors.get(proposal.proposal_id)
        conflicts = tuple(dict.fromkeys((
            *proposal.conflicts,
            *(conflict.reason for conflict in preview.conflicts
              if proposal.proposal_id in conflict.proposal_ids
              or conflict.page_number == proposal.page_number),
        )))
        matched = None
        if proposal.decision != "ACCEPTED_PROPOSAL":
            reason = "proposal_not_accepted"
        elif proposal.suggested_role != "DOCUMENT_BOUNDARY_CANDIDATE":
            reason = "not_document_boundary_candidate"
        elif native_owner.get(proposal.page_number) is not None or conflicts:
            reason = "native_or_proposal_conflict"
        elif (anchor is None or anchor.page_number != proposal.page_number
              or anchor.candidate_refs != proposal.candidate_refs
              or anchor.original_text_parts != proposal.title_parts):
            reason = "unopposed_document_preview_anchor_missing"
        else:
            matched = _coherent_visual_title(proposal, candidates_by_ref)
            reason = "coherent_visual_document_title" if matched else "coherent_title_evidence_missing"
        admitted = matched is not None
        refs = tuple(dict.fromkeys((
            *((anchor.anchor_id,) if admitted and anchor is not None else ()),
            proposal.proposal_id, *proposal.candidate_refs,
            *(ref for item in (matched or ())
              for ref in (item.prediction_reference, item.source_reference) if ref),
        )))
        decisions.append(DocumentAnchorAdmissionDecision(
            proposal_id=proposal.proposal_id, page_number=proposal.page_number,
            anchor_ref=anchor.anchor_id if admitted and anchor is not None else None,
            status="ANCHOR_CONFIRMED" if admitted else "NOT_ADMITTED",
            reason=reason, candidate_refs=proposal.candidate_refs,
            evidence_refs=refs,
            bbox_coordinate_space="PROVIDER_INPUT_IMAGE" if admitted else None,
            conflicts=conflicts,
        ))
    return tuple(decisions)
