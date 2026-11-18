#!/usr/bin/env python3
"""Static skill selfcheck, not a live model/Provider test."""
from __future__ import annotations
import argparse, json
from pathlib import Path

FILES = ("SKILL.md", "README.md", "references/repo-contract.md",
         "references/benchmark-upgrade-policy.md", "scripts/inspect_project.py",
         "scripts/benchmark.py", "scripts/evaluate_upgrade.py", "scripts/selfcheck.py",
         "tests/test_upgrade_gate.py")
PROJECT_FILES = ("pdffast", "configs/providers.json", "tools/provider_benchmark/prepare.py",
                 "tools/provider_benchmark/run.py", "tools/provider_benchmark/evaluate.py",
                 "tools/provider_benchmark/report.py")

def check(skill_root, project_root):
    errors = []
    for item in FILES:
        path = skill_root / item
        if not path.is_file():
            errors.append("missing " + item)
        elif path.suffix == ".py":
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except SyntaxError as exc:
                errors.append(str(exc))
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8") if (skill_root/"SKILL.md").is_file() else ""
    if not skill.startswith("---\nname: pdffast-maintainer\n") or "description:" not in skill:
        errors.append("invalid frontmatter")
    for item in PROJECT_FILES:
        if not (project_root / item).exists():
            errors.append("missing project item " + item)
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "warning": "Static selfcheck only. No live OCR, model or end-to-end validation."}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True, type=Path)
    a = p.parse_args()
    result = check(Path(__file__).resolve().parents[1], a.project_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
