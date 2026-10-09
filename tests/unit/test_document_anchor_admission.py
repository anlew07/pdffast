"""A proposed document anchor needs coherent, conflict-free source evidence."""

from copy import deepcopy
from dataclasses import replace

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.anchor_admission import admit_recovered_document_anchors
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.heading_candidates import RecoveredHeadingCandidate
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def _native(*owners: str | None) -> dict:
    return {
        "source_file": "fixture.pdf", "page_count": len(owners),
        "sections": [
            {"section_id": owner, "title": f"Native {owner}",
             "anchor_page": page, "start_page": page, "end_page": page}
            for page, owner in enumerate(owners, 1) if owner
        ],
        "pages": [
            {"page_number": page, "section_id": owner}
            for page, owner in enumerate(owners, 1)
        ],
        "unresolved_regions": [],
    }


def _candidate(page: int, text: str, top: float, *, confidence: float = .99) -> RecoveredHeadingCandidate:
    return RecoveredHeadingCandidate(
        page_number=page, text=text, task_id=f"task-p{page}",
        task_type="PAGE_FALLBACK", provider="fixture",
        evidence_kind="OCR_VISUAL_LINE", source_reference=f"raw-p{page}.json",
        prediction_reference=f"selected-p{page}.json",
        provider_confidence=confidence,
        raw_bbox={"x0": 200, "top": top, "x1": 800, "bottom": top + 40},
        bbox_coordinate_space="PROVIDER_INPUT_IMAGE", block_index=None,
        signals={"relative_line_height": 1.5,
                 "top_in_observed_ocr_extent": .04,
                 "center_offset_in_observed_ocr_extent": .03,
                 "observed_ocr_line_count": 30}, score=.65,
    )


def _composite(page: int, first: str = "教育厅项目", second: str = "合同书") -> tuple[RecoveredHeadingCandidate, ...]:
    return (_candidate(page, first, 100), _candidate(page, second, 165))


def _report(native: dict, candidates: tuple[RecoveredHeadingCandidate, ...]):
    flow = {"page_index": native["pages"]}
    proposals = adjudicate_recovered_heading_candidates(candidates, native_flow=flow).proposals
    preview = preview_reconciled_structure(native, proposals)
    return proposals, preview


def test_accepted_document_boundary_can_be_admitted() -> None:
    native = _native(None)
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    provisional = create_document_units(preview)[1]
    decisions = admit_recovered_document_anchors(preview, proposals, candidates)
    admitted = create_document_units(preview, admissions=decisions)[1]

    assert provisional.anchor_status == "PROPOSED"
    assert decisions[0].status == "ANCHOR_CONFIRMED"
    assert admitted.anchor_status == "ANCHOR_CONFIRMED"
    assert admitted.anchor_page == 1


def test_ambiguous_proposal_cannot_be_admitted() -> None:
    native = _native(None)
    candidates = (_candidate(1, "可能是标题", 100, confidence=.99999),)
    proposals, preview = _report(native, candidates)
    decisions = admit_recovered_document_anchors(preview, proposals, candidates)

    assert proposals[0].decision == "AMBIGUOUS"
    assert decisions[0].status == "NOT_ADMITTED"
    assert len(create_document_units(preview, admissions=decisions)) == 1


def test_accepted_non_document_role_cannot_be_admitted() -> None:
    native = _native(None)
    candidates = _composite(1)
    proposals, _ = _report(native, candidates)
    non_document = replace(proposals[0], suggested_role="SECTION_CANDIDATE")
    preview = preview_reconciled_structure(native, (non_document,))
    decisions = admit_recovered_document_anchors(preview, (non_document,), candidates)

    assert decisions[0].status == "NOT_ADMITTED"
    assert len(create_document_units(preview, admissions=decisions)) == 1


