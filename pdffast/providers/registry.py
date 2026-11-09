from __future__ import annotations

import importlib
from hashlib import sha256
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
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
    if not callable(factory):
        raise ProviderConfigurationError(f"Provider entrypoint is not callable: {path}")
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
    *,
    registry: Any | None = None,
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
        supports = getattr(registry, "supports", None)
        allowed = (
            bool(supports(name, kind))
            if callable(supports)
            else name in PRODUCTION_PROVIDER_NAMES and kind in DEFAULT_ADAPTER_PATHS
        )
        if not allowed:
            errors.append(f"{name}: unsupported production adapter kind={kind!r}")
    if errors:
        raise ProviderClosureError("; ".join(errors))
    return names


class ProviderRegistry:
    def __init__(
        self,
        *,
        factories: Mapping[str, ProviderFactory] | None = None,
        base_dir: Path | None = None,
        plugins: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._factories = dict(factories or {})
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None
        self._plugins: dict[str, dict[str, str]] = {}
        if plugins is not None and not isinstance(plugins, Mapping):
            raise ProviderConfigurationError("plugins must be a mapping")
        for name, entry in (plugins or {}).items():
            if not isinstance(name, str) or not name.isidentifier() or name in PRODUCTION_PROVIDER_NAMES:
                raise ProviderConfigurationError(f"invalid or reserved Provider plugin name: {name!r}")
            if not isinstance(entry, Mapping):
                raise ProviderConfigurationError(f"plugin {name}: definition must be an object")
            kind = entry.get("kind")
            factory = entry.get("factory")
            normalizer = entry.get("normalizer")
            if not isinstance(kind, str) or not kind:
                raise ProviderConfigurationError(f"plugin {name}: kind is required")
            for field, value in (("factory", factory), ("normalizer", normalizer)):
                if not isinstance(value, str) or not all(value.partition(":")[::2]):
                    raise ProviderConfigurationError(f"plugin {name}: invalid {field} entrypoint")
            self._plugins[name] = {"kind": kind, "factory": factory, "normalizer": normalizer}

    @property
    def plugin_normalizers(self) -> dict[str, str]:
        return {name: spec["normalizer"] for name, spec in self._plugins.items()}

    def supports(self, name: str, kind: str) -> bool:
        if name in PRODUCTION_PROVIDER_NAMES:
            return kind in DEFAULT_ADAPTER_PATHS
        plugin = self._plugins.get(name)
        return plugin is not None and kind == plugin["kind"]

    def _resolve_path(self, raw_path: str, *, field: str) -> Path:
        expanded = os.path.expandvars(raw_path)
        if "$PDFFAST_PROJECT_ROOT" in expanded:
            if self._base_dir is None:
                raise ProviderConfigurationError(
                    f"{field} requires a PDFFast project root: {raw_path}"
                )
            expanded = expanded.replace("$PDFFAST_PROJECT_ROOT", str(self._base_dir))
        path = Path(expanded).expanduser()
        if not path.is_absolute():
            if self._base_dir is None:
                raise ProviderConfigurationError(
                    f"relative {field} requires ProviderRegistry(base_dir=...): {raw_path}"
                )
            path = self._base_dir / path
        # Keep virtualenv interpreter symlinks intact: resolving the final
        # component would invoke the base interpreter without its venv prefix.
        return Path(os.path.abspath(path))

    def _prepare_config(self, config: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(config)
        python_executable = prepared.get("python_executable")
        if python_executable:
            prepared["python_executable"] = str(
                self._resolve_path(str(python_executable), field="python_executable")
            )

        for field in (
            "text_detection_model_dir",
            "text_recognition_model_dir",
            "layout_detection_model_dir",
            "vl_rec_model_dir",
        ):
            if prepared.get(field):
                prepared[field] = str(
                    self._resolve_path(str(prepared[field]), field=field)
                )

        missing: list[str] = []
        for raw_path in prepared.get("required_artifacts") or []:
            resolved = self._resolve_path(str(raw_path), field="required_artifact")
            if not resolved.exists():
                missing.append(str(resolved))
        if missing:
            raise ProviderConfigurationError(
                "missing required artifact(s): " + ", ".join(missing)
            )

        for raw_path in prepared.get("required_artifact_manifests") or []:
            manifest = self._resolve_path(
                str(raw_path), field="required_artifact_manifest"
            )
            if not manifest.is_file():
                missing.append(str(manifest))
                continue
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise ProviderConfigurationError(
                    f"invalid required artifact manifest: {manifest}: {exc}"
                ) from exc
            if not isinstance(payload, dict) or "files" not in payload:
                raise ProviderConfigurationError(
                    f"invalid required artifact manifest: {manifest}"
                )
            references = payload["files"]
            if not isinstance(references, list):
                raise ProviderConfigurationError(
                    f"invalid required artifact manifest files[]: {manifest}"
                )
            for reference in references:
                relative = Path(str(reference))
                if (
                    not isinstance(reference, str)
                    or not reference
                    or relative.is_absolute()
                    or ".." in relative.parts
                ):
                    raise ProviderConfigurationError(
                        f"invalid required artifact manifest entry: {manifest}: {reference!r}"
                    )
                artifact = manifest.parent / relative
                if not artifact.is_file():
                    missing.append(str(artifact))

        for raw_root, references in (
            prepared.get("required_artifact_trees") or {}
        ).items():
            root = self._resolve_path(str(raw_root), field="required_artifact_tree")
            if not root.is_dir():
                missing.append(str(root))
                continue
            if not isinstance(references, list):
                raise ProviderConfigurationError(
                    f"invalid required artifact tree files[]: {root}"
                )
            for reference in references:
                relative = Path(str(reference))
                if (
                    not isinstance(reference, str)
                    or not reference
                    or relative.is_absolute()
                    or ".." in relative.parts
                ):
                    raise ProviderConfigurationError(
                        f"invalid required artifact tree entry: {root}: {reference!r}"
                    )
                artifact = root / relative
                if not artifact.is_file():
                    missing.append(str(artifact))
        if missing:
            raise ProviderConfigurationError(
                "missing required artifact(s): " + ", ".join(missing)
            )

        mismatched: list[str] = []
        for raw_path, expected in (
            prepared.get("required_artifact_sha256") or {}
        ).items():
            resolved = self._resolve_path(str(raw_path), field="required_artifact_sha256")
            if not resolved.is_file():
                missing.append(str(resolved))
                continue
            digest = sha256()
            with resolved.open("rb") as artifact:
                for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != str(expected).lower():
                mismatched.append(f"{resolved} expected={expected} actual={actual}")
        if missing:
            raise ProviderConfigurationError(
                "missing required artifact(s): " + ", ".join(missing)
            )
        if mismatched:
            raise ProviderConfigurationError(
                "required artifact sha256 mismatch: " + "; ".join(mismatched)
            )
        return prepared

    def create(self, name: str, config: dict[str, Any]) -> Provider:
        if config.get("runtime_enabled") is not True:
            raise ProviderDisabledError(
                f"Provider runtime_enabled is not true: {name}"
            )
        kind = str(config.get("kind") or "")
        if name in PRODUCTION_PROVIDER_NAMES:
            if kind not in DEFAULT_ADAPTER_PATHS:
                raise UnknownProviderKindError(f"Unsupported Provider kind: {kind}")
            factory_path = DEFAULT_ADAPTER_PATHS[kind]
        else:
            plugin = self._plugins.get(name)
            if plugin is None:
                raise ProviderConfigurationError(f"Provider is outside the production closure: {name}")
            if kind != plugin["kind"]:
                raise ProviderConfigurationError(
                    f"plugin {name}: configured kind={kind!r}, declared kind={plugin['kind']!r}"
                )
            factory_path = plugin["factory"]

        prepared = self._prepare_config(config)
        factory = self._factories.get(kind)
        if factory is None:
            factory = _load_factory(factory_path)
        return factory(name, prepared)
