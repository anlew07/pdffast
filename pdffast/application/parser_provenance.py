"""Build provenance from the completed plan, execution state and published records."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.fallback.policy import ProviderExecutionPlan
from pdffast.runtime import check_parse_cancelled

SCHEMA_VERSION = "1.0"
IDENTITY_FIELDS = (
    "profile_locked", "profile_name", "profile_sha256", "providers_config_sha256",
    "effective_config_fingerprint", "allowed_providers", "capability_routes",
    "pdffast_commit", "code_identity",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Provider execution provenance mismatch: {message}")


def _task_index(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed = {}
    for item in items:
        task_id = item["task_id"]
        _require(isinstance(task_id, str) and bool(task_id), f"invalid task ID in {label}")
        _require(task_id not in indexed, f"duplicate task ID in {label}")
        indexed[task_id] = item
    return indexed


def collect_execution_statistics(
    plan: ProviderExecutionPlan,
    execution: ProviderExecutionResult,
    allowed_providers: tuple[str, ...],
    *,
    output_dir: Path | None = None,
    plan_path: Path | None = None,
) -> dict[str, Any]:
    planned = _task_index(plan.data["tasks"], "plan")
    index = _task_index(execution.selected_index["items"], "selection index")
    predictions = _task_index(execution.selected_predictions, "selected predictions")
    manifest = execution.manifest
    count = len(planned)
    _require(planned.keys() == index.keys() == predictions.keys(), "task IDs differ across records")
    _require(
        type(execution.selected_index["task_count"]) is int
        and execution.selected_index["task_count"] == count
        and type(plan.data["summary"]["task_count"]) is int
        and plan.data["summary"]["task_count"] == count,
        "plan or index task count does not match records",
    )
    _require(manifest["selected_predictions"] == execution.selected_index["items"], "manifest index differs")
    if plan_path is not None:
        saved_plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        _require(saved_plan == plan.data, "persisted runtime escalation policy differs from execution plan")
    if output_dir is not None:
        for name, expected in (
            ("production_execution_manifest.json", manifest),
            ("selected_prediction_index.json", execution.selected_index),
        ):
            saved = json.loads((output_dir / name).read_text(encoding="utf-8"))
            _require(saved == expected, f"{name} differs from execution state")
        selected_dir = output_dir / "selected_predictions"
        expected_files = set()
        for task_id, prediction in predictions.items():
            expected_path = (selected_dir / f"{task_id}.json").resolve()
            reference = Path(str(index[task_id]["selected_prediction"]))
            actual_path = reference.resolve() if reference.is_absolute() else (Path.cwd() / reference).resolve()
            _require(actual_path == expected_path, f"{task_id} selected prediction path escapes its run directory")
            saved_prediction = json.loads(expected_path.read_text(encoding="utf-8"))
            _require(saved_prediction == prediction, f"{task_id} persisted selected prediction differs")
            expected_files.add(expected_path)
        actual_files = (
            {path.resolve() for path in selected_dir.glob("*.json")}
            if selected_dir.is_dir() else set()
        )
        _require(actual_files == expected_files, "persisted selected prediction file set differs from plan")

    selected: Counter[str] = Counter()
    attempted: Counter[str] = Counter()
    dispatch: Counter[tuple[int, str, str]] = Counter()
    terminal_count = failure_count = escalated_count = 0
    for task_id, task in planned.items():
        item = predictions[task_id]
        ref = index[task_id]
        chain = [candidate["provider"] for candidate in task["provider_chain"]]
        _require(bool(chain) and set(chain) <= set(allowed_providers), f"{task_id} invalid planned chain")
        attempts = item["attempts"]
        _require(0 < len(attempts) <= len(chain), f"{task_id} missing or excessive attempts")
        acceptance = []
        for position, attempt in enumerate(attempts):
            name = attempt["provider"]
            _require(
                type(attempt["chain_index"]) is int and attempt["chain_index"] == position
                and name == chain[position]
                and attempt["canonical"]["provider"]["name"] == name
                and attempt["canonical"]["task_id"] == task_id,
                f"{task_id} invalid attempt identity or order",
            )
            _require(type(attempt["accepted"]) is bool, f"{task_id} invalid acceptance flag")
            attempted[name] += 1
            dispatch[position, name, task_id] += 1
            if attempt["accepted"]:
                acceptance.append(position)
        provider = item["selected_provider"]
        terminal = item["terminal_fallback_applied"]
        failure = item["pipeline_failure"]
        _require(type(terminal) is bool and type(failure) is bool, f"{task_id} invalid outcome flags")
        _require(
            provider == ref["selected_provider"] and terminal is ref["terminal_fallback_applied"]
            and failure is ref["pipeline_failure"],
            f"{task_id} outcome differs from index",
        )
        if provider is not None:
            _require(
                acceptance == [len(attempts) - 1] and provider == attempts[-1]["provider"]
                and item["selected_canonical"] == attempts[-1]["canonical"] and not terminal and not failure,
                f"{task_id} selected prediction disagrees with acceptance",
            )
            selected[provider] += 1
        else:
            terminal_action = (task.get("terminal_fallback") or {}).get("action")
            _require(
                not acceptance and len(attempts) == len(chain)
                and item["selected_canonical"] is None and terminal is bool(terminal_action)
                and failure is not terminal
                and item["terminal_fallback_action"] == (terminal_action if terminal else None),
                f"{task_id} invalid exhausted outcome",
            )
        terminal_count += terminal
        failure_count += failure
        escalated_count += len(attempts) > 1

    batch_dispatch = Counter(
        (batch["wave"], batch["provider"], task_id)
        for batch in manifest["batch_history"] for task_id in batch["task_ids"]
    )
    _require(batch_dispatch == dispatch, "executed batches do not match attempts")
    status = "COMPLETED_WITH_PIPELINE_FAILURES" if failure_count else "COMPLETED"
    expected_summary = {
        "task_count": count, "accepted_task_count": sum(selected.values()),
        "terminal_preserve_count": terminal_count, "pipeline_failure_count": failure_count,
        "attempt_provider_counts": dict(attempted), "selected_provider_counts": dict(selected),
        "selected_artifact_count": count, "escalated_count": escalated_count,
    }
    _require(
        all(
            type(manifest["summary"].get(key)) is type(value) and manifest["summary"][key] == value
            for key, value in expected_summary.items()
        ) and manifest["status"] == status,
        "manifest execution summary differs from records",
    )
    return {
        "planned_task_count": count,
        "attempted_provider_counts": dict(sorted(attempted.items())),
        "selected_provider_counts": dict(sorted(selected.items())),
        "accepted_task_count": sum(selected.values()),
        "terminal_preserve_count": terminal_count,
        "pipeline_failure_count": failure_count,
        "provider_execution_required": count > 0,
        "execution_status": status,
    }


def build_parser_provenance(identity: dict, statistics: dict) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        **{key: identity[key] for key in IDENTITY_FIELDS},
        **statistics,
        "preflight_status": "PASS",
        "audit_passed": True,
        "outputs_written": True,
    }


def publish_manifest(path: Path, manifest: dict[str, Any]) -> None:
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=".manifest-", delete=False, encoding="utf-8", mode="w",
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        check_parse_cancelled()
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
