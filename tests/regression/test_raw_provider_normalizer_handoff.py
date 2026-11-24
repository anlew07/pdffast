"""Artifact-backed real Provider normalization regression cases."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from pdffast.providers.base import RawProviderResult
from pdffast.fallback.executor import _evaluate
from pdffast.providers.normalization import normalize_prediction
from pdffast.providers.runtime_normalization import normalize_runtime_result, _runtime_manifest

pytestmark = pytest.mark.regression


def _fixture(case: int, provider: str) -> tuple[RawProviderResult, dict, bytes]:
    raw_root = os.environ.get("PDFFAST_REGRESSION_ARTIFACTS_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REGRESSION_ARTIFACTS_ROOT is required for artifact-backed regression")
    root = Path(raw_root).resolve() / f"template_removal_review/case_{case:03d}"
    raw_dir = root / "09_8_production_fallback/provider_raw"
    plan_path = root / "09_2_provider_plan/provider_plan.json"
    if not raw_dir.is_dir() or not plan_path.is_file():
        pytest.skip(f"case_{case:03d} raw Provider artifacts unavailable")
    tasks = {item["task_id"]: item for item in json.loads(plan_path.read_text())["tasks"]}
    for path in sorted(raw_dir.glob("*.json")):
        if path.name == "runtime_manifest.json":
            continue
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        if raw_data["provider"]["name"] != provider:
            continue
        payload = {key: value for key, value in raw_data.items()
                   if key not in {"provider", "task_id", "status", "markdown", "elapsed_seconds"}}
        raw = RawProviderResult(
            provider=provider, task_id=raw_data["task_id"], status=raw_data["status"],
            payload=payload, markdown=raw_data["markdown"],
            elapsed_seconds=raw_data["elapsed_seconds"], warnings=tuple(raw_data["warnings"]),
        )
        return raw, tasks[raw.task_id], path.read_bytes()
    pytest.skip(f"case_{case:03d} has no {provider} raw result")


@pytest.mark.parametrize(("case", "provider"), [
    (2, "rapidocr_ch_light"),
    (3, "rapidocr_ch_light"),
    (3, "paddleocr_v5_mobile"),
    (3, "marker_local"),
    (3, "mineru_local"),
    (4, "rapidocr_ch_light"),
])
def test_raw_provider_result_passes_directly_without_raw_json_reload(
    case: int, provider: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, task, historical_bytes = _fixture(case, provider)
    original_raw = copy.deepcopy(raw)
    result_path = tmp_path / "provider_raw" / f"{raw.task_id}.json"
    manifest_path = result_path.parent / "runtime_manifest.json"
    original_read_text, original_open = Path.read_text, Path.open
    guarded = {result_path.resolve(), manifest_path.resolve()}

    def guard_read_text(path: Path, *args, **kwargs):
        if path.resolve() in guarded:
            raise AssertionError(f"fresh normalizer reopened its own artifact: {path}")
        return original_read_text(path, *args, **kwargs)

    def guard_open(path: Path, mode="r", *args, **kwargs):
        if path.resolve() in guarded and "r" in mode:
            raise AssertionError(f"fresh normalizer reopened its own artifact: {path}")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_text", guard_read_text)
        patcher.setattr(Path, "open", guard_open)
        live = normalize_runtime_result(raw, task, result_path=result_path, manifest_path=manifest_path)

    assert raw == original_raw
    assert result_path.read_bytes() == historical_bytes
    manifest, task_map = _runtime_manifest(raw, task, result_path)
    replay = normalize_prediction(
        manifest=manifest, manifest_path=manifest_path, task_map=task_map,
        provider=provider, result_path=result_path,
    )
    assert live == replay
    assert json.dumps(live, ensure_ascii=False, indent=2) == json.dumps(replay, ensure_ascii=False, indent=2)


@pytest.mark.parametrize(("case", "expected_tasks", "terminal"), [
    (2, 1, 0), (3, 54, 2), (4, 92, 0),
])
def test_real_case_raw_results_keep_normalization_and_task_closure(
    case: int, expected_tasks: int, terminal: int, tmp_path: Path,
) -> None:
    raw_root = os.environ.get("PDFFAST_REGRESSION_ARTIFACTS_ROOT")
    if not raw_root:
        pytest.skip("PDFFAST_REGRESSION_ARTIFACTS_ROOT is required for artifact-backed regression")
    root = Path(raw_root).resolve() / f"template_removal_review/case_{case:03d}"
    raw_dir = root / "09_8_production_fallback/provider_raw"
    plan_path = root / "09_2_provider_plan/provider_plan.json"
    policy_path = root / "09_6_3_runtime_policy/runtime_escalation_policy.json"
    index_path = root / "09_8_production_fallback/selected_prediction_index.json"
    selected_dir = root / "09_8_production_fallback/selected_predictions"
    if not all(path.exists() for path in (raw_dir, plan_path, policy_path, index_path, selected_dir)):
        pytest.skip(f"case_{case:03d} raw execution outputs unavailable")
    tasks = {item["task_id"]: item for item in json.loads(plan_path.read_text())["tasks"]}
    policy_tasks = {item["task_id"]: item for item in json.loads(policy_path.read_text())["tasks"]}
    index = json.loads(index_path.read_text())
    assert len(tasks) == len(index["items"]) == expected_tasks
    assert sum(bool(item.get("terminal_fallback_applied")) for item in index["items"]) == terminal
    assert set(tasks) == {item["task_id"] for item in index["items"]}

    checked = 0
    for source in sorted(raw_dir.glob("*.json")):
        if source.name == "runtime_manifest.json":
            continue
        old = json.loads(source.read_text(encoding="utf-8"))
        provider = old["provider"]["name"]
        payload = {key: value for key, value in old.items()
                   if key not in {"provider", "task_id", "status", "markdown", "elapsed_seconds"}}
        raw = RawProviderResult(
            provider, old["task_id"], old["status"], payload,
            old["markdown"], old["elapsed_seconds"], tuple(old["warnings"]),
        )
        result_path = tmp_path / "provider_raw" / source.name
        manifest_path = result_path.parent / "runtime_manifest.json"
        live = normalize_runtime_result(raw, tasks[raw.task_id], result_path=result_path,
                                        manifest_path=manifest_path)
        assert result_path.read_bytes() == source.read_bytes()
        manifest, task_map = _runtime_manifest(raw, tasks[raw.task_id], result_path)
        replay = normalize_prediction(manifest=manifest, manifest_path=manifest_path,
                                      task_map=task_map, provider=provider, result_path=result_path)
        assert live == replay, (case, source.name)
        selected = json.loads((selected_dir / source.name).read_text(encoding="utf-8"))
        last_attempt = selected["attempts"][-1]
        assert last_attempt["provider"] == provider
        historical_prediction = last_attempt["canonical"]
        assert {key: value for key, value in live.items() if key != "source_artifacts"} == {
            key: value for key, value in historical_prediction.items() if key != "source_artifacts"
        }
        assert live["source_artifacts"]["provider_raw_refs"] == historical_prediction["source_artifacts"]["provider_raw_refs"]
        assert _evaluate(live, policy_tasks[raw.task_id]) == (
            last_attempt["accepted"], last_attempt["escalation_triggers"]
        )
        checked += 1
    assert checked == expected_tasks
