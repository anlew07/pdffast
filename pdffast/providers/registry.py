from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from .base import Provider


ProviderFactory = Callable[[str, dict[str, Any]], Provider]


DEFAULT_ADAPTER_PATHS: dict[str, str] = {
    "rapidocr": "pdffast.providers.rapidocr:RapidOCRProvider",
    "paddleocr_text": "pdffast.providers.paddleocr:PaddleOCRTextProvider",
    "paddleocr_vl": "pdffast.providers.paddleocr:PaddleOCRVLProvider",
    "pp_structure_v3": "pdffast.providers.paddleocr:PPStructureV3Provider",
    "docling_worker": "pdffast.providers.docling:DoclingProvider",
    "mineru_worker": "pdffast.providers.mineru:MinerUProvider",
    "marker_worker": "pdffast.providers.marker:MarkerProvider",
}


class ProviderConfigurationError(ValueError):
    """Base error for invalid production Provider configuration."""


class ProviderDisabledError(ProviderConfigurationError):
    """Raised when a disabled Provider is selected by runtime policy."""


class UnknownProviderKindError(ProviderConfigurationError):
    """Raised when configuration requests an unsupported adapter kind."""


def _load_factory(path: str) -> ProviderFactory:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ProviderConfigurationError(f"Invalid Provider factory path: {path}")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    return factory


class ProviderRegistry:
    def __init__(
        self,
        *,
        factories: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        self._factories = dict(factories or {})

    def create(self, name: str, config: dict[str, Any]) -> Provider:
        if config.get("enabled") is not True:
            raise ProviderDisabledError(f"Provider is disabled: {name}")

        kind = str(config.get("kind") or "")
        if kind not in DEFAULT_ADAPTER_PATHS:
            raise UnknownProviderKindError(f"Unsupported Provider kind: {kind}")

        factory = self._factories.get(kind)
        if factory is None:
            factory = _load_factory(DEFAULT_ADAPTER_PATHS[kind])
        return factory(name, config)
