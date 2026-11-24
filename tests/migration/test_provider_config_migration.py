"""Explicit opt-in comparison against the archived V2 provider registry."""

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.migration


def test_retained_provider_objects_equal_explicit_reference_migration() -> None:
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required for migration parity")

    candidate = json.loads(Path("configs/providers.json").read_text(encoding="utf-8"))["providers"]
    reference = json.loads(
        (Path(raw_root) / "configs/stage9_providers_v011.json").read_text(encoding="utf-8")
    )["providers"]
    expected = {}
    normalized_candidate = {}
    migrated_python_paths = {
        "docling_local": (".venv-docling/bin/python", "runtimes/docling/.venv/bin/python"),
        "mineru_local": (".venv-mineru/bin/python", "runtimes/mineru/.venv/bin/python"),
        "marker_local": (".venv-marker/bin/python", "runtimes/marker/.venv/bin/python"),
    }
    assert set(candidate) - set(reference) == {"indra_local"}
    for name in set(candidate) & set(reference):
        migrated = dict(reference[name])
        migrated["benchmark_enabled"] = bool(migrated.pop("enabled"))
        migrated["runtime_enabled"] = True
        expected[name] = migrated

        actual = dict(candidate[name])
        for field in (
            "model_asset_manifest", "required_artifacts", "required_artifact_manifests",
            "required_artifact_sha256", "required_artifact_trees",
            "process_sentinel_paths", "force_child_process_group",
        ):
            actual.pop(field, None)
        if name in migrated_python_paths:
            old_path, new_path = migrated_python_paths[name]
            assert migrated["python_executable"] == old_path
            assert actual["python_executable"] == new_path
            actual["python_executable"] = old_path
        for field in (
            "text_detection_model_dir", "text_recognition_model_dir",
            "layout_detection_model_dir", "vl_rec_model_dir",
        ):
            actual.pop(field, None)
        if isinstance(actual.get("env"), dict) and isinstance(migrated.get("env"), dict):
            actual_env = dict(actual["env"])
            reference_env = dict(migrated["env"])
            if name == "marker_local":
                current_home = "${HOME}/Library/Caches/pdffast/marker-workers/${PDFFAST_WORKER_ID}"
                assert actual_env.get("HOME") == current_home
                reference_env["HOME"] = current_home
            actual["env"] = {
                key: actual_env[key]
                for key in reference_env
                if key in actual_env
            }
            migrated["env"] = reference_env
        normalized_candidate[name] = actual
    assert normalized_candidate == expected
