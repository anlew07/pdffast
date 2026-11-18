#!/usr/bin/env python3
"""One command entry for inspection, code navigation, test and technology radar."""
from __future__ import annotations
import argparse,subprocess,sys,json
from pathlib import Path
DIR=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("task",choices=("doctor","map","impact","scaffold","tests","radar"))
    p.add_argument("--project-root",required=True,type=Path)
    p.add_argument("--out",type=Path)
    p.add_argument("--topic")
    p.add_argument("--candidate")
    p.add_argument("--route")
    p.add_argument("--online",action="store_true")
    p.add_argument("--with-tests",action="store_true")
    a=p.parse_args();root=a.project_root.resolve()
    if not (root/"pdffast/parser.py").is_file():p.error("not a PDFFast project")
    if a.task=="doctor":
        cmds=[("inspection",[sys.executable,str(DIR/"inspect_project.py"),"--project-root",str(root)]),
              ("index",[sys.executable,str(DIR/"project_index.py"),"--project-root",str(root)])]
        if a.out:cmds[-1][1].extend(["--out",str(a.out)])
        if a.with_tests:cmds.append(("tests",[sys.executable,"-m","pytest","-q","tests/unit","tests/contracts","tests/regression"]))
    elif a.task=="impact":
        if not a.topic:p.error("impact requires --topic")
        cmd=[sys.executable,str(DIR/"change_impact.py"),"--project-root",str(root),"--topic",a.topic]
        if a.out:cmd+=["--out",str(a.out)]
        cmds=[("impact",cmd)]
    elif a.task=="scaffold":
        if not a.candidate or not a.route or not a.out:p.error("scaffold requires --candidate --route --out")
        cmds=[("scaffold",[sys.executable,str(DIR/"candidate_scaffold.py"),
                          "--candidate",a.candidate,"--route",a.route,"--out",str(a.out)])]
    elif a.task=="map":
        cmd=[sys.executable,str(DIR/"project_index.py"),"--project-root",str(root)]
        if a.out:cmd+=["--out",str(a.out)]
        if a.topic:cmd+=["--topic",a.topic]
        cmds=[("map",cmd)]
    elif a.task=="tests":
        cmds=[("tests",[sys.executable,"-m","pytest","-q","tests/unit","tests/contracts","tests/regression"])]
    else:
        cmd=[sys.executable,str(DIR/"technology_radar.py")]
        if a.out:cmd+=["--out",str(a.out)]
        if a.online:cmd+=["--online"]
        cmds=[("radar",cmd)]
    results=[]
    for name,cmd in cmds:
        code=subprocess.run(cmd,cwd=root,check=False).returncode
        results.append({"step":name,"exit_code":code})
    print(json.dumps({"task":a.task,"results":results},ensure_ascii=False))
    return 2 if any(x["exit_code"] for x in results) else 0
if __name__=="__main__":raise SystemExit(main())
