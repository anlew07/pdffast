"""Load the trusted inputs for one locked parse or preflight."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError
from pdffast.fallback.policy import validate_candidates
from pdffast.providers.profiles import apply_production_profile, decode_config_json
from pdffast.providers.registry import (
    ProviderRegistry,
    validate_runtime_provider_closure,
)

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = "frozen/stage9_route_candidates_prod_v001.json"

# Adapter bindings identify shipped code. The profile alone chooses the allowed set.
BUILTIN_KINDS = {
    "rapidocr_ch_light": "rapidocr",
    "paddleocr_v5_mobile": "paddleocr_text",
    "paddleocr_vl_16": "paddleocr_vl",
    "docling_local": "docling_worker",
    "mineru_local": "mineru_worker",
    "marker_local": "marker_worker",
}
SHIPPED_PLUGINS = {
    "indra_local": {
        "kind": "indra_worker",
        "factory": "pdffast.providers.indra:IndraProvider",
        "normalizer": "pdffast.providers.indra_normalizer:normalize_indra",
    },
}


@dataclass(frozen=True)
class ProductionProfile:
    root: Path
    name: str
    profile_path: Path
    profile_bytes: bytes
    providers_path: str
    providers_bytes: bytes
    candidates_path: str
    candidates_bytes: bytes
    candidates: dict[str, Any]
    configs: dict[str, dict[str, Any]]
    chains: dict[str, list[str]]
    allowed: tuple[str, ...]
    registry: ProviderRegistry
    plugins: dict[str, dict[str, str]]
    environment: Mapping[str, str] = field(repr=False)


def load_production_profile(config: ParserConfig) -> ProductionProfile:
    if config.provider_profile is None:
        raise ConfigurationError("provider_profile is required for production locking")
    for option in (
        "provider_chain_overrides", "provider_configs", "provider_plugins", "registry", "normalizer"
    ):
        if getattr(config, option) is not None:
            raise ConfigurationError(f"provider_profile cannot be combined with {option}")
    environment = MappingProxyType(dict(os.environ))
    try:
        root = Path(config.project_root or ROOT).expanduser().resolve()
        profile_path = (root / Path(config.provider_profile).expanduser()).resolve()
        config_dir = root / "configs" if config.project_root is not None else files("pdffast.resources.configs")
        providers_path = config_dir.joinpath("providers.json")
        candidates_path = config_dir.joinpath(*CANDIDATES.split("/"))
        profile_bytes = profile_path.read_bytes()
        profile = decode_config_json(profile_bytes)
        providers_bytes = providers_path.read_bytes()
        payload = decode_config_json(providers_bytes)
        if payload.get("provider_chain_overrides") is not None:
            raise ValueError("provider_profile cannot be combined with providers.json overrides")
        configs, chains = apply_production_profile(payload["providers"], profile)
        allowed = tuple(profile["enabled_providers"])
        plugins = payload.get("plugins", {})
        if not isinstance(plugins, dict):
            raise TypeError("plugins must be an object")
        for name in allowed:
            kind = configs[name].get("kind")
            if payload["providers"][name].get("runtime_enabled") is not True:
                raise ValueError(f"{name}: configured Provider is runtime-disabled")
            if name in BUILTIN_KINDS:
                if kind != BUILTIN_KINDS[name] or name in plugins:
                    raise ValueError(f"{name}: Provider kind or plugin does not match shipped adapter")
            elif (
                name not in SHIPPED_PLUGINS
                or plugins.get(name) != SHIPPED_PLUGINS[name]
                or kind != SHIPPED_PLUGINS[name]["kind"]
            ):
                raise ValueError(f"{name}: untrusted Provider plugin or kind")
        registry = ProviderRegistry(
            base_dir=root, plugins={name: plugins[name] for name in allowed if name in plugins},
            environment=environment,
        )
        validate_runtime_provider_closure(
            {"tasks": [
                {"task_id": route, "capability_route": route,
                 "provider_chain": [{"provider": name} for name in chain]}
                for route, chain in chains.items()
            ]},
            configs,
            registry=registry,
            locked_routes=chains,
        )
        candidates_bytes = candidates_path.read_bytes()
        candidates = decode_config_json(candidates_bytes)
        validate_candidates(candidates)
    except (OSError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid provider_profile {config.provider_profile}: {exc}") from exc
    return ProductionProfile(
        root, profile["name"], profile_path, profile_bytes, str(providers_path), providers_bytes,
        str(candidates_path), candidates_bytes, candidates, configs, chains, allowed, registry,
        {name: plugins[name] for name in allowed if name in plugins}, environment,
    )
