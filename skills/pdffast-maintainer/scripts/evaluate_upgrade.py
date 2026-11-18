#!/usr/bin/env python3
"""Paired approved-text-GT upgrade gate. NEVER modifies production config."""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path

SUCCESS = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
APPROVED = {"approved", "reviewed"}

def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]

def index(rows, name):
    result = {}
    for row in rows:
        page_id = row.get("page_id")
        if not isinstance(page_id, str) or not page_id or page_id in result:
            raise ValueError(name + ": missing or duplicate page_id " + repr(page_id))
        result[page_id] = row
    return result

def dist(a, b):
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(a,b)
    except ImportError:
        pass
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        new = [i]
        for j, other in enumerate(b, 1):
            new.append(min(new[-1] + 1, prev[j] + 1, prev[j - 1] + (ch != other)))
        prev = new
    return prev[-1]

def p95(values):
    if not values:
        return None
    values = sorted(values)
    x = (len(values) - 1) * .95
    i, j = int(x), math.ceil(x)
    return values[i] + (values[j] - values[i]) * (x - i)

def evaluate(manifest, truth, baseline, candidate, baseline_name, candidate_name,
             min_gt_pages=5, max_p95_ratio=1.25):
    pages = index(manifest, "manifest")
    gt = index(truth or [], "truth")
    if set(gt) - set(pages):
        raise ValueError("truth contains pages outside manifest")
    b = index([x for x in baseline if x.get("provider") == baseline_name
               and x.get("page_id") != "__teardown__"], "baseline")
    c = index([x for x in candidate if x.get("provider") == candidate_name
               and x.get("page_id") != "__teardown__"], "candidate")
    if (set(b) | set(c)) - set(pages):
        raise ValueError("predictions outside manifest")
    blocked, missing = [], []
    if not pages or set(b) != set(pages) or set(c) != set(pages):
        blocked.append("missing per-page predictions")
    b_ok = sum(x.get("status") in SUCCESS for x in b.values())
    c_ok = sum(x.get("status") in SUCCESS for x in c.values())
    if c_ok < b_ok:
        blocked.append("candidate has fewer successful pages")
    gt_pages = [p for p in pages if p in gt and gt[p].get("label_status") in APPROVED
                and isinstance(gt[p].get("text_gt"), str) and "".join(gt[p]["text_gt"].split())]
    if len(gt_pages) < min_gt_pages:
        missing.append("approved GT pages below threshold")
    paired = [p for p in gt_pages if p in b and p in c
              and b[p].get("status") in SUCCESS and c[p].get("status") in SUCCESS
              and isinstance(b[p].get("text"), str) and isinstance(c[p].get("text"), str)]
    if len(paired) != len(gt_pages):
        blocked.append("approved pages without successful paired predictions")
    n = e_b = e_c = 0
    for p in paired:
        ref = "".join(gt[p]["text_gt"].split())
        n += len(ref)
        e_b += dist(ref, "".join(b[p]["text"].split()))
        e_c += dist(ref, "".join(c[p]["text"].split()))
    cer_b, cer_c = (e_b/n, e_c/n) if n else (None, None)
    if cer_b is not None and cer_c > cer_b + 1e-12:
        blocked.append("candidate paired CER regression")
    def times(rows):
        values = []
        for p in pages:
            x = rows.get(p, {})
            t = x.get("elapsed_seconds")
            if x.get("status") in SUCCESS and isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) and t >= 0:
                values.append(float(t))
        return values
    t_b, t_c = times(b), times(c)
    p_b, p_c = p95(t_b), p95(t_c)
    if len(t_b) != len(pages) or len(t_c) != len(pages):
        missing.append("incomplete successful timing coverage")
    elif p_c > p_b * max_p95_ratio + 1e-12:
        blocked.append("candidate P95 latency regression")
    decision = "BLOCKED" if blocked else "INSUFFICIENT_EVIDENCE" if missing else "READY_FOR_END_TO_END"
    return {"decision": decision, "production_ready": False,
            "baseline_provider": baseline_name, "candidate_provider": candidate_name,
            "expected_pages": len(pages), "baseline_success": b_ok, "candidate_success": c_ok,
            "approved_gt_pages": len(gt_pages), "paired_gt_pages": len(paired),
            "baseline_paired_cer": round(cer_b, 6) if cer_b is not None else None,
            "candidate_paired_cer": round(cer_c, 6) if cer_c is not None else None,
            "baseline_p95_seconds": p_b, "candidate_p95_seconds": p_c,
            "blockers": blocked, "insufficient_evidence": missing,
            "warning": "Only paired text GT. Full PDF/structure/JudgeAI regression is mandatory."}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("manifest", "baseline-predictions", "candidate-predictions", "out"):
        p.add_argument("--" + option, type=Path, required=True)
    p.add_argument("--truth", type=Path)
    p.add_argument("--baseline-provider", required=True)
    p.add_argument("--candidate-provider", required=True)
    p.add_argument("--min-gt-pages", type=int, default=5)
    p.add_argument("--max-p95-ratio", type=float, default=1.25)
    a = p.parse_args()
    if a.min_gt_pages < 1 or not math.isfinite(a.max_p95_ratio) or a.max_p95_ratio <= 0:
        p.error("min-gt-pages >= 1 and max-p95-ratio > 0 required")
    result = evaluate(read_jsonl(a.manifest), read_jsonl(a.truth) if a.truth else None,
                      read_jsonl(a.baseline_predictions), read_jsonl(a.candidate_predictions),
                      a.baseline_provider, a.candidate_provider, a.min_gt_pages, a.max_p95_ratio)
    paths = [a.manifest, a.baseline_predictions, a.candidate_predictions]
    if a.truth:
        paths.append(a.truth)
    result["input_sha256"] = {str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["decision"] == "READY_FOR_END_TO_END" else 2

if __name__ == "__main__":
    raise SystemExit(main())
