"""Inject isolated PDFFast supervision faults on macOS using real subprocesses."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

from pdffast.providers.workers import JsonLineWorker, WorkerShutdownError
from pdffast.runtime import ParseCancelledError, cancellable_parse

SCENARIOS = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J_OWNER", "J")
WORKER = r"""
from __future__ import annotations
import json, os, signal, subprocess, sys, time
from pathlib import Path

root = Path(__ROOT__)
mode = __MODE__
# Deliberately request a detached subprocess. Under supervision the approved
# Python Worker launcher keeps it inside the run session.
child = subprocess.Popen([sys.executable, "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(25)"],
    start_new_session=True)
def topology(pid):
    return dict(pid=pid, pgid=os.getpgid(pid), sid=os.getsid(pid))
tmp = root.with_suffix(".tmp")
tmp.write_text(json.dumps({"worker": topology(os.getpid()), "grandchild": topology(child.pid)}))
tmp.replace(root)
if mode == "init":
    time.sleep(25)
print(json.dumps({"status": "READY"}), flush=True)
for line in sys.stdin:
    if json.loads(line)["op"] == "close":
        child.kill()
        child.wait()
        print(json.dumps({"status": "BYE"}), flush=True)
        break
    if mode == "exit":
        while not (root.parent / "release").exists():
            time.sleep(.02)
        sys.exit(7)
    (root.parent / "inference").touch()
    while not (root.parent / "release").exists():
        time.sleep(.02)
    print(json.dumps({"status": "SUCCESS"}), flush=True)
