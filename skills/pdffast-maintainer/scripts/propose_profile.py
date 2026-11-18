#!/usr/bin/env python3
"""Review-only four-route trial profile from an exact matching A/B gate."""
from __future__ import annotations
import argparse,json
from pathlib import Path
ROUTES=("PAGE_DOCUMENT_OCR","PAGE_DOCUMENT_LAYOUT_PARSE","REGION_MULTIMODAL_PARSE","INLINE_CONTEXT_PARSE")
def propose(profile,cfg,gate,route,baseline,candidate):
    if gate.get("decision")!="READY_FOR_END_TO_END" or gate.get("production_ready") is not False:
        raise ValueError("gate not eligible for further end-to-end validation")
    if gate.get("baseline_provider")!=baseline or gate.get("candidate_provider")!=candidate:
        raise ValueError("gate Provider identities do not match requested upgrade")
    providers=cfg.get("providers",{})
    if baseline not in providers or candidate not in providers:raise ValueError("Provider not registered")
    if providers[candidate].get("runtime_enabled") is not True:
        raise ValueError("candidate runtime_enabled must be true in reviewed experiment config")
    chains=profile.get("chains")
    if not isinstance(chains,dict) or set(chains)!=set(ROUTES):
        raise ValueError("profile must contain exactly four routes")
    if route not in chains or baseline not in chains[route]:
        raise ValueError("baseline missing in selected route")
    result=json.loads(json.dumps(profile))
    new=[candidate]+[x for x in chains[route] if x!=candidate]
    if len(new)>10:raise ValueError("chain exceeds 10")
    result["chains"][route]=new
    for key,names in result["chains"].items():
        if not isinstance(names,list) or not names or len(names)!=len(set(names)):
            raise ValueError("duplicate or empty route "+key)
        if any(n not in providers or providers[n].get("runtime_enabled") is not True for n in names):
            raise ValueError("unknown/disabled provider in "+key)
    result["enabled_providers"]=sorted({x for v in result["chains"].values() for x in v})
    result["name"]="TRIAL-REVIEW-ONLY-"+candidate
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("base-profile","provider-config","gate","out"):p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--route",required=True,choices=ROUTES)
    p.add_argument("--baseline",required=True);p.add_argument("--candidate",required=True)
    a=p.parse_args()
    if a.out.exists() or a.out.resolve()==a.base_profile.resolve():p.error("output exists: no overwrite")
    try:
        data=propose(json.loads(a.base_profile.read_text(encoding="utf8")),
                     json.loads(a.provider_config.read_text(encoding="utf8")),
                     json.loads(a.gate.read_text(encoding="utf8")),a.route,a.baseline,a.candidate)
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        print("REVIEW_ONLY "+str(a.out)+"; full PDF/structure/HTTP/JudgeAI regression required")
        return 0
    except (OSError,ValueError,KeyError,TypeError) as e:p.error(str(e))
if __name__=="__main__":raise SystemExit(main())