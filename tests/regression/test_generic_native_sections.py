"""Characterize the template-free native path on the reference sample."""

import json
import os
from pathlib import Path

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.sections import run_section_discovery, load_snapshot_pages
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import create_text_flow_result, write_text_flow_result
from pdffast.quality.evidence import create_evidence_report, write_evidence_report
from pdffast.quality.gate import evaluate_evidence_report, write_quality_report


@pytest.mark.parametrize("case_id", ("case_001", "case_002"))
def test_real_pdf_generic_sections_and_accounting(tmp_path: Path, case_id: str) -> None:
    reference_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if reference_root:
        pdf = Path(reference_root).resolve() / "benchmark/samples/real" / f"{case_id}.pdf"
    elif case_id == "case_002" and os.environ.get("PDFFAST_SAMPLE_PDF"):
        pdf = Path(os.environ["PDFFAST_SAMPLE_PDF"]).resolve()
    else:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for this real PDF")
    profile = tmp_path / "01/page_profile.json"
    snapshot = tmp_path / "01/page_snapshot.jsonl"
    sections_path = tmp_path / "03/section_alignment.json"
    structure = tmp_path / "04/page_structure.json"
    tables_dir = tmp_path / "05"
    flow_dir = tmp_path / "06"
    evidence_dir = tmp_path / "07"
    quality_dir = tmp_path / "08"

    run_profiler(pdf_path=pdf, profile_output=profile, snapshot_output=snapshot, table_mode="auto")
    sections = run_section_discovery(profile_path=profile, snapshot_path=snapshot, output_path=sections_path)
    snapshots = load_snapshot_pages(snapshot)
    assert len(sections["pages"]) == sections["page_count"] == len(snapshots)
    assert sections["sections"]
    assert all(
        section["title"] in snapshots[section["anchor_page"]]["native_text"]
        for section in sections["sections"]
    )
    assert not any(section.get("canonical_title") for section in sections["sections"])
    assert all(page["structure_type"] != "unassigned" for page in sections["pages"])

    run_page_structure(snapshot_path=snapshot, profile_path=profile, alignment_path=sections_path, output_path=structure)
    run_table_recovery(structure_path=structure, snapshot_path=snapshot, output_dir=tables_dir)
    flow = create_text_flow_result(snapshot_path=snapshot, structure_path=structure, table_result_path=tables_dir / "result.json")
    write_text_flow_result(flow, flow_dir)
    report = create_evidence_report(
        profile_path=profile, snapshot_path=snapshot, alignment_path=sections_path,
        structure_path=structure, stage5_path=tables_dir / "result.json",
        stage6_dir=flow_dir, text_flow=flow,
    )
    write_evidence_report(report, evidence_dir)
    assert len(report.data["pages"]) == sections["page_count"]
    assert report.data["summary"]["valid_raw_word_count"] > 0
    assert "stage2_template" not in report.data["inputs"]
    assert json.loads((evidence_dir / "evidence_manifest.json").read_text())["summary"] == report.data["summary"]
    quality = evaluate_evidence_report(
        report, manifest_path=evidence_dir / "evidence_manifest.json", pdf_path=pdf,
        output_dir=quality_dir, probe_dpi=150, save_probe_crops=False,
    )
    write_quality_report(quality, quality_dir)
    assert (quality_dir / "quality_gate.json").is_file()

    if reference_root:
        historical = Path(reference_root) / "outputs/pipeline_runs" / f"{case_id}_final_bench_v1"
        old_flow = json.loads((historical / "06_stage6/normalized_text_flow.json").read_text())
        assert [record.get("text") for record in flow.normalized_flow["records"]] == [
            record.get("text") for record in old_flow["records"]
        ]
        old_evidence = json.loads((historical / "07_stage7/evidence_manifest.json").read_text())
        for key in (
            "valid_raw_word_count", "accounted_word_count", "accounted_table_word_count",
            "unaccounted_native_word_count",
        ):
            assert report.data["summary"][key] == old_evidence["summary"][key]
