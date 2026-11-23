"""CLI output contracts: no OCR body in terminal; preserve full smoke logs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_run_pipeline_prints_artifact_paths_not_document_body(tmp_path, monkeypatch, capsys):
    from scripts import run_pipeline

    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({"providers": {}}), encoding="utf-8")

    class FakeParser:
        def parse(self, pdf_path, *, run_id, case_id):
            return {
                "canonical": {"text": "SECRET_DOCUMENT_BODY_SENTINEL"},
                "markdown": "SECRET_DOCUMENT_BODY_SENTINEL",
                "structure_audit": {"validation": {"pass": True},
                                    "payload": "SECRET_AUDIT_BODY_SENTINEL"},
                "result_document": tmp_path / "result/document.json",
                "result_markdown": tmp_path / "result/document.md",
                "result_audit": tmp_path / "result/audit.json",
                "result_manifest": tmp_path / "result/manifest.json",
            }

    monkeypatch.setattr(run_pipeline, "PDFFastParser", lambda **kwargs: FakeParser())
    monkeypatch.setattr(sys, "argv", [
        "run_pipeline.py", str(pdf), "--project-root", str(tmp_path),
        "--provider-config", str(config), "--run-id", "test-cli",
    ])
    assert run_pipeline.main() == 0
    stdout = capsys.readouterr().out
    assert "Status: PASS" in stdout
    assert "result/document.md" in stdout
    assert "result/audit.json" in stdout
    assert "SECRET_DOCUMENT_BODY_SENTINEL" not in stdout
    assert "SECRET_AUDIT_BODY_SENTINEL" not in stdout


def test_locked_cli_reports_pipeline_failure_and_nonzero_exit(tmp_path, monkeypatch, capsys):
    from pdffast import ParseResult
    from scripts import run_pipeline

    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    result = ParseResult(
        canonical={}, markdown="body", audit={"validation": {"pass": True}},
        artifacts={f"result_{key}": tmp_path / key for key in ("document", "markdown", "audit", "manifest")},
        parser_provenance={"execution_status": "COMPLETED_WITH_PIPELINE_FAILURES"},
    )

    class FakeParser:
        def parse(self, *args, **kwargs):
            return result

    monkeypatch.setattr(run_pipeline, "PDFFastParser", lambda **kwargs: FakeParser())
    monkeypatch.setattr(sys, "argv", [
        "run_pipeline.py", str(pdf), "--provider-profile", "production.json",
    ])
    assert run_pipeline.main() == 3
    output = capsys.readouterr().out
    assert "Status: COMPLETED_WITH_PIPELINE_FAILURES" in output
    assert "Status: PASS" not in output


def test_indra_smoke_keeps_full_log_and_prints_only_summary(tmp_path, monkeypatch, capsys):
    from scripts import verify_indra_runtime

    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def fake_subprocess(command, *, cwd, stdout, stderr, check):
        assert stderr == subprocess.STDOUT
        assert check is False
        assert "--run-id" in command
        stdout.write("PRIVATE_OCR_TEXT\n" * 200)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(verify_indra_runtime.subprocess, "run", fake_subprocess)
    run_dir = verify_indra_runtime.smoke_pdf(tmp_path, pdf)
    output = capsys.readouterr().out
    assert "PASS: PDF smoke" in output
    assert "PRIVATE_OCR_TEXT" not in output
    assert "result/document.md" in output
    log = run_dir / "smoke_console.log"
    assert log.is_file()
    assert log.read_text(encoding="utf-8").count("PRIVATE_OCR_TEXT") == 200


def test_indra_smoke_failure_keeps_full_log_but_tails_error(tmp_path, monkeypatch, capsys):
    from scripts import verify_indra_runtime

    pdf = tmp_path / "fixture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    def fail_subprocess(command, *, cwd, stdout, stderr, check):
        stdout.write("ERROR_SENTINEL\n" * 60)
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(verify_indra_runtime.subprocess, "run", fail_subprocess)
    with pytest.raises(SystemExit) as exc:
        verify_indra_runtime.smoke_pdf(tmp_path, pdf)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.err.count("ERROR_SENTINEL") == 25
    assert "FAIL: PDF smoke" in output.err
    logs = list((tmp_path / "outputs/indra_triple_smoke").glob("*/smoke_console.log"))
    assert len(logs) == 1
    assert logs[0].read_text(encoding="utf-8").count("ERROR_SENTINEL") == 60
