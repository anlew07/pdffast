#!/usr/bin/env python3
"""Official GitHub release radar. --online queries public releases; never install models."""
from __future__ import annotations
import argparse,json,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
SOURCES=Path(__file__).resolve().parents[1]/"references/technology-sources.json"
def collect(online=False,opener=urlopen):
    sources=json.loads(SOURCES.read_text(encoding="utf8"))["sources"];rows=[]
    for s in sources:
        repo=s["repo"]
        row={"id":s["id"],"url":s["official_url"],"release_url":s["official_url"]+"/releases",
             "state":"SOURCE_ONLY","live_checked":False}
        if online:
            try:
                req=Request(f"https://api.github.com/repos/{repo}/releases/latest",
                            headers={"Accept":"application/vnd.github+json","User-Agent":"pdffast-maintainer/0.2"})
                if os.environ.get("GITHUB_TOKEN"):
                    req.add_header("Authorization","Bearer "+os.environ["GITHUB_TOKEN"])
                with opener(req,timeout=10) as resp:raw=resp.read(262145)
                if len(raw)>262144:raise ValueError("API response too large")
                payload=json.loads(raw)
                row.update({"state":"RELEASE_FOUND","live_checked":True,
                            "version":payload.get("tag_name"),"published_at":payload.get("published_at"),
                            "release_url":payload.get("html_url")})
            except Exception as exc:
                row.update({"state":"FETCH_FAILED","error":f"{type(exc).__name__}: {exc}"[:220]})
        rows.append(row)
    return {"utc":datetime.now(timezone.utc).isoformat(),"online_requested":online,"rows":rows,
            "warning":"Release metadata is NOT accuracy, license validation or hardware compatibility; verify official source."}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--online",action="store_true")
    p.add_argument("--out",type=Path)
    a=p.parse_args();data=collect(a.online);txt=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    if a.out:
        a.out.parent.mkdir(parents=True,exist_ok=True)
        a.out.write_text(txt,encoding="utf8")
    print(txt,end="")
    return 0 if not a.online or all(x["live_checked"] for x in data["rows"]) else 2
if __name__=="__main__":raise SystemExit(main())
