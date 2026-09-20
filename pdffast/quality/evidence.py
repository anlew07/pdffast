#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stage 7 — Native Evidence Manifest v0.3.0

职责：
- 只汇总 Stage1~6 已有证据；
- 建立统一 page / region ledger；
- 对 Stage1 raw words 做“去向记账”（accounting）；
- 以 Stage6 normalized_text_flow.json 作为唯一最终机器 authority；
- readable_final.md 仅是人工视图，不参与 Stage7 计算；
- 对 Stage1 raw evidence 做“最终去向记账”，只把 Stage6 结束后仍未被最终 flow 表示的内容保留为 unresolved；
- 输出 Coverage Manifest + provenance；
- 不重新打开 PDF；
- 不做 OCR / Layout / Vision；
- 不做 GOOD / BAD / FALLBACK 质量裁决；
- 不修改 Stage1~6 原产物。

这里的 ACCOUNTED_* / ACCOUNTED_FINAL_FLOW 只表示“已被 native pipeline 最终结果表示/归账”，
绝不等于“内容质量正确”。真正的 Quality Gate 放在 Stage8。

Stage7 的原则：
- Stage1~5 的历史异常可以保留在 provenance 中，但不等于最终异常；
- Stage6 final flow 已经表示的 raw evidence 只做 accounting，不再进入 Stage8 unresolved；
- 只有 Stage6 结束后仍无法被最终机器结果解释/表示的 native evidence 才进入 Stage8 候选池；
- Stage7 不修复任何内容，也不把 readable_final.md 当作数据源。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterable


STAGE = 7
VERSION = "0.3.2"
MANIFEST_SCHEMA_VERSION = "1.2"

ACCOUNTED_TEXT = "ACCOUNTED_TEXT"
ACCOUNTED_TABLE = "ACCOUNTED_TABLE"
ACCOUNTED_NOISE = "ACCOUNTED_NOISE"
ACCOUNTED_FINAL_FLOW = "ACCOUNTED_FINAL_FLOW"
UNACCOUNTED_NATIVE = "UNACCOUNTED_NATIVE"
NON_TEXT_UNASSESSED = "NON_TEXT_UNASSESSED"
UNACCOUNTED_TABLE_REGION = "UNACCOUNTED_TABLE_REGION"
QUARANTINED_STRUCTURE_EVIDENCE = "QUARANTINED_STRUCTURE_EVIDENCE"


# =============================================================================
# I/O
# =============================================================================


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON 不存在: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层不是 object: {path}")
    return value


