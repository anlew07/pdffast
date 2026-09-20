import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_reference_source_matches_committed_manifest() -> None:
    """Catches reference drift before a parity comparison becomes misleading."""
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is not set")

    try:
        from tools.migration.baseline import capture_manifest
    except ModuleNotFoundError as exc:
        pytest.fail(f"reference baseline capture is not implemented: {exc}")

    manifest_path = Path("tests/contracts/reference_source_manifest.json")
    assert manifest_path.is_file(), "committed reference manifest is missing"
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = capture_manifest(Path(raw_root))
    assert actual == expected


def test_baseline_cli_refuses_overwrite_and_supports_check(tmp_path: Path) -> None:
    """Catches silent baseline replacement, which could hide reference drift."""
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is not set")

    output = tmp_path / "manifest.json"
    base_cmd = [
        sys.executable,
        "-m",
        "tools.migration.baseline",
        "--reference-root",
        raw_root,
        "--output",
        str(output),
    ]

    created = subprocess.run(base_cmd, text=True, capture_output=True)
    assert created.returncode == 0, created.stderr
    assert output.is_file()

    refused = subprocess.run(base_cmd, text=True, capture_output=True)
    assert refused.returncode != 0
    assert "exists" in refused.stderr.lower()

    checked = subprocess.run([*base_cmd, "--check"], text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
