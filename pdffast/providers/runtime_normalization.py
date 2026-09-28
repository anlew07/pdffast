"""Runtime adapter from in-process Provider results to CanonicalPrediction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import RawProviderResult
from .normalization import normalize_prediction


def _runtime_manifest(raw: RawProviderResult, task: dict[str, Any], result_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    task_id = str(task.get("task_id") or raw.task_id)
    manifest_task = dict(task)
    manifest_task["task_id"] = task_id
    manifest = {
        "name": "provider_benchmark",
        "selected_task_count": 1,
        "selection": {"requested_providers": [raw.provider]},
        "selected_tasks": [manifest_task],
        "runtime_adapter": True,
        "runtime_result": str(result_path),
    }
    return manifest, {task_id: manifest_task}


def normalize_runtime_result(
    raw: RawProviderResult,
    task: dict[str, Any],
    *,
    result_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Normalize a live provider result without coupling Core to transport APIs."""
    result_path = Path(result_path)
    manifest_path = Path(manifest_path)
    payload = raw.payload if isinstance(raw.payload, dict) else {"value": raw.payload}
    result = dict(payload)
    result.update(
        {
            # The offline normalizers consume the frozen raw-result contract:
            # provider metadata is an object with a stable ``name`` field.
            # Runtime providers expose ``RawProviderResult.provider`` as a
            # string, so adapt that transport-level value at this boundary.
            "provider": {
                "name": raw.provider,
                "kind": result.get("provider_kind"),
                "model_or_engine": result.get("model_or_engine"),
            },
            "task_id": raw.task_id,
            "status": raw.status,
            "markdown": raw.markdown,
            "elapsed_seconds": raw.elapsed_seconds,
            "warnings": list(raw.warnings),
        }
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    manifest, task_map = _runtime_manifest(raw, task, result_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalize_prediction(
        manifest=manifest,
        manifest_path=manifest_path,
        task_map=task_map,
        provider=raw.provider,
        result_path=result_path,
    )
