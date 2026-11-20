"""Read-only environment inventory tests, without provider imports or model downloads."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.audit_environment import audit, main, resolve, _profile_selection

LOCKS = (
    "pyproject.toml", "uv.lock",
    "runtimes/mineru/pyproject.toml", "runtimes/mineru/uv.lock",
    "runtimes/marker/pyproject.toml", "runtimes/marker/uv.lock",
    "runtimes/docling/pyproject.toml", "runtimes/docling/uv.lock",
)


def repository(tmp_path: Path) -> Path:
    root = tmp_path / "pdffast"
    for filename in LOCKS:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stub", encoding="utf-8")
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("stub")
    providers = {
        "rapidocr_ch_light": {
            "kind": "rapidocr", "runtime_enabled": True,
            "required_artifacts": ["fixtures/rapid.onnx"],
            "required_artifact_sha256": {
                "fixtures/rapid.onnx": hashlib.sha256(b"good").hexdigest()
            },
        },
        "indra_local": {
            "kind": "indra_worker", "runtime_enabled": True,
            "python_executable": "runtimes/indra/.venv/bin/python",
            "required_artifacts": ["runtimes/indra/models/indra-ocr/det.onnx"],
        },
    }
    config = root / "configs/providers.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"providers": providers}), encoding="utf-8")
    return root


def test_clean_clone_inventory_reports_missing_artifacts_without_creating_them(tmp_path):
    root = repository(tmp_path)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    report = audit(root)
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    assert before == after
    assert report["summary"]["failed"] > 0
    assert not report["summary"]["artifact_files_present"]
    assert report["provider_selection"] == "all_runtime_enabled"
    assert report["providers"] == ["indra_local", "rapidocr_ch_light"]
    assert report["not_checked"]


def test_selected_profile_does_not_require_unselected_indra_files(tmp_path):
    root = repository(tmp_path)
    (root / "fixtures").mkdir()
    (root / "fixtures/rapid.onnx").write_bytes(b"good")
    profile = root / "configs/profiles/production.speed.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({
        "schema_version": "1.0", "name": "speed",
        "enabled_providers": ["rapidocr_ch_light"],
        "chains": {route: ["rapidocr_ch_light"] for route in (
            "PAGE_DOCUMENT_OCR", "PAGE_DOCUMENT_LAYOUT_PARSE",
            "REGION_MULTIMODAL_PARSE", "INLINE_CONTEXT_PARSE")},
    }), encoding="utf-8")
    report = audit(root, profile=Path("configs/profiles/production.speed.json"), hashes=True)
    assert report["summary"]["artifact_files_present"]
    assert report["providers"] == ["rapidocr_ch_light"]
    assert not [item for item in report["checks"] if "indra" in item["id"]]


def test_model_hash_failure_is_not_silently_accepted(tmp_path):
    root = repository(tmp_path)
    (root / "fixtures").mkdir()
    (root / "fixtures/rapid.onnx").write_bytes(b"wrong")
    result = audit(root, hashes=True)
    mismatches = [item for item in result["checks"] if item["id"].startswith(
        "provider:rapidocr_ch_light:sha256")]
    assert len(mismatches) == 1
    assert mismatches[0]["status"] == "MISSING_OR_INVALID"


def test_indra_model_without_manifest_is_not_reproducible(tmp_path):
    root = repository(tmp_path)
    model = root / "runtimes/indra/models/indra-ocr"
    model.mkdir(parents=True)
    (model / "det.onnx").write_bytes(b"x")
    report = audit(root)
    assert any(item["id"] == "indra:manifest" and item["status"] == "MISSING_OR_INVALID"
               for item in report["checks"])


def test_invalid_profile_is_rejected(tmp_path):
    root = repository(tmp_path)
    file = root / "bad.json"
    file.write_text(json.dumps({"schema_version": "1.0",
                                "enabled_providers": ["rapidocr_ch_light"],
                                "chains": {}}))
    import pytest
    with pytest.raises(ValueError, match="四条"):
        audit(root, profile=file)


def test_cli_strict_and_inventory_exit_codes(tmp_path):
    root = repository(tmp_path)
    script = Path(__file__).resolve().parents[2] / "scripts/audit_environment.py"
    cmd = [sys.executable, str(script), "--root", str(root), "--format", "json"]
    inventory = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert inventory.returncode == 0
    assert json.loads(inventory.stdout)["summary"]["failed"] > 0
    strict = subprocess.run([*cmd, "--strict"], capture_output=True, text=True,
                            check=False)
    assert strict.returncode == 1
