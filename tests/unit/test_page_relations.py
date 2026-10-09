"""Adjacent page evidence must not imply document, section, or record ownership."""

from copy import deepcopy

import pytest

from pdffast.structure_reconciliation.adjudication import RecoveredSectionProposal
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.page_relations import (
    PageRelationEvidence,
    decide_adjacent_page_relation,
    decide_page_relations,
)
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def _native(*section_ids: str | None) -> dict:
    return {
        "source_file": "fixture.pdf",
        "page_count": len(section_ids),
        "sections": [
            {"section_id": section_id, "title": f"Observed {section_id}",
             "anchor_page": page, "start_page": page, "end_page": page,
             "structure_evidence": "observed_native_top_level_heading"}
            for page, section_id in enumerate(section_ids, 1) if section_id
        ],
        "pages": [
            {"page_number": page, "section_id": section_id}
            for page, section_id in enumerate(section_ids, 1)
        ],
        "unresolved_regions": [],
    }


def _anchor(page: int, *, proposal_id: str | None = None) -> RecoveredSectionProposal:
    return RecoveredSectionProposal(
        proposal_id=proposal_id or f"proposal-p{page}", page_number=page,
        title_parts=(f"Document {page}",), candidate_refs=(f"candidate-p{page}",),
        suggested_role="DOCUMENT_BOUNDARY_CANDIDATE",
        evidence_kinds=("OCR_VISUAL_LINE",), providers=("fixture",),
        task_ids=(f"task-p{page}",), signals={}, conflicts=(),
        structure_strength="STRONG", decision="ACCEPTED_PROPOSAL", reason="fixture",
    )


def _evidence(kind: str, *, left: int = 1, right: int = 2) -> PageRelationEvidence:
    return PageRelationEvidence(
        kind=kind, left_page=left, right_page=right,
        refs=(f"verified:{kind}:{left}-{right}",), detail="fixture evidence",
    )


def test_adjacent_recovered_anchors_create_boundary() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), (_anchor(2), _anchor(3)))
    decision = decide_adjacent_page_relation(preview, 2, 3)
    assert decision.decision == "BOUNDARY"
    assert "recovered-anchor:proposal-p3" in decision.evidence_refs
    assert "proposal-p3" in decision.evidence_refs
    assert "candidate-p3" in decision.evidence_refs


def test_native_heading_can_supply_boundary_evidence() -> None:
    preview = preview_reconciled_structure(_native(None, "native-2"), ())
    decision = decide_adjacent_page_relation(preview, 1, 2)
    assert [item.kind for item in decision.boundary_evidence] == ["NATIVE_OBSERVED_HEADING"]
    assert "native-2" in decision.evidence_refs
    assert decision.decision == "INSUFFICIENT"


def test_absence_of_heading_is_not_continuity() -> None:
    decision = decide_adjacent_page_relation(preview_reconciled_structure(_native(None, None), ()), 1, 2)
    assert decision.decision == "INSUFFICIENT"
    assert decision.continuity_evidence == ()


def test_same_provider_is_not_continuity() -> None:
    preview = preview_reconciled_structure(_native(None, None), ())
    decision = decide_adjacent_page_relation(
        preview, 1, 2, corroborating_evidence=(_evidence("SAME_PROVIDER"),),
    )
    assert decision.decision == "INSUFFICIENT"
    assert decision.continuity_evidence == ()


def test_package_level_page_number_is_not_continuity() -> None:
    preview = preview_reconciled_structure(_native(None, None), ())
    decision = decide_adjacent_page_relation(
        preview, 1, 2, corroborating_evidence=(_evidence("PACKAGE_PAGE_NUMBER_SEQUENCE"),),
    )
    assert decision.decision == "INSUFFICIENT"


def test_confirmed_internal_page_sequence_can_support_continuity() -> None:
    preview = preview_reconciled_structure(_native(None, None), ())
    decision = decide_adjacent_page_relation(
        preview, 1, 2,
        corroborating_evidence=(_evidence("CONFIRMED_DOCUMENT_INTERNAL_PAGE_SEQUENCE"),),
    )
    assert decision.decision == "CONTINUITY"
    assert [item.kind for item in decision.continuity_evidence] == [
        "CONFIRMED_DOCUMENT_INTERNAL_PAGE_SEQUENCE"
    ]


def test_weak_layout_similarity_returns_insufficient() -> None:
    preview = preview_reconciled_structure(_native(None, None), ())
    decision = decide_adjacent_page_relation(
        preview, 1, 2, corroborating_evidence=(_evidence("WEAK_LAYOUT_SIMILARITY"),),
    )
    assert decision.decision == "INSUFFICIENT"


def test_strong_boundary_and_continuity_returns_conflict() -> None:
    preview = preview_reconciled_structure(_native(None, None), (_anchor(2),))
    decision = decide_adjacent_page_relation(
        preview, 1, 2,
        corroborating_evidence=(_evidence("CONFIRMED_DOCUMENT_INTERNAL_PAGE_SEQUENCE"),),
    )
    assert decision.decision == "CONFLICT"
    assert decision.continuity_evidence and decision.boundary_evidence
    assert decision.conflicts


def test_edge_decision_does_not_create_document_range() -> None:
    preview = preview_reconciled_structure(_native(None, None), (_anchor(2),))
    units_before = create_document_units(preview)
    decide_adjacent_page_relation(preview, 1, 2)
    assert create_document_units(preview) == units_before
    assert all(unit.page_range is None and unit.range_status == "UNRESOLVED" for unit in units_before)


def test_edge_decision_does_not_assign_record_ownership() -> None:
    native = _native(None, None)
    native["records"] = [{"record_id": "r1", "source_page": 2}]
    before = deepcopy(native)
    preview = preview_reconciled_structure(native, (_anchor(2),))
    decide_adjacent_page_relation(preview, 1, 2)
    assert native == before
    assert "document_id" not in native["records"][0]


def test_edge_decision_does_not_assign_section_parent() -> None:
    preview = preview_reconciled_structure(_native(None, "native-2"), ())
    units = create_document_units(preview)
    decide_adjacent_page_relation(preview, 1, 2)
    assert units[0].section_ids == ()
    assert section_parent_map(units) == {}


def test_decision_preserves_evidence_refs() -> None:
    preview = preview_reconciled_structure(_native(None, None), (_anchor(2),))
    decision = decide_adjacent_page_relation(preview, 1, 2)
    assert decision.boundary_evidence[0].refs == (
        "recovered-anchor:proposal-p2", "proposal-p2", "candidate-p2",
    )


def test_all_page_edges_are_evaluated_without_eof_edge() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), (_anchor(3),))
    decisions = decide_page_relations(preview)
    assert [(item.left_page, item.right_page, item.decision) for item in decisions] == [
        (1, 2, "INSUFFICIENT"), (2, 3, "BOUNDARY"),
    ]


def test_non_adjacent_pages_are_rejected() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), ())
    with pytest.raises(ValueError, match="adjacent"):
        decide_adjacent_page_relation(preview, 1, 3)
