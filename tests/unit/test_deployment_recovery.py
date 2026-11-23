"""Opt-in fault injection for temporary per-user launchd jobs."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from pdffast import deployment_recovery as recovery
from pdffast.providers.workers import JsonLineWorker

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or os.getenv("PDFFAST_TEST_LAUNCHD") != "1",
    reason="requires explicit permission for ephemeral current-user launchd jobs",
)


def wait_for(predicate, timeout=8):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        result = predicate()
        if result:
            return result
        time.sleep(.025)
    raise AssertionError("condition was not observed before deadline")


class Job:
    def __init__(self, root, name, mode="A", lease=25):
        self.fixture = root / name
        self.fixture.mkdir(mode=0o700)
        self.run = recovery.prepare(
            root, domain=f"gui/{os.getuid()}", log=self.fixture / "core.log",
            timeout=18, lease_seconds=lease,
            command=[sys.executable, "-B", "-m", "scripts.verify_process_supervision",
                     "--core", mode, str(self.fixture)],
        )
        self.root = root
        self.path, _, self.target = recovery._plan(root, self.run)
        self.identities = {}

    def submit(self):
        recovery.submit(self.root, self.run)

    def observe(self, marker=None):
        path = self.fixture / "worker-1.json"
        wait_for(path.exists)
        if marker is not None:
            wait_for((self.fixture / marker).exists)
        topology = json.loads(path.read_bytes())
        group = json.loads((self.path / "claimed.json").read_bytes())["pid"]
        rows = JsonLineWorker._darwin_process_rows()
        assert rows is not None
        processes = {pid: (ppid, pgid, ident) for pid, ppid, pgid, ident in rows}
        assert topology["worker"]["pgid"] == topology["grandchild"]["pgid"] == group
        self.pgid = group
        for pid, (_, pgid, ident) in processes.items():
            if pgid == group:
                self.identities[pid] = ident
        assert len(self.identities) >= 4  # Supervisor, Core, Worker, model child
        return topology

    def fail(self, sig):
        state = recovery._inspect(self.path, self.target)
        assert state is not None and f"pid = {self.pgid}" in {x.strip() for x in state.splitlines()}
        recovery._checked(recovery._launch("kill", sig, self.target))

    def recovered(self):
        return all(JsonLineWorker._current_identity(pid) != ident for pid, ident in self.identities.items())

    def state(self):
        # New controller process reopens the durable registration each time.
        run = subprocess.run([
            sys.executable, "-B", "-m", "pdffast.deployment_recovery", "reconcile",
            str(self.root), self.run,
        ], check=True, capture_output=True, text=True, timeout=18)
        return json.loads(run.stdout)

    def close(self):
        if recovery._inspect(self.path, self.target) is not None:
            recovery._checked(recovery._launch("bootout", self.target))
        wait_for(self.recovered)


@pytest.fixture
def spool(tmp_path):
    path = tmp_path / "spool"
    path.mkdir(mode=0o700)
    jobs = []

    def make(name, mode="A", lease=25):
        job = Job(path, name, mode, lease)
        jobs.append(job)
        return job

    yield make
    for job in jobs:
        job.close()


@pytest.mark.parametrize(("mode", "marker", "sig"), [
    ("D", "inference", "SIGKILL"),
    ("C", None, "SIGKILL"),
    ("E", "manifest.json", "SIGABRT"),
])
def test_launchd_recovers_supervisor_failures(spool, mode, marker, sig):
    job = spool(mode, mode)
    job.submit()
    topology = job.observe(marker)
    if mode == "C":
        assert not (job.fixture / "inference").exists()
    start = time.monotonic()
    job.fail(sig)
    wait_for(job.recovered)
    print(json.dumps({"mode": mode, "signal": sig, "elapsed": round(time.monotonic()-start, 4),
                      "pgid": job.pgid, "topology": topology}))
    assert job.state()["accepted_exit"] is False


def test_launchd_concurrent_completion_and_single_use(spool):
    victim, peer = spool("victim"), spool("peer")
    for job in (victim, peer):
        job.submit()
        job.observe("inference")
    assert victim.pgid != peer.pgid
    victim.fail("SIGKILL")
    wait_for(victim.recovered)
    assert all(JsonLineWorker._current_identity(pid) == ident for pid, ident in peer.identities.items())
    (peer.fixture / "release").touch()
    wait_for(peer.recovered)
    observed = peer.state()
    if observed["state"] != "COMPLETED":
        details = recovery._inspect(peer.path, peer.target) or ""
        print([line.strip() for line in details.splitlines() if any(
            key in line for key in ("exit", "state =", "runs =", "pid =")
        )])
    assert observed["state"] == "COMPLETED"
    assert peer.state()["state"] == "COMPLETED"
    with pytest.raises(RuntimeError, match="already consumed"):
        peer.submit()


def test_restarted_controller_retires_expired_job(spool):
    job = spool("restart", lease=3)
    # A separate submitter exits once launchd has accepted the job. There is
    # no parent-local state to inherit when reconcile starts another process.
    launcher = subprocess.Popen([sys.executable, "-B", "-m", "pdffast.deployment_recovery",
                                 "submit", str(job.root), job.run])
    assert launcher.wait(timeout=10) == 0
    job.observe("inference")
    job.fail("SIGSTOP")
    expires = json.loads((job.path / "plan.json").read_bytes())["expires_at"]
    wait_for(lambda: time.time() >= expires)
    paused = job.fixture / "reconcile-paused"
    code = """
