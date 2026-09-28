#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

STAGE = 10
SUBSTAGE = "10.2"
VERSION = "0.1.10"
SCHEMA_VERSION = "1.0"
ARTIFACT_ROLE = "llm_ready_markdown_renderer"

MODE_NATIVE = "NATIVE"
MODE_REGION_TEXT = "REGION_TEXT_ENRICHMENT"
MODE_REGION_UNRESOLVED = "REGION_PRESERVED_UNRESOLVED"
MODE_PRESERVED_VISUAL = "PRESERVED_NATIVE_VISUAL"
MODE_INLINE_MEMBER = "INLINE_CONTEXT_MEMBER"
MODE_INLINE_COVERED = "INLINE_CONTEXT_COVERED"
MODE_PAGE_FALLBACK = "PAGE_FALLBACK_SOURCE"
MODE_PAGE_LAYOUT_FALLBACK = "PAGE_LAYOUT_FALLBACK_SOURCE"

INLINE_REPLACEMENT_NOTE = "INLINE_CONTEXT_REPLACEMENT"
INLINE_PARTIAL_NOTE = "INLINE_CONTEXT_PARTIAL_SUPPLEMENT"


# -------------------------------------------------------------------------------------------------
# IO / helpers
# -------------------------------------------------------------------------------------------------

def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compact_ws(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def nonempty_text_channel(content: dict[str, Any] | None) -> str:
    if not isinstance(content, dict):
        return ""
    text = content.get("text")
    if not isinstance(text, dict):
        return ""
    if str(text.get("availability") or "") != "AVAILABLE":
        return ""
    return str(text.get("content") or "").strip()


def raw_or_content(content: dict[str, Any] | None) -> str:
    if not isinstance(content, dict):
        return ""
    text = content.get("text")
    if not isinstance(text, dict):
        return ""
    raw = str(text.get("raw_content") or "").strip()
    if raw:
        return raw
    return str(text.get("content") or "").strip()


def record_page(record: dict[str, Any]) -> int | None:
    if record.get("source_page") is not None:
        try:
            return int(record.get("source_page"))
        except Exception:
            pass
    pages = record.get("source_pages")
    if isinstance(pages, list) and pages:
        try:
            return min(int(x) for x in pages)
        except Exception:
            return None
    return None


def record_pages(record: dict[str, Any]) -> list[int]:
    if record.get("source_page") is not None:
        try:
            return [int(record.get("source_page"))]
        except Exception:
            return []
    pages = record.get("source_pages")
    if not isinstance(pages, list):
        return []
    out: list[int] = []
    for x in pages:
        try:
            out.append(int(x))
        except Exception:
            pass
    return sorted(set(out))


def record_mode(record: dict[str, Any]) -> str:
    return str((record.get("stage10_resolution") or {}).get("mode") or "")


def visibility(record: dict[str, Any]) -> str:
    return str(record.get("effective_visibility") or "visible")


def first_page_comment(record: dict[str, Any]) -> str:
    pages = record_pages(record)
    if not pages:
        return ""
    if len(pages) == 1:
        return f"<!-- source-page: {pages[0]} -->"
    return f"<!-- source-pages: {pages[0]}-{pages[-1]} -->"


def normalize_heading_core(text: str) -> str:
    s = str(text or "").strip()
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^第[一二三四五六七八九十百零〇0-9]+章\s*", "", s)
    s = re.sub(r"^[一二三四五六七八九十百零〇0-9]+\s*[、.．]\s*", "", s)
    s = re.sub(r"[\s:：、，,。；;（）()\-—_]+", "", s)
    return s


def heading_equivalent(text: str, section_title: str) -> bool:
    t = str(text or "").strip()
    if not t or "\n" in t or len(t) > 40:
        return False
    a = normalize_heading_core(t)
    b = normalize_heading_core(section_title)
    return bool(a and b and a == b)


def clean_markdown_text(text: str) -> str:
    # Stage10.2 is a renderer, not a content normalizer. Preserve substantive text;
    # only normalize newlines/trailing spaces and collapse excessive blank lines.
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out).strip()


def append_block(chunks: list[str], block: str) -> None:
    block = str(block or "").strip()
    if not block:
        return
    if chunks and chunks[-1] != "":
        chunks.append("")
    chunks.append(block)
    chunks.append("")


# -------------------------------------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------------------------------------

def validate_canonical(doc: dict[str, Any]) -> None:
    if int(doc.get("stage", -1)) != 10:
        raise ValueError("输入必须是 Stage10 canonical_document.json")
    if str(doc.get("substage") or "") != "10.1":
        raise ValueError(f"输入 substage 必须为 10.1，实际={doc.get('substage')}")
    if str(doc.get("status") or "") != "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING":
        raise ValueError(f"canonical document 尚未准备好渲染：status={doc.get('status')}")
    if not isinstance(doc.get("sections"), list):
        raise ValueError("canonical document 缺少 sections")
    if not isinstance(doc.get("records"), list):
        raise ValueError("canonical document 缺少 records")
    overlays = doc.get("fallback_overlays")
    if not isinstance(overlays, dict):
        raise ValueError("canonical document 缺少 fallback_overlays")
    for k in ("page_fallbacks", "region_fallbacks", "inline_contexts"):
        if not isinstance(overlays.get(k), list):
            raise ValueError(f"fallback_overlays.{k} 缺失或不是数组")

    records = doc["records"]
    ids = [str(r.get("record_id") or "") for r in records if isinstance(r, dict)]
    if any(not x for x in ids):
        raise ValueError("存在缺少 record_id 的 record")
    if len(ids) != len(set(ids)):
        raise ValueError("record_id 存在重复")

    record_set = set(ids)
    for sec in doc["sections"]:
        if not isinstance(sec, dict):
            raise ValueError("sections 中存在非对象")
        for rid in sec.get("record_ids") or []:
            if rid not in record_set:
                raise ValueError(f"section 引用了不存在的 record_id：{rid}")

    summary = doc.get("summary") or {}
    declared = int(summary.get("native_record_count", -1))
    if declared != len(records):
        raise ValueError(f"native_record_count 不一致：summary={declared}, actual={len(records)}")
    if bool(summary.get("ground_truth_used", False)):
        raise ValueError("Stage10.2 runtime renderer 禁止消费 Ground Truth")


# -------------------------------------------------------------------------------------------------
# Inline overlay plan
# -------------------------------------------------------------------------------------------------

