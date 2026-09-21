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
        base_dir: Path | None = None,
    ) -> None:
        self._factories = dict(factories or {})
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else None

    def _resolve_path(self, raw_path: str, *, field: str) -> Path:
        path = Path(os.path.expandvars(raw_path)).expanduser()
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
                references = payload["files"]
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise ProviderConfigurationError(
                    f"invalid required artifact manifest: {manifest}: {exc}"
                ) from exc
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
        if name not in PRODUCTION_PROVIDER_NAMES:
            raise ProviderConfigurationError(
                f"Provider is outside the production closure: {name}"
            )

        kind = str(config.get("kind") or "")
        if kind not in DEFAULT_ADAPTER_PATHS:
            raise UnknownProviderKindError(f"Unsupported Provider kind: {kind}")

        prepared = self._prepare_config(config)

        factory = self._factories.get(kind)
        if factory is None:
            factory = _load_factory(DEFAULT_ADAPTER_PATHS[kind])
        return factory(name, prepared)
