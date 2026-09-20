from __future__ import annotations

import json
import os
import select
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from .base import ProviderPreflight, ProviderTask, RawProviderResult


class WorkerProtocol(Protocol):
    def preflight(self) -> tuple[bool, str]: ...
    def start(self) -> dict[str, Any]: ...
    def request(self, command: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]: ...
    def close(self) -> None: ...


class JsonLineWorker:
    """Persistent subprocess speaking one JSON request/response per line."""

    def __init__(
        self,
        *,
        python_executable: Path,
        worker_code: str,
        dependency_probe_code: str,
        init_timeout_seconds: float = 300.0,
        preflight_timeout_seconds: float = 60.0,
        env: dict[str, str] | None = None,
    ) -> None:
        self.python_executable = Path(python_executable).absolute()
        self.worker_code = worker_code
        self.dependency_probe_code = dependency_probe_code
        self.init_timeout_seconds = init_timeout_seconds
        self.preflight_timeout_seconds = preflight_timeout_seconds
        self.extra_env = dict(env or {})
        self._process: subprocess.Popen[str] | None = None
        self._closed = False

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__"):
            env.pop(key, None)
        env.update(self.extra_env)
        return env

    def preflight(self) -> tuple[bool, str]:
        if not self.python_executable.exists():
            return False, f"python executable not found: {self.python_executable}"
        try:
            completed = subprocess.run(
                [str(self.python_executable), "-c", self.dependency_probe_code],
                capture_output=True,
                text=True,
                timeout=self.preflight_timeout_seconds,
                env=self._env(),
            )
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        output = (completed.stdout or completed.stderr or "").strip()
        return completed.returncode == 0, output or f"exit={completed.returncode}"

    def _read_response(self, timeout_seconds: float) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("worker is not started")
        ready, _, _ = select.select([process.stdout], [], [], timeout_seconds)
        if not ready:
            self._terminate()
            raise TimeoutError(f"worker response timeout after {timeout_seconds:g}s")
        line = process.stdout.readline()
        if not line:
            code = process.poll()
            self._terminate()
            raise RuntimeError(f"worker exited before response: exit={code}")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            self._terminate()
            raise RuntimeError(f"invalid worker JSON: {line[:500]}") from exc
        if not isinstance(response, dict):
            self._terminate()
            raise RuntimeError("worker response must be a JSON object")
        return response

    def start(self) -> dict[str, Any]:
        if self._process is not None and self._process.poll() is None:
            return {"status": "READY", "reused": True}
        if not self.python_executable.exists():
            raise FileNotFoundError(self.python_executable)
        self._process = subprocess.Popen(
            [str(self.python_executable), "-u", "-c", self.worker_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=self._env(),
        )
        self._closed = False
        response = self._read_response(self.init_timeout_seconds)
        if response.get("status") != "READY":
            self._terminate()
            raise RuntimeError(f"worker initialization failed: {response}")
        return response

    def request(self, command: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        self.start()
        process = self._process
        assert process is not None and process.stdin is not None
        process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        process.stdin.flush()
        return self._read_response(timeout_seconds)

    def _terminate(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def close(self) -> None:
        if self._closed:
            return
        process = self._process
        if process is not None and process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"op": "close"}) + "\n")
                process.stdin.flush()
                self._read_response(5.0)
            except Exception:
                pass
        self._terminate()
        self._closed = True


class IsolatedWorkerProvider:
    default_python = ""
    result_path_key = "markdown_path"
    worker_code = ""
    dependency_probe_code = ""

    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        *,
        worker_factory: Callable[[dict[str, Any]], WorkerProtocol] | None = None,
    ) -> None:
        self.name = name
        self.config = dict(config)
        self._worker_factory = worker_factory or self._default_worker_factory
        self._worker: WorkerProtocol | None = None
        self._started = False
        self._closed = False

    def _default_worker_factory(self, config: dict[str, Any]) -> WorkerProtocol:
        return JsonLineWorker(
            python_executable=Path(str(config.get("python_executable") or self.default_python)),
            worker_code=self.worker_code,
            dependency_probe_code=self.dependency_probe_code,
            init_timeout_seconds=float(config.get("worker_init_timeout_seconds", 300)),
            preflight_timeout_seconds=float(config.get("preflight_timeout_seconds", 60)),
            env={str(k): str(v) for k, v in (config.get("env") or {}).items()},
        )

    def _get_worker(self) -> WorkerProtocol:
        if self._worker is None:
            self._worker = self._worker_factory(self.config)
        return self._worker

    def preflight(self) -> ProviderPreflight:
        available, detail = self._get_worker().preflight()
        return ProviderPreflight(self.name, available, detail)

    def initialize(self) -> None:
        if not self._started:
            self._get_worker().start()
            self._started = True
            self._closed = False

    def build_command(self, task: ProviderTask) -> dict[str, Any]:
        return {
            "op": "parse",
            "input": str(task.input_image.absolute()),
            "output_dir": str(
                Path(str(task.metadata.get("raw_output_dir") or task.input_image.parent)).absolute()
            ),
        }

    def execute(self, task: ProviderTask) -> RawProviderResult:
        self.initialize()
        response = self._get_worker().request(
            self.build_command(task),
            timeout_seconds=float(self.config.get("predict_timeout_seconds", 600)),
        )
        if response.get("status") != "SUCCESS":
            raise RuntimeError(f"{self.name} parse failed: {response.get('error')}")
        output_path = Path(str(response.get(self.result_path_key) or ""))
        text = output_path.read_text(encoding="utf-8", errors="replace") if output_path.is_file() else ""
        warnings = () if text.strip() else ("EMPTY_TEXT",)
        return RawProviderResult(
            provider=self.name,
            task_id=task.task_id,
            status="SUCCESS",
            payload={
                "text": text.strip(),
                "confidence": None,
                "warnings": list(warnings),
                "structure": {
                    "persistent_worker": True,
                    "worker_elapsed_seconds": response.get("elapsed_seconds"),
                },
                "raw_refs": [str(value) for value in response.get("raw_refs") or []],
                "worker_response": response,
            },
            markdown=text,
            elapsed_seconds=response.get("elapsed_seconds"),
            warnings=warnings,
        )

    def close(self) -> None:
        if self._closed:
            return
        if self._worker is not None:
            self._worker.close()
        self._started = False
        self._closed = True
