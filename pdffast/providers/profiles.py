"""Production Provider configuration profiles; no runtime mutation or model loading.

Profiles select the enabled Provider set and complete capability-route chains.
The default historical policy is unchanged when no profile is supplied.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

REQUIRED_ROUTES = frozenset({
    "PAGE_DOCUMENT_OCR",
    "PAGE_DOCUMENT_LAYOUT_PARSE",
    "REGION_MULTIMODAL_PARSE",
    "INLINE_CONTEXT_PARSE",
})


class ProviderProfileError(ValueError):
    """A profile cannot be safely applied to a production Provider registry."""


def load_provider_profile(path: Path) -> dict[str, Any]:
    """Read a trusted, local profile. Never accept a path supplied by a PDF."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderProfileError(f"unable to read Provider profile {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProviderProfileError("Provider profile must be a JSON object")
    return data


def apply_production_profile(
    provider_configs: Mapping[str, dict[str, Any]],
    profile: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Return fresh configs and route overrides; never modify caller data.

    Require all routes so disabling unused Providers cannot leave hard-coded
    fallback candidates in production. Route semantics/acceptance do not change.
    """
    if not isinstance(profile, Mapping):
        raise ProviderProfileError("profile must be an object")
    if profile.get("schema_version") != "1.0":
        raise ProviderProfileError("profile schema_version must be 1.0")
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        raise ProviderProfileError("profile must have a nonempty name")

    enabled = profile.get("enabled_providers")
    if (
        not isinstance(enabled, list) or not enabled or len(enabled) > 10
        or any(not isinstance(name, str) or not name.strip() for name in enabled)
        or len(enabled) != len(set(enabled))
    ):
        raise ProviderProfileError("enabled_providers must have 1–10 distinct names")
    if not isinstance(provider_configs, Mapping):
        raise ProviderProfileError("provider_configs must be a mapping")

    unknown = set(enabled) - set(provider_configs)
    if unknown:
        raise ProviderProfileError(f"unknown enabled Provider(s): {sorted(unknown)}")

    chains = profile.get("chains")
    if not isinstance(chains, dict) or set(chains) != REQUIRED_ROUTES:
        missing = sorted(REQUIRED_ROUTES - set(chains or {}) if isinstance(chains, dict) else REQUIRED_ROUTES)
        extra = sorted(set(chains) - REQUIRED_ROUTES) if isinstance(chains, dict) else []
        raise ProviderProfileError(f"production profile must define all four routes; missing={missing}; unknown={extra}")

    allowed = set(enabled)
    clean: dict[str, list[str]] = {}
    used: set[str] = set()
    for route in sorted(REQUIRED_ROUTES):
        names = chains[route]
        if (
            not isinstance(names, list) or not names or len(names) > 10
            or any(not isinstance(x, str) or not x.strip() for x in names)
            or len(names) != len(set(names))
        ):
            raise ProviderProfileError(f"{route}: chain must have 1–10 distinct Provider names")
        if not set(names) <= allowed:
            raise ProviderProfileError(f"{route}: references disabled/unknown Provider(s): {sorted(set(names) - allowed)}")
        clean[route] = list(names)
        used.update(names)
    if used != allowed:
        raise ProviderProfileError(f"enabled Providers unused by all routes: {sorted(allowed - used)}")

    configs = deepcopy(dict(provider_configs))
    for name, item in configs.items():
        if not isinstance(item, dict):
            raise ProviderProfileError(f"{name}: provider config must be an object")
        item["runtime_enabled"] = name in allowed
    return configs, clean
