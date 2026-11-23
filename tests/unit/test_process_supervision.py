import json
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin process supervisor")
def test_supervisor_preserves_core_status_and_exclusive_log(tmp_path):
    log = tmp_path / "core.log"
    command = [
        sys.executable, "-B", "-m", "pdffast.process_supervisor",
        "--timeout", "5", "--log", str(log), "--",
        sys.executable, "-B", "-c", "print('core output'); raise SystemExit(7)",
    ]
    run = subprocess.run(command, capture_output=True, text=True, timeout=7, check=False)
    assert run.returncode != 0
    report = json.loads(run.stdout)
    assert report["core_returncode"] == 7
    assert report["cleanup_complete"] is True
    assert report["accepted_exit"] is False
    assert log.read_text() == "core output\n"
    again = subprocess.run(command, capture_output=True, text=True, timeout=7, check=False)
    assert again.returncode != 0
    assert log.read_text() == "core output\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin process supervisor")
@pytest.mark.parametrize("name", ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J_OWNER", "J"])
def test_process_supervision_faults(tmp_path, name):
    from scripts.verify_process_supervision import scenario

    report = scenario(tmp_path, name)
    if name == "J":
        assert report["status"] == "NOT_PROTECTED"
    else:
        assert report["cleanup_complete"] is True
        assert report["cleanup_seconds"] < 5
