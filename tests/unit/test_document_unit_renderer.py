"""Document boundaries are structural annotations, not PDF headings or record owners."""

from copy import deepcopy

from pdffast.render.llm_ready import build_rendered_document


def _unit(document_id: str = "document:recovered:p0002", *, page: int = 2,
          status: str = "PARTIAL", parts: tuple[str, ...] = ("原始标题第一行", "原始标题第二行"),
          start: int | None = None, end: int | None = None) -> dict:
    return {
        "document_id": document_id, "source": "RECOVERED", "role": "UNKNOWN",
        "anchor": {"page": page, "title_parts": list(parts), "anchor_ref": f"anchor:{document_id}",
                   "candidate_refs": [f"candidate:{document_id}"], "evidence_refs": [f"source:{document_id}"],
                   "bbox_coordinate_space": "PROVIDER_INPUT_IMAGE"},
        "anchor_status": "ANCHOR_CONFIRMED", "range_status": status,
        "page_range": {"start_page": start or page, "end_page": end or page},
        "coverage_evidence_refs": [],
    }


def _doc(*units: dict) -> dict:
    return {
        "stage": 10, "substage": "10.1", "schema_version": "1.1",
        "status": "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING", "page_count": 3,
        "sections": [
            {"section_id": "s1", "section_title": "一、原生章节", "page_numbers": [1], "record_ids": ["r1"]},
            {"section_id": "s2", "section_title": "二、另一原生章节", "page_numbers": [2, 3],
             "record_ids": ["r2", "r3", "r4"]},
        ],
        "records": [
            {"record_id": "r1", "record_type": "paragraph", "source_page": 1, "text": "第一段原文"},
            {"record_id": "r2", "record_type": "paragraph", "source_page": 2, "text": "第二段原文"},
            {"record_id": "r3", "record_type": "table_ref", "source_page": 2, "table_text": "表内原文"},
            {"record_id": "r4", "record_type": "image_ref", "source_page": 3},
        ],
        "fallback_overlays": {"page_fallbacks": [], "region_fallbacks": [], "inline_contexts": []},
        "summary": {"native_record_count": 4},
        "document_units": list(units),
    }


def _set_page_fallback_text(doc: dict, text: str) -> None:
    doc["records"][1] = {
        "record_id": "r2", "record_type": "image_ref", "source_page": 2,
        "stage10_resolution": {"mode": "PAGE_FALLBACK_SOURCE", "fallback_task_ids": ["task-p2"]},
    }
    doc["fallback_overlays"]["page_fallbacks"] = [{
        "task_id": "task-p2", "page_number": 2,
        "fallback_content": {"text": {"availability": "AVAILABLE", "content": text}},
    }]
    doc["summary"]["page_fallback_count"] = 1


def test_document_unit_renders_boundary_before_anchor_page_content() -> None:
    markdown, _ = build_rendered_document(_doc(_unit()))
    assert "【PDFFast文档边界元数据｜锚点第2页" in markdown
    assert "页内具体边界未确定" in markdown
    assert markdown.index("【PDFFast文档边界元数据") < markdown.index("<!-- source-page: 2 -->")
    assert markdown.index("【PDFFast文档边界元数据") < markdown.index("第二段原文")


def test_document_unit_is_not_section_heading_and_keeps_native_heading_order() -> None:
    markdown, _ = build_rendered_document(_doc(_unit()))
    assert "# 二、另一原生章节" in markdown
    assert "# 原始标题第一行" not in markdown
    assert markdown.index("【PDFFast文档边界元数据") < markdown.index("# 二、另一原生章节")
    assert markdown.index("# 一、原生章节") < markdown.index("第一段原文")


def test_title_parts_preserve_original_order_without_synthetic_combination() -> None:
    markdown, _ = build_rendered_document(_doc(_unit(parts=("陕西省教育厅服务地方专项计划项目", "合同书"))))
    assert "标题原文 1：陕西省教育厅服务地方专项计划项目\n标题原文 2：合同书" in markdown
    assert "陕西省教育厅服务地方专项计划项目合同书" not in markdown


