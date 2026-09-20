from hashlib import sha256
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "configs/templates.json",
            "a3c50aafa43c2afece508b27ff9204b47bdf6a0d145547beb22fb3fd4fb546b1",
        ),
        (
            "configs/providers.json",
            "805424d87fb8469230ba0c636957c6b4b83f889a4b6244ff35ef0e67037b0f6e",
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
    """Only the enable split may change retained reference Provider objects."""
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
    for name in candidate:
        migrated = dict(reference[name])
        migrated["benchmark_enabled"] = bool(migrated.pop("enabled"))
        migrated["runtime_enabled"] = True
        expected[name] = migrated
    assert candidate == expected
