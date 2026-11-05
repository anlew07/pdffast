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
.note{color:#576778;line-height:1.65;font-size:13px}
table{width:100%;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid #e8edf3}
th{background:#f7f9fc}.page{display:none}.page.active{display:block}
.top{display:grid;grid-template-columns:minmax(260px,1fr) minmax(320px,2fr);gap:18px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
img{width:100%;max-height:650px;object-fit:contain;background:#f7f9fc}
pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto;max-height:490px;line-height:1.7;font:13px ui-monospace,Menlo,monospace;padding:10px;background:#f6f8fb;border-radius:6px}
select{font-size:15px;padding:9px;max-width:500px;width:100%}.bad{color:#ad2525}.good{color:#19744b}
@media(max-width:900px){.top,.grid{grid-template-columns:1fr}}
</style></head><body>
<h1>PDFFast · 同一页面七 Provider 对照</h1>
<p class="note">本地报告：相同页面下并排查看原图、各 Provider 的完整解析文本、执行耗时、状态、字符长度和结构通道。字符多不等于更准；没有人工审核 GT 时不产生准确率。所有内容留在本机。</p>
<section class="panel"><h2>总体性能</h2><table><tr><th>Provider</th><th>成功</th><th>总耗时(s)</th><th>平均(s)</th><th>P50(s)</th><th>P95(s)</th><th>需关注页数</th></tr>"""]
    for x in summary:
        parts.append("<tr>" + "".join("<td>" + h(v) + "</td>" for v in (
            x["provider"], f'{x["successful_pages"]}/{x["page_count"]}', x["total_s"],
            x["mean_s"], x["p50_s"], x["p95_s"], x["flagged_pages"])) + "</tr>")
    parts.append("</table></section><section class='panel'><strong>选择页面：</strong> "
                 "<select id='selector'>")
    for i, page in enumerate(pages):
        parts.append(f"<option value='{i}'>{h(page['page_id'])}</option>")
    parts.append("</select><p class='note'>结构通道只表示输出状态，不代表表格/公式/阅读顺序正确。</p></section>")

    for idx, page in enumerate(pages):
        pid = page["page_id"]
        url = file_url(page.get("_image"), out)
        image = f'<img src="{h(url)}" alt="页面原始图片">' if url else "<p>本地原图缺失</p>"
        parts.append(f"<section class='page{' active' if idx == 0 else ''}'><div class='panel'>"
                     f"<h2>{h(pid)}</h2><p class='note'>原文件 {h(page.get('document_id') or '—')} "
                     f"· 第 {h(page.get('page_number') or '—')} 页 "
                     f"· 抽样原因：{h(page.get('selection_reason') or '—')}</p>"
                     f"<div class='top'><div>{image}</div><div><h3>同页快速对照</h3>"
                     "<table><tr><th>Provider</th><th>状态</th><th>秒</th><th>字符数</th><th>提示</th></tr>")
        for provider in providers:
            item = cells[(pid, provider)]
            parts.append("<tr>" + "".join("<td>" + h(v) + "</td>" for v in (
                provider, item["status"], item["seconds"], item["chars"], item["flags"] or "—")) + "</tr>")
        parts.append("</table></div></div></div><div class='grid'>")
        for provider in providers:
            x = cells[(pid, provider)]
            availability = " · ".join(f"{k}: {x[k]}" for k in CHANNELS)
            link = f' · <a href="{h(x["canonical_url"])}">Canonical</a>' if x["canonical_url"] else ""
            css_class = "good" if x["status"] in SUCCESS else "bad"
            parts.append(f"<article class='provider'><h3>{h(provider)}</h3>"
                         f'<p class="{css_class}">{h(x["status"])} · {h(x["seconds"])}s · {x["chars"]}字{link}</p>'
                         f'<p class="note">{h(availability)}</p>'
                         f'<p class="bad">{h(x["flags"])}</p>'
                         f'<pre>{h(x["text"] or "（无文本输出）")}</pre></article>')
        parts.append("</div></section>")
    parts.append("""<script>
const selector=document.getElementById("selector");
selector.addEventListener("change",()=>{
document.querySelectorAll(".page").forEach((node,i)=>{
node.classList.toggle("active",String(i)===selector.value);
});});
</script></body></html>""")
    return "\n".join(parts)


def build_report(*, manifest: Path, prediction_files: list[Path], out: Path, cwd: Path | None = None) -> dict:
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
            item = {
                "page_id": pid, "provider": provider, "status": status,
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
                ("chars", item["chars"]), ("flags", item["flags"])
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
        })
    matrix_columns = ["page_id", "document_id", "page_number", "selection_reason"]
    for provider in providers:
        matrix_columns.extend(provider + "__" + s for s in ("status", "seconds", "chars", "flags"))
    write_csv(out / "page_matrix.csv", matrix_columns, matrix)
    write_csv(out / "page_provider_details.csv", [
        "page_id", "provider", "status", "seconds", "chars", "nonspace_chars",
        "flags", *CHANNELS, "text_preview", "canonical_path"
    ], detail)
    (out / "page_compare.html").write_text(
        html_report(pages, providers, cells, summary, out), encoding="utf-8"
    )
    md = [
        "# PDFFast 七模型同页对照（27页）", "",
        f"- {len(ids)} 页 × {len(providers)} Provider；实际预测 {len(records)} 条。",
        "- 相同页面以 page_id 对齐；不重复推理。",
        "- 未审核 Ground Truth：此报告仅统计执行性能、文本长度、通道与告警，**不产生准确率**。",
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
        "quality": "NOT_SCORED_NEEDS_APPROVED_GROUND_TRUTH",
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
    args = p.parse_args()
    report = build_report(manifest=args.manifest, prediction_files=args.predictions, out=args.out)
    print(json.dumps({
        "pages": report["page_count"], "providers": report["provider_count"],
        "pairs": report["observed_predictions"], "expected_pairs": report["expected_pairs"],
        "quality": report["quality"], "output_dir": str(args.out)
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
