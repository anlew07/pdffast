"""DocumentUnit audit checks the published metadata and rendered text together."""

from copy import deepcopy

import pytest

from pdffast.audit.document_units import audit_document_units
from pdffast.render.llm_ready import build_rendered_document


def _unit(document_id: str = "document:p2", *, page: int = 2, status: str = "PARTIAL",
          title: tuple[str, ...] = ("原文标题甲", "原文标题乙"),
          span: tuple[int, int] | None = None) -> dict:
    start, end = span or (page, page)
    task_id = f"task-{document_id.replace(':', '-')}"
    candidate = f"p{page:04d}:{task_id}:0001"
    anchor_ref = f"recovered-anchor:proposal-{document_id}"
    return {
        "document_id": document_id, "source": "RECOVERED", "role": "UNKNOWN",
        "anchor": {"page": page, "title_parts": list(title), "anchor_ref": anchor_ref,
                   "candidate_refs": [candidate],
                   "evidence_refs": [anchor_ref, f"proposal-{document_id}", candidate,
                                     f"selected_predictions/{task_id}.json"],
                   "bbox_coordinate_space": "PROVIDER_INPUT_IMAGE"},
        "anchor_status": "ANCHOR_CONFIRMED", "range_status": status,
        "page_range": {"start_page": start, "end_page": end},
        "coverage_evidence_refs": [],
    }


def _doc(*units: dict) -> dict:
    return {
        "stage": 10, "substage": "10.1", "schema_version": "1.1",
        "status": "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING", "page_count": 3,
        "sections": [{"section_id": "s1", "section_title": "一、原生章节", "page_numbers": [1, 2, 3],
                      "record_ids": ["r1", "r2", "r3"]}],
        "records": [
            {"record_id": "r1", "record_type": "paragraph", "source_page": 1, "text": "第一段"},
            {"record_id": "r2", "record_type": "paragraph", "source_page": 2, "text": "第二段"},
            {"record_id": "r3", "record_type": "paragraph", "source_page": 3, "text": "第三段"},
        ],
        "fallback_overlays": {"page_fallbacks": [], "region_fallbacks": [], "inline_contexts": []},
        "summary": {"native_record_count": 3}, "document_units": list(units),
    }


def _result(doc: dict, markdown: str | None = None) -> dict:
    if markdown is None:
        markdown, _ = build_rendered_document(doc)
    return audit_document_units(doc, markdown)


def test_canonical_unit_has_exactly_one_marker_and_traceable_provenance() -> None:
    result = _result(_doc(_unit()))
    assert result["status"] == "PASS"
    assert result["units"] == result["rendered_markers"] == result["provenance_checked"] == 1
    assert result["body_unchanged"] is True


def test_missing_marker_fails_audit() -> None:
    doc = _doc(_unit())
    markdown, _ = build_rendered_document(_doc())
    assert _result(doc, markdown)["status"] == "FAIL"


def test_duplicate_marker_fails_audit() -> None:
    doc = _doc(_unit())
    markdown, _ = build_rendered_document(doc)
    marker = markdown[markdown.index("<!-- pdffast-document-unit:"):markdown.index("【PDFFast文档边界结束】") + len("【PDFFast文档边界结束】")]
    assert _result(doc, markdown + "\n" + marker + "\n")["status"] == "FAIL"


@pytest.mark.parametrize("change", [
    ("完整范围未确定", "完整范围已确定"),
    ("2–2页", "2–3页"),
])
def test_partial_marker_preserves_uncertainty(change: tuple[str, str]) -> None:
    doc = _doc(_unit())
    markdown, _ = build_rendered_document(doc)
    old, new = change
    assert _result(doc, markdown.replace(old, new, 1))["status"] == "FAIL"


def test_resolved_marker_matches_canonical_range_without_exclusive_claim() -> None:
    doc = _doc(_unit(status="RESOLVED"))
    markdown, _ = build_rendered_document(doc)
    assert _result(doc)["status"] == "PASS"
    assert _result(doc, markdown.replace("（非独占）", "（整页独占）", 1))["status"] == "FAIL"


def test_title_parts_match_exactly_and_in_order() -> None:
    doc = _doc(_unit())
    markdown, _ = build_rendered_document(doc)
    assert _result(doc, markdown.replace("标题原文 2：原文标题乙", "标题原文 2：改写标题", 1))["status"] == "FAIL"
    assert _result(doc, markdown.replace("标题原文 1：原文标题甲\n标题原文 2：原文标题乙",
                                         "标题原文 1：原文标题乙\n标题原文 2：原文标题甲", 1))["status"] == "FAIL"


def test_duplicate_titles_and_overlapping_ranges_are_allowed() -> None:
    doc = _doc(_unit("document:a", page=2, span=(2, 3), title=("同名标题",)),
               _unit("document:b", page=3, span=(3, 3), title=("同名标题",)))
    result = _result(doc)
    assert result["status"] == "PASS"
    assert result["rendered_markers"] == 2


@pytest.mark.parametrize("location", ["records", "sections"])
def test_document_ownership_is_not_inferred(location: str) -> None:
    doc = _doc(_unit())
    doc[location][0]["document_id"] = "document:p2"
    assert _result(doc)["status"] == "FAIL"


def test_document_unit_is_not_section_heading() -> None:
    doc = _doc(_unit())
    markdown, _ = build_rendered_document(doc)
    assert _result(doc, markdown.replace("标题原文 1：原文标题甲", "# 原文标题甲", 1))["status"] == "FAIL"


def test_broken_evidence_chain_fails_audit() -> None:
    doc = _doc(_unit())
    doc["document_units"][0]["anchor"]["evidence_refs"] = ["unrelated-ref"]
    assert _result(doc)["status"] == "FAIL"


def test_base_record_content_cannot_change_outside_marker() -> None:
    doc = _doc(_unit())
    before = deepcopy(doc)
    markdown, _ = build_rendered_document(doc)
    assert _result(doc, markdown.replace("第二段", "篡改正文", 1))["status"] == "FAIL"
    assert doc == before


def test_fallback_content_cannot_change_outside_marker() -> None:
    doc = _doc(_unit())
    doc["records"][1] = {
        "record_id": "r2", "record_type": "image_ref", "source_page": 2,
        "stage10_resolution": {"mode": "PAGE_FALLBACK_SOURCE", "fallback_task_ids": ["task-p2"]},
    }
    doc["fallback_overlays"]["page_fallbacks"] = [{
        "task_id": "task-p2", "page_number": 2,
        "fallback_content": {"text": {"availability": "AVAILABLE", "content": "OCR原文内容"}},
    }]
    doc["summary"]["page_fallback_count"] = 1
    markdown, _ = build_rendered_document(doc)
    assert _result(doc)["status"] == "PASS"
    assert _result(doc, markdown.replace("OCR原文内容", "篡改内容", 1))["status"] == "FAIL"


def test_duplicate_document_id_fails_audit() -> None:
    doc = _doc(_unit(), _unit())
    assert _result(doc)["status"] == "FAIL"


def test_empty_title_parts_fail_audit() -> None:
    doc = _doc(_unit(title=()))
    result = _result(doc)
    assert result["status"] == "FAIL"
    assert any("title_parts must be nonempty" in error for error in result["errors"])
