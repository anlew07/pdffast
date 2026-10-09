"""Characterize adjacent-page decisions using existing case_003 artifacts only."""

import json
from collections import Counter
from pathlib import Path

import pytest

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.heading_candidates import diagnose_recovered_heading_candidates
from pdffast.structure_reconciliation.page_relations import decide_page_relations
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def test_case003_adjacent_page_decisions_do_not_assign_ownership() -> None:
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
    units_before = create_document_units(preview)
    decisions = decide_page_relations(preview)
    by_edge = {(item.left_page, item.right_page): item for item in decisions}

    assert len(decisions) == 65
    assert Counter(item.decision for item in decisions) == {
        "BOUNDARY": 5, "INSUFFICIENT": 60,
    }
    assert {edge for edge, item in by_edge.items() if item.decision == "BOUNDARY"} == {
        (26, 27), (28, 29), (29, 30), (35, 36), (65, 66),
    }
    assert by_edge[27, 28].decision == "INSUFFICIENT"
    assert [item.kind for item in by_edge[27, 28].boundary_evidence] == [
        "NATIVE_OBSERVED_HEADING"
    ]
    assert by_edge[36, 37].decision == "INSUFFICIENT"
    assert (66, 67) not in by_edge
    assert create_document_units(preview) == units_before
    assert all(unit.page_range is None for unit in units_before)
    assert section_parent_map(units_before) == {}
    assert canonical_path.read_bytes() == canonical_before
