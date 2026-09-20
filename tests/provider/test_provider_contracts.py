from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pdffast.providers.registry import ProviderRegistry


IN_PROCESS_DEPENDENCY_BY_KIND = {
    "rapidocr": "rapidocr",
    "paddleocr_text": "paddleocr",
    "paddleocr_vl": "paddleocr",
}


PROVIDER_CONFIGS = json.loads(
    Path("configs/providers.json").read_text(encoding="utf-8")
)["providers"]


@pytest.mark.parametrize("provider_name", sorted(PROVIDER_CONFIGS))
def test_real_provider_preflight_is_explicit_pass_or_skip(provider_name: str) -> None:
    config = PROVIDER_CONFIGS[provider_name]
    kind = config["kind"]
    dependency = IN_PROCESS_DEPENDENCY_BY_KIND.get(kind)
    if dependency is not None and importlib.util.find_spec(dependency) is None:
        pytest.skip(f"optional Provider dependency is not installed: {dependency}")
    if dependency is None:
        python_executable = Path(config["python_executable"])
        if not python_executable.is_file():
            pytest.skip(
                f"optional Provider environment is not installed: {python_executable}"
            )

    provider = ProviderRegistry().create(
        provider_name,
        config,
    )
    preflight = provider.preflight()
    assert preflight.available, preflight.detail