def load_snapshot(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot 不存在: {path}")

    meta: dict[str, Any] | None = None
    pages: dict[int, dict[str, Any]] = {}

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Snapshot 第 {line_no} 行 JSON 无效") from exc

            if not isinstance(item, dict):
                continue

            record_type = item.get("record_type")
            if record_type == "meta":
                if meta is not None:
                    raise ValueError("Snapshot 出现多个 meta record")
                meta = item
                continue

            if record_type == "page" or "page_number" in item:
                try:
                    page_number = int(item["page_number"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Snapshot 第 {line_no} 行缺少有效 page_number") from exc
                if page_number in pages:
                    raise ValueError(f"Snapshot 页面重复: {page_number}")
                pages[page_number] = item

    if meta is None:
        raise ValueError("Snapshot 缺少 meta record")

    return meta, pages


def index_pages(data: dict[str, Any], key: str = "pages") -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    values = data.get(key, [])
    if not isinstance(values, list):
        return result
    for item in values:
        if not isinstance(item, dict):
            continue
        try:
            page_number = int(item["page_number"])
        except (KeyError, TypeError, ValueError):
            continue
        result[page_number] = item
    return result


# =============================================================================
# Geometry
# =============================================================================


def normalize_bbox(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        try:
            bbox = {
                "x0": float(value["x0"]),
                "top": float(value["top"]),
                "x1": float(value["x1"]),
                "bottom": float(value["bottom"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    elif isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            bbox = {
                "x0": float(value[0]),
                "top": float(value[1]),
                "x1": float(value[2]),
                "bottom": float(value[3]),
            }
        except (TypeError, ValueError):
            return None
    else:
        return None

    if not all(math.isfinite(v) for v in bbox.values()):
        return None
    if bbox["x1"] <= bbox["x0"] or bbox["bottom"] <= bbox["top"]:
        return None
    return bbox


def bbox_area(bbox: dict[str, float] | None) -> float:
    if bbox is None:
        return 0.0
    return max(0.0, bbox["x1"] - bbox["x0"]) * max(0.0, bbox["bottom"] - bbox["top"])


def bbox_intersection_area(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    if a is None or b is None:
        return 0.0
    x0 = max(a["x0"], b["x0"])
    top = max(a["top"], b["top"])
    x1 = min(a["x1"], b["x1"])
    bottom = min(a["bottom"], b["bottom"])
    if x1 <= x0 or bottom <= top:
        return 0.0
    return (x1 - x0) * (bottom - top)


def bbox_overlap_coverage(inner: dict[str, float] | None, outer: dict[str, float] | None) -> float:
    area = bbox_area(inner)
    if area <= 0:
        return 0.0
    return bbox_intersection_area(inner, outer) / area


def bbox_center_inside(inner: dict[str, float] | None, outer: dict[str, float] | None, tol: float = 1.0) -> bool:
    if inner is None or outer is None:
        return False
    cx = (inner["x0"] + inner["x1"]) / 2.0
    cy = (inner["top"] + inner["bottom"]) / 2.0
    return (
        outer["x0"] - tol <= cx <= outer["x1"] + tol
        and outer["top"] - tol <= cy <= outer["bottom"] + tol
    )


def bbox_matches(inner: dict[str, float] | None, outer: dict[str, float] | None, min_coverage: float = 0.55) -> bool:
    return bbox_center_inside(inner, outer) or bbox_overlap_coverage(inner, outer) >= min_coverage


def bbox_union(values: Iterable[dict[str, float] | None]) -> dict[str, float] | None:
    items = [item for item in values if item is not None]
    if not items:
        return None
    return {
        "x0": min(item["x0"] for item in items),
        "top": min(item["top"] for item in items),
        "x1": max(item["x1"] for item in items),
        "bottom": max(item["bottom"] for item in items),
    }


def word_bbox(word: dict[str, Any]) -> dict[str, float] | None:
    return normalize_bbox(word)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_accounting_text(value: Any) -> str:
    """Normalize text only for evidence accounting, never for output rewriting."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return "".join(ch for ch in text if ch.isalnum())


def extract_text(item: dict[str, Any]) -> str:
    for key in (
        "table_text",
        "normalized_text",
        "text",
        "content",
        "plain_text",
        "markdown_text",
        "value",
    ):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return clean_text(value)
    return ""


def extract_any_bbox(item: dict[str, Any]) -> dict[str, float] | None:
    for key in ("bbox", "source_bbox", "page_bbox", "original_bbox"):
        bbox = normalize_bbox(item.get(key))
        if bbox is not None:
            return bbox
    return None


def stage6_final_text_evidence_index(
    normalized: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    """
    Build page-level text evidence from Stage6 final machine artifact only.

    Authority contract:
    - paragraph: normalized_text_flow.records[].text
    - table: visible/materialized table_ref.records[].table_text
    - readable_final.md is deliberately excluded; it is a human-readable view only.

    Paragraph records may span multiple source pages. The same logical paragraph text is
    indexed on every source page for raw-evidence accounting; this does not rewrite text.
    """
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for index, record in enumerate(normalized.get("records", [])):
        if not isinstance(record, dict):
            continue

        record_type = str(record.get("record_type") or "")
        evidence_id = record.get("record_id") or f"normalized_record_{index:06d}"

        if record_type == "paragraph":
            text = extract_text(record)
            if not text:
                continue
            pages: list[int] = []
            for value in record.get("source_pages", []):
                try:
                    pages.append(int(value))
                except (TypeError, ValueError):
                    continue
            for page_number in sorted(set(pages)):
                result[page_number].append(
                    {
                        "source": "stage6.normalized_final_paragraph",
                        "evidence_id": evidence_id,
                        "record_type": record_type,
                        "text": text,
                        "normalized_text": normalize_accounting_text(text),
                        "bbox": None,
                    }
                )
            continue

        if record_type != "table_ref":
            continue

        # suppressed_duplicate 已由 paragraph authority 表示；unresolved table 没有
        # 可作为最终内容 authority 的 table text。
        visibility = str(record.get("effective_visibility") or "")
        materialization = str(record.get("materialization_status") or "")
        if visibility != "visible":
            continue
        if materialization not in {"materialized", "materialized_empty"}:
            continue

        text = str(record.get("table_text") or "").strip()
        if not text:
            continue

        try:
            page_number = int(record["source_page"])
        except (KeyError, TypeError, ValueError):
            continue

        result[page_number].append(
            {
                "source": "stage6.normalized_final_table",
                "evidence_id": evidence_id,
                "record_type": record_type,
                "source_table_index": record.get("source_table_index"),
                "text": text,
                "normalized_text": normalize_accounting_text(text),
                "bbox": extract_any_bbox(record),
            }
        )

    # Same-page aggregate supports a raw word that was split across adjacent final records.
    # Because aggregate evidence has no geometry, matching uses the stricter text-only path.
    for page_number, items in list(result.items()):
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            key = (
                str(item.get("evidence_id") or ""),
                str(item.get("normalized_text") or ""),
            )
            if not key[1] or key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        aggregate_text = " ".join(
            str(item.get("text") or "")
            for item in deduped
            if item.get("text")
        )
        if aggregate_text:
            deduped.append(
                {
                    "source": "stage6.normalized_final_page_aggregate",
                    "evidence_id": f"p{page_number:04d}_final_flow_aggregate",
                    "record_type": "page_aggregate",
                    "text": aggregate_text,
                    "normalized_text": normalize_accounting_text(aggregate_text),
                    "bbox": None,
                }
            )
        result[page_number] = deduped

    return result


def stage6_final_word_ownership_index(
    normalized: dict[str, Any],
) -> dict[int, dict[int, dict[str, Any]]]:
    """
    从 Stage6 最终 paragraph provenance 中建立 source_word_index 直接归账索引。

    这用于处理一个 Stage1 raw word 同时混入正文字符与已确认噪声字符的情况：
    Stage6 已经通过 char geometry 保留正文、剔除噪声后，最终 paragraph 仍会保留
    source_word_indices。Stage7 应尊重这一最终 provenance，而不是因为原始 word bbox/text
    较大就再次把它判成 residual。
    """
    result: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)

    for record_index, record in enumerate(normalized.get("records", [])):
        if not isinstance(record, dict):
            continue
        if str(record.get("record_type") or "") != "paragraph":
            continue

        evidence_id = record.get("record_id") or f"normalized_record_{record_index:06d}"
        fragments = record.get("source_fragment_geometry", [])
        if not isinstance(fragments, list):
            continue

        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            try:
                page_number = int(fragment["page_number"])
            except (KeyError, TypeError, ValueError):
                continue
            bbox = normalize_bbox(fragment.get("bbox"))
            indices = fragment.get("source_word_indices", [])
            if not isinstance(indices, list):
                continue
            for value in indices:
                if not isinstance(value, int) or value < 0:
                    continue
                result[page_number][value] = {
                    "evidence_id": evidence_id,
                    "record_type": "paragraph",
                    "source": "stage6.normalized_final_paragraph_source_word",
                    "fragment_bbox": bbox,
                }

    return dict(result)


def stage6_final_table_bboxes(
    normalized: dict[str, Any],
) -> dict[int, list[dict[str, float]]]:
    """Visible/materialized Stage6 final tables that can account raw Stage1 words."""
    result: dict[int, list[dict[str, float]]] = defaultdict(list)
    for record in normalized.get("records", []):
        if not isinstance(record, dict) or record.get("record_type") != "table_ref":
            continue
        if str(record.get("effective_visibility") or "") != "visible":
            continue
        if str(record.get("materialization_status") or "") not in {
            "materialized",
            "materialized_empty",
        }:
            continue
        bbox = extract_any_bbox(record)
        if bbox is None:
            continue
        try:
            page_number = int(record["source_page"])
        except (KeyError, TypeError, ValueError):
            continue
        result[page_number].append(bbox)
    return dict(result)


def validate_stage6_final_contract(normalized: dict[str, Any]) -> None:
    """Stage7 only accepts the finalized Stage6 machine artifact, never the readable view."""
    if normalized.get("artifact_role") != "native_parser_final_flow":
        raise ValueError(
            "Stage7 需要 Stage6 最终机器结果：artifact_role 必须为 native_parser_final_flow"
        )

    finalization = normalized.get("stage66_table_finalization", {})
    if not isinstance(finalization, dict) or finalization.get("status") != "completed":
        raise ValueError(
            "Stage7 需要 Stage6.6 table finalization=completed；请先使用新版 Stage6 产物"
        )

    policy = normalized.get("text_policy", {})
    if not isinstance(policy, dict) or policy.get("readable_renderer_mutates_content") is not False:
        raise ValueError(
            "Stage6 final contract 无效：readable renderer 必须是纯展示层"
        )

def sequence_match_stats(query: str, candidate: str) -> tuple[float, float]:
    matcher = SequenceMatcher(None, query, candidate, autojunk=False)
    ratio = matcher.ratio()
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / len(query) if query else 0.0
    return ratio, coverage


def best_partial_sequence_match(query: str, candidate: str) -> dict[str, Any]:
    """Return a local fuzzy match of query inside a longer same-page candidate."""
    if not query or not candidate:
        return {"ratio": 0.0, "query_coverage": 0.0, "window": ""}

    if query in candidate:
        return {"ratio": 1.0, "query_coverage": 1.0, "window": query}

    qlen = len(query)
    if len(candidate) <= qlen + 2:
        ratio, coverage = sequence_match_stats(query, candidate)
        return {"ratio": ratio, "query_coverage": coverage, "window": candidate}

    # SequenceMatcher matching blocks give good anchors for the likely local
    # position. Around each anchor, test a small deterministic family of windows.
    anchor_matcher = SequenceMatcher(None, query, candidate, autojunk=False)
    anchors = anchor_matcher.get_matching_blocks()
    shift_limit = min(8, max(2, qlen // 4))
    length_deltas = sorted({-4, -2, 0, 2, 4, max(-6, -(qlen // 5)), min(6, qlen // 5)})

    best = {"ratio": 0.0, "query_coverage": 0.0, "window": ""}
    for block in anchors:
        predicted_start = block.b - block.a
        for shift in range(-shift_limit, shift_limit + 1):
            start = max(0, predicted_start + shift)
            for delta in length_deltas:
                length = max(4, qlen + delta)
                end = min(len(candidate), start + length)
                if end - start < 4:
                    continue
                window = candidate[start:end]
                ratio, coverage = sequence_match_stats(query, window)
                if (ratio, coverage) > (best["ratio"], best["query_coverage"]):
                    best = {
                        "ratio": ratio,
                        "query_coverage": coverage,
                        "window": window,
                    }
    return best


def geometry_supports_final_flow_accounting(
    raw_bbox: dict[str, float] | None,
    evidence_bbox: dict[str, float] | None,
) -> bool:
    if raw_bbox is None or evidence_bbox is None:
        return False
    return (
        bbox_intersection_area(raw_bbox, evidence_bbox) > 0.0
        or bbox_matches(raw_bbox, evidence_bbox, min_coverage=0.20)
        or bbox_matches(evidence_bbox, raw_bbox, min_coverage=0.20)
    )


def match_raw_word_to_final_flow(
    raw_text: str,
    raw_bbox: dict[str, float] | None,
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Match a Stage1 raw native text object against the Stage6 final machine flow.

    This is provenance accounting, not repair and not quality judgement. Thresholds are intentionally
    conservative: geometry-supported matches may be moderately fuzzy; text-only
    matches must be very strong.
    """
    query = normalize_accounting_text(raw_text)
    if len(query) < 6:
        return None

    best: dict[str, Any] | None = None

    for evidence in evidence_items:
        candidate = str(evidence.get("normalized_text") or "")
        if not candidate:
            continue

        stats = best_partial_sequence_match(query, candidate)
        geometry_support = geometry_supports_final_flow_accounting(raw_bbox, evidence.get("bbox"))

        qlen = len(query)
        if geometry_support:
            min_ratio = 0.88 if qlen < 8 else 0.82
            min_coverage = 0.82 if qlen < 8 else 0.78
        else:
            min_ratio = 0.96 if qlen < 8 else 0.92
            min_coverage = 0.90 if qlen < 8 else 0.86

        accepted = (
            stats["ratio"] >= min_ratio
            and stats["query_coverage"] >= min_coverage
        )
        candidate_result = {
            "accepted": accepted,
            "method": "stage6_final_flow_accounting",
            "evidence_source": evidence.get("source"),
            "evidence_id": evidence.get("evidence_id"),
            "record_type": evidence.get("record_type"),
            "similarity": round(float(stats["ratio"]), 6),
            "query_coverage": round(float(stats["query_coverage"]), 6),
            "geometry_support": geometry_support,
            "matched_text_preview": str(stats.get("window") or "")[:240],
        }

        if best is None or (
            candidate_result["accepted"],
            candidate_result["similarity"],
            candidate_result["query_coverage"],
        ) > (
            best["accepted"],
            best["similarity"],
            best["query_coverage"],
        ):
            best = candidate_result

    if best and best.get("accepted"):
        return best
    return None


# =============================================================================
# Upstream validation / indexes
# =============================================================================


def validate_inputs(
    snapshot_meta: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    inputs: dict[str, dict[str, Any]],
) -> tuple[str, int]:
    source_file = str(snapshot_meta.get("source_file") or "")
    if not source_file:
        raise ValueError("Snapshot meta 缺少 source_file")

    try:
        page_count = int(snapshot_meta["page_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Snapshot meta 缺少有效 page_count") from exc

    expected = set(range(1, page_count + 1))
    if set(snapshot_pages) != expected:
        raise ValueError(
            "Snapshot pages 不完整: "
            f"missing={sorted(expected - set(snapshot_pages))}, "
            f"extra={sorted(set(snapshot_pages) - expected)}"
        )

    for name, data in inputs.items():
        if not isinstance(data, dict):
            continue
        value = data.get("source_file")
        if value and str(value) != source_file:
            raise ValueError(f"{name} source_file 不一致: {value} != {source_file}")
        count = data.get("page_count")
        if count is not None:
            try:
                count_int = int(count)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} page_count 无效: {count}") from exc
            if count_int != page_count:
                raise ValueError(f"{name} page_count 不一致: {count_int} != {page_count}")

    return source_file, page_count


def stage4_validation_index(structure: dict[str, Any]) -> dict[int, dict[str, Any]]:
    validation = structure.get("validation", {})
    if not isinstance(validation, dict):
        return {}
    return index_pages(validation)


def stage5_page_table_indices(stage5: dict[str, Any]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = defaultdict(set)
    for page in stage5.get("pages", []):
        if not isinstance(page, dict):
            continue
        try:
            page_number = int(page["page_number"])
        except (KeyError, TypeError, ValueError):
            continue
        for item in page.get("items", []):
            if not isinstance(item, dict) or item.get("type") != "table":
                continue
            index = item.get("table_index")
            if isinstance(index, int):
                result[page_number].add(index)
    return result


def stage5_logical_table_index(stage5: dict[str, Any]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    result: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for logical in stage5.get("cross_page_logical_tables", []):
        if not isinstance(logical, dict):
            continue
        group_id = logical.get("group_id")
        partial_merge_count = int(logical.get("partial_merge_count", 0) or 0)
        for fragment in logical.get("source_fragments", []):
            if not isinstance(fragment, dict):
                continue
            try:
                key = (int(fragment["page_number"]), int(fragment["table_index"]))
            except (KeyError, TypeError, ValueError):
                continue
            result[key].append(
                {
                    "group_id": group_id,
                    "block_id": fragment.get("block_id"),
                    "partial_merge_count": partial_merge_count,
                    "source_pages": logical.get("source_pages", []),
                    "merged_row_count": logical.get("merged_row_count", 0),
                    "footer_removed_count": logical.get("footer_removed_count", 0),
                }
            )
    return result


def stage5_boundary_index(stage5: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in stage5.get("cross_page_boundary_results", []):
        if not isinstance(item, dict):
            continue
        pages: set[int] = set()
        for key in ("from", "to"):
            ref = item.get(key)
            if isinstance(ref, dict):
                try:
                    pages.add(int(ref["page_number"]))
                except (KeyError, TypeError, ValueError):
                    pass
        compact = {
            "relation": item.get("relation"),
            "status": item.get("status"),
            "from": item.get("from"),
            "to": item.get("to"),
        }
        for page_number in pages:
            result[page_number].append(compact)
    return result


def normalized_non_text_index(normalized: dict[str, Any]) -> tuple[dict[tuple[int, str], list[dict[str, Any]]], dict[tuple[int, int], list[dict[str, Any]]]]:
    by_block: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    by_table: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)

    for record in normalized.get("records", []):
        if not isinstance(record, dict):
            continue
        if record.get("record_type") == "paragraph":
            continue
        try:
            page_number = int(record["source_page"])
        except (KeyError, TypeError, ValueError):
            continue

        for block_key in ("block_id", "source_block_id"):
            block_id = record.get(block_key)
            if block_id:
                by_block[(page_number, str(block_id))].append(record)

        table_index = record.get("source_table_index")
        if isinstance(table_index, int):
            by_table[(page_number, table_index)].append(record)

    return by_block, by_table


def auto_remove_noise_occurrences(noise: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for candidate in noise.get("noise_candidates", []):
        if not isinstance(candidate, dict) or candidate.get("action") != "auto_remove":
            continue
        for occurrence in candidate.get("occurrences", []):
            if not isinstance(occurrence, dict):
                continue
            try:
                page_number = int(occurrence["page_number"])
            except (KeyError, TypeError, ValueError):
                continue
            bbox = normalize_bbox(occurrence.get("bbox"))
            if bbox is None:
                continue
            result[page_number].append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "type": candidate.get("type"),
                    "subtype": candidate.get("subtype"),
                    "text": clean_text(occurrence.get("text") or candidate.get("text")),
                    "bbox": bbox,
                }
            )
    return result


def reading_excluded_noise_regions(reading_page: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in reading_page.get("excluded_noise_blocks", []):
        if not isinstance(item, dict):
            continue
        bbox = normalize_bbox(item.get("bbox"))
        if bbox is None:
            continue
        result.append(
            {
                "bbox": bbox,
                "block_id": item.get("block_id"),
                "source_block_id": item.get("source_block_id"),
                "candidate_types": item.get("candidate_types", []),
                "source": "stage6.2_excluded_noise_block",
            }
        )
    return result


# =============================================================================
# Word accounting
# =============================================================================


def word_matches_exact_noise(word: dict[str, Any], occurrence: dict[str, Any]) -> bool:
    word_text = clean_text(word.get("text"))
    noise_text = clean_text(occurrence.get("text"))
    if not word_text or not noise_text or word_text != noise_text:
        return False
    return bbox_matches(word_bbox(word), occurrence.get("bbox"), min_coverage=0.45)


def account_words(
    raw_page: dict[str, Any],
    paragraphs: list[dict[str, Any]],
    layout_container_bboxes: list[dict[str, float]],
    data_table_bboxes: list[dict[str, float]],
    noise_occurrences: list[dict[str, Any]],
    excluded_noise_regions: list[dict[str, Any]],
    image_bboxes: list[dict[str, float]],
    stage6_final_evidence: list[dict[str, Any]],
    stage6_final_word_ownership: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    paragraph_bboxes = [
        bbox for item in paragraphs
        if isinstance(item, dict)
        and (bbox := normalize_bbox(item.get("bbox"))) is not None
    ]

    words = raw_page.get("words", [])
    if not isinstance(words, list):
        words = []

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    unaccounted_inside_image = 0
    historical_residual_count = 0
    valid_count = 0

    for word_index, word in enumerate(words):
        if not isinstance(word, dict):
            continue
        text = clean_text(word.get("text"))
        bbox = word_bbox(word)
        if not text or bbox is None:
            continue

        valid_count += 1
        status: str
        source: str

        # Stage6 已明确排除的 noise block 是最强事实证据。
        if any(bbox_matches(bbox, item.get("bbox"), 0.55) for item in excluded_noise_regions):
            status = ACCOUNTED_NOISE
            source = "stage6.2_excluded_noise_block"

        # Stage6.1 auto_remove occurrence：必须文本精确匹配，避免大 watermark bbox
        # 把其下方正常正文整块误记为 noise。
        elif any(word_matches_exact_noise(word, item) for item in noise_occurrences):
            status = ACCOUNTED_NOISE
            source = "stage6.1_auto_remove_exact_occurrence"

        # final Stage6 paragraph 是最终 native text accounting 依据。
        elif any(bbox_matches(bbox, pb, 0.50) for pb in paragraph_bboxes):
            status = ACCOUNTED_TEXT
            source = "stage6.3_final_paragraph"

        # layout_container 使用 Stage1 extracted_data 作为正文 authority；
        # 其中 raw native word 即使被 logical 去重，也已被 text authority 表示。
        elif any(bbox_matches(bbox, lb, 0.50) for lb in layout_container_bboxes):
            status = ACCOUNTED_TEXT
            source = "stage6.3_layout_container_authority"

        # data table 内 raw word 由 Stage5/Stage6 table representation 归账。
        elif any(bbox_matches(bbox, tb, 0.50) for tb in data_table_bboxes):
            status = ACCOUNTED_TABLE
            source = "stage6.6_materialized_table"

        # Stage6 final paragraph 的 source_word_indices 是强 provenance 兜底。
        # 只在常规 paragraph/layout/table 几何归账都失败时使用，避免改变正常统计口径。
        # 典型场景：一个 Stage1 raw word 同时混入正文字符与 watermark 字符，Stage6 通过
        # char geometry 保留正文后，最终 paragraph 仍明确引用该 source_word_index。
        elif word_index in stage6_final_word_ownership:
            status = ACCOUNTED_FINAL_FLOW
            source = "stage6_final_flow_source_word_ownership"

        else:
            status = UNACCOUNTED_NATIVE
            source = "stage7_accounting_residual"

        initial_status = status
        initial_source = source

        final_flow_match: dict[str, Any] | None = None
        if status == UNACCOUNTED_NATIVE:
            historical_residual_count += 1
            final_flow_match = match_raw_word_to_final_flow(
                raw_text=text,
                raw_bbox=bbox,
                evidence_items=stage6_final_evidence,
            )
            if final_flow_match is not None:
                status = ACCOUNTED_FINAL_FLOW
                source = "stage6_final_flow_text_accounting"

        inside_image = any(bbox_matches(bbox, ib, 0.50) for ib in image_bboxes)
        if status == UNACCOUNTED_NATIVE and inside_image:
            unaccounted_inside_image += 1

        counts[status] += 1
        records.append(
            {
                "word_index": word_index,
                "text": text,
                "bbox": bbox,
                "accounting_status": status,
                "accounting_source": source,
                "initial_accounting_status": initial_status,
                "initial_accounting_source": initial_source,
                "final_flow_match": final_flow_match,
                "final_flow_word_ownership": stage6_final_word_ownership.get(word_index),
                "inside_image_region": inside_image,
            }
        )

    accounted_count = (
        counts[ACCOUNTED_TEXT]
        + counts[ACCOUNTED_TABLE]
        + counts[ACCOUNTED_NOISE]
        + counts[ACCOUNTED_FINAL_FLOW]
    )

    summary = {
        "valid_raw_word_count": valid_count,
        "accounted_text_word_count": counts[ACCOUNTED_TEXT],
        "accounted_table_word_count": counts[ACCOUNTED_TABLE],
        "accounted_noise_word_count": counts[ACCOUNTED_NOISE],
        "accounted_final_flow_word_count": counts[ACCOUNTED_FINAL_FLOW],
        "initial_residual_word_count": historical_residual_count,
        "unaccounted_native_word_count": counts[UNACCOUNTED_NATIVE],
        "unaccounted_native_inside_image_word_count": unaccounted_inside_image,
        "accounted_word_count": accounted_count,
        "native_word_accounting_ratio": (
            round(accounted_count / valid_count, 6) if valid_count else 1.0
        ),
        "note": "accounting ratio is provenance coverage, not a quality score",
    }

    return records, summary


# =============================================================================
# Residual word clustering (localization only, not quality judgement)
# =============================================================================


def cluster_unaccounted_words(
    word_records: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    residual = [
        item for item in word_records
        if item.get("accounting_status") == UNACCOUNTED_NATIVE
        and normalize_bbox(item.get("bbox")) is not None
    ]
    if not residual:
        return []

    heights = [
        bbox["bottom"] - bbox["top"]
        for item in residual
        if (bbox := normalize_bbox(item.get("bbox"))) is not None
    ]
    h = median(heights) if heights else 10.0
    line_tol = max(2.0, h * 0.65)
    gap_limit = max(h * 2.0, page_width * 0.035)

    # 先按视觉行聚合。
    ordered = sorted(
        residual,
        key=lambda item: (
            normalize_bbox(item["bbox"])["top"],
            normalize_bbox(item["bbox"])["x0"],
        ),
    )

    rows: list[list[dict[str, Any]]] = []
    for item in ordered:
        bbox = normalize_bbox(item["bbox"])
        cy = (bbox["top"] + bbox["bottom"]) / 2.0
        best_row = None
        best_delta = None
        for row in rows[-4:]:
            row_bbox = bbox_union(normalize_bbox(v["bbox"]) for v in row)
            row_cy = (row_bbox["top"] + row_bbox["bottom"]) / 2.0
            delta = abs(cy - row_cy)
            if delta <= line_tol and (best_delta is None or delta < best_delta):
                best_row = row
                best_delta = delta
        if best_row is None:
            rows.append([item])
        else:
            best_row.append(item)

    # 行内按大间隙切 segment。
    segments: list[dict[str, Any]] = []
    for row in rows:
        row = sorted(row, key=lambda item: normalize_bbox(item["bbox"])["x0"])
        current: list[dict[str, Any]] = []
        previous_bbox: dict[str, float] | None = None
        for item in row:
            bbox = normalize_bbox(item["bbox"])
            if (
                previous_bbox is not None
                and bbox["x0"] - previous_bbox["x1"] > gap_limit
            ):
                segments.append(make_residual_segment(current))
                current = []
            current.append(item)
            previous_bbox = bbox
        if current:
            segments.append(make_residual_segment(current))

    # 相邻视觉行若横向有明显重叠且垂直接近，则合并为一个 residual region。
    segments.sort(key=lambda item: (item["bbox"]["top"], item["bbox"]["x0"]))
    groups: list[list[dict[str, Any]]] = []
    vertical_limit = max(h * 2.2, 6.0)

    for seg in segments:
        merged = False
        for group in reversed(groups[-4:]):
            gb = bbox_union(item["bbox"] for item in group)
            sb = seg["bbox"]
            vertical_gap = sb["top"] - gb["bottom"]
            horizontal_overlap = max(0.0, min(gb["x1"], sb["x1"]) - max(gb["x0"], sb["x0"]))
            min_width = max(1.0, min(gb["x1"] - gb["x0"], sb["x1"] - sb["x0"]))
            overlap_ratio = horizontal_overlap / min_width
            if -h <= vertical_gap <= vertical_limit and overlap_ratio >= 0.20:
                group.append(seg)
                merged = True
                break
        if not merged:
            groups.append([seg])

    result: list[dict[str, Any]] = []
    for group in groups:
        words = [word for seg in group for word in seg["words"]]
        bbox = bbox_union(normalize_bbox(word["bbox"]) for word in words)
        result.append(
            {
                "bbox": bbox,
                "word_count": len(words),
                "word_indices": [int(word["word_index"]) for word in words],
                "text_preview": " ".join(str(word.get("text") or "") for word in words)[:300],
                "inside_image_word_count": sum(1 for word in words if word.get("inside_image_region")),
                "derivation": "clustered_unaccounted_stage1_words",
            }
        )

    return result


def make_residual_segment(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bbox": bbox_union(normalize_bbox(item["bbox"]) for item in items),
        "words": list(items),
    }


def word_records_inside_region(
    word_records: list[dict[str, Any]],
    region_bbox: dict[str, float] | None,
) -> list[dict[str, Any]]:
    if region_bbox is None:
        return []
    result: list[dict[str, Any]] = []
    for word in word_records:
        bbox = normalize_bbox(word.get("bbox"))
        if bbox is None:
            continue
        if bbox_matches(bbox, region_bbox, min_coverage=0.45):
            result.append(word)
    return result


def resolved_region_status_from_words(words: list[dict[str, Any]]) -> str | None:
    if not words:
        return None
    statuses = [str(item.get("accounting_status") or "") for item in words]
    if any(status == UNACCOUNTED_NATIVE for status in statuses):
        return None
    unique = set(statuses)
    if unique == {ACCOUNTED_TEXT}:
        return ACCOUNTED_TEXT
    if unique == {ACCOUNTED_TABLE}:
        return ACCOUNTED_TABLE
    if unique == {ACCOUNTED_NOISE}:
        return ACCOUNTED_NOISE
    return ACCOUNTED_FINAL_FLOW


def finalize_regions_from_word_accounting(
    regions: list[dict[str, Any]],
    word_records: list[dict[str, Any]],
) -> None:
    """
    A historical structure residual is not final unresolved when every raw word in that region is accounted by the Stage6 final flow.

    This mutates only Stage7 manifest records; it never changes upstream artifacts.
    """
    historical_statuses = {
        UNACCOUNTED_NATIVE,
        UNACCOUNTED_TABLE_REGION,
        QUARANTINED_STRUCTURE_EVIDENCE,
    }

    for region in regions:
        if region.get("overlay"):
            continue
        old_status = str(region.get("accounting_status") or "")
        if old_status not in historical_statuses:
            continue

        bbox = normalize_bbox(region.get("bbox"))
        words = word_records_inside_region(word_records, bbox)
        new_status = resolved_region_status_from_words(words)
        if new_status is None:
            continue

        region["historical_accounting_status"] = old_status
        region["historical_accounting_source"] = region.get("accounting_source")
        region["accounting_status"] = new_status
        region["accounting_source"] = "stage7_final_word_accounting"
        region["final_accounting"] = {
            "method": "all_native_words_in_region_accounted",
            "word_count": len(words),
            "word_status_counts": dict(
                Counter(str(item.get("accounting_status") or "UNKNOWN") for item in words)
            ),
        }


# =============================================================================
# Region ledger
# =============================================================================


def paragraph_source_block_ids(paragraph_page: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for paragraph in paragraph_page.get("paragraphs", []):
        if not isinstance(paragraph, dict):
            continue
        for block_id in paragraph.get("source_block_ids", []):
            if block_id:
                result.add(str(block_id))
    return result


def excluded_block_ids(reading_page: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in reading_page.get("excluded_noise_blocks", []):
        if not isinstance(item, dict):
            continue
        for key in ("block_id", "source_block_id"):
            value = item.get(key)
            if value:
                result.add(str(value))
    return result


def table_diagnostics_by_block(paragraph_page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in paragraph_page.get("table_unit_diagnostics", []):
        if not isinstance(item, dict):
            continue
        block_id = item.get("block_id")
        if block_id:
            result[str(block_id)] = item
    return result


def dedupe_stage6_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    对同一 Stage6 final-flow record 去重，并保持首次出现顺序。

    同一个 record 可能同时通过 block_id / source_block_id / source_table_index
    被索引命中。Stage7 只保留一次 provenance，不改变任何 accounting 判定。
    """
    result: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()
    seen_object_ids: set[int] = set()

    for item in records:
        if not isinstance(item, dict):
            continue

        record_id = item.get("record_id")
        if record_id is not None and str(record_id):
            key = str(record_id)
            if key in seen_record_ids:
                continue
            seen_record_ids.add(key)
            result.append(item)
            continue

        # 理论上 Stage6 final flow 都应有 record_id。
        # 对缺失 record_id 的异常记录只按对象身份去重，避免误合并不同证据。
        object_id = id(item)
        if object_id in seen_object_ids:
            continue
        seen_object_ids.add(object_id)
        result.append(item)

    return result


def build_stage4_region(
    page_number: int,
    block: dict[str, Any],
    region_id: str,
    paragraph_block_ids: set[str],
    excluded_ids: set[str],
    table_diag: dict[str, dict[str, Any]],
    normalized_by_block: dict[tuple[int, str], list[dict[str, Any]]],
    normalized_by_table: dict[tuple[int, int], list[dict[str, Any]]],
    stage5_tables: dict[int, set[int]],
    stage5_logical: dict[tuple[int, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    block_type = str(block.get("block_type") or "unknown")
    block_id = str(block.get("block_id") or "")
    source_block_id = str(block.get("source_block_id") or "")
    source_table_index = block.get("source_table_index")
    source_image_index = block.get("source_image_index")

    source_refs: list[str] = []
    if block_id:
        source_refs.append(f"stage4:block:{block_id}")
    if isinstance(source_table_index, int):
        source_refs.append(f"stage1:table:{page_number}:{source_table_index}")
    if isinstance(source_image_index, int):
        source_refs.append(f"stage1:image:{page_number}:{source_image_index}")

    stage6_records = []
    for candidate_id in (block_id, source_block_id):
        if candidate_id:
            stage6_records.extend(normalized_by_block.get((page_number, candidate_id), []))
    if isinstance(source_table_index, int):
        stage6_records.extend(normalized_by_table.get((page_number, source_table_index), []))

    # 同一个 Stage6 record 可能通过 block / source_block / table 三条索引路径重复命中。
    # Stage7 provenance 只记录一次；这一步不改变 accounting 语义。
    stage6_records = dedupe_stage6_records(stage6_records)

    accounting_status: str
    accounting_source: str
    table_info: dict[str, Any] | None = None

    if block_id in excluded_ids or (source_block_id and source_block_id in excluded_ids):
        accounting_status = ACCOUNTED_NOISE
        accounting_source = "stage6.2_excluded_noise_block"

    elif block_type == "text":
        if block_id in paragraph_block_ids or (source_block_id and source_block_id in paragraph_block_ids):
            accounting_status = ACCOUNTED_TEXT
            accounting_source = "stage6.3_paragraph_provenance"
        else:
            accounting_status = UNACCOUNTED_NATIVE
            accounting_source = "no_final_stage6_paragraph_provenance"

    elif block_type == "table":
        diag = table_diag.get(block_id, {})
        classification = str(diag.get("classification") or "")
        table_info = {
            "stage6_classification": classification or None,
            "stage6_diagnostic": diag or None,
            "stage5_physical_table_present": (
                isinstance(source_table_index, int)
                and source_table_index in stage5_tables.get(page_number, set())
            ),
            "stage5_logical_membership": (
                stage5_logical.get((page_number, int(source_table_index)), [])
                if isinstance(source_table_index, int)
                else []
            ),
            "stage6_non_text_record_ids": [
                item.get("record_id") for item in stage6_records if item.get("record_id")
            ],
            "stage6_table_materialization": [
                {
                    "record_id": item.get("record_id"),
                    "materialization_status": item.get("materialization_status"),
                    "effective_visibility": item.get("effective_visibility"),
                    "content_status": item.get("content_status"),
                }
                for item in stage6_records
                if isinstance(item, dict) and item.get("record_type") == "table_ref"
            ],
        }

        table_records = [
            item
            for item in stage6_records
            if isinstance(item, dict) and item.get("record_type") == "table_ref"
        ]
        has_materialized = any(
            str(item.get("effective_visibility") or "") == "visible"
            and str(item.get("materialization_status") or "")
            in {"materialized", "materialized_empty"}
            for item in table_records
        )
        has_suppressed_duplicate = any(
            str(item.get("materialization_status") or "") == "suppressed_duplicate"
            for item in table_records
        )
        has_unresolved = any(
            str(item.get("materialization_status") or "") == "unresolved_stage5_table"
            for item in table_records
        )

        if classification == "layout_container":
            accounting_status = ACCOUNTED_TEXT
            accounting_source = "stage6.3_layout_container_authority"
        elif has_suppressed_duplicate:
            accounting_status = ACCOUNTED_TEXT
            accounting_source = "stage6.6_table_suppressed_as_final_paragraph_duplicate"
        elif has_materialized:
            accounting_status = ACCOUNTED_TABLE
            accounting_source = "stage6.6_materialized_table"
        elif has_unresolved or classification == "data_table":
            accounting_status = UNACCOUNTED_TABLE_REGION
            accounting_source = "stage6.6_table_not_materialized_in_final_flow"
        else:
            accounting_status = UNACCOUNTED_TABLE_REGION
            accounting_source = "table_not_represented_in_stage6_final_flow"

    elif block_type in {"image", "vector"}:
        accounting_status = NON_TEXT_UNASSESSED
        accounting_source = "native_non_text_evidence_requires_stage8_assessment"

    else:
        accounting_status = NON_TEXT_UNASSESSED
        accounting_source = "unknown_stage4_block_type"

    return {
        "region_id": region_id,
        "region_origin": "stage4_block",
        "region_type": block_type,
        "bbox": normalize_bbox(block.get("bbox")),
        "accounting_status": accounting_status,
        "accounting_source": accounting_source,
        "source_refs": source_refs,
        "stage4": {
            "block_id": block.get("block_id"),
            "source_block_id": block.get("source_block_id"),
            "spatial_order": block.get("spatial_order"),
            "column": block.get("column"),
            "flow_role": block.get("flow_role"),
            "structure_confidence": block.get("structure_confidence"),
            "boundary_fragment": block.get("boundary_fragment"),
            "original_bbox": block.get("original_bbox"),
        },
        "source_table_index": source_table_index if isinstance(source_table_index, int) else None,
        "source_image_index": source_image_index if isinstance(source_image_index, int) else None,
        "table_evidence": table_info,
        "stage6_record_ids": [item.get("record_id") for item in stage6_records if item.get("record_id")],
    }


def build_regions_for_page(
    page_number: int,
    raw_page: dict[str, Any],
    structure_page: dict[str, Any],
    reading_page: dict[str, Any],
    paragraph_page: dict[str, Any],
    normalized_by_block: dict[tuple[int, str], list[dict[str, Any]]],
    normalized_by_table: dict[tuple[int, int], list[dict[str, Any]]],
    stage5_tables: dict[int, set[int]],
    stage5_logical: dict[tuple[int, int], list[dict[str, Any]]],
    residual_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks = [item for item in structure_page.get("blocks", []) if isinstance(item, dict)]
    blocks.sort(
        key=lambda item: (
            int(item.get("spatial_order", 10**9) or 10**9),
            (normalize_bbox(item.get("bbox")) or {"top": 10**9})["top"],
            (normalize_bbox(item.get("bbox")) or {"x0": 10**9})["x0"],
        )
    )

    paragraph_ids = paragraph_source_block_ids(paragraph_page)
    excluded_ids = excluded_block_ids(reading_page)
    table_diag = table_diagnostics_by_block(paragraph_page)

    regions: list[dict[str, Any]] = []
    represented_images: set[int] = set()
    represented_tables: set[int] = set()

    for block in blocks:
        region_id = f"p{page_number:04d}_r{len(regions) + 1:03d}"
        region = build_stage4_region(
            page_number,
            block,
            region_id,
            paragraph_ids,
            excluded_ids,
            table_diag,
            normalized_by_block,
            normalized_by_table,
            stage5_tables,
            stage5_logical,
        )
        regions.append(region)
        if isinstance(region.get("source_image_index"), int):
            represented_images.add(int(region["source_image_index"]))
        if isinstance(region.get("source_table_index"), int):
            represented_tables.add(int(region["source_table_index"]))

    # Stage4 退化候选也不能丢；它们不参与正常 region block，但属于原证据账本。
    for candidate in structure_page.get("degenerate_candidates", []):
        if not isinstance(candidate, dict):
            continue
        region_id = f"p{page_number:04d}_r{len(regions) + 1:03d}"
        bbox = normalize_bbox(candidate.get("page_bbox")) or normalize_bbox(candidate.get("raw_bbox"))
        regions.append(
            {
                "region_id": region_id,
                "region_origin": "stage4_degenerate_candidate",
                "region_type": str(candidate.get("block_type") or "unknown"),
                "bbox": bbox,
                "accounting_status": QUARANTINED_STRUCTURE_EVIDENCE,
                "accounting_source": "stage4_degenerate_candidate",
                "source_refs": [f"stage4:degenerate:{candidate.get('candidate_id')}"] if candidate.get("candidate_id") else [],
                "stage4_degenerate": candidate,
            }
        )
        if isinstance(candidate.get("source_image_index"), int):
            represented_images.add(int(candidate["source_image_index"]))
        if isinstance(candidate.get("source_table_index"), int):
            represented_tables.add(int(candidate["source_table_index"]))

    # Stage4 会保守过滤小 image / table 内 image；Stage7 必须把 Stage1 原始 image 重新记到账本，
    # 但只标 NON_TEXT_UNASSESSED，不判断 logo / OCR / decorative。
    for image_index, image in enumerate(raw_page.get("images", []) if isinstance(raw_page.get("images"), list) else []):
        if image_index in represented_images or not isinstance(image, dict):
            continue
        bbox = normalize_bbox(image)
        if bbox is None:
            continue
        region_id = f"p{page_number:04d}_r{len(regions) + 1:03d}"
        regions.append(
            {
                "region_id": region_id,
                "region_origin": "stage1_unrepresented_image",
                "region_type": "image",
                "bbox": bbox,
                "accounting_status": NON_TEXT_UNASSESSED,
                "accounting_source": "stage1_image_not_promoted_to_stage4_block",
                "source_refs": [f"stage1:image:{page_number}:{image_index}"],
                "source_image_index": image_index,
                "stage1_image": {
                    key: image.get(key)
                    for key in ("name", "width", "height", "srcsize", "bits", "colorspace", "imagemask")
                    if key in image
                },
            }
        )

    # 理论上 Stage4 已把未表示 table candidate 放入 degenerate；这里再做一次无损兜底。
    raw_tables = raw_page.get("table_candidates", [])
    if not isinstance(raw_tables, list):
        raw_tables = []
    for fallback_index, table in enumerate(raw_tables):
        if not isinstance(table, dict):
            continue
        table_index = table.get("table_index", fallback_index)
        try:
            table_index = int(table_index)
        except (TypeError, ValueError):
            table_index = fallback_index
        if table_index in represented_tables:
            continue
        bbox = normalize_bbox(table.get("bbox"))
        if bbox is None:
            continue
        region_id = f"p{page_number:04d}_r{len(regions) + 1:03d}"
        regions.append(
            {
                "region_id": region_id,
                "region_origin": "stage1_unrepresented_table_candidate",
                "region_type": "table",
                "bbox": bbox,
                "accounting_status": UNACCOUNTED_TABLE_REGION,
                "accounting_source": "stage1_table_not_promoted_to_stage4_or_stage6",
                "source_refs": [f"stage1:table:{page_number}:{table_index}"],
                "source_table_index": table_index,
            }
        )

    # Unaccounted native word overlays：不是新的“物理对象”，只是后续精准 fallback 的定位抓手。
    for cluster in residual_clusters:
        region_id = f"p{page_number:04d}_r{len(regions) + 1:03d}"
        regions.append(
            {
                "region_id": region_id,
                "region_origin": "stage7_residual_overlay",
                "region_type": "native_residual",
                "bbox": cluster.get("bbox"),
                "accounting_status": UNACCOUNTED_NATIVE,
                "accounting_source": "clustered_unaccounted_stage1_words",
                "overlay": True,
                "word_count": cluster.get("word_count"),
                "word_indices": cluster.get("word_indices"),
                "inside_image_word_count": cluster.get("inside_image_word_count"),
                "text_preview": cluster.get("text_preview"),
                "source_refs": [
                    f"stage1:word:{page_number}:{index}"
                    for index in cluster.get("word_indices", [])
                ],
            }
        )

    return regions


# =============================================================================
# Manifest
# =============================================================================


def page_stage5_evidence(page_number: int, stage5_boundary: dict[int, list[dict[str, Any]]], stage5_logical: dict[tuple[int, int], list[dict[str, Any]]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for (page, _table_index), memberships in stage5_logical.items():
        if page != page_number:
            continue
        for item in memberships:
            group_id = str(item.get("group_id") or "")
            if group_id:
                groups[group_id] = item
    boundaries = stage5_boundary.get(page_number, [])
    return {
        "logical_table_groups": list(groups.values()),
        "boundary_relations": boundaries,
        "boundary_relation_count": len(boundaries),
    }


def build_manifest(
    profile: dict[str, Any],
    snapshot_meta: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    template: dict[str, Any],
    alignment: dict[str, Any],
    structure: dict[str, Any],
    stage5: dict[str, Any],
    noise: dict[str, Any],
    reading: dict[str, Any],
    paragraphs: dict[str, Any],
    normalized: dict[str, Any],
    input_paths: dict[str, str],
) -> dict[str, Any]:
    source_file, page_count = validate_inputs(
        snapshot_meta,
        snapshot_pages,
        {
            "profile": profile,
            "template": template,
            "alignment": alignment,
            "structure": structure,
            "stage5": stage5,
            "noise": noise,
            "reading": reading,
            "paragraphs": paragraphs,
            "normalized": normalized,
        },
    )

    validate_stage6_final_contract(normalized)

    profile_pages = index_pages(profile)
    alignment_pages = index_pages(alignment)
    structure_pages = index_pages(structure)
    validation_pages = stage4_validation_index(structure)
    reading_pages = index_pages(reading)
    paragraph_pages = index_pages(paragraphs)

    stage5_tables = stage5_page_table_indices(stage5)
    stage5_logical = stage5_logical_table_index(stage5)
    stage5_boundary = stage5_boundary_index(stage5)
    normalized_by_block, normalized_by_table = normalized_non_text_index(normalized)
    noise_occurrences = auto_remove_noise_occurrences(noise)
    stage6_final_evidence = stage6_final_text_evidence_index(normalized)
    stage6_final_word_ownership = stage6_final_word_ownership_index(normalized)
    final_table_bboxes = stage6_final_table_bboxes(normalized)

    pages_out: list[dict[str, Any]] = []
    doc_word_counts: Counter[str] = Counter()
    doc_region_status: Counter[str] = Counter()
    doc_region_types: Counter[str] = Counter()
    pages_with_unaccounted_native: list[int] = []
    pages_with_final_flow_accounted: list[int] = []
    pages_with_non_text_unassessed: list[int] = []
    total_primary_regions = 0
    total_overlay_regions = 0

    for page_number in range(1, page_count + 1):
        raw_page = snapshot_pages[page_number]
        profile_page = profile_pages.get(page_number, {})
        alignment_page = alignment_pages.get(page_number, {})
        structure_page = structure_pages.get(page_number, {})
        validation_page = validation_pages.get(page_number, {})
        reading_page = reading_pages.get(page_number, {})
        paragraph_page = paragraph_pages.get(page_number, {})

        table_diag = table_diagnostics_by_block(paragraph_page)
        layout_container_bboxes: list[dict[str, float]] = []
        data_table_bboxes: list[dict[str, float]] = list(final_table_bboxes.get(page_number, []))
        image_bboxes: list[dict[str, float]] = []

        for block in structure_page.get("blocks", []):
            if not isinstance(block, dict):
                continue
            bbox = normalize_bbox(block.get("bbox"))
            if bbox is None:
                continue
            block_type = str(block.get("block_type") or "")
            if block_type == "image":
                image_bboxes.append(bbox)
            if block_type != "table":
                continue
            block_id = str(block.get("block_id") or "")
            classification = str(table_diag.get(block_id, {}).get("classification") or "")
            if classification == "layout_container":
                layout_container_bboxes.append(bbox)


        # Stage1 未提升为 Stage4 的 image 也参与 inside-image 标记。
        for image in raw_page.get("images", []) if isinstance(raw_page.get("images"), list) else []:
            if isinstance(image, dict):
                bbox = normalize_bbox(image)
                if bbox is not None:
                    image_bboxes.append(bbox)

        excluded_regions = reading_excluded_noise_regions(reading_page)
        word_records, word_summary = account_words(
            raw_page=raw_page,
            paragraphs=paragraph_page.get("paragraphs", []) if isinstance(paragraph_page.get("paragraphs"), list) else [],
            layout_container_bboxes=layout_container_bboxes,
            data_table_bboxes=data_table_bboxes,
            noise_occurrences=noise_occurrences.get(page_number, []),
            excluded_noise_regions=excluded_regions,
            image_bboxes=image_bboxes,
            stage6_final_evidence=stage6_final_evidence.get(page_number, []),
            stage6_final_word_ownership=stage6_final_word_ownership.get(page_number, {}),
        )

        residual_clusters = cluster_unaccounted_words(
            word_records,
            float(raw_page.get("width", 0.0) or 0.0),
        )

        regions = build_regions_for_page(
            page_number=page_number,
            raw_page=raw_page,
            structure_page=structure_page,
            reading_page=reading_page,
            paragraph_page=paragraph_page,
            normalized_by_block=normalized_by_block,
            normalized_by_table=normalized_by_table,
            stage5_tables=stage5_tables,
            stage5_logical=stage5_logical,
            residual_clusters=residual_clusters,
        )

        finalize_regions_from_word_accounting(regions, word_records)

        region_status_counts = Counter(str(item.get("accounting_status") or "UNKNOWN") for item in regions)
        region_type_counts = Counter(str(item.get("region_type") or "unknown") for item in regions)
        primary_region_count = sum(1 for item in regions if not item.get("overlay"))
        overlay_region_count = sum(1 for item in regions if item.get("overlay"))
        total_primary_regions += primary_region_count
        total_overlay_regions += overlay_region_count

        for key, value in word_summary.items():
            if key.endswith("_word_count") and isinstance(value, int):
                doc_word_counts[key] += value
        doc_region_status.update(region_status_counts)
        doc_region_types.update(region_type_counts)

        if word_summary["unaccounted_native_word_count"] > 0:
            pages_with_unaccounted_native.append(page_number)
        if word_summary["accounted_final_flow_word_count"] > 0:
            pages_with_final_flow_accounted.append(page_number)
        if region_status_counts[NON_TEXT_UNASSESSED] > 0:
            pages_with_non_text_unassessed.append(page_number)

        assignment_diag = paragraph_page.get("assignment_diagnostics", {})
        if not isinstance(assignment_diag, dict):
            assignment_diag = {}

        page_out = {
            "page_number": page_number,
            "page_geometry": {
                "width": raw_page.get("width"),
                "height": raw_page.get("height"),
                "rotation": raw_page.get("rotation", 0),
            },
            "page_profile": {
                key: profile_page.get(key)
                for key in (
                    "primary_type", "native_char_count", "word_count", "image_count",
                    "image_ratio", "largest_image_ratio", "char_in_image_ratio",
                    "native_char_count_outside_images", "vector_object_count", "multi_column",
                    "column_split_support_rows", "column_split_support_ratio",
                    "column_split_vertical_span", "table_candidate_count", "table_detection_status",
                )
                if key in profile_page
            },
            "document_structure": {
                "section_id": alignment_page.get("section_id") or structure_page.get("document_structure", {}).get("section_id"),
                "section_title": alignment_page.get("title") or structure_page.get("document_structure", {}).get("section_title"),
                "zone_type": alignment_page.get("zone_type") or structure_page.get("document_structure", {}).get("zone_type"),
                "boundary_confidence": alignment_page.get("boundary_confidence") or structure_page.get("document_structure", {}).get("boundary_confidence"),
                "match_mode": alignment_page.get("match_mode") or structure_page.get("document_structure", {}).get("match_mode"),
                "complexity_prior": structure_page.get("document_structure", {}).get("complexity_prior"),
            },
            "upstream_status": {
                "stage4_validation": validation_page.get("status"),
                "stage4_error_count": validation_page.get("error_count", 0),
                "stage4_warning_count": validation_page.get("warning_count", 0),
                "stage4_degenerate_candidate_count": len(structure_page.get("degenerate_candidates", [])) if isinstance(structure_page.get("degenerate_candidates"), list) else 0,
                "stage6_reading_status": reading_page.get("status"),
                "stage6_reading_confidence": reading_page.get("confidence"),
                "stage6_reading_ambiguity_count": reading_page.get("ambiguity_count", 0),
                "stage6_invalid_block_count": reading_page.get("invalid_block_count", 0),
                "stage6_paragraph_status": paragraph_page.get("status"),
                "stage6_paragraph_confidence": paragraph_page.get("confidence"),
                "stage6_inherited_reading_risk": paragraph_page.get("inherited_reading_risk", False),
                "stage6_risky_unsupported_empty_text_unit_count": assignment_diag.get("risky_unsupported_empty_text_unit_count", 0),
            },
            "stage5_table_evidence": page_stage5_evidence(page_number, stage5_boundary, stage5_logical),
            "word_accounting": word_summary,
            "word_records": word_records,
            "region_count": len(regions),
            "primary_region_count": primary_region_count,
            "overlay_region_count": overlay_region_count,
            "region_status_counts": dict(region_status_counts),
            "region_type_counts": dict(region_type_counts),
            "regions": regions,
        }
        pages_out.append(page_out)

    total_valid_words = doc_word_counts["valid_raw_word_count"]
    total_accounted_words = doc_word_counts["accounted_word_count"]

    return {
        "stage": STAGE,
        "name": "native_evidence_manifest",
        "version": VERSION,
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "source_file": source_file,
        "page_count": page_count,
        "artifact_role": "native_pipeline_final_evidence_manifest",
        "quality_gate_completed": False,
        "pdf_reopened": False,
        "content_repaired": False,
        "final_flow_accounting_completed": True,
        "inputs": input_paths,
        "upstream_versions": {
            "page_scan_version": snapshot_meta.get("page_scan_version"),
            "snapshot_schema_version": snapshot_meta.get("snapshot_schema_version"),
            "profiler_version": profile.get("profiler_version"),
            "template_analyzer_version": template.get("analyzer_version"),
            "section_aligner_version": alignment.get("aligner_version"),
            "stage4_builder_version": structure.get("builder_version"),
            "stage5_version": stage5.get("version"),
            "stage6_pipeline_version": normalized.get("pipeline_version") or paragraphs.get("pipeline_version"),
        },
        "document_context": {
            "template_decision": template.get("template_decision"),
            "template_id": alignment.get("template_id") or template.get("template_id"),
            "template_name": alignment.get("template_name") or template.get("template_name"),
            "template_confidence": alignment.get("template_confidence") or template.get("template_confidence"),
            "structure_mode": alignment.get("structure_mode") or structure.get("structure_mode"),
        },
        "pipeline_integrity_evidence": {
            "stage4_validation": structure.get("validation", {}),
            "stage6_normalized_status": normalized.get("status"),
            "stage6_mapping_integrity": normalized.get("mapping_integrity"),
            "stage6_missing_logical_records": normalized.get("missing_logical_records", []),
            "stage6_partial_source_pages": normalized.get("partial_source_pages", []),
            "stage6_artifact_role": normalized.get("artifact_role"),
            "stage6_table_finalization": normalized.get("stage66_table_finalization", {}),
            "stage6_readable_renderer_mutates_content": (
                normalized.get("text_policy", {}).get("readable_renderer_mutates_content")
                if isinstance(normalized.get("text_policy"), dict)
                else None
            ),
        },
        "summary": {
            "region_count": sum(doc_region_status.values()),
            "primary_region_count": total_primary_regions,
            "overlay_region_count": total_overlay_regions,
            "region_status_counts": dict(doc_region_status),
            "region_type_counts": dict(doc_region_types),
            "valid_raw_word_count": total_valid_words,
            "accounted_word_count": total_accounted_words,
            "accounted_text_word_count": doc_word_counts["accounted_text_word_count"],
            "accounted_table_word_count": doc_word_counts["accounted_table_word_count"],
            "accounted_noise_word_count": doc_word_counts["accounted_noise_word_count"],
            "accounted_final_flow_word_count": doc_word_counts["accounted_final_flow_word_count"],
            "initial_residual_word_count": doc_word_counts["initial_residual_word_count"],
            "unaccounted_native_word_count": doc_word_counts["unaccounted_native_word_count"],
            "unaccounted_native_inside_image_word_count": doc_word_counts["unaccounted_native_inside_image_word_count"],
            "native_word_accounting_ratio": (
                round(total_accounted_words / total_valid_words, 6)
                if total_valid_words else 1.0
            ),
            "pages_with_unaccounted_native_words": pages_with_unaccounted_native,
            "pages_with_final_flow_accounted_words": pages_with_final_flow_accounted,
            "pages_with_non_text_unassessed": pages_with_non_text_unassessed,
            "note": (
                "Stage1 raw evidence may be accounted directly by geometry/provenance or by matching "
                "the Stage6 final machine flow. Only evidence still unaccounted after Stage6 remains unresolved. "
                "These are accounting facts, not Stage8 quality decisions."
            ),
        },
        "pages": pages_out,
        "stage_status": {
            "scope": "stage1_to_stage6_final_evidence_aggregation_and_accounting_only",
            "historical_anomaly_policy": "preserve_provenance_but_final_unresolved_comes_from_stage6_end_state",
            "final_unresolved_policy": "only_evidence_unaccounted_after_stage6_final_flow_is_forwarded_to_stage8",
            "quality_decision": "forbidden",
            "ocr": "forbidden",
            "layout_fallback": "forbidden",
            "pdf_reopen": "forbidden",
            "next_stage": "stage_8_quality_gate_and_routing",
        },
    }


# =============================================================================
# Markdown / terminal
# =============================================================================


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Stage 7 Native Evidence Manifest",
        "",
        f"- 文件：{manifest.get('source_file')}",
        f"- 页数：{manifest.get('page_count')}",
        f"- Stage7 版本：{manifest.get('version')}",
        f"- Quality Gate：{manifest.get('quality_gate_completed')}",
        f"- PDF reopened：{manifest.get('pdf_reopened')}",
        "",
        "> ACCOUNTED_* / ACCOUNTED_FINAL_FLOW 只代表 Stage1~6 最终机器结果已有 native 证据可解释，不代表解析质量正确。真正质量裁决在 Stage8。",
        "> Stage7 不读取 readable_final.md；Stage6 normalized_text_flow.json 是最终机器 authority。",
        "",
        "| page | type | section | zone | S4 | S6 reading | words(text/table/noise/final-flow/unresolved) | regions | non-text |",
        "|---:|---|---|---|---|---|---|---:|---:|",
    ]

    for page in manifest.get("pages", []):
        profile = page.get("page_profile", {})
        structure = page.get("document_structure", {})
        upstream = page.get("upstream_status", {})
        wa = page.get("word_accounting", {})
        status_counts = page.get("region_status_counts", {})
        word_cell = (
            f"{wa.get('accounted_text_word_count', 0)}/"
            f"{wa.get('accounted_table_word_count', 0)}/"
            f"{wa.get('accounted_noise_word_count', 0)}/"
            f"{wa.get('accounted_final_flow_word_count', 0)}/"
            f"{wa.get('unaccounted_native_word_count', 0)}"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(page.get("page_number")),
                    str(profile.get("primary_type") or ""),
                    str(structure.get("section_id") or ""),
                    str(structure.get("zone_type") or ""),
                    str(upstream.get("stage4_validation") or ""),
                    str(upstream.get("stage6_reading_status") or ""),
                    word_cell,
                    str(page.get("region_count", 0)),
                    str(status_counts.get(NON_TEXT_UNASSESSED, 0)),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Summary", "", "```json"])
    lines.append(json.dumps(manifest.get("summary", {}), ensure_ascii=False, indent=2))
    lines.extend(["```", ""])
    return "\n".join(lines)


def print_summary(manifest: dict[str, Any], output_dir: Path) -> None:
    summary = manifest.get("summary", {})
    print()
    print("=" * 112)
    print(
        f"Stage 7 Native Evidence Manifest | {manifest.get('source_file')} "
        f"| 页数={manifest.get('page_count')} | 版本={VERSION}"
    )
    print("=" * 112)
    print(
        "状态"
        f" | regions={summary.get('region_count', 0)}"
        f" | words={summary.get('valid_raw_word_count', 0)}"
        f" | accounted={summary.get('accounted_word_count', 0)}"
        f" | final_flow_accounted={summary.get('accounted_final_flow_word_count', 0)}"
        f" | unaccounted_native={summary.get('unaccounted_native_word_count', 0)}"
        f" | non_text_unassessed={summary.get('region_status_counts', {}).get(NON_TEXT_UNASSESSED, 0)}"
        f" | accounting_ratio={summary.get('native_word_accounting_ratio', 0):.4f}"
    )
    print(
        "页面"
        f" | final_flow_accounted_pages={len(summary.get('pages_with_final_flow_accounted_words', []))}"
        f" | unaccounted_native_pages={len(summary.get('pages_with_unaccounted_native_words', []))}"
        f" | non_text_unassessed_pages={len(summary.get('pages_with_non_text_unassessed', []))}"
    )
    print(f"JSON：{output_dir / 'evidence_manifest.json'}")
    print(f"Markdown：{output_dir / 'evidence_manifest.md'}")
    print(
        "说明：Stage7 只做 Stage1~6 final evidence aggregation / accounting；"
        "不重新打开 PDF，不做 OCR，不做 Quality Gate，不输出 fallback route。"
    )
    print("=" * 112)


# =============================================================================
# CLI
# =============================================================================


def run_evidence_manifest(
    *,
    profile_path: Path,
    snapshot_path: Path,
    template_path: Path,
    alignment_path: Path,
    structure_path: Path,
    stage5_path: Path,
    stage6_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run Stage 7 through the package API while preserving both artifacts."""
    stage6_dir = Path(stage6_dir)
    noise_path = stage6_dir / "noise_candidates.json"
    reading_path = stage6_dir / "reading_order.json"
    paragraphs_path = stage6_dir / "paragraphs.json"
    normalized_path = stage6_dir / "normalized_text_flow.json"

    profile = load_json(Path(profile_path))
    snapshot_meta, snapshot_pages = load_snapshot(Path(snapshot_path))
    template = load_json(Path(template_path))
    alignment = load_json(Path(alignment_path))
    structure = load_json(Path(structure_path))
    stage5 = load_json(Path(stage5_path))
    noise = load_json(noise_path)
    reading = load_json(reading_path)
    paragraphs = load_json(paragraphs_path)
    normalized = load_json(normalized_path)

    input_paths = {
        "stage1_profile": str(profile_path),
        "stage1_snapshot": str(snapshot_path),
        "stage2_template": str(template_path),
        "stage3_alignment": str(alignment_path),
        "stage4_structure": str(structure_path),
        "stage5_result": str(stage5_path),
        "stage6_noise": str(noise_path),
        "stage6_reading_order": str(reading_path),
        "stage6_paragraphs": str(paragraphs_path),
        "stage6_normalized_text_flow": str(normalized_path),
    }
    manifest = build_manifest(
        profile=profile,
        snapshot_meta=snapshot_meta,
        snapshot_pages=snapshot_pages,
        template=template,
        alignment=alignment,
        structure=structure,
        stage5=stage5,
        noise=noise,
        reading=reading,
        paragraphs=paragraphs,
        normalized=normalized,
        input_paths=input_paths,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "evidence_manifest.md").write_text(
        render_markdown(manifest),
        encoding="utf-8",
    )
    return manifest

