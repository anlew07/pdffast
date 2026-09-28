from pathlib import Path

from pdffast.providers.base import RawProviderResult
from pdffast.providers.runtime_normalization import normalize_runtime_result


def test_runtime_adapter_writes_provider_object_for_marker_worker(tmp_path: Path) -> None:
    task = {
        "task_id": "task-1",
        "task_type": "REGION_FALLBACK",
        "page_number": 1,
        "source_id": "p0001_r001",
        "capability_route": "REGION_MULTIMODAL_PARSE",
        "output_contract": {"required": ["text"]},
    }
    raw = RawProviderResult(
        provider="marker_local",
        task_id="task-1",
        status="SUCCESS",
        payload={"text": "识别结果", "structure": {}},
    )

    prediction = normalize_runtime_result(
        raw,
        task,
        result_path=tmp_path / "raw.json",
        manifest_path=tmp_path / "runtime_manifest.json",
    )

    assert prediction["status"] == "SUCCESS"
    assert prediction["provider"]["name"] == "marker_local"
    assert prediction["text"]["content"] == "识别结果"
