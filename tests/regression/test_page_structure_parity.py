import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


def test_page_structure_artifact_is_byte_identical(tmp_path: Path) -> None:
    """Catches geometry, block-order, validation, or serialization drift in Stage 4."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.native.structure import run_page_structure
    except ModuleNotFoundError as exc:
        pytest.fail(f"page structure migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    sample_pdf = Path(sample_pdf_raw).resolve()
    candidate_templates = Path("configs/templates.json").resolve()
    expected_manifest = json.loads(
        Path("tests/contracts/reference_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture_manifest(reference_root) == expected_manifest

    profile = tmp_path / "shared/page_profile.json"
    snapshot = tmp_path / "shared/page_snapshot.jsonl"
    analysis = tmp_path / "shared/template_analysis.json"
    alignment = tmp_path / "shared/section_alignment.json"
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

    reference_output = tmp_path / "reference/page_structure.json"
    candidate_output = tmp_path / "candidate/page_structure.json"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/4_page_structure_builder.py"),
            str(snapshot),
            "--profile",
            str(profile),
            "--alignment",
            str(alignment),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run_page_structure(
        snapshot_path=snapshot,
        profile_path=profile,
        alignment_path=alignment,
        output_path=candidate_output,
    )
    assert candidate_output.read_bytes() == reference_output.read_bytes()
