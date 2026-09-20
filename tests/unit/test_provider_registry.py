import sys
from pathlib import Path

import pytest


APPROVED_KINDS = {
    "rapidocr",
    "paddleocr_text",
    "paddleocr_vl",
    "docling_worker",
    "mineru_worker",
    "marker_worker",
}


def test_provider_runtime_value_types_have_stable_fields() -> None:
    from pdffast.providers.base import (
        ProviderPreflight,
        ProviderTask,
        RawProviderResult,
    )

    task = ProviderTask(
        task_id="task-1",
        capability_route="REGION_MULTIMODAL_PARSE",
        input_image=Path("input.png"),
        metadata={"page_number": 1},
    )
    preflight = ProviderPreflight(
        provider="rapidocr_ch_light",
        available=True,
        detail="ready",
        metadata={"version": "test"},
    )
    result = RawProviderResult(
        provider="rapidocr_ch_light",
        task_id="task-1",
        status="SUCCEEDED",
        payload={"text": "ok"},
        markdown="ok",
        elapsed_seconds=0.1,
        warnings=("fixture",),
    )

    assert task.input_image == Path("input.png")
    assert preflight.available is True
    assert result.warnings == ("fixture",)


def test_registry_declares_only_approved_lazy_adapter_kinds() -> None:
    from pdffast.providers.registry import DEFAULT_ADAPTER_PATHS

    assert set(DEFAULT_ADAPTER_PATHS) == APPROVED_KINDS
    assert "rapidocr" not in sys.modules
    assert "paddleocr" not in sys.modules
    assert "docling" not in sys.modules
    assert "mineru" not in sys.modules
    assert "marker" not in sys.modules


def test_registry_creates_injected_provider_without_optional_imports() -> None:
    from pdffast.providers.registry import ProviderRegistry

    sentinel = object()
    registry = ProviderRegistry(
        factories={"rapidocr": lambda name, config: (sentinel, name, config)}
    )

    assert registry.create(
        "rapidocr_ch_light",
        {
            "runtime_enabled": True,
            "benchmark_enabled": True,
            "kind": "rapidocr",
            "params": {"lang": "ch"},
        },
    ) == (
        sentinel,
        "rapidocr_ch_light",
        {
            "runtime_enabled": True,
            "benchmark_enabled": True,
            "kind": "rapidocr",
            "params": {"lang": "ch"},
        },
    )


def test_registry_rejects_disabled_provider() -> None:
    from pdffast.providers.registry import ProviderDisabledError, ProviderRegistry

    with pytest.raises(ProviderDisabledError, match="marker_local"):
        ProviderRegistry(factories={}).create(
            "marker_local",
            {
                "runtime_enabled": False,
                "benchmark_enabled": True,
                "kind": "marker_worker",
            },
        )


def test_registry_rejects_unknown_adapter_kind() -> None:
    from pdffast.providers.registry import ProviderRegistry, UnknownProviderKindError

    with pytest.raises(UnknownProviderKindError, match="generic_cli"):
        ProviderRegistry(factories={}).create(
            "rapidocr_ch_light",
            {
                "runtime_enabled": True,
                "benchmark_enabled": False,
                "kind": "generic_cli",
            },
        )
