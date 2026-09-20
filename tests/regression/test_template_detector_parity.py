import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from tools.migration.baseline import capture_manifest


def test_template_detector_artifact_is_byte_identical(tmp_path: Path) -> None:
    """Catches scoring, tie-break, field-order, or serialization drift in Stage 2."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.template.detector import run_template_analysis
    except ModuleNotFoundError as exc:
        pytest.fail(f"template detector migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    sample_pdf = Path(sample_pdf_raw).resolve()
    expected_manifest = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture_manifest(reference_root) == expected_manifest

    shared_profile = tmp_path / "shared/page_profile.json"
    shared_snapshot = tmp_path / "shared/page_snapshot.jsonl"
    run_profiler(
        pdf_path=sample_pdf,
        profile_output=shared_profile,
        snapshot_output=shared_snapshot,
        table_mode="auto",
    )

    reference_output = tmp_path / "reference/template_analysis.json"
    candidate_output = tmp_path / "candidate/template_analysis.json"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/2_template_analyzer.py"),
            str(shared_profile),
            "--templates",
            str(reference_root / "configs/templates.json"),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run_template_analysis(
        profile_path=shared_profile,
        template_path=Path("configs/templates.json").resolve(),
        output_path=candidate_output,
    )
    assert candidate_output.read_bytes() == reference_output.read_bytes()
