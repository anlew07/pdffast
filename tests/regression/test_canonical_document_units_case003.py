"""Compare the real case_003 Canonical payload before and after additive metadata."""

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from pdffast.canonical.builder import build_document
from pdffast.canonical.document_units import resolve_document_units_from_artifacts
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10
from pdffast.render.llm_ready import build_rendered_document


def _without_document_boundary_metadata(markdown: str) -> tuple[str, int]:
    """Remove only the new, delimited presentation blocks for parity checks."""
    return re.subn(
        r"(?m)^<!-- pdffast-document-unit: [^\n]+ -->\n"
        r"【PDFFast文档边界元数据[^\n]*】\n"
        r"(?:标题原文 \d+：[^\n]*\n)+"
        r"【PDFFast文档边界结束】\n\n?",
        "", markdown,
    )


def test_case003_adds_only_confirmed_document_units_to_canonical() -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review/case_003"
    stage3 = root / "03_stage3/section_alignment.json"
    flow = root / "06_stage6/normalized_text_flow.json"
    quality = root / "08_stage8/quality_gate.json"
    plan = root / "09_2_provider_plan/provider_plan.json"
    index = root / "09_8_production_fallback/selected_prediction_index.json"
    selected = root / "09_8_production_fallback/selected_predictions"
    old_json = root / "result/document.json"
    old_md = root / "result/document.md"
    if not all(path.exists() for path in (stage3, flow, quality, plan, index, selected, old_json, old_md)):
        pytest.skip("case_003 existing artifacts are unavailable")

    before_bytes = old_json.read_bytes()
    markdown_before = old_md.read_bytes()
    before = json.loads(before_bytes)
    coverage, admissions = resolve_document_units_from_artifacts(stage3, flow, index, selected)
    after = build_document(flow, quality, plan, index, selected, document_units=coverage, admissions=admissions)
    markdown, _ = build_rendered_document(after)

    assert before["schema_version"] == "1.0"
    assert after["schema_version"] == "1.1"
    assert [item["anchor"]["page"] for item in after["document_units"]] == [27, 29, 30, 36, 66]
    assert [item["range_status"] for item in after["document_units"]] == [
        "PARTIAL", "RESOLVED", "PARTIAL", "PARTIAL", "RESOLVED",
    ]
    assert all(item["role"] == "UNKNOWN" for item in after["document_units"])
    for key in ("sections", "pages", "records", "fallback_overlays", "summary"):
        assert after[key] == before[key], key
    assert len(after["records"]) == len(before["records"])
    assert all("document_id" not in record for record in after["records"])
    assert all("document_id" not in section for section in after["sections"])
    original_body, marker_count = _without_document_boundary_metadata(markdown)
    assert marker_count == 5
    assert original_body.encode("utf-8") == markdown_before
    assert old_json.read_bytes() == before_bytes
    assert old_md.read_bytes() == markdown_before


def test_case003_runner_publishes_markers_without_changing_original_body(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review/case_003"
    files = {
        "section_alignment": root / "03_stage3/section_alignment.json",
        "normalized_flow": root / "06_stage6/normalized_text_flow.json",
        "quality_gate": root / "08_stage8/quality_gate.json",
        "provider_plan": root / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": root / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": root / "09_8_production_fallback/selected_predictions",
    }
    if not all(path.exists() for path in (*files.values(), root / "result/document.md")):
        pytest.skip("case_003 existing artifacts are unavailable")
    context = PipelineContext.create(
        project_root=Path(__file__).resolve().parents[2],
        pdf=tmp_path / "case_003.pdf", output_root=tmp_path,
        run_id="canonical-document-units", case_id="case_003",
        page_dpi=200, region_dpi=300, rapidocr_workers=1, table_mode="auto",
    )
    context = replace(context, artifacts=replace(context.artifacts, **files))
    run_stage10(context)
    canonical = json.loads(context.artifacts.result_document.read_text(encoding="utf-8"))
    assert [unit["anchor"]["page"] for unit in canonical["document_units"]] == [27, 29, 30, 36, 66]
    rendered = context.artifacts.result_markdown.read_text(encoding="utf-8")
    original_body, marker_count = _without_document_boundary_metadata(rendered)
    assert marker_count == 5
    assert original_body.encode("utf-8") == (root / "result/document.md").read_bytes()


def test_case004_publishes_only_units_admitted_by_its_real_evidence_chain() -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review/case_004"
    stage3 = root / "03_stage3/section_alignment.json"
    flow = root / "06_stage6/normalized_text_flow.json"
    quality = root / "08_stage8/quality_gate.json"
    plan = root / "09_2_provider_plan/provider_plan.json"
    index = root / "09_8_production_fallback/selected_prediction_index.json"
    selected = root / "09_8_production_fallback/selected_predictions"
    if not all(path.exists() for path in (stage3, flow, quality, plan, index, selected)):
        pytest.skip("case_004 existing evidence chain is unavailable")
    coverage, admissions = resolve_document_units_from_artifacts(stage3, flow, index, selected)
    actual = build_document(flow, quality, plan, index, selected, document_units=coverage, admissions=admissions)
    assert [(item["anchor"]["page"], item["range_status"]) for item in actual["document_units"]] == [
        (83, "PARTIAL"), (108, "PARTIAL"),
    ]
    old_json = json.loads((root / "result/document.json").read_text(encoding="utf-8"))
    for key in ("sections", "pages", "records", "fallback_overlays", "summary"):
        assert actual[key] == old_json[key], key
    rendered, _ = build_rendered_document(actual)
    original_body, marker_count = _without_document_boundary_metadata(rendered)
    assert marker_count == 2
    assert original_body.encode("utf-8") == (root / "result/document.md").read_bytes()
