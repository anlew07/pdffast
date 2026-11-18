"""Port the four historical Indra CLI behaviors to the V3 persistent-worker contract.

The earlier local-only test_indra_provider.py used subprocess.run and the
temporary indra_ocr/indra_cli plugin. It is not a V3 runtime contract test.
These tests preserve the behaviors, using fake workers instead of external OCR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pdffast.providers.base import ProviderTask, RawProviderResult
from pdffast.providers.indra import IndraProvider
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result


class FakeWorker:
    def __init__(self, folder: Path, *, result="success"):
        self.folder = folder
        self.result = result
        self.started = 0
        self.requests = 0
        self.closed = False

    def preflight(self):
        return True, "fake-ready"

    def start(self):
        self.started += 1
        return {"status": "READY"}

    def request(self, command, *, timeout_seconds):
        self.requests += 1
        assert command["op"] == "parse"
        if self.result == "failed":
            return {"status": "FAILED", "error": "failed"}
        if self.result == "timeout":
            raise TimeoutError("fake worker response timeout")
        filename = self.folder / "image_text.md"
        filename.write_text("识别文本\n", encoding="utf-8")
        return {"status": "SUCCESS", "markdown_path": str(filename),
                "elapsed_seconds": 0.25, "raw_refs": [str(filename)]}

    def close(self):
        self.closed = True


def task_for(tmp_path: Path) -> ProviderTask:
    image = tmp_path / "crop.png"
    image.write_bytes(b"fake image, not decoded by FakeWorker")
    return ProviderTask("task1", "PAGE_DOCUMENT_OCR", image, {
        "raw_output_dir": str(tmp_path),
    })


def make_provider(tmp_path: Path, outcome: str):
    worker = FakeWorker(tmp_path, result=outcome)
    provider = IndraProvider(
        "indra_local", {"model_dir": str(tmp_path), "predict_timeout_seconds": 3},
        worker_factory=lambda _: worker,
    )
    return provider, worker


def test_v3_success_preserves_ocr_text(tmp_path):
    provider, worker = make_provider(tmp_path, "success")
    try:
        result = provider.execute(task_for(tmp_path))
        assert result.status == "SUCCESS"
        assert "识别文本" in result.markdown
        assert result.provider == "indra_local"
        assert worker.requests == 1
    finally:
        provider.close()


def test_v3_failed_worker_propagates_for_fallback(tmp_path):
    provider, worker = make_provider(tmp_path, "failed")
    try:
        with pytest.raises(RuntimeError, match="failed"):
            provider.execute(task_for(tmp_path))
        assert worker.requests == 1
    finally:
        provider.close()


def test_v3_worker_timeout_propagates_for_fallback(tmp_path):
    provider, worker = make_provider(tmp_path, "timeout")
    try:
        with pytest.raises(TimeoutError, match="timeout"):
            provider.execute(task_for(tmp_path))
        assert worker.requests == 1
    finally:
        provider.close()


def test_v3_real_plugin_registry_and_canonical_normalization(tmp_path):
    plugins = {
        "indra_local": {
            "kind": "indra_worker",
            "factory": "pdffast.providers.indra:IndraProvider",
            "normalizer": "pdffast.providers.indra_normalizer:normalize_indra",
        }
    }
    registry = ProviderRegistry(plugins=plugins, base_dir=tmp_path)
    provider = registry.create("indra_local", {
        "kind": "indra_worker", "runtime_enabled": True,
        "python_executable": "/unused/python", "model_dir": str(tmp_path),
    })
    assert isinstance(provider, IndraProvider)
    raw = RawProviderResult(
        provider="indra_local", task_id="task1",
        status="SUCCESS", payload={"text": "识别内容"},
    )
    prediction = normalize_runtime_result(
        raw, {"task_id": "task1", "capability_route": "PAGE_DOCUMENT_OCR"},
        result_path=tmp_path / "result.json",
        manifest_path=tmp_path / "manifest.json",
        plugin_normalizer_paths=registry.plugin_normalizers,
    )
    assert prediction["text"]["content"].strip() == "识别内容"
    assert prediction["provider"]["name"] == "indra_local"
    assert prediction["normalization_policy"]["re_ocr"] is False
