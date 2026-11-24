#!/usr/bin/env python3
"""Sequential real-PDF regression for the single V3 Indra/RapidOCR/MinerU profile.

The prior case_002 smoke may be referenced without rerunning it. This script
never changes Provider configs, suppresses full OCR console output, preserves
artifacts, and does not claim manual OCR-quality acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CASES = ("case_001", "case_003", "case_004", "case_005")
ALL_CASES = ("case_001", "case_002", "case_003", "case_004", "case_005")
DEFAULT_PDF_DIR = Path("benchmark/samples/real")
PROFILE = Path("configs/profiles/production.indra-triple.json")
CONFIG = Path("configs/providers.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_run(run_dir: Path, case_id: str, pdf: Path, code: int, seconds: float) -> dict:
    """Report evidence and machine status; manual accuracy remains pending."""
    paths = {
        "markdown": run_dir / "result/document.md",
        "canonical": run_dir / "result/document.json",
        "audit": run_dir / "result/audit.json",
        "provider_manifest": run_dir / "09_8_production_fallback/production_execution_manifest.json",
        "log": (run_dir / "console.log" if (run_dir / "console.log").is_file()
                else run_dir / "smoke_console.log"),
    }
    record = {
        "case_id": case_id, "pdf": str(pdf), "pdf_sha256": sha256(pdf) if pdf.is_file() else None,
        "exit_code": code, "duration_seconds": round(seconds, 2),
        "artifacts": {k: str(v) for k, v in paths.items()},
        "missing_artifacts": [k for k in ("markdown", "canonical", "audit") if not paths[k].is_file()],
        "audit_pass": None, "audit_errors": [], "audit_warnings": [],
        "provider_summary_status": "NOT_AVAILABLE", "provider_summary": None,
        "rejection_counts": {}, "machine_code_guard_counts": {},
        "indra_empty_text_attempts": 0, "prediction_files_inspected": 0,
        "manual_review": {
            "status": "PENDING",
            "checks": (["复核第 22 页中文标识", "核对正文、图片及证书 OCR"]
                       if case_id == "case_001" else ["核对全文关键字段和图片文字"]),
        },
    }
    try:
        audit = load_json(paths["audit"])
        if isinstance(audit, dict):
            validation = audit.get("validation") or {}
            if isinstance(validation, dict):
                value = validation.get("pass")
                record["audit_pass"] = value if isinstance(value, bool) else None
                record["audit_errors"] = validation.get("errors") if isinstance(validation.get("errors"), list) else []
                record["audit_warnings"] = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
        manifest = load_json(paths["provider_manifest"])
        if isinstance(manifest, dict) and isinstance(manifest.get("summary"), dict):
            record["provider_summary_status"] = "AVAILABLE"
            record["provider_summary"] = manifest["summary"]
        rejected, guards = Counter(), Counter()
        folder = run_dir / "09_8_production_fallback/selected_predictions"
        for selected_file in sorted(folder.glob("*.json")):
            selected = load_json(selected_file)
            if not isinstance(selected, dict):
                continue
            record["prediction_files_inspected"] += 1
            for attempt in selected.get("attempts") or []:
                if not isinstance(attempt, dict):
                    continue
                provider = str(attempt.get("provider") or "UNKNOWN")
                canonical = attempt.get("canonical") or {}
                if not isinstance(canonical, dict):
                    canonical = {}
                text_obj = canonical.get("text") or {}
                text = text_obj.get("content") if isinstance(text_obj, dict) else None
                if provider == "indra_local" and isinstance(text, str) and not text.strip():
                    record["indra_empty_text_attempts"] += 1
                if attempt.get("accepted") is False:
                    for trigger in attempt.get("escalation_triggers") or []:
                        rejected[f"{provider}:{trigger}"] += 1
                diagnostics = canonical.get("diagnostics") or {}
                machine = diagnostics.get("machine_code") if isinstance(diagnostics, dict) else None
                if isinstance(machine, dict):
                    action = str(machine.get("action") or "NONE")
                    if action not in ("NONE", ""):
                        guards[action] += 1
                        # Never copy uncertain barcode numbers into reports.
        record["rejection_counts"] = dict(sorted(rejected.items()))
        record["machine_code_guard_counts"] = dict(sorted(guards.items()))
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        record["evidence_error"] = f"{type(exc).__name__}: {exc}"
    record["machine_status"] = (
        "PASS" if code == 0 and record["audit_pass"] is True
        and not record["missing_artifacts"] and not record.get("evidence_error")
        else "FAIL"
    )
    record["final_acceptance"] = (
        "PENDING_MANUAL_REVIEW" if record["machine_status"] == "PASS" else "FAILED"
    )
    return record


def save_report(batch: dict, folder: Path) -> None:
    new = [c for c in batch["cases"] if c["source"] == "NEW_RUN"]
    batch["summary"] = {
        "planned_new_cases": batch["planned_new_cases"],
        "completed_new_cases": len(new),
        "machine_pass": sum(x["machine_status"] == "PASS" for x in new),
        "machine_fail": sum(x["machine_status"] != "PASS" for x in new),
        "manual_review_pending": sum(x["manual_review"]["status"] == "PENDING" for x in batch["cases"]),
    }
    (folder / "regression_summary.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Indra / RapidOCR / MinerU 真实 PDF 回归验收",
        "",
        f"- 批次：{batch['batch_id']}",
        f"- Profile SHA-256：{batch['profile_sha256']}",
        f"- Provider config SHA-256：{batch['provider_config_sha256']}",
        f"- 状态：{batch['status']}",
        f"- 已完成机器校验：{batch['summary']['machine_pass']}/{batch['planned_new_cases']} PASS",
        "- OCR 内容准确性：尚需人工复核，不自动判定通过。",
        "",
        "| 案例 | 来源 | 机器状态 | 审计 | 任务 | Indra 尝试 | RapidOCR 尝试 | MinerU 尝试 | 回退数 | 人工 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for c in batch["cases"]:
        stats = c.get("provider_summary") or {}
        attempted = stats.get("attempt_provider_counts") or {}
        fields = [
            c["case_id"], c["source"], c["machine_status"], str(c["audit_pass"]),
            str(stats.get("task_count", "-")), str(attempted.get("indra_local", 0)),
            str(attempted.get("rapidocr_ch_light", 0)), str(attempted.get("mineru_local", 0)),
            str(stats.get("escalated_count", "-")), c["manual_review"]["status"],
        ]
        lines.append("| " + " | ".join(fields) + " |")
    lines += ["", "## 分案例诊断", ""]
    for c in batch["cases"]:
        stats = c.get("provider_summary") or {}
        lines += [
            f"### {c['case_id']}",
            f"- 状态：{c['machine_status']}；退出码：{c['exit_code']}；耗时：{c['duration_seconds']} 秒",
            f"- Audit errors：{json.dumps(c['audit_errors'], ensure_ascii=False)}",
            f"- Audit warnings：{json.dumps(c['audit_warnings'], ensure_ascii=False)}",
            f"- Provider 统计：{c['provider_summary_status']}",
            f"- 最终选中：{json.dumps(stats.get('selected_provider_counts') or {}, ensure_ascii=False)}",
            f"- 回退原因：{json.dumps(c['rejection_counts'], ensure_ascii=False)}",
            f"- 条码保护动作：{json.dumps(c['machine_code_guard_counts'], ensure_ascii=False)}",
            f"- Indra 空文本次数：{c['indra_empty_text_attempts']}",
            f"- Markdown：{c['artifacts']['markdown']}",
            f"- 完整日志：{c['artifacts']['log']}",
            f"- 人工复核：{'；'.join(c['manual_review']['checks'])}",
            "",
        ]
    lines += [
        "## 验收边界", "",
        "机器 PASS 只证明解析产物存在且结构审计通过，不证明 OCR 文字或条形码值正确。",
        "OCR 数字与已验证条码解码值必须区分；冲突编号应抑制并保留图像证据。",
        "case_001 第 22 页中文标识必须人工核对。",
    ]
    (folder / "regression_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch(root: Path, pdf_dir: Path, output_root: Path,
              cases: tuple[str, ...] = DEFAULT_CASES,
              *, case_002_existing: Path | None = None) -> tuple[dict, Path]:
    root, pdf_dir, output_root = root.resolve(), pdf_dir.resolve(), output_root.resolve()
    profile, config = root / PROFILE, root / CONFIG
    py, entry = root / ".venv/bin/python", root / "scripts/run_pipeline.py"
    for needed in (profile, config, py, entry):
        if not needed.is_file():
            raise FileNotFoundError(f"Required file is missing: {needed}")
    if len(cases) != len(set(cases)) or any(c not in ALL_CASES for c in cases):
        raise ValueError("Case IDs must be unique and among case_001 ... case_005")
    if case_002_existing is not None and "case_002" in cases:
        raise ValueError("Do not rerun case_002 while referencing its existing result")
    for case in cases:
        pdf = pdf_dir / f"{case}.pdf"
        if not pdf.is_file():
            raise FileNotFoundError(f"Required PDF missing: {pdf}")
    folder = output_root / (
        "indra_triple_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + f"_{os.getpid()}"
    )
    folder.mkdir(parents=True, exist_ok=False)
    batch = {
        "schema_version": "1.0", "batch_id": folder.name,
        "status": "RUNNING", "started_utc": datetime.now(timezone.utc).isoformat(),
        "finished_utc": None,
        "profile": str(profile), "profile_sha256": sha256(profile),
        "provider_config_sha256": sha256(config),
        "planned_new_cases": len(cases), "cases": [],
    }
    if case_002_existing is not None:
        old = case_002_existing.expanduser().resolve()
        if not old.is_dir():
            raise FileNotFoundError(f"Existing case_002 run missing: {old}")
        previous = inspect_run(old, "case_002", pdf_dir / "case_002.pdf", 0, 0)
        previous["source"] = "EXISTING_NOT_REPROCESSED"
        previous["manual_review"]["checks"] = [
            "核对条形码歧义保护和最终 Markdown", "核对旧运行使用的 Profile/模型版本",
        ]
        batch["cases"].append(previous)
    save_report(batch, folder)
    for i, case in enumerate(cases, start=1):
        pdf = pdf_dir / f"{case}.pdf"
        target = folder / case
        log_path = folder / f"{case}.console.log"
        cmd = [str(py), str(entry), str(pdf),
               "--project-root", str(root), "--output-root", str(folder),
               "--run-id", case, "--case-id", case,
               "--provider-profile", str(profile)]
        print(f"[{i}/{len(cases)}] {case} START; log={log_path}", flush=True)
        started = time.monotonic()
        try:
            with log_path.open("w", encoding="utf-8") as log:
                exitcode = subprocess.run(cmd, cwd=root, stdout=log,
                                          stderr=subprocess.STDOUT, check=False).returncode
        except OSError as exc:
            exitcode = 127
            log_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        elapsed = time.monotonic() - started
        row = inspect_run(target, case, pdf, exitcode, elapsed)
        row["artifacts"]["log"] = str(log_path)
        row["source"] = "NEW_RUN"
        batch["cases"].append(row)
        save_report(batch, folder)
        stats = row.get("provider_summary") or {}
        attempts = stats.get("attempt_provider_counts") or {}
        print(f"[{i}/{len(cases)}] {case} {row['machine_status']} "
              f"audit={row['audit_pass']} fallback={stats.get('task_count', '?')} "
              f"indra={attempts.get('indra_local', '?')} "
              f"rapidocr={attempts.get('rapidocr_ch_light', '?')} "
              f"mineru={attempts.get('mineru_local', '?')} "
              f"elapsed={round(elapsed)}s", flush=True)
        if row["machine_status"] != "PASS":
            with log_path.open("r", encoding="utf-8", errors="replace") as log:
                for line in deque(log, maxlen=15):
                    print(line.rstrip("\n"), file=sys.stderr)
    batch["finished_utc"] = datetime.now(timezone.utc).isoformat()
    batch["status"] = (
        "COMPLETED" if all(c["machine_status"] == "PASS"
                           for c in batch["cases"] if c["source"] == "NEW_RUN")
        else "COMPLETED_WITH_FAILURES"
    )
    save_report(batch, folder)
    print(f"Done: {batch['summary']['machine_pass']}/{len(cases)} machine PASS; manual review PENDING")
    print(f"Report: {folder / 'regression_report.md'}")
    print(f"JSON: {folder / 'regression_summary.json'}")
    return batch, folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR,
                        help="PDF source directory (default: <project-root>/benchmark/samples/real)")
    parser.add_argument("--output-root", type=Path, default=Path("outputs/indra_triple_regression"))
    parser.add_argument("--all", action="store_true", help="Run all five PDFs including case_002")
    parser.add_argument("--case-002-existing", type=Path,
                        help="Include old case_002 for reference, without rerunning it")
    args = parser.parse_args()
    root = args.root.resolve()
    pdf_dir = args.pdf_dir if args.pdf_dir.is_absolute() else root / args.pdf_dir
    out = args.output_root if args.output_root.is_absolute() else root / args.output_root
    try:
        batch, _ = run_batch(root, pdf_dir, out, ALL_CASES if args.all else DEFAULT_CASES,
                             case_002_existing=args.case_002_existing)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    return 0 if batch["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
