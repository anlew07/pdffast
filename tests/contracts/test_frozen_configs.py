from hashlib import sha256
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "configs/providers.json",
            "9de971e198a849713fcc18db28142140f3a84b184cc3f608440bd14bc4b323da",
        ),
        (
            "configs/frozen/stage9_route_candidates_prod_v001.json",
            "0d999777e130de54ff25248c02cf39ae37e9fe7c5ef9231650aa3304008772d3",
        ),
    ],
)
def test_production_config_checksum(path: str, expected: str) -> None:
    """Catches formatting or content drift in migration-critical configuration."""
    assert sha256(Path(path).read_bytes()).hexdigest() == expected


def test_provider_registry_contains_exact_approved_scope() -> None:
    """Catches accidental migration of experimental adapters or loss of runtime ones."""
    registry = json.loads(Path("configs/providers.json").read_text(encoding="utf-8"))
    assert set(registry["providers"]) == {
        "paddleocr_v5_mobile",
        "paddleocr_vl_16",
        "rapidocr_ch_light",
        "docling_local",
        "mineru_local",
        "marker_local",
    }


def test_retained_provider_objects_equal_explicit_reference_migration() -> None:
    """Only the audited enable, runtime path, and safety migrations may differ."""
    raw_root = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REFERENCE_ROOT is not set")

    candidate = json.loads(
        Path("configs/providers.json").read_text(encoding="utf-8")
    )["providers"]
    reference = json.loads(
        (Path(raw_root) / "configs/stage9_providers_v011.json").read_text(
            encoding="utf-8"
        )
    )["providers"]
    expected = {}
    normalized_candidate = {}
    migrated_python_paths = {
        "docling_local": (".venv-docling/bin/python", "runtimes/docling/.venv/bin/python"),
        "mineru_local": (".venv-mineru/bin/python", "runtimes/mineru/.venv/bin/python"),
        "marker_local": (".venv-marker/bin/python", "runtimes/marker/.venv/bin/python"),
    }
    for name in candidate:
        migrated = dict(reference[name])
        migrated["benchmark_enabled"] = bool(migrated.pop("enabled"))
        migrated["runtime_enabled"] = True
        expected[name] = migrated

        actual = dict(candidate[name])
        actual.pop("required_artifacts", None)
        actual.pop("required_artifact_manifests", None)
        actual.pop("required_artifact_sha256", None)
        actual.pop("required_artifact_trees", None)
        actual.pop("process_sentinel_paths", None)
        actual.pop("force_child_process_group", None)
        if name in migrated_python_paths:
            old_path, new_path = migrated_python_paths[name]
            assert migrated["python_executable"] == old_path
            assert actual["python_executable"] == new_path
            actual["python_executable"] = old_path
        for field in (
            "text_detection_model_dir",
            "text_recognition_model_dir",
            "layout_detection_model_dir",
            "vl_rec_model_dir",
        ):
            actual.pop(field, None)
        if isinstance(actual.get("env"), dict) and isinstance(migrated.get("env"), dict):
            actual["env"] = {
                key: actual["env"][key]
                for key in migrated["env"]
                if key in actual["env"]
            }
        normalized_candidate[name] = actual
    assert normalized_candidate == expected
