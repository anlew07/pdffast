"""Characterize coverage using only the existing case_003 evidence artifacts."""

import json
from pathlib import Path

import pytest

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.anchor_admission import admit_recovered_document_anchors
from pdffast.structure_reconciliation.coverage import resolve_document_coverages
from pdffast.structure_reconciliation.document_units import create_document_units, section_parent_map
from pdffast.structure_reconciliation.heading_candidates import diagnose_recovered_heading_candidates
from pdffast.structure_reconciliation.page_relations import decide_page_relations
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


def test_case003_admitted_anchors_resolve_only_confirmed_page_intersections() -> None:
    root = Path(__file__).resolve().parents[2] / "outputs/template_removal_review/case_003"
    native_path = root / "03_stage3/section_alignment.json"
    flow_path = root / "06_stage6/normalized_text_flow.json"
    index_path = root / "09_8_production_fallback/selected_prediction_index.json"
    selected_dir = root / "09_8_production_fallback/selected_predictions"
    canonical_path = root / "result/document.json"
    if not all(path.exists() for path in (native_path, flow_path, index_path, selected_dir, canonical_path)):
        pytest.skip("case_003 existing production artifacts are unavailable")

    canonical_before = canonical_path.read_bytes()
    native = json.loads(native_path.read_text(encoding="utf-8"))
    flow = json.loads(flow_path.read_text(encoding="utf-8"))
    headings = diagnose_recovered_heading_candidates(flow_path, index_path, selected_dir)
    proposals = adjudicate_recovered_heading_candidates(headings.candidates, native_flow=flow)
    preview = preview_reconciled_structure(native, proposals.proposals)
    admissions = admit_recovered_document_anchors(preview, proposals.proposals, headings.candidates)
    units = create_document_units(preview, admissions=admissions)
    relations = decide_page_relations(preview)
    results = resolve_document_coverages(units, relations, page_count=native["page_count"])

    assert len(results) == 6
    assert results[0].unit.range_status == "UNRESOLVED"
    assert [result.unit.anchor_page for result in results[1:]] == [27, 29, 30, 36, 66]
    assert [result.unit.range_status for result in results[1:]] == [
        "PARTIAL", "RESOLVED", "PARTIAL", "PARTIAL", "RESOLVED",
    ]
    assert [result.unit.page_range for result in results[1:]] == [
        (27, 27), (29, 29), (30, 30), (36, 36), (66, 66),
    ]
    assert [result.left_stop_reason for result in results[1:]] == ["BOUNDARY"] * 5
    assert [result.right_stop_reason for result in results[1:]] == [
        "INSUFFICIENT", "BOUNDARY", "INSUFFICIENT", "INSUFFICIENT", "EOF",
    ]
    assert all(result.left_extent == "CLOSED" for result in results[1:])
    assert [result.right_extent for result in results[1:]] == [
        "OPEN", "CLOSED", "OPEN", "OPEN", "CLOSED",
    ]
    assert all(result.used_evidence_refs for result in results[1:])
    assert section_parent_map(result.unit for result in results) == {}
    assert canonical_path.read_bytes() == canonical_before
