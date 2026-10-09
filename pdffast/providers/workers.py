from __future__ import annotations

import ctypes
import json
import os
import select
import signal
import string
import subprocess
import sys
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


class _DarwinProcBSDInfo(ctypes.Structure):
    """Layout of macOS proc_bsdinfo (sys/proc_info.h)."""

    _fields_ = [
        *((name, ctypes.c_uint32) for name in (
            "flags", "status", "xstatus", "pid", "ppid", "uid", "gid",
            "ruid", "rgid", "svuid", "svgid", "reserved",
        )),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        *((name, ctypes.c_uint32) for name in (
            "nfiles", "pgid", "pjobc", "e_tdev", "e_tpgid",
        )),
        ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64),
        ("start_usec", ctypes.c_uint64),
    ]


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
        self._owned_group_members: dict[int, _ProcessIdentity] = {}
        self._sentinel_baselines: dict[
            Path, tuple[bytes | None, _ProcessIdentity | None]
        ] = {}
        self._owned_sentinels: dict[Path, tuple[bytes, _ProcessIdentity]] = {}
        self._closed = False
        self._response_buffer = b""

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
        from pdffast.runtime import check_parse_cancelled
        process = None
        try:
            check_parse_cancelled()
            process = subprocess.Popen(
                [str(self.python_executable), "-c", self.dependency_probe_code],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self._env(),
            )
            deadline = time.monotonic() + self.preflight_timeout_seconds
            while True:
                check_parse_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, self.preflight_timeout_seconds)
                try:
                    stdout, stderr = process.communicate(timeout=min(remaining, 0.1))
                    break
                except subprocess.TimeoutExpired:
                    continue
            output = (stdout or stderr or "").strip()
            return process.returncode == 0, output or f"exit={process.returncode}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    else:
                        process.wait()
                finally:
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()

    def _read_response(self, timeout_seconds: float, *, cancellable: bool = True) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("worker is not started")
        deadline = time.monotonic() + timeout_seconds
        try:
            while b"\n" not in self._response_buffer:
                if cancellable:
                    from pdffast.runtime import check_parse_cancelled
                    check_parse_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"worker response timeout after {timeout_seconds:g}s")
                ready, _, _ = select.select([process.stdout], [], [], min(remaining, 0.1))
                if not ready:
                    continue
                self._capture_process_group()
                self._capture_descendants()
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError(f"worker exited before response: exit={process.poll()}")
                self._response_buffer += chunk
            encoded, self._response_buffer = self._response_buffer.split(b"\n", 1)
            self._capture_process_group()
            self._capture_descendants()
            try:
                line = encoded.decode("utf-8")
                response = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"invalid worker JSON: {encoded[:500]!r}") from exc
        except BaseException:
            self._terminate()
            raise
        if not isinstance(response, dict):
            self._terminate()
            raise RuntimeError("worker response must be a JSON object")
        return response

    def start(self) -> dict[str, Any]:
        if self._process is not None:
            self._capture_process_group(
                require_continuity=self._process.returncode is not None
            )
            self._capture_descendants()
            if self._process.poll() is None:
                return {"status": "READY", "reused": True}
            self._terminate()
        if not self.python_executable.exists():
            raise FileNotFoundError(self.python_executable)
        self._snapshot_sentinels()
        self._response_buffer = b""
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
        try:
            response = self._read_response(self.init_timeout_seconds)
        except BaseException:
            if self._process is not None:
                self._terminate()
            raise
        if response.get("status") != "READY":
            self._terminate()
            raise RuntimeError(f"worker initialization failed: {response}")
        return response

    def request(self, command: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        self.start()
        process = self._process
        assert process is not None and process.stdin is not None
        try:
            process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            process.stdin.flush()
            return self._read_response(timeout_seconds)
        except BaseException:
            if self._process is not None:
                self._terminate()
            raise

    def _terminate(self) -> None:
        process = self._process
        self._capture_process_group(
            require_continuity=process is None or process.returncode is not None
        )
        self._capture_descendants()
        self._capture_sentinel_processes()
        self._process = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self._capture_process_group(require_continuity=True)
            self._terminate_descendants()
            self._process_group_id = None
        finally:
            self._close_pipes(process)

    @staticmethod
    def _close_pipes(process: subprocess.Popen[str] | None) -> None:
        if process is None:
            return
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                try:
                    pipe.close()
                except OSError:
                    # A broken stdin can report its pending flush error while
                    # closing; cleanup must not mask the original failure.
                    pass

    @staticmethod
    def _darwin_process_rows() -> tuple[tuple[int, int, int, _ProcessIdentity], ...] | None:
        """Read process identity without relying on the sandboxed `ps` executable."""
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            libproc.proc_listpids.argtypes = (
                ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int,
            )
            libproc.proc_listpids.restype = ctypes.c_int
            libproc.proc_pidinfo.argtypes = (
                ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int,
            )
            libproc.proc_pidinfo.restype = ctypes.c_int
            count_bytes = libproc.proc_listpids(1, 0, None, 0)  # PROC_ALL_PIDS
            if count_bytes <= 0:
                return None
            capacity = count_bytes // ctypes.sizeof(ctypes.c_int) + 256
            while True:
                pids = (ctypes.c_int * capacity)()
                filled_bytes = libproc.proc_listpids(1, 0, pids, ctypes.sizeof(pids))
                if filled_bytes < 0:
                    return None
                if filled_bytes < ctypes.sizeof(pids):
                    break
                capacity *= 2
            rows: list[tuple[int, int, int, _ProcessIdentity]] = []
            for pid in pids[:filled_bytes // ctypes.sizeof(ctypes.c_int)]:
                if pid <= 0:
                    continue
                info = _DarwinProcBSDInfo()
                size = libproc.proc_pidinfo(
                    pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info),
                )  # PROC_PIDTBSDINFO
                if size != ctypes.sizeof(info) or info.pid != pid or info.status == 5:
                    continue  # inaccessible, exited, or SZOMB (already terminated)
                identity = _ProcessIdentity(
                    pid=pid,
                    started_at=f"{info.start_sec}.{info.start_usec:06d}",
                    command=bytes(info.comm).split(b"\0", 1)[0].decode(errors="replace"),
                )
                rows.append((pid, info.ppid, info.pgid, identity))
            return tuple(rows)
        except (AttributeError, OSError, ValueError):
            return None

    @staticmethod
    def _process_rows() -> tuple[tuple[int, int, int, _ProcessIdentity], ...]:
        if sys.platform == "darwin":
            rows = JsonLineWorker._darwin_process_rows()
            if rows is not None:
                return rows
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
        if process is None or process.returncode is not None:
            return
        for identity in self._descendant_processes(process.pid):
            self._owned_descendants[identity.pid] = identity

    def _capture_process_group(self, *, require_continuity: bool = False) -> None:
        if self._process_group_id is None:
            return
        if require_continuity and not any(
            self._current_identity(pid) == identity
            for pid, identity in self._owned_group_members.items()
        ):
            return
        for identity in self._process_group_members(self._process_group_id):
            self._owned_descendants[identity.pid] = identity
            self._owned_group_members[identity.pid] = identity

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
        self._owned_group_members.clear()

    def close(self) -> None:
        if self._closed:
            return
        process = self._process
        self._capture_process_group()
        self._capture_descendants()
        self._capture_sentinel_processes()
        exited_cleanly = False
        if process is not None and process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write(json.dumps({"op": "close"}) + "\n")
                process.stdin.flush()
                response = self._read_response(5.0, cancellable=False)
                if response.get("status") == "BYE":
                    process.wait(timeout=5.0)
                    exited_cleanly = True
            except Exception:
                pass
        if exited_cleanly:
            self._process = None
            try:
                self._capture_process_group(require_continuity=True)
                self._terminate_descendants()
                self._process_group_id = None
            finally:
                self._close_pipes(process)
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
        from .supplemental import validate_supplemental

        supplemental = validate_supplemental(
            response.get("supplemental_evidence"),
            provider=self.name,
            page=task.metadata.get("page_number"),
            markdown=text,
        )
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
            supplemental_evidence=supplemental,
        )

    def close(self) -> None:
        if self._closed:
            return
        if self._worker is not None:
            self._worker.close()
        self._started = False
        self._closed = True
