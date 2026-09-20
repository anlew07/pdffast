import json
from pathlib import Path

import pytest


PRODUCTION_NAMES = {
    "rapidocr_ch_light",
    "paddleocr_v5_mobile",
    "paddleocr_vl_16",
    "mineru_local",
    "marker_local",
    "docling_local",
}

PRODUCTION_KINDS = {
    "rapidocr",
    "paddleocr_text",
    "paddleocr_vl",
    "mineru_worker",
    "marker_worker",
    "docling_worker",
}


def _config(name: str, kind: str, *, runtime: bool, benchmark: bool) -> dict:
    return {
        "runtime_enabled": runtime,
        "benchmark_enabled": benchmark,
        "kind": kind,
        "name_for_test": name,
    }


def _policy(*providers: str) -> dict:
    return {
        "tasks": [
            {
                "task_id": "task-1",
                "provider_chain": [{"provider": name} for name in providers],
            }
        ]
    }


def test_production_config_contains_exact_runtime_closure_and_explicit_flags() -> None:
    config = json.loads(Path("configs/providers.json").read_text(encoding="utf-8"))
    providers = config["providers"]

    assert set(providers) == PRODUCTION_NAMES
    assert "pp_structure_v3_light" not in providers
    for provider in providers.values():
        assert provider["runtime_enabled"] is True
        assert isinstance(provider["benchmark_enabled"], bool)
        assert "enabled" not in provider


def test_registry_declares_only_production_adapter_kinds() -> None:
    from pdffast.providers.registry import DEFAULT_ADAPTER_PATHS

    assert set(DEFAULT_ADAPTER_PATHS) == PRODUCTION_KINDS
    assert "pp_structure_v3" not in DEFAULT_ADAPTER_PATHS


def test_all_six_production_providers_resolve_without_optional_imports() -> None:
    from pdffast.providers.registry import ProviderRegistry

    providers = json.loads(
        Path("configs/providers.json").read_text(encoding="utf-8")
    )["providers"]
    factories = {
        kind: (lambda name, config: (name, config["kind"]))
        for kind in PRODUCTION_KINDS
    }
    registry = ProviderRegistry(factories=factories)

    assert {
        registry.create(name, config)
        for name, config in providers.items()
    } == {(name, config["kind"]) for name, config in providers.items()}


def test_benchmark_disabled_production_provider_still_resolves() -> None:
    from pdffast.providers.registry import ProviderRegistry

    registry = ProviderRegistry(
        factories={"mineru_worker": lambda name, config: name}
    )

    assert registry.create(
        "mineru_local",
        _config("mineru_local", "mineru_worker", runtime=True, benchmark=False),
    ) == "mineru_local"


def test_runtime_disabled_provider_cannot_resolve() -> None:
    from pdffast.providers.registry import ProviderDisabledError, ProviderRegistry

    registry = ProviderRegistry(
        factories={"marker_worker": lambda name, config: name}
    )

    with pytest.raises(ProviderDisabledError, match="marker_local"):
        registry.create(
            "marker_local",
            _config("marker_local", "marker_worker", runtime=False, benchmark=True),
        )


def test_legacy_enabled_is_not_accepted_as_runtime_authority() -> None:
    from pdffast.providers.registry import ProviderDisabledError, ProviderRegistry

    registry = ProviderRegistry(
        factories={"rapidocr": lambda name, config: name}
    )

    with pytest.raises(ProviderDisabledError, match="runtime_enabled"):
        registry.create(
            "rapidocr_ch_light",
            {"enabled": True, "kind": "rapidocr"},
        )


def test_closure_validation_accepts_runtime_enabled_policy_set() -> None:
    from pdffast.providers.registry import validate_runtime_provider_closure

    configs = {
        "rapidocr_ch_light": _config(
            "rapidocr_ch_light", "rapidocr", runtime=True, benchmark=True
        ),
        "mineru_local": _config(
            "mineru_local", "mineru_worker", runtime=True, benchmark=False
        ),
    }

    assert validate_runtime_provider_closure(
        _policy("rapidocr_ch_light", "mineru_local"), configs
    ) == frozenset({"rapidocr_ch_light", "mineru_local"})


def test_closure_validation_rejects_missing_provider() -> None:
    from pdffast.providers.registry import (
        ProviderClosureError,
        validate_runtime_provider_closure,
    )

    with pytest.raises(ProviderClosureError, match="mineru_local.*missing"):
        validate_runtime_provider_closure(
            _policy("rapidocr_ch_light", "mineru_local"),
            {
                "rapidocr_ch_light": _config(
                    "rapidocr_ch_light", "rapidocr", runtime=True, benchmark=True
                )
            },
        )


def test_closure_validation_rejects_runtime_disabled_provider() -> None:
    from pdffast.providers.registry import (
        ProviderClosureError,
        validate_runtime_provider_closure,
    )

    with pytest.raises(ProviderClosureError, match="marker_local.*runtime-disabled"):
        validate_runtime_provider_closure(
            _policy("marker_local"),
            {
                "marker_local": _config(
                    "marker_local", "marker_worker", runtime=False, benchmark=True
                )
            },
        )


def test_closure_validation_rejects_nonproduction_adapter_kind() -> None:
    from pdffast.providers.registry import (
        ProviderClosureError,
        validate_runtime_provider_closure,
    )

    with pytest.raises(ProviderClosureError, match="pp_structure_v3_light.*unsupported"):
        validate_runtime_provider_closure(
            _policy("pp_structure_v3_light"),
            {
                "pp_structure_v3_light": _config(
                    "pp_structure_v3_light",
                    "pp_structure_v3",
                    runtime=True,
                    benchmark=True,
                )
            },
        )
