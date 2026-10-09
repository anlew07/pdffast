"""Characterize document-unit candidates from existing case_003 artifacts."""

import json
from pathlib import Path

import pytest

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.heading_candidates import diagnose_recovered_heading_candidates
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def test_case003_primary_and_five_recovered_units_without_ranges() -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review/case_003"
    native_path = root / "03_stage3/section_alignment.json"
    flow_path = root / "06_stage6/normalized_text_flow.json"
    selected_index_path = root / "09_8_production_fallback/selected_prediction_index.json"
    selected_dir = root / "09_8_production_fallback/selected_predictions"
    canonical_path = root / "result/document.json"
    if not all(path.exists() for path in (native_path, flow_path, selected_index_path, selected_dir, canonical_path)):
        pytest.skip("case_003 existing production artifacts are unavailable")

    canonical_before = canonical_path.read_bytes()
    native = json.loads(native_path.read_text(encoding="utf-8"))
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    headings = diagnose_recovered_heading_candidates(flow_path, selected_index_path, selected_dir)
    proposals = adjudicate_recovered_heading_candidates(headings.candidates, native_flow=flow)
    preview = preview_reconciled_structure(native, proposals.proposals)
    units = create_document_units(preview)

    assert len(units) == 6
    assert units[0].role == "PRIMARY" and units[0].source == "NATIVE"
    assert len(native["sections"]) == 16
    assert units[0].section_ids == ()
    assert section_parent_map(units) == {}
    recovered = units[1:]
    assert [unit.anchor_page for unit in recovered] == [27, 29, 30, 36, 66]
    assert all(unit.source == "RECOVERED" and unit.role == "UNKNOWN" for unit in recovered)
    assert all(unit.range_status == "UNRESOLVED" and unit.page_range is None for unit in recovered)
    assert all(unit.section_ids == () for unit in recovered)
    assert recovered[1].title_parts == ("陕西省教育厅服务地方专项计划项目", "合同书")
    assert len(recovered[1].evidence_refs) == 2
    assert canonical_path.read_bytes() == canonical_before
