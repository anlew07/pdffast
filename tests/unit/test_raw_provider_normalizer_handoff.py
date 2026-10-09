"""Live RawProviderResult normalization keeps the frozen file adapter as replay input."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pdffast.providers.base import RawProviderResult
from pdffast.fallback.executor import _evaluate
from pdffast.providers.normalization import normalize_prediction
from pdffast.providers.runtime_normalization import normalize_runtime_result, _runtime_manifest


ROOT = Path(__file__).resolve().parents[2]


def _fixture(case: int, provider: str) -> tuple[RawProviderResult, dict, bytes]:
    root = ROOT / f"outputs/template_removal_review/case_{case:03d}"
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


@pytest.mark.parametrize(("provider", "status", "text"), [
    ("rapidocr_ch_light", "SUCCESS", "第一行\n第二行"),
    ("paddleocr_v5_mobile", "SUCCESS", "第一行\n第二行"),
    *[(provider, "SUCCESS", "# 标题\n\n<table><tr><th>A</th></tr><tr><td>1</td></tr></table>\n\n$x$")
      for provider in ("mineru_local", "marker_local", "docling_local", "pp_structure_v3_light", "paddleocr_vl_16")],
    ("rapidocr_ch_light", "FAILED", ""),
    ("rapidocr_ch_light", "TIMEOUT", ""),
])
def test_object_and_file_normalization_match_for_provider_shapes(
    provider: str, status: str, text: str, tmp_path: Path,
) -> None:
    task = {
        "task_id": "synthetic-1", "task_type": "REGION_FALLBACK", "page_number": 1,
        "source_id": "region-1", "capability_route": "REGION_MULTIMODAL_PARSE",
        "input_image": str(tmp_path / "region.png"),
    }
    raw = RawProviderResult(
        provider=provider, task_id="synthetic-1", status=status,
        payload={"text": text, "confidence": 0.9, "structure": {
            "spatial_text_items": [{"text": "第一行", "bbox": [0, 0, 30, 10], "confidence": 0.9}]
            if provider == "rapidocr_ch_light" and status == "SUCCESS" else [],
        }},
        markdown=text if provider not in {"rapidocr_ch_light", "paddleocr_v5_mobile"} else None,
        warnings=("FAILED",) if status == "FAILED" else (),
    )
    result_path = tmp_path / "raw.json"
    manifest_path = tmp_path / "manifest.json"
    live = normalize_runtime_result(raw, task, result_path=result_path, manifest_path=manifest_path)
    manifest, task_map = _runtime_manifest(raw, task, result_path)
    replay = normalize_prediction(manifest=manifest, manifest_path=manifest_path,
                                  task_map=task_map, provider=provider, result_path=result_path)
    assert live == replay
    assert live["task_id"] == raw.task_id
    assert live["provider"]["name"] == provider
    if provider == "rapidocr_ch_light" and status == "SUCCESS":
        assert live["spatial_text"]["availability"] == "AVAILABLE"
        assert len(live["spatial_text"]["items"]) == 1
    if provider == "paddleocr_v5_mobile":
        assert live["reading_blocks"]["availability"] == "NOT_EMITTED"
    if provider in {"mineru_local", "marker_local", "docling_local", "pp_structure_v3_light", "paddleocr_vl_16"}:
        assert all(live[channel]["availability"] == "AVAILABLE" for channel in ("reading_blocks", "tables", "formulas"))
    if status in {"FAILED", "TIMEOUT"}:
        assert live["status"] in {"ERROR", "TIMEOUT"}


def test_object_path_preserves_json_wire_shape_without_reloading(tmp_path: Path) -> None:
    task = {
        "task_id": "wire-shape-1", "task_type": "PAGE_FALLBACK", "page_number": 1,
        "source_id": "page-1", "capability_route": "PAGE_DOCUMENT_OCR",
    }
    raw = RawProviderResult(
        provider="rapidocr_ch_light", task_id="wire-shape-1", status="SUCCESS",
        payload={"text": "扫描文字", "structure": {
            "provider_stage_elapse_seconds": (0.1, 0.2),
            "diagnostic_path": tmp_path / "provider-output.json",
        }},
    )
    original = copy.deepcopy(raw)
    result_path = tmp_path / "raw.json"
    manifest_path = tmp_path / "manifest.json"
    live = normalize_runtime_result(raw, task, result_path=result_path, manifest_path=manifest_path)
    manifest, task_map = _runtime_manifest(raw, task, result_path)
    replay = normalize_prediction(manifest=manifest, manifest_path=manifest_path,
                                  task_map=task_map, provider=raw.provider, result_path=result_path)
    assert raw == original
    assert live == replay


@pytest.mark.parametrize(("case", "expected_tasks", "terminal"), [
    (2, 1, 0), (3, 54, 2), (4, 92, 0),
])
def test_real_case_raw_results_keep_normalization_and_task_closure(
    case: int, expected_tasks: int, terminal: int, tmp_path: Path,
) -> None:
    root = ROOT / f"outputs/template_removal_review/case_{case:03d}"
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
