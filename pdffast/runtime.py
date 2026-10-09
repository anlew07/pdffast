"""Per-parse logging, progress observation and runtime output capture."""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator, TextIO

from pdffast.errors import ParseExecutionError
from pdffast.runtime_format import ChineseRuntimeFormatter


class ParseCancelledError(BaseException):
    """Explicitly aborted work, never a recoverable Provider result."""


_cancellation: ContextVar[threading.Event | None] = ContextVar("pdffast_cancellation", default=None)


@contextlib.contextmanager
def cancellable_parse(cancelled: threading.Event) -> Iterator[None]:
    token = _cancellation.set(cancelled)
    try:
        yield
    finally:
        _cancellation.reset(token)


def check_parse_cancelled() -> None:
    cancelled = _cancellation.get()
    if cancelled is not None and cancelled.is_set():
        raise ParseCancelledError("parse aborted during service shutdown")


_capture_stream: ContextVar[TextIO | None] = ContextVar("pdffast_capture", default=None)
_observation: ContextVar[ParseObservation | None] = ContextVar("pdffast_observation", default=None)
_capture_lock = threading.RLock()
_capture_users = 0
_host_handlers: set[logging.Handler] = set()


class _ContextStream:
    """Route Python output to its caller's capture, leaving other threads alone."""

    def __init__(self, fallback: TextIO):
        self.fallback = fallback

    def write(self, text: str) -> int:
        stream = _capture_stream.get() or self.fallback
        written = stream.write(text)
        stream.flush()
        return written

    def flush(self) -> None:
        (_capture_stream.get() or self.fallback).flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(_capture_stream.get() or self.fallback, name)


class _HostFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return _capture_stream.get() is None


_host_filter = _HostFilter()


class _CapturedLogHandler(logging.StreamHandler):
    def filter(self, record: logging.LogRecord) -> bool:
        return _capture_stream.get() is self.stream and super().filter(record)


@contextlib.contextmanager
def capture_runtime_output(log_path: Path, *, enabled: bool = True) -> Iterator[None]:
    """Capture this context's debug output without replacing root handlers.

    Shared stream routers exist only while captures are active. Runtime events
    use a separate live logger; ordinary captured debug logs remain quiet.
    """
    if not enabled:
        yield
        return
    global _capture_users
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        handler = _CapturedLogHandler(stream)
        root = logging.getLogger()
        with _capture_lock:
            if _capture_users == 0:
                sys.stdout = _ContextStream(sys.stdout)
                sys.stderr = _ContextStream(sys.stderr)
            for host in root.handlers:
                if not isinstance(host, _CapturedLogHandler):
                    host.addFilter(_host_filter)
                    _host_handlers.add(host)
            _capture_users += 1
            root.addHandler(handler)
        token = _capture_stream.set(stream)
        try:
            yield
        finally:
            _capture_stream.reset(token)
            with _capture_lock:
                root.removeHandler(handler)
                handler.close()
                _capture_users -= 1
                if _capture_users == 0:
                    if isinstance(sys.stdout, _ContextStream):
                        sys.stdout = sys.stdout.fallback
                    if isinstance(sys.stderr, _ContextStream):
                        sys.stderr = sys.stderr.fallback
                    for host in _host_handlers:
                        host.removeFilter(_host_filter)
                    _host_handlers.clear()


