#!/usr/bin/env python3
"""Check/accept PDFFast source contract drift. Accept needs explicit review and tests."""
from __future__ import annotations
import argparse,ast,hashlib,json,subprocess,sys
from pathlib import Path
FILES=("configs/providers.json","tools/provider_benchmark/run.py",
       "tools/provider_benchmark/prepare.py","tools/provider_benchmark/evaluate.py",
       "tools/provider_benchmark/report.py","scripts/run_pipeline.py",
       "pdffast/parser.py","pdffast/providers/base.py","pdffast/providers/registry.py")
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def cli(path):
    tree=ast.parse(path.read_text(encoding="utf8"));flags=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="add_argument":
            for x in n.args:
                if isinstance(x,ast.Constant) and isinstance(x.value,str) and x.value.startswith("--"):
                    flags.append(x.value)
    return sorted(set(flags))
def snapshot(repo):
    repo=Path(repo).resolve();config=json.loads((repo/"configs/providers.json").read_text(encoding="utf8"))
    data={"providers":sorted(config["providers"]),"plugins":sorted(config.get("plugins") or {}),
          "sha256":{},"cli":{},"missing":[]}
    for rel in FILES:
        p=repo/rel
        if not p.is_file():
            data["missing"].append(rel);continue
        data["sha256"][rel]=sha(p)
        if rel.startswith(("tools/","scripts/")):data["cli"][rel]=cli(p)
    return data
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("task",choices=("check","accept"))
    p.add_argument("--project-root",type=Path,required=True)
    p.add_argument("--confirm-reviewed",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    path=root/"references/contract_snapshot.json"
    current=snapshot(a.project_root)
    old=json.loads(path.read_text(encoding="utf8")) if path.is_file() else None
    changes={k:{"old":old.get(k) if old else None,"new":current[k]}
             for k in current if old is None or old.get(k)!=current[k]}
    result={"status":"ALIGNED" if not changes else "NO_SNAPSHOT" if old is None else "DRIFT",
            "changes":changes,"snapshot":str(path)}
    if a.task=="accept":
        if not a.confirm_reviewed or current["missing"]:
            p.error("explicit --confirm-reviewed and all required project files needed")
        t=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-v"],
                         cwd=root,capture_output=True,text=True)
        result["test_exit_code"]=t.returncode
        if t.returncode:
            result["status"]="TESTS_FAILED"
        else:
            path.write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
            result["status"]="ACCEPTED"
    output=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(output,encoding="utf8")
    print(output,end="")
    return 0 if result["status"] in {"ALIGNED","ACCEPTED"} else 2
if __name__=="__main__":raise SystemExit(main())
