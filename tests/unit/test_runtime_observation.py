"""Real event emission, heartbeat lifecycle and concurrent run isolation."""

import logging
import asyncio
import threading
from pathlib import Path

import pytest

from pdffast import runtime


def observe(*args, **kwargs):
    factory = getattr(runtime, "observe_parse", None)
    assert callable(factory), "parse observation lifecycle is missing"
    return factory(*args, **kwargs)


class Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
        self.heartbeat = threading.Event()

    def emit(self, record):
        self.records.append(record)
        if getattr(record, "event", None) == "parse_heartbeat":
            self.heartbeat.set()


@pytest.fixture
def records():
    handler = Records()
    logger = logging.getLogger("pdffast.runtime.events")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


def test_progress_events_are_live_and_written_to_existing_log(tmp_path, records, capsys, monkeypatch):
    monkeypatch.setattr(runtime._events, "handlers", [h for h in runtime._events.handlers if not isinstance(h, runtime._LiveEventHandler)] + [runtime._LiveEventHandler(mode="debug")])
    path = tmp_path / "pipeline.log"
    with observe("live", log_path=path) as run:
        run.progress("native_analysis_started", "native_analysis")
        assert any(r.event == "native_analysis_started" for r in records.records)
        assert "[PDFFast][原生解析] 开始分析" in capsys.readouterr().err
        assert "native_analysis_started" in path.read_text()
    assert [r.event for r in records.records] == [
        "parse_started", "native_analysis_started", "parse_finished",
    ]
    assert all(r.run_id == "live" for r in records.records)


def test_heartbeat_reports_inactivity_without_updating_progress(tmp_path, records):
    with observe("long", log_path=tmp_path / "log", heartbeat_interval=0.01) as run:
        run.progress("native_analysis_started", "native_analysis")
        assert records.heartbeat.wait(2), "long-running parse emitted no heartbeat"
        first = next(r for r in records.records if r.event == "parse_heartbeat")
        records.heartbeat.clear()
        assert records.heartbeat.wait(2)
        last = [r for r in records.records if r.event == "parse_heartbeat"][-1]
        assert last.current_phase == "native_analysis"
        assert last.last_progress_elapsed_seconds > first.last_progress_elapsed_seconds
        assert last.elapsed_seconds > first.elapsed_seconds
        assert not hasattr(last, "provider")
    count = len(records.records)
    records.heartbeat.clear()
    assert not records.heartbeat.wait(0.03)
    assert len(records.records) == count


@pytest.mark.parametrize("failure", [ValueError("broken"), KeyboardInterrupt("cancelled"), asyncio.CancelledError("cancelled"), SystemExit("exit")])
def test_failure_or_cancel_logs_context_and_releases_heartbeat(tmp_path, records, failure):
    before = {t.ident for t in threading.enumerate()}
    with pytest.raises(type(failure)):
        with observe("failed", log_path=tmp_path / "log", heartbeat_interval=0.01) as run:
            run.progress("native_analysis_started", "native_analysis")
            raise failure
    failed = next(r for r in records.records if r.event == "parse_failed")
    assert failed.run_id == "failed"
    assert failed.current_phase == "native_analysis"
    assert failed.exception_type == type(failure).__name__
    assert failed.exception_message == str(failure)
    assert failed.exc_info is not None
    assert not any(t.ident not in before and t.name.startswith("pdffast-heartbeat") for t in threading.enumerate())
    records.heartbeat.clear()
    assert not records.heartbeat.wait(0.03)


