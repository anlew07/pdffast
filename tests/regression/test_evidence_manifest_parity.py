import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import run_text_flow
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


EVIDENCE_ARTIFACTS = (
    "evidence_manifest.json",
    "evidence_manifest.md",
)


def test_evidence_manifest_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Catches Stage 7 aggregation, accounting, or rendering drift."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.quality.evidence import run_evidence_manifest
    except ModuleNotFoundError as exc:
        pytest.fail(f"evidence manifest migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    sample_pdf = Path(sample_pdf_raw).resolve()
    candidate_templates = Path("configs/templates.json").resolve()
    expected_manifest = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture_manifest(reference_root) == expected_manifest

    shared = tmp_path / "shared"
    profile = shared / "page_profile.json"
    snapshot = shared / "page_snapshot.jsonl"
    analysis = shared / "template_analysis.json"
    alignment = shared / "section_alignment.json"
    structure = shared / "page_structure.json"
    table_dir = shared / "table_recovery"
    text_flow_dir = shared / "text_flow"
    run_profiler(
        pdf_path=sample_pdf,
        profile_output=profile,
        snapshot_output=snapshot,
        table_mode="auto",
    )
    run_template_analysis(
        profile_path=profile,
        template_path=candidate_templates,
        output_path=analysis,
    )
    run_section_alignment(
        analysis_path=analysis,
        template_path=candidate_templates,
        snapshot_path=snapshot,
        output_path=alignment,
    )
    run_page_structure(
        snapshot_path=snapshot,
        profile_path=profile,
        alignment_path=alignment,
        output_path=structure,
    )
    run_table_recovery(
        structure_path=structure,
        snapshot_path=snapshot,
        output_dir=table_dir,
    )
    from pdffast.native.text_flow import create_text_flow_result, write_text_flow_result

    flow = create_text_flow_result(
        snapshot_path=snapshot,
        structure_path=structure,
        table_result_path=table_dir / "result.json",
    )

    evidence_kwargs = dict(
        profile_path=profile,
        snapshot_path=snapshot,
        template_path=analysis,
        alignment_path=alignment,
        structure_path=structure,
        stage5_path=table_dir / "result.json",
        stage6_dir=text_flow_dir,
    )
    from pdffast.quality.evidence import create_evidence_report, write_evidence_report

    report = create_evidence_report(**evidence_kwargs, text_flow=flow)
    assert not (text_flow_dir / "normalized_text_flow.json").exists()
    write_text_flow_result(flow, text_flow_dir)

    reference_output = tmp_path / "reference/evidence"
    candidate_output = tmp_path / "candidate/evidence"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/7_native_evidence_manifest.py"),
            "--profile",
            str(profile),
            "--snapshot",
            str(snapshot),
            "--template",
            str(analysis),
            "--alignment",
            str(alignment),
            "--structure",
            str(structure),
            "--stage5",
            str(table_dir / "result.json"),
            "--stage6-dir",
            str(text_flow_dir),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    write_evidence_report(report, candidate_output)
    object_artifacts = {
        name: (candidate_output / name).read_bytes() for name in EVIDENCE_ARTIFACTS
    }
    assert report.data["summary"]["valid_raw_word_count"] == report.data["summary"]["accounted_word_count"] + report.data["summary"]["unaccounted_native_word_count"]
    run_evidence_manifest(**evidence_kwargs, output_dir=candidate_output)
    for name in EVIDENCE_ARTIFACTS:
        assert (candidate_output / name).read_bytes() == object_artifacts[name]
        assert (candidate_output / name).read_bytes() == (
            reference_output / name
        ).read_bytes(), f"artifact drift: {name}"
