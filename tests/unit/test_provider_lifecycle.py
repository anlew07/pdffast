from __future__ import annotations

from pathlib import Path
import sys

import pytest

from pdffast.providers.base import ProviderTask


class RapidResult:
    txts = ["alpha", "beta"]
    scores = [0.8, 1.0]
    boxes = [[[0, 0], [10, 0], [10, 5], [0, 5]]]
    elapse = 0.25
    elapse_list = [0.1, 0.15]


class FakeRapidEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, image: str, **kwargs):
        self.calls.append((image, kwargs))
        return RapidResult()


class PaddleResult:
    def __init__(self, payload: dict, markdown: str = "") -> None:
        self.json = payload
        self.markdown = markdown


class FakePaddleEngine:
    def __init__(self, results: list[PaddleResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict]] = []

    def predict(self, *, input: str, **kwargs):
        self.calls.append((input, kwargs))
        return self.results


class FakeWorker:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.started = 0
        self.closed = 0
        self.commands: list[dict] = []

    def preflight(self):
        return True, "fake worker ready"

    def start(self) -> dict:
        self.started += 1
        return {"status": "READY", "worker": "fake"}

    def request(self, command: dict, *, timeout_seconds: float) -> dict:
        self.commands.append(command)
        return self.response

    def close(self) -> None:
        self.closed += 1


def _task(tmp_path: Path) -> ProviderTask:
    image = tmp_path / "input.png"
    image.write_bytes(b"not-a-real-image")
    return ProviderTask(
        task_id="task-1",
        capability_route="REGION_MULTIMODAL_PARSE",
        input_image=image,
    )


def test_rapidocr_lifecycle_is_lazy_reused_and_idempotently_closed(tmp_path: Path) -> None:
    from pdffast.providers.rapidocr import RapidOCRProvider

    engine = FakeRapidEngine()
    factory_calls: list[dict] = []

    def factory(config: dict):
        factory_calls.append(config)
        return engine

    provider = RapidOCRProvider(
        "rapid",
        {"kind": "rapidocr", "enabled": True, "predict_options": {"use_det": True}},
        engine_factory=factory,
        dependency_probe=lambda: (True, "rapidocr=fake"),
    )

    assert provider.preflight().available is True
    assert factory_calls == []
    provider.initialize()
    provider.initialize()
    first = provider.execute(_task(tmp_path))
    second = provider.execute(_task(tmp_path))
    provider.close()
    provider.close()

    assert len(factory_calls) == 1
    assert len(engine.calls) == 2
    assert first.payload["text"] == "alpha\nbeta"
    assert first.payload["confidence"] == pytest.approx(0.9)
    assert first.payload["structure"]["ocr_line_count"] == 2
    assert second.status == "SUCCESS"


@pytest.mark.parametrize(
    ("class_name", "kind", "payload", "markdown", "expected_text"),
    [
        (
            "PaddleOCRTextProvider",
            "paddleocr_text",
            {"rec_texts": ["one", "two"], "rec_scores": [0.7, 0.9]},
            "",
            "one\ntwo",
        ),
        ("PaddleOCRVLProvider", "paddleocr_vl", {"blocks": []}, "# title", "# title"),
        (
            "PPStructureV3Provider",
            "pp_structure_v3",
            {"blocks": []},
            "| a |\n|---|",
            "| a |\n|---|",
        ),
    ],
)
def test_paddle_adapters_share_lifecycle_without_importing_dependency(
    tmp_path: Path,
    class_name: str,
    kind: str,
    payload: dict,
    markdown: str,
    expected_text: str,
) -> None:
    from pdffast.providers import paddleocr

    engine = FakePaddleEngine([PaddleResult(payload, markdown)])
    provider_class = getattr(paddleocr, class_name)
    provider = provider_class(
        "paddle",
        {"kind": kind, "enabled": True},
        engine_factory=lambda config: engine,
        dependency_probe=lambda: (True, "paddleocr=fake"),
    )

    assert provider.preflight().available is True
    result = provider.execute(_task(tmp_path))
    provider.close()
    provider.close()

    assert result.status == "SUCCESS"
    assert result.payload["text"] == expected_text
    assert engine.calls == [(str(tmp_path / "input.png"), {})]


@pytest.mark.parametrize(
    ("module_name", "class_name", "kind", "response_path_key"),
    [
        ("docling", "DoclingProvider", "docling_worker", "markdown_path"),
        ("mineru", "MinerUProvider", "mineru_worker", "markdown_path"),
        ("marker", "MarkerProvider", "marker_worker", "result_path"),
    ],
)
def test_isolated_adapters_use_persistent_worker_and_close_once(
    tmp_path: Path,
    module_name: str,
    class_name: str,
    kind: str,
    response_path_key: str,
) -> None:
    import importlib

    output = tmp_path / "result.md"
    output.write_text("worker markdown", encoding="utf-8")
    worker = FakeWorker(
        {
            "status": "SUCCESS",
            response_path_key: str(output),
            "raw_refs": [str(output)],
            "elapsed_seconds": 1.25,
        }
    )
    module = importlib.import_module(f"pdffast.providers.{module_name}")
    provider_class = getattr(module, class_name)
    provider = provider_class(
        "worker-provider",
        {"kind": kind, "enabled": True, "predict_timeout_seconds": 3},
        worker_factory=lambda config: worker,
    )

    assert provider.preflight().available is True
    provider.initialize()
    result = provider.execute(_task(tmp_path))
    provider.close()
    provider.close()

    assert worker.started == 1
    assert worker.closed == 1
    assert worker.commands[0]["op"] == "parse"
    assert worker.commands[0]["input"] == str(tmp_path / "input.png")
    assert result.payload["text"] == "worker markdown"
    assert result.elapsed_seconds == 1.25


def test_json_line_worker_round_trip_and_idempotent_close() -> None:
    from pdffast.providers.workers import JsonLineWorker

    code = r'''
import json, sys
print(json.dumps({"status": "READY"}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    if command.get("op") == "close":
        print(json.dumps({"status": "BYE"}), flush=True)
        break
    print(json.dumps({"status": "SUCCESS", "echo": command}), flush=True)
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        init_timeout_seconds=1,
    )

    assert worker.preflight() == (True, "probe=ok")
    assert worker.start()["status"] == "READY"
    response = worker.request({"op": "parse", "value": 7}, timeout_seconds=1)
    worker.close()
    worker.close()

    assert response == {
        "status": "SUCCESS",
        "echo": {"op": "parse", "value": 7},
    }


def test_json_line_worker_timeout_terminates_process() -> None:
    from pdffast.providers.workers import JsonLineWorker

    code = r'''
import json, sys, time
print(json.dumps({"status": "READY"}), flush=True)
for line in sys.stdin:
    time.sleep(5)
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        init_timeout_seconds=1,
    )
    worker.start()

    with pytest.raises(TimeoutError, match="response timeout"):
        worker.request({"op": "parse"}, timeout_seconds=0.01)

    assert worker._process is None
    worker.close()
