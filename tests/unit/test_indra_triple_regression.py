"""Offline contract tests for real-PDF regression orchestration; no OCR model needed."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_indra_triple_regression as regression


def test_default_pdf_directory_is_shared_workspace_resource():
    assert regression.DEFAULT_PDF_DIR == Path.home() / "Workspace/resource"


def fixture_root(tmp_path: Path):
    root = tmp_path / "project"
    for path in (regression.PROFILE, regression.CONFIG,
                 Path("scripts/run_pipeline.py"), Path(".venv/bin/python")):
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}", encoding="utf-8")
    pdfs = root / "benchmark/samples/real"
    pdfs.mkdir(parents=True)
    for name in regression.ALL_CASES:
        (pdfs / f"{name}.pdf").write_bytes(b"%PDF-1.4")
    return root, pdfs


def success(cmd, **kwargs):
    assert cmd[cmd.index("--provider-profile") + 1].endswith(
        "configs/profiles/production.indra-triple.json"
    )
    case = cmd[cmd.index("--run-id") + 1]
    run = Path(cmd[cmd.index("--output-root") + 1]) / case
    out = run / "result"
    out.mkdir(parents=True, exist_ok=True)
    (out / "document.md").write_text("正文", encoding="utf-8")
    (out / "document.json").write_text("{}", encoding="utf-8")
    (out / "audit.json").write_text(json.dumps({"validation": {
        "pass": True, "errors": [], "warnings": []
    }}), encoding="utf-8")
    stage = run / "09_8_production_fallback"
    stage.mkdir()
    (stage / "production_execution_manifest.json").write_text(json.dumps({
        "summary": {
            "task_count": 1, "accepted_task_count": 1, "escalated_count": 1,
            "attempt_provider_counts": {"indra_local": 1, "rapidocr_ch_light": 1},
            "selected_provider_counts": {"rapidocr_ch_light": 1}
        }
    }), encoding="utf-8")
    selected = stage / "selected_predictions"
    selected.mkdir()
    (selected / "t1.json").write_text(json.dumps({"attempts": [
        {"provider": "indra_local", "accepted": False,
         "escalation_triggers": ["EMPTY_TEXT_WHEN_REQUIRED"],
         "canonical": {"text": {"content": ""}}},
        {"provider": "rapidocr_ch_light", "accepted": True,
         "canonical": {"text": {"content": "005119116173\n006119116173"},
                       "diagnostics": {"machine_code": {
                           "action": "SUPPRESS_AMBIGUOUS_LONG_NUMERIC_OCR",
                           "long_numeric_candidates": ["005119116173", "006119116173"]
                       }}}},
    ]}), encoding="utf-8")
    kwargs["stdout"].write("SENSITIVE_OCR_BODY\n")
    return subprocess.CompletedProcess(cmd, 0)


def test_four_pdf_batch_produces_independent_artifacts(tmp_path, monkeypatch, capsys):
    root, pdf_dir = fixture_root(tmp_path)
    monkeypatch.setattr(regression.subprocess, "run", success)
    batch, folder = regression.run_batch(root, pdf_dir, root / "outputs")
    assert batch["status"] == "COMPLETED"
    assert batch["summary"]["machine_pass"] == 4
    assert batch["summary"]["manual_review_pending"] == 4
    assert [c["case_id"] for c in batch["cases"]] == list(regression.DEFAULT_CASES)
    for case in batch["cases"]:
        assert case["machine_status"] == "PASS"
        assert case["final_acceptance"] == "PENDING_MANUAL_REVIEW"
        assert case["indra_empty_text_attempts"] == 1
        assert case["rejection_counts"] == {"indra_local:EMPTY_TEXT_WHEN_REQUIRED": 1}
        assert case["machine_code_guard_counts"] == {
            "SUPPRESS_AMBIGUOUS_LONG_NUMERIC_OCR": 1
        }
        assert Path(case["artifacts"]["log"]).is_file()
    report = (folder / "regression_report.md").read_text(encoding="utf-8")
    assert "复核第 22 页中文标识" in report
    assert "005119116173" not in report
    assert "006119116173" not in report
    assert "SENSITIVE_OCR_BODY" not in capsys.readouterr().out
    assert (folder / "regression_summary.json").exists()


def test_failed_pipeline_does_not_count_as_pass(tmp_path, monkeypatch):
    root, pdf_dir = fixture_root(tmp_path)

    def failed(cmd, **kwargs):
        kwargs["stdout"].write("parse failed\n")
        return subprocess.CompletedProcess(cmd, 2)

    monkeypatch.setattr(regression.subprocess, "run", failed)
    batch, _ = regression.run_batch(root, pdf_dir, root / "outputs", cases=("case_001",))
    assert batch["status"] == "COMPLETED_WITH_FAILURES"
    assert batch["summary"]["machine_fail"] == 1
    assert batch["cases"][0]["machine_status"] == "FAIL"
    assert batch["cases"][0]["audit_pass"] is None


def test_missing_pdf_fails_before_creating_output(tmp_path):
    root, pdf_dir = fixture_root(tmp_path)
    (pdf_dir / "case_005.pdf").unlink()
    with pytest.raises(FileNotFoundError, match="case_005"):
        regression.run_batch(root, pdf_dir, root / "outputs")
    assert not (root / "outputs").exists()


def test_existing_case002_is_reference_only(tmp_path, monkeypatch):
    root, pdf_dir = fixture_root(tmp_path)
    monkeypatch.setattr(regression.subprocess, "run", success)
    old = root / "existing_case002"
    log = root / "log"
    with log.open("w", encoding="utf-8") as stream:
        success(["python", "--run-id", "existing_case002", "--output-root", str(root),
                 "--provider-profile", str(root / regression.PROFILE)], stdout=stream)
    assert old.is_dir()
    batch, folder = regression.run_batch(
        root, pdf_dir, root / "outputs", cases=("case_003",),
        case_002_existing=old,
    )
    assert batch["summary"]["completed_new_cases"] == 1
    assert batch["summary"]["machine_pass"] == 1
    assert batch["cases"][0]["source"] == "EXISTING_NOT_REPROCESSED"
    assert batch["cases"][1]["source"] == "NEW_RUN"
    assert "EXISTING_NOT_REPROCESSED" in (
        folder / "regression_report.md"
    ).read_text(encoding="utf-8")
