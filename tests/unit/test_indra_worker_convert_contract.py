"""Reproduce the real Indra 1.1.2 convert() yield shape in the embedded worker.

No ONNX download: the fake API yields (index, Page) exactly as upstream
indra_ocr.document.Converter.convert does. Tests exercise WORKER_CODE itself,
not only the Provider->Normalizer adapter.
"""
from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest

from pdffast.providers.indra import WORKER_CODE


def execute_fake_worker(tmp_path: Path, monkeypatch, *, page: object, yield_shape="tuple"):
    image = tmp_path / "region.png"
    image.write_bytes(b"not used by fake converter")
    model = tmp_path / "model"
    model.mkdir()
    (model / "det.onnx").write_bytes(b"fake")
    output = tmp_path / "out"
    request = {
        "op": "parse", "task_id": "region-test", "input": str(image),
        "model_dir": str(model), "output_dir": str(output), "threads": 4,
    }

    class FakeConverter:
        def convert(self, image_path):
            assert image_path == str(image)
            if yield_shape == "tuple":
                yield 0, page
            elif yield_shape == "page":
                yield page
            else:
                raise AssertionError(yield_shape)

    engine = types.ModuleType("indra_ocr")
    engine.__version__ = "1.1.2"
    engine.load = lambda **kwargs: FakeConverter()
    monkeypatch.setitem(sys.modules, "indra_ocr", engine)
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request) + "\n"))
    monkeypatch.setattr(sys, "stdout", stdout)
    exec(WORKER_CODE, {"__name__": "__main__"})
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert replies[0]["status"] == "READY"
    return replies[1], output


def test_real_indra_tuple_result_yields_nonempty_markdown_and_lines(tmp_path, monkeypatch):
    page = types.SimpleNamespace(
        source="ocr", markdown="## 测试\n中文数字 123", text="测试\n中文数字 123",
        lines=[types.SimpleNamespace(box=(1, 2, 50, 20), text="中文数字 123", conf=0.92)],
        blocks=[{"label": "Text", "text": "测试"}], rotation=0, skew=0,
        timings={"total_ms": 1.5},
    )
    response, folder = execute_fake_worker(tmp_path, monkeypatch, page=page)
    assert response["status"] == "SUCCESS"
    assert response["plain_text"] == "测试\n中文数字 123"
    assert response["source"] == "ocr"
    assert response["lines"][0]["text"] == "中文数字 123"
    assert Path(response["markdown_path"]).read_text(encoding="utf-8") == page.markdown
    raw_json = json.loads(next(folder.glob("*.json")).read_text(encoding="utf-8"))
    assert raw_json["plain_text"] == page.text
    assert raw_json["lines"][0]["text"] == "中文数字 123"


def test_indra_page_error_is_failure_not_empty_success(tmp_path, monkeypatch):
    page = types.SimpleNamespace(
        source="error", note="bad raster", markdown="", text="", lines=[],
    )
    response, folder = execute_fake_worker(tmp_path, monkeypatch, page=page)
    assert response["status"] == "FAILED"
    assert "bad raster" in response["error"]
    assert not list(folder.glob("*.md")) if folder.exists() else True


def test_indra_incorrect_bare_page_shape_fails_loudly(tmp_path, monkeypatch):
    page = types.SimpleNamespace(source="ocr", markdown="Text", text="Text", lines=[])
    response, folder = execute_fake_worker(
        tmp_path, monkeypatch, page=page, yield_shape="page"
    )
    assert response["status"] == "FAILED"
    assert "expected (0, Page)" in response["error"]
    assert not folder.exists()