def build_inline_plan(doc: dict[str, Any], order_index: dict[str, int], records_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    inline_overlays = list((doc.get("fallback_overlays") or {}).get("inline_contexts") or [])
    replacement_anchor: dict[str, dict[str, Any]] = {}
    partial_before: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    partial_after: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    suppress_ids: set[str] = set()
    overlay_dispositions: dict[str, dict[str, Any]] = {}

    for ov in inline_overlays:
        if not isinstance(ov, dict):
            continue
        tid = str(ov.get("task_id") or "")
        full_ids = [str(x) for x in (ov.get("fully_contained_native_record_ids") or []) if str(x) in records_by_id]
        partial_ids = [str(x) for x in (ov.get("partially_overlapping_native_record_ids") or []) if str(x) in records_by_id]
        rich = raw_or_content(ov.get("fallback_content"))
        if not rich:
            overlay_dispositions[tid] = {
                "mode": "EMPTY_OVERLAY_SKIPPED",
                "page_number": ov.get("page_number"),
            }
            continue

        if full_ids:
            anchor = min(full_ids, key=lambda rid: order_index.get(rid, 10**9))
            replacement_anchor[anchor] = ov
            suppress_ids.update(full_ids)
            overlay_dispositions[tid] = {
                "mode": INLINE_REPLACEMENT_NOTE,
                "page_number": ov.get("page_number"),
                "anchor_record_id": anchor,
                "suppressed_record_ids": full_ids,
                "partial_record_ids_preserved": partial_ids,
            }
            continue

        # Partial-only overlays are not allowed to rewrite native paragraph text.
        # Render the richer context nearby as an explicit supplement. Geometry decides whether
        # it belongs before or after the partially-overlapping native record.
        if partial_ids:
            anchor = min(partial_ids, key=lambda rid: order_index.get(rid, 10**9))
            rec = records_by_id[anchor]
            obox = ov.get("source_bbox") or {}
            rbox = rec.get("bbox") or {}
            try:
                otop = float(obox.get("top"))
                rtop = float(rbox.get("top"))
                rbottom = float(rbox.get("bottom"))
                rel = (otop - rtop) / max(1.0, rbottom - rtop)
            except Exception:
                rel = 1.0
            if rel <= 0.20:
                partial_before[anchor].append(ov)
                position = "before"
            else:
                partial_after[anchor].append(ov)
                position = "after"
            overlay_dispositions[tid] = {
                "mode": INLINE_PARTIAL_NOTE,
                "page_number": ov.get("page_number"),
                "anchor_record_id": anchor,
                "position": position,
                "partial_record_ids_preserved": partial_ids,
            }
        else:
            # No materialized native anchor. Keep it visible at section tail via deferred list.
            overlay_dispositions[tid] = {
                "mode": "UNANCHORED_SUPPLEMENT",
                "page_number": ov.get("page_number"),
            }

    return {
        "replacement_anchor": replacement_anchor,
        "partial_before": dict(partial_before),
        "partial_after": dict(partial_after),
        "suppress_ids": suppress_ids,
        "overlay_dispositions": overlay_dispositions,
    }


# -------------------------------------------------------------------------------------------------
# Rendering
# -------------------------------------------------------------------------------------------------

def render_inline_replacement(overlay: dict[str, Any]) -> str:
    raw = clean_markdown_text(raw_or_content(overlay.get("fallback_content")))
    if not raw:
        return ""
    tid = str(overlay.get("task_id") or "")
    page = overlay.get("page_number")
    return (
        f"<!-- inline-context-replacement: {tid}; page: {page} -->\n"
        f"【局部识别替换开始｜第{page}页】\n"
        f"{raw}\n"
        f"【局部识别替换结束】"
    )


def render_inline_partial_supplement(overlay: dict[str, Any]) -> str:
    content = overlay.get("fallback_content")
    raw = clean_markdown_text(raw_or_content(content))
    if not raw:
        return ""
    tid = str(overlay.get("task_id") or "")
    page = overlay.get("page_number")

    # Partial overlap must not rewrite native text. If the provider emitted explicit formulas,
    # expose only those symbols/formulas to avoid duplicating the surrounding native sentence.
    formulas_obj = (content or {}).get("formulas") if isinstance(content, dict) else None
    formulas = []
    if isinstance(formulas_obj, dict) and str(formulas_obj.get("availability") or "") == "AVAILABLE":
        seen = set()
        for item in formulas_obj.get("items") or []:
            if not isinstance(item, dict):
                continue
            latex = str(item.get("latex") or "").strip()
            if latex and latex not in seen:
                seen.add(latex)
                formulas.append(latex)
    if formulas:
        rendered_formula = "；".join(f"${x}$" for x in formulas[:8])
        return (
            f"<!-- inline-context-supplement: {tid}; page: {page} -->\n"
            f"【局部公式/符号识别补充开始｜第{page}页】\n"
            f"{rendered_formula}\n"
            f"【局部公式/符号识别补充结束】"
        )

    return (
        f"<!-- inline-context-supplement: {tid}; page: {page} -->\n"
        f"【局部上下文识别补充开始｜第{page}页】\n"
        f"{raw}\n"
        f"【局部上下文识别补充结束】"
    )


def render_table(record: dict[str, Any]) -> str:
    display = str(record.get("table_display_text") or "").strip()
    if not display:
        display = str(record.get("table_text") or "").strip()
    if not display:
        rows = record.get("table_rows") or []
        if isinstance(rows, list):
            out: list[str] = []
            for row in rows:
                if isinstance(row, list):
                    vals = [str(x).strip() for x in row if str(x).strip()]
                    if vals:
                        out.append(" | ".join(vals))
            display = "\n".join(out)
    display = clean_markdown_text(display)
    if not display:
        return "【表格内容未能结构化输出】"
    return f"【表格】\n{display}"



def spatial_text_items(canonical: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(canonical, dict):
        return []
    obj = canonical.get("spatial_text")
    if not isinstance(obj, dict) or str(obj.get("availability") or "") != "AVAILABLE":
        return []
    items = obj.get("items")
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict) and str(x.get("text") or "").strip()]


