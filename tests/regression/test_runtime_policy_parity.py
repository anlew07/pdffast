import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.fallback.planner import run_fallback_planning
from pdffast.fallback.router import run_capability_routing
from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import run_text_flow
from pdffast.quality.evidence import run_evidence_manifest
from pdffast.quality.gate import run_quality_gate
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis
from tools.migration.baseline import capture_manifest


def test_runtime_policy_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Catches Stage 9.6.3 provider-chain, acceptance, or terminal drift."""
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    sample_pdf_raw = os.environ.get("PDFFAST_SAMPLE_PDF")
    if not reference_root_raw or not sample_pdf_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT and PDFFAST_SAMPLE_PDF are required")

    try:
        from pdffast.fallback.policy import run_runtime_policy
    except ModuleNotFoundError as exc:
        pytest.fail(f"runtime policy migration is not implemented: {exc}")

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
    evidence_dir = shared / "evidence"
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
    run_text_flow(
        snapshot_path=snapshot,
        structure_path=structure,
        table_result_path=table_dir / "result.json",
        output_dir=text_flow_dir,
    )
    run_evidence_manifest(
        profile_path=profile,
        snapshot_path=snapshot,
        template_path=analysis,
        alignment_path=alignment,
        structure_path=structure,
        stage5_path=table_dir / "result.json",
        stage6_dir=text_flow_dir,
        output_dir=evidence_dir,
    )

    quality_dir = shared / "quality_gate"
    run_quality_gate(
        manifest_path=evidence_dir / "evidence_manifest.json",
        pdf_path=sample_pdf,
        output_dir=quality_dir,
        probe_dpi=200,
        save_probe_crops=True,
    )

    planning_dir = shared / "fallback_planning"
    run_fallback_planning(
        quality_gate_path=quality_dir / "quality_gate.json",
        pdf_path=sample_pdf,
        output_dir=planning_dir,
        page_dpi=300,
        region_dpi=300,
        render_inputs=True,
    )

    routing_dir = shared / "provider_routing"
    run_capability_routing(
        manifest_path=planning_dir / "fallback_execution_manifest.json",
        output_dir=routing_dir,
    )

    output_dir = shared / "runtime_policy"
    completed = subprocess.run(
        [
            str(reference_root / ".venv/bin/python"),
            str(reference_root / "scripts/9_6_3_runtime_escalation_policy.py"),
            "--provider-plan",
            str(routing_dir / "provider_plan.json"),
            "--route-candidates",
            str(reference_root / "configs/frozen/stage9_route_candidates_prod_v001.json"),
            "--output",
            str(output_dir),
        ],
        cwd=reference_root,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    expected = {
        path.relative_to(output_dir): path.read_bytes()
        for path in output_dir.rglob("*")
        if path.is_file()
    }

    run_runtime_policy(
        provider_plan_path=routing_dir / "provider_plan.json",
        route_candidates_path=Path(
            "configs/frozen/stage9_route_candidates_prod_v001.json"
        ).resolve(),
        output_dir=output_dir,
    )
    actual_paths = {
        path.relative_to(output_dir)
        for path in output_dir.rglob("*")
        if path.is_file()
    }
    assert actual_paths == set(expected)
    for relative_path, expected_bytes in expected.items():
        assert (output_dir / relative_path).read_bytes() == expected_bytes, (
            f"artifact drift: {relative_path}"
        )
