import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


def _run_reference(reference_root: Path, arguments: list[str]) -> None:
    completed = subprocess.run(
        [str(reference_root / ".venv/bin/python"), *arguments],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_phase1b_pipeline_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Runs Stages 1-5 in both trees and compares all eight artifacts."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

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
    table_dir = shared / "table_recovery"
    artifacts = {
        "page_profile.json": shared / "page_profile.json",
        "page_snapshot.jsonl": shared / "page_snapshot.jsonl",
        "template_analysis.json": shared / "template_analysis.json",
        "section_alignment.json": shared / "section_alignment.json",
        "page_structure.json": shared / "page_structure.json",
        "table_recovery/result.json": table_dir / "result.json",
        "table_recovery/result.md": table_dir / "result.md",
        "table_recovery/logical_tables.md": table_dir / "logical_tables.md",
    }
    reference_templates = reference_root / "configs/templates.json"

    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/1_page_profiler.py"),
            str(sample_pdf),
            "--output",
            str(artifacts["page_profile.json"]),
            "--snapshot-output",
            str(artifacts["page_snapshot.jsonl"]),
            "--table-mode",
            "auto",
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/2_template_analyzer.py"),
            str(artifacts["page_profile.json"]),
            "--templates",
            str(reference_templates),
            "--output",
            str(artifacts["template_analysis.json"]),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/3_section_aligner.py"),
            str(artifacts["template_analysis.json"]),
            "--templates",
            str(reference_templates),
            "--snapshot",
            str(artifacts["page_snapshot.jsonl"]),
            "--output",
            str(artifacts["section_alignment.json"]),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/4_page_structure_builder.py"),
            str(artifacts["page_snapshot.jsonl"]),
            "--profile",
            str(artifacts["page_profile.json"]),
            "--alignment",
            str(artifacts["section_alignment.json"]),
            "--output",
            str(artifacts["page_structure.json"]),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/5_table_recovery.py"),
            str(artifacts["page_structure.json"]),
            str(artifacts["page_snapshot.jsonl"]),
            "--output",
            str(table_dir),
        ],
    )
    expected_bytes = {
        name: path.read_bytes() for name, path in artifacts.items()
    }

    run_profiler(
        pdf_path=sample_pdf,
        profile_output=artifacts["page_profile.json"],
        snapshot_output=artifacts["page_snapshot.jsonl"],
        table_mode="auto",
    )
    run_template_analysis(
        profile_path=artifacts["page_profile.json"],
        template_path=candidate_templates,
        output_path=artifacts["template_analysis.json"],
    )
    run_section_alignment(
        analysis_path=artifacts["template_analysis.json"],
        template_path=candidate_templates,
        snapshot_path=artifacts["page_snapshot.jsonl"],
        output_path=artifacts["section_alignment.json"],
    )
    run_page_structure(
        snapshot_path=artifacts["page_snapshot.jsonl"],
        profile_path=artifacts["page_profile.json"],
        alignment_path=artifacts["section_alignment.json"],
        output_path=artifacts["page_structure.json"],
    )
    run_table_recovery(
        structure_path=artifacts["page_structure.json"],
        snapshot_path=artifacts["page_snapshot.jsonl"],
        output_dir=table_dir,
    )

    for name, path in artifacts.items():
        assert path.read_bytes() == expected_bytes[name], f"first drift: {name}"