def test_native_conflict_blocks_admission() -> None:
    candidates = _composite(1)
    proposals, _ = _report(_native(None), candidates)
    preview = preview_reconciled_structure(_native("native-1"), proposals)
    decisions = admit_recovered_document_anchors(preview, proposals, candidates)

    assert decisions[0].status == "NOT_ADMITTED"
    assert "native_ownership_wins" in decisions[0].conflicts
    assert len(create_document_units(preview, admissions=decisions)) == 1


def test_provider_confidence_alone_cannot_admit() -> None:
    native = _native(None)
    candidates = (_candidate(1, "合同书", 100, confidence=1.0),)
    proposals, preview = _report(native, candidates)
    decisions = admit_recovered_document_anchors(preview, proposals, candidates)
    assert decisions[0].status == "NOT_ADMITTED"


def test_accepted_proposal_without_coherent_candidate_geometry_cannot_admit() -> None:
    native = _native(None)
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    displaced = replace(candidates[1], raw_bbox={
        "x0": 200, "top": 600, "x1": 800, "bottom": 640,
    })
    decision = admit_recovered_document_anchors(preview, proposals, (candidates[0], displaced))[0]
    assert proposals[0].decision == "ACCEPTED_PROPOSAL"
    assert decision.status == "NOT_ADMITTED"
    assert decision.reason == "coherent_title_evidence_missing"
    assert create_document_units(preview, admissions=(decision,))[1].anchor_status == "PROPOSED"


def test_composite_title_preserves_candidate_refs_and_image_coordinates() -> None:
    native = _native(None)
    candidates = _composite(1, "陕西省教育厅服务地方专项计划项目", "合同书")
    proposals, preview = _report(native, candidates)
    decision = admit_recovered_document_anchors(preview, proposals, candidates)[0]

    assert decision.status == "ANCHOR_CONFIRMED"
    assert decision.candidate_refs == proposals[0].candidate_refs
    assert len(decision.candidate_refs) == 2
    assert decision.bbox_coordinate_space == "PROVIDER_INPUT_IMAGE"
    assert "selected-p1.json" in decision.evidence_refs
    assert "raw-p1.json" in decision.evidence_refs


def test_admitted_anchor_confirms_intersection_not_whole_page() -> None:
    native = _native(None)
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    admitted = create_document_units(
        preview, admissions=admit_recovered_document_anchors(preview, proposals, candidates)
    )[1]
    assert admitted.anchor_status == "ANCHOR_CONFIRMED"
    assert admitted.anchor_page == 1
    assert admitted.page_range is None
    assert not hasattr(admitted, "owned_pages")


def test_admission_does_not_create_page_range() -> None:
    native = _native(None)
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    admitted = create_document_units(
        preview, admissions=admit_recovered_document_anchors(preview, proposals, candidates)
    )[1]
    assert admitted.range_status == "UNRESOLVED"
    assert admitted.page_range is None


def test_admission_does_not_assign_record_ownership() -> None:
    native = _native(None)
    native["records"] = [{"record_id": "r1", "source_page": 1}]
    before = deepcopy(native)
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    create_document_units(preview, admissions=admit_recovered_document_anchors(preview, proposals, candidates))
    assert native == before
    assert "document_id" not in native["records"][0]


def test_admission_does_not_assign_section_parent() -> None:
    native = _native(None, "native-2")
    candidates = _composite(1)
    proposals, preview = _report(native, candidates)
    units = create_document_units(
        preview, admissions=admit_recovered_document_anchors(preview, proposals, candidates)
    )
    assert section_parent_map(units) == {}
    assert all(unit.section_ids == () for unit in units)


def test_same_title_different_pages_remain_distinct() -> None:
    native = _native(None, None)
    candidates = (*_composite(1), *_composite(2))
    proposals, preview = _report(native, candidates)
    decisions = admit_recovered_document_anchors(preview, proposals, candidates)
    units = create_document_units(preview, admissions=decisions)

    assert [decision.status for decision in decisions] == ["ANCHOR_CONFIRMED"] * 2
    assert [unit.anchor_page for unit in units[1:]] == [1, 2]
    assert units[1].title_parts == units[2].title_parts
    assert units[1].document_id != units[2].document_id