def test_concurrent_capture_and_heartbeat_do_not_mix_runs(tmp_path, records):
    barrier = threading.Barrier(2)
    errors = []
    def parse(run_id):
        try:
            with observe(run_id, log_path=tmp_path / f"{run_id}.log", heartbeat_interval=0.01) as run:
                with runtime.capture_runtime_output(tmp_path / f"{run_id}.log"):
                    run.progress("native_analysis_started", f"native_{run_id}")
                    barrier.wait(timeout=2)
                    print(f"print-only-{run_id}", flush=True)
                    logging.getLogger("pdffast.provider").warning(f"warning-only-{run_id}")
                    # Hold both runs open until each has a heartbeat.
                    deadline = threading.Event()
                    for _ in range(100):
                        if any(getattr(r, "run_id", None) == run_id and r.event == "parse_heartbeat" for r in records.records):
                            break
                        deadline.wait(0.01)
                    barrier.wait(timeout=2)
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=parse, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=3)
    assert not errors
    assert not any(t.is_alive() for t in threads)
    for name, other in (("alpha", "beta"), ("beta", "alpha")):
        log = (tmp_path / f"{name}.log").read_text()
        assert f"print-only-{name}" in log and f"warning-only-{name}" in log
        assert f"print-only-{other}" not in log and f"warning-only-{other}" not in log
        assert f'"run_id": "{other}"' not in log
        heartbeats = [r for r in records.records if r.event == "parse_heartbeat" and r.run_id == name]
        assert heartbeats and all(r.current_phase == f"native_{name}" for r in heartbeats)


def test_repeated_start_stop_restores_streams_and_handlers(tmp_path, records):
    import sys
    streams = sys.stdout, sys.stderr
    handlers = tuple(logging.getLogger().handlers)
    for index in range(8):
        with observe(str(index), log_path=tmp_path / f"{index}.log", heartbeat_interval=0.01):
            with runtime.capture_runtime_output(tmp_path / f"{index}.log"):
                print("captured")
    assert (sys.stdout, sys.stderr) == streams
    assert tuple(logging.getLogger().handlers) == handlers
    assert not any(t.name.startswith("pdffast-heartbeat") for t in threading.enumerate())


def test_observation_nesting_emits_one_parse_lifecycle(records):
    with observe("nested") as outer:
        with observe("nested") as inner:
            assert inner is outer
    assert [r.event for r in records.records] == ["parse_started", "parse_finished"]


def test_log_handler_failure_cannot_replace_parse_exception(tmp_path):
    class BrokenHandler(logging.Handler):
        def emit(self, record): raise OSError("log sink failed")
    logger = logging.getLogger("pdffast.runtime.events")
    handler = BrokenHandler()
    logger.addHandler(handler)
    try:
        with pytest.raises(ValueError, match="original parse failure"):
            with observe("bad-sink", log_path=tmp_path / "log"):
                raise ValueError("original parse failure")
    finally:
        logger.removeHandler(handler)
    assert not any(t.name.startswith("pdffast-heartbeat") for t in threading.enumerate())
    assert "original parse failure" in (tmp_path / "log").read_text()


def test_uncaptured_host_thread_keeps_logging_to_host(tmp_path, capsys):
    import sys
    handler = logging.StreamHandler(sys.stderr)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with runtime.capture_runtime_output(tmp_path / "log"):
            thread = threading.Thread(target=lambda: logging.getLogger("host").warning("host alive"))
            thread.start()
            thread.join(timeout=2)
    finally:
        root.removeHandler(handler)
        handler.close()
    assert "host alive" in capsys.readouterr().err
    assert "host alive" not in (tmp_path / "log").read_text()


@pytest.mark.parametrize("fails", [False, True])
def test_file_close_failure_does_not_leak_observer_or_mask_parse(tmp_path, records, monkeypatch, fails):
    original_close = logging.FileHandler.close
    def broken_close(handler):
        original_close(handler)
        raise OSError("close failed")
    monkeypatch.setattr(logging.FileHandler, "close", broken_close)
    failure = ValueError("original failure")
    if fails:
        with pytest.raises(ValueError) as caught:
            with observe("close-failure", log_path=tmp_path / "log"):
                raise failure
        assert caught.value is failure
    else:
        with observe("close-failure", log_path=tmp_path / "log"):
            pass
    assert runtime.current_observation() is None
    assert not any(t.name.startswith("pdffast-heartbeat") for t in threading.enumerate())
    with observe("close-failure"):
        pass
    assert sum(r.event == "parse_started" for r in records.records) == 2
    monkeypatch.setattr(logging.FileHandler, "close", original_close)
