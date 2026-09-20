import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


def test_section_aligner_artifact_is_byte_identical(tmp_path: Path) -> None:
    """Catches ranking, range, recovery, or serialization drift in Stage 3."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.template.aligner import run_section_alignment
    except ModuleNotFoundError as exc:
        pytest.fail(f"section aligner migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    sample_pdf = Path(sample_pdf_raw).resolve()
    candidate_templates = Path("configs/templates.json").resolve()
    expected_manifest = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture_manifest(reference_root) == expected_manifest

    shared_profile = tmp_path / "shared/page_profile.json"
    shared_snapshot = tmp_path / "shared/page_snapshot.jsonl"
    shared_analysis = tmp_path / "shared/template_analysis.json"
    run_profiler(
        pdf_path=sample_pdf,
        profile_output=shared_profile,
        snapshot_output=shared_snapshot,
        table_mode="auto",
    )
    run_template_analysis(
        profile_path=shared_profile,
        template_path=candidate_templates,
        output_path=shared_analysis,
    )

    reference_output = tmp_path / "reference/section_alignment.json"
    candidate_output = tmp_path / "candidate/section_alignment.json"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/3_section_aligner.py"),
            str(shared_analysis),
            "--templates",
            str(reference_root / "configs/templates.json"),
            "--snapshot",
            str(shared_snapshot),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run_section_alignment(
        analysis_path=shared_analysis,
        template_path=candidate_templates,
        snapshot_path=shared_snapshot,
        output_path=candidate_output,
    )
    assert candidate_output.read_bytes() == reference_output.read_bytes()
