"""Characterize document evidence, page coverage, and ownership as distinct facts."""

from copy import deepcopy
from dataclasses import replace

from pdffast.structure_reconciliation.adjudication import RecoveredSectionProposal
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.page_relations import decide_adjacent_page_relation
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def _native(*section_ids: str | None) -> dict:
    return {
        "source_file": "fixture.pdf", "page_count": len(section_ids),
        "sections": [
            {"section_id": section_id, "title": f"Observed {section_id}",
             "anchor_page": page, "start_page": page, "end_page": page}
            for page, section_id in enumerate(section_ids, 1) if section_id
        ],
        "pages": [
            {"page_number": page, "section_id": section_id}
            for page, section_id in enumerate(section_ids, 1)
        ],
        "unresolved_regions": [],
    }


def _proposal(page: int) -> RecoveredSectionProposal:
    return RecoveredSectionProposal(
        proposal_id=f"proposal-p{page}", page_number=page,
        title_parts=(f"Document title on p{page}",),
        candidate_refs=(f"candidate-p{page}",),
        suggested_role="DOCUMENT_BOUNDARY_CANDIDATE",
        evidence_kinds=("OCR_VISUAL_LINE",), providers=("fixture",),
        task_ids=(f"task-p{page}",), signals={}, conflicts=(),
        structure_strength="STRONG", decision="ACCEPTED_PROPOSAL", reason="fixture",
    )


def test_document_anchor_confirms_anchor_evidence_not_whole_page_ownership() -> None:
    native = _native(None, None)
    native["records"] = [
        {"record_id": "before-title", "source_page": 2},
        {"record_id": "after-title", "source_page": 2},
    ]
    before = deepcopy(native)
    preview = preview_reconciled_structure(native, (_proposal(2),))
    unit = create_document_units(preview)[1]

    assert unit.anchor_page == 2
    assert unit.anchor_ref == "recovered-anchor:proposal-p2"
    assert unit.title_parts == ("Document title on p2",)
    assert unit.evidence_refs == ("candidate-p2",)
    assert unit.page_range is None
    assert native == before
    assert all("document_id" not in record for record in native["records"])


def test_page_range_does_not_imply_all_records_owned() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), (_proposal(2),))
    unit = replace(create_document_units(preview)[1], range_status="RESOLVED", page_range=(2, 3))
    records = [
        {"record_id": "shared-page-other-document", "source_page": 2},
        {"record_id": "this-document", "source_page": 2},
        {"record_id": "unknown", "source_page": 3},
    ]

    assert unit.page_range == (2, 3)
    assert all("document_id" not in record for record in records)


def test_document_ranges_are_not_semantically_required_to_be_exclusive() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), (_proposal(2), _proposal(3)))
    primary, first, second = create_document_units(preview)
    first = replace(first, range_status="RESOLVED", page_range=(1, 2))
    second = replace(second, range_status="RESOLVED", page_range=(2, 3))

    assert first.page_range == (1, 2)
    assert second.page_range == (2, 3)
    assert section_parent_map((primary, first, second)) == {}


def test_boundary_edge_does_not_assign_whole_page() -> None:
    preview = preview_reconciled_structure(_native(None, None, None), (_proposal(2), _proposal(3)))
    decision = decide_adjacent_page_relation(preview, 2, 3)
    units = create_document_units(preview)

    assert decision.decision == "BOUNDARY"
    assert units[1].anchor_page == 2
    assert units[1].page_range is None
    assert units[1].range_status == "UNRESOLVED"


def test_anchor_page_can_be_known_while_range_unresolved() -> None:
    preview = preview_reconciled_structure(_native(None, None), (_proposal(2),))
    unit = create_document_units(preview)[1]
    assert unit.anchor_page == 2
    assert unit.range_status == "UNRESOLVED"
    assert unit.page_range is None


def test_record_ownership_remains_independent() -> None:
    preview = preview_reconciled_structure(_native(None, None), (_proposal(2),))
    unit = replace(create_document_units(preview)[1], range_status="RESOLVED", page_range=(2, 2))
    records = [
        {"record_id": "r1", "source_page": 2, "document_id": "another-document"},
        {"record_id": "r2", "source_page": 2},
    ]
    before = deepcopy(records)

    assert unit.page_range == (2, 2)
    assert records == before
    assert records[0]["document_id"] != unit.document_id
    assert "document_id" not in records[1]


def test_section_parent_remains_independent() -> None:
    native = _native(None, "native-2")
    preview = preview_reconciled_structure(native, ())
    primary = replace(create_document_units(preview)[0], range_status="RESOLVED", page_range=(1, 2))

    assert native["sections"][0]["section_id"] == "native-2"
    assert primary.page_range == (1, 2)
    assert primary.section_ids == ()
    assert section_parent_map((primary,)) == {}
