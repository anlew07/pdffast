"""Indra integration tests: isolation, canonical evidence, and fallback policy.

No model download or network required. Real PDF smoke runs separately on Mac.
"""
from __future__ import annotations

import json
from pathlib import Path

from pdffast.fallback.executor import _evaluate
from pdffast.providers.base import ProviderTask
from pdffast.providers.indra import IndraProvider
from pdffast.providers.indra_normalizer import normalize_indra
from pdffast.providers.normalization import validate_canonical
from pdffast.providers.profiles import apply_production_profile


class StubWorker:
    def __init__(self, folder):
        self.folder = folder
        self.starts = 0
        self.requests = []
        self.closed = False

    def preflight(self):
        return True, "fake-indra-ok"

    def start(self):
        self.starts += 1
        return {"status": "READY"}

    def request(self, cmd, *, timeout_seconds):
        self.requests.append(cmd)
        file = self.folder / f"result_{len(self.requests)}.md"
        file.write_text("中文 OCR 内容", encoding="utf-8")
        return {
            "status": "SUCCESS", "markdown_path": str(file),
            "raw_refs": [str(file)], "plain_text": "中文 OCR 内容",
            "lines": [{"box": [1, 2, 3, 4], "text": "中文 OCR 内容", "conf": 0.91}],
            "elapsed_seconds": 0.1,
        }

    def close(self):
        self.closed = True


def test_indra_is_lazy_and_reuses_persistent_worker(tmp_path):
    worker = StubWorker(tmp_path)
    provider = IndraProvider("indra_local", {
        "model_dir": str(tmp_path), "threads": 2, "predict_timeout_seconds": 15,
    }, worker_factory=lambda _: worker)
    assert worker.starts == 0
    assert provider.preflight().available
    image = tmp_path / "crop.png"
    image.write_bytes(b"stub crop; no image decoding with fake worker")
    task = ProviderTask(task_id="region-A", capability_route="REGION_MULTIMODAL_PARSE",
                        input_image=image, metadata={"raw_output_dir": str(tmp_path)})
    a = provider.execute(task)
    b = provider.execute(task)
    assert a.status == b.status == "SUCCESS"
    assert a.markdown.strip() == "中文 OCR 内容"
    assert worker.starts == 1
    assert len(worker.requests) == 2
    assert all(cmd["input"] == str(image) for cmd in worker.requests)
    assert all(cmd["op"] == "parse" for cmd in worker.requests)
    assert all(cmd["model_dir"] == str(tmp_path) for cmd in worker.requests)
    provider.close()
    assert worker.closed


def test_indra_normalizer_preserves_text_and_geometry(tmp_path):
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "result.json"
    manifest.write_text("{}", encoding="utf-8")
    output.write_text("{}", encoding="utf-8")
    result = {
        "task_id": "region-A", "status": "SUCCESS",
        "text": "中文 OCR 内容", "input_image": str(tmp_path / "crop.png"),
        "provider": {"name": "indra_local", "kind": "indra_worker",
                     "model_or_engine": "indra-ocr"},
        "warnings": [],
        "worker_response": {
            "plain_text": "中文 OCR 内容",
            "raw_refs": [str(output)],
            "lines": [{"text": "中文 OCR 内容", "box": [1, 2, 3, 4], "conf": 0.91}],
        },
    }
    task = {"task_id": "region-A", "task_type": "REGION_FALLBACK",
            "page_number": 3, "source_id": "region-01",
            "capability_route": "REGION_MULTIMODAL_PARSE",
            "input_image": str(tmp_path / "crop.png")}
    pred = normalize_indra(result=result, manifest_task=task,
                           manifest_path=manifest, result_path=output)
    validate_canonical(pred)
    assert pred["text"]["availability"] == "AVAILABLE"
    assert "中文 OCR 内容" in pred["text"]["content"]
    assert pred["spatial_text"]["items"][0]["text"] == "中文 OCR 内容"
    assert pred["tables"]["availability"] != "AVAILABLE"
    assert pred["relations"]["availability"] == "UNSUPPORTED"


def test_empty_indra_text_rejected_by_unchanged_stage98_gate(tmp_path):
    manifest = tmp_path / "manifest.json"
    output = tmp_path / "result.json"
    manifest.write_text("{}", encoding="utf-8")
    output.write_text("{}", encoding="utf-8")
    task = {"task_id": "region-A", "task_type": "REGION_FALLBACK",
            "page_number": 3, "source_id": "region-01",
            "capability_route": "REGION_MULTIMODAL_PARSE",
            "output_contract": {"required": ["text"], "empty_text_requires_warning": True}}
    result = {"task_id": "region-A", "status": "SUCCESS",
              "text": "", "provider": {"name": "indra_local", "kind": "indra_worker"}}
    pred = normalize_indra(result=result, manifest_task=task,
                           manifest_path=manifest, result_path=output)
    accepted, reasons = _evaluate(pred, task)
    assert accepted is False
    assert "EMPTY_TEXT_WHEN_REQUIRED" in reasons


def test_candidate_profile_uses_mineru_for_layout():
    root = Path(__file__).resolve().parents[2]
    profile = json.loads(
        (root / "configs/profiles/production.indra-triple.json").read_text(encoding="utf-8")
    )
    cfg = json.loads((root / "configs/providers.json").read_text(encoding="utf-8"))
    configs, routes = apply_production_profile(cfg["providers"], profile)
    assert routes["PAGE_DOCUMENT_LAYOUT_PARSE"] == ["mineru_local"]
    assert routes["PAGE_DOCUMENT_OCR"] == [
        "indra_local", "rapidocr_ch_light", "mineru_local"
    ]
    assert routes["INLINE_CONTEXT_PARSE"][-1] == "rapidocr_ch_light"
    assert set(name for chain in routes.values() for name in chain) == set(
        profile["enabled_providers"]
    )
    assert cfg["plugins"]["indra_local"]["factory"] == "pdffast.providers.indra:IndraProvider"
