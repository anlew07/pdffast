#!/usr/bin/env python3
"""Validate human/Agent researched OCR candidate metadata, not source truth."""
from __future__ import annotations
import argparse,json,re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
ROUTES={"PAGE_DOCUMENT_OCR","PAGE_DOCUMENT_LAYOUT_PARSE","REGION_MULTIMODAL_PARSE","INLINE_CONTEXT_PARSE"}
REQUIRED=("id","name","version","license","release_date","source_urls","routes","hardware","model_size_gb","known_limitations")
def validate(card):
    errors=[]
    if not isinstance(card,dict):return {"status":"BLOCKED_METADATA","issues":["not a JSON object"]}
    if any(k not in card or card[k] in (None,"",[]) for k in REQUIRED):errors.append("incomplete candidate card")
    if not isinstance(card.get("id"),str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,59}",card["id"]):
        errors.append("invalid id")
    urls=card.get("source_urls")
    if not isinstance(urls,list) or not urls or any(not isinstance(u,str) or urlparse(u).scheme!="https" or not urlparse(u).netloc for u in urls):
        errors.append("source URLs must be HTTPS")
    routes=card.get("routes")
    if not isinstance(routes,list) or not routes or any(r not in ROUTES for r in routes):
        errors.append("invalid routes")
    try:
        if date.fromisoformat(card["release_date"])>date.today():errors.append("future release date")
    except (KeyError,TypeError,ValueError):errors.append("invalid release date")
    size=card.get("model_size_gb")
    if isinstance(size,bool) or not isinstance(size,(int,float)) or size<0:errors.append("invalid model size")
    return {"id":card.get("id"),"status":"BLOCKED_METADATA" if errors else "NEEDS_SOURCE_REVIEW",
            "issues":errors,"claims_are_verified":False}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cards",required=True,type=Path);p.add_argument("--out",required=True,type=Path)
    a=p.parse_args();cards=json.loads(a.cards.read_text(encoding="utf8"))
    if not isinstance(cards,list) or any(not isinstance(x,dict) for x in cards):p.error("expected JSON array of cards")
    ids=[x.get("id") for x in cards]
    if len(ids)!=len(set(ids)):p.error("duplicate ids")
    data={"cards":[validate(x) for x in cards],"note":"Sources require actual review; no license or quality verified"}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(data,ensure_ascii=False))
    return 2 if any(x["status"]=="BLOCKED_METADATA" for x in data["cards"]) else 0
if __name__=="__main__":raise SystemExit(main())