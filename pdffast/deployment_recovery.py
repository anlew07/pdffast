"""Prepare and reconcile one-shot per-user launchd recovery jobs on macOS."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import math
import os
import platform
import plistlib
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from pdffast.application.production_identity import code_identity
from pdffast.process_supervisor import CORE_TERM_GRACE, supervise
from pdffast.providers.workers import JsonLineWorker

PREFIX = "local.pdffast.v1."
ID = re.compile(r"[0-9a-f]{32}")
JOB_PID = re.compile(r"^\s*pid = ([1-9]\d*)\s*$", re.MULTILINE)
SWEEP_FRESHNESS_SECONDS = 60
CONTROLLER_LABEL = "local.pdffast.v1.reconcile"
CONTROLLER_INTERVAL_SECONDS = 20
CANCEL_TIMEOUT_SECONDS = 4.75  # Leaves room for CLI startup in JudgeAI's five-second window.
CANCEL_COOPERATIVE_SECONDS = CORE_TERM_GRACE + 0.5
POLL_SECONDS = 0.04
_STATE_ERRORS = (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError, TypeError)


class ControlError(RuntimeError):
    """Stable deployment control failure."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(detail or code)


def _write(path: Path, data: dict, *, plist: bool = False, replace: bool = False) -> None:
    payload = plistlib.dumps(data) if plist else json.dumps(data, allow_nan=False).encode()
    with tempfile.NamedTemporaryFile(dir=path.parent) as tmp:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        if replace:
            # Only the sweep heartbeat is mutable. Keep the receipt path create-only.
            pending = Path(tmp.name).with_suffix(".publish")
            try:
                os.link(tmp.name, pending)
                os.replace(pending, path)
            finally:
                pending.unlink(missing_ok=True)
        else:
            os.link(tmp.name, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _root(root: Path) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("this deployment backend requires macOS launchd")
    root = root.absolute()
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("state root must be a private directory owned by the deployment user")
    return root.resolve()


def _domain(value: str) -> str:
    if value not in (f"gui/{os.getuid()}", f"user/{os.getuid()}"):
        raise ValueError("only the current user's launchd domain is supported")
    return value


def _launch(*args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/bin/launchctl", *args], text=True, capture_output=True, check=False, timeout=timeout,
    )


def _time_left(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ControlError("DEADLINE_EXCEEDED")
    return remaining


def _checked(result: subprocess.CompletedProcess) -> None:
    if result.returncode:
        raise RuntimeError(f"launchctl exited {result.returncode}: {result.stderr.strip()}")


def prepare(root: Path, *, domain: str, log: Path, timeout: float, command: list[str],
            lease_seconds: float | None = None) -> str:
    root = _root(root)
    domain = _domain(domain)
    lease = timeout + 30 if lease_seconds is None else lease_seconds
    if not all(math.isfinite(x) and x > 0 for x in (timeout, lease)) or not command:
        raise ValueError("finite positive timeout and lease and a trusted Core command are required")
    if not log.is_absolute() or not Path(command[0]).is_absolute():
        raise ValueError("Core interpreter and log paths must be absolute")
    run = uuid.uuid4().hex
    path = root / run
    path.mkdir(mode=0o700)
    label = PREFIX + run
    _write(path / "job.plist", {
        "Label": label,
        "ProgramArguments": [sys.executable, "-B", "-m", "pdffast.deployment_recovery", "job", str(root), run],
        "WorkingDirectory": str(Path.cwd().resolve()),
        "RunAtLoad": True,
        "KeepAlive": False,
        "AbandonProcessGroup": False,
        "ExitTimeOut": 1,
        "StandardOutPath": str(path / "launchd.stdout"),
        "StandardErrorPath": str(path / "launchd.stderr"),
    }, plist=True)
    _write(path / "plan.json", {
        "domain": domain, "command": command, "log": str(log), "timeout": timeout,
        "expires_at": time.time() + lease,
    })
    parent = os.open(root, os.O_RDONLY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return run


def _plan(root: Path, run: str) -> tuple[Path, dict, str]:
    if not ID.fullmatch(run):
        raise ValueError("invalid recovery run identity")
    path = _root(root) / run
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("invalid private run directory")
    plan = _read(path / "plan.json")
    return path, plan, f"{_domain(plan['domain'])}/{PREFIX}{run}"


def _inspect(path: Path, target: str, *, deadline: float | None = None) -> str | None:
    try:
        result = (_launch("print", target) if deadline is None
                  else _launch("print", target, timeout=_time_left(deadline)))
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlError("LAUNCHD_UNAVAILABLE") from exc
    if result.returncode and "Could not find service" in result.stderr:
        return None
    if result.returncode:
        raise ControlError("LAUNCHD_UNAVAILABLE", result.stderr.strip())
    if f"path = {path / 'job.plist'}" not in {line.strip() for line in result.stdout.splitlines()}:
        raise ControlError("JOB_OWNERSHIP_MISMATCH", "launchd label is not bound to this run's plist")
    return result.stdout


@contextlib.contextmanager
def _controller_lock(path: Path, *, deadline: float | None = None):
    with (path / "controller.lock").open("ab") as lock:
        if deadline is None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        else:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(min(POLL_SECONDS, _time_left(deadline)))
        yield


def submit(root: Path, run: str) -> None:
    path, plan, target = _plan(root, run)
    with _controller_lock(path):
        if time.time() >= plan["expires_at"] or any(
            (path / filename).exists() for filename in ("submitted.json", "claimed.json", "stop.json", "cancel.json", "result.json")
        ):
            raise RuntimeError("lease expired or run already consumed")
        if _inspect(path, target) is not None:
            raise RuntimeError("run is already registered with launchd")
        # Write-ahead submission prevents duplicate launch on an ambiguous
        # controller crash between this point and launchd's acknowledgement.
        _write(path / "submitted.json", {"requested_at": time.time()})
        _checked(_launch("bootstrap", plan["domain"], str(path / "job.plist")))


def _job(root: Path, run: str) -> int:
    path, plan, target = _plan(root, run)
    pid = os.getpid()
    with _controller_lock(path):
        state = _inspect(path, target)
        if state is None or f"pid = {pid}" not in {line.strip() for line in state.splitlines()}:
            raise RuntimeError("job was not launched by its registered launchd scope")
        if not (path / "submitted.json").exists():
            raise RuntimeError("job has no durable submission intent")
        if time.time() >= plan["expires_at"] or (path / "stop.json").exists() or (path / "cancel.json").exists():
            raise RuntimeError("lease expired or revoked before Core start")
        _write(path / "claimed.json", {"pid": pid, "pgid": os.getpgrp(), "started_at": time.time()})
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    def stop_requested() -> bool:
        return stopped or (path / "cancel.json").exists() or (path / "stop.json").exists()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if stop_requested():
        return 1
    outcome = supervise(
        plan["command"], log_path=Path(plan["log"]), timeout=plan["timeout"],
        cancelled=stop_requested, managed_job=True, core_start_lock=lambda: _controller_lock(path),
    )
    if not outcome["accepted_exit"]:
        _write(path / "result.json", outcome)
        return 1
    if stop_requested():
        return 1
    with _controller_lock(path):
        if stop_requested():
            return 1
        _write(path / "result.json", outcome)
    return 0


def _active_pid(state: str | None) -> int | None:
    match = JOB_PID.search(state or "")
    return int(match[1]) if match is not None else None


def _supervisor_success(path: Path) -> bool:
    result = _read(path / "result.json") if (path / "result.json").exists() else {}
    return result.get("accepted_exit") is True and result.get("cleanup_complete") is True


def _completion(path: Path, run: str, state: str | None) -> dict | None:
    if (path / "completed.json").exists():
        return _read(path / "completed.json")
    if state is None or _active_pid(state) is not None:
        return None
    if "last exit code = 0" not in {line.strip() for line in state.splitlines()}:
        return None
    if _supervisor_success(path):
        completed = {"run_id": run, "state": "COMPLETED", "accepted_exit": True}
        _write(path / "completed.json", completed)
        return completed
    return None


def _cancel_report(run: str | None, state: str, code: str | None = None, receipt: dict | None = None) -> dict:
    return {
        "schema_version": "1.0", "run_id": run, "state": state,
        "accepted_exit": state == "COMPLETED",
        "cleanup_complete": state in {"COMPLETED", "CANCELLED"},
        "error_code": code, "receipt": receipt,
    }


def _process_rows():
    rows = JsonLineWorker._darwin_process_rows()
    if rows is None or not any(pid == os.getpid() and pgid == os.getpgrp() for pid, _, pgid, _ in rows):
        raise ControlError("PROCESS_OBSERVATION_UNAVAILABLE")
    return rows


def _bootout(path: Path, target: str, deadline: float) -> None:
    timeout = _time_left(deadline)
    try:
        result = _launch("bootout", target, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlError("LAUNCHD_UNAVAILABLE") from exc
    # An external unload can race our verified request. Confirm absence either way.
    while _inspect(path, target, deadline=deadline) is not None:
        if result.returncode:
            raise ControlError("BOOTOUT_FAILED")
        time.sleep(min(POLL_SECONDS, _time_left(deadline)))


def _finish_cancel(path: Path, plan: dict, target: str, run: str, deadline: float) -> dict:
    requested_at = _read(path / "cancel.json")["requested_at"]
    state = _inspect(path, target, deadline=deadline)
    scope_path = path / "cancel-scope.json"
    if state is not None and not scope_path.exists():
        _write(scope_path, {"pgid": _active_pid(state)})
    # An armed managed Supervisor watches the durable request and gives Core
    # its existing TERM grace. A stopped or unresponsive Job is then booted out.
    cooperate_until = time.monotonic() + max(
        0, min(CANCEL_COOPERATIVE_SECONDS, requested_at + CANCEL_COOPERATIVE_SECONDS - time.time()),
    )
    while _active_pid(state) is not None and time.monotonic() < cooperate_until:
        time.sleep(min(POLL_SECONDS, _time_left(deadline)))
        state = _inspect(path, target, deadline=deadline)
    if state is not None:
        _bootout(path, target, deadline)

    scope = _read(scope_path) if scope_path.exists() else {}
    claim = _read(path / "claimed.json") if (path / "claimed.json").exists() else {}
    group = claim.get("pgid", scope.get("pgid"))
    if claim and (type(group) is not int or group < 2 or group != claim.get("pid")):
        raise ControlError("INVALID_CLAIM")
    if group is not None:
        if type(group) is not int or group < 2:
            raise ControlError("INVALID_CLAIM")
        # A durable numeric group is read-only evidence. It is never used
        # as a signal target. Reuse of its number can only delay confirmation.
        while any(pgid == group for _, _, pgid, _ in _process_rows()):
            if time.monotonic() >= deadline:
                return _cancel_report(run, "CANCEL_PENDING", "GROUP_NOT_EMPTY")
            time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
        verification = "GROUP_EMPTY"
    elif scope:
        verification = "REGISTRATION_REVOKED"
    elif not (path / "submitted.json").exists():
        verification = "NEVER_SUBMITTED"
    elif time.time() >= plan["expires_at"]:
        verification = "LEASE_REVOKED"
    else:
        return _cancel_report(run, "CANCEL_PENDING", "SUBMISSION_UNCONFIRMED")

    if _inspect(path, target, deadline=deadline) is not None:
        return _cancel_report(run, "CANCEL_PENDING", "SCOPE_STILL_REGISTERED")
    reply = _cancel_report(run, "CANCELLED", receipt={
        "requested_at": requested_at,
        "confirmed_at": max(requested_at, time.time()),
        "verification": verification,
    })
    _write(path / "cancelled.json", reply)
    return reply


def _resume_cancel(path: Path, plan: dict, target: str, run: str, deadline: float) -> dict:
    try:
        return _finish_cancel(path, plan, target, run, deadline)
    except ControlError as exc:
        return _cancel_report(run, "CANCEL_PENDING", exc.code)
    except _STATE_ERRORS:
        return _cancel_report(run, "CANCEL_PENDING", "STATE_IO_ERROR")


def cancel(root: Path, run: str) -> dict:
    if not ID.fullmatch(run):
        return _cancel_report(None, "CANCEL_ERROR", "INVALID_JOB_ID")
    deadline = time.monotonic() + CANCEL_TIMEOUT_SECONDS
    try:
        root = _root(root)
    except _STATE_ERRORS:
        return _cancel_report(run, "CANCEL_ERROR", "STATE_ROOT_INVALID")
    try:
        path, plan, target = _plan(root, run)
        with _controller_lock(path, deadline=deadline):
            if (path / "cancelled.json").exists():
                return _read(path / "cancelled.json")
            if not (path / "cancel.json").exists():
                if (path / "completed.json").exists():
                    return _cancel_report(run, "COMPLETED")
                try:
                    state = _inspect(path, target, deadline=deadline)
                except ControlError as exc:
                    # Preserve a possibly successful natural exit until launchd
                    # can verify it. Otherwise record revocation even during an outage.
                    if exc.code != "LAUNCHD_UNAVAILABLE" or _supervisor_success(path):
                        raise
                    _write(path / "cancel.json", {"requested_at": time.time()})
                    return _cancel_report(run, "CANCEL_PENDING", exc.code)
                if _supervisor_success(path):
                    # Its success record won the Job lock. Give launchd time
                    # to observe that exit before changing its disposition.
                    while _active_pid(state) is not None:
                        time.sleep(min(POLL_SECONDS, _time_left(deadline)))
                        state = _inspect(path, target, deadline=deadline)
                    if _completion(path, run, state) is not None:
                        return _cancel_report(run, "COMPLETED")
                _write(path / "cancel.json", {"requested_at": time.time()})
            return _resume_cancel(path, plan, target, run, deadline)
    except FileNotFoundError:
        code = "STATE_IO_ERROR" if (root / run).exists() else "JOB_NOT_FOUND"
        return _cancel_report(run, "CANCEL_ERROR", code)
    except ControlError as exc:
        return _cancel_report(run, "CANCEL_ERROR", exc.code)
    except _STATE_ERRORS:
        return _cancel_report(run, "CANCEL_ERROR", "STATE_IO_ERROR")


def reconcile(root: Path, run: str) -> dict:
    """Re-open the durable intent after restart and act only by verified job label."""
    path, plan, target = _plan(root, run)
    with _controller_lock(path):
        if (path / "completed.json").exists():
            return _read(path / "completed.json")
        if (path / "cancelled.json").exists():
            reply = _read(path / "cancelled.json")
            if reply["receipt"]["verification"] == "LEASE_REVOKED":
                # A delayed earlier bootstrap cannot claim, but might still register.
                deadline = time.monotonic() + CANCEL_TIMEOUT_SECONDS
                if _inspect(path, target, deadline=deadline) is not None:
                    _bootout(path, target, deadline)
            return reply
        if (path / "cancel.json").exists():
            return _resume_cancel(path, plan, target, run, time.monotonic() + CANCEL_TIMEOUT_SECONDS)
        state = _inspect(path, target)
        active = _active_pid(state) is not None
        completed = _completion(path, run, state)
        if completed is not None:
            return completed
        expired = time.time() >= plan["expires_at"]
        if active and (expired or (path / "stop.json").exists()):
            if not (path / "stop.json").exists():
                _write(path / "stop.json", {"requested_at": time.time(), "reason": "LEASE_EXPIRED"})
            _checked(_launch("bootout", target))
            return {"run_id": run, "state": "UNLOADED", "accepted_exit": False}
        if active:
            status = "RUNNING"
        elif (path / "claimed.json").exists() or (path / "stop.json").exists():
            status = "FAILED"
        elif state is not None:
            status = "FAILED" if expired or re.search(
                r"^\s*(last exit code = [1-9]\d*|last terminating signal = .+)\s*$",
                state, re.MULTILINE,
            ) else "REGISTERED"
        elif (path / "submitted.json").exists():
            status = "SUBMISSION_UNCONFIRMED"
        else:
            status = "EXPIRED_UNSUBMITTED" if expired else "PREPARED"
        return {"run_id": run, "state": status, "accepted_exit": False}


def _sweep_identity(root: Path, code: dict) -> dict:
    boot = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"], capture_output=True,
        check=True, text=True, timeout=3,
    ).stdout.strip()
    if not boot:
        raise ControlError("BOOT_ID_UNAVAILABLE")
    return {
        "boot_id": boot, "source_sha256": code["source_sha256"], "commit": code["pdffast_commit"],
        "python": sys.executable, "working_directory": str(Path.cwd().resolve()),
        "state_root": str(root), "uid": os.getuid(),
    }


def reconcile_all(root: Path) -> list[dict]:
    root = _root(root)
    heartbeat = root / "reconcile-heartbeat.json"
    with _controller_lock(root):
        sweep = {
            "identity": None, "status": "RUNNING",
            "monotonic_seconds": time.monotonic(), "unix_seconds": time.time(),
        }
        _write(heartbeat, sweep, replace=True)
        sweep["identity"] = _sweep_identity(root, code_identity())
        results = []
        for entry in sorted(root.iterdir()):
            if ID.fullmatch(entry.name) and (entry / "plan.json").is_file():
                try:
                    results.append(reconcile(root, entry.name))
                except _STATE_ERRORS as exc:
                    results.append({
                        "run_id": entry.name, "state": "RECONCILIATION_ERROR",
                        "accepted_exit": False, "error": str(exc),
                    })
        failed = any(_sweep_failed(reply) for reply in results)
        _write(heartbeat, {
            **sweep, "status": "FAILED" if failed else "PASS",
            "monotonic_seconds": time.monotonic(), "unix_seconds": time.time(),
        }, replace=True)
        return results


def _sweep_failed(reply: dict) -> bool:
    return reply["state"] == "RECONCILIATION_ERROR" or (
        reply["state"] == "CANCEL_PENDING" and reply["error_code"] != "SUBMISSION_UNCONFIRMED"
    )


def _controller_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{CONTROLLER_LABEL}.plist"


def _controller_plist(root: Path) -> dict:
    project_root = Path(__file__).resolve().parents[1]
    log_root = root / "controller-logs"
    return {
        "Label": CONTROLLER_LABEL,
        "ProgramArguments": [
            sys.executable, "-B", "-m", "pdffast.deployment_recovery",
            "reconcile-all", str(root),
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "StartInterval": CONTROLLER_INTERVAL_SECONDS,
        "StandardOutPath": str(log_root / "reconcile.stdout.log"),
        "StandardErrorPath": str(log_root / "reconcile.stderr.log"),
        "AbandonProcessGroup": False,
        "ProcessType": "Background",
        "Umask": 0o077,
    }


def install_controller(root: Path, domain: str) -> dict:
    """Install a per-user LaunchAgent that runs reconcile-all every 20 seconds."""
    root = _root(root)
    domain = _domain(domain)
    path = _controller_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / "controller-logs").mkdir(mode=0o700, exist_ok=True)
    expected = _controller_plist(root)
    target = f"{domain}/{CONTROLLER_LABEL}"

    if path.exists():
        try:
            current = plistlib.loads(path.read_bytes())
        except Exception as exc:
            raise ControlError("SWEEP_IDENTITY_MISMATCH", "controller plist is invalid") from exc
        if current.get("Label") != CONTROLLER_LABEL:
            raise ControlError("SWEEP_IDENTITY_MISMATCH", "controller plist label is not owned by PDFFast")
        if current != expected:
            raise ControlError("SWEEP_IDENTITY_MISMATCH", "installed controller plist differs from this deployment")
        loaded = _launch("print", target, timeout=3)
        if loaded.returncode != 0:
            _checked(_launch("bootstrap", domain, str(path)))
    else:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pdffast-controller-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(plistlib.dumps(expected))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        _checked(_launch("bootstrap", domain, str(path)))

    _checked(_launch("kickstart", "-k", target))
    deadline = time.monotonic() + 20
    expected_identity = _sweep_identity(root, code_identity())
    while time.monotonic() < deadline:
        heartbeat = root / "reconcile-heartbeat.json"
        if heartbeat.is_file():
            try:
                record = _read(heartbeat)
                if record.get("status") == "PASS" and record.get("identity") == expected_identity:
                    return {
                        "state": "INSTALLED",
                        "label": CONTROLLER_LABEL,
                        "plist_path": str(path),
                        "start_interval_seconds": CONTROLLER_INTERVAL_SECONDS,
                    }
            except (OSError, ValueError, TypeError):
                pass
        time.sleep(0.05)
    raise ControlError("SWEEP_NOT_SUCCESSFUL", "periodic reconciliation agent did not complete its initial sweep")


def uninstall_controller(root: Path, domain: str) -> dict:
    """Unload and remove the PDFFast periodic reconciliation LaunchAgent."""
    root = _root(root)
    domain = _domain(domain)
    path = _controller_plist_path()
    if not path.exists():
        return {"state": "NOT_INSTALLED", "label": CONTROLLER_LABEL}
    try:
        current = plistlib.loads(path.read_bytes())
    except Exception as exc:
        raise ControlError("SWEEP_IDENTITY_MISMATCH", "controller plist is invalid") from exc
    if current != _controller_plist(root):
        raise ControlError("SWEEP_IDENTITY_MISMATCH", "controller plist belongs to another deployment")
    target = f"{domain}/{CONTROLLER_LABEL}"
    loaded = _launch("print", target, timeout=3)
    if loaded.returncode == 0:
        _checked(_launch("bootout", target))
    path.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"state": "UNINSTALLED", "label": CONTROLLER_LABEL}


def _check_controller_agent(root: Path, domain: str) -> None:
    path = _controller_plist_path()
    if not path.is_file():
        raise ControlError("SWEEP_MISSING", "periodic reconciliation LaunchAgent is not installed")
    try:
        installed = plistlib.loads(path.read_bytes())
    except Exception as exc:
        raise ControlError("SWEEP_INVALID", "periodic reconciliation LaunchAgent plist is invalid") from exc
    if installed != _controller_plist(root):
        raise ControlError("SWEEP_IDENTITY_MISMATCH", "periodic reconciliation LaunchAgent differs from this deployment")
    target = f"{_domain(domain)}/{CONTROLLER_LABEL}"
    state = _launch("print", target, timeout=3)
    if state.returncode != 0:
        raise ControlError("SWEEP_MISSING", "periodic reconciliation LaunchAgent is not loaded")
    if str(path) not in state.stdout:
        raise ControlError("SWEEP_IDENTITY_MISMATCH", "loaded reconciliation LaunchAgent points to another plist")


def _check_controller(root: Path, code: dict, report: dict, domain: str) -> None:
    _check_controller_agent(root, domain)
    report.update(last_sweep_unix_seconds=None, age_seconds=None)
    path = root / "reconcile-heartbeat.json"
    if not path.exists():
        raise ControlError("SWEEP_MISSING")
    sweep = _read(path)
    if sweep["status"] == "RUNNING":
        raise ControlError("SWEEP_NOT_SUCCESSFUL")
    if sweep["identity"] != _sweep_identity(root, code):
        raise ControlError("SWEEP_IDENTITY_MISMATCH")
    age = time.monotonic() - sweep["monotonic_seconds"]
    timestamp = sweep["unix_seconds"]
    if not math.isfinite(age) or age < 0 or not math.isfinite(timestamp):
        raise ControlError("SWEEP_INVALID")
    report.update(last_sweep_unix_seconds=timestamp, age_seconds=age)
    if age > SWEEP_FRESHNESS_SECONDS:
        raise ControlError("SWEEP_STALE")
    if sweep["status"] != "PASS":
        raise ControlError("SWEEP_NOT_SUCCESSFUL")


def _check_root_storage(root: Path) -> None:
    with tempfile.TemporaryDirectory(dir=root, prefix=".health-storage-") as directory:
        path = Path(directory)
        with _controller_lock(path):
            _write(path / "probe.json", {"ready": True})
            if _read(path / "probe.json") != {"ready": True}:
                raise ControlError("STATE_ROOT_IO_ERROR")


def _check_process_observation() -> None:
    _process_rows()
    with contextlib.closing(select.kqueue()) as queue:
        queue.control([
            select.kevent(os.getpid(), filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD,
                          fflags=select.KQ_NOTE_EXIT),
        ], 0, 0)


HEALTH_CORE = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-B", "-c", sys.argv[1], sys.argv[2]])
child.wait()
"""
HEALTH_CHILD = """
import json, os, signal, sys, time
from pathlib import Path
from pdffast.application.production_identity import code_identity
signal.signal(signal.SIGTERM, signal.SIG_IGN)
ready = Path(sys.argv[1])
temporary = ready.with_suffix(".tmp")
temporary.write_text(json.dumps({"pid": os.getpid(), "code_identity": code_identity()}))
temporary.rename(ready)
time.sleep(20)
"""


def _check_recovery(root: Path, domain: str, code: dict) -> None:
    # Register in the actual spool so lease recovery can see this canary if
    # the health caller dies. Only tear down a label verified against its plist.
    with tempfile.TemporaryDirectory(dir=root, prefix=".health-job-") as directory:
        fixture = Path(directory)
        ready = fixture / "ready"
        run = prepare(
            root, domain=domain, log=fixture / "core.log", timeout=12, lease_seconds=16,
            command=[sys.executable, "-B", "-c", HEALTH_CORE, HEALTH_CHILD, str(ready)],
        )
        path, _, target = _plan(root, run)
        try:
            submit(root, run)
            deadline = time.monotonic() + 5
            while not ready.exists():
                time.sleep(min(POLL_SECONDS, _time_left(deadline)))
            group = _read(path / "claimed.json")["pgid"]
            evidence = _read(ready)
            if evidence["code_identity"] != code:
                raise ControlError("CANARY_CODE_IDENTITY_MISMATCH")
            if not any(pid == evidence["pid"] and pgid == group for pid, _, pgid, _ in _process_rows()):
                raise ControlError("CANARY_SCOPE_INVALID")
            if _active_pid(_inspect(path, target, deadline=deadline)) != group:
                raise ControlError("CANARY_SCOPE_INVALID")
            _checked(_launch("kill", "SIGKILL", target, timeout=_time_left(deadline)))
            while any(pgid == group for _, _, pgid, _ in _process_rows()):
                time.sleep(min(POLL_SECONDS, _time_left(deadline)))
        finally:
            cleanup = cancel(root, run)
            if cleanup["state"] != "CANCELLED":
                raise ControlError("CANARY_CLEANUP_UNVERIFIED")
            with _controller_lock(root, deadline=time.monotonic() + CANCEL_TIMEOUT_SECONDS):
                shutil.rmtree(path)


def _health_check(checks: dict, name: str, operation, error: str) -> bool:
    try:
        operation()
    except ControlError as exc:
        checks[name] = {"status": "BLOCKED", "code": exc.code}
        return False
    except _STATE_ERRORS:
        checks[name] = {"status": "BLOCKED", "code": error}
        return False
    checks[name] = {"status": "PASS", "code": None}
    return True


def health(root: Path, domain: str) -> dict:
    checks = {
        name: {"status": "NOT_CHECKED", "code": None}
        for name in ("state_root", "launchd", "process_observation", "controller", "recovery_probe", "code_identity")
    }
    controller = {"last_sweep_unix_seconds": None, "age_seconds": None, "freshness_seconds": SWEEP_FRESHNESS_SECONDS}
    report = {
        "schema_version": "1.0", "state": "BLOCKED",
        "environment": {
            "platform": sys.platform, "platform_release": platform.release(), "machine": platform.machine(),
            "python": platform.python_version(), "python_executable": sys.executable, "uid": os.getuid(),
            "domain": domain, "state_root": str(root.absolute()),
        },
        "code_identity": None, "checks": checks, "controller": controller,
    }

    def read_identity() -> None:
        report["code_identity"] = code_identity()

    def check_launchd() -> None:
        _checked(_launch("print", _domain(domain), timeout=3))

    _health_check(checks, "code_identity", read_identity, "CODE_IDENTITY_UNAVAILABLE")
    if sys.platform != "darwin":
        checks["launchd"] = {"status": "BLOCKED", "code": "UNSUPPORTED_PLATFORM"}
        return report
    _health_check(checks, "launchd", check_launchd, "LAUNCHD_UNAVAILABLE")
    _health_check(checks, "state_root", lambda: _check_root_storage(_root(root)), "STATE_ROOT_INVALID")
    _health_check(checks, "process_observation", _check_process_observation, "PROCESS_OBSERVATION_UNAVAILABLE")
    if all(checks[name]["status"] == "PASS" for name in ("state_root", "code_identity")):
        _health_check(checks, "controller", lambda: _check_controller(
            _root(root), report["code_identity"], controller, domain,
        ), "SWEEP_INVALID")
    if all(item["status"] == "PASS" for name, item in checks.items() if name != "recovery_probe"):
        recovered = _health_check(checks, "recovery_probe", lambda: _check_recovery(
            _root(root), domain, report["code_identity"],
        ), "CANARY_FAILED")
        if recovered:
            # The sweep's freshness must still hold after the live Job probe.
            _health_check(checks, "controller", lambda: _check_controller(
                _root(root), report["code_identity"], controller, domain,
            ), "SWEEP_INVALID")
    if all(item["status"] == "PASS" for item in checks.values()):
        report["state"] = "PASS"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    plan = commands.add_parser("prepare")
    plan.add_argument("--state-root", required=True, type=Path)
    plan.add_argument("--domain", required=True)
    plan.add_argument("--log", required=True, type=Path)
    plan.add_argument("--timeout", required=True, type=float)
    plan.add_argument("command", nargs=argparse.REMAINDER)
    for action in ("submit", "reconcile", "job", "cancel"):
        cli = commands.add_parser(action)
        cli.add_argument("root", type=Path)
        cli.add_argument("run")
    commands.add_parser("reconcile-all").add_argument("root", type=Path)
    check = commands.add_parser("health")
    check.add_argument("--state-root", required=True, type=Path)
    check.add_argument("--domain", required=True)
    check.add_argument("--json", action="store_true", help="Emit JSON (also the default)")
    for action in ("install-controller", "uninstall-controller"):
        controller = commands.add_parser(action)
        controller.add_argument("--state-root", required=True, type=Path)
        controller.add_argument("--domain", required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        print(prepare(args.state_root, domain=args.domain, log=args.log, timeout=args.timeout, command=command))
    elif args.action == "reconcile-all":
        results = reconcile_all(args.root)
        print(json.dumps(results), flush=True)
        return int(any(_sweep_failed(reply) for reply in results))
    elif args.action == "health":
        report = health(args.state_root, args.domain)
        print(json.dumps(report, allow_nan=False), flush=True)
        return int(report["state"] != "PASS")
    elif args.action == "install-controller":
        report = install_controller(args.state_root, args.domain)
        print(json.dumps(report, allow_nan=False), flush=True)
    elif args.action == "uninstall-controller":
        report = uninstall_controller(args.state_root, args.domain)
        print(json.dumps(report, allow_nan=False), flush=True)
    elif args.action == "cancel":
        report = cancel(args.root, args.run)
        print(json.dumps(report, allow_nan=False), flush=True)
        if report["state"] in {"CANCELLED", "COMPLETED"}:
            return 0
        if report["state"] == "CANCEL_PENDING":
            return 3
        return 2 if report["error_code"] in {"INVALID_JOB_ID", "JOB_NOT_FOUND"} else 1
    elif args.action == "job":
        return _job(args.root, args.run)
    elif args.action == "submit":
        submit(args.root, args.run)
    else:
        print(json.dumps(reconcile(args.root, args.run)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
