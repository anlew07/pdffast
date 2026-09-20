import json
import os
from pathlib import Path
import subprocess

import pytest

from tools.migration.baseline import capture_manifest
from tools.migration.compare_artifacts import RootMapping, compare_json


def test_profiler_artifacts_match_reference(tmp_path: Path) -> None:
    """Catches Stage 1 drift while allowing only the output snapshot path."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.native.profiler import run_profiler
    except ModuleNotFoundError as exc:
        pytest.fail(f"profiler migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    sample_pdf = Path(sample_pdf_raw).resolve()
    expected_manifest = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture_manifest(reference_root) == expected_manifest
    assert sample_pdf.is_file()

    reference_dir = tmp_path / "reference"
    candidate_dir = tmp_path / "candidate"
    reference_profile = reference_dir / "page_profile.json"
    reference_snapshot = reference_dir / "page_snapshot.jsonl"
    candidate_profile = candidate_dir / "page_profile.json"
    candidate_snapshot = candidate_dir / "page_snapshot.jsonl"

    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/1_page_profiler.py"),
            str(sample_pdf),
            "--output",
            str(reference_profile),
            "--snapshot-output",
            str(reference_snapshot),
            "--table-mode",
            "auto",
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run_profiler(
        pdf_path=sample_pdf,
        profile_output=candidate_profile,
        snapshot_output=candidate_snapshot,
        table_mode="auto",
    )

    profile_comparison = compare_json(
        reference_profile,
        candidate_profile,
        RootMapping(
            reference_project=reference_root,
            candidate_project=Path.cwd(),
            reference_run=reference_dir,
            candidate_run=candidate_dir,
        ),
    )
    assert profile_comparison.equal, profile_comparison.diff
    assert candidate_snapshot.read_bytes() == reference_snapshot.read_bytes()
