"""Build an offline page-first report from existing Provider Benchmark results.

No inference, no upload, no accuracy claims without reviewed ground truth.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import statistics
from collections import Counter
from itertools import combinations

from tools.provider_benchmark.comparison_metrics import compare_texts
from tools.provider_benchmark.evaluate import _distance, _plain
from pathlib import Path
from urllib.parse import quote

CHANNELS = ("tables", "formulas", "reading_blocks", "spatial_text", "relations")
SUCCESS = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}


def read_jsonl(path: Path) -> list[dict]:
    result = []
    for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_num}: expected object")
            result.append(item)
    return result


def percentile95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = 0.95 * (len(ordered) - 1)
    i = int(pos)
    return ordered[i] + (ordered[min(i + 1, len(ordered) - 1)] - ordered[i]) * (pos - i)


def valid_elapsed(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    n = float(value)
    return n if math.isfinite(n) and n >= 0 else None


def csv_cell(value: object) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.lstrip().startswith(("=", "+", "-", "@")) else s


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(row.get(key)) for key in columns})


def file_url(path: Path | None, output_dir: Path) -> str:
    if path is None or not path.is_file():
        return ""
    relative = os.path.relpath(path.resolve(), output_dir.resolve()).replace(os.sep, "/")
    return quote(relative, safe="/._-")


def asset_path(manifest: Path, asset: object) -> Path | None:
    if not isinstance(asset, str) or not asset:
        return None
    path = Path(asset).expanduser()
    return path if path.is_absolute() else (manifest.parent / path).resolve()


def canonical_info(raw: object, cwd: Path) -> tuple[dict, str, Path | None]:
    if not isinstance(raw, str) or not raw:
        return {}, "CANONICAL_NOT_RECORDED", None
    path = Path(raw)
    path = path if path.is_absolute() else (cwd / path)
    if not path.is_file():
        return {}, "CANONICAL_NOT_FOUND", path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (data, "", path) if isinstance(data, dict) else ({}, "CANONICAL_BAD_TYPE", path)
    except (OSError, ValueError) as exc:
        return {}, f"CANONICAL_READ_ERROR:{type(exc).__name__}", path


def h(value: object) -> str:
    return html.escape(str("" if value is None else value), quote=True)


def html_report(pages: list[dict], providers: list[str], cells: dict, summary: list[dict], out: Path) -> str:
    parts = ["""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PDFFast 同页七模型对照</title><style>
