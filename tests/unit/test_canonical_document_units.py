"""Document units add structural metadata without claiming content ownership."""

from copy import deepcopy

import pytest

from pdffast.canonical.document_units import with_document_units, validate_document_units
from pdffast.structure_reconciliation.anchor_admission import DocumentAnchorAdmissionDecision
from pdffast.structure_reconciliation.coverage import DocumentCoverageResult
from pdffast.structure_reconciliation.document_units import DocumentUnit


def _doc() -> dict:
    return {
        "schema_version": "1.0", "page_count": 4,
        "sections": [{"section_id": "native-1", "title": "原文标题"}],
        "pages": [{"page_number": page} for page in range(1, 5)],
        "records": [{"record_id": "r1", "source_page": 2, "text": "原文"}],
        "fallback_overlays": {"page_fallbacks": [{"task_id": "t1"}],
                              "region_fallbacks": [], "inline_contexts": []},
    }


def _result(page: int, *, status: str = "RESOLVED", anchor_status: str = "ANCHOR_CONFIRMED",
            span: tuple[int, int] | None = None, title_parts: tuple[str, ...] = ("原始第一行", "原始第二行")) -> DocumentCoverageResult:
    page_range = span if span is not None else (page, page)
    unit = DocumentUnit(
        document_id=f"document:recovered:p{page:04d}", role="UNKNOWN", source="RECOVERED",
        anchor_ref=f"anchor:p{page}", anchor_page=page, title_parts=title_parts,
        evidence_refs=(f"candidate:p{page}:1", f"candidate:p{page}:2"),
        range_status=status, page_range=page_range, section_ids=(),
        anchor_status=anchor_status,
    )
    return DocumentCoverageResult(unit, "CLOSED", "CLOSED", "BOUNDARY", "BOUNDARY", (f"edge:p{page}",))


def _admission(page: int) -> DocumentAnchorAdmissionDecision:
    return DocumentAnchorAdmissionDecision(
        proposal_id=f"proposal:p{page}", page_number=page, anchor_ref=f"anchor:p{page}",
        status="ANCHOR_CONFIRMED", reason="coherent_visual_document_title",
        candidate_refs=(f"candidate:p{page}:1", f"candidate:p{page}:2"),
        evidence_refs=(f"proposal:p{page}", f"candidate:p{page}:1", f"candidate:p{page}:2", f"selected:p{page}"),
        bbox_coordinate_space="PROVIDER_INPUT_IMAGE", conflicts=(),
    )


def test_confirmed_document_unit_enters_canonical() -> None:
    doc = with_document_units(_doc(), (_result(2),), (_admission(2),))
    assert len(doc["document_units"]) == 1
    assert doc["document_units"][0]["anchor"]["page"] == 2


def test_proposed_document_unit_does_not_enter_canonical() -> None:
    doc = with_document_units(_doc(), (_result(2, anchor_status="PROPOSED"),), ())
    assert doc["document_units"] == []


def test_primary_placeholder_without_confirmation_is_not_published() -> None:
    primary = DocumentUnit(
        document_id="document:native:primary", role="PRIMARY", source="NATIVE",
        anchor_ref=None, anchor_page=None, title_parts=(), evidence_refs=(),
        range_status="UNRESOLVED", page_range=None, section_ids=(),
    )
    doc = with_document_units(_doc(), (DocumentCoverageResult(primary, "NOT_EVALUATED", "NOT_EVALUATED", "NO_ADMITTED_ANCHOR", "NO_ADMITTED_ANCHOR", ()),), ())
    assert doc["document_units"] == []


@pytest.mark.parametrize("status", ["PARTIAL", "RESOLVED"])
def test_coverage_status_is_preserved(status: str) -> None:
    item = with_document_units(_doc(), (_result(2, status=status),), (_admission(2),))["document_units"][0]
    assert item["range_status"] == status
    assert item["page_range"] == {"start_page": 2, "end_page": 2}


def test_title_parts_preserve_original_text() -> None:
    parts = ("陕西省教育厅服务地方专项计划项目", "合同书")
    item = with_document_units(_doc(), (_result(2, title_parts=parts),), (_admission(2),))["document_units"][0]
    assert item["anchor"]["title_parts"] == list(parts)


def test_canonical_document_unit_has_stable_id() -> None:
    first = with_document_units(_doc(), (_result(2),), (_admission(2),))
    second = with_document_units(_doc(), (_result(2),), (_admission(2),))
    assert first["document_units"][0]["document_id"] == second["document_units"][0]["document_id"]


def test_document_unit_does_not_assign_record_document_id() -> None:
    doc = with_document_units(_doc(), (_result(2),), (_admission(2),))
    assert "document_id" not in doc["records"][0]


def test_document_unit_does_not_assign_section_parent() -> None:
    doc = with_document_units(_doc(), (_result(2),), (_admission(2),))
    assert "document_id" not in doc["sections"][0]


@pytest.mark.parametrize("key", ["sections", "records", "fallback_overlays"])
def test_existing_content_fields_remain_unchanged(key: str) -> None:
    before = _doc()
    after = with_document_units(before, (_result(2),), (_admission(2),))
    assert after[key] == before[key]
    assert before == _doc()


def test_overlapping_ranges_are_schema_valid() -> None:
    doc = with_document_units(_doc(), (_result(2, span=(2, 3)), _result(3, span=(3, 4))), (_admission(2), _admission(3)))
    validate_document_units(doc)
    assert [item["page_range"] for item in doc["document_units"]] == [
        {"start_page": 2, "end_page": 3}, {"start_page": 3, "end_page": 4},
    ]


def test_canonical_schema_version_is_updated_correctly() -> None:
    doc = with_document_units(_doc(), (), ())
    assert doc["schema_version"] == "1.1"
    assert doc["document_units"] == []


def test_document_unit_keeps_proposal_candidate_and_provider_source_refs() -> None:
    item = with_document_units(_doc(), (_result(2),), (_admission(2),))["document_units"][0]
    assert item["anchor"]["anchor_ref"] == "anchor:p2"
    assert item["anchor"]["candidate_refs"] == ["candidate:p2:1", "candidate:p2:2"]
    assert "selected:p2" in item["anchor"]["evidence_refs"]
    assert item["anchor"]["bbox_coordinate_space"] == "PROVIDER_INPUT_IMAGE"
    assert item["coverage_evidence_refs"] == ["edge:p2"]


def test_input_canonical_is_not_mutated() -> None:
    original = _doc()
    before = deepcopy(original)
    with_document_units(original, (_result(2),), (_admission(2),))
    assert original == before
