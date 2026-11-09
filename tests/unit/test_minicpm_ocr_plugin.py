from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from pdffast.providers.base import ProviderTask
from pdffast.providers.minicpm_ocr import MiniCPMOCRProvider
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result
from tools.provider_benchmark.configure_minicpm import PLUGIN_NAME, with_minicpm


class FakeHTTP:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, n=-1):
        return json.dumps(self.data).encode("utf-8")


def fake_opener(request, timeout):
    assert timeout > 0
    if request.full_url.endswith("/models"):
        assert request.get_method() == "GET"
        return FakeHTTP({"data": [{"id": "minicpm-ocr"}]})
    assert request.full_url.endswith("/chat/completions")
    assert request.get_method() == "POST"
    payload = json.loads(request.data)
    assert payload["model"] == "minicpm-ocr"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert base64.b64decode(content[0]["image_url"]["url"].split(",")[1]) == b"fake-image"
    assert content[1] == {"type": "text", "text": "Text Recognition:"}
    return FakeHTTP({
        "choices": [{"message": {"content": "识别成功"}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 9},
    })


def test_minicpm_plugin_roundtrip_to_canonical(tmp_path):
    payload = with_minicpm({"providers": {"rapidocr_ch_light": {"runtime_enabled": True}}})
    assert "minicpm_ocr_local" not in payload.get("provider_chain_overrides", {})
    assert payload["providers"][PLUGIN_NAME]["runtime_enabled"] is False
    registry = ProviderRegistry(base_dir=tmp_path, plugins=payload["plugins"])
    assert registry.supports(PLUGIN_NAME, "minicpm_ocr_api")
    provider = MiniCPMOCRProvider(PLUGIN_NAME, payload["providers"][PLUGIN_NAME], opener=fake_opener)
    assert provider.preflight().available
    image_path = tmp_path / "p.png"
    image_path.write_bytes(b"fake-image")
    task = ProviderTask("x", "PAGE_DOCUMENT_OCR", image_path, metadata={"page_number": 1})
    raw = provider.execute(task)
    assert raw.status == "SUCCESS"
    assert raw.markdown == "识别成功"
    canonical = normalize_runtime_result(
        raw,
        {
            "task_id": "x", "task_type": "PAGE_FALLBACK",
            "page_number": 1, "source_id": "page:1",
            "capability_route": "PAGE_DOCUMENT_OCR",
            "input_image": str(image_path),
        },
        result_path=tmp_path / "result.json",
        manifest_path=tmp_path / "manifest.json",
        plugin_normalizer_paths=registry.plugin_normalizers,
    )
    assert canonical["status"] == "SUCCESS"
    assert canonical["text"]["content"] == "识别成功"
    assert canonical["reading_blocks"]["availability"] == "NOT_EMITTED"
    assert canonical["relations"]["availability"] == "UNSUPPORTED"
    assert canonical["provider"]["adapter"] == "minicpm_ocr_single_image_v1"


def test_minicpm_preflight_requires_served_model():
    def opener(request, timeout):
        return FakeHTTP({"data": [{"id": "another-model"}]})
    provider = MiniCPMOCRProvider(PLUGIN_NAME, {}, opener=opener)
    preflight = provider.preflight()
    assert not preflight.available
    assert "not served" in preflight.detail


def test_minicpm_rejects_remote_by_default():
    with pytest.raises(ValueError, match="allow_remote"):
        MiniCPMOCRProvider(PLUGIN_NAME, {"base_url": "https://example.com/v1"})


def test_minicpm_rejects_pdf(tmp_path):
    provider = MiniCPMOCRProvider(PLUGIN_NAME, {}, opener=fake_opener)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"fake")
    with pytest.raises(ValueError, match="not a PDF"):
        provider.execute(ProviderTask("a", "PAGE_DOCUMENT_OCR", pdf))


def test_minicpm_truncation_is_visible(tmp_path):
    def opener(request, timeout):
        if request.get_method() == "GET":
            return FakeHTTP({"data": [{"id": "minicpm-ocr"}]})
        return FakeHTTP({"choices": [
            {"message": {"content": "partial"}, "finish_reason": "length"}
        ]})
    provider = MiniCPMOCRProvider(PLUGIN_NAME, {}, opener=opener)
    png = tmp_path / "p.png"
    png.write_bytes(b"fake-image")
    raw = provider.execute(ProviderTask("a", "PAGE_DOCUMENT_OCR", png))
    assert raw.status == "SUCCESS_WITH_WARNINGS"
    assert "OUTPUT_TRUNCATED" in raw.warnings


def test_configuration_generator_never_mutates_existing_registry():
    initial = {"providers": {"rapidocr_ch_light": {"runtime_enabled": True}}}
    enhanced = with_minicpm(initial)
    assert list(initial["providers"]) == ["rapidocr_ch_light"]
    assert enhanced["providers"]["rapidocr_ch_light"]["runtime_enabled"] is True
    with pytest.raises(ValueError, match="already registered"):
        with_minicpm(enhanced)
