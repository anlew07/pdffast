"""Regression: PAGE_DOCUMENT_OCR must retain structured provider Markdown.

No model inference, PDF fixtures, network access or benchmark artifacts required.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from pdffast.render.llm_ready import build_rendered_document


def _ocr_page(*, source_format: str, content: str, raw_content: str | None) -> dict:
    """Minimal Stage10.1 canonical document with one accepted page OCR task."""
    return {
        "schema_version": "1.1",
        "stage": 10,
        "substage": "10.1",
        "status": "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING",
        "page_count": 1,
        "sections": [
            {
                "section_id": "section-1",
                "section_title": "一、测试章节",
                "page_numbers": [1],
                "record_ids": ["record-1"],
            }
        ],
        "records": [
            {
                "record_id": "record-1",
                "record_type": "image_ref",
                "source_page": 1,
                "stage10_resolution": {
                    "mode": "PAGE_FALLBACK_SOURCE",
                    "fallback_task_ids": ["ocr-p1"],
                },
            }
        ],
        "fallback_overlays": {
            "page_fallbacks": [
                {
                    "task_id": "ocr-p1",
                    "page_number": 1,
                    "fallback_content": {
                        "status": "SUCCESS",
                        "text": {
                            "availability": "AVAILABLE",
                            "content": content,
                            "raw_content": raw_content,
                            "source_format": source_format,
                        },
                    },
                }
            ],
            "region_fallbacks": [],
            "inline_contexts": [],
        },
        "summary": {
            "native_record_count": 1,
            "page_fallback_count": 1,
            "page_ocr_fallback_count": 1,
            "page_layout_fallback_count": 0,
            "region_fallback_count": 0,
            "detached_region_fallback_count": 0,
            "inline_context_count": 0,
            "terminal_preserve_count": 0,
            "pipeline_failure_count": 0,
        },
        "document_units": [],
    }


@pytest.mark.parametrize("source_format", ["markdown", "html_markdown"])
def test_page_ocr_keeps_html_table_from_structured_provider(source_format: str) -> None:
    raw = (
        "# 模型识别的标题\n"
        "<table><tr><th>指标</th><th>金额</th></tr>"
        "<tr><td>研发费</td><td>123.45</td></tr></table>"
    )
    doc = _ocr_page(
        source_format=source_format,
        content="模型识别的标题 指标 金额 研发费 123.45",
        raw_content=raw,
    )
    before = deepcopy(doc)
    markdown, manifest = build_rendered_document(doc)

    assert manifest["status"] == "PASS"
    assert manifest["summary"]["page_ocr_fallback_rendered_count"] == 1
    assert markdown.count("<table>") == 1
    assert markdown.count("</table>") == 1
    assert "<td>123.45</td>" in markdown
    assert "# 一、测试章节" in markdown
    assert "\n# 模型识别的标题\n" not in markdown
    assert "模型识别的标题" in markdown
    assert doc == before  # Rendering must not mutate Canonical.


def test_page_ocr_keeps_formula_from_mineru_markdown() -> None:
    raw = "公式如下：\n$$\\frac{a+b}{c} = 2$$\n其他说明"
    doc = _ocr_page(
        source_format="markdown",
        content="公式如下 a+b/c = 2 其他说明",
        raw_content=raw,
    )
    markdown, manifest = build_rendered_document(doc)

    assert manifest["status"] == "PASS"
    assert "$$\\frac{a+b}{c} = 2$$" in markdown
    assert markdown.count("$$") == 2
    assert "【整页识别开始｜第1页】" in markdown
    assert "【整页识别结束】" in markdown


def test_rapidocr_plain_text_still_uses_canonical_content() -> None:
    doc = _ocr_page(
        source_format="plain_text",
        content="OCR 的可靠文字 100 元",
        raw_content="<table><tr><td>不应渲染的原始内容</td></tr></table>",
    )
    markdown, manifest = build_rendered_document(doc)

    assert manifest["status"] == "PASS"
    assert "OCR 的可靠文字 100 元" in markdown
    assert "<table>" not in markdown
    assert "不应渲染的原始内容" not in markdown


def test_markdown_provider_with_empty_raw_falls_back_to_plain_content() -> None:
    doc = _ocr_page(
        source_format="markdown",
        content="标准化文字仍然需要保留",
        raw_content="",
    )
    markdown, manifest = build_rendered_document(doc)

    assert manifest["status"] == "PASS"
    assert "标准化文字仍然需要保留" in markdown
    assert "【整页识别失败" not in markdown


def test_plain_provider_without_structured_metadata_is_backward_compatible() -> None:
    doc = _ocr_page(
        source_format="plain_text",
        content="基础 OCR 文本",
        raw_content=None,
    )
    text = doc["fallback_overlays"]["page_fallbacks"][0]["fallback_content"]["text"]
    text.pop("source_format")
    text.pop("raw_content")

    markdown, manifest = build_rendered_document(doc)
    assert manifest["status"] == "PASS"
    assert "基础 OCR 文本" in markdown
