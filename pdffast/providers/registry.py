from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from .base import Provider


ProviderFactory = Callable[[str, dict[str, Any]], Provider]


PRODUCTION_PROVIDER_NAMES = frozenset(
    {
        "rapidocr_ch_light",
        "paddleocr_v5_mobile",
        "paddleocr_vl_16",
        "mineru_local",
        "marker_local",
        "docling_local",
    }
)


DEFAULT_ADAPTER_PATHS: dict[str, str] = {
    "rapidocr": "pdffast.providers.rapidocr:RapidOCRProvider",
    "paddleocr_text": "pdffast.providers.paddleocr:PaddleOCRTextProvider",
    "paddleocr_vl": "pdffast.providers.paddleocr:PaddleOCRVLProvider",
    "docling_worker": "pdffast.providers.docling:DoclingProvider",
    "mineru_worker": "pdffast.providers.mineru:MinerUProvider",
    "marker_worker": "pdffast.providers.marker:MarkerProvider",
}


class ProviderConfigurationError(ValueError):
    """Base error for invalid production Provider configuration."""


class ProviderDisabledError(ProviderConfigurationError):
    """Raised when a runtime-disabled Provider is selected by production policy."""


class UnknownProviderKindError(ProviderConfigurationError):
    """Raised when configuration requests an unsupported production adapter kind."""


class ProviderClosureError(ProviderConfigurationError):
    """Raised when policy references cannot be resolved before execution."""


def _load_factory(path: str) -> ProviderFactory:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise ProviderConfigurationError(f"Invalid Provider factory path: {path}")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    return factory


def _policy_provider_names(policy: dict[str, Any]) -> frozenset[str]:
    tasks = policy.get("tasks")
    if not isinstance(tasks, list):
        raise ProviderClosureError("runtime policy must contain tasks[]")
    names: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ProviderClosureError("runtime policy tasks must be objects")
        task_id = str(task.get("task_id") or "<unknown>")
        chain = task.get("provider_chain")
        if not isinstance(chain, list) or not chain:
            raise ProviderClosureError(f"task={task_id}: provider_chain is empty")
        for entry in chain:
            name = str(entry.get("provider") or "") if isinstance(entry, dict) else ""
            if not name:
                raise ProviderClosureError(
                    f"task={task_id}: provider_chain contains an invalid entry"
                )
            names.add(name)
    return frozenset(names)


def validate_runtime_provider_closure(
    policy: dict[str, Any],
    provider_configs: Mapping[str, dict[str, Any]],
) -> frozenset[str]:
    """Validate every policy reference before any Provider or artifact is created."""
    names = _policy_provider_names(policy)
    errors: list[str] = []
    for name in sorted(names):
        config = provider_configs.get(name)
        if not isinstance(config, dict):
            errors.append(f"{name}: missing from runtime registry")
            continue
        if config.get("runtime_enabled") is not True:
            errors.append(f"{name}: runtime-disabled")
            continue
        kind = str(config.get("kind") or "")
        if name not in PRODUCTION_PROVIDER_NAMES or kind not in DEFAULT_ADAPTER_PATHS:
            errors.append(f"{name}: unsupported production adapter kind={kind!r}")
    if errors:
        raise ProviderClosureError("; ".join(errors))
    return names


class ProviderRegistry:
    def __init__(
        self,
        *,
        factories: Mapping[str, ProviderFactory] | None = None,
    ) -> None:
        self._factories = dict(factories or {})

    def create(self, name: str, config: dict[str, Any]) -> Provider:
        if config.get("runtime_enabled") is not True:
            raise ProviderDisabledError(
                f"Provider runtime_enabled is not true: {name}"
            )
        if name not in PRODUCTION_PROVIDER_NAMES:
            raise ProviderConfigurationError(
                f"Provider is outside the production closure: {name}"
            )

        kind = str(config.get("kind") or "")
        if kind not in DEFAULT_ADAPTER_PATHS:
            raise UnknownProviderKindError(f"Unsupported Provider kind: {kind}")

        factory = self._factories.get(kind)
        if factory is None:
            factory = _load_factory(DEFAULT_ADAPTER_PATHS[kind])
        return factory(name, config)
