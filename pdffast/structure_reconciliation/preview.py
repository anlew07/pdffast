"""Read-only view of Native sections alongside accepted recovered anchors.

An anchor marks one page only. It does not own that page or any later page,
and this module does not write Canonical or Stage artifacts.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .adjudication import RecoveredSectionProposal


@dataclass(frozen=True)
class RecoveredStructureAnchor:
    anchor_id: str
    page_number: int
    original_text_parts: tuple[str, ...]
    source: str
    proposal_id: str
    candidate_refs: tuple[str, ...]
    suggested_role: str
    anchor_kind: str
    range_status: str
    page_range: None


@dataclass(frozen=True)
class RecoveredDocumentAnchor(RecoveredStructureAnchor):
    """A possible subdocument boundary, never an implied section."""


@dataclass(frozen=True)
class RecoveredSectionAnchor(RecoveredStructureAnchor):
    """A possible section heading without page ownership or range."""


@dataclass(frozen=True)
class StructurePreviewConflict:
    proposal_ids: tuple[str, ...]
    page_number: int | None
    reason: str
    native_section_id: str | None = None


@dataclass(frozen=True)
class IgnoredStructureProposal:
    proposal_id: str
    page_number: int
    decision: str
    reason: str


@dataclass(frozen=True)
class ReconciledStructurePreview:
    native_sections: tuple[dict[str, Any], ...]
    native_pages: tuple[dict[str, Any], ...]
    unresolved_regions: tuple[dict[str, Any], ...]
    recovered_anchors: tuple[RecoveredStructureAnchor, ...]
    conflicts: tuple[StructurePreviewConflict, ...]
    ignored_proposals: tuple[IgnoredStructureProposal, ...]
    unresolved_pages_without_anchor: tuple[int, ...]
    provenance: dict[str, Any]


_ANCHOR_ROLES = {
    "DOCUMENT_BOUNDARY_CANDIDATE": "recovered_document_anchor",
    "SECTION_CANDIDATE": "recovered_section_anchor",
}


def preview_reconciled_structure(
    native_structure: Mapping[str, Any],
    proposals: Iterable[RecoveredSectionProposal],
) -> ReconciledStructurePreview:
    """Preserve Native structure and preview only unopposed accepted anchors."""
    native_sections = tuple(deepcopy(item) for item in native_structure.get("sections", []))
    native_pages = tuple(deepcopy(item) for item in native_structure.get("pages", []))
    unresolved_regions = tuple(deepcopy(item) for item in native_structure.get("unresolved_regions", []))
    ownership = {int(page["page_number"]): page.get("section_id") for page in native_pages}
    all_proposals = tuple(proposals)
    anchors: list[RecoveredStructureAnchor] = []
    conflicts: list[StructurePreviewConflict] = []
    ignored: list[IgnoredStructureProposal] = []
    eligible_by_page: dict[int, list[RecoveredSectionProposal]] = defaultdict(list)

    for proposal in all_proposals:
        if proposal.decision != "ACCEPTED_PROPOSAL":
            ignored.append(IgnoredStructureProposal(
                proposal.proposal_id, proposal.page_number, proposal.decision,
                "proposal_not_accepted",
            ))
            continue
        page = proposal.page_number
        if page not in ownership:
            ignored.append(IgnoredStructureProposal(
                proposal.proposal_id, page, proposal.decision, "native_page_missing",
            ))
            continue
        owner = ownership[page]
        if owner is not None:
            conflicts.append(StructurePreviewConflict(
                (proposal.proposal_id,), page, "native_ownership_wins", str(owner),
            ))
            ignored.append(IgnoredStructureProposal(
                proposal.proposal_id, page, proposal.decision, "native_ownership_wins",
            ))
            continue
        if proposal.conflicts:
            conflicts.append(StructurePreviewConflict(
                (proposal.proposal_id,), page, "proposal_evidence_conflict",
            ))
            ignored.append(IgnoredStructureProposal(
                proposal.proposal_id, page, proposal.decision, "proposal_evidence_conflict",
            ))
            continue
        if proposal.suggested_role not in _ANCHOR_ROLES:
            ignored.append(IgnoredStructureProposal(
                proposal.proposal_id, page, proposal.decision, "role_not_anchor",
            ))
            continue
        eligible_by_page[page].append(proposal)

    competing_ids: set[str] = set()
    for page, items in sorted(eligible_by_page.items()):
        if len(items) > 1:
            ids = tuple(item.proposal_id for item in items)
            conflicts.append(StructurePreviewConflict(
                ids, page, "competing_accepted_proposals_same_page",
            ))
            competing_ids.update(ids)

    eligible = [item for items in eligible_by_page.values() for item in items]
    ref_to_proposals: dict[str, set[str]] = defaultdict(set)
    for proposal in eligible:
        for ref in proposal.candidate_refs:
            ref_to_proposals[ref].add(proposal.proposal_id)
    duplicated = {ref: ids for ref, ids in ref_to_proposals.items() if len(ids) > 1}
    for ref, ids in sorted(duplicated.items()):
        ordered_ids = tuple(item.proposal_id for item in eligible if item.proposal_id in ids)
        conflicts.append(StructurePreviewConflict(
            ordered_ids, None, "competing_accepted_proposals_same_evidence",
        ))
        competing_ids.update(ids)

    # Proposal identity must not be reused for two anchors, even if their text
    # and page differ. Titles themselves are deliberately not deduplicated.
    repeated_ids = {proposal_id for proposal_id, count in Counter(
        item.proposal_id for item in eligible
    ).items() if count > 1}
    for proposal_id in sorted(repeated_ids):
        conflicts.append(StructurePreviewConflict(
            (proposal_id,), None, "duplicate_proposal_id",
        ))
        competing_ids.add(proposal_id)

    for item in sorted(eligible, key=lambda value: (value.page_number, value.proposal_id)):
        if item.proposal_id in competing_ids:
            ignored.append(IgnoredStructureProposal(
                item.proposal_id, item.page_number, item.decision, "recovered_proposal_conflict",
            ))
            continue
        anchor_type = (RecoveredDocumentAnchor if item.suggested_role == "DOCUMENT_BOUNDARY_CANDIDATE"
                       else RecoveredSectionAnchor)
        anchors.append(anchor_type(
            anchor_id=f"recovered-anchor:{item.proposal_id}",
            page_number=item.page_number,
            original_text_parts=tuple(item.title_parts),
            source="RECOVERED", proposal_id=item.proposal_id,
            candidate_refs=tuple(item.candidate_refs),
            suggested_role=item.suggested_role,
            anchor_kind=_ANCHOR_ROLES[item.suggested_role],
            range_status="UNRESOLVED", page_range=None,
        ))

    anchor_pages = {anchor.page_number for anchor in anchors}
    remaining = tuple(sorted(page for page, owner in ownership.items()
                             if owner is None and page not in anchor_pages))
    return ReconciledStructurePreview(
        native_sections=native_sections, native_pages=native_pages,
        unresolved_regions=unresolved_regions,
        recovered_anchors=tuple(anchors), conflicts=tuple(conflicts),
        ignored_proposals=tuple(ignored),
        unresolved_pages_without_anchor=remaining,
        provenance={
            "source_file": native_structure.get("source_file"),
            "native_section_count": len(native_sections),
            "input_proposal_count": len(all_proposals),
            "range_resolution_performed": False,
        },
    )