def spatial_layout_diagnostics(canonical: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(canonical, dict):
        return {}
    diagnostics = canonical.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    layout = diagnostics.get("spatial_layout")
    return layout if isinstance(layout, dict) else {}


def spatial_structure_risk(canonical: dict[str, Any] | None) -> str:
    return str(spatial_layout_diagnostics(canonical).get("structure_risk") or "UNKNOWN").upper()


def machine_code_diagnostics(canonical: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(canonical, dict):
        return {}
    diagnostics = canonical.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {}
    obj = diagnostics.get("machine_code")
    return obj if isinstance(obj, dict) else {}


def render_machine_code_safety_block(
    canonical: dict[str, Any] | None,
    *,
    page: Any,
    region_meta: str,
    detached_note: str | None = None,
) -> str:
    """Return an LLM-facing machine-code block, or empty string when no guard applies.

    Plain OCR is never allowed to choose among conflicting barcode-like numeric
    candidates. A concrete code value is emitted only when a provider-side decoder
    explicitly verified it.
    """
    diag = machine_code_diagnostics(canonical)
    action = str(diag.get("action") or "NONE").upper()
    if action == "NONE":
        return ""

    kind = str(diag.get("kind") or "").upper()
    if kind == "QRCODE":
        kind_label = "二维码"
    elif kind == "BARCODE":
        kind_label = "条形码"
    else:
        kind_label = "机器编码/长数字图示"

    suffix = f"｜{detached_note}" if detached_note else ""
    if action == "USE_VERIFIED_MACHINE_CODE_DECODE":
        values = []
        for value in diag.get("decoded_values") or []:
            value = str(value or "").strip()
            if value and value not in values:
                values.append(value)
        if values:
            body = "\n".join(f"解码值：{value}" for value in values[:4])
            return (
                f"【机器编码识别开始｜第{page}页{region_meta}｜类型={kind_label}{suffix}】\n"
                f"{body}\n"
                "说明：以上值来自机器编码解码器，不是从普通OCR候选中猜选。\n"
                "【机器编码识别结束】"
            )

    candidate_count = int(diag.get("long_numeric_candidate_count") or 0)
    if action == "SUPPRESS_UNVERIFIED_MACHINE_CODE_OCR":
        reason = "检测到疑似机器编码区域，但未获得可靠解码值"
    else:
        reason = "普通OCR产生多个相互冲突的长数字候选，无法可靠确定具体编码值"
    count_text = f"；OCR候选数={candidate_count}" if candidate_count else ""
    return (
        f"【机器编码候选抑制开始｜第{page}页{region_meta}｜类型={kind_label}｜未可靠解码{suffix}】\n"
        f"{reason}{count_text}。为避免向下游模型提供看似真实但未经验证的编号，具体OCR候选未写入LLM正文。\n"
        "原始OCR候选、坐标与置信度仍保留在结构化解析证据中。\n"
        "【机器编码候选抑制结束】"
    )


def _complex_fragment_quality(item: dict[str, Any]) -> tuple[bool, float]:
    """Lightweight evidence-quality filter for dense diagrams.

    The score is purely lexical/OCR-confidence based. It does not decide semantic
    importance and never invents missing labels.
    """
    text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False, -10.0
    confidence = item.get("confidence")
    conf = float(confidence) if isinstance(confidence, (int, float)) else 0.75
    if conf < 0.62:
        return False, conf

    # Reject fragments that are only punctuation or a single isolated glyph.
    useful_chars = sum(1 for ch in compact if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if useful_chars == 0:
        return False, -5.0
    if len(compact) == 1:
        return False, -2.0

    punct = sum(1 for ch in compact if not (ch.isalnum() or "\u4e00" <= ch <= "\u9fff"))
    punct_ratio = punct / max(1, len(compact))
    numeric_symbol = sum(1 for ch in compact if ch.isdigit() or ch in ".,%+-−–—σΣ×*/()[]{}:=<>")
    numeric_ratio = numeric_symbol / max(1, len(compact))
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in compact)
    alpha_count = sum(1 for ch in compact if ch.isalpha())

    score = conf * 2.0
    if has_cjk:
        score += 1.4
    if alpha_count >= 3:
        score += 0.8
    if 2 <= len(compact) <= 48:
        score += 0.4
    if punct_ratio >= 0.45:
        score -= 1.0
    if numeric_ratio >= 0.75:
        score -= 1.2
    if len(compact) <= 2:
        score -= 0.7

    return score >= 1.55, score


def _spatial_entries(canonical: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return OCR text items with normalized geometry for rendering only.

    Geometry is evidence for coarse visual grouping. It is never promoted to
    reading order, arrows, hierarchy, causality, or semantic relations.
    """
    out: list[dict[str, Any]] = []
    for item in spatial_text_items(canonical):
        text = clean_markdown_text(str(item.get("text") or "")).replace("\n", " ").strip()
        if not text:
            continue
        rb = item.get("relative_bbox")
        if not isinstance(rb, dict):
            continue
        try:
            x0 = float(rb["x0"])
            x1 = float(rb["x1"])
            top = float(rb["top"])
            bottom = float(rb["bottom"])
        except Exception:
            continue
        if x1 < x0:
            x0, x1 = x1, x0
        if bottom < top:
            top, bottom = bottom, top
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = None
        out.append({
            "text": text,
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "cx": (x0 + x1) / 2.0,
            "cy": (top + bottom) / 2.0,
            "height": max(0.001, bottom - top),
            "confidence": confidence,
        })
    return out


def _group_spatial_rows(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group OCR boxes into approximate horizontal bands without inferring relations."""
    if not entries:
        return []
    heights = sorted(float(x.get("height") or 0.001) for x in entries)
    median_h = heights[len(heights) // 2] if heights else 0.03
    # Relative coordinates are normalized to the OCR-item union bbox.  Keep the
    # tolerance conservative so nearby graph nodes are not merged casually.
    row_tol = min(0.08, max(0.015, median_h * 0.75))
    ordered = sorted(entries, key=lambda x: (float(x["cy"]), float(x["x0"])))
    rows: list[list[dict[str, Any]]] = []
    centers: list[float] = []
    for item in ordered:
        cy = float(item["cy"])
        best_idx: int | None = None
        best_dist: float | None = None
        # Only compare against the most recent few rows; rows are already y-sorted.
        for idx in range(max(0, len(rows) - 3), len(rows)):
            dist = abs(cy - centers[idx])
            if dist <= row_tol and (best_dist is None or dist < best_dist):
                best_idx = idx
                best_dist = dist
        if best_idx is None:
            rows.append([item])
            centers.append(cy)
        else:
            rows[best_idx].append(item)
            centers[best_idx] = sum(float(x["cy"]) for x in rows[best_idx]) / len(rows[best_idx])
    for row in rows:
        row.sort(key=lambda x: (float(x["x0"]), float(x["cx"])))
    paired = sorted(zip(centers, rows), key=lambda x: x[0])
    return [row for _, row in paired]


def _dedupe_text_items(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in entries:
        key = re.sub(r"\s+", "", str(item.get("text") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _sample_evenly(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[len(items) // 2]]
    idxs = []
    for i in range(limit):
        idx = round(i * (len(items) - 1) / (limit - 1))
        if idx not in idxs:
            idxs.append(idx)
    return [items[i] for i in idxs]


def spatial_render_strategy(canonical: dict[str, Any] | None) -> str:
    """Choose LLM-facing serialization while keeping full bbox evidence internally."""
    entries = _spatial_entries(canonical)
    if not entries:
        return "FLAT_TEXT"
    risk = spatial_structure_risk(canonical)
    diag = spatial_layout_diagnostics(canonical)
    n = len(entries)
    try:
        row_count = int(diag.get("row_count") or 0)
    except Exception:
        row_count = 0
    try:
        numeric_ratio = float(diag.get("numeric_symbol_heavy_ratio") or 0.0)
    except Exception:
        numeric_ratio = 0.0

    # LOW-risk regions remain ordinary OCR text.  MEDIUM-risk regions and
    # manageable HIGH-risk regions keep only coarse horizontal layout.
    if risk in {"LOW", "UNKNOWN"} and n < 8:
        return "FLAT_TEXT"

    # Very dense network diagrams/charts can explode the LLM context if every
    # OCR box is serialized.  Preserve full evidence in canonical JSON but show
    # only a bounded, geometry-sampled subset in Markdown.
    if (
        n >= 24
        or (risk == "HIGH" and row_count >= 12 and n >= 16)
        or (risk == "HIGH" and numeric_ratio >= 0.45 and n >= 10)
    ):
        return "COMPLEX_COMPACT"

    return "COARSE_2D_ROWS"


def render_coarse_spatial_rows(canonical: dict[str, Any] | None) -> str:
    entries = _spatial_entries(canonical)
    rows = _group_spatial_rows(entries)
    if not rows:
        return ""
    lines = [
        "说明：以下仅按OCR文字框的近似水平位置做粗粒度分组；",
        "同一行中的左右排列仅表示几何位置，不表示箭头、连接关系、层级、流程或因果关系。",
    ]
    for row in rows:
        texts = [str(x.get("text") or "").strip() for x in row if str(x.get("text") or "").strip()]
        if texts:
            lines.append(" ｜ ".join(texts))
    return "\n".join(lines)


def render_complex_spatial_compact(canonical: dict[str, Any] | None, *, max_items: int = 8) -> str:
    """Bound dense-diagram context while preserving all evidence internally.

    Dense diagrams are auxiliary evidence for the downstream reviewer.  When OCR
    fragments are sparse or the reliable-fragment ratio is low, exposing a few
    plausible-looking labels is more likely to add noise than useful evidence.
    In that case the Markdown deliberately suppresses the fragments while the
    complete OCR text, geometry, and confidence remain in canonical JSON.
    """
    entries = _dedupe_text_items(_spatial_entries(canonical))
    if not entries:
        return ""
    entries.sort(key=lambda x: (float(x["cy"]), float(x["x0"])))
    total = len(entries)

    reliable_scored: list[tuple[dict[str, Any], float]] = []
    for item in entries:
        keep, score = _complex_fragment_quality(item)
        if keep:
            reliable_scored.append((item, score))
    reliable_count = len(reliable_scored)
    reliable_ratio = reliable_count / max(1, total)

    # Conservative LLM-facing policy for complex diagrams:
    # - too few trustworthy fragments => do not expose them;
    # - for genuinely dense diagrams, a low reliable/total ratio means the OCR
    #   evidence is dominated by fragments/noise, so do not cherry-pick a few
    #   plausible-looking labels and accidentally overstate confidence.
    suppress_for_quality = (
        reliable_count < 6
        or (total >= 12 and reliable_ratio < 0.45)
    )
    if suppress_for_quality:
        return (
            f"OCR检测到{total}个去重后的文字片段，轻量质量过滤后{reliable_count}个达到候选条件"
            f"（可靠候选占比约{reliable_ratio:.0%}）。\n"
            "该图示OCR结果中碎片或噪声占比较高，为避免少量看似可信的标签误导下游模型，LLM正文不展开具体片段。\n"
            "完整OCR文字、二维坐标与置信度仍保留在结构化解析证据中。"
        )

    # Rank only by OCR/lexical quality inside each geometric zone. This is not
    # semantic-importance ranking. Final display remains upper/middle/lower.
    reliable = [item for item, _ in reliable_scored]
    score_map = {id(item): score for item, score in reliable_scored}
    zones = [
        ("上部", [x for x in reliable if float(x["cy"]) < 1.0 / 3.0]),
        ("中部", [x for x in reliable if 1.0 / 3.0 <= float(x["cy"]) < 2.0 / 3.0]),
        ("下部", [x for x in reliable if float(x["cy"]) >= 2.0 / 3.0]),
    ]
    nonempty_zones = [(name, items) for name, items in zones if items]
    base = max_items // len(nonempty_zones)
    remainder = max_items % len(nonempty_zones)
    sampled: list[tuple[str, list[dict[str, Any]]]] = []
    shown = 0
    for idx, (name, items) in enumerate(nonempty_zones):
        quota = base + (1 if idx < remainder else 0)
        ranked = sorted(items, key=lambda x: (-score_map.get(id(x), 0.0), float(x["x0"])))
        picked = ranked[:quota]
        picked.sort(key=lambda x: float(x["x0"]))
        shown += len(picked)
        sampled.append((name, picked))

    lines = [
        f"OCR检测到{total}个去重后的文字片段；轻量质量过滤后保留{reliable_count}个候选，为控制上下文仅展示{shown}个。",
        "展示仅依据OCR置信度、字符完整性与二维位置，不代表语义重要性，也不表示阅读顺序、箭头、连接关系、层级、流程或因果关系。",
    ]
    for name, items in sampled:
        texts = [str(x.get("text") or "").strip() for x in items if str(x.get("text") or "").strip()]
        if texts:
            lines.append(f"{name}：" + " ｜ ".join(texts))
    omitted = max(0, total - shown)
    if omitted:
        lines.append(f"其余{omitted}个OCR片段未在LLM正文展开；完整文字、二维坐标与置信度仍保留在结构化解析证据中。")
    return "\n".join(lines)

def render_region_record(record: dict[str, Any]) -> str:
    res = record.get("stage10_resolution") or {}
    mode = str(res.get("mode") or "")
    page = record_page(record)
    rtype = str(record.get("record_type") or "")

    # Prefer the Stage10 source-region id carried in provenance; fall back to the
    # stable native record id. Runtime task ids are never exposed as semantic ids.
    region_id = str(
        res.get("source_region_id")
        or record.get("source_id")
        or record.get("region_id")
        or record.get("record_id")
        or ""
    ).strip()
    region_meta = f"｜区域={region_id}" if region_id else ""

    if rtype == "vector_ref":
        noun = "图形/向量区域"
        start = "图形/向量区域文字识别开始"
        end = "图形/向量区域文字识别结束"
        unresolved = "图形/向量内容未解析"
        preserved = "图形/向量内容"
    elif rtype == "image_ref":
        noun = "图示区域"
        start = "图示文字识别开始"
        end = "图示文字识别结束"
        unresolved = "图示内容未解析"
        preserved = "图示内容"
    else:
        # Future non-text refs remain explicit rather than being mislabeled as images.
        noun = "非文本区域"
        start = "非文本区域文字识别开始"
        end = "非文本区域文字识别结束"
        unresolved = "非文本区域未解析"
        preserved = "非文本区域"

    if mode == MODE_REGION_TEXT:
        fallback_content = res.get("fallback_content")
        machine_code_block = render_machine_code_safety_block(
            fallback_content,
            page=page,
            region_meta=region_meta,
        )
        if machine_code_block:
            return machine_code_block
        text = clean_markdown_text(nonempty_text_channel(fallback_content))
        strategy = spatial_render_strategy(fallback_content)
        if strategy == "COARSE_2D_ROWS":
            spatial = render_coarse_spatial_rows(fallback_content)
            if spatial:
                spatial_start = (
                    "图示文字识别开始" if rtype == "image_ref"
                    else "图形/向量区域文字识别开始" if rtype == "vector_ref"
                    else "非文本区域文字识别开始"
                )
                spatial_end = (
                    "图示文字识别结束" if rtype == "image_ref"
                    else "图形/向量区域文字识别结束" if rtype == "vector_ref"
                    else "非文本区域文字识别结束"
                )
                return (
                    f"【{spatial_start}｜第{page}页{region_meta}"
                    f"｜二维布局粗略保留｜结构关系未恢复】\n"
                    f"{spatial}\n"
                    f"【{spatial_end}】"
                )
        elif strategy == "COMPLEX_COMPACT":
            compact = render_complex_spatial_compact(fallback_content)
            if compact:
                complex_start = (
                    "复杂图示开始" if rtype == "image_ref"
                    else "复杂图形/向量区域开始" if rtype == "vector_ref"
                    else "复杂非文本区域开始"
                )
                complex_end = (
                    "复杂图示结束" if rtype == "image_ref"
                    else "复杂图形/向量区域结束" if rtype == "vector_ref"
                    else "复杂非文本区域结束"
                )
                return (
                    f"【{complex_start}｜第{page}页{region_meta}｜结构关系未恢复】\n"
                    f"{compact}\n"
                    f"【{complex_end}】"
                )
        if not text:
            return (
                f"【{noun}｜第{page}页{region_meta}"
                f"｜OCR文本为空，原始区域已保留】"
            )
        return (
            f"【{start}｜第{page}页{region_meta}｜结构关系未恢复】\n"
            f"{text}\n"
            f"【{end}】"
        )
    if mode == MODE_REGION_UNRESOLVED:
        return (
            f"【{unresolved}｜第{page}页{region_meta}"
            f"｜原始区域已保留】"
        )
    if mode == MODE_PRESERVED_VISUAL:
        return (
            f"【{preserved}｜第{page}页{region_meta}"
            f"｜保留原始区域】"
        )
    return ""


def render_detached_region_overlay(overlay: dict[str, Any]) -> tuple[str, str]:
    """Render a Stage7 source-only region that has no Stage6 native record anchor.

    The output is deliberately explicit that the region did not enter the Stage6 main
    structural flow. We therefore expose the recovered text without pretending to know
    its exact relative reading-order position among native paragraphs.
    """
    page = overlay.get("page_number")
    qgr = overlay.get("quality_gate_region") or {}
    region_id = str(qgr.get("region_id") or overlay.get("source_id") or "").strip()
    region_type = str(qgr.get("region_type") or "").strip().lower()
    region_meta = f"｜区域={region_id}" if region_id else ""

    if region_type == "image":
        noun = "图示区域"
        start = "未进入主结构流的图示文字识别开始"
        end = "未进入主结构流的图示文字识别结束"
        unresolved = "未进入主结构流的图示内容未解析"
    elif region_type == "vector":
        noun = "图形/向量区域"
        start = "未进入主结构流的图形/向量文字识别开始"
        end = "未进入主结构流的图形/向量文字识别结束"
        unresolved = "未进入主结构流的图形/向量内容未解析"
    else:
        noun = "非文本区域"
        start = "未进入主结构流的非文本区域文字识别开始"
        end = "未进入主结构流的非文本区域文字识别结束"
        unresolved = "未进入主结构流的非文本区域未解析"

    note = "原始区域未进入Stage6主结构流，正文相对位置未恢复"
    if bool(overlay.get("terminal_fallback_applied")):
        return (
            f"【{unresolved}｜第{page}页{region_meta}｜{note}】",
            MODE_REGION_UNRESOLVED,
        )

    fallback_content = overlay.get("fallback_content")
    machine_code_block = render_machine_code_safety_block(
        fallback_content,
        page=page,
        region_meta=region_meta,
        detached_note=note,
    )
    if machine_code_block:
        return machine_code_block, MODE_REGION_TEXT
    text = clean_markdown_text(nonempty_text_channel(fallback_content))
    strategy = spatial_render_strategy(fallback_content)
    if strategy == "COARSE_2D_ROWS":
        spatial = render_coarse_spatial_rows(fallback_content)
        if spatial:
            return (
                f"【未进入主结构流的{noun}文字识别开始｜第{page}页{region_meta}"
                f"｜二维布局粗略保留｜原始区域未进入Stage6主结构流，正文相对位置与结构关系未恢复】\n"
                f"{spatial}\n"
                f"【未进入主结构流的{noun}文字识别结束】",
                MODE_REGION_TEXT,
            )
    elif strategy == "COMPLEX_COMPACT":
        compact = render_complex_spatial_compact(fallback_content)
        if compact:
            return (
                f"【未进入主结构流的复杂{noun}开始｜第{page}页{region_meta}"
                f"｜原始区域未进入Stage6主结构流，正文相对位置与结构关系未恢复】\n"
                f"{compact}\n"
                f"【未进入主结构流的复杂{noun}结束】",
                MODE_REGION_TEXT,
            )
    if not text:
        return (
            f"【{noun}｜第{page}页{region_meta}｜OCR文本为空｜{note}】",
            MODE_REGION_TEXT,
        )
    return (
        f"【{start}｜第{page}页{region_meta}｜{note}】\n"
        f"{text}\n"
        f"【{end}】",
        MODE_REGION_TEXT,
    )


def neutralize_nested_markdown_headings(text: str) -> str:
    """Keep layout-parser content readable without creating document-level headings."""
    out: list[str] = []
    for line in str(text or "").splitlines():
        # Canonical/template sections are the only document headings in Stage10.2.
        # Provider-emitted Markdown headings remain visible as body text.
        out.append(re.sub(r"^\s{0,3}#{1,6}\s+", "", line))
    return "\n".join(out)


def render_page_fallback(record: dict[str, Any], page_overlay_by_task: dict[str, dict[str, Any]]) -> str:
    res = record.get("stage10_resolution") or {}
    tids = [str(x) for x in (res.get("fallback_task_ids") or []) if str(x)]
    page = record_page(record)
    mode = str(res.get("mode") or "")
    if not tids:
        if mode == MODE_PAGE_LAYOUT_FALLBACK:
            return f"【整页结构解析失败｜第{page}页｜解析结果缺失】"
        return f"【整页识别失败｜第{page}页｜OCR结果缺失】"

    ov = page_overlay_by_task.get(tids[0])
    if not ov:
        if mode == MODE_PAGE_LAYOUT_FALLBACK:
            return f"【整页结构解析失败｜第{page}页｜task={tids[0]}｜解析结果缺失】"
        return f"【整页识别失败｜第{page}页｜task={tids[0]}｜OCR结果缺失】"

    if mode == MODE_PAGE_LAYOUT_FALLBACK:
        # Prefer provider raw Markdown because it carries explicit reading order/table/formula
        # structure. Provider headings are neutralized so only canonical section titles become
        # Markdown headings in the final document.
        text = clean_markdown_text(raw_or_content(ov.get("fallback_content")))
        if not text:
            text = clean_markdown_text(nonempty_text_channel(ov.get("fallback_content")))
        text = clean_markdown_text(neutralize_nested_markdown_headings(text))
        if not text:
            return f"【整页结构解析失败｜第{page}页｜未恢复可靠结构化内容】"
        return (
            f"【整页结构解析开始｜第{page}页｜结构由布局解析器恢复】\n"
            f"{text}\n"
            f"【整页结构解析结束】"
        )

    text = clean_markdown_text(nonempty_text_channel(ov.get("fallback_content")))
    if not text:
        return f"【整页识别失败｜第{page}页｜未恢复可靠文本】"
    # OCR fallback is content inside the current canonical section, not a new Markdown heading.
    return (
        f"【整页识别开始｜第{page}页】\n"
        f"{text}\n"
        f"【整页识别结束】"
    )


def build_rendered_document(doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    records = [r for r in doc["records"] if isinstance(r, dict)]
    records_by_id = {str(r["record_id"]): r for r in records}

    # Global semantic order is section order + each section's canonical record_ids.
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for sec in doc["sections"]:
        for rid in sec.get("record_ids") or []:
            rid = str(rid)
            if rid not in seen:
                seen.add(rid)
                ordered_ids.append(rid)
    # Preserve any unexpected records deterministically at the end.
    for r in records:
        rid = str(r["record_id"])
        if rid not in seen:
            seen.add(rid)
            ordered_ids.append(rid)
    order_index = {rid: i for i, rid in enumerate(ordered_ids)}

    inline_plan = build_inline_plan(doc, order_index, records_by_id)
    replacement_anchor = inline_plan["replacement_anchor"]
    partial_before = inline_plan["partial_before"]
    partial_after = inline_plan["partial_after"]
    suppress_ids: set[str] = inline_plan["suppress_ids"]

    page_overlays = list((doc.get("fallback_overlays") or {}).get("page_fallbacks") or [])
    page_overlay_by_task = {str(x.get("task_id") or ""): x for x in page_overlays if isinstance(x, dict)}

    region_overlays = [
        x for x in ((doc.get("fallback_overlays") or {}).get("region_fallbacks") or [])
        if isinstance(x, dict)
    ]
    detached_region_overlays = [x for x in region_overlays if not x.get("source_native_record_id")]
    detached_regions_by_page: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for ov in detached_region_overlays:
        try:
            detached_regions_by_page[int(ov.get("page_number"))].append(ov)
        except Exception:
            continue
    for pn in detached_regions_by_page:
        detached_regions_by_page[pn].sort(
            key=lambda x: (
                float(((x.get("quality_gate_region") or {}).get("bbox") or {}).get("top", 10**9)),
                str(x.get("task_id") or ""),
            )
        )

    chunks: list[str] = []
    record_dispositions: dict[str, dict[str, Any]] = {}
    rendered_section_count = 0
    rendered_record_count = 0
    page_fallback_rendered = 0
    page_ocr_fallback_rendered = 0
    page_layout_fallback_rendered = 0
    page_fallback_duplicate_source_suppressed = 0
    rendered_page_fallback_task_ids: set[str] = set()
    region_text_rendered = 0
    region_unresolved_rendered = 0
    preserved_visual_rendered = 0
    table_rendered = 0
    paragraph_rendered = 0
    suppressed_duplicate_count = 0
    inline_replacement_count = 0
    inline_partial_supplement_count = 0
    detached_region_rendered_count = 0
    detached_region_rendered_task_ids: set[str] = set()
    detached_region_overlay_dispositions: dict[str, dict[str, Any]] = {}
    current_page_marker: tuple[int, ...] | None = None

    def emit_detached_regions_for_page(page_number: int, section_id: str) -> None:
        nonlocal region_text_rendered, region_unresolved_rendered, detached_region_rendered_count
        for ov in detached_regions_by_page.get(page_number, []):
            tid = str(ov.get("task_id") or "")
            if tid and tid in detached_region_rendered_task_ids:
                continue
            rendered, mode = render_detached_region_overlay(ov)
            if rendered:
                append_block(chunks, rendered)
            detached_region_rendered_count += 1
            if mode == MODE_REGION_UNRESOLVED:
                region_unresolved_rendered += 1
                disposition = "RENDERED_DETACHED_REGION_UNRESOLVED"
            else:
                region_text_rendered += 1
                disposition = "RENDERED_DETACHED_REGION_TEXT_ENRICHMENT"
            if tid:
                detached_region_rendered_task_ids.add(tid)
                detached_region_overlay_dispositions[tid] = {
                    "disposition": disposition,
                    "page_number": page_number,
                    "section_id": section_id,
                    "source_id": ov.get("source_id"),
                    "anchor_status": ov.get("anchor_status"),
                }

    for sec in doc["sections"]:
        if not isinstance(sec, dict):
            continue
        section_title = str(sec.get("section_title") or sec.get("section_id") or "未命名章节").strip()
        section_id = str(sec.get("section_id") or "")
        # Only canonical/template-aligned sections become Markdown headings.
        # Native paragraphs are never promoted to ## / ### based on numbering, length or typography.
        append_block(chunks, f"# {section_title}")
        rendered_section_count += 1
        current_page_marker = None
        first_native_paragraph_seen = False

        for rid_raw in sec.get("record_ids") or []:
            rid = str(rid_raw)
            record = records_by_id.get(rid)
            if not record:
                continue

            pages_tuple = tuple(record_pages(record))
            if pages_tuple and pages_tuple != current_page_marker:
                append_block(chunks, first_page_comment(record))
                for source_page in pages_tuple:
                    emit_detached_regions_for_page(source_page, section_id)
                current_page_marker = pages_tuple

            # Partial-only inline overlays may need to appear before the native paragraph.
            for ov in partial_before.get(rid, []):
                text = render_inline_partial_supplement(ov)
                if text:
                    append_block(chunks, text)
                    inline_partial_supplement_count += 1

            # Rich inline replacement is anchored at the earliest fully-contained record.
            if rid in replacement_anchor:
                text = render_inline_replacement(replacement_anchor[rid])
                if text:
                    append_block(chunks, text)
                    inline_replacement_count += 1

            if rid in suppress_ids:
                record_dispositions[rid] = {
                    "disposition": "SUPPRESSED_BY_INLINE_CONTEXT_REPLACEMENT",
                    "section_id": section_id,
                    "page_numbers": list(pages_tuple),
                }
                continue

            vis = visibility(record)
            if vis.startswith("suppressed_"):
                suppressed_duplicate_count += 1
                record_dispositions[rid] = {
                    "disposition": "SUPPRESSED_BY_CANONICAL_VISIBILITY",
                    "visibility": vis,
                    "section_id": section_id,
                    "page_numbers": list(pages_tuple),
                }
                continue

            rtype = str(record.get("record_type") or "")
            mode = record_mode(record)
            rendered = ""
            disposition = ""

            if mode in {MODE_PAGE_FALLBACK, MODE_PAGE_LAYOUT_FALLBACK}:
                # One PAGE fallback task may map to multiple native image_ref records on the
                # same physical page (for example, a scanned page composed of multiple images).
                # The canonical provenance may keep all source refs, but the LLM-ready document
                # must serialize the whole-page OCR result exactly once per fallback task.
                fallback_task_ids = [
                    str(x)
                    for x in ((record.get("stage10_resolution") or {}).get("fallback_task_ids") or [])
                    if str(x).strip()
                ]
                primary_task_id = fallback_task_ids[0] if fallback_task_ids else ""

                if primary_task_id and primary_task_id in rendered_page_fallback_task_ids:
                    page_fallback_duplicate_source_suppressed += 1
                    record_dispositions[rid] = {
                        "disposition": "SUPPRESSED_DUPLICATE_PAGE_FALLBACK_SOURCE",
                        "section_id": section_id,
                        "page_numbers": list(pages_tuple),
                        "resolution_mode": mode,
                        "record_type": rtype,
                        "fallback_task_ids": fallback_task_ids,
                    }
                    continue

                rendered = render_page_fallback(record, page_overlay_by_task)
                page_fallback_rendered += 1
                if mode == MODE_PAGE_LAYOUT_FALLBACK:
                    disposition = "RENDERED_PAGE_LAYOUT_FALLBACK"
                    page_layout_fallback_rendered += 1
                else:
                    disposition = "RENDERED_PAGE_OCR_FALLBACK"
                    page_ocr_fallback_rendered += 1
                if primary_task_id:
                    rendered_page_fallback_task_ids.add(primary_task_id)
            elif mode in {MODE_REGION_TEXT, MODE_REGION_UNRESOLVED, MODE_PRESERVED_VISUAL}:
                rendered = render_region_record(record)
                disposition = f"RENDERED_{mode}"
                if mode == MODE_REGION_TEXT:
                    region_text_rendered += 1
                elif mode == MODE_REGION_UNRESOLVED:
                    region_unresolved_rendered += 1
                else:
                    preserved_visual_rendered += 1
            elif mode in {MODE_INLINE_MEMBER, MODE_INLINE_COVERED}:
                # Normally these ids are already in suppress_ids. If not, keep them silent rather than
                # emitting duplicate standalone image placeholders.
                disposition = "SUPPRESSED_STANDALONE_INLINE_IMAGE_REF"
                record_dispositions[rid] = {
                    "disposition": disposition,
                    "section_id": section_id,
                    "page_numbers": list(pages_tuple),
                }
                continue
            elif rtype == "table_ref":
                rendered = render_table(record)
                disposition = "RENDERED_NATIVE_TABLE"
                table_rendered += 1
            elif rtype == "paragraph":
                text = clean_markdown_text(str(record.get("text") or ""))
                if not text:
                    disposition = "EMPTY_NATIVE_PARAGRAPH_SKIPPED"
                    record_dispositions[rid] = {
                        "disposition": disposition,
                        "section_id": section_id,
                        "page_numbers": list(pages_tuple),
                    }
                    continue
                # Conservative heading policy:
                # - only the canonical section title above is rendered as Markdown '#';
                # - every native paragraph remains ordinary body text;
                # - only the FIRST native paragraph may be suppressed when it is merely the
                #   same section heading in the PDF (e.g. "三、拟开展研究内容" vs
                #   canonical "第三章 拟展开研究内容"). Later matching text is preserved.
                is_first_native_paragraph = not first_native_paragraph_seen
                first_native_paragraph_seen = True
                if is_first_native_paragraph and heading_equivalent(text, section_title):
                    disposition = "SUPPRESSED_DUPLICATE_SECTION_HEADING"
                    suppressed_duplicate_count += 1
                    record_dispositions[rid] = {
                        "disposition": disposition,
                        "section_id": section_id,
                        "page_numbers": list(pages_tuple),
                    }
                    continue
                rendered = text
                disposition = "RENDERED_NATIVE_PARAGRAPH"
                paragraph_rendered += 1
            elif rtype == "image_ref":
                # A native image_ref without a more specific Stage10 resolution remains explicit.
                page = record_page(record)
                rendered = f"【图示内容｜第{page}页】"
                disposition = "RENDERED_GENERIC_IMAGE_PLACEHOLDER"
                preserved_visual_rendered += 1
            elif rtype == "vector_ref":
                # Vector/diagram evidence must never disappear merely because it has no text channel.
                page = record_page(record)
                rendered = f"【图形/向量内容｜第{page}页】"
                disposition = "RENDERED_GENERIC_VECTOR_PLACEHOLDER"
                preserved_visual_rendered += 1
            else:
                text = clean_markdown_text(str(record.get("text") or ""))
                if text:
                    rendered = text
                    disposition = "RENDERED_OTHER_TEXT_RECORD"
                else:
                    disposition = "UNSUPPORTED_EMPTY_RECORD_SKIPPED"
                    record_dispositions[rid] = {
                        "disposition": disposition,
                        "section_id": section_id,
                        "page_numbers": list(pages_tuple),
                    }
                    continue

            if rendered:
                append_block(chunks, rendered)
                rendered_record_count += 1
                record_dispositions[rid] = {
                    "disposition": disposition,
                    "section_id": section_id,
                    "page_numbers": list(pages_tuple),
                    "resolution_mode": mode,
                    "record_type": rtype,
                }

            for ov in partial_after.get(rid, []):
                text = render_inline_partial_supplement(ov)
                if text:
                    append_block(chunks, text)
                    inline_partial_supplement_count += 1

    # A page can contain source-only Stage7 regions but no Stage6 record that causes the
    # normal page loop to visit it. Serialize any such leftovers at the end under an
    # explicit unresolved-position supplement rather than guessing a reading-order anchor.
    remaining_detached = [
        ov for ov in detached_region_overlays
        if str(ov.get("task_id") or "") not in detached_region_rendered_task_ids
    ]
    if remaining_detached:
        append_block(chunks, "【未进入主结构流的区域识别补充｜正文相对位置未恢复】")
        for ov in sorted(remaining_detached, key=lambda x: (int(x.get("page_number", 0) or 0), str(x.get("task_id") or ""))):
            try:
                pn = int(ov.get("page_number"))
            except Exception:
                pn = 0
            if pn > 0:
                append_block(chunks, f"<!-- source-page: {pn} -->")
            emit_detached_regions_for_page(pn, "UNANCHORED_REGION_SUPPLEMENT")

    # Any unanchored inline overlays are appended under a clearly marked final supplement section.
    unanchored: list[dict[str, Any]] = []
    for ov in (doc.get("fallback_overlays") or {}).get("inline_contexts") or []:
        if not isinstance(ov, dict):
            continue
        tid = str(ov.get("task_id") or "")
        disp = inline_plan["overlay_dispositions"].get(tid) or {}
        if disp.get("mode") == "UNANCHORED_SUPPLEMENT":
            unanchored.append(ov)
    if unanchored:
        # Technical supplement marker only; do not invent another document section heading.
        append_block(chunks, "【局部识别补充】")
        for ov in unanchored:
            text = render_inline_partial_supplement(ov)
            if text:
                append_block(chunks, text)
                inline_partial_supplement_count += 1

    markdown = "\n".join(chunks)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"

    # Coverage / integrity checks.
    all_record_ids = set(records_by_id)
    accounted_record_ids = set(record_dispositions)
    unaccounted = sorted(all_record_ids - accounted_record_ids)

    summary = doc.get("summary") or {}
    expected_page = int(summary.get("page_fallback_count", 0))
    expected_page_ocr = int(summary.get("page_ocr_fallback_count", expected_page))
    expected_page_layout = int(summary.get("page_layout_fallback_count", 0))
    expected_region = int(summary.get("region_fallback_count", 0))
    expected_detached_region = int(summary.get("detached_region_fallback_count", 0))
    expected_inline = int(summary.get("inline_context_count", 0))
    expected_terminal = int(summary.get("terminal_preserve_count", 0))
    expected_failures = int(summary.get("pipeline_failure_count", 0))

    overlay_disp = inline_plan["overlay_dispositions"]
    inline_accounted = sum(1 for x in overlay_disp.values() if x.get("mode") in {
        INLINE_REPLACEMENT_NOTE, INLINE_PARTIAL_NOTE, "UNANCHORED_SUPPLEMENT"
    })

    validation_errors: list[str] = []
    if unaccounted:
        validation_errors.append(f"unaccounted records: {len(unaccounted)}")
    if page_fallback_rendered != expected_page:
        validation_errors.append(f"PAGE fallback rendered={page_fallback_rendered}, expected={expected_page}")
    if page_ocr_fallback_rendered != expected_page_ocr:
        validation_errors.append(
            f"PAGE OCR fallback rendered={page_ocr_fallback_rendered}, expected={expected_page_ocr}"
        )
    if page_layout_fallback_rendered != expected_page_layout:
        validation_errors.append(
            f"PAGE layout fallback rendered={page_layout_fallback_rendered}, expected={expected_page_layout}"
        )
    if region_text_rendered + region_unresolved_rendered != expected_region:
        validation_errors.append(
            f"REGION rendered={region_text_rendered + region_unresolved_rendered}, expected={expected_region}"
        )
    if detached_region_rendered_count != expected_detached_region:
        validation_errors.append(
            f"detached REGION rendered={detached_region_rendered_count}, expected={expected_detached_region}"
        )
    if region_unresolved_rendered != expected_terminal:
        validation_errors.append(
            f"terminal region placeholders={region_unresolved_rendered}, expected={expected_terminal}"
        )
    if inline_accounted != expected_inline:
        validation_errors.append(f"INLINE overlays accounted={inline_accounted}, expected={expected_inline}")
    if expected_failures != 0:
        validation_errors.append(f"canonical document contains pipeline failures={expected_failures}")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "substage": SUBSTAGE,
        "name": "llm_ready_renderer",
        "version": VERSION,
        "artifact_role": ARTIFACT_ROLE,
        "source_file": doc.get("source_file"),
        "page_count": doc.get("page_count"),
        "status": "PASS" if not validation_errors else "FAIL",
        "principles": [
            "Render only from Stage10.1 canonical content; do not re-open the PDF and do not run OCR.",
            "Use canonical section order and record order as the semantic backbone.",
            "Only canonical/template-aligned section titles are emitted as Markdown headings; native paragraphs are never promoted to subheadings by numbering, length, font, or geometry heuristics.",
            "Whole-page OCR fallback replaces PAGE_FALLBACK_SOURCE records only on OCR_REQUIRED pages.",
            "Whole-page layout fallback replaces PAGE_LAYOUT_FALLBACK_SOURCE records only on LAYOUT_FALLBACK_REQUIRED pages and remains explicitly labeled as structure recovery.",
            "A whole-page fallback is serialized once per fallback task even when multiple native source records on that page share the same task.",
            "Region OCR is explicit enrichment; RapidOCR line-box geometry is preserved internally, while LLM-facing Markdown uses ordinary text for low-risk regions, coarse row grouping for manageable 2D regions, and bounded compact labels for dense complex diagrams; coordinates and semantic relations are never invented in Markdown.",
            "All injected fallback content uses explicit begin/end semantic boundaries so downstream LLMs do not infer scope from blank lines.",
            "Terminal-preserved regions remain explicit placeholders instead of synthesized text.",
            "Structured tables are serialized as plain readable text, not Markdown grid tables.",
            "Inline-context overlays may replace only fully-contained native fragments; partial overlaps remain native and receive an explicit supplement.",
            "Canonical visibility suppression is respected to avoid table/text duplication.",
            "Ground Truth and benchmark labels are not used at runtime.",
        ],
        "summary": {
            "section_count": rendered_section_count,
            "canonical_record_count": len(records),
            "record_disposition_count": len(record_dispositions),
            "rendered_record_count": rendered_record_count,
            "paragraph_rendered_count": paragraph_rendered,
            "table_rendered_count": table_rendered,
            "page_fallback_rendered_count": page_fallback_rendered,
            "page_ocr_fallback_rendered_count": page_ocr_fallback_rendered,
            "page_layout_fallback_rendered_count": page_layout_fallback_rendered,
            "page_fallback_duplicate_source_suppressed_count": page_fallback_duplicate_source_suppressed,
            "region_text_enrichment_rendered_count": region_text_rendered,
            "region_unresolved_placeholder_count": region_unresolved_rendered,
            "detached_region_rendered_count": detached_region_rendered_count,
            "preserved_visual_placeholder_count": preserved_visual_rendered,
            "inline_replacement_count": inline_replacement_count,
            "inline_partial_supplement_count": inline_partial_supplement_count,
            "inline_overlay_accounted_count": inline_accounted,
            "suppressed_duplicate_count": suppressed_duplicate_count,
            "unaccounted_record_count": len(unaccounted),
            "markdown_char_count": len(markdown),
            "ground_truth_used": False,
        },
        "expected_from_canonical": {
            "page_fallback_count": expected_page,
            "page_ocr_fallback_count": expected_page_ocr,
            "page_layout_fallback_count": expected_page_layout,
            "region_fallback_count": expected_region,
            "detached_region_fallback_count": expected_detached_region,
            "inline_context_count": expected_inline,
            "terminal_preserve_count": expected_terminal,
            "pipeline_failure_count": expected_failures,
        },
        "inline_overlay_dispositions": overlay_disp,
        "detached_region_overlay_dispositions": detached_region_overlay_dispositions,
        "validation": {
            "pass": not validation_errors,
            "errors": validation_errors,
            "unaccounted_record_ids": unaccounted,
        },
        "record_dispositions": record_dispositions,
    }
    return markdown, manifest


# -------------------------------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Stage 10.2: render LLM-ready Markdown from Stage10.1 canonical document")
    ap.add_argument("--canonical", required=True, help="Stage10.1 canonical_document.json")
    ap.add_argument("--output", required=True, help="output directory")
    ap.add_argument("--validate-only", action="store_true", help="validate and render in-memory only; do not write final files")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    canonical_path = Path(args.canonical)
    output_dir = Path(args.output)

    doc = load_json(canonical_path)
    validate_canonical(doc)
    markdown, manifest = build_rendered_document(doc)

    print("=" * 120)
    print(f"Stage 10.2 LLM-ready Renderer | version={VERSION} | source={doc.get('source_file')}")
    print("=" * 120)
    s = manifest["summary"]
    print(f"Sections            | {s['section_count']}")
    print(f"Canonical records   | {s['canonical_record_count']}")
    print(f"Accounted records   | {s['record_disposition_count']}/{s['canonical_record_count']}")
    print(f"Rendered records    | {s['rendered_record_count']}")
    print(f"Paragraphs          | {s['paragraph_rendered_count']}")
    print(f"Tables              | {s['table_rendered_count']}")
    print(f"PAGE fallback       | {s['page_fallback_rendered_count']}")
    print(f"  OCR               | {s['page_ocr_fallback_rendered_count']}")
    print(f"  Layout            | {s['page_layout_fallback_rendered_count']}")
    print(f"PAGE source dedup   | {s['page_fallback_duplicate_source_suppressed_count']}")
    print(f"REGION enrichment   | {s['region_text_enrichment_rendered_count']}")
    print(f"REGION unresolved   | {s['region_unresolved_placeholder_count']}")
    print(f"REGION detached     | {s['detached_region_rendered_count']}")
    print(f"Preserved visuals   | {s['preserved_visual_placeholder_count']}")
    print(f"INLINE replacement  | {s['inline_replacement_count']}")
    print(f"INLINE supplement   | {s['inline_partial_supplement_count']}")
    print(f"INLINE accounted    | {s['inline_overlay_accounted_count']}")
    print(f"Suppressed duplicate| {s['suppressed_duplicate_count']}")
    print(f"Markdown chars      | {s['markdown_char_count']}")
    print(f"Ground truth        | NOT USED")
    print(f"Validation          | {'PASS' if manifest['validation']['pass'] else 'FAIL'}")

    if manifest["validation"]["errors"]:
        for err in manifest["validation"]["errors"]:
            print(f"  ERROR              | {err}")

    if args.validate_only:
        print("Write final         | NO")
        print("Next                | rerun without --validate-only")
        print("=" * 120)
        return 0 if manifest["validation"]["pass"] else 2

    if not manifest["validation"]["pass"]:
        print("Write final         | NO (validation failed)")
        print("=" * 120)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "llm_ready.md"
    manifest_path = output_dir / "render_manifest.json"
    md_path.write_text(markdown, encoding="utf-8")

    manifest["inputs"] = {
        "canonical_document": str(canonical_path),
        "canonical_sha256": sha256_file(canonical_path),
    }
    manifest["outputs"] = {
        "llm_ready_markdown": str(md_path),
        "render_manifest": str(manifest_path),
    }
    write_json(manifest_path, manifest)

    print(f"Markdown            | {md_path}")
    print(f"Manifest            | {manifest_path}")
    print("Write final         | YES")
    print("Next                | Stage 10.3 chunk builder")
    print("=" * 120)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
