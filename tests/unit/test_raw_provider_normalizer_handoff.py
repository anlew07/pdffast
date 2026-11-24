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


