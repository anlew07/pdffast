import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


def test_table_recovery_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Catches row/cell, cross-page, provenance, or rendering drift in Stage 5."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.native.tables import run_table_recovery
    except ModuleNotFoundError as exc:
        pytest.fail(f"table recovery migration is not implemented: {exc}")

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
    structure = tmp_path / "shared/page_structure.json"
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

    reference_output = tmp_path / "reference/table_recovery"
    candidate_output = tmp_path / "candidate/table_recovery"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/5_table_recovery.py"),
            str(structure),
            str(snapshot),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run_table_recovery(
        structure_path=structure,
        snapshot_path=snapshot,
        output_dir=candidate_output,
    )
    for name in ("result.json", "result.md", "logical_tables.md"):
        assert (candidate_output / name).read_bytes() == (
            reference_output / name
        ).read_bytes(), f"artifact drift: {name}"
