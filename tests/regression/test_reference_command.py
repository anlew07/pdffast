import json
from pathlib import Path
import subprocess
import sys

import pytest


def _command_api():
    try:
        from tools.migration.run_reference import (
            build_candidate_command,
            build_reference_command,
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"reference command planner is not implemented: {exc}")
    return build_reference_command, build_candidate_command


def test_reference_command_pins_all_behavior_relevant_arguments() -> None:
    """Catches old/new runs silently using different production parameters."""
    build_reference_command, _ = _command_api()
    cmd = build_reference_command(
        python=Path("/reference/.venv/bin/python"),
        reference_root=Path("/reference"),
        pdf=Path("/samples/case_007.pdf"),
        output_root=Path("/runs/reference"),
        run_id="case_007_parity_v001",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )
    assert cmd == [
        "/reference/.venv/bin/python",
        "/reference/scripts/pipeline_observed_runner.py",
        "/samples/case_007.pdf",
        "--output-root",
        "/runs/reference",
        "--run-id",
        "case_007_parity_v001",
        "--page-dpi",
        "150",
        "--region-dpi",
        "150",
        "--rapidocr-workers",
        "1",
        "--table-mode",
        "auto",
        "--route-candidates",
        "/reference/configs/frozen/stage9_route_candidates_prod_v001.json",
        "--provider-config",
        "/reference/configs/stage9_providers_v011.json",
        "--templates",
        "/reference/configs/templates.json",
    ]


def test_candidate_command_targets_only_the_public_v2_entry() -> None:
    """Catches test tooling depending on future internal stage modules."""
    _, build_candidate_command = _command_api()
    cmd = build_candidate_command(
        python=Path("/candidate/.venv/bin/python"),
        candidate_root=Path("/candidate"),
        pdf=Path("/samples/case_007.pdf"),
        output_root=Path("/runs/candidate"),
        run_id="case_007_parity_v001",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )
    assert cmd[:3] == [
        "/candidate/.venv/bin/python",
        "/candidate/scripts/run_pipeline.py",
        "/samples/case_007.pdf",
    ]
    assert "/candidate/configs/providers.json" in cmd


def test_cli_plans_without_executing(tmp_path: Path) -> None:
    """Catches accidental execution while a user is only reviewing commands."""
    missing_pdf = tmp_path / "does-not-exist.pdf"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.migration.run_reference",
            "--reference-root",
            "/reference",
            "--candidate-root",
            "/candidate",
            "--pdf",
            str(missing_pdf),
            "--reference-output-root",
            "/runs/reference",
            "--candidate-output-root",
            "/runs/candidate",
            "--run-id",
            "fixed",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    planned = json.loads(result.stdout)
    assert planned["reference_command"][1] == (
        "/reference/scripts/pipeline_observed_runner.py"
    )
    assert planned["candidate_command"][1] == "/candidate/scripts/run_pipeline.py"
    assert not missing_pdf.exists()


def test_cli_execute_rejects_missing_pdf(tmp_path: Path) -> None:
    """Catches subprocess launch before destructive-target validation."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.migration.run_reference",
            "--reference-root",
            "/reference",
            "--candidate-root",
            "/candidate",
            "--pdf",
            str(tmp_path / "missing.pdf"),
            "--reference-output-root",
            str(tmp_path / "reference-runs"),
            "--candidate-output-root",
            str(tmp_path / "candidate-runs"),
            "--run-id",
            "fixed",
            "--execute",
            "reference",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "PDF does not exist" in result.stderr
