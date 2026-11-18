#!/usr/bin/env python3
"""Generate unvalidated complete four-route trial Profile; no production writes."""
from __future__ import annotations
import argparse,json
from pathlib import Path
ROUTES={"PAGE_DOCUMENT_OCR","PAGE_DOCUMENT_LAYOUT_PARSE","REGION_MULTIMODAL_PARSE","INLINE_CONTEXT_PARSE"}
def draft(root,template,baseline,candidate,route):
    root=Path(root).resolve()
    registry=json.loads((root/"configs/providers.json").read_text(encoding="utf8"))["providers"]
    if candidate not in registry:raise ValueError("candidate not registered in providers.json")
    if route not in ROUTES:raise ValueError("invalid route")
    src=json.loads(Path(template).read_text(encoding="utf8"))
    if set(src.get("chains",{}))!=ROUTES:raise ValueError("template must contain exactly four routes")
    if baseline==candidate:raise ValueError("candidate identical to baseline")
    if baseline not in src["chains"][route]:raise ValueError("baseline not in selected chain")
    chains={k:list(v) for k,v in src["chains"].items()}
    if any(not isinstance(v,list) or not v for v in chains.values()):
        raise ValueError("invalid empty route")
    if candidate in chains[route]:raise ValueError("candidate already in selected route")
    chains[route]=[candidate if x==baseline else x for x in chains[route]]
    enabled=sorted({x for v in chains.values() for x in v})
    if set(enabled)-set(registry):raise ValueError("unknown provider in chains")
    return {"schema_version":"1.0","name":"REVIEW_ONLY_UNVALIDATED_"+candidate,
            "enabled_providers":enabled,"chains":chains}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",required=True,type=Path)
    p.add_argument("--template",required=True,type=Path)
    p.add_argument("--baseline",required=True)
    p.add_argument("--candidate",required=True)
    p.add_argument("--route",required=True,choices=sorted(ROUTES))
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    if a.out.exists() or a.out.resolve()==a.template.resolve():
        p.error("output exists / no overwrite allowed")
    content=draft(a.project_root,a.template,a.baseline,a.candidate,a.route)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(content,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("REVIEW ONLY: "+str(a.out)+"; full PDF/structure/HTTP/JudgeAI regression pending.")
    return 0
if __name__=="__main__":raise SystemExit(main())
