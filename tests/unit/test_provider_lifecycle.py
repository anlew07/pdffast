from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

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
        {
            "kind": "rapidocr",
            "runtime_enabled": True,
            "benchmark_enabled": True,
            "predict_options": {"use_det": True},
        },
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
        {
            "kind": kind,
            "runtime_enabled": kind != "pp_structure_v3",
            "benchmark_enabled": True,
        },
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
        {
            "kind": kind,
            "runtime_enabled": True,
            "benchmark_enabled": False,
            "predict_timeout_seconds": 3,
        },
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


def test_json_line_worker_close_allows_worker_atexit_cleanup(tmp_path: Path) -> None:
    from pdffast.providers.workers import JsonLineWorker

    cleanup_marker = tmp_path / "child-atexit-ran.txt"
    code = f'''
import atexit, json, sys, time
from pathlib import Path
marker = Path({str(cleanup_marker)!r})
atexit.register(lambda: marker.write_text("clean", encoding="utf-8"))
print(json.dumps({{"status": "READY"}}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    if command.get("op") == "close":
        print(json.dumps({{"status": "BYE"}}), flush=True)
        time.sleep(0.5)
        break
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        init_timeout_seconds=1,
    )
    worker.start()

    worker.close()

    assert cleanup_marker.read_text(encoding="utf-8") == "clean"


def test_json_line_worker_close_reaps_detached_descendants() -> None:
    from pdffast.providers.workers import JsonLineWorker

    code = r'''
import json, subprocess, sys
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    start_new_session=True,
)
print(json.dumps({"status": "READY", "child_pid": child.pid}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    if command.get("op") == "close":
        print(json.dumps({"status": "BYE"}), flush=True)
        break
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        init_timeout_seconds=1,
    )
    child_pid = int(worker.start()["child_pid"])

    try:
        worker.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        subprocess.run(["kill", "-KILL", str(child_pid)], capture_output=True)


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


def test_json_line_worker_timeout_reaps_detached_descendants(tmp_path: Path) -> None:
    from pdffast.providers.workers import JsonLineWorker

    child_pid_path = tmp_path / "child.pid"
    code = f'''
import json, subprocess, sys, time
from pathlib import Path
print(json.dumps({{"status": "READY"}}), flush=True)
for line in sys.stdin:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        init_timeout_seconds=1,
    )
    worker.start()

    with pytest.raises(TimeoutError, match="response timeout"):
        worker.request({"op": "parse"}, timeout_seconds=0.2)

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_json_line_worker_eof_reaps_process_registered_in_new_sentinel(
    tmp_path: Path,
) -> None:
    """Catches a detached server leak when its worker exits before READY."""
    from pdffast.providers.workers import JsonLineWorker

    sentinel = tmp_path / "server.json"
    child_pid_path = tmp_path / "child.pid"
    code = f'''
import json, subprocess, sys
from pathlib import Path
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    start_new_session=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding="utf-8")
Path({str(sentinel)!r}).write_text(
    json.dumps({{"pid": child.pid}}), encoding="utf-8"
)
raise SystemExit(9)
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        process_sentinel_paths=(sentinel,),
        init_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match="worker exited before response"):
        worker.start()

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_json_line_worker_eof_reaps_grouped_child_before_sentinel_publication(
    tmp_path: Path,
) -> None:
    """Catches the detached-spawn to sentinel-publication crash window."""
    from pdffast.providers.workers import JsonLineWorker

    child_pid_path = tmp_path / "child.pid"
    code = f'''
import subprocess, sys
from pathlib import Path
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(60)"],
    start_new_session=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
Path({str(child_pid_path)!r}).write_text(str(child.pid), encoding="utf-8")
raise SystemExit(9)
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        force_child_process_group=True,
        init_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match="worker exited before response"):
        worker.start()

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_json_line_worker_does_not_own_unchanged_preexisting_sentinel(
    tmp_path: Path,
) -> None:
    """Catches cleanup of a shared model server that predates this worker."""
    from pdffast.providers.workers import JsonLineWorker

    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    sentinel = tmp_path / "server.json"
    sentinel.write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
    try:
        worker = JsonLineWorker(
            python_executable=Path(sys.executable),
            worker_code="raise SystemExit(9)",
            dependency_probe_code="print('probe=ok')",
            process_sentinel_paths=(sentinel,),
            init_timeout_seconds=1,
        )
        with pytest.raises(RuntimeError, match="worker exited before response"):
            worker.start()
        os.kill(child.pid, 0)
    finally:
        child.kill()
        child.wait(timeout=2)


def test_worker_receives_offline_environment_from_production_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdffast.providers.workers import JsonLineWorker

    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(name, raising=False)
    config = json.loads(Path("configs/providers.json").read_text(encoding="utf-8"))[
        "providers"
    ]["docling_local"]
    code = r'''
import json, os, sys
print(json.dumps({
    "status": "READY",
    "hf_offline": os.environ.get("HF_HUB_OFFLINE"),
    "transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE"),
}), flush=True)
for line in sys.stdin:
    command = json.loads(line)
    if command.get("op") == "close":
        print(json.dumps({"status": "BYE"}), flush=True)
        break
'''
    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code=code,
        dependency_probe_code="print('probe=ok')",
        env=config["env"],
        init_timeout_seconds=1,
    )

    ready = worker.start()
    worker.close()

    assert ready["hf_offline"] == "1"
    assert ready["transformers_offline"] == "1"


def test_workers_expand_nonce_templated_home_into_disjoint_sentinel_namespaces(
    tmp_path: Path,
) -> None:
    """Catches concurrent Marker workers sharing ambiguous sentinel ownership."""
    from pdffast.providers.workers import JsonLineWorker

    code = r'''
import json, os, sys
print(json.dumps({"status": "READY", "home": os.environ["HOME"]}), flush=True)
for line in sys.stdin:
    if json.loads(line).get("op") == "close":
        print(json.dumps({"status": "BYE"}), flush=True)
        break
'''

    def make_worker() -> JsonLineWorker:
        return JsonLineWorker(
            python_executable=Path(sys.executable),
            worker_code=code,
            dependency_probe_code="print('probe=ok')",
            env={
                "HOME": str(tmp_path / "marker-${PDFFAST_WORKER_ID}"),
            },
            process_sentinel_paths=(Path("${HOME}/server.json"),),
            init_timeout_seconds=1,
        )

    first = make_worker()
    second = make_worker()
    try:
        first_home = Path(first.start()["home"])
        second_home = Path(second.start()["home"])
        assert first_home.parent == tmp_path
        assert second_home.parent == tmp_path
        assert first_home != second_home
        assert first._sentinel_paths() == (first_home / "server.json",)
        assert second._sentinel_paths() == (second_home / "server.json",)
    finally:
        first.close()
        second.close()


def test_descendant_cleanup_does_not_signal_recycled_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdffast.providers.workers import JsonLineWorker, _ProcessIdentity

    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code="",
        dependency_probe_code="",
    )
    original = _ProcessIdentity(4242, "Sun Sep 21 16:00:00 2026", "owned-child")
    recycled = _ProcessIdentity(4242, "Sun Sep 21 16:01:00 2026", "unrelated")
    worker._owned_descendants[original.pid] = original
    monkeypatch.setattr(worker, "_current_identity", lambda pid: recycled)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))

    worker._terminate_descendants()

    assert signals == []
    worker.close()


def test_post_reap_group_scan_rejects_recycled_pgid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an unrelated replacement process group being claimed after reap."""
    from pdffast.providers.workers import JsonLineWorker, _ProcessIdentity

    worker = JsonLineWorker(
        python_executable=Path(sys.executable),
        worker_code="",
        dependency_probe_code="",
    )
    original = _ProcessIdentity(4243, "Tue Sep 22 09:00:00 2026", "owned-server")
    replacement = _ProcessIdentity(5001, "Tue Sep 22 09:01:00 2026", "unrelated")
    worker._process_group_id = 4242
    worker._owned_group_members[original.pid] = original
    monkeypatch.setattr(worker, "_current_identity", lambda pid: None)
    monkeypatch.setattr(
        worker,
        "_process_group_members",
        lambda pgid: (replacement,),
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))

    worker._capture_process_group(require_continuity=True)
    worker._terminate_descendants()

    assert replacement.pid not in worker._owned_descendants
    assert signals == []
