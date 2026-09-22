from __future__ import annotations

import json
import os
import select
import signal
import string
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .base import ProviderPreflight, ProviderTask, RawProviderResult


@dataclass(frozen=True)
class _ProcessIdentity:
    pid: int
    started_at: str
    command: str


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
        process_sentinel_paths: tuple[Path, ...] = (),
        force_child_process_group: bool = False,
    ) -> None:
        self.python_executable = Path(python_executable).absolute()
        self.worker_code = worker_code
        self.dependency_probe_code = dependency_probe_code
        self.init_timeout_seconds = init_timeout_seconds
        self.preflight_timeout_seconds = preflight_timeout_seconds
        self.extra_env = dict(env or {})
        self.worker_id = uuid4().hex
        self.process_sentinel_paths = tuple(process_sentinel_paths)
        self.force_child_process_group = force_child_process_group
        self._process: subprocess.Popen[str] | None = None
        self._process_group_id: int | None = None
        self._owned_descendants: dict[int, _ProcessIdentity] = {}
        self._sentinel_baselines: dict[
            Path, tuple[bytes | None, _ProcessIdentity | None]
        ] = {}
        self._owned_sentinels: dict[Path, tuple[bytes, _ProcessIdentity]] = {}
        self._closed = False

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__"):
            env.pop(key, None)
        substitutions = dict(env)
        substitutions["PDFFAST_WORKER_ID"] = self.worker_id
        env["PDFFAST_WORKER_ID"] = self.worker_id
        env.update(
            {
                key: string.Template(value).safe_substitute(substitutions)
                for key, value in self.extra_env.items()
            }
        )
        return env

    def _sentinel_paths(self) -> tuple[Path, ...]:
        env = self._env()
        paths: list[Path] = []
        for raw_path in self.process_sentinel_paths:
            expanded = string.Template(str(raw_path)).safe_substitute(env)
            if expanded == "~" or expanded.startswith("~/"):
                expanded = str(Path(env.get("HOME", str(Path.home()))) / expanded[2:])
            paths.append(Path(expanded).absolute())
        return tuple(paths)

    @staticmethod
    def _read_sentinel(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
            return None

    @staticmethod
    def _sentinel_pid(content: bytes | None) -> int | None:
        if content is None:
            return None
        try:
            pid = int(json.loads(content).get("pid"))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return pid if pid > 0 else None

    def _snapshot_sentinels(self) -> None:
        self._sentinel_baselines.clear()
        self._owned_sentinels.clear()
        for path in self._sentinel_paths():
            content = self._read_sentinel(path)
            pid = self._sentinel_pid(content)
            identity = self._current_identity(pid) if pid is not None else None
            self._sentinel_baselines[path] = (content, identity)

    def _capture_sentinel_processes(self) -> None:
        for path, (baseline_content, baseline_identity) in self._sentinel_baselines.items():
            content = self._read_sentinel(path)
            if content is None or content == baseline_content:
                continue
            pid = self._sentinel_pid(content)
            if pid is None:
                continue
            identity = self._current_identity(pid)
            if identity is None or identity == baseline_identity:
                continue
            self._owned_descendants[pid] = identity
            self._owned_sentinels[path] = (content, identity)

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
        self._capture_descendants()
        self._capture_process_group()
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
        self._snapshot_sentinels()
        worker_code = self.worker_code
        if self.force_child_process_group:
            worker_code = r'''
import subprocess as _pdffast_subprocess
_pdffast_original_popen = _pdffast_subprocess.Popen
def _pdffast_grouped_popen(*args, **kwargs):
    if kwargs.get("start_new_session") is True:
        kwargs["start_new_session"] = False
    if kwargs.get("process_group") not in (None, -1):
        kwargs["process_group"] = None
    return _pdffast_original_popen(*args, **kwargs)
_pdffast_subprocess.Popen = _pdffast_grouped_popen
''' + worker_code
        self._process = subprocess.Popen(
            [str(self.python_executable), "-u", "-c", worker_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=self._env(),
            start_new_session=True,
        )
        self._process_group_id = self._process.pid
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
        self._capture_descendants()
        self._capture_process_group()
        self._capture_sentinel_processes()
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._capture_process_group()
        self._terminate_descendants()
        self._process_group_id = None

    @staticmethod
    def _process_rows() -> tuple[tuple[int, int, int, _ProcessIdentity], ...]:
        try:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,ppid=,pgid=,lstart=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except Exception:
            return ()

        rows: list[tuple[int, int, int, _ProcessIdentity]] = []
        for line in completed.stdout.splitlines():
            fields = line.split(None, 8)
            if len(fields) != 9:
                continue
            try:
                pid = int(fields[0])
                parent_pid = int(fields[1])
                process_group_id = int(fields[2])
            except ValueError:
                continue
            rows.append(
                (
                    pid,
                    parent_pid,
                    process_group_id,
                    _ProcessIdentity(
                        pid=pid,
                        started_at=" ".join(fields[3:8]),
                        command=fields[8],
                    ),
                )
            )
        return tuple(rows)

    @classmethod
    def _descendant_processes(cls, root_pid: int) -> tuple[_ProcessIdentity, ...]:
        """Return the current process tree below a worker.

        Some isolated providers launch detached model servers. Detaching changes
        the session but not the parent PID, so capture the tree while the worker
        is still alive and reap any survivors after its protocol shutdown.
        """
        children: dict[int, list[int]] = {}
        identities: dict[int, _ProcessIdentity] = {}
        for pid, parent_pid, _, identity in cls._process_rows():
            children.setdefault(parent_pid, []).append(pid)
            identities[pid] = identity

        descendants: list[_ProcessIdentity] = []
        pending = list(children.get(root_pid, ()))
        while pending:
            pid = pending.pop()
            identity = identities.get(pid)
            if identity is not None:
                descendants.append(identity)
            pending.extend(children.get(pid, ()))
        return tuple(descendants)

    @classmethod
    def _current_identity(cls, pid: int) -> _ProcessIdentity | None:
        return next(
            (
                identity
                for row_pid, _, _, identity in cls._process_rows()
                if row_pid == pid
            ),
            None,
        )

    @classmethod
    def _process_group_members(cls, process_group_id: int) -> tuple[_ProcessIdentity, ...]:
        return tuple(
            identity
            for pid, _, row_group_id, identity in cls._process_rows()
            if row_group_id == process_group_id and pid != process_group_id
        )

    def _capture_descendants(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        for identity in self._descendant_processes(process.pid):
            self._owned_descendants[identity.pid] = identity

    def _capture_process_group(self) -> None:
        if self._process_group_id is None:
            return
        for identity in self._process_group_members(self._process_group_id):
            self._owned_descendants[identity.pid] = identity

    def _terminate_descendants(self) -> None:
        remaining = dict(self._owned_descendants)
        self._owned_descendants.clear()
        for identity in reversed(tuple(remaining.values())):
            if self._current_identity(identity.pid) != identity:
                remaining.pop(identity.pid, None)
                continue
            try:
                os.kill(identity.pid, signal.SIGTERM)
            except ProcessLookupError:
                remaining.pop(identity.pid, None)
            except PermissionError:
                remaining.pop(identity.pid, None)

        deadline = time.monotonic() + 5.0
        while remaining and time.monotonic() < deadline:
            for pid, identity in tuple(remaining.items()):
                if self._current_identity(pid) != identity:
                    remaining.pop(pid, None)
            if remaining:
                time.sleep(0.05)

        for pid, identity in remaining.items():
            if self._current_identity(pid) != identity:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        for path, (content, identity) in tuple(self._owned_sentinels.items()):
            if self._current_identity(identity.pid) == identity:
                continue
            if self._read_sentinel(path) == content:
                try:
                    path.unlink()
                except (FileNotFoundError, PermissionError, OSError):
                    pass
        self._owned_sentinels.clear()

    def close(self) -> None:
        if self._closed:
            return
        process = self._process
        self._capture_descendants()
        self._capture_process_group()
        self._capture_sentinel_processes()
        exited_cleanly = False
        if process is not None and process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"op": "close"}) + "\n")
                process.stdin.flush()
                response = self._read_response(5.0)
                if response.get("status") == "BYE":
                    process.wait(timeout=5.0)
                    exited_cleanly = True
            except Exception:
                pass
        if exited_cleanly:
            self._process = None
            self._capture_process_group()
            self._terminate_descendants()
            self._process_group_id = None
        else:
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
            process_sentinel_paths=tuple(
                Path(str(value))
                for value in config.get("process_sentinel_paths") or ()
            ),
            force_child_process_group=bool(
                config.get("force_child_process_group", False)
            ),
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