"""


def _core(root: Path, scenario: str) -> int:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    cancelled = Event()
    if scenario == "F":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, lambda *_: cancelled.set())

    def worker(index: int, mode: str) -> JsonLineWorker:
        code = WORKER.replace("__ROOT__", repr(str(root / f"worker-{index}.json"))).replace(
            "__MODE__", repr(mode),
        )
        return JsonLineWorker(
            python_executable=Path(sys.executable), worker_code=code,
            dependency_probe_code="", locked_runtime=True,
        )

    try:
        with cancellable_parse(cancelled):
            if scenario == "I":
                first = worker(1, "normal")
                first.start()
                while not (root / "close-first").exists():
                    time.sleep(.02)
                first.close()
            instance = worker(2 if scenario == "I" else 1, {"C": "init", "H": "exit"}.get(scenario, "normal"))
            try:
                instance.start()
                if scenario == "E":
                    (root / "document.md").write_text("Output written before abort\n")
                    (root / "manifest.json").write_text('{"status":"COMPLETED"}')
                instance.request({"op": "parse"}, timeout_seconds=15)
            finally:
                instance.close()
    except ParseCancelledError:
        return 17
    except WorkerShutdownError as error:
        print(json.dumps({"worker_returncode": error.returncode}), flush=True)
        return 27
    return 0


def _wait(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.02)
    raise TimeoutError("fault fixture did not reach its expected state")


class Run:
    def __init__(self, root: Path, scenario: str):
        root.mkdir()
        self.root = root
        self.owned = {}
        self.topology = {}
        self.owner = None
        descriptors = ()
        owner_option = []
        if scenario == "J_OWNER":
            reader, writer = os.pipe()
            try:
                self.owner = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(20)"],
                    pass_fds=(writer,), stdout=subprocess.DEVNULL,
                )
                descriptors = (reader,)
                owner_option = ["--owner-fd", str(reader)]
            finally:
                os.close(writer)
        try:
            self.process = subprocess.Popen([
                sys.executable, "-B", "-m", "pdffast.process_supervisor",
                "--timeout", "1.3" if scenario == "F" else "12", "--log", str(root / "core.log"),
                *owner_option, "--", sys.executable, "-B", "-m", "scripts.verify_process_supervision",
                "--core", scenario, str(root),
            ], stdout=subprocess.PIPE, text=True, pass_fds=descriptors, start_new_session=True)
        finally:
            for descriptor in descriptors:
                os.close(descriptor)

    def capture(self, index=1):
        file = self.root / f"worker-{index}.json"
        _wait(file.is_file)
        data = json.loads(file.read_bytes())
        group = data["worker"]["pgid"]
        assert group != self.process.pid
        rows = JsonLineWorker._darwin_process_rows()
        assert rows is not None
        ids = {pid: (ppid, pgid, identity) for pid, ppid, pgid, identity in rows}
        assert ids[group][0] == self.process.pid
        assert ids[data["worker"]["pid"]][0] == group
        assert ids[data["grandchild"]["pid"]][0] == data["worker"]["pid"]
        core = {"pid": group, "pgid": os.getpgid(group), "sid": os.getsid(group)}
        for name, entry in {"core": core, **data}.items():
            assert entry["pgid"] == entry["sid"] == group
            pid = entry["pid"]
            self.owned[pid] = ids[pid][2]
            self.topology[name if name == "core" else f"{name}-{index}"] = {
                **entry, "ppid": ids[pid][0], "start": ids[pid][2].started_at,
            }
        self.core_pid = group

    def alive(self, pid):
        return JsonLineWorker._current_identity(pid) == self.owned[pid]

    def fault(self, sig):
        assert self.alive(self.core_pid)
        os.kill(self.core_pid, sig)

    def result(self):
        out, _ = self.process.communicate(timeout=7)
        report = json.loads(out)
        assert bool(self.process.returncode == 0) == report["accepted_exit"]
        assert report["cleanup_complete"] and report["remaining_pids"] == []
        assert not any(self.alive(pid) for pid in self.owned)
        assert report["cleanup_seconds"] < 5
        return {**report, "topology": self.topology}

    def close(self):
        if self.owner is not None and self.owner.poll() is None:
            self.owner.kill()
            self.owner.wait(timeout=2)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate(timeout=2)
        # Harness-only rescue for intentionally killing the Supervisor.
        # Verify the creation identity before signalling any recorded PID.
        for pid in self.owned:
            if self.alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for pid in self.owned:
            _wait(lambda pid=pid: not self.alive(pid), timeout=3)
        if self.process.stdout is not None:
            self.process.stdout.close()


def scenario(root: Path, name: str) -> dict:
    run = Run(root / name, name)
    try:
        if name == "H":
            # Hold the fault until the controller has recorded the live identities.
            # H uses a separate acknowledgement condition in the Worker.
            run.capture()
            (run.root / "release").touch()
        else:
            run.capture()
        if name == "G":
            other = Run(root / "G-peer", "A")
            try:
                other.capture()
                assert run.core_pid != other.core_pid
                run.fault(signal.SIGKILL)
                result = run.result()
                assert result["core_returncode"] == -signal.SIGKILL
                assert all(other.alive(pid) for pid in other.owned)
                (other.root / "release").touch()
                peer = other.result()
                assert peer["accepted_exit"]
                return {**result, "peer": peer}
            finally:
                other.close()

        if name == "A":
            (run.root / "release").touch()
        elif name == "B":
            _wait((run.root / "inference").is_file)
            run.process.terminate()
        elif name == "C":
            assert not (run.root / "inference").exists()
            run.fault(signal.SIGABRT)
        elif name == "D":
            _wait((run.root / "inference").is_file)
            run.fault(signal.SIGKILL)
        elif name == "E":
            _wait((run.root / "manifest.json").is_file)
            run.fault(signal.SIGABRT)
        elif name == "I":
            (run.root / "close-first").touch()
            run.capture(2)
            assert not run.alive(run.topology["worker-1"]["pid"])
            assert run.alive(run.topology["worker-2"]["pid"])
            run.fault(signal.SIGKILL)
        elif name == "J_OWNER":
            run.owner.kill()
            run.owner.wait(timeout=2)
        elif name == "J":
            run.process.kill()
            assert run.process.wait(timeout=2) == -signal.SIGKILL
            assert run.alive(run.topology["worker-1"]["pid"])
            return {"status": "NOT_PROTECTED", "supervisor_returncode": -9,
                    "cleanup_by_harness_only": True, "topology": run.topology}

        result = run.result()
        expected_reasons = {"B": "CANCELLED", "F": "TIMEOUT", "J_OWNER": "OWNER_GONE"}
        expected_codes = {"A": 0, "B": 17, "C": -6, "D": -9, "E": -6, "F": -9, "H": 27, "I": -9, "J_OWNER": 17}
        assert result["reason"] == expected_reasons.get(name, "CORE_EXITED"), result
        assert result["core_returncode"] == expected_codes[name], result
        assert result["accepted_exit"] == (name == "A")
        if name == "H":
            assert '"worker_returncode": 7' in (run.root / "core.log").read_text()
        if name == "E":
            assert (run.root / "document.md").is_file() and (run.root / "manifest.json").is_file()
        return result
    finally:
        run.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", choices=SCENARIOS, help=argparse.SUPPRESS)
    parser.add_argument("--case", action="append", choices=SCENARIOS)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.core:
        return _core(args.root, args.core)
    if sys.platform != "darwin":
        parser.error("fault injection requires the macOS implementation")
    args.root.mkdir(exist_ok=False)
    for name in args.case or SCENARIOS:
        result = scenario(args.root, name)
        print(json.dumps({"case": name, **result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
