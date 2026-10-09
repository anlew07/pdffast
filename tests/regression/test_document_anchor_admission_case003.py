"""Admit case_003 anchors from existing predictions without running providers."""

import json
from pathlib import Path

import pytest

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.anchor_admission import admit_recovered_document_anchors
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.heading_candidates import diagnose_recovered_heading_candidates
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def test_case003_five_title_regions_are_admitted_without_ranges_or_ownership() -> None:
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
    provisional = create_document_units(preview)
    decisions = admit_recovered_document_anchors(preview, proposals.proposals, headings.candidates)
    units = create_document_units(preview, admissions=decisions)

    confirmed = [decision for decision in decisions if decision.status == "ANCHOR_CONFIRMED"]
    assert [decision.page_number for decision in confirmed] == [27, 29, 30, 36, 66]
    assert [len(decision.candidate_refs) for decision in confirmed] == [2] * 5
    assert all(decision.conflicts == () for decision in confirmed)
    assert all(decision.bbox_coordinate_space == "PROVIDER_INPUT_IMAGE" for decision in confirmed)
    assert len(units) == len(provisional) == 6
    assert all(unit.anchor_status == "PROPOSED" for unit in provisional[1:])
    assert all(unit.anchor_status == "ANCHOR_CONFIRMED" for unit in units[1:])
    assert all(unit.range_status == "UNRESOLVED" and unit.page_range is None for unit in units)
    assert section_parent_map(units) == {}
    assert canonical_path.read_bytes() == canonical_before
