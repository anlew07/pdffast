import importlib.util
import json
import os
from pathlib import Path

import pytest


PROVIDERS = (
    ("rapidocr_ch_light", "rapidocr"),
    ("paddleocr_v5_mobile", "paddleocr_text"),
    ("paddleocr_vl_16", "paddleocr_vl"),
    ("pp_structure_v3_light", "pp_structure_v3"),
    ("docling_local", "docling_worker"),
    ("mineru_local", "mineru_worker"),
    ("marker_local", "marker_worker"),
)


def _load_reference_normalizer(reference_root: Path):
    source = reference_root / "scripts/9_5_1_prediction_normalizer.py"
    spec = importlib.util.spec_from_file_location("pdffast_reference_normalizer", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("provider", "kind"), PROVIDERS)
def test_prediction_normalizer_is_byte_identical(
    tmp_path: Path,
    provider: str,
    kind: str,
) -> None:
    reference_root_raw = os.environ.get("PDFFAST_REFERENCE_ROOT")
    if not reference_root_raw:
        pytest.skip("PDFFAST_REFERENCE_ROOT is required")

    try:
        from pdffast.providers.normalization import normalize_prediction
    except ModuleNotFoundError as exc:
        pytest.fail(f"prediction normalizer migration is not implemented: {exc}")

    reference_root = Path(reference_root_raw).resolve()
    manifest_path = tmp_path / "provider_manifest.json"
    result_path = tmp_path / f"{provider}_result.json"
    task = {
        "task_id": "synthetic-region-1",
        "task_type": "REGION_FALLBACK",
        "page_number": 1,
        "source_id": "region-1",
        "capability_route": "REGION_MULTIMODAL_PARSE",
        "input_image": str(tmp_path / "region.png"),
    }
    manifest = {
        "name": "provider_benchmark",
        "selected_task_count": 1,
        "selected_tasks": [task],
        "selection": {"requested_providers": [provider]},
    }
    result = {
        **task,
        "provider": {
            "name": provider,
            "kind": kind,
            "model_or_engine": "synthetic-engine",
        },
        "status": "SUCCESS",
        "elapsed_seconds": 0.125,
        "text": "合成 Provider 文本 123",
        "confidence": 0.98,
        "warnings": [],
        "quality_hints": {"empty": False, "char_count": 12},
        "structure": {},
        "provider_raw_refs": [],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    task_map = {task["task_id"]: task}

    reference = _load_reference_normalizer(reference_root).normalize_one(
        manifest=manifest,
        manifest_path=manifest_path,
        task_map=task_map,
        provider=provider,
        result_path=result_path,
    )
    candidate = normalize_prediction(
        manifest=manifest,
        manifest_path=manifest_path,
        task_map=task_map,
        provider=provider,
        result_path=result_path,
    )
    assert json.dumps(candidate, ensure_ascii=False, indent=2) == json.dumps(
        reference, ensure_ascii=False, indent=2
    )
