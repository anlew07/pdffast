from pathlib import Path
import subprocess
import sys

import pytest


FIXTURES = Path("tests/fixtures/artifacts")


def _comparison_api():
    try:
        from tools.migration.compare_artifacts import (
            RootMapping,
            compare_bytes,
            compare_json,
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"artifact comparator is not implemented: {exc}")
    return RootMapping, compare_bytes, compare_json


def _roots(RootMapping):
    return RootMapping(
        reference_project=Path("/reference"),
        candidate_project=Path("/candidate"),
        reference_run=Path("/reference/outputs/reference_run"),
        candidate_run=Path("/candidate/outputs/candidate_run"),
    )


def test_json_comparison_ignores_only_approved_runtime_metadata() -> None:
    """Catches false diffs from runtime metadata without hiding literal text."""
    RootMapping, _, compare_json = _comparison_api()
    result = compare_json(
        FIXTURES / "reference.json",
        FIXTURES / "candidate_runtime_only.json",
        _roots(RootMapping),
    )
    assert result.equal is True
    assert result.diff == ""


def test_json_comparison_reports_first_semantic_json_pointer() -> None:
    """Catches text drift even when every allowed metadata field differs too."""
    RootMapping, _, compare_json = _comparison_api()
    result = compare_json(
        FIXTURES / "reference.json",
        FIXTURES / "candidate_semantic_change.json",
        _roots(RootMapping),
    )
    assert result.equal is False
    assert "/records/0/text" in result.summary
    assert "changed semantic text" in result.diff


def test_markdown_requires_byte_equality() -> None:
    """Catches whitespace drift in the final downstream-facing artifact."""
    _, compare_bytes, _ = _comparison_api()
    result = compare_bytes(
        FIXTURES / "reference.md",
        FIXTURES / "candidate.md",
    )
    assert result.equal is False
    assert result.diff


def test_cli_exit_code_distinguishes_equal_and_different() -> None:
    """Catches a regression command that reports differences but exits zero."""
    common = [
        sys.executable,
        "-m",
        "tools.migration.compare_artifacts",
        "--kind",
        "json",
        "--reference",
        str(FIXTURES / "reference.json"),
        "--reference-root",
        "/reference",
        "--candidate-root",
        "/candidate",
        "--reference-run-root",
        "/reference/outputs/reference_run",
        "--candidate-run-root",
        "/candidate/outputs/candidate_run",
    ]
    equal = subprocess.run(
        [
            *common,
            "--candidate",
            str(FIXTURES / "candidate_runtime_only.json"),
        ],
        text=True,
        capture_output=True,
    )
    different = subprocess.run(
        [
            *common,
            "--candidate",
            str(FIXTURES / "candidate_semantic_change.json"),
        ],
        text=True,
        capture_output=True,
    )
    assert equal.returncode == 0, equal.stderr
    assert different.returncode == 1
    assert "/records/0/text" in different.stdout
