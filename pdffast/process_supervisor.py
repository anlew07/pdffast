"""Run a trusted PDFFast Core in a dedicated macOS process group."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import select
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from pdffast.providers.workers import (
    MANAGED_JOB_PGID,
    SUPERVISED_CORE_PID,
    JsonLineWorker,
)

BOOTSTRAP = """
import os, sys
fd = int(sys.argv[1])
ready = os.read(fd, 1)
os.close(fd)
if ready != b"1":
    sys.exit(125)
os.environ[sys.argv[2]] = str(os.getpid())
os.environ.pop(sys.argv[3], None)
if sys.argv[4]:
    os.environ[sys.argv[3]] = sys.argv[4]
os.execvpe(sys.argv[5], sys.argv[5:], os.environ)
"""
JOB_GUARD = """
import os, signal, sys
fd, group = map(int, sys.argv[1:])
if os.getpgrp() != group:
    sys.exit(125)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
os.write(1, b"1")
os.close(1)
if os.read(fd, 1) != b"D":
    os.killpg(os.getpgrp(), signal.SIGKILL)
"""
POLL_INTERVAL = 0.025
CORE_TERM_GRACE = 2.5
GROUP_TERM_GRACE = 0.25
GROUP_KILL_GRACE = 1.0


def _members(group: int) -> list[int]:
    rows = JsonLineWorker._darwin_process_rows()
    if rows is None:
        raise RuntimeError("cannot verify the run process group with libproc")
    return sorted(pid for pid, _, pgid, _ in rows if pgid == group and pid != group)


def _send(target: int, sig: signal.Signals, *, group: bool = False) -> None:
    try:
        (os.killpg if group else os.kill)(target, sig)
    except ProcessLookupError:
        pass


@contextlib.contextmanager
def _job_guard(group: int | None):
    if group is None:
        yield None, None
        return
    reader, writer = os.pipe()
    try:
        guard = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", JOB_GUARD, str(reader), str(group)],
            pass_fds=(reader,), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        )
    except BaseException:
        os.close(writer)
        raise
    finally:
        os.close(reader)
    try:
        with guard.stdout as ready:
            if not select.select([ready], [], [], 2)[0] or ready.read(1) != b"1":
                raise RuntimeError("job recovery guard failed to arm")
        yield guard, writer
    finally:
        os.close(writer)


def supervise(
    command: Sequence[str], *, log_path: Path, timeout: float,
    owner_fd: int | None = None, cancelled: Callable[[], bool] = lambda: False,
    managed_job: bool = False,
    core_start_lock: Callable[[], contextlib.AbstractContextManager] = contextlib.nullcontext,
) -> dict:
    """Return the raw Core status and verified cleanup state before acceptance."""
    if sys.platform != "darwin":
        raise RuntimeError("process supervision is verified and supported on Darwin only")
    if not command or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("a Core command and finite positive timeout are required")
    if owner_fd is not None and not stat.S_ISFIFO(os.fstat(owner_fd).st_mode):
        raise ValueError("owner_fd must be a dedicated lifetime pipe")

    job_group = os.getpid() if managed_job else None
    if job_group is not None and os.getpgrp() != job_group:
        raise RuntimeError("managed Supervisor must lead its dedicated job process group")

    started = time.monotonic()
    with (
        log_path.open("xb", buffering=0) as log,
        contextlib.closing(select.kqueue()) as queue,
        _job_guard(job_group) as (guard, lease),
    ):
        read_gate, write_gate = os.pipe()
        core = None
        try:
            core = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", BOOTSTRAP, str(read_gate),
                 SUPERVISED_CORE_PID, MANAGED_JOB_PGID, str(job_group or ""), *command],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=not managed_job, pass_fds=(read_gate,),
            )
            if os.getpgid(core.pid) != (job_group or core.pid) or (
                not managed_job and os.getsid(core.pid) != core.pid
            ):
                raise RuntimeError("Core is outside its dedicated run scope")
            queue.control([
                select.kevent(
                    core.pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD,
                    fflags=select.KQ_NOTE_EXIT,
                ),
            ], 0, 0)
            with core_start_lock():
                os.write(write_gate, b"0" if managed_job and cancelled() else b"1")
        except BaseException:
            # Before the gate opens the bootstrap cannot spawn Providers.
            if core is not None:
                core.kill()
                core.wait(timeout=GROUP_KILL_GRACE)
            raise
        finally:
            os.close(read_gate)
            os.close(write_gate)

        try:
            def stop_requested() -> bool:
                return cancelled() or (guard is not None and guard.poll() is not None)

            report = _monitor(
                core, queue, timeout, started, owner_fd, stop_requested,
                job_group, guard.pid if guard else None,
            )
            if guard is not None and report["cleanup_complete"]:
                os.write(lease, b"D")
                if guard.wait(timeout=GROUP_KILL_GRACE) != 0:
                    raise RuntimeError("job recovery guard failed before disarm")
            return report
        except BaseException:
            if job_group is None and core.returncode is None:
                _send(core.pid, signal.SIGKILL, group=True)
                core.wait(timeout=GROUP_KILL_GRACE)
            raise


def _monitor(core, queue, timeout, started, owner_fd, cancelled, job_group=None, guard_pid=None) -> dict:
    exited = False
    reason = "CORE_EXITED"
    until = started + timeout
    while True:
        if cancelled():
            reason = "CANCELLED"
            break
        if owner_fd is not None and select.select([owner_fd], [], [], 0)[0]:
            # The pipe is a lifetime token. Either EOF or data closes the run.
            reason = "OWNER_GONE"
            break
        left = until - time.monotonic()
        if left <= 0:
            reason = "TIMEOUT"
            break
        if queue.control(None, 1, min(left, POLL_INTERVAL)):
            exited = True
            break

    cleanup_started = time.monotonic()
    if not exited:
        _send(core.pid, signal.SIGTERM)
        exited = bool(queue.control(None, 1, CORE_TERM_GRACE))

    # launchd owns the job group, including this Supervisor. Its exit hands
    # remaining members back to launchd rather than signalling our own group.
    remaining = [pid for pid in _members(job_group or core.pid) if pid not in (core.pid, guard_pid)]
    residual_on_core_exit = reason == "CORE_EXITED" and bool(remaining)
    if job_group is None and (remaining or not exited):
        _send(core.pid, signal.SIGTERM, group=True)
        deadline = time.monotonic() + GROUP_TERM_GRACE
        exited, remaining = _wait_group(core.pid, queue, exited, deadline)
        if remaining or not exited:
            _send(core.pid, signal.SIGKILL, group=True)
            deadline = time.monotonic() + GROUP_KILL_GRACE
            exited, remaining = _wait_group(core.pid, queue, exited, deadline)

    # Do not poll or reap the Core until the last possible group signal is sent.
    # Its unreaped PID prevents this PGID from being recycled for an unrelated task.
    code = core.wait(timeout=0) if exited else None
    clean = exited and not remaining
    return {
        "reason": reason,
        "core_pid": core.pid,
        "core_returncode": code,
        "cleanup_complete": clean,
        "remaining_pids": remaining,
        "residual_on_core_exit": residual_on_core_exit,
        "cleanup_seconds": round(time.monotonic() - cleanup_started, 4),
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "accepted_exit": reason == "CORE_EXITED" and code == 0 and clean and not residual_on_core_exit,
    }


def _wait_group(group, queue, exited, deadline):
    while True:
        remaining = _members(group)
        if exited and not remaining:
            return exited, remaining
        left = deadline - time.monotonic()
        if left <= 0:
            return exited, remaining
        if exited:
            time.sleep(min(left, POLL_INTERVAL))
        else:
            exited = bool(queue.control(None, 1, min(left, POLL_INTERVAL)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--owner-fd", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        report = supervise(
            command, log_path=args.log, timeout=args.timeout,
            owner_fd=args.owner_fd, cancelled=lambda: stopped,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report = {
            "reason": "SUPERVISION_ERROR", "core_returncode": None,
            "cleanup_complete": False, "accepted_exit": False, "error": str(exc),
        }
    print(json.dumps(report, allow_nan=False), flush=True)
    return 0 if report["accepted_exit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
