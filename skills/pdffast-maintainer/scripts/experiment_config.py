#!/usr/bin/env python3
"""Merge a new plugin into private PDFFast benchmark Registry only, never production."""
from __future__ import annotations
import argparse,copy,json
from pathlib import Path
def assemble(repo,fragment,dest):
    repo=Path(repo).resolve();dest=Path(dest).resolve()
    if dest.exists() or dest==repo or repo in dest.parents:raise ValueError("destination exists or is inside project")
    original=json.loads((repo/"configs/providers.json").read_text(encoding="utf8"))
    c=json.loads(Path(fragment).read_text(encoding="utf8"))
    if set(c.get("providers",{}))!=set(c.get("plugins",{})) or len(c.get("providers",{}))!=1:
        raise ValueError("requires one matching Provider/plugin")
    name=next(iter(c["providers"]));entry=c["providers"][name];plugin=c["plugins"][name]
    if name in original.get("providers",{}) or name in original.get("plugins",{}):raise ValueError("cannot replace existing Provider")
    if not isinstance(entry,dict) or not isinstance(plugin,dict) or entry.get("kind")!=plugin.get("kind"):
        raise ValueError("kind mismatch")
    if entry.get("runtime_enabled") is not False or entry.get("benchmark_enabled") is not False:
        raise ValueError("new Provider must start disabled")
    if any(not isinstance(plugin.get(k),str) or ":" not in plugin[k] for k in ("factory","normalizer")):
        raise ValueError("invalid callable paths")
    result=copy.deepcopy(original)
    result["providers"][name]=entry;result.setdefault("plugins",{})[name]=plugin
    result.pop("provider_chain_overrides",None)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return {"candidate":name,"output":str(dest),"production_changed":False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",required=True,type=Path)
    p.add_argument("--fragment",required=True,type=Path);p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:print(json.dumps(assemble(a.project_root,a.fragment,a.out),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as e:p.error(str(e))
if __name__=="__main__":raise SystemExit(main())