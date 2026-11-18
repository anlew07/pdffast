#!/usr/bin/env python3
"""Verify Skill structure, syntax and basic repo contract. Not a live OCR test."""
from __future__ import annotations
import argparse,compileall,json
from pathlib import Path
REQUIRED=["SKILL.md","README.md","references/project-guide.md",
          "references/change-playbooks.md","references/technology-sources.json",
          "references/repo-contract.md","references/benchmark-upgrade-policy.md",
          "scripts/project_index.py","scripts/technology_radar.py",
          "scripts/upgrade_profile.py","scripts/maintain.py","scripts/benchmark.py",
          "scripts/evaluate_upgrade.py","scripts/inspect_project.py"]
PROJECT=["pdffast/parser.py","pdffast/providers/base.py","pdffast/providers/registry.py",
         "pdffast/pipeline/runner.py","tools/provider_benchmark/run.py",
         "tools/provider_benchmark/evaluate.py","configs/providers.json"]
def check(skill,repo):
    errors=[]
    for f in REQUIRED:
        path=skill/f
        if not path.is_file():errors.append("missing skill: "+f)
        elif path.suffix==".py":
            try:compile(path.read_text(encoding="utf8"),str(path),"exec")
            except SyntaxError as exc:errors.append(str(exc))
    if (skill/"SKILL.md").is_file():
        raw=(skill/"SKILL.md").read_text(encoding="utf8")
        if not raw.startswith("---\nname: pdffast-maintainer\n") or "description:" not in raw:
            errors.append("frontmatter invalid")
    for f in PROJECT:
        if not (repo/f).is_file():errors.append("missing repo: "+f)
    return {"status":"PASS" if not errors else "FAIL","errors":errors,
            "note":"Static checks only; no model installation/inference, content accuracy, HTTP acceptance."}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",type=Path,required=True)
    a=p.parse_args()
    data=check(Path(__file__).resolve().parents[1],a.project_root.resolve())
    print(json.dumps(data,ensure_ascii=False,indent=2))
    return 0 if data["status"]=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
