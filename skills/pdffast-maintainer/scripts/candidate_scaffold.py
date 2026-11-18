#!/usr/bin/env python3
"""Generate unique installable OCR Provider development skeleton; not a working OCR."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
ROUTES=("PAGE_DOCUMENT_OCR","PAGE_DOCUMENT_LAYOUT_PARSE","REGION_MULTIMODAL_PARSE","INLINE_CONTEXT_PARSE")
def scaffold(candidate,out,route):
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}",candidate):raise ValueError("invalid candidate ID")
    if route not in ROUTES:raise ValueError("invalid route")
    out=Path(out).resolve()
    if out.exists():raise ValueError("output exists; no overwrite")
    if not out.parent.is_dir():raise ValueError("create private experiment parent first")
    out.mkdir(mode=0o700)
    package="pdffast_lab_"+candidate
    pkg=out/package;pkg.mkdir()
    (pkg/"__init__.py").write_text("",encoding="utf8")
    (pkg/"adapter.py").write_text('''from pdffast.providers.base import ProviderPreflight,ProviderTask,RawProviderResult

class CandidateProvider:
    def __init__(self,name:str,config:dict):
        self.name=name
        self.config=dict(config)
    def preflight(self)->ProviderPreflight:
        return ProviderPreflight(self.name,False,"NOT_IMPLEMENTED: review official SDK/model/license")
    def initialize(self)->None:
        raise RuntimeError("NOT_IMPLEMENTED: load isolated model")
    def execute(self,task:ProviderTask)->RawProviderResult:
        raise RuntimeError("NOT_IMPLEMENTED: implement real inference and evidence")
    def close(self)->None:
        pass
''',encoding="utf8")
    (pkg/"normalizer.py").write_text('''"""Implement the complete PDFFast CanonicalPrediction contract."""
def normalize(*,result,manifest_task,manifest_path,result_path,known_hashes=None)->dict:
    # Read pdffast.providers.normalization and minicpm_normalizer.
    # No hallucinated tables/formulas/reading_blocks/relations.
    raise NotImplementedError("NOT_IMPLEMENTED: validate real output")
''',encoding="utf8")
    cfg={"providers":{candidate:{"kind":"experiment_"+candidate,"runtime_enabled":False,"benchmark_enabled":False}},
         "plugins":{candidate:{"kind":"experiment_"+candidate,"factory":package+".adapter:CandidateProvider",
                               "normalizer":package+".normalizer:normalize"}}}
    (out/"registry-fragment.json").write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    pyproject=("[build-system]\nrequires = [\"setuptools>=68\"]\nbuild-backend = \"setuptools.build_meta\"\n\n"+
      f"[project]\nname = \"pdffast-lab-{candidate.replace('_','-')}\"\nversion = \"0.0.0\"\nrequires-python = \">=3.12\"\n\n"+
      f"[tool.setuptools.packages.find]\nwhere = [\".\"]\ninclude = [\"{package}*\"]\n")
    (out/"pyproject.toml").write_text(pyproject,encoding="utf8")
    (out/"CHECKLIST.md").write_text(
      "1. Verify official source/license/release/platform/model size.\n"+
      "2. Isolate Worktree and Python venv; lock dependencies and model revision.\n"+
      "3. Implement Adapter preflight/initialize/execute/close and CanonicalPrediction normalizer.\n"+
      "4. Review editable install, run import/preflight/smoke/normalizer/timeout/close tests.\n"+
      "5. Use experiment_config.py to merge into private config; run A/B reviewed GT.\n"+
      "6. Full PDF/structure/HTTP/JudgeAI regression and owner-approved PR before production.\n",encoding="utf8")
    return {"candidate":candidate,"output":str(out),"status":"SKELETON_ONLY","production_ready":False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate",required=True);p.add_argument("--route",required=True,choices=ROUTES)
    p.add_argument("--out",type=Path,required=True);a=p.parse_args()
    try:r=scaffold(a.candidate,a.out,a.route)
    except (OSError,ValueError) as e:p.error(str(e))
    print(json.dumps(r,ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())