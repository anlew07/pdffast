"""Audit the existing admitted units without rerunning any Provider."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from pdffast.audit.structure_boundary import audit
from pdffast.canonical.builder import build_document
from pdffast.canonical.document_units import resolve_document_units_from_artifacts
from pdffast.render.llm_ready import build_rendered_document


@pytest.mark.parametrize("case,pages,statuses", [
    ("003", [27, 29, 30, 36, 66], ["PARTIAL", "RESOLVED", "PARTIAL", "PARTIAL", "RESOLVED"]),
    ("004", [83, 108], ["PARTIAL", "PARTIAL"]),
])
def test_existing_case_document_units_pass_semantic_audit(case: str, pages: list[int], statuses: list[str]) -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review" / f"case_{case}"
    stage3 = root / "03_stage3/section_alignment.json"
    flow = root / "06_stage6/normalized_text_flow.json"
    quality = root / "08_stage8/quality_gate.json"
    plan = root / "09_2_provider_plan/provider_plan.json"
    index = root / "09_8_production_fallback/selected_prediction_index.json"
    selected = root / "09_8_production_fallback/selected_predictions"
    old = root / "result/document.json"
    if not all(path.exists() for path in (stage3, flow, quality, plan, index, selected, old)):
        pytest.skip(f"case_{case} existing artifacts are unavailable")
    coverage, admissions = resolve_document_units_from_artifacts(stage3, flow, index, selected)
    canonical = build_document(flow, quality, plan, index, selected,
                               document_units=coverage, admissions=admissions)
    markdown, manifest = build_rendered_document(canonical)
    result = audit(json.loads(flow.read_text()), json.loads(quality.read_text()),
                   canonical, manifest, markdown=markdown)
    units = canonical["document_units"]
    assert [item["anchor"]["page"] for item in units] == pages
    assert [item["range_status"] for item in units] == statuses
    assert result["validation"]["pass"] is True
    assert result["document_unit_audit"]["status"] == "PASS"
    assert result["document_unit_audit"]["units"] == len(pages)
    assert result["document_unit_audit"]["rendered_markers"] == len(pages)
    assert result["document_unit_audit"]["provenance_checked"] == len(pages)
    if case == "003":
        missing = audit(json.loads(flow.read_text()), json.loads(quality.read_text()),
                        canonical, manifest, markdown=markdown.replace("<!-- pdffast-document-unit:", "<!-- removed-document-unit:", 1))
        assert missing["status"] == "FAIL"
        assert missing["validation"]["pass"] is False
        changed_section = deepcopy(canonical)
        changed_section["sections"][0]["section_title"] = "伪造章节"
        changed_markdown, changed_manifest = build_rendered_document(changed_section)
        altered = audit(json.loads(flow.read_text()), json.loads(quality.read_text()),
                        changed_section, changed_manifest, markdown=changed_markdown)
        assert altered["status"] == "FAIL"
        changed_table = deepcopy(canonical)
        table = next(record for record in changed_table["records"] if record.get("record_type") == "table_ref")
        table["table_text"] = "伪造表格内容"
        table_markdown, table_manifest = build_rendered_document(changed_table)
        altered_table = audit(json.loads(flow.read_text()), json.loads(quality.read_text()),
                              changed_table, table_manifest, markdown=table_markdown)
        assert altered_table["status"] == "FAIL"
    historical = json.loads(old.read_text())
    for key in ("sections", "pages", "records", "fallback_overlays"):
        assert canonical[key] == historical[key]
