import json
import os
from pathlib import Path
import subprocess

import pytest

from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import run_text_flow
from pdffast.quality.evidence import run_evidence_manifest
from pdffast.quality.gate import run_quality_gate
from pdffast.fallback.planner import run_fallback_planning
from pdffast.fallback.router import run_capability_routing
from pdffast.fallback.policy import run_runtime_policy
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


def test_phase2_pipeline_artifacts_are_byte_identical(tmp_path: Path) -> None:
    """Runs Stages 1-9.6.3 in both trees and compares every produced file."""
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
    text_flow_dir = shared / "text_flow"
    evidence_dir = shared / "evidence"
    quality_dir = shared / "quality_gate"
    planning_dir = shared / "fallback_planning"
    routing_dir = shared / "provider_routing"
    policy_dir = shared / "runtime_policy"
    artifacts = {
        "page_profile.json": shared / "page_profile.json",
        "page_snapshot.jsonl": shared / "page_snapshot.jsonl",
        "template_analysis.json": shared / "template_analysis.json",
        "section_alignment.json": shared / "section_alignment.json",
        "page_structure.json": shared / "page_structure.json",
        "table_recovery/result.json": table_dir / "result.json",
        "table_recovery/result.md": table_dir / "result.md",
        "table_recovery/logical_tables.md": table_dir / "logical_tables.md",
        **{
            f"text_flow/{name}": text_flow_dir / name
            for name in (
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
        },
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
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/6_text_flow_normalizer.py"),
            str(artifacts["page_snapshot.jsonl"]),
            str(artifacts["page_structure.json"]),
            str(artifacts["table_recovery/result.json"]),
            "--output",
            str(text_flow_dir),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/7_native_evidence_manifest.py"),
            "--profile", str(artifacts["page_profile.json"]),
            "--snapshot", str(artifacts["page_snapshot.jsonl"]),
            "--template", str(artifacts["template_analysis.json"]),
            "--alignment", str(artifacts["section_alignment.json"]),
            "--structure", str(artifacts["page_structure.json"]),
            "--stage5", str(artifacts["table_recovery/result.json"]),
            "--stage6-dir", str(text_flow_dir),
            "--output", str(evidence_dir),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/8_quality_gate.py"),
            "--manifest", str(evidence_dir / "evidence_manifest.json"),
            "--pdf", str(sample_pdf),
            "--output", str(quality_dir),
            "--save-probe-crops",
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/9_1_fallback_unit_builder.py"),
            "--quality-gate", str(quality_dir / "quality_gate.json"),
            "--pdf", str(sample_pdf),
            "--output", str(planning_dir),
            "--page-dpi", "300",
            "--region-dpi", "300",
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/9_2_provider_router.py"),
            "--manifest", str(planning_dir / "fallback_execution_manifest.json"),
            "--output", str(routing_dir),
        ],
    )
    _run_reference(
        reference_root,
        [
            str(reference_root / "scripts/9_6_3_runtime_escalation_policy.py"),
            "--provider-plan", str(routing_dir / "provider_plan.json"),
            "--route-candidates",
            str(reference_root / "configs/frozen/stage9_route_candidates_prod_v001.json"),
            "--output", str(policy_dir),
        ],
    )
    expected_files = {
        path.relative_to(shared): path.read_bytes()
        for path in shared.rglob("*")
        if path.is_file()
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
    run_text_flow(
        snapshot_path=artifacts["page_snapshot.jsonl"],
        structure_path=artifacts["page_structure.json"],
        table_result_path=artifacts["table_recovery/result.json"],
        output_dir=text_flow_dir,
    )
    run_evidence_manifest(
        profile_path=artifacts["page_profile.json"],
        snapshot_path=artifacts["page_snapshot.jsonl"],
        template_path=artifacts["template_analysis.json"],
        alignment_path=artifacts["section_alignment.json"],
        structure_path=artifacts["page_structure.json"],
        stage5_path=artifacts["table_recovery/result.json"],
        stage6_dir=text_flow_dir,
        output_dir=evidence_dir,
    )
    run_quality_gate(
        manifest_path=evidence_dir / "evidence_manifest.json",
        pdf_path=sample_pdf,
        output_dir=quality_dir,
        probe_dpi=200,
        save_probe_crops=True,
    )
    run_fallback_planning(
        quality_gate_path=quality_dir / "quality_gate.json",
        pdf_path=sample_pdf,
        output_dir=planning_dir,
        page_dpi=300,
        region_dpi=300,
        render_inputs=True,
    )
    run_capability_routing(
        manifest_path=planning_dir / "fallback_execution_manifest.json",
        output_dir=routing_dir,
    )
    run_runtime_policy(
        provider_plan_path=routing_dir / "provider_plan.json",
        route_candidates_path=Path(
            "configs/frozen/stage9_route_candidates_prod_v001.json"
        ).resolve(),
        output_dir=policy_dir,
    )

    actual_paths = {
        path.relative_to(shared)
        for path in shared.rglob("*")
        if path.is_file()
    }
    assert actual_paths == set(expected_files)
    for relative_path, expected_bytes in expected_files.items():
        assert (shared / relative_path).read_bytes() == expected_bytes, (
            f"first drift: {relative_path}"
        )