class _LiveEventHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(ChineseRuntimeFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stderr
            if isinstance(stream, _ContextStream):
                stream = stream.fallback
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


_events = logging.getLogger("pdffast.runtime.events")
_events.setLevel(logging.INFO)
_events.propagate = False
_events.addHandler(_LiveEventHandler())


class ParseObservation:
    """Small run-owned state; stores no document, predictions or task payloads."""

    def __init__(self, run_id: str, *, log_path: Path | None, heartbeat_interval: float):
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be greater than zero")
        self.run_id = run_id
        self._started = self._last_progress = time.monotonic()
        self._phase = "parse_preparation"
        self._provider: str | None = None
        self._task_id: str | None = None
        self._task_started: float | None = None
        self._completed: int | None = None
        self._total: int | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._interval = heartbeat_interval
        self._thread = threading.Thread(
            target=self._heartbeat_loop, name=f"pdffast-heartbeat-{run_id}", daemon=True,
        )
        self._file: logging.FileHandler | None = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = logging.FileHandler(log_path, encoding="utf-8")

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            result: dict[str, Any] = {
                "run_id": self.run_id, "current_phase": self._phase,
                "elapsed_seconds": round(now - self._started, 3),
                "last_progress_elapsed_seconds": round(now - self._last_progress, 3),
            }
            if self._provider is not None:
                result["provider"] = self._provider
            if self._task_id is not None:
                result["task_id"] = self._task_id
                result["task_elapsed_seconds"] = round(now - self._task_started, 3)
            if self._total is not None:
                result.update(completed_tasks=self._completed, total_tasks=self._total)
            return result

    def _emit(self, event: str, *, exc: BaseException | None = None, **fields: Any) -> None:
        payload = self._snapshot()
        payload.update(fields, event=event, timestamp=datetime.now(timezone.utc).isoformat())
        if exc is not None:
            payload.update(exception_type=type(exc).__name__, exception_message=str(exc))
        level = logging.ERROR if exc is not None else logging.INFO
        record = _events.makeRecord(
            _events.name, level, __file__, 0,
            json.dumps(payload, ensure_ascii=False), (),
            (type(exc), exc, exc.__traceback__) if exc is not None else None,
            extra=payload,
        )
        # Observability sinks must not turn a recovered provider error into a
        # pipeline failure, or replace the original exception during teardown.
        try:
            _events.handle(record)
        except Exception:
            pass
        if self._file is not None:
            try:
                self._file.handle(record)
            except Exception:
                pass

    def progress(self, event: str, phase: str, **fields: Any) -> None:
        with self._lock:
            self._phase = phase
            self._last_progress = time.monotonic()
        self._emit(event, **fields)

    def provider_started(self, provider: str) -> None:
        with self._lock:
            self._provider = provider
        self.progress("provider_initialization_started", "provider_initialization")

    def tasks_known(self, total: int) -> None:
        with self._lock:
            self._total, self._completed = total, 0

    def task_started(self, provider: str, task_id: str) -> None:
        with self._lock:
            self._provider, self._task_id = provider, task_id
            self._task_started = time.monotonic()
        self.progress("provider_task_started", "provider_execution")

    def task_finished(self, *, accepted: bool, completed: int, status: str) -> None:
        with self._lock:
            self._completed = completed
        self.progress("provider_task_finished", "provider_execution", accepted=accepted, status=status)
        with self._lock:
            self._task_id = self._task_started = None

    def tasks_completed(self, completed: int) -> None:
        with self._lock:
            self._completed = completed
        self.progress("provider_task_terminal", "provider_execution")

    def providers_finished(self) -> None:
        self.progress("provider_execution_finished", "provider_execution")
        with self._lock:
            self._provider = self._task_id = self._task_started = None

    def diagnostic(self, event: str, **fields: Any) -> None:
        """Emit observational data without resetting actual progress time."""
        self._emit(event, **fields)

    def failure(self, event: str, exc: BaseException, **fields: Any) -> None:
        self._emit(event, exc=exc, **fields)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._emit("parse_heartbeat")

    def start(self) -> None:
        self.progress("parse_started", "parse_preparation")
        self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join()

    def close(self) -> None:
        self.stop_heartbeat()
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                # A failed diagnostic sink must not change the parse result.
                pass


def current_observation() -> ParseObservation | None:
    return _observation.get()


def runtime_progress(event: str, phase: str) -> None:
    check_parse_cancelled()
    run = current_observation()
    if run is not None:
        run.progress(event, phase)


@contextlib.contextmanager
def observe_parse(
    run_id: str, *, log_path: Path | None = None, heartbeat_interval: float = 30.0,
) -> Iterator[ParseObservation]:
    """Own heartbeat resources and preserve exceptions, including cancellation."""
    existing = current_observation()
    if existing is not None and existing.run_id == run_id:
        yield existing
        return
    run = ParseObservation(run_id, log_path=log_path, heartbeat_interval=heartbeat_interval)
    token = _observation.set(run)
    try:
        run.start()
        try:
            yield run
        except BaseException as exc:
            run.stop_heartbeat()
            error = exc.__cause__ if isinstance(exc, ParseExecutionError) and exc.__cause__ else exc
            run.failure("parse_failed", error)
            raise
        else:
            run.stop_heartbeat()
            run.progress("parse_finished", "finished")
    finally:
        try:
            run.close()
        finally:
            _observation.reset(token)
