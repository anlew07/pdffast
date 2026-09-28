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


TEXT_FLOW_ARTIFACTS = (
    "noise_candidates.json",
    "noise_candidates.md",
    "reading_order.json",
    "reading_order.md",
    "paragraphs.json",
    "paragraphs.md",
    "cross_page_paragraphs.json",
    "cross_page_paragraphs.md",
    "normalized_text_flow.json",
    "normalized_text_flow.md",
    "readable_final.md",
)


def test_text_flow_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Catches any Stage 6 substage, ownership, or rendering drift."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.native.text_flow import run_text_flow
    except ModuleNotFoundError as exc:
        pytest.fail(f"text flow migration is not implemented: {exc}")

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

    reference_output = tmp_path / "reference/text_flow"
    candidate_output = tmp_path / "candidate/text_flow"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/6_text_flow_normalizer.py"),
            str(snapshot),
            str(structure),
            str(table_dir / "result.json"),
            "--output",
            str(reference_output),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    from pdffast.native.text_flow import create_text_flow_result, write_text_flow_result

    flow_kwargs = dict(
        snapshot_path=snapshot,
        structure_path=structure,
        table_result_path=table_dir / "result.json",
    )
    flow = create_text_flow_result(**flow_kwargs)
    write_text_flow_result(flow, candidate_output)
    object_artifacts = {
        name: (candidate_output / name).read_bytes() for name in TEXT_FLOW_ARTIFACTS
    }
    assert run_text_flow(**flow_kwargs, output_dir=candidate_output) == flow.normalized_flow
    for name in TEXT_FLOW_ARTIFACTS:
        assert (candidate_output / name).read_bytes() == object_artifacts[name]
        assert (candidate_output / name).read_bytes() == (
            reference_output / name
        ).read_bytes(), f"artifact drift: {name}"