import sys, time
from pathlib import Path
from pdffast import deployment_recovery as r
original = r._launch
def intercepted(*args):
    if args[0] == "bootout":
        Path(sys.argv[3]).touch()
        time.sleep(15)
    return original(*args)
r._launch = intercepted
r.reconcile(Path(sys.argv[1]), sys.argv[2])
"""
    interrupted = subprocess.Popen(
        [sys.executable, "-B", "-c", code, str(job.root), job.run, str(paused)],
    )
    try:
        wait_for(paused.exists)
        assert (job.path / "stop.json").is_file()
        assert not job.recovered()
    finally:
        interrupted.kill()
        assert interrupted.wait(timeout=3) == -signal.SIGKILL
    started = time.monotonic()
    resumed = subprocess.run([
        sys.executable, "-B", "-m", "pdffast.deployment_recovery", "reconcile-all", str(job.root),
    ], check=True, capture_output=True, text=True, timeout=18)
    assert {"run_id": job.run, "state": "UNLOADED", "accepted_exit": False} in json.loads(resumed.stdout)
    wait_for(job.recovered)
    print(json.dumps({"mode": "reconcile_after_SIGKILL", "elapsed_after_restart": round(time.monotonic()-started, 4)}))


def test_durable_plan_and_stale_pid_are_not_process_authority(spool, monkeypatch):
    job = spool("prepared")
    assert job.state()["state"] == "PREPARED"
    assert not (job.path / "claimed.json").exists()
    # Simulate an interrupted registrar with a reused/stale claim: no manager
    # record exists. Numeric values in that file never become signal targets.
    recovery._write(job.path / "claimed.json", {"pid": os.getpid(), "pgid": os.getpgrp()})
    assert job.state()["state"] == "FAILED"
    with pytest.raises(RuntimeError, match="already consumed"):
        job.submit()
    original = recovery._launch

    def foreign(*args):
        if args[0] == "print":
            return subprocess.CompletedProcess(args, 0, "path = /foreign/job.plist\n", "")
        pytest.fail("a mismatched job label must never be targeted")

    with monkeypatch.context() as context:
        context.setattr(recovery, "_launch", foreign)
        with pytest.raises(RuntimeError, match="not bound"):
            recovery.reconcile(job.root, job.run)
    assert recovery._launch is original



def test_claim_write_failure_cannot_open_core_gate(spool, monkeypatch):
    job = spool("claim-failure")
    recovery._write(job.path / "submitted.json", {"requested_at": time.time()})
    monkeypatch.setattr(recovery, "_inspect", lambda *_: f"pid = {os.getpid()}")
    monkeypatch.setattr(recovery, "_write", lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
    monkeypatch.setattr(recovery, "supervise", lambda *_a, **_kw: pytest.fail("unregistered Core started"))
    with monkeypatch.context() as context:
        context.setattr(recovery.signal, "signal", lambda *_: None)
        with pytest.raises(OSError, match="disk failure"):
            recovery._job(job.root, job.run)
    monkeypatch.undo()
    assert not (job.path / "claimed.json").exists()
    assert not (job.fixture / "core.log").exists()


def test_actual_out_of_group_process_needs_stronger_containment(tmp_path):
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    ready = tmp_path / "detached.pid"
    code = """
