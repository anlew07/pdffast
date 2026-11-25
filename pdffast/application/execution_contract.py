"""Build the stable Embedded execution handoff for one locked Core run."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pdffast.application.input_fingerprint import fingerprint_input




REQUEST_SCHEMA_VERSION = "pdffast.execution.request.v1"
_REQUEST_OPTION_NAMES = {
    "page_dpi", "region_dpi", "rapidocr_workers", "table_mode",
}


def validate_execution_request(value: Any) -> dict[str, Any]:
    """Validate and normalize the versioned, transport-neutral parse request.

    Provider selection, provider chains, profiles, and runtime configuration
    are deliberately excluded: those remain controlled by the PDFFast
    deployment and its locked Production Profile.
    """
    if not isinstance(value, Mapping):
        raise ValueError("execution request must be an object")
    if set(value) != {"schema_version", "run_id", "input", "options"}:
        raise ValueError("execution request has missing or unknown top-level fields")
    if value.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError("unsupported execution request schema_version")

    run_id = value.get("run_id")
    if (
        not isinstance(run_id, str)
        or not run_id
        or run_id in {".", ".."}
        or "/" in run_id
        or chr(92) in run_id
        or chr(0) in run_id
    ):
        raise ValueError("execution request run_id must be a single safe directory name")

    input_identity = value.get("input")
    if (
        not isinstance(input_identity, Mapping)
        or set(input_identity) != {"sha256"}
        or not isinstance(input_identity.get("sha256"), str)
        or len(input_identity["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in input_identity["sha256"])
    ):
        raise ValueError("execution request input.sha256 must be a lowercase SHA-256 digest")

    options = value.get("options")
    if not isinstance(options, Mapping) or set(options) - _REQUEST_OPTION_NAMES:
        raise ValueError("execution request options contain unsupported fields")
    normalized_options: dict[str, Any] = {}
    for name in ("page_dpi", "region_dpi", "rapidocr_workers"):
        if name in options:
            number = options[name]
            if type(number) is not int or number < 1:
                raise ValueError(f"execution request options.{name} must be a positive integer")
            normalized_options[name] = number
    if "table_mode" in options:
        table_mode = options["table_mode"]
        if table_mode not in {"off", "auto", "all"}:
            raise ValueError("execution request options.table_mode must be off, auto, or all")
        normalized_options["table_mode"] = table_mode

    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "run_id": run_id,
        "input": {"sha256": input_identity["sha256"]},
        "options": normalized_options,
    }


def _warning(code: str, stage: str, message: str, **details: Any) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "stage": stage, "message": message}
    if details:
        item["details"] = details
    return item


def _relative_path(run_dir: Path, path: Path) -> str:
    root = Path(run_dir).resolve(strict=True)
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"execution artifact cannot be a symlink: {source}")
    resolved = source.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"execution artifact is not a regular file: {source}")
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"execution artifact escapes run directory: {source}") from exc


def _artifact(
    run_dir: Path,
    *,
    name: str,
    path: Path,
    media_type: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    relative = _relative_path(run_dir, path)
    resolved = Path(run_dir).resolve(strict=True) / relative
    before = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = resolved.stat()
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise ValueError(f"execution artifact changed while hashing: {relative}")
    artifact = {
        "name": name,
        "path": relative,
        "media_type": media_type,
        "byte_size": after.st_size,
        "sha256": digest.hexdigest(),
    }
    if task_id is not None:
        if not task_id:
            raise ValueError("selected prediction artifact has an empty task_id")
        artifact["task_id"] = task_id
    return artifact


def build_execution_contract(
    context: Any,
    *,
    production_identity: dict[str, Any],
    statistics: dict[str, Any],
    execution_plan: Any,
    production_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the Embedded contract from already-validated production evidence.

    The root result/manifest.json is deliberately excluded from its own
    artifact inventory to avoid a self-referential digest.
    """
    artifacts = context.artifacts
    run_dir = Path(context.run_dir).resolve(strict=True)
    input_metadata = context.input_metadata
    if (
        not isinstance(input_metadata, dict)
        or input_metadata.get("algorithm") != "sha256"
        or input_metadata.get("status") != "COMPLETE"
        or not isinstance(input_metadata.get("sha256"), str)
        or len(input_metadata["sha256"]) != 64
        or type(input_metadata.get("byte_size")) is not int
        or input_metadata["byte_size"] < 1
    ):
        raise ValueError("locked execution requires a complete SHA-256 input identity")

    # The start-of-run fingerprint is not an immutable snapshot. Re-read the
    # source after all stages finish and before publishing the final manifest.
    final_input = fingerprint_input(Path(context.pdf))
    if (
        final_input.get("status") != "COMPLETE"
        or final_input.get("algorithm") != input_metadata["algorithm"]
        or final_input.get("sha256") != input_metadata["sha256"]
        or final_input.get("byte_size") != input_metadata["byte_size"]
    ):
        raise ValueError("input PDF changed or became unavailable during locked parse")

    if production_identity.get("status") != "PASS":
        raise ValueError("execution contract requires a passing production preflight")
    provider_runtime = production_identity.get("provider_runtime")
    allowed_providers = production_identity.get("allowed_providers")
    if (
        not isinstance(provider_runtime, dict)
        or not isinstance(allowed_providers, list)
        or not allowed_providers
        or set(provider_runtime) != set(allowed_providers)
        or any(
            not isinstance(provider_runtime[name], dict)
            or provider_runtime[name].get("status") != "READY"
            or not isinstance(provider_runtime[name].get("identity"), dict)
            for name in allowed_providers
        )
    ):
        raise ValueError("execution contract requires runtime identity for every allowed Provider")

    summary = production_manifest.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("production execution manifest has no summary")
    policy_version = execution_plan.data.get("version")
    if not isinstance(policy_version, str) or not policy_version:
        raise ValueError("runtime escalation policy has no version")

    planned_count = statistics["planned_task_count"]
    accepted_count = statistics["accepted_task_count"]
    terminal_count = statistics["terminal_preserve_count"]
    failure_count = statistics["pipeline_failure_count"]
    escalated_count = summary["escalated_count"]
    attempted_counts = statistics["attempted_provider_counts"]
    selected_counts = statistics["selected_provider_counts"]
    allowed_set = set(allowed_providers)
    if (
        type(planned_count) is not int
        or type(accepted_count) is not int
        or type(terminal_count) is not int
        or type(failure_count) is not int
        or type(escalated_count) is not int
        or planned_count < 0
        or min(accepted_count, terminal_count, failure_count, escalated_count) < 0
        or accepted_count + terminal_count + failure_count != planned_count
        or not isinstance(attempted_counts, dict)
        or not isinstance(selected_counts, dict)
        or set(attempted_counts) - allowed_set
        or set(selected_counts) - allowed_set
        or sum(selected_counts.values()) != accepted_count
        or (planned_count == 0 and (attempted_counts or selected_counts or escalated_count))
        or (planned_count > 0 and (
            not attempted_counts
            or sum(attempted_counts.values()) < planned_count
            or escalated_count > planned_count
        ))
        or statistics["execution_status"] != (
            "COMPLETED_WITH_PIPELINE_FAILURES" if failure_count else "COMPLETED"
        )
    ):
        raise ValueError("execution statistics do not reconcile with the planned task outcomes")

    required = [
        _artifact(
            run_dir, name="document", path=artifacts.result.document_json,
            media_type="application/json",
        ),
        _artifact(
            run_dir, name="markdown", path=artifacts.result.document_md,
            media_type="text/markdown",
        ),
        _artifact(
            run_dir, name="audit", path=artifacts.result.audit_json,
            media_type="application/json",
        ),
        _artifact(
            run_dir, name="production_execution_manifest",
            path=artifacts.providers.production_manifest, media_type="application/json",
        ),
        _artifact(
            run_dir, name="selected_prediction_index",
            path=artifacts.providers.selected_index, media_type="application/json",
        ),
        _artifact(
            run_dir, name="runtime_escalation_policy",
            path=artifacts.observability.execution_plan, media_type="application/json",
        ),
    ]
    for path in sorted(artifacts.providers.selected_dir.glob("*.json")):
        required.append(
            _artifact(
                run_dir, name="selected_prediction", path=path,
                media_type="application/json", task_id=path.stem,
            )
        )
    required.sort(key=lambda item: item["path"])
    if len({item["path"] for item in required}) != len(required):
        raise ValueError("execution artifact paths are duplicated")

    def relative(path: Path) -> str:
        return _relative_path(run_dir, path)

    code_identity = production_identity["code_identity"]
    execution = {
        "execution_status": statistics["execution_status"],
        "pdffast_commit": production_identity.get("pdffast_commit"),
        "source_sha256": code_identity["source_sha256"],
        "source_dirty": code_identity.get("source_dirty"),
        "algorithm_sha256": code_identity["algorithm_sha256"],
        "profile_name": production_identity["profile_name"],
        "profile_sha256": production_identity["profile_sha256"],
        "providers_config_sha256": production_identity["providers_config_sha256"],
        "effective_config_fingerprint": production_identity["effective_config_fingerprint"],
        "policy_version": policy_version,
        "allowed_providers": list(allowed_providers),
        "provider_runtime": provider_runtime,
        "attempted_provider_counts": statistics["attempted_provider_counts"],
        "selected_provider_counts": statistics["selected_provider_counts"],
        "planned_task_count": statistics["planned_task_count"],
        "accepted_task_count": statistics["accepted_task_count"],
        "terminal_preserve_count": statistics["terminal_preserve_count"],
        "pipeline_failure_count": statistics["pipeline_failure_count"],
        "escalated_count": escalated_count,
        "preflight_status": production_identity["status"],
        "audit_passed": True,
        "outputs_written": True,
    }
    warnings: list[dict[str, Any]] = []
    risk_flags: set[str] = {"INPUT_NOT_SNAPSHOTTED"}
    request = getattr(context, "execution_request", None)
    if request is None:
        warnings.append(_warning(
            "EXPECTED_INPUT_SHA256_NOT_SUPPLIED",
            "request_validation",
            "The caller did not supply an expected input SHA-256 digest.",
        ))
        risk_flags.add("EXPECTED_INPUT_SHA256_NOT_SUPPLIED")
    dependency_probe_skipped = sorted(
        name for name, runtime in provider_runtime.items()
        if runtime.get("dependency_probe") == "NOT_RUN"
    )
    if dependency_probe_skipped:
        warnings.append(_warning(
            "PROVIDER_DEPENDENCY_PROBE_NOT_RUN",
            "production_preflight",
            "Strict runtime identity was checked, but Provider preflight probes were not run during production preflight.",
            providers=dependency_probe_skipped,
        ))
        risk_flags.add("PROVIDER_DEPENDENCY_PROBE_NOT_RUN")
    if terminal_count:
        warnings.append(_warning(
            "TERMINAL_PRESERVATION_PRESENT",
            "provider_execution",
            "One or more tasks retained terminal source evidence without an accepted Provider result.",
            count=terminal_count,
        ))
        risk_flags.add("TERMINAL_PRESERVATION_PRESENT")
    if failure_count:
        warnings.append(_warning(
            "PIPELINE_FAILURES_PRESENT",
            "provider_execution",
            "One or more Provider tasks ended without an accepted result or terminal preservation.",
            count=failure_count,
        ))
        risk_flags.add("PIPELINE_FAILURES_PRESENT")
    if code_identity.get("source_dirty") is True:
        warnings.append(_warning(
            "PDFFAST_SOURCE_DIRTY",
            "production_identity",
            "The PDFFast source checkout contains monitored uncommitted changes.",
        ))
        risk_flags.add("PDFFAST_SOURCE_DIRTY")

    contract = {
        "schema_version": "pdffast.execution.v1",
        "run_id": context.run_id,
        "input": {
            "algorithm": "sha256",
            "sha256": input_metadata["sha256"],
            "byte_size": input_metadata["byte_size"],
            "status": "COMPLETE",
        },
        "result": {
            "document": relative(artifacts.result.document_json),
            "markdown": relative(artifacts.result.document_md),
            "audit": relative(artifacts.result.audit_json),
        },
        "execution": execution,
        "execution_evidence": {
            "production_manifest": relative(artifacts.providers.production_manifest),
            "selected_prediction_index": relative(artifacts.providers.selected_index),
            "runtime_policy": relative(artifacts.observability.execution_plan),
        },
        "artifacts": required,
        "warnings": warnings,
        "risk_flags": sorted(risk_flags),
        "error": None,
    }
    if request is not None:
        contract["request"] = request
    return contract
