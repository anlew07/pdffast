"""Characterize the template input actually passed by the production runner."""

import json
import os
from pathlib import Path

import pytest

from pdffast.native.text_flow import create_text_flow_result
from pdffast.quality.evidence import create_evidence_report, write_evidence_report


def test_runner_template_input_contract_on_real_case_002(tmp_path: Path) -> None:
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for real case_002")

    reference_run = (
        Path(raw_root).resolve()
        / "outputs/pipeline_runs/case_002_final_bench_v1"
    )
    profile = reference_run / "01_stage1/page_profile.json"
    snapshot = reference_run / "01_stage1/page_snapshot.jsonl"
    analysis = reference_run / "02_stage2/template_analysis.json"
    alignment = reference_run / "03_stage3/section_alignment.json"
    structure = reference_run / "04_stage4/page_structure.json"
    table_result = reference_run / "05_stage5/result.json"
    stage6_dir = tmp_path / "06_stage6"
    template_config = Path("configs/templates.json").resolve()
    for path in (profile, snapshot, analysis, alignment, structure, table_result):
        assert path.is_file(), f"Missing case_002 characterization input: {path}"

    flow = create_text_flow_result(
        snapshot_path=snapshot,
        structure_path=structure,
        table_result_path=table_result,
    )
    inputs = dict(
        profile_path=profile,
        snapshot_path=snapshot,
        alignment_path=alignment,
        structure_path=structure,
        stage5_path=table_result,
        stage6_dir=stage6_dir,
        text_flow=flow,
    )
    actual = create_evidence_report(**inputs, template_path=template_config)
    comparison = create_evidence_report(**inputs, template_path=analysis)
    output_dir = tmp_path / "07_stage7"
    write_evidence_report(actual, output_dir)
    comparison_dir = tmp_path / "07_stage7_analysis_input"
    write_evidence_report(comparison, comparison_dir)
    written = json.loads((output_dir / "evidence_manifest.json").read_text(encoding="utf-8"))

    assert written == actual.data
    assert written["source_file"] == "case_002.pdf"
    assert written["inputs"]["stage2_template"] == str(template_config)
    assert written["upstream_versions"]["template_analyzer_version"] is None
    assert written["document_context"]["template_decision"] is None
    assert comparison.data["upstream_versions"]["template_analyzer_version"] == "0.2.0"

    # The template argument changes only input provenance and analyzer version.
    normalized = json.loads(json.dumps(comparison.data))
    normalized["inputs"]["stage2_template"] = str(template_config)
    normalized["upstream_versions"]["template_analyzer_version"] = None
    assert written == normalized
    assert (output_dir / "evidence_manifest.md").read_bytes() == (
        comparison_dir / "evidence_manifest.md"
    ).read_bytes()
