from __future__ import annotations

import importlib.util

import pytest

from pdffast.providers.registry import DEFAULT_ADAPTER_PATHS, ProviderRegistry


@pytest.mark.parametrize("kind", sorted(DEFAULT_ADAPTER_PATHS))
def test_real_provider_preflight_is_explicit_pass_or_skip(kind: str) -> None:
    dependency = {
        "rapidocr": "rapidocr",
        "paddleocr_text": "paddleocr",
        "paddleocr_vl": "paddleocr",
        "pp_structure_v3": "paddleocr",
        "docling_worker": "docling",
        "mineru_worker": "mineru",
        "marker_worker": "marker",
    }[kind]
    if importlib.util.find_spec(dependency) is None:
        pytest.skip(f"optional Provider dependency is not installed: {dependency}")

    provider = ProviderRegistry().create(
        kind,
        {"kind": kind, "enabled": True},
    )
    preflight = provider.preflight()
    assert preflight.available, preflight.detail
