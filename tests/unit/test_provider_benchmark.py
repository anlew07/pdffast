from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdffast.providers.base import ProviderPreflight, RawProviderResult
from tools.provider_benchmark.run import choose_input, read_jsonl, run_benchmark


class FakeProvider:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.calls = 0
        self.closed = False

    def preflight(self):
        return ProviderPreflight(self.name, True)

    def initialize(self):
        pass

    def execute(self, task):
        self.calls += 1
        return RawProviderResult(self.name, task.task_id, "SUCCESS", {}, markdown="测试文本")

    def close(self):
        self.closed = True


class FakeRegistry:
    def __init__(self):
        self.created = []

    def create(self, name, cfg):
        item = FakeProvider(name, cfg)
        self.created.append(item)
        return item


def fake_normalizer(raw, task, **kwargs):
    return {"text": {"content": raw.markdown}}


def test_benchmark_runs_real_provider_contract_and_keeps_prod_disabled(tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(b"image-placeholder")
    rows = [{"page_id": "x:p001", "image": img.name, "page_number": 1}]
    original = {"mock": {"kind": "rapidocr", "benchmark_enabled": True, "runtime_enabled": False}}
    registry = FakeRegistry()
    result = run_benchmark(
        rows=rows, names=["mock"], provider_configs=original, registry=registry,
        output_dir=tmp_path / "out", input_base=tmp_path, normalizer=fake_normalizer,
    )
    assert result[0]["status"] == "SUCCESS"
    assert result[0]["text"] == "测试文本"
    assert result[0]["input_sha256"]
    assert original["mock"]["runtime_enabled"] is False
    assert registry.created[0].config["runtime_enabled"] is True
    assert registry.created[0].closed
    assert (tmp_path / "out/predictions.jsonl").is_file()
    assert (tmp_path / "out/run_manifest.json").is_file()


def test_missing_input_is_explicit_not_fake_success(tmp_path):
    result = run_benchmark(
        rows=[{"page_id": "missing", "image": "absent.png"}], names=["mock"],
        provider_configs={"mock": {"kind": "rapidocr", "benchmark_enabled": True}},
        registry=FakeRegistry(), output_dir=tmp_path / "out", input_base=tmp_path,
        normalizer=fake_normalizer,
    )
    assert result[0]["status"] == "SKIPPED_INPUT"
    assert result[0]["text"] is None


def test_benchmark_unapproved_requires_opt_in(tmp_path):
    with pytest.raises(ValueError, match="benchmark_enabled"):
        run_benchmark(
            rows=[{"page_id": "x", "image": "missing"}], names=["x"],
            provider_configs={"x": {"benchmark_enabled": False}}, registry=FakeRegistry(),
            output_dir=tmp_path, input_base=tmp_path,
        )


def test_inputs_use_pdf_for_workers_and_image_for_ocr(tmp_path):
    row = {"image": "x.png", "pdf": "x.pdf"}
    assert choose_input(row, {"kind": "mineru_worker"}, tmp_path) == tmp_path / "x.pdf"
    assert choose_input(row, {"kind": "rapidocr"}, tmp_path) == tmp_path / "x.png"
    assert choose_input(row, {"kind": "custom", "benchmark_input": "pdf"}, tmp_path) == tmp_path / "x.pdf"


def test_jsonl_rejects_duplicate_page_ids(tmp_path):
    p = tmp_path / "manifest.jsonl"
    p.write_text('{"page_id":"x"}\n{"page_id":"x"}\n')
    with pytest.raises(ValueError, match="duplicate"):
        read_jsonl(p)
