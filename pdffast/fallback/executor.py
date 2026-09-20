from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from pdffast.providers.base import Provider, ProviderTask, RawProviderResult


SUCCESS_STATUSES = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}


def _provider_chain(task: dict[str, Any]) -> list[str]:
    chain = [
        str(item.get("provider") or "").strip()
        for item in task.get("provider_chain") or []
        if isinstance(item, dict)
    ]
    if not chain or any(not item for item in chain):
        raise ValueError(f"task={task.get('task_id')} provider_chain 为空或非法")
    return chain


def _channel_has_items(canonical: dict[str, Any], channel: str) -> bool:
    value = canonical.get(channel)
    return bool(
        isinstance(value, dict)
        and value.get("availability") == "AVAILABLE"
        and isinstance(value.get("items"), list)
        and value["items"]
    )


def _evaluate(canonical: dict[str, Any], task: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if str(canonical.get("status") or "") not in SUCCESS_STATUSES:
        reasons.append("PROVIDER_EXECUTION_ERROR")

    text = canonical.get("text") if isinstance(canonical.get("text"), dict) else {}
    contract = task.get("output_contract") or {}
    required = {str(item) for item in contract.get("required") or []}
    if "text" in required and text.get("availability") != "AVAILABLE":
        reasons.append("TEXT_CHANNEL_UNAVAILABLE")
    if contract.get("empty_text_requires_warning") and not str(
        text.get("content") or ""
    ).strip():
        reasons.append("EMPTY_TEXT_WHEN_REQUIRED")

    structure_channels = [
        str(item)
        for item in contract.get("required_structure_channels_any") or []
        if str(item)
    ]
    if structure_channels and not any(
        _channel_has_items(canonical, channel) for channel in structure_channels
    ):
        reasons.append("REQUIRED_STRUCTURE_CHANNEL_UNAVAILABLE")
    reasons = list(dict.fromkeys(reasons))
    return not reasons, reasons


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def execute_fallback(
    *,
    policy: dict[str, Any],
    plan: dict[str, Any],
    provider_configs: dict[str, dict[str, Any]],
    registry: Any,
    normalizer: Callable[[RawProviderResult, dict[str, Any]], dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    """Execute the frozen provider chains as deterministic escalation waves."""
    tasks = policy.get("tasks")
    plan_tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not isinstance(plan_tasks, list):
        raise ValueError("policy and plan must contain tasks")
    policy_ids = [str(task.get("task_id") or "") for task in tasks]
    plan_ids = [str(task.get("task_id") or "") for task in plan_tasks]
    if not all(policy_ids) or set(policy_ids) != set(plan_ids):
        raise ValueError("policy/plan task_id 集不一致")

    output_dir = Path(output_dir)
    selected_dir = output_dir / "selected_predictions"
    task_index = {str(task["task_id"]): task for task in tasks}
    states = {
        task_id: {
            "next_index": 0,
            "attempts": [],
            "selected_provider": None,
            "selected_canonical": None,
            "terminal": False,
            "failure": False,
            "done": False,
        }
        for task_id in policy_ids
    }
    providers: dict[str, Provider] = {}
    batch_history: list[dict[str, Any]] = []

    try:
        wave = 0
        while not all(state["done"] for state in states.values()):
            groups: dict[str, list[str]] = defaultdict(list)
            for task_id in policy_ids:
                state = states[task_id]
                if state["done"]:
                    continue
                task = task_index[task_id]
                chain = _provider_chain(task)
                if state["next_index"] >= len(chain):
                    terminal = task.get("terminal_fallback")
                    if isinstance(terminal, dict) and terminal.get("action"):
                        state["terminal"] = True
                    else:
                        state["failure"] = True
                    state["done"] = True
                    continue
                groups[chain[state["next_index"]]].append(task_id)

            for provider_name in sorted(groups):
                provider = providers.get(provider_name)
                if provider is None:
                    config = provider_configs.get(provider_name)
                    if not isinstance(config, dict):
                        raise ValueError(f"missing provider config: {provider_name}")
                    provider = registry.create(provider_name, config)
                    preflight = provider.preflight()
                    if not preflight.available:
                        raise RuntimeError(
                            f"provider preflight failed: {provider_name}: {preflight.detail}"
                        )
                    provider.initialize()
                    providers[provider_name] = provider

                task_ids = groups[provider_name]
                batch_history.append(
                    {"wave": wave, "provider": provider_name, "task_ids": task_ids}
                )
                for task_id in task_ids:
                    task = task_index[task_id]
                    state = states[task_id]
                    try:
                        raw = provider.execute(
                            ProviderTask(
                                task_id=task_id,
                                capability_route=str(task.get("capability_route") or ""),
                                input_image=Path(str(task.get("input_image") or "")),
                                metadata=task,
                            )
                        )
                        canonical = normalizer(raw, task)
                    except Exception as exc:
                        canonical = {
                            "task_id": task_id,
                            "provider": {"name": provider_name},
                            "status": "FAILED",
                            "text": {"availability": "NOT_EMITTED", "content": ""},
                            "tables": {"availability": "NOT_EMITTED", "items": []},
                            "formulas": {"availability": "NOT_EMITTED", "items": []},
                            "reading_blocks": {"availability": "NOT_EMITTED", "items": []},
                            "relations": {"availability": "NOT_EMITTED", "items": []},
                            "exception": f"{type(exc).__name__}: {exc}",
                        }
                    accepted, triggers = _evaluate(canonical, task)
                    state["attempts"].append(
                        {
                            "provider": provider_name,
                            "chain_index": state["next_index"],
                            "accepted": accepted,
                            "escalation_triggers": triggers,
                            "canonical": canonical,
                        }
                    )
                    if accepted:
                        state["selected_provider"] = provider_name
                        state["selected_canonical"] = canonical
                        state["done"] = True
                    else:
                        state["next_index"] += 1
            wave += 1
            if wave > 10:
                raise RuntimeError("provider escalation wave exceeded 10")
    finally:
        for provider in providers.values():
            provider.close()

    selected_counts: Counter[str] = Counter()
    attempt_counts: Counter[str] = Counter()
    selected_index: list[dict[str, Any]] = []
    accepted_count = terminal_count = failure_count = escalated_count = 0
    for task_id in policy_ids:
        task = task_index[task_id]
        state = states[task_id]
        selected_provider = state["selected_provider"]
        if selected_provider:
            accepted_count += 1
            selected_counts[selected_provider] += 1
        terminal_count += int(state["terminal"])
        failure_count += int(state["failure"])
        escalated_count += int(len(state["attempts"]) > 1)
        for attempt in state["attempts"]:
            attempt_counts[attempt["provider"]] += 1

        wrapper = {
            "task_id": task_id,
            "page_number": task.get("page_number"),
            "capability_route": task.get("capability_route"),
            "selected_provider": selected_provider,
            "terminal_fallback_applied": bool(state["terminal"]),
            "pipeline_failure": bool(state["failure"]),
            "attempts": state["attempts"],
            "canonical_prediction": state["selected_canonical"],
        }
        selected_path = selected_dir / f"{task_id}.json"
        _write_json(selected_path, wrapper)
        selected_index.append(
            {
                "task_id": task_id,
                "selected_provider": selected_provider,
                "terminal_fallback_applied": bool(state["terminal"]),
                "pipeline_failure": bool(state["failure"]),
                "selected_prediction": str(selected_path),
            }
        )

    summary = {
        "task_count": len(policy_ids),
        "accepted_task_count": accepted_count,
        "terminal_preserve_count": terminal_count,
        "pipeline_failure_count": failure_count,
        "escalated_count": escalated_count,
        "escalated_rate": round(escalated_count / len(policy_ids), 8) if policy_ids else 0.0,
        "selected_provider_counts": dict(sorted(selected_counts.items())),
        "attempt_provider_counts": dict(sorted(attempt_counts.items())),
        "selected_artifact_count": len(selected_index),
    }
    manifest = {
        "schema_version": "1.0",
        "stage": 9,
        "substage": "9.8",
        "name": "full_production_fallback_executor",
        "status": "COMPLETED_WITH_PIPELINE_FAILURES" if failure_count else "COMPLETED",
        "source_file": policy.get("source_file"),
        "summary": summary,
        "batch_history": batch_history,
        "selected_predictions": selected_index,
    }
    _write_json(output_dir / "production_execution_manifest.json", manifest)
    _write_json(
        output_dir / "selected_prediction_index.json",
        {"task_count": len(selected_index), "items": selected_index},
    )
    return manifest
