#!/usr/bin/env python3
"""Private, resumable PDFFast A/B experiment orchestrator.

Never installs models, modifies production configuration or uploads private data.
"""
from __future__ import annotations
import argparse,hashlib,json,os,shutil,subprocess,sys,time,platform
from pathlib import Path
from datetime import datetime,timezone
from contextlib import contextmanager

def timestamp():return datetime.now(timezone.utc).isoformat()
def fingerprint(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
def rows(p):
    records=[json.loads(x) for x in Path(p).read_text(encoding="utf8").splitlines() if x.strip()]
    ids=[x.get("page_id") for x in records]
    if not ids or any(not isinstance(x,str) or not x or not all(c.isascii() and (c.isalnum() or c in "_.:-") for c in x) for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError("empty, invalid or duplicated manifest page_id")
    return ids
def json_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    os.replace(tmp,path)
def read_state(lab):
    return json.loads((Path(lab)/"experiment.json").read_text(encoding="utf8"))
def save(s):
    s["updated"]=timestamp();json_write(Path(s["lab"])/"experiment.json",s)
def inside(a,b):
    try:Path(a).resolve().relative_to(Path(b).resolve());return True
    except ValueError:return False
def head(root):
    r=subprocess.run(["git","-C",str(root),"rev-parse","HEAD"],capture_output=True,text=True)
    return r.stdout.strip() if r.returncode==0 else None
def freeze_assets(plan_rows):
    frozen={}
    for item in plan_rows:
        path=item.get("input")
        if not isinstance(path,str) or not Path(path).is_file():
            raise ValueError("missing actual OCR asset in plan")
        resolved=str(Path(path).resolve())
        frozen[resolved]=fingerprint(resolved)
    if not frozen:raise ValueError("empty OCR input assets")
    return frozen
def validate_assets(s):
    locked=s.get("asset_sha256")
    if not isinstance(locked,dict) or not locked:
        raise ValueError("plan has no locked OCR input hashes")
    for path,expected in locked.items():
        if not Path(path).is_file() or fingerprint(path)!=expected:
            raise ValueError("OCR input asset changed since plan: "+path)
def verify_source(s):
    for path,expected in s.get("source_sha256",{}).items():
        if not Path(path).is_file() or fingerprint(path)!=expected:
            raise ValueError("project source changed since experiment init: "+path)
def verify(s):
    root=Path(s["root"])
    if not (root/"tools/provider_benchmark/run.py").is_file():raise ValueError("benchmark runner missing")
    if head(root)!=s["head"]:raise ValueError("project HEAD changed; refuse stale experiment")
    if fingerprint(s["manifest"])!=s["manifest_sha"] or fingerprint(s["config"])!=s["config_sha"]:
        raise ValueError("locked input/config changed; make a new experiment")
    if s.get("truth") and fingerprint(s["truth"])!=s["truth_sha"]:
        raise ValueError("GT changed; make a new experiment")
    rows(s["manifest"])
    verify_source(s)
def event(s,step,phase,message):
    s["phase"]=phase;s.setdefault("history",[]).append({"when":timestamp(),"step":step,"status":phase,"message":message})
def initialize(a):
    root,lab=a.project_root.resolve(),a.lab.resolve()
    if inside(lab,root) or inside(root,lab):raise ValueError("private lab must not be within repository")
    if lab.exists():raise ValueError("lab already exists; never overwrite")
    if a.baseline==a.candidate:raise ValueError("baseline and candidate must differ")
    if not 10<=a.timeout_seconds<=86400:raise ValueError("timeout must be 10..86400 seconds")
    if not (root/"pdffast/parser.py").is_file():raise ValueError("not PDFFast repo")
    manifest=a.manifest.resolve();ids=rows(manifest)
    cfg=(a.provider_config or root/"configs/providers.json").resolve()
    providers=json.loads(cfg.read_text(encoding="utf8"))["providers"]
    if a.baseline not in providers or a.candidate not in providers:raise ValueError("providers not registered")
    gt=a.truth.resolve() if a.truth else None
    if gt and (len(rows(gt))<1 or set(rows(gt))-set(ids)):raise ValueError("GT page set invalid")
    lab.mkdir(mode=0o700,parents=True)
    s={"version":"pdffast-experiment/1","lab":str(lab),"root":str(root),"head":head(root),
       "manifest":str(manifest),"manifest_sha":fingerprint(manifest),
       "config":str(cfg),"config_sha":fingerprint(cfg),"truth":str(gt) if gt else None,
       "truth_sha":fingerprint(gt) if gt else None,"baseline":a.baseline,
       "candidate":a.candidate,"python":a.python,"allow_unapproved":a.allow_unapproved,
       "pages":len(ids),"runs":{},"phase":"INIT","history":[],
       "asset_sha256":{},"timeout_seconds":a.timeout_seconds,
       "environment":{"system":platform.system(),"machine":platform.machine(),"python":a.python},
       "source_sha256":{str(p):fingerprint(p) for folder in (root/"pdffast",root/"tools/provider_benchmark")
                        if folder.is_dir() for p in sorted(folder.rglob("*.py"))}}
    event(s,"init","INIT",f"frozen {len(ids)} pages; no inference")
    save(s);return s
@contextmanager
def locked(lab):
    path=Path(lab)/".operation.lock"
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.write(fd,f"pid={os.getpid()}\n".encode());os.close(fd)
        yield
    finally:path.unlink(missing_ok=True)
def execute(s,provider,dry):
    lab=Path(s["lab"]);dest=lab/"runs"/provider/("plan" if dry else "actual")
    if dest.exists() and any(dest.iterdir()):
        if dry:shutil.rmtree(dest)
        else:
            archive=lab/"runs"/provider/"attempts";archive.mkdir(parents=True,exist_ok=True)
            num=1
            while (archive/f"attempt-{num:03d}").exists():num+=1
            shutil.move(str(dest),str(archive/f"attempt-{num:03d}"))
    dest.mkdir(parents=True,exist_ok=True)
    cmd=[s["python"],"-m","tools.provider_benchmark.run","--project-root",s["root"],
         "--manifest",s["manifest"],"--provider-config",s["config"],
         "--providers",provider,"--out",str(dest)]
    if dry:cmd.append("--dry-run")
    if s["allow_unapproved"]:cmd.append("--allow-unapproved")
    log=dest.parent/("plan.log" if dry else "run.log")
    try:
        with log.open("w",encoding="utf8") as f:
            try:rc=subprocess.run(cmd,cwd=s["root"],stdout=f,stderr=subprocess.STDOUT,
                                   timeout=s.get("timeout_seconds",7200)).returncode
            except subprocess.TimeoutExpired:
                f.write("\nTIMEOUT: Provider process exceeded configured seconds\n")
                rc=124
    except OSError as e:log.write_text(str(e),encoding="utf8");rc=127
    return rc,dest
def plan(s):
    verify(s)
    if s["runs"]:
        if any(x for x in s["runs"].values()):
            raise ValueError("cannot re-plan after results; create a new experiment")
    frozen={}
    for p in (s["baseline"],s["candidate"]):
        rc,dest=execute(s,p,True)
        if rc or not (dest/"plan.json").is_file():
            event(s,"plan","BLOCKED",f"{p} dry-run failed");return
        data=json.loads((dest/"plan.json").read_text(encoding="utf8"))
        if len(data.get("rows",[]))!=s["pages"] or any(not x.get("input_exists") for x in data["rows"]):
            event(s,"plan","BLOCKED",f"{p} missing benchmark inputs");return
        frozen.update(freeze_assets(data["rows"]))
    s["asset_sha256"]=frozen
    event(s,"plan","PLANNED",f"locked {len(frozen)} real input asset hashes; no models initialized")
def real_run(s):
    verify(s)
    validate_assets(s)
    if s["phase"] not in {"PLANNED","PARTIAL","EXECUTED"}:raise ValueError("plan required first")
    for p in (s["baseline"],s["candidate"]):
        saved=s["runs"].get(p)
        if saved:
            pred=Path(saved["path"])
            if pred.is_file() and fingerprint(pred)==saved["sha256"]:continue
            raise ValueError("previous prediction changed; refuse overwrite")
        rc,dest=execute(s,p,False)
        pred=dest/"predictions.jsonl"
        if rc or not pred.is_file():
            event(s,"run","PARTIAL",f"{p} failed; see private log");return
        recs=[json.loads(x) for x in pred.read_text(encoding="utf8").splitlines() if x.strip()]
        if any(x.get("page_id")=="__teardown__" and x.get("status")=="CLOSE_FAILED"
               for x in recs):
            event(s,"run","PARTIAL",f"{p} Provider close failed");return
        recs=[x for x in recs if x.get("page_id")!="__teardown__"]
        pages=rows(s["manifest"]);ids=[x.get("page_id") for x in recs]
        if len(ids)!=len(pages) or set(ids)!=set(pages) or len(ids)!=len(set(ids)) or any(x.get("provider")!=p for x in recs):
            event(s,"run","PARTIAL",f"{p} incomplete/invalid results");return
        s["runs"][p]={"path":str(pred),"sha256":fingerprint(pred)}
    event(s,"run","EXECUTED","both model runs complete; accuracy unverified")
def evaluate(s):
    verify(s)
    validate_assets(s)
    if s["phase"]!="EXECUTED":raise ValueError("both runs required")
    lab=Path(s["lab"]);pred=[]
    for p in (s["baseline"],s["candidate"]):
        rec=s["runs"][p];path=Path(rec["path"])
        if fingerprint(path)!=rec["sha256"]:raise ValueError("prediction tampered")
        pred.append(str(path))
    report=lab/"comparison"
    cmd=[s["python"],"-m","tools.provider_benchmark.report","--manifest",s["manifest"],
         "--predictions",*pred,"--out",str(report)]
    if s["truth"]:cmd.extend(["--truth",s["truth"]])
    with (lab/"report.log").open("w",encoding="utf8") as out:
        rc=subprocess.run(cmd,cwd=s["root"],stdout=out,stderr=subprocess.STDOUT).returncode
    if rc:
        event(s,"evaluate","BLOCKED","report failed; see report.log");return
    gate=[s["python"],str(Path(__file__).with_name("evaluate_upgrade.py")),
          "--manifest",s["manifest"],"--baseline-predictions",pred[0],
          "--candidate-predictions",pred[1],"--baseline-provider",s["baseline"],
          "--candidate-provider",s["candidate"],"--out",str(lab/"upgrade_gate.json")]
    if s["truth"]:gate+=["--truth",s["truth"]]
    with (lab/"gate.log").open("w",encoding="utf8") as out:
        rc=subprocess.run(gate,cwd=s["root"],stdout=out,stderr=subprocess.STDOUT).returncode
    if rc not in {0,2} or not (lab/"upgrade_gate.json").is_file():
        event(s,"evaluate","BLOCKED","gate failed; see gate.log");return
    s["decision"]=json.loads((lab/"upgrade_gate.json").read_text(encoding="utf8"))["decision"]
    event(s,"evaluate","EVALUATED","gate="+s["decision"])
def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest="task",required=True)
    i=sub.add_parser("init")
    for key in ("project-root","lab","manifest"):i.add_argument("--"+key,required=True,type=Path)
    i.add_argument("--baseline",required=True);i.add_argument("--candidate",required=True)
    i.add_argument("--truth",type=Path);i.add_argument("--provider-config",type=Path)
    i.add_argument("--python",default=sys.executable);i.add_argument("--allow-unapproved",action="store_true")
    i.add_argument("--timeout-seconds",type=int,default=7200)
    for name in ("plan","run","evaluate","status"):
        q=sub.add_parser(name);q.add_argument("--lab",type=Path,required=True)
        if name=="run":q.add_argument("--confirm-inference",action="store_true")
    a=p.parse_args()
    try:
        if a.task=="init":s=initialize(a)
        else:
            with locked(a.lab):
                s=read_state(a.lab)
                if a.task=="plan":plan(s)
                if a.task=="run":
                    if not a.confirm_inference:raise ValueError("--confirm-inference required")
                    real_run(s)
                if a.task=="evaluate":evaluate(s)
                if a.task!="status":save(s)
        print(json.dumps({"phase":s["phase"],"decision":s.get("decision"),"lab":s["lab"],
                          "latest":s["history"][-1]},ensure_ascii=False,indent=2))
        return 2 if s["phase"] in {"BLOCKED","PARTIAL"} else 0
    except (ValueError,KeyError,OSError,json.JSONDecodeError) as e:
        print("ERROR: "+str(e),file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