import os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"], start_new_session=True)
Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(15)
"""
    run = recovery.prepare(
        root, domain=f"gui/{os.getuid()}", log=tmp_path / "escaped.log",
        timeout=16, command=[sys.executable, "-B", "-c", code, str(ready)],
    )
    path, _, target = recovery._plan(root, run)
    pid = None
    identity = None
    try:
        recovery.submit(root, run)
        wait_for(lambda: ready.exists() and ready.stat().st_size)
        pid = int(ready.read_text())
        identity = JsonLineWorker._current_identity(pid)
        assert identity and os.getsid(pid) == os.getpgid(pid) == pid
        job = json.loads((path / "claimed.json").read_bytes())
        assert pid != job["pgid"]
        assert recovery._inspect(path, target) is not None
        recovery._checked(recovery._launch("kill", "SIGKILL", target))
        wait_for(lambda: JsonLineWorker._current_identity(job["pid"]) is None)
        assert JsonLineWorker._current_identity(pid) == identity
        print(json.dumps({"mode": "escaped_session", "status": "RESIDUAL_OBSERVED"}))
    finally:
        if recovery._inspect(path, target) is not None:
            recovery._checked(recovery._launch("bootout", target))
        if identity is not None and JsonLineWorker._current_identity(pid) == identity:
            os.kill(pid, signal.SIGKILL)
            wait_for(lambda: JsonLineWorker._current_identity(pid) != identity)



def test_interrupted_submission_is_not_replayed(spool, monkeypatch):
    job = spool("submission-unknown")
    real = recovery._launch

    def interrupted(*args):
        if args[0] == "bootstrap":
            assert (job.path / "submitted.json").exists()
            raise TimeoutError("ambiguous launchd acknowledgement")
        return real(*args)

    with monkeypatch.context() as context:
        context.setattr(recovery, "_launch", interrupted)
        with pytest.raises(TimeoutError):
            job.submit()
    assert job.state()["state"] == "SUBMISSION_UNCONFIRMED"
    with pytest.raises(RuntimeError, match="already consumed"):
        job.submit()
    assert not (job.path / "claimed.json").exists()



def test_kill_after_claim_before_any_worker(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    ready = tmp_path / "before-worker"
    code = "from pathlib import Path; import sys,time; Path(sys.argv[1]).touch(); time.sleep(15)"
    run = recovery.prepare(
        root, domain=f"gui/{os.getuid()}", log=tmp_path / "core.log",
        timeout=16, command=[sys.executable, "-B", "-c", code, str(ready)],
    )
    path, _, target = recovery._plan(root, run)
    try:
        recovery.submit(root, run)
        wait_for(ready.is_file)
        assert all((path / f).is_file() for f in ("plan.json", "submitted.json", "claimed.json"))
        job = json.loads((path / "claimed.json").read_bytes())
        rows = JsonLineWorker._darwin_process_rows()
        assert rows is not None
        owned = {pid: identity for pid, _, pgid, identity in rows if pgid == job["pgid"]}
        assert len(owned) == 3  # Job Supervisor, guard, and Core only
        assert recovery._inspect(path, target) is not None
        recovery._checked(recovery._launch("kill", "SIGKILL", target))
        wait_for(lambda: all(JsonLineWorker._current_identity(pid) != i for pid, i in owned.items()))
        assert recovery.reconcile(root, run)["accepted_exit"] is False
    finally:
        if recovery._inspect(path, target) is not None:
            recovery._checked(recovery._launch("bootout", target))


@pytest.mark.parametrize("managed", [True, False], ids=["launchd", "standalone"])
def test_supervised_worker_group_does_not_depend_on_locked_runtime(tmp_path, managed):
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    report = tmp_path / "topology.json"
    code = """
import json, os, sys
from pathlib import Path
from pdffast.providers.workers import JsonLineWorker

worker = JsonLineWorker(
    python_executable=Path(sys.executable),
    worker_code="import sys; print('{\\\"status\\\":\\\"READY\\\"}'); sys.stdin.readline()",
    dependency_probe_code="",
)
worker.start()
try:
    pid = worker._process.pid
    Path(sys.argv[1]).write_text(json.dumps({
        "core_pgid": os.getpgrp(), "core_sid": os.getsid(0),
        "worker_pgid": os.getpgid(pid), "worker_sid": os.getsid(pid),
    }))
finally:
    worker.close()
