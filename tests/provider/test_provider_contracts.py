from __future__ import annotations

import importlib.util

import pytest

from pdffast.providers.registry import DEFAULT_ADAPTER_PATHS, ProviderRegistry


PRODUCTION_NAME_BY_KIND = {
    "rapidocr": "rapidocr_ch_light",
    "paddleocr_text": "paddleocr_v5_mobile",
    "paddleocr_vl": "paddleocr_vl_16",
    "docling_worker": "docling_local",
    "mineru_worker": "mineru_local",
    "marker_worker": "marker_local",
}


@pytest.mark.parametrize("kind", sorted(DEFAULT_ADAPTER_PATHS))
def test_real_provider_preflight_is_explicit_pass_or_skip(kind: str) -> None:
    dependency = {
        "rapidocr": "rapidocr",
        "paddleocr_text": "paddleocr",
        "paddleocr_vl": "paddleocr",
        "docling_worker": "docling",
        "mineru_worker": "mineru",
        "marker_worker": "marker",
    }[kind]
    if importlib.util.find_spec(dependency) is None:
        pytest.skip(f"optional Provider dependency is not installed: {dependency}")

    provider = ProviderRegistry().create(
        PRODUCTION_NAME_BY_KIND[kind],
        {
            "kind": kind,
            "runtime_enabled": True,
            "benchmark_enabled": True,
        },
    )
    preflight = provider.preflight()
    assert preflight.available, preflight.detail