def test_partial_range_does_not_claim_complete_extent() -> None:
    markdown, _ = build_rendered_document(_doc(_unit(status="PARTIAL")))
    assert "已确认覆盖：2–2页；完整范围未确定" in markdown
    assert "范围已确认：2–2页" not in markdown


def test_resolved_range_does_not_claim_exclusive_page_ownership() -> None:
    markdown, _ = build_rendered_document(_doc(_unit(status="RESOLVED")))
    assert "当前证据确认覆盖：2–2页" in markdown
    assert "全部属于" not in markdown


def test_unknown_role_is_not_rendered_as_noise() -> None:
    markdown, _ = build_rendered_document(_doc(_unit()))
    assert "未知类型文档" not in markdown
    assert "UNKNOWN" not in markdown


def test_same_title_different_units_both_render() -> None:
    markdown, _ = build_rendered_document(_doc(
        _unit("document:a", page=2, parts=("同名标题",)),
        _unit("document:b", page=3, parts=("同名标题",)),
    ))
    assert markdown.count("标题原文 1：同名标题") == 2
    assert markdown.index("document:a") < markdown.index("document:b")


def test_multiple_units_on_same_page_render_in_stable_input_order() -> None:
    markdown, _ = build_rendered_document(_doc(_unit("document:a"), _unit("document:b")))
    assert markdown.count("【PDFFast文档边界元数据｜锚点第2页") == 2
    assert markdown.index("document:a") < markdown.index("document:b")
    assert markdown.index("document:b") < markdown.index("第二段原文")


def test_anchor_title_with_leading_page_text_places_marker_after_that_text() -> None:
    doc = _doc(_unit(parts=("观察到的标题",)))
    _set_page_fallback_text(doc, "上一份文档末行\n观察到的标题\n当前文档正文")
    markdown, _ = build_rendered_document(doc)
    assert markdown.index("上一份文档末行") < markdown.index("【PDFFast文档边界元数据")
    assert markdown.index("【PDFFast文档边界结束】") < markdown.index("\n观察到的标题\n")


def test_multiple_same_page_anchors_follow_observed_text_order() -> None:
    doc = _doc(
        _unit("document:a", parts=("标题甲",)),
        _unit("document:b", parts=("标题乙",)),
    )
    _set_page_fallback_text(doc, "页首先前文\n标题甲\n中间正文\n标题乙\n末尾正文")
    markdown, _ = build_rendered_document(doc)
    assert markdown.index("页首先前文") < markdown.index("document:a") < markdown.index("\n标题甲\n")
    assert markdown.index("中间正文") < markdown.index("document:b") < markdown.index("\n标题乙\n")


def test_native_duplicate_heading_does_not_consume_recovered_anchor() -> None:
    doc = _doc(_unit(parts=("二、另一原生章节",)))
    doc["records"][1]["text"] = "二、另一原生章节"
    markdown, _ = build_rendered_document(doc)
    assert markdown.count("【PDFFast文档边界元数据") == 1
    assert markdown.index("【PDFFast文档边界元数据") < markdown.index("# 二、另一原生章节")


def test_records_tables_images_and_canonical_remain_unchanged() -> None:
    doc = _doc(_unit())
    before = deepcopy(doc)
    old, old_manifest = build_rendered_document(_doc())
    new, new_manifest = build_rendered_document(doc)
    assert doc == before
    assert [x for x in ("第一段原文", "第二段原文", "表内原文", "【图示内容｜第3页】") if x in new] == [
        "第一段原文", "第二段原文", "表内原文", "【图示内容｜第3页】",
    ]
    assert new.count("第一段原文") == old.count("第一段原文") == 1
    assert new.count("第二段原文") == old.count("第二段原文") == 1
    assert new.count("表内原文") == old.count("表内原文") == 1
    assert new.count("【图示内容｜第3页】") == old.count("【图示内容｜第3页】") == 1
    assert new_manifest["record_dispositions"] == old_manifest["record_dispositions"]
    assert new_manifest["inline_overlay_dispositions"] == old_manifest["inline_overlay_dispositions"]