body{background:#f3f6fa;color:#16253b;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1700px;margin:auto;padding:24px}
.panel,.provider{background:white;border:1px solid #dbe2ec;border-radius:12px;padding:16px;margin-bottom:14px}
.pair-columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.pair-columns pre{min-height:140px;max-height:650px}
mark.only-a{background:#ffe6d9;color:#8a321d}mark.only-b{background:#dbf3e6;color:#165d3a}
.pair-head{font-weight:650;margin:8px 0}
.pair-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.pair-controls select{width:auto;min-width:170px}

.note{color:#576778;line-height:1.65;font-size:13px}
table{width:100%;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid #e8edf3}
th{background:#f7f9fc}.page{display:none}.page.active{display:block}
.top{display:grid;grid-template-columns:minmax(260px,1fr) minmax(320px,2fr);gap:18px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
img{width:100%;max-height:650px;object-fit:contain;background:#f7f9fc}
pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto;max-height:490px;line-height:1.7;font:13px ui-monospace,Menlo,monospace;padding:10px;background:#f6f8fb;border-radius:6px}
select{font-size:15px;padding:9px;max-width:500px;width:100%}.bad{color:#ad2525}.good{color:#19744b}
@media(max-width:900px){.top,.grid,.pair-columns{grid-template-columns:1fr}}
</style></head><body>
<h1>PDFFast · 同一页面 Provider 对照</h1>
<p class="note">本地报告：相同页面下并排查看原图与所有 Provider 完整文本；任选 A/B 两模型高亮不同文字片段。字符重合度和三字片段重合度表示<strong>模型之间的一致程度，不是识别准确率</strong>。未审核 Ground Truth 时 CER、字段召回均未评分。所有内容留在本机。</p>
<section class="panel"><h2>总体性能</h2><table><tr><th>Provider</th><th>成功</th><th>总耗时(s)</th><th>平均(s)</th><th>P50(s)</th><th>P95(s)</th><th>CER</th><th>字段字面召回</th><th>需关注页数</th></tr>"""]
    for x in summary:
        parts.append("<tr>" + "".join("<td>" + h(v) + "</td>" for v in (
            x["provider"], f'{x["successful_pages"]}/{x["page_count"]}', x["total_s"],
            x["mean_s"], x["p50_s"], x["p95_s"],
            (str(x["micro_cer_pct"]) + "%") if x["micro_cer_pct"] is not None else "未评分",
            (str(x["field_literal_recall_pct"]) + "%") if x["field_literal_recall_pct"] is not None else "未评分",
            x["flagged_pages"])) + "</tr>")
    parts.append("</table></section><section class='panel'><strong>选择页面：</strong> "
                 "<select id='selector'>")
    for i, page in enumerate(pages):
        parts.append(f"<option value='{i}'>{h(page['page_id'])}</option>")
    parts.append("</select><p class='note'>结构通道只表示输出状态，不代表表格/公式/阅读顺序正确。</p>")
    parts.append("<div class='pair-controls'><label for='provider-a'>A 模型</label><select id='provider-a'>")
    for i, provider in enumerate(providers):
        parts.append(f'<option value="{i}">{h(provider)}</option>')
    parts.append("</select><label for='provider-b'>B 模型</label><select id='provider-b'>")
    for i, provider in enumerate(providers):
        sel = " selected" if i == 1 else ""
        parts.append(f'<option value="{i}"{sel}>{h(provider)}</option>')
    parts.append("</select></div>"
                 "<p class='note'>切换 A/B 自动更新该页的百分比、耗时差、字数差和差异高亮；红色为 A 独有片段，绿色为 B 独有片段。百分比均不是准确率。</p>"
                 "</section>")

    for idx, page in enumerate(pages):
        pid = page["page_id"]
        url = file_url(page.get("_image"), out)
        image = f'<img src="{h(url)}" alt="页面原始图片">' if url else "<p>本地原图缺失</p>"
        parts.append(f"<section class='page{' active' if idx == 0 else ''}'><div class='panel'>"
                     f"<h2>{h(pid)}</h2><p class='note'>原文件 {h(page.get('document_id') or '—')} "
                     f"· 第 {h(page.get('page_number') or '—')} 页 "
                     f"· 抽样原因：{h(page.get('selection_reason') or '—')}</p>"
                     f"<div class='top'><div>{image}</div><div><h3>同页快速对照</h3>"
                     "<table><tr><th>Provider</th><th>状态</th><th>秒</th><th>字符数</th><th>CER</th><th>字段字面召回</th><th>提示</th></tr>")
        for provider in providers:
            item = cells[(pid, provider)]
            parts.append("<tr>" + "".join("<td>" + h(v) + "</td>" for v in (
                provider, item["status"], item["seconds"], item["chars"],
                (str(item["cer_pct"]) + "%") if item["cer_pct"] is not None else "未评分",
                (str(item["field_literal_recall_pct"]) + "%") if item["field_literal_recall_pct"] is not None else "未评分",
                item["flags"] or "—")) + "</tr>")
        parts.append("</table></div></div></div>"
                     "<div class='panel'><h3>同页 A/B 差异高亮</h3>"
                     "<p class='pair-summary note' aria-live='polite'>选择两个 Provider 查看同页差异</p>"
                     "<div class='pair-columns'>"
                     "<div><p class='pair-head'>A：<span class='pair-a-name'></span>（橙色为 A 独有片段）</p><pre class='pair-a-text'></pre></div>"
                     "<div><p class='pair-head'>B：<span class='pair-b-name'></span>（绿色为 B 独有片段）</p><pre class='pair-b-text'></pre></div>"
                     "</div><p class='pair-note note'></p></div>"
                     "<div class='grid'>")
        for provider_index, provider in enumerate(providers):
            x = cells[(pid, provider)]
            availability = " · ".join(f"{k}: {x[k]}" for k in CHANNELS)
            link = f' · <a href="{h(x["canonical_url"])}">Canonical</a>' if x["canonical_url"] else ""
            css_class = "good" if x["status"] in SUCCESS else "bad"
            parts.append(f"<article class='provider' data-provider-index='{provider_index}' data-seconds='{h(x['seconds'])}'><h3>{h(provider)}</h3>"
                         f'<p class="{css_class}">{h(x["status"])} · {h(x["seconds"])}s · {x["chars"]}字{link}</p>'
                         f'<p class="note">{h(availability)}</p>'
                         f'<p class="bad">{h(x["flags"])}</p>'
                         f'<pre data-empty="{1 if not x["text"] else 0}">{h(x["text"] or "（无文本输出）")}</pre></article>')
        parts.append("</div></section>")
    parts.append("""<script>
const selector=document.getElementById("selector");
const selectorA=document.getElementById("provider-a");
const selectorB=document.getElementById("provider-b");
function normChars(value){ return Array.from(value.replace(/\\s+/gu,"")); }
function overlap(A,B,n) {
 const a=normChars(A),b=normChars(B);
 if(!a.length&&!b.length) return null;
 if(!a.length||!b.length) return 0;
 const width=Math.min(n,a.length,b.length);
 function count(values) {
   const m=new Map();
   for(let i=0;i<=values.length-width;i++) {
     const key=values.slice(i,i+width).join("");
     m.set(key,(m.get(key)||0)+1);
   }
   return m;
 }
 const ca=count(a),cb=count(b);let common=0,total=0;
 for(const v of ca.values())total+=v;
 for(const v of cb.values())total+=v;
 for(const [key,v] of ca)common+=Math.min(v,cb.get(key)||0);
 return 100*2*common/total;
}
function units(text) {
 return text.match(/[^。！？；;\\n]+[。！？；;\\n]?|\\n+/gu)||[];
}
function annotate(target, text, highlight) {
 if(!text)return;
 const span=document.createElement("mark");
 span.className=highlight;
 span.textContent=text;
 target.appendChild(span);
}
function flushChanged(a,b,outA,outB) {
 const left=Array.from(a.join("")),right=Array.from(b.join(""));
 let prefix=0,suffix=0;
 while(prefix<left.length&&prefix<right.length&&left[prefix]===right[prefix])prefix++;
 while(suffix<left.length-prefix&&suffix<right.length-prefix&&
       left[left.length-suffix-1]===right[right.length-suffix-1])suffix++;
 const start=left.slice(0,prefix).join("");
 const end=suffix?left.slice(left.length-suffix).join(""):"";
 for(const out of [outA,outB])out.appendChild(document.createTextNode(start));
 annotate(outA,left.slice(prefix,left.length-suffix).join(""),"only-a");
 annotate(outB,right.slice(prefix,right.length-suffix).join(""),"only-b");
 for(const out of [outA,outB])out.appendChild(document.createTextNode(end));
}
function compareFragments(left,right,outA,outB,note) {
 outA.replaceChildren();outB.replaceChildren();
 const A=units(left),B=units(right),m=A.length,n=B.length;
 if(!m&&!n) {note.textContent="两侧均无文本输出";return;}
 // Deliberately bounded: a very long page must not freeze an offline report.
 if(m*n>65000||m>500||n>500) {
   outA.textContent=left||"（无文本）";
   outB.textContent=right||"（无文本）";
   note.textContent="该页片段过多，已保留全文对照而跳过高亮；CSV 百分比仍可使用。";
   return;
 }
 const dp=Array.from({length:m+1},()=>new Uint16Array(n+1));
 for(let i=m-1;i>=0;i--) for(let j=n-1;j>=0;j--) {
   dp[i][j]=A[i]===B[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);
 }
 let i=0,j=0,changeA=[],changeB=[];
 function flush(){flushChanged(changeA,changeB,outA,outB);changeA=[];changeB=[];}
 while(i<m||j<n) {
   if(i<m&&j<n&&A[i]===B[j]) {
     flush();
     outA.appendChild(document.createTextNode(A[i]));
     outB.appendChild(document.createTextNode(B[j]));i++;j++;
   } else if(j>=n||(i<m&&dp[i+1][j]>=dp[i][j+1])) {
     changeA.push(A[i]);i++;
   } else {
     changeB.push(B[j]);j++;
   }
 }
 flush();
 note.textContent="先对齐相同语句片段，再细化差异块的共同前后缀；标亮部分包含内容变化和排版变化，不代表识别错误。";
}
function fmt(v){return v===null?"不可计算":v.toFixed(2)+"%";}
function update() {
 document.querySelectorAll(".page").forEach((el,i)=>{
   el.classList.toggle("active",String(i)===selector.value);
 });
 const page=document.querySelector(".page.active");
 if(!page)return;
 const cards=page.querySelectorAll(".provider");
 const idxA=Number(selectorA.value),idxB=Number(selectorB.value);
 const cardA=cards[idxA],cardB=cards[idxB];
 if(!cardA||!cardB)return;
 const preA=cardA.querySelector("pre"),preB=cardB.querySelector("pre");
 const textA=preA.dataset.empty==="1"?"":preA.textContent;
 const textB=preB.dataset.empty==="1"?"":preB.textContent;
 const nameA=cardA.querySelector("h3").textContent;
 const nameB=cardB.querySelector("h3").textContent;
 page.querySelector(".pair-a-name").textContent=nameA;
 page.querySelector(".pair-b-name").textContent=nameB;
 const aLen=normChars(textA).length,bLen=normChars(textB).length;
 const char=overlap(textA,textB,1),gram=overlap(textA,textB,3);
 page.querySelector(".pair-summary").textContent=
   "字符重合度："+fmt(char)+"｜连续三字片段重合度："+fmt(gram)+
   "｜去空白字数 A："+aLen+"，B："+bLen+
   "｜字数差（A−B）："+(aLen-bLen)+
   "｜执行耗时差（A−B）："+
   (Number.isFinite(Number(cardA.dataset.seconds))&&Number.isFinite(Number(cardB.dataset.seconds))?
      (Number(cardA.dataset.seconds)-Number(cardB.dataset.seconds)).toFixed(2)+"s":"不可计算")+
   "。这些百分比表示两份输出有多像，不表示识别正确率。";
 if(idxA===idxB) {
   page.querySelector(".pair-a-text").textContent=textA||"（无文本）";
   page.querySelector(".pair-b-text").textContent=textB||"（无文本）";
   page.querySelector(".pair-note").textContent="你选择了同一个 Provider，两边输出完全相同。";
   return;
 }
 compareFragments(textA,textB,page.querySelector(".pair-a-text"),
                  page.querySelector(".pair-b-text"),
                  page.querySelector(".pair-note"));
}
for(const x of [selector,selectorA,selectorB])x.addEventListener("change",update);
update();
</script></body></html>""")
    return "\n".join(parts)


def build_report(*, manifest: Path, prediction_files: list[Path], out: Path, cwd: Path | None = None,
                 exclude: list[str] | None = None, truth: Path | None = None) -> dict:
    manifest = Path(manifest).resolve()
    out = Path(out).resolve()
    cwd = Path(cwd or Path.cwd()).resolve()
    pages = read_jsonl(manifest)
    ids = [p.get("page_id") for p in pages]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("empty, invalid or duplicate page_id in manifest")
    fp = hashlib.sha256(
        json.dumps(pages, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    excluded = set(exclude or [])
    truth_rows = read_jsonl(Path(truth).resolve()) if truth else []
    truth_by_id = {x.get("page_id"): x for x in truth_rows}
    if len(truth_by_id) != len(truth_rows):
        raise ValueError("duplicate Ground Truth page_id")
    unexpected_truth = set(truth_by_id) - set(ids)
    if unexpected_truth:
        raise ValueError(f"Ground Truth contains unexpected pages: {sorted(unexpected_truth)}")
    records: dict[tuple[str, str], dict] = {}
    providers: list[str] = []
    runs = []
    for source in prediction_files:
        source = Path(source).resolve()
        run_manifest = source.parent / "run_manifest.json"
        meta = json.loads(run_manifest.read_text(encoding="utf-8")) if run_manifest.is_file() else {}
        if meta.get("dataset_fingerprint_sha256") and meta["dataset_fingerprint_sha256"] != fp:
            raise ValueError(f"dataset fingerprint mismatch: {source}")
        runs.append({
            "source": str(source), "runtime": meta.get("runtime"),
            "dataset_sha256": meta.get("dataset_fingerprint_sha256"),
            "config_sha256": meta.get("provider_config_fingerprint_sha256"),
            "warning": None if run_manifest.is_file() else "RUN_MANIFEST_MISSING",
        })
        for r in read_jsonl(source):
            pid = r.get("page_id")
            if pid == "__teardown__":
                continue
            if pid not in ids:
                raise ValueError(f"unexpected page_id={pid} in {source}")
            provider = r.get("provider")
            if not isinstance(provider, str) or not provider:
                raise ValueError(f"invalid provider in {source}")
            if provider in excluded:
                continue
            key = (pid, provider)
            if key in records:
                raise ValueError(f"duplicate prediction: {key}")
            records[key] = r
            if provider not in providers:
                providers.append(provider)
    if not providers:
        raise ValueError("no predictions found")
    out.mkdir(parents=True, exist_ok=True)

    cells = {}
    detail = []
    matrix = []
    for page in pages:
        pid = page["page_id"]
        page["_image"] = asset_path(manifest, page.get("image"))
        matrix_row = {k: page.get(k) for k in ("page_id", "document_id", "page_number", "selection_reason")}
        for provider in providers:
            record = records.get((pid, provider), {})
            canonical, canonical_error, canonical_path = canonical_info(record.get("canonical_path"), cwd)
            status = str(record.get("status") or "MISSING")
            full_text = record.get("text") if isinstance(record.get("text"), str) else ""
            elapsed = valid_elapsed(record.get("elapsed_seconds"))
            warnings = canonical.get("warnings") or []
            if not isinstance(warnings, list):
                warnings = [str(warnings)]
            flags = []
            if status not in SUCCESS:
                flags.append(status)
            if status in SUCCESS and not full_text.strip():
                flags.append("EMPTY_TEXT")
            if status == "SUCCESS_WITH_WARNINGS":
                flags.append(status)
            if canonical_error:
                flags.append(canonical_error)
            flags.extend(str(w) for w in warnings)
            if record.get("reason"):
                flags.append(str(record["reason"]))
            # Scoring against manual GT is only allowed for approved/reviewed
            # rows. There is no automatic "truth" from other Providers.
            gt = truth_by_id.get(pid, {})
            approved = gt.get("label_status") in {"reviewed", "approved"}
            gt_text = gt.get("text_gt")
            gt_chars = gt_edits = 0
            cer_pct = None
            if approved and status in SUCCESS and isinstance(gt_text, str) and isinstance(full_text, str):
                normalized_gt = _plain(gt_text)
                if normalized_gt:
                    gt_chars = len(normalized_gt)
                    gt_edits = _distance(normalized_gt, _plain(full_text))
                    cer_pct = round(100 * gt_edits / gt_chars, 3)
            field_count = field_found = 0
            if approved and status in SUCCESS:
                for field in gt.get("critical_fields_gt") or []:
                    val = field.get("value") if isinstance(field, dict) else None
                    if isinstance(val, str) and val.strip():
                        field_count += 1
                        field_found += int(_plain(val) in _plain(full_text))
            field_recall_pct = round(100 * field_found / field_count, 3) if field_count else None
            item = {
                "page_id": pid, "provider": provider, "status": status,
                "gt_label_status": gt.get("label_status", "unlabeled"),
                "cer_pct": cer_pct, "field_literal_recall_pct": field_recall_pct,
                "gt_chars": gt_chars, "gt_edits": gt_edits,
                "field_count": field_count, "field_found": field_found,
                "seconds": round(elapsed, 4) if elapsed is not None else None,
                "chars": len(full_text), "nonspace_chars": len("".join(full_text.split())),
                "flags": "; ".join(dict.fromkeys(flags)), "text": full_text,
                "text_preview": full_text.replace("\n", " ")[:160],
                "canonical_path": str(canonical_path) if canonical_path else "",
                "canonical_url": file_url(canonical_path, out),
            }
            for channel in CHANNELS:
                value = canonical.get(channel)
                item[channel] = value.get("availability", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN"
            cells[(pid, provider)] = item
            detail.append({k: v for k, v in item.items() if k not in ("text", "canonical_url")})
            for suffix, value in (
                ("status", status), ("seconds", item["seconds"]),
                ("chars", item["chars"]), ("flags", item["flags"]),
                ("cer_pct", item["cer_pct"]),
                ("field_literal_recall_pct", item["field_literal_recall_pct"])
            ):
                matrix_row[provider + "__" + suffix] = value
        matrix.append(matrix_row)
    summary = []
    for provider in providers:
        items = [cells[(pid, provider)] for pid in ids]
        times = [i["seconds"] for i in items if i["seconds"] is not None]
        summary.append({
            "provider": provider, "page_count": len(ids),
            "successful_pages": sum(i["status"] in SUCCESS for i in items),
            "total_s": round(sum(times), 3),
            "mean_s": round(statistics.mean(times), 3) if times else None,
            "p50_s": round(statistics.median(times), 3) if times else None,
            "p95_s": round(percentile95(times), 3) if times else None,
            "flagged_pages": sum(bool(i["flags"]) for i in items),
            "empty_text_pages": sum(i["status"] in SUCCESS and not i["text"].strip() for i in items),
            "status_counts": dict(Counter(i["status"] for i in items)),
            "scored_gt_pages": sum(i["cer_pct"] is not None for i in items),
            "micro_cer_pct": (
                round(100 * sum(i["gt_edits"] for i in items) / sum(i["gt_chars"] for i in items), 3)
                if sum(i["gt_chars"] for i in items) else None
            ),
            "field_literal_recall_pct": (
                round(100 * sum(i["field_found"] for i in items) / sum(i["field_count"] for i in items), 3)
                if sum(i["field_count"] for i in items) else None
            ),
        })
    # Every provider pair is compared on each page (not only to a chosen
    # "reference" provider), so readers can select any two fairly.
    pair_rows: list[dict] = []
    pair_summary: list[dict] = []
    for provider_a, provider_b in combinations(providers, 2):
        sub = []
        for pid in ids:
            a, b = cells[(pid, provider_a)], cells[(pid, provider_b)]
            comparable = a["status"] in SUCCESS and b["status"] in SUCCESS
            metrics = compare_texts(a["text"], b["text"]) if comparable else {
                "char_overlap_pct": None, "trigram_overlap_pct": None,
                "char_delta": None, "normalized_chars_a": None, "normalized_chars_b": None
            }
            item = {
                "page_id": pid, "provider_a": provider_a, "provider_b": provider_b,
                "status_a": a["status"], "status_b": b["status"],
                "elapsed_a_s": a["seconds"], "elapsed_b_s": b["seconds"],
                "elapsed_delta_a_minus_b_s": (
                    round(a["seconds"] - b["seconds"], 3)
                    if a["seconds"] is not None and b["seconds"] is not None else None
                ),
                **metrics,
            }
            pair_rows.append(item)
            sub.append(item)
        character = [x["char_overlap_pct"] for x in sub if x["char_overlap_pct"] is not None]
        trigrams = [x["trigram_overlap_pct"] for x in sub if x["trigram_overlap_pct"] is not None]
        pair_summary.append({
            "provider_a": provider_a, "provider_b": provider_b,
            "comparable_pages": sum(
                x["status_a"] in SUCCESS and x["status_b"] in SUCCESS for x in sub
            ),
            "char_overlap_mean_pct": round(statistics.mean(character), 2) if character else None,
            "trigram_overlap_mean_pct": round(statistics.mean(trigrams), 2) if trigrams else None,
        })
    matrix_columns = ["page_id", "document_id", "page_number", "selection_reason"]
    for provider in providers:
        matrix_columns.extend(provider + "__" + s for s in ("status", "seconds", "chars", "flags", "cer_pct", "field_literal_recall_pct"))
    write_csv(out / "page_matrix.csv", matrix_columns, matrix)
    write_csv(out / "page_provider_details.csv", [
        "page_id", "provider", "status", "seconds", "chars", "nonspace_chars",
        "flags", *CHANNELS, "text_preview", "canonical_path",
        "gt_label_status", "cer_pct", "field_literal_recall_pct",
    ], detail)
    write_csv(out / "pairwise_pages.csv", [
        "page_id", "provider_a", "provider_b", "status_a", "status_b",
        "elapsed_a_s", "elapsed_b_s", "elapsed_delta_a_minus_b_s",
        "char_overlap_pct", "trigram_overlap_pct", "char_delta",
        "normalized_chars_a", "normalized_chars_b",
    ], pair_rows)
    write_csv(out / "pairwise_summary.csv", [
        "provider_a", "provider_b", "comparable_pages",
        "char_overlap_mean_pct", "trigram_overlap_mean_pct",
    ], pair_summary)
    (out / "page_compare.html").write_text(
        html_report(pages, providers, cells, summary, out), encoding="utf-8"
    )
    md = [
        "# PDFFast 七模型同页对照（27页）", "",
        f"- {len(ids)} 页 × {len(providers)} Provider；实际预测 {len(records)} 条。",
        "- 相同页面以 page_id 对齐；不重复推理。",
        "- 未审核 Ground Truth：CER、关键字段召回率不评分；模型间百分比仅为文本重合度，**不是准确率**。",
        "- 查看原图与完整文字：本地打开 page_compare.html。",
        "",
        "## 模型汇总", "",
        "| Provider | 成功 | 总秒 | 平均秒 | P50 | P95 | 空文本成功页 | 提示页 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        md.append(f'| {s["provider"]} | {s["successful_pages"]}/{len(ids)} | '
                  f'{s["total_s"]} | {s["mean_s"]} | {s["p50_s"]} | {s["p95_s"]} | '
                  f'{s["empty_text_pages"]} | {s["flagged_pages"]} |')
    md.extend([
        "", "## 两两模型对照（同页输出重合度，非准确率）", "",
        "字符重合：忽略空白、考虑字符数量但不考虑顺序；三字连续片段：考虑局部顺序，均不是正确率或信息覆盖率。",
        "差异详情见 pairwise_pages.csv；任意两模型可在 page_compare.html 里选择并高亮差异。",
        "",
        "| A | B | 可比较页面 | 平均字符重合度 | 平均三字片段重合度 |",
        "|---|---|---:|---:|---:|",
    ])
    for x in pair_summary:
        md.append(f'| {x["provider_a"]} | {x["provider_b"]} | '
                  f'{x["comparable_pages"]} | {x["char_overlap_mean_pct"]}% | '
                  f'{x["trigram_overlap_mean_pct"]}% |')
    md.extend(["", "## 每页对齐：耗时 / 字符数", "",
               "| 页面 | " + " | ".join(providers) + " |",
               "|---|" + "|".join("---:" for _ in providers) + "|"])
    for page in pages:
        pid = page["page_id"]
        data = []
        for provider in providers:
            item = cells[(pid, provider)]
            data.append(
                f'{item["seconds"]}s / {item["chars"]}字' if item["status"] in SUCCESS else item["status"]
            )
        md.append("| " + pid + " | " + " | ".join(data) + " |")
    md.extend(["", "## 有审核 GT 时的正式质量指标", "",
               "| Provider | 已评 GT 页数 | CER（微平均，越低越好） | 字段字面召回（越高越好） |",
               "|---|---:|---:|---:|"])
    for row in summary:
        cer = f'{row["micro_cer_pct"]}%' if row["micro_cer_pct"] is not None else "未评分"
        field = f'{row["field_literal_recall_pct"]}%' if row["field_literal_recall_pct"] is not None else "未评分"
        md.append(f'| {row["provider"]} | {row["scored_gt_pages"]} | {cer} | {field} |')
    md.extend(["", "## 注意", "",
               "- 文本长度和结构通道仅用于诊断；不等于 OCR 正确率、表格正确率。",
               "- 模型加载不计入执行耗时；不同 Provider 的执行模式可能不同。",
               "- 本报告含私有 OCR 全文，仅在本机保存，禁止上传 GitHub。", ""])
    (out / "overview.md").write_text("\n".join(md), encoding="utf-8")
    meta = {
        "page_count": len(ids), "provider_count": len(providers),
        "observed_predictions": len(records), "expected_pairs": len(ids) * len(providers),
        "providers": providers, "summaries": summary,
        "dataset_fingerprint_sha256": fp, "runs": runs,
        "excluded_providers": sorted(excluded),
        "ground_truth_path": str(Path(truth).resolve()) if truth else None,
        "pairwise_summary": pair_summary,
        "quality": (
            "GT_SCORED_APPROVED_PAGES_ONLY"
            if any(x["scored_gt_pages"] for x in summary)
            else "NOT_SCORED_NEEDS_APPROVED_GROUND_TRUTH"
        ),
    }
    (out / "report_manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def main() -> int:
    p = argparse.ArgumentParser(description="Offline same-page comparison of Provider predictions")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--predictions", required=True, nargs="+", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--exclude", nargs="*", default=[], help="Providers not included in this report")
    p.add_argument("--truth", type=Path, help="Optional manually reviewed ground-truth JSONL")
    args = p.parse_args()
    report = build_report(manifest=args.manifest, prediction_files=args.predictions, out=args.out,
                          exclude=args.exclude, truth=args.truth)
    print(json.dumps({
        "pages": report["page_count"], "providers": report["provider_count"],
        "pairs": report["observed_predictions"], "expected_pairs": report["expected_pairs"],
        "quality": report["quality"], "output_dir": str(args.out)
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