"""
    log = tmp_path / "core.log"
    command = [sys.executable, "-B", "-c", code, str(report)]
    if managed:
        run = recovery.prepare(
            root, domain=f"gui/{os.getuid()}", log=log, timeout=15, command=command,
        )
        scope, _, target = recovery._plan(root, run)
        try:
            recovery.submit(root, run)
            wait_for(lambda: recovery.reconcile(root, run)["state"] in {"COMPLETED", "FAILED"})
            assert recovery.reconcile(root, run)["state"] == "COMPLETED", log.read_text()
        finally:
            if recovery._inspect(scope, target) is not None:
                recovery._checked(recovery._launch("bootout", target))
    else:
        outcome = subprocess.run(
            [sys.executable, "-B", "-m", "pdffast.process_supervisor",
             "--timeout", "15", "--log", str(log), "--", *command],
            text=True, capture_output=True, timeout=20, check=False,
        )
        assert outcome.returncode == 0, outcome.stdout + outcome.stderr + log.read_text()
    topology = json.loads(report.read_bytes())
    assert topology["worker_pgid"] == topology["core_pgid"]
    assert topology["worker_sid"] == topology["core_sid"]


def _control(action, *args):
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pdffast.deployment_recovery", action, *map(str, args)],
        capture_output=True, text=True, check=False, timeout=25,
    )
    assert result.stdout, result.stderr
    return result.returncode, json.loads(result.stdout)


def test_deployment_health_checks_current_gui_and_controller(tmp_path):
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    args = ("--state-root", root, "--domain", f"gui/{os.getuid()}", "--json")
    status, absent = _control("health", *args)
    assert status == 1 and absent["state"] == "BLOCKED"
    assert absent["checks"]["controller"]["code"] == "SWEEP_MISSING"
    assert _control("reconcile-all", root) == (0, [])
    status, healthy = _control("health", *args)
    assert status == 0 and healthy["state"] == "PASS"
    assert healthy["environment"]["uid"] == os.getuid()
    assert all(item["status"] == "PASS" for item in healthy["checks"].values())
    assert healthy["code_identity"]["source_sha256"]
    assert 0 <= healthy["controller"]["age_seconds"] <= healthy["controller"]["freshness_seconds"]
    heartbeat = root / "reconcile-heartbeat.json"
    sweep = json.loads(heartbeat.read_bytes())
    recovery._write(heartbeat, {**sweep, "monotonic_seconds": time.monotonic() - 61}, replace=True)
    status, stale = _control("health", *args)
    assert status == 1 and stale["checks"]["controller"]["code"] == "SWEEP_STALE"
    recovery._write(heartbeat, {**sweep, "status": "FAILED"}, replace=True)
    status, failed = _control("health", *args)
    assert status == 1 and failed["checks"]["controller"]["code"] == "SWEEP_NOT_SUCCESSFUL"
    root.chmod(0o755)
    status, insecure = _control("health", *args)
    assert status == 1 and insecure["checks"]["state_root"]["status"] == "BLOCKED"


def test_job_cancel_cli_confirms_group_and_preserves_concurrent_job(spool):
    victim, peer = spool("cancel-victim"), spool("cancel-peer")
    for job in (victim, peer):
        job.submit()
        job.observe("inference")
    begin = time.monotonic()
    status, cancelled = _control("cancel", victim.root, victim.run)
    elapsed = time.monotonic() - begin
    assert status == 0 and cancelled["state"] == "CANCELLED"
    assert cancelled["accepted_exit"] is False and cancelled["cleanup_complete"] is True
    assert cancelled["receipt"]["verification"] == "GROUP_EMPTY"
    assert victim.recovered()
    assert elapsed < 5, elapsed
    assert all(JsonLineWorker._current_identity(pid) == identity for pid, identity in peer.identities.items())
    assert _control("cancel", victim.root, victim.run) == (0, cancelled)
    assert victim.state() == cancelled
    (peer.fixture / "release").touch()
    wait_for(peer.recovered)
    status, completed = _control("cancel", peer.root, peer.run)
    assert status == 0 and completed["state"] == "COMPLETED"
    assert completed["accepted_exit"] is True
    assert peer.state()["state"] == "COMPLETED"
    assert not (peer.path / "cancel.json").exists()
    print(json.dumps({"cancel_cooperative_seconds": round(elapsed, 4)}))


def test_job_cancel_unsubmitted_and_ambiguous_submission(spool):
    clean, ambiguous = spool("cancel-before-submit"), spool("cancel-ambiguous", lease=2)
    assert _control("cancel", clean.root, clean.run)[1]["receipt"]["verification"] == "NEVER_SUBMITTED"
    with pytest.raises(RuntimeError, match="already consumed"):
        clean.submit()
    recovery._write(ambiguous.path / "submitted.json", {"requested_at": time.time()})
    status, pending = _control("cancel", ambiguous.root, ambiguous.run)
    assert status == 3 and pending["state"] == "CANCEL_PENDING"
    assert pending["error_code"] == "SUBMISSION_UNCONFIRMED"
    assert (ambiguous.path / "cancel.json").exists()
    expires = json.loads((ambiguous.path / "plan.json").read_bytes())["expires_at"]
    wait_for(lambda: time.time() >= expires)
    completed = ambiguous.state()
    assert completed["state"] == "CANCELLED"
    assert completed["receipt"]["verification"] == "LEASE_REVOKED"
    assert _control("cancel", ambiguous.root, ambiguous.run) == (0, completed)


def test_job_cancel_restarts_after_durable_intent(spool, monkeypatch):
    victim = spool("cancel-restart")
    victim.submit()
    victim.observe("inference")
    victim.fail("SIGSTOP")
    real = recovery._inspect

    def crash_after_intent(path, target, **kwargs):
        if (path / "cancel.json").exists():
            raise KeyboardInterrupt("controller interrupted")
        return real(path, target, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(recovery, "_inspect", crash_after_intent)
        with pytest.raises(KeyboardInterrupt):
            recovery.cancel(victim.root, victim.run)
    assert (victim.path / "cancel.json").exists()
    assert not victim.recovered()
    started = time.monotonic()
    status, receipts = _control("reconcile-all", victim.root)
    elapsed = time.monotonic() - started
    assert status == 0 and receipts[0]["state"] == "CANCELLED", receipts
    assert receipts[0]["receipt"]["verification"] == "GROUP_EMPTY"
    assert victim.recovered()
    assert elapsed < 5, elapsed
    print(json.dumps({"cancel_forced_after_controller_restart_seconds": round(elapsed, 4)}))



def test_job_cancel_durable_during_manager_outage_and_refuses_foreign_scope(spool, monkeypatch):
    job = spool("cancel-manager-outage")

    def foreign(*args, **_kwargs):
        assert args[0] == "print"
        return subprocess.CompletedProcess(args, 0, "path = /foreign/job.plist\n", "")

    def unavailable(*args, **_kwargs):
        assert args[0] == "print"
        return subprocess.CompletedProcess(args, 5, "", "Could not find domain")

    with monkeypatch.context() as context:
        context.setattr(recovery, "_launch", foreign)
        mismatch = recovery.cancel(job.root, job.run)
        assert mismatch["state"] == "CANCEL_ERROR"
        assert mismatch["error_code"] == "JOB_OWNERSHIP_MISMATCH"
        assert not (job.path / "cancel.json").exists()
        context.setattr(recovery, "_launch", unavailable)
        pending = recovery.cancel(job.root, job.run)
        assert pending["state"] == "CANCEL_PENDING"
        assert pending["error_code"] == "LAUNCHD_UNAVAILABLE"
        assert (job.path / "cancel.json").exists()
    confirmed = job.state()
    assert confirmed["state"] == "CANCELLED"
    assert confirmed["receipt"]["verification"] == "NEVER_SUBMITTED"


def test_health_refuses_different_managed_code_identity(tmp_path, monkeypatch):
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    actual = recovery.code_identity()
    monkeypatch.setattr(recovery, "code_identity", lambda: {**actual, "source_sha256": "0" * 64})
    assert recovery.reconcile_all(root) == []
    report = recovery.health(root, f"gui/{os.getuid()}")
    assert report["state"] == "BLOCKED"
    assert report["checks"]["recovery_probe"]["code"] == "CANARY_CODE_IDENTITY_MISMATCH"


def test_health_checks_controller_again_after_live_probe(tmp_path, monkeypatch):
    root = tmp_path / "spool"
    root.mkdir(mode=0o700)
    assert recovery.reconcile_all(root) == []
    canary = recovery._check_recovery

    def complete_then_expire(*args):
        canary(*args)
        path = root / "reconcile-heartbeat.json"
        record = recovery._read(path)
        recovery._write(path, {**record, "monotonic_seconds": time.monotonic() - 61}, replace=True)

    monkeypatch.setattr(recovery, "_check_recovery", complete_then_expire)
    report = recovery.health(root, f"gui/{os.getuid()}")
    assert report["state"] == "BLOCKED"
    assert report["checks"]["recovery_probe"]["status"] == "PASS"
    assert report["checks"]["controller"]["code"] == "SWEEP_STALE"
