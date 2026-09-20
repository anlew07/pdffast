#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


STAGE8_VERSION = "0.3.2"
QUALITY_GATE_SCHEMA_VERSION = "1.4"

# Page-level thresholds: only routing evidence, never a scalar quality score.
IMAGE_DOMINANT_LARGEST_RATIO = 0.50
IMAGE_DOMINANT_TOTAL_RATIO = 0.60
ACCOUNTING_RATIO_EPSILON = 1e-9

# Region-level thresholds: geometry-only significance buckets.
# They intentionally do NOT claim that an image contains text, a chart, a logo, etc.
FULL_PAGE_SCAN_MIN_AREA_RATIO = 0.50
TINY_NON_TEXT_MAX_AREA_RATIO = 0.005
SMALL_NON_TEXT_MAX_AREA_RATIO = 0.03
MEDIUM_NON_TEXT_MAX_AREA_RATIO = 0.10
FRAGMENT_CLUSTER_MIN_COUNT = 3
FRAGMENT_CLUSTER_MAX_TOTAL_AREA_RATIO = 0.02

DECISION_NATIVE_PASS = "NATIVE_PASS"
DECISION_NATIVE_PASS_WITH_NON_TEXT = "NATIVE_PASS_WITH_NON_TEXT"
DECISION_OCR_REQUIRED = "OCR_REQUIRED"
DECISION_LAYOUT_FALLBACK_REQUIRED = "LAYOUT_FALLBACK_REQUIRED"

GATE_HARD_PASS = "HARD_PASS"
GATE_HARD_FALLBACK = "HARD_FALLBACK"
GATE_UNCERTAIN = "UNCERTAIN_NEEDS_PROBE"

REGION_FULL_PAGE_SCAN = "FULL_PAGE_SCAN"
REGION_TINY_FRAGMENT = "TINY_NON_TEXT_FRAGMENT"
REGION_SMALL = "SMALL_NON_TEXT_REGION"
REGION_MEDIUM = "MEDIUM_NON_TEXT_REGION"
REGION_LARGE = "LARGE_NON_TEXT_REGION"

REGION_ACTION_PAGE_OCR = "PAGE_OCR_REQUIRED"
REGION_ACTION_PRESERVE = "PRESERVE_WITH_NATIVE"
REGION_ACTION_REVIEW = "REGION_REVIEW_REQUIRED"

# Raster-probe labels are intentionally routing hints, not semantic truth.
# Stage8 v0.3.2 does not decide OCR-vs-layout for a region. That belongs to Stage9.
RASTER_LOW_INFORMATION = "LOW_INFORMATION_RASTER"
RASTER_AUXILIARY_IMAGE = "AUXILIARY_CONTINUOUS_TONE_RASTER_CANDIDATE"
RASTER_CONTENT_BEARING = "CONTENT_BEARING_RASTER_CANDIDATE"
RASTER_AMBIGUOUS_CONTENT = "AMBIGUOUS_CONTENT_RASTER"
RASTER_INLINE_CLUSTER_MEMBER = "INLINE_RASTER_CONTEXT_MEMBER"
RASTER_COVERED_INLINE_CONTEXT = "COVERED_BY_INLINE_RASTER_CONTEXT"
RASTER_SKIPPED_PAGE_OCR = "SKIPPED_PAGE_OCR_ALREADY_REQUIRED"

FINAL_REGION_ACTION_FALLBACK = "REGION_FALLBACK_REQUIRED"
FINAL_REGION_ACTION_DEFER_INLINE_CLUSTER = "DEFER_TO_INLINE_RASTER_CONTEXT"
FINAL_REGION_ACTION_COVERED_INLINE_CONTEXT = "COVERED_BY_INLINE_RASTER_CONTEXT"

# A clear continuous-tone raster may be preserved without invoking Stage9.
# These are deliberately conservative and only suppress fallback when photo-like evidence is strong.
AUXILIARY_PHOTO_MIN_SCORE = 0.50
AUXILIARY_PHOTO_MIN_ENTROPY = 5.50
AUXILIARY_PHOTO_MAX_TEXT_SCORE = 0.35

# Tiny raster fragments can be formula/image glyphs embedded in native text.
# Group them with nearby accounted text and send one contextual crop to Stage9 instead of one call per glyph.
INLINE_TEXT_VERTICAL_GAP_PT = 8.0
INLINE_TEXT_HORIZONTAL_GAP_PT = 24.0
INLINE_CONTEXT_PADDING_PT = 8.0
INLINE_CLUSTER_MIN_MEMBERS = 2
INLINE_SINGLETON_MIN_VERTICAL_OVERLAP_RATIO = 0.50
INLINE_SINGLETON_MIN_HORIZONTAL_OVERLAP_RATIO = 0.25
INLINE_SINGLETON_MAX_TIGHT_GAP_PT = 12.0
INLINE_CONTEXT_COVERAGE_RATIO = 0.95
INLINE_CONTEXT_MAX_COVERED_AREA_RATIO = SMALL_NON_TEXT_MAX_AREA_RATIO

DEFAULT_PROBE_DPI = 200
MAX_ADAPTIVE_PROBE_DPI = 360
MIN_PROBE_SHORT_SIDE_PX = 96

# Conservative raster-probe thresholds. These produce candidates, not truth labels.
TEXT_SCORE_THRESHOLD = 0.58
STRUCTURE_SCORE_THRESHOLD = 0.55
PHOTO_SCORE_THRESHOLD = 0.62
MIN_TEXT_ROW_BANDS = 2
MIN_STRUCTURE_LINE_RATIO = 0.008


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return data


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_manifest(manifest: dict[str, Any]) -> None:
    if safe_int(manifest.get("stage"), -1) != 7:
        raise ValueError("Stage8 输入必须是 Stage7 evidence manifest。")

    if manifest.get("artifact_role") != "native_pipeline_final_evidence_manifest":
        raise ValueError(
            "Stage8 输入 artifact_role 必须是 "
            "'native_pipeline_final_evidence_manifest'。"
        )

    if manifest.get("final_flow_accounting_completed") is not True:
        raise ValueError("Stage7 final_flow_accounting_completed 必须为 true。")

    if manifest.get("quality_gate_completed") is True:
        raise ValueError("输入不应已经完成 Quality Gate。")

    pages = manifest.get("pages")
    if not isinstance(pages, list):
        raise ValueError("Stage7 manifest 缺少 pages 列表。")

    page_count = safe_int(manifest.get("page_count"), -1)
    if page_count < 0 or page_count != len(pages):
        raise ValueError(
            f"Stage7 page_count 不一致：header={page_count}, pages={len(pages)}"
        )


def add_fact(
    facts: list[dict[str, Any]],
    code: str,
    severity: str,
    observed: Any,
    reason: str,
) -> None:
    facts.append(
        {
            "code": code,
            "severity": severity,
            "observed": observed,
            "reason": reason,
        }
    )


def bbox_geometry(
    bbox: Any,
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    if not isinstance(bbox, dict) or page_width <= 0 or page_height <= 0:
        return {
            "valid": False,
            "width": 0.0,
            "height": 0.0,
            "width_ratio": 0.0,
            "height_ratio": 0.0,
            "area_ratio": 0.0,
            "center_x_ratio": None,
            "center_y_ratio": None,
        }

    x0 = safe_float(bbox.get("x0"))
    x1 = safe_float(bbox.get("x1"))
    top = safe_float(bbox.get("top"))
    bottom = safe_float(bbox.get("bottom"))
    width = max(0.0, x1 - x0)
    height = max(0.0, bottom - top)
    area = width * height
    page_area = page_width * page_height

    return {
        "valid": width > 0 and height > 0,
        "width": round(width, 4),
        "height": round(height, 4),
        "width_ratio": round(width / page_width, 6),
        "height_ratio": round(height / page_height, 6),
        "area_ratio": round(area / page_area, 6),
        "center_x_ratio": round(((x0 + x1) / 2.0) / page_width, 6),
        "center_y_ratio": round(((top + bottom) / 2.0) / page_height, 6),
    }


def page_observations(page: dict[str, Any]) -> dict[str, Any]:
    profile = page.get("page_profile") or {}
    structure = page.get("document_structure") or {}
    upstream = page.get("upstream_status") or {}
    accounting = page.get("word_accounting") or {}
    region_status = page.get("region_status_counts") or {}

    accounted_text = safe_int(accounting.get("accounted_text_word_count"))
    accounted_table = safe_int(accounting.get("accounted_table_word_count"))
    accounted_final_flow = safe_int(accounting.get("accounted_final_flow_word_count"))

    complexity = structure.get("complexity_prior") or {}

    return {
        "primary_type": str(profile.get("primary_type") or "unknown"),
        "section_id": structure.get("section_id"),
        "zone_type": structure.get("zone_type"),
        "complexity_level": str(complexity.get("level") or "unknown"),
        "useful_native_word_count": accounted_text + accounted_table + accounted_final_flow,
        "accounted_noise_word_count": safe_int(accounting.get("accounted_noise_word_count")),
        "accounted_final_flow_word_count": accounted_final_flow,
        "unaccounted_native_word_count": safe_int(accounting.get("unaccounted_native_word_count")),
        "native_word_accounting_ratio": safe_float(accounting.get("native_word_accounting_ratio"), 0.0),
        "non_text_unassessed_region_count": safe_int(region_status.get("NON_TEXT_UNASSESSED")),
        "unaccounted_table_region_count": safe_int(region_status.get("UNACCOUNTED_TABLE_REGION")),
        "image_count": safe_int(profile.get("image_count")),
        "image_ratio": safe_float(profile.get("image_ratio")),
        "largest_image_ratio": safe_float(profile.get("largest_image_ratio")),
        "char_in_image_ratio": safe_float(profile.get("char_in_image_ratio")),
        "native_char_count": safe_int(profile.get("native_char_count")),
        "native_char_count_outside_images": safe_int(profile.get("native_char_count_outside_images")),
        "multi_column": bool(profile.get("multi_column")),
        "stage4_validation": str(upstream.get("stage4_validation") or "unknown"),
        "stage6_reading_status": str(upstream.get("stage6_reading_status") or "unknown"),
        "stage6_paragraph_status": str(upstream.get("stage6_paragraph_status") or "unknown"),
        "stage6_reading_ambiguity_count": safe_int(upstream.get("stage6_reading_ambiguity_count")),
        "stage6_invalid_block_count": safe_int(upstream.get("stage6_invalid_block_count")),
        "stage6_inherited_reading_risk": bool(upstream.get("stage6_inherited_reading_risk")),
        "stage6_risky_unsupported_empty_text_unit_count": safe_int(upstream.get("stage6_risky_unsupported_empty_text_unit_count")),
        "complexity_is_quality_failure": bool(complexity.get("is_quality_failure")),
        "complexity_reason_code": complexity.get("reason_code"),
    }


def page_quality_gate(page: dict[str, Any]) -> dict[str, Any]:
    page_number = safe_int(page.get("page_number"), -1)
    obs = page_observations(page)

    primary_type = obs["primary_type"]
    image_count = obs["image_count"]
    image_ratio = obs["image_ratio"]
    largest_image_ratio = obs["largest_image_ratio"]
    native_chars_outside_images = obs["native_char_count_outside_images"]
    useful_native_words = obs["useful_native_word_count"]
    accounted_final_flow = obs["accounted_final_flow_word_count"]
    non_text_unassessed = obs["non_text_unassessed_region_count"]
    unresolved_native = obs["unaccounted_native_word_count"]
    unaccounted_table_regions = obs["unaccounted_table_region_count"]
    accounting_ratio = obs["native_word_accounting_ratio"]
    stage4_status = obs["stage4_validation"]
    reading_status = obs["stage6_reading_status"]
    paragraph_status = obs["stage6_paragraph_status"]
    ambiguity_count = obs["stage6_reading_ambiguity_count"]
    invalid_block_count = obs["stage6_invalid_block_count"]
    inherited_reading_risk = obs["stage6_inherited_reading_risk"]
    risky_empty_count = obs["stage6_risky_unsupported_empty_text_unit_count"]
    complexity_level = obs["complexity_level"]
    complexity_is_failure = obs["complexity_is_quality_failure"]

    facts: list[dict[str, Any]] = []

    if primary_type == "scan_like":
        add_fact(facts, "SCAN_LIKE_PAGE", "high", primary_type, "Stage1 将页面判为 scan_like；这表示主要内容可能不在可靠 native 文本层中。")
    elif primary_type == "mixed_image_text":
        add_fact(facts, "MIXED_IMAGE_TEXT_PAGE", "info", primary_type, "页面同时包含 native text 与较明显图像内容，本身不构成失败。")
    elif primary_type == "sparse":
        add_fact(facts, "SPARSE_PAGE", "info", primary_type, "native 内容较稀疏；只作为页面形态信息，不单独触发 fallback。")

    if useful_native_words == 0:
        add_fact(facts, "NO_USEFUL_NATIVE_CONTENT", "high" if primary_type == "scan_like" else "medium", useful_native_words, "最终 native flow 中没有正文、表格或 final-flow 可用 word。")

    image_dominant = largest_image_ratio >= IMAGE_DOMINANT_LARGEST_RATIO or image_ratio >= IMAGE_DOMINANT_TOTAL_RATIO
    if image_dominant:
        add_fact(facts, "IMAGE_DOMINANT", "medium", {"image_ratio": round(image_ratio, 4), "largest_image_ratio": round(largest_image_ratio, 4)}, "图像覆盖占比较高；该事实只辅助 scan-like/OCR 判断，不单独触发整页 OCR。")

    if non_text_unassessed > 0:
        add_fact(facts, "UNASSESSED_NON_TEXT_PRESENT", "low", non_text_unassessed, "Stage7 保留了尚未判断语义价值的非文本区域。")
    if unresolved_native > 0:
        add_fact(facts, "UNACCOUNTED_NATIVE_EVIDENCE", "high", unresolved_native, "Stage1 native word 在 Stage1~6 final flow 后仍无法解释。")
    if unaccounted_table_regions > 0:
        add_fact(facts, "UNACCOUNTED_TABLE_REGION", "high", unaccounted_table_regions, "存在未被最终 flow 正式解释的 table region。")
    if accounting_ratio + ACCOUNTING_RATIO_EPSILON < 1.0:
        add_fact(facts, "INCOMPLETE_NATIVE_ACCOUNTING", "high", round(accounting_ratio, 6), "Stage7 native accounting 未达到完整归账。")
    if stage4_status != "PASS":
        add_fact(facts, "STAGE4_VALIDATION_NOT_PASS", "high", stage4_status, "Stage4 结构构建内部一致性未通过。")
    if reading_status != "resolved":
        add_fact(facts, "STAGE6_READING_NOT_RESOLVED", "high", reading_status, "Stage6 阅读顺序没有达到 resolved。")
    if paragraph_status != "completed":
        add_fact(facts, "STAGE6_PARAGRAPH_NOT_COMPLETED", "high", paragraph_status, "Stage6 段落重建没有达到 completed。")
    if ambiguity_count > 0:
        add_fact(facts, "STAGE6_READING_AMBIGUITY", "medium", ambiguity_count, "Stage6 reading order 仍存在显式 ambiguity。")
    if invalid_block_count > 0:
        add_fact(facts, "STAGE6_INVALID_BLOCKS", "high", invalid_block_count, "Stage6 reading order 中仍存在 invalid block。")
    if inherited_reading_risk:
        add_fact(facts, "INHERITED_READING_RISK", "medium", True, "Stage6 paragraph 继承了上游 reading-order 风险。")
    if risky_empty_count > 0:
        add_fact(facts, "RISKY_UNSUPPORTED_EMPTY_TEXT", "high", risky_empty_count, "存在缺少 Stage1 word 支持的非平凡空 text unit。")
    if accounted_final_flow > 0:
        add_fact(facts, "FINAL_FLOW_RECONCILIATION_USED", "info", accounted_final_flow, "历史 Stage1 raw anomaly 已由 Stage6 final flow 解释；保留 provenance，但不自动判失败。")
    if obs["multi_column"]:
        add_fact(facts, "MULTI_COLUMN_PAGE", "info", True, "页面具有多栏证据；若 Stage6 已 resolved，则不单独触发 fallback。")
    if complexity_level in {"high", "very_high"}:
        add_fact(facts, "HIGH_COMPLEXITY_PRIOR", "info", {"level": complexity_level, "reason_code": obs["complexity_reason_code"]}, "模板/章节先验提示页面复杂，但 complexity prior 本身不是质量失败。")
    if complexity_is_failure:
        add_fact(facts, "UPSTREAM_COMPLEXITY_FAILURE", "high", True, "上游 complexity prior 明确标记为 quality failure。")

    scan_evidence_present = non_text_unassessed > 0 or image_count > 0 or image_dominant
    scan_native_is_weak = useful_native_words == 0 or native_chars_outside_images <= 20 or image_dominant

    if primary_type == "scan_like" and scan_evidence_present and scan_native_is_weak:
        decision = DECISION_OCR_REQUIRED
        route = "ocr"
        route_confidence = "high" if useful_native_words == 0 else "medium"
        reason = "页面被 Stage1 判为 scan_like，且 image/non-text 证据占主导，native final flow 无法代表主要页面内容。"
    else:
        layout_failure = (
            unresolved_native > 0
            or unaccounted_table_regions > 0
            or accounting_ratio + ACCOUNTING_RATIO_EPSILON < 1.0
            or stage4_status != "PASS"
            or reading_status != "resolved"
            or paragraph_status != "completed"
            or ambiguity_count > 0
            or invalid_block_count > 0
            or inherited_reading_risk
            or risky_empty_count > 0
            or complexity_is_failure
        )

        if layout_failure:
            decision = DECISION_LAYOUT_FALLBACK_REQUIRED
            route = "layout_fallback"
            route_confidence = "high" if any([
                unresolved_native > 0,
                unaccounted_table_regions > 0,
                stage4_status != "PASS",
                reading_status != "resolved",
                paragraph_status != "completed",
                invalid_block_count > 0,
                risky_empty_count > 0,
            ]) else "medium"
            reason = "native 内容/结构证据仍存在未闭合或上游结构风险，应交给成熟 layout parser 重新解析。"
        elif non_text_unassessed > 0:
            decision = DECISION_NATIVE_PASS_WITH_NON_TEXT
            route = "native"
            route_confidence = "high"
            reason = "native 正文/表格证据闭合，但仍有未评估的非文本区域；保留 native 结果，不执行整页 fallback。"
        else:
            decision = DECISION_NATIVE_PASS
            route = "native"
            route_confidence = "high"
            reason = "native 内容与结构证据闭合，当前页无需 fallback。"

    if decision in {DECISION_OCR_REQUIRED, DECISION_LAYOUT_FALLBACK_REQUIRED}:
        gate_state = GATE_HARD_FALLBACK
    elif decision == DECISION_NATIVE_PASS_WITH_NON_TEXT:
        gate_state = GATE_UNCERTAIN
    else:
        gate_state = GATE_HARD_PASS

    return {
        "page_number": page_number,
        "decision": decision,
        "route": route,
        "gate_state": gate_state,
        # compatibility alias; semantic name below is preferred
        "confidence": route_confidence,
        "route_confidence": route_confidence,
        "reason": reason,
        "risk_facts": facts,
        "observations": obs,
        "region_followup": "lightweight_probe" if gate_state == GATE_UNCERTAIN else None,
    }



def classify_non_text_region(
    page: dict[str, Any],
    page_result: dict[str, Any],
    region: dict[str, Any],
) -> dict[str, Any]:
    geometry_page = page.get("page_geometry") or {}
    page_width = safe_float(geometry_page.get("width"))
    page_height = safe_float(geometry_page.get("height"))
    geom = bbox_geometry(region.get("bbox"), page_width, page_height)
    area_ratio = safe_float(geom.get("area_ratio"))

    obs = page_result.get("observations") or {}
    primary_type = str(obs.get("primary_type") or "unknown")
    useful_native_words = safe_int(obs.get("useful_native_word_count"))
    page_decision = page_result.get("decision")

    if (
        page_decision == DECISION_OCR_REQUIRED
        and primary_type == "scan_like"
        and useful_native_words == 0
        and area_ratio >= FULL_PAGE_SCAN_MIN_AREA_RATIO
    ):
        classification = REGION_FULL_PAGE_SCAN
        geometry_action = REGION_ACTION_PAGE_OCR
        confidence = "high"
        review_priority = "high"
        rationale = "scan_like 页面无 useful native 内容，且该非文本区域覆盖至少半页；几何证据足以支持整页 OCR。"
    elif area_ratio <= TINY_NON_TEXT_MAX_AREA_RATIO:
        classification = REGION_TINY_FRAGMENT
        geometry_action = REGION_ACTION_PRESERVE
        confidence = "high" if page_result.get("route") == "native" else "medium"
        review_priority = "very_low"
        rationale = "区域面积极小；几何层只降低优先级，不再把它直接宣布为语义安全。"
    elif area_ratio <= SMALL_NON_TEXT_MAX_AREA_RATIO:
        classification = REGION_SMALL
        geometry_action = REGION_ACTION_PRESERVE
        confidence = "medium"
        review_priority = "low"
        rationale = "区域占页较小；几何层只保留 native 主结果，最终是否需要区域 fallback 交给 raster probe。"
    elif area_ratio <= MEDIUM_NON_TEXT_MAX_AREA_RATIO:
        classification = REGION_MEDIUM
        geometry_action = REGION_ACTION_REVIEW
        confidence = "medium"
        review_priority = "medium"
        rationale = "区域占页达到可感知规模；进入 raster probe 判断是否需要 region OCR / layout fallback。"
    else:
        classification = REGION_LARGE
        geometry_action = REGION_ACTION_REVIEW
        confidence = "high" if area_ratio >= 0.15 else "medium"
        review_priority = "high"
        rationale = "区域占页较大；native 主文本不整页回退，但该区域必须进入 raster probe。"

    return {
        "region_id": region.get("region_id"),
        "region_type": region.get("region_type"),
        "source_image_index": region.get("source_image_index"),
        "source_refs": region.get("source_refs") or [],
        "bbox": region.get("bbox"),
        "geometry": geom,
        "classification": classification,
        "geometry_action": geometry_action,
        "action": geometry_action,
        "assessment_confidence": confidence,
        "review_priority": review_priority,
        "assessment_basis": "stage7_geometry_and_upstream_evidence_plus_stage8_raster_probe",
        "content_semantics": "not_claimed_without_parser_or_ocr",
        "rationale": rationale,
    }


def _require_probe_dependencies() -> tuple[Any, Any]:
    """Reuse the existing pdfplumber stack; no OCR/layout engine is loaded here."""
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Stage8 v0.3.2 Lightweight Probe 复用现有 pdfplumber。当前环境缺少它，请先恢复 Stage1~6 的项目依赖。"
        ) from exc
    try:
        from PIL import ImageFilter  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Stage8 v0.3.2 Lightweight Probe 需要 Pillow（pdfplumber 常规依赖）。请检查项目依赖。"
        ) from exc
    return pdfplumber, ImageFilter


def _adaptive_probe_dpi(region_bbox: Any, base_dpi: int) -> int:
    if not isinstance(region_bbox, dict):
        return base_dpi
    w_pt = max(0.0, safe_float(region_bbox.get("x1")) - safe_float(region_bbox.get("x0")))
    h_pt = max(0.0, safe_float(region_bbox.get("bottom")) - safe_float(region_bbox.get("top")))
    short_pt = min(w_pt, h_pt) if w_pt > 0 and h_pt > 0 else 0.0
    if short_pt <= 0:
        return base_dpi
    need = math.ceil(MIN_PROBE_SHORT_SIDE_PX * 72.0 / short_pt)
    return max(base_dpi, min(MAX_ADAPTIVE_PROBE_DPI, need))


def _render_region_rgb(
    pdf_page: Any,
    manifest_page: dict[str, Any],
    region: dict[str, Any],
    base_dpi: int,
) -> tuple[Any, dict[str, Any]]:
    """Render only the named bbox through pdfplumber's existing page renderer."""
    page_geom = manifest_page.get("page_geometry") or {}
    manifest_w = safe_float(page_geom.get("width"))
    manifest_h = safe_float(page_geom.get("height"))
    bbox = region.get("bbox") or {}
    if manifest_w <= 0 or manifest_h <= 0 or not isinstance(bbox, dict):
        raise ValueError("region bbox/page_geometry 无效，无法做 lightweight probe。")

    # Stage7 geometry is produced in pdfplumber-style (x0, top, x1, bottom).
    # Normalize if the actual page dimensions differ slightly.
    sx = safe_float(getattr(pdf_page, "width", 0.0)) / manifest_w
    sy = safe_float(getattr(pdf_page, "height", 0.0)) / manifest_h
    if sx <= 0 or sy <= 0:
        raise ValueError("PDF page 尺寸无效。")

    x0 = max(0.0, safe_float(bbox.get("x0")) * sx)
    top = max(0.0, safe_float(bbox.get("top")) * sy)
    x1 = min(safe_float(getattr(pdf_page, "width", 0.0)), safe_float(bbox.get("x1")) * sx)
    bottom = min(safe_float(getattr(pdf_page, "height", 0.0)), safe_float(bbox.get("bottom")) * sy)
    if x1 <= x0 or bottom <= top:
        raise ValueError("region 映射到 PDF 后为空。")

    dpi = _adaptive_probe_dpi(bbox, base_dpi)
    cropped_page = pdf_page.crop((x0, top, x1, bottom), strict=False)
    image = cropped_page.to_image(resolution=dpi, antialias=True).original.convert("RGB")

    return image, {
        "renderer": "pdfplumber_page_to_image",
        "dpi": dpi,
        "pixel_width": int(image.width),
        "pixel_height": int(image.height),
        "pdf_clip": {
            "x0": round(x0, 4),
            "top": round(top, 4),
            "x1": round(x1, 4),
            "bottom": round(bottom, 4),
        },
        "manifest_to_pdf_scale": {"x": round(sx, 6), "y": round(sy, 6)},
    }


def _run_count(flags: list[bool], max_run: int | None = None) -> int:
    count = 0
    start: int | None = None
    for idx, value in enumerate(flags + [False]):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            length = idx - start
            if max_run is None or length <= max_run:
                count += 1
            start = None
    return count


def _max_true_run(flags: list[bool]) -> int:
    best = cur = 0
    for value in flags:
        if value:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _raster_metrics(ImageFilter: Any, rgb: Any) -> dict[str, Any]:
    """Cheap Pillow-only visual features. No OCR, no text recognition, no layout parsing."""
    # Cap analysis pixels; classification only needs coarse visual evidence.
    max_side = 900
    work = rgb
    if max(work.size) > max_side:
        scale = max_side / max(work.size)
        work = work.resize((max(1, int(work.width * scale)), max(1, int(work.height * scale))))

    gray = work.convert("L")
    w, h = gray.size
    total = max(1, w * h)
    hist = gray.histogram()
    mean = sum(i * c for i, c in enumerate(hist)) / total
    var = sum(((i - mean) ** 2) * c for i, c in enumerate(hist)) / total
    gray_std = math.sqrt(max(0.0, var))

    entropy = 0.0
    for c in hist:
        if c:
            p = c / total
            entropy -= p * math.log2(p)

    foreground = sum(hist[:245]) / total
    dark = sum(hist[:180]) / total
    white = sum(hist[245:]) / total

    # Edge density from Pillow's lightweight edge filter.
    edge_img = gray.filter(ImageFilter.FIND_EDGES)
    edge_hist = edge_img.histogram()
    edge_density = sum(edge_hist[36:]) / total

    # Downsample again for projection/transition analysis to keep loops cheap.
    proj_max_side = 420
    proj = gray
    if max(proj.size) > proj_max_side:
        scale = proj_max_side / max(proj.size)
        proj = proj.resize((max(1, int(proj.width * scale)), max(1, int(proj.height * scale))))
    pw, ph = proj.size
    pix = list(proj.get_flattened_data()) if hasattr(proj, "get_flattened_data") else list(proj.getdata())
    threshold = 205

    row_ratios: list[float] = []
    row_long_line = 0
    transition_sum = 0
    transition_den = 0
    sample_step = max(1, ph // 80)
    for y in range(ph):
        row = [pix[y * pw + x] < threshold for x in range(pw)]
        ink = sum(row)
        row_ratios.append(ink / max(1, pw))
        if _max_true_run(row) >= max(6, int(pw * 0.55)):
            row_long_line += 1
        if y % sample_step == 0:
            transition_sum += sum(1 for a, b in zip(row, row[1:]) if a != b)
            transition_den += max(1, pw - 1)

    col_ratios: list[float] = []
    col_long_line = 0
    for x in range(pw):
        col = [pix[y * pw + x] < threshold for y in range(ph)]
        ink = sum(col)
        col_ratios.append(ink / max(1, ph))
        if _max_true_run(col) >= max(6, int(ph * 0.45)):
            col_long_line += 1

    active_rows = [r > max(0.008, min(0.10, foreground * 0.55)) for r in row_ratios]
    row_band_count = _run_count(active_rows, max_run=max(2, int(ph * 0.25)))
    active_cols = [r > max(0.008, min(0.12, foreground * 0.65)) for r in col_ratios]
    column_band_count = _run_count(active_cols, max_run=max(2, int(pw * 0.35)))

    transition_density = transition_sum / max(1, transition_den)
    horizontal_line_ratio = row_long_line / max(1, ph)
    vertical_line_ratio = col_long_line / max(1, pw)
    structure_line_ratio = horizontal_line_ratio + vertical_line_ratio

    low_information = foreground < 0.0015 or (gray_std < 3.0 and entropy < 1.0)

    # Candidate scores: deliberately coarse, used only to choose a Stage9 route.
    band_score = clamp01(row_band_count / 8.0)
    col_band_score = clamp01(column_band_count / 10.0)
    transition_score = clamp01(transition_density / 0.18)
    edge_score = clamp01(edge_density / 0.22)
    if 0.006 <= foreground <= 0.55:
        foreground_score = 1.0
    elif foreground < 0.006:
        foreground_score = clamp01(foreground / 0.006)
    else:
        foreground_score = clamp01((0.90 - foreground) / 0.35)

    text_score = (
        0.34 * band_score
        + 0.18 * col_band_score
        + 0.24 * transition_score
        + 0.14 * edge_score
        + 0.10 * foreground_score
    )
    line_score = clamp01(structure_line_ratio / 0.035)
    structure_score = 0.62 * line_score + 0.20 * edge_score + 0.18 * band_score
    entropy_score = clamp01((entropy - 4.0) / 3.0)
    std_score = clamp01((gray_std - 18.0) / 52.0)
    photo_score = clamp01(
        0.45 * entropy_score
        + 0.30 * std_score
        + 0.20 * edge_score
        - 0.22 * line_score
        - 0.08 * band_score
    )

    return {
        "gray_mean": round(mean, 4),
        "gray_std": round(gray_std, 4),
        "entropy": round(entropy, 4),
        "foreground_ratio": round(foreground, 6),
        "dark_pixel_ratio": round(dark, 6),
        "white_background_ratio": round(white, 6),
        "edge_density": round(edge_density, 6),
        "row_band_count": int(row_band_count),
        "column_band_count": int(column_band_count),
        "transition_density": round(transition_density, 6),
        "horizontal_line_ratio": round(horizontal_line_ratio, 6),
        "vertical_line_ratio": round(vertical_line_ratio, 6),
        "structure_line_ratio": round(structure_line_ratio, 6),
        "text_score": round(text_score, 6),
        "structure_score": round(structure_score, 6),
        "photo_score": round(photo_score, 6),
        "low_information": bool(low_information),
        "analysis_width": pw,
        "analysis_height": ph,
    }


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _classify_raster_probe(
    metrics: dict[str, Any],
    geometry_classification: str,
    fragment_cluster_member: bool,
) -> tuple[str, str, str, str, dict[str, Any]]:
    """Return a generic Stage8 region decision plus non-binding visual hints.

    v0.3.1 deliberately does NOT choose OCR vs layout. The cheap probe answers only:
    can we safely preserve this raster, or does it carry enough/uncertain content to
    deserve one Stage9 fallback call?
    """
    text_score = safe_float(metrics.get("text_score"))
    structure_score = safe_float(metrics.get("structure_score"))
    photo_score = safe_float(metrics.get("photo_score"))
    entropy = safe_float(metrics.get("entropy"))
    row_bands = safe_int(metrics.get("row_band_count"))
    line_ratio = safe_float(metrics.get("structure_line_ratio"))

    text_like = text_score >= TEXT_SCORE_THRESHOLD and row_bands >= MIN_TEXT_ROW_BANDS
    structure_like = structure_score >= STRUCTURE_SCORE_THRESHOLD and line_ratio >= MIN_STRUCTURE_LINE_RATIO
    photo_like = photo_score >= AUXILIARY_PHOTO_MIN_SCORE and entropy >= AUXILIARY_PHOTO_MIN_ENTROPY
    clear_auxiliary_photo = (
        photo_like
        and text_score < AUXILIARY_PHOTO_MAX_TEXT_SCORE
    )

    hints = {
        "text_like": bool(text_like),
        "structure_like": bool(structure_like),
        "photo_like": bool(photo_like),
        "conflicting_signals": bool(sum([text_like, structure_like, photo_like]) >= 2),
        "note": "probe hints only; Stage8 v0.3.2 does not map these hints to OCR/layout engine choice",
    }

    if metrics.get("low_information"):
        return (
            RASTER_LOW_INFORMATION,
            REGION_ACTION_PRESERVE,
            "high",
            "局部 raster 信息量极低；当前没有证据要求进入 Stage9 region fallback。",
            hints,
        )

    # Photo/continuous-tone override is intentionally evaluated before line heuristics.
    # Real photos often contain strong long edges (device borders, crop borders, etc.) and
    # were incorrectly routed to layout in v0.3.0.
    if clear_auxiliary_photo:
        return (
            RASTER_AUXILIARY_IMAGE,
            REGION_ACTION_PRESERVE,
            "medium",
            "局部 raster 呈明显连续色调/照片型特征，且缺少强文字型证据；Stage8 保留该图，不提前指定解析引擎。",
            hints,
        )

    if text_like or structure_like:
        classification = RASTER_AMBIGUOUS_CONTENT if hints["conflicting_signals"] else RASTER_CONTENT_BEARING
        return (
            classification,
            FINAL_REGION_ACTION_FALLBACK,
            "medium",
            "局部 raster 明显承载内容或存在多种视觉信号；Stage8 只判定需要 region fallback，OCR/layout/vision 选择交给 Stage9。",
            hints,
        )

    # If the probe cannot confidently prove that the raster is low-information or an
    # auxiliary continuous-tone image, do not declare it safe. This is intentionally
    # asymmetric: uncertain content is routed to one generic Stage9 fallback.
    return (
        RASTER_AMBIGUOUS_CONTENT,
        FINAL_REGION_ACTION_FALLBACK,
        "low",
        "轻量视觉证据不足以证明该区域可安全忽略；Stage8 保守标记为通用 region fallback candidate。",
        hints,
    )

def raster_probe_region(
    ImageFilter: Any,
    pdf_page: Any,
    manifest_page: dict[str, Any],
    region_source: dict[str, Any],
    region_assessment: dict[str, Any],
    base_dpi: int,
    debug_crop_dir: Path | None,
) -> dict[str, Any]:
    # Hard-fallback pages already have a stronger route; do not "probe to decide whether to fallback".
    if region_assessment.get("geometry_action") == REGION_ACTION_PAGE_OCR:
        return {
            "probe_completed": False,
            "probe_skipped": True,
            "skip_reason": "hard_page_fallback_already_decided",
            "classification": RASTER_SKIPPED_PAGE_OCR,
            "final_action": REGION_ACTION_PAGE_OCR,
            "probe_confidence": "high",
            "metrics": {},
            "reason": "页面已有硬 OCR 证据；Stage8 不重复看图。",
        }

    try:
        rgb, render_meta = _render_region_rgb(pdf_page, manifest_page, region_source, base_dpi)
        metrics = _raster_metrics(ImageFilter, rgb)
        classification, final_action, confidence, reason, probe_hints = _classify_raster_probe(
            metrics,
            str(region_assessment.get("classification")),
            bool(region_assessment.get("fragment_cluster_member")),
        )
        crop_path = None
        if debug_crop_dir is not None:
            debug_crop_dir.mkdir(parents=True, exist_ok=True)
            safe_rid = str(region_assessment.get("region_id") or "region").replace("/", "_")
            crop_file = debug_crop_dir / f"p{safe_int(manifest_page.get('page_number')):04d}_{safe_rid}.png"
            rgb.save(crop_file, format="PNG")
            crop_path = str(crop_file)

        return {
            "probe_completed": True,
            "probe_skipped": False,
            "classification": classification,
            "final_action": final_action,
            "probe_confidence": confidence,
            "render": render_meta,
            "metrics": metrics,
            "probe_hints": probe_hints,
            "reason": reason,
            "debug_crop": crop_path,
        }
    except Exception as exc:
        return {
            "probe_completed": False,
            "probe_skipped": False,
            "classification": RASTER_AMBIGUOUS_CONTENT,
            "final_action": FINAL_REGION_ACTION_FALLBACK,
            "probe_confidence": "low",
            "render": {},
            "metrics": {},
            "reason": "Lightweight probe 执行失败；不把失败误判为安全，保守进入通用 region fallback。",
            "error": f"{type(exc).__name__}: {exc}",
            "debug_crop": None,
        }


def _bbox_union_dict(bboxes: list[dict[str, Any]]) -> dict[str, float] | None:
    valid = [b for b in bboxes if isinstance(b, dict) and safe_float(b.get("x1")) > safe_float(b.get("x0")) and safe_float(b.get("bottom")) > safe_float(b.get("top"))]
    if not valid:
        return None
    return {
        "x0": min(safe_float(b.get("x0")) for b in valid),
        "top": min(safe_float(b.get("top")) for b in valid),
        "x1": max(safe_float(b.get("x1")) for b in valid),
        "bottom": max(safe_float(b.get("bottom")) for b in valid),
    }


def _interval_gap(a0: float, a1: float, b0: float, b1: float) -> float:
    if a1 < b0:
        return b0 - a1
    if b1 < a0:
        return a0 - b1
    return 0.0


def _clip_expand_bbox(bbox: dict[str, Any], page: dict[str, Any], padding: float) -> dict[str, float]:
    geom = page.get("page_geometry") or {}
    pw = safe_float(geom.get("width"))
    ph = safe_float(geom.get("height"))
    return {
        "x0": round(max(0.0, safe_float(bbox.get("x0")) - padding), 4),
        "top": round(max(0.0, safe_float(bbox.get("top")) - padding), 4),
        "x1": round(min(pw, safe_float(bbox.get("x1")) + padding), 4),
        "bottom": round(min(ph, safe_float(bbox.get("bottom")) + padding), 4),
    }


def _axis_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _bbox_coverage_ratio(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    ix0 = max(safe_float(inner.get("x0")), safe_float(outer.get("x0")))
    iy0 = max(safe_float(inner.get("top")), safe_float(outer.get("top")))
    ix1 = min(safe_float(inner.get("x1")), safe_float(outer.get("x1")))
    iy1 = min(safe_float(inner.get("bottom")), safe_float(outer.get("bottom")))
    iw = max(0.0, ix1 - ix0)
    ih = max(0.0, iy1 - iy0)
    inner_w = max(0.0, safe_float(inner.get("x1")) - safe_float(inner.get("x0")))
    inner_h = max(0.0, safe_float(inner.get("bottom")) - safe_float(inner.get("top")))
    denom = inner_w * inner_h
    return (iw * ih / denom) if denom > 0 else 0.0


def _inline_context_affinity(raster_bbox: dict[str, Any], text_bbox: dict[str, Any]) -> dict[str, Any]:
    rx0 = safe_float(raster_bbox.get("x0")); rx1 = safe_float(raster_bbox.get("x1"))
    rt = safe_float(raster_bbox.get("top")); rb = safe_float(raster_bbox.get("bottom"))
    tx0 = safe_float(text_bbox.get("x0")); tx1 = safe_float(text_bbox.get("x1"))
    tt = safe_float(text_bbox.get("top")); tb = safe_float(text_bbox.get("bottom"))
    rw = max(0.0, rx1 - rx0); rh = max(0.0, rb - rt)
    h_overlap = _axis_overlap(rx0, rx1, tx0, tx1)
    v_overlap = _axis_overlap(rt, rb, tt, tb)
    h_overlap_ratio = h_overlap / rw if rw > 0 else 0.0
    v_overlap_ratio = v_overlap / rh if rh > 0 else 0.0
    hgap = _interval_gap(rx0, rx1, tx0, tx1)
    vgap = _interval_gap(rt, rb, tt, tb)
    tight_adjacent = vgap <= INLINE_SINGLETON_MAX_TIGHT_GAP_PT and hgap <= INLINE_SINGLETON_MAX_TIGHT_GAP_PT
    strong_overlap = (
        v_overlap_ratio >= INLINE_SINGLETON_MIN_VERTICAL_OVERLAP_RATIO
        and (h_overlap_ratio >= INLINE_SINGLETON_MIN_HORIZONTAL_OVERLAP_RATIO or hgap <= INLINE_TEXT_HORIZONTAL_GAP_PT)
    )
    return {
        "eligible": bool(strong_overlap or tight_adjacent),
        "vertical_overlap_ratio": round(v_overlap_ratio, 6),
        "horizontal_overlap_ratio": round(h_overlap_ratio, 6),
        "vertical_gap_pt": round(vgap, 4),
        "horizontal_gap_pt": round(hgap, 4),
        "strong_overlap": bool(strong_overlap),
        "tight_adjacent": bool(tight_adjacent),
    }


def _localized_inline_context_bbox(
    page: dict[str, Any],
    member_bbox: dict[str, Any],
    context_regions: list[dict[str, Any]],
) -> dict[str, float] | None:
    context_union = _bbox_union_dict([(ctx.get("bbox") or {}) for ctx in context_regions])
    if not context_union:
        return None
    # Keep the horizontal native-text context, but localize vertically around the raster members.
    # This prevents a large paragraph/container bbox from turning a singleton inline glyph into a huge crop.
    local = {
        "x0": min(safe_float(member_bbox.get("x0")), safe_float(context_union.get("x0"))),
        "top": safe_float(member_bbox.get("top")),
        "x1": max(safe_float(member_bbox.get("x1")), safe_float(context_union.get("x1"))),
        "bottom": safe_float(member_bbox.get("bottom")),
    }
    return _clip_expand_bbox(local, page, INLINE_CONTEXT_PADDING_PT)


def _nearest_accounted_text_context(page: dict[str, Any], tiny_bbox: dict[str, Any]) -> dict[str, Any] | None:
    tx0 = safe_float(tiny_bbox.get("x0")); tx1 = safe_float(tiny_bbox.get("x1"))
    tt = safe_float(tiny_bbox.get("top")); tb = safe_float(tiny_bbox.get("bottom"))
    best: tuple[float, dict[str, Any]] | None = None
    for region in page.get("regions") or []:
        if not isinstance(region, dict):
            continue
        if region.get("region_type") != "text" or region.get("accounting_status") != "ACCOUNTED_TEXT":
            continue
        b = region.get("bbox") or {}
        x0 = safe_float(b.get("x0")); x1 = safe_float(b.get("x1"))
        top = safe_float(b.get("top")); bottom = safe_float(b.get("bottom"))
        if x1 <= x0 or bottom <= top:
            continue
        vgap = _interval_gap(tt, tb, top, bottom)
        hgap = _interval_gap(tx0, tx1, x0, x1)
        if vgap > INLINE_TEXT_VERTICAL_GAP_PT or hgap > INLINE_TEXT_HORIZONTAL_GAP_PT:
            continue
        # Prefer the nearest line/block, while mildly penalizing very large text containers.
        score = 2.0 * vgap + hgap + 0.002 * ((x1 - x0) * (bottom - top))
        if best is None or score < best[0]:
            best = (score, region)
    return best[1] if best else None


def build_inline_raster_clusters(
    page: dict[str, Any],
    assessments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build generic inline-raster contexts from geometry and accounted-text adjacency.

    This is intentionally content-agnostic: no page id, region id, character, formula, or
    document-specific exception is used. Multi-member groups are accepted when nearby tiny
    rasters share native-text context. A singleton tiny raster is accepted only when its
    overlap/adjacency to accounted native text is strong enough.
    """
    tiny = [a for a in assessments if a.get("classification") == REGION_TINY_FRAGMENT]
    if not tiny:
        return []

    raw_groups: dict[str, dict[str, Any]] = {}
    for item in tiny:
        b = item.get("bbox") or {}
        ctx = _nearest_accounted_text_context(page, b)
        if not ctx:
            continue
        ctx_id = str(ctx.get("region_id") or "")
        if not ctx_id:
            continue
        evidence = _inline_context_affinity(b, ctx.get("bbox") or {})
        slot = raw_groups.setdefault(ctx_id, {"context_regions": [ctx], "members": [], "member_evidence": {}})
        slot["members"].append(item)
        slot["member_evidence"][str(item.get("region_id"))] = evidence

    # Merge groups that lie on the same visual line. This is based only on member geometry,
    # allowing a formula/inline run split across adjacent native-text blocks to stay together.
    groups = list(raw_groups.values())
    changed = True
    while changed:
        changed = False
        merged: list[dict[str, Any]] = []
        used = [False] * len(groups)
        for i, g in enumerate(groups):
            if used[i]:
                continue
            base = {
                "context_regions": list(g["context_regions"]),
                "members": list(g["members"]),
                "member_evidence": dict(g.get("member_evidence") or {}),
            }
            used[i] = True
            for j in range(i + 1, len(groups)):
                if used[j]:
                    continue
                a_bbox = _bbox_union_dict([m.get("bbox") or {} for m in base["members"]])
                b_bbox = _bbox_union_dict([m.get("bbox") or {} for m in groups[j]["members"]])
                if not a_bbox or not b_bbox:
                    continue
                ac = (safe_float(a_bbox.get("top")) + safe_float(a_bbox.get("bottom"))) / 2.0
                bc = (safe_float(b_bbox.get("top")) + safe_float(b_bbox.get("bottom"))) / 2.0
                hgap = _interval_gap(
                    safe_float(a_bbox.get("x0")), safe_float(a_bbox.get("x1")),
                    safe_float(b_bbox.get("x0")), safe_float(b_bbox.get("x1")),
                )
                if abs(ac - bc) <= 12.0 and hgap <= 180.0:
                    base["members"].extend(groups[j]["members"])
                    base["context_regions"].extend(groups[j]["context_regions"])
                    base["member_evidence"].update(groups[j].get("member_evidence") or {})
                    used[j] = True
                    changed = True
            merged.append(base)
        groups = merged

    clusters: list[dict[str, Any]] = []
    page_number = safe_int(page.get("page_number"), -1)
    seq = 1
    for group in groups:
        members = group["members"]
        if not members:
            continue
        mode = "multi_member_cluster" if len(members) >= INLINE_CLUSTER_MIN_MEMBERS else "singleton_inline_context"
        if len(members) == 1:
            rid = str(members[0].get("region_id") or "")
            evidence = (group.get("member_evidence") or {}).get(rid) or {}
            if not evidence.get("eligible"):
                continue

        member_bbox = _bbox_union_dict([m.get("bbox") or {} for m in members])
        context_regions = []
        seen_ctx: set[str] = set()
        for ctx in group["context_regions"]:
            rid = str(ctx.get("region_id") or "")
            if rid and rid not in seen_ctx:
                seen_ctx.add(rid)
                context_regions.append(ctx)
        if not member_bbox or not context_regions:
            continue
        context_bbox = _localized_inline_context_bbox(page, member_bbox, context_regions)
        if not context_bbox:
            continue
        cluster_id = f"p{page_number:04d}_inline_context_{seq:03d}"
        seq += 1
        reason = (
            "tiny raster 与 accounted native-text 具有稳定邻接/重叠关系；Stage9 应按局部上下文处理，而不是逐 glyph 调用。"
            if mode == "singleton_inline_context"
            else "多个 tiny raster 共享相邻 accounted native-text 上下文；Stage9 应按局部上下文一次处理，而不是逐 glyph 调用。"
        )
        clusters.append({
            "cluster_id": cluster_id,
            "classification": "INLINE_RASTER_CONTEXT",
            "context_mode": mode,
            "action": FINAL_REGION_ACTION_FALLBACK,
            "member_region_ids": [str(m.get("region_id")) for m in members],
            "member_count": len(members),
            "member_union_bbox": member_bbox,
            "context_region_ids": [str(ctx.get("region_id")) for ctx in context_regions],
            "context_bbox": context_bbox,
            "member_context_evidence": group.get("member_evidence") or {},
            "reason": reason,
        })
    return clusters


def _covered_by_inline_context(
    page: dict[str, Any],
    item: dict[str, Any],
    inline_contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return a context that already subsumes a small standalone raster candidate.

    The rule is generic and conservative: only tiny/small regions may be absorbed, the
    context crop must cover almost the whole region, and both must resolve to the same
    nearby accounted-text context. Large/medium figures are never suppressed by this rule.
    """
    if item.get("classification") not in {REGION_TINY_FRAGMENT, REGION_SMALL}:
        return None
    area_ratio = safe_float((item.get("geometry") or {}).get("area_ratio"))
    if area_ratio > INLINE_CONTEXT_MAX_COVERED_AREA_RATIO:
        return None
    bbox = item.get("bbox") or {}
    nearest = _nearest_accounted_text_context(page, bbox)
    nearest_id = str((nearest or {}).get("region_id") or "")
    if not nearest_id:
        return None
    for context in inline_contexts:
        if str(item.get("region_id") or "") in set(context.get("member_region_ids") or []):
            continue
        if nearest_id not in set(context.get("context_region_ids") or []):
            continue
        coverage = _bbox_coverage_ratio(bbox, context.get("context_bbox") or {})
        if coverage >= INLINE_CONTEXT_COVERAGE_RATIO:
            return {
                "cluster_id": context.get("cluster_id"),
                "coverage_ratio": round(coverage, 6),
                "shared_context_region_id": nearest_id,
            }
    return None

def raster_probe_inline_cluster(
    ImageFilter: Any,
    pdf_page: Any,
    manifest_page: dict[str, Any],
    cluster: dict[str, Any],
    base_dpi: int,
    debug_crop_dir: Path | None,
) -> dict[str, Any]:
    try:
        pseudo_region = {"bbox": cluster.get("context_bbox") or {}, "region_id": cluster.get("cluster_id")}
        rgb, render_meta = _render_region_rgb(pdf_page, manifest_page, pseudo_region, base_dpi)
        metrics = _raster_metrics(ImageFilter, rgb)
        _classification, _action, confidence, _reason, probe_hints = _classify_raster_probe(
            metrics, REGION_TINY_FRAGMENT, True
        )
        crop_path = None
        if debug_crop_dir is not None:
            debug_crop_dir.mkdir(parents=True, exist_ok=True)
            crop_file = debug_crop_dir / f"p{safe_int(manifest_page.get('page_number')):04d}_{cluster.get('cluster_id')}.png"
            rgb.save(crop_file, format="PNG")
            crop_path = str(crop_file)
        return {
            "probe_completed": True,
            "probe_skipped": False,
            "classification": "INLINE_RASTER_CONTEXT",
            "final_action": FINAL_REGION_ACTION_FALLBACK,
            "probe_confidence": confidence,
            "render": render_meta,
            "metrics": metrics,
            "probe_hints": probe_hints,
            "reason": "该 probe 只用于记录整段公式/行内 raster 上下文特征；Stage8 不再逐 glyph 选择 OCR/layout。",
            "debug_crop": crop_path,
        }
    except Exception as exc:
        return {
            "probe_completed": False,
            "probe_skipped": False,
            "classification": "INLINE_RASTER_CONTEXT",
            "final_action": FINAL_REGION_ACTION_FALLBACK,
            "probe_confidence": "low",
            "render": {},
            "metrics": {},
            "probe_hints": {},
            "reason": "Inline raster context probe 失败；context 仍保守进入 Stage9 region fallback。",
            "error": f"{type(exc).__name__}: {exc}",
            "debug_crop": None,
        }


def assess_non_text_regions(
    page: dict[str, Any],
    page_result: dict[str, Any],
    ImageFilter: Any,
    pdf_page: Any,
    probe_dpi: int,
    debug_crop_dir: Path | None,
) -> dict[str, Any]:
    candidates = [
        region
        for region in page.get("regions", [])
        if isinstance(region, dict)
        and region.get("accounting_status") == "NON_TEXT_UNASSESSED"
    ]

    assessments = [
        classify_non_text_region(page, page_result, region)
        for region in candidates
    ]

    tiny = [item for item in assessments if item.get("classification") == REGION_TINY_FRAGMENT]
    tiny_total_area = sum(safe_float((item.get("geometry") or {}).get("area_ratio")) for item in tiny)
    fragment_cluster = (
        len(tiny) >= FRAGMENT_CLUSTER_MIN_COUNT
        and tiny_total_area <= FRAGMENT_CLUSTER_MAX_TOTAL_AREA_RATIO
    )

    inline_clusters = build_inline_raster_clusters(page, assessments)
    member_to_cluster: dict[str, str] = {}
    for cluster in inline_clusters:
        for rid in cluster.get("member_region_ids") or []:
            member_to_cluster[str(rid)] = str(cluster.get("cluster_id"))

    for item in assessments:
        rid = str(item.get("region_id") or "")
        item["fragment_cluster_member"] = item.get("classification") == REGION_TINY_FRAGMENT and fragment_cluster
        item["inline_cluster_id"] = member_to_cluster.get(rid)
        item["covered_by_inline_context"] = (
            None if item.get("inline_cluster_id") else _covered_by_inline_context(page, item, inline_clusters)
        )

    source_by_id = {region.get("region_id"): region for region in candidates}

    for item in assessments:
        source_region = source_by_id.get(item.get("region_id")) or {}
        cluster_id = item.get("inline_cluster_id")
        covered_context = item.get("covered_by_inline_context")
        if page_result.get("gate_state") == GATE_UNCERTAIN and cluster_id:
            probe = {
                "probe_completed": False,
                "probe_skipped": True,
                "skip_reason": "inline_cluster_member_uses_context_probe",
                "classification": RASTER_INLINE_CLUSTER_MEMBER,
                "final_action": FINAL_REGION_ACTION_DEFER_INLINE_CLUSTER,
                "probe_confidence": "high",
                "metrics": {},
                "probe_hints": {},
                "reason": f"该 tiny raster 已并入 {cluster_id}；不单独做视觉判定/Stage9 调用。",
            }
        elif page_result.get("gate_state") == GATE_UNCERTAIN and covered_context:
            probe = {
                "probe_completed": False,
                "probe_skipped": True,
                "skip_reason": "standalone_region_covered_by_inline_context",
                "classification": RASTER_COVERED_INLINE_CONTEXT,
                "final_action": FINAL_REGION_ACTION_COVERED_INLINE_CONTEXT,
                "probe_confidence": "high",
                "metrics": {},
                "probe_hints": {},
                "reason": (
                    f"该小区域已被 {covered_context.get('cluster_id')} 的局部上下文覆盖，"
                    "且共享同一 accounted-text context；Stage9 不重复处理。"
                ),
                "coverage": covered_context,
            }
        elif page_result.get("gate_state") == GATE_UNCERTAIN:
            probe = raster_probe_region(
                ImageFilter,
                pdf_page,
                page,
                source_region,
                item,
                probe_dpi,
                debug_crop_dir,
            )
        else:
            final_action = REGION_ACTION_PAGE_OCR if item.get("geometry_action") == REGION_ACTION_PAGE_OCR else item.get("geometry_action")
            probe = {
                "probe_completed": False,
                "probe_skipped": True,
                "skip_reason": "gate_state_not_uncertain",
                "classification": RASTER_SKIPPED_PAGE_OCR if final_action == REGION_ACTION_PAGE_OCR else "SKIPPED_NOT_NEEDED",
                "final_action": final_action,
                "probe_confidence": page_result.get("route_confidence"),
                "metrics": {},
                "probe_hints": {},
                "reason": "页面已经由硬证据完成路由；lightweight probe 仅用于 UNCERTAIN_NEEDS_PROBE。",
            }
        item["raster_probe"] = probe
        item["action"] = probe.get("final_action") or item.get("geometry_action")
        item["content_semantics"] = "not_semantically_classified_stage8"

    if page_result.get("gate_state") == GATE_UNCERTAIN:
        for cluster in inline_clusters:
            cluster["raster_probe"] = raster_probe_inline_cluster(
                ImageFilter,
                pdf_page,
                page,
                cluster,
                probe_dpi,
                debug_crop_dir,
            )

    class_counts = Counter(item["classification"] for item in assessments)
    geometry_action_counts = Counter(item["geometry_action"] for item in assessments)
    final_action_counts = Counter(item["action"] for item in assessments)
    raster_class_counts = Counter(
        (item.get("raster_probe") or {}).get("classification")
        for item in assessments
        if (item.get("raster_probe") or {}).get("classification")
    )

    region_fallback_ids = [item["region_id"] for item in assessments if item["action"] == FINAL_REGION_ACTION_FALLBACK]
    inline_deferred_ids = [item["region_id"] for item in assessments if item["action"] == FINAL_REGION_ACTION_DEFER_INLINE_CLUSTER]
    covered_inline_ids = [item["region_id"] for item in assessments if item["action"] == FINAL_REGION_ACTION_COVERED_INLINE_CONTEXT]
    page_ocr_ids = [item["region_id"] for item in assessments if item["action"] == REGION_ACTION_PAGE_OCR]
    preserve_ids = [item["region_id"] for item in assessments if item["action"] == REGION_ACTION_PRESERVE]

    if page_result.get("decision") == DECISION_OCR_REQUIRED:
        completeness = "NATIVE_INCOMPLETE_PAGE_OCR_REQUIRED"
    elif page_result.get("decision") == DECISION_LAYOUT_FALLBACK_REQUIRED:
        completeness = "NATIVE_STRUCTURE_UNRELIABLE"
    elif region_fallback_ids or inline_clusters:
        completeness = "NATIVE_TEXT_COMPLETE_REGION_FALLBACK_REQUIRED"
    elif assessments:
        completeness = "NATIVE_TEXT_COMPLETE_NON_TEXT_RASTER_ASSESSED"
    else:
        completeness = "NATIVE_CONTENT_COMPLETE_FOR_AVAILABLE_EVIDENCE"

    return {
        "assessment_completed": True,
        "assessment_scope": "hard_gate_then_uncertain_only_probe_generic_region_fallback_v3",
        "region_count": len(assessments),
        "classification_counts": dict(class_counts),
        "geometry_action_counts": dict(geometry_action_counts),
        "raster_classification_counts": dict(raster_class_counts),
        "action_counts": dict(final_action_counts),
        "fragment_cluster_detected": fragment_cluster,
        "fragment_cluster_tiny_region_count": len(tiny) if fragment_cluster else 0,
        "fragment_cluster_total_area_ratio": round(tiny_total_area, 6) if fragment_cluster else 0.0,
        "inline_raster_cluster_count": len(inline_clusters),
        "inline_raster_clusters": inline_clusters,
        "inline_raster_cluster_member_region_ids": inline_deferred_ids,
        "covered_by_inline_context_region_ids": covered_inline_ids,
        "preserve_region_ids": preserve_ids,
        "region_fallback_required_region_ids": region_fallback_ids,
        "page_ocr_region_ids": page_ocr_ids,
        "content_completeness": completeness,
        "regions": assessments,
    }

def validate_pdf_identity(manifest: dict[str, Any], pdf_path: Path, pdfplumber: Any) -> dict[str, Any]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在：{pdf_path}")
    expected_name = str(manifest.get("source_file") or "")
    if expected_name and pdf_path.name != Path(expected_name).name:
        raise ValueError(
            f"PDF 文件名与 Stage7 source_file 不一致：manifest={expected_name}, pdf={pdf_path.name}"
        )
    with pdfplumber.open(pdf_path) as doc:
        pdf_page_count = len(doc.pages)
    manifest_page_count = safe_int(manifest.get("page_count"), -1)
    if pdf_page_count != manifest_page_count:
        raise ValueError(
            f"PDF 页数与 Stage7 不一致：manifest={manifest_page_count}, pdf={pdf_page_count}"
        )
    return {
        "path": str(pdf_path),
        "name": pdf_path.name,
        "page_count": pdf_page_count,
        "identity_check": "filename_and_page_count_match_stage7",
    }


def build_quality_gate(
    manifest: dict[str, Any],
    input_path: Path,
    pdf_path: Path | None,
    probe_dpi: int,
    debug_crop_dir: Path | None,
) -> dict[str, Any]:
    validate_manifest(manifest)
    manifest_pages = [page for page in manifest.get("pages", []) if isinstance(page, dict)]

    # Pass 1: pure evidence gate. Do not touch the PDF yet.
    staged: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (page, page_quality_gate(page)) for page in manifest_pages
    ]
    uncertain_count = sum(
        1 for _page, result in staged
        if result.get("gate_state") == GATE_UNCERTAIN
    )

    pdf_identity: dict[str, Any] | None = None
    pdf_doc: Any = None
    ImageFilter: Any = None

    if uncertain_count > 0:
        if pdf_path is None:
            raise RuntimeError(
                f"Stage8 发现 {uncertain_count} 个 UNCERTAIN_NEEDS_PROBE 页面；"
                "只有这些页面需要 --pdf 做轻量视觉 probe。"
            )
        pdfplumber, ImageFilter = _require_probe_dependencies()
        pdf_identity = validate_pdf_identity(manifest, pdf_path, pdfplumber)
        pdf_doc = pdfplumber.open(pdf_path)

    page_results: list[dict[str, Any]] = []
    try:
        for page, result in staged:
            page_number = safe_int(page.get("page_number"), -1)
            pdf_page = None
            if result.get("gate_state") == GATE_UNCERTAIN:
                if pdf_doc is None:
                    raise RuntimeError("UNCERTAIN page 缺少 PDF probe context。")
                if page_number < 1 or page_number > len(pdf_doc.pages):
                    raise ValueError(f"Stage7 page_number 越界：{page_number}")
                pdf_page = pdf_doc.pages[page_number - 1]

            result["non_text_assessment"] = assess_non_text_regions(
                page,
                result,
                ImageFilter,
                pdf_page,
                probe_dpi,
                debug_crop_dir,
            )
            nta = result["non_text_assessment"]
            if nta.get("region_fallback_required_region_ids") or nta.get("inline_raster_clusters"):
                result["region_followup"] = "execute_generic_region_fallback_in_stage9"
            elif result.get("decision") == DECISION_NATIVE_PASS_WITH_NON_TEXT:
                result["region_followup"] = "preserve_non_text_with_native"
            page_results.append(result)
    finally:
        if pdf_doc is not None:
            pdf_doc.close()

    decision_counts = Counter(result["decision"] for result in page_results)
    route_counts = Counter(result["route"] for result in page_results)
    gate_state_counts = Counter(result["gate_state"] for result in page_results)

    pages_by_decision = {
        decision: [item["page_number"] for item in page_results if item["decision"] == decision]
        for decision in (
            DECISION_NATIVE_PASS,
            DECISION_NATIVE_PASS_WITH_NON_TEXT,
            DECISION_OCR_REQUIRED,
            DECISION_LAYOUT_FALLBACK_REQUIRED,
        )
    }

    fallback_pages = pages_by_decision[DECISION_OCR_REQUIRED] + pages_by_decision[DECISION_LAYOUT_FALLBACK_REQUIRED]

    region_class_counts: Counter[str] = Counter()
    region_action_counts: Counter[str] = Counter()
    raster_class_counts: Counter[str] = Counter()
    pages_region_fallback: list[int] = []
    pages_with_fragment_clusters: list[int] = []
    pages_with_inline_clusters: list[int] = []
    raster_probe_completed_count = 0
    raster_probe_skipped_count = 0
    skipped_page_ocr_count = 0
    inline_cluster_member_count = 0
    inline_cluster_count = 0
    inline_cluster_probe_completed_count = 0
    covered_by_inline_context_count = 0

    for page in page_results:
        nta = page.get("non_text_assessment") or {}
        region_class_counts.update(nta.get("classification_counts") or {})
        region_action_counts.update(nta.get("action_counts") or {})
        raster_class_counts.update(nta.get("raster_classification_counts") or {})
        if nta.get("region_fallback_required_region_ids") or nta.get("inline_raster_clusters"):
            pages_region_fallback.append(page["page_number"])
        if nta.get("fragment_cluster_detected"):
            pages_with_fragment_clusters.append(page["page_number"])
        clusters = nta.get("inline_raster_clusters") or []
        covered_by_inline_context_count += len(nta.get("covered_by_inline_context_region_ids") or [])
        if clusters:
            pages_with_inline_clusters.append(page["page_number"])
            inline_cluster_count += len(clusters)
            inline_cluster_member_count += sum(safe_int(c.get("member_count")) for c in clusters)
            inline_cluster_probe_completed_count += sum(1 for c in clusters if (c.get("raster_probe") or {}).get("probe_completed"))
        for region in nta.get("regions") or []:
            probe = region.get("raster_probe") or {}
            if probe.get("probe_completed"):
                raster_probe_completed_count += 1
            elif probe.get("probe_skipped"):
                raster_probe_skipped_count += 1
                if probe.get("classification") == RASTER_SKIPPED_PAGE_OCR:
                    skipped_page_ocr_count += 1

    routed_region_pages = sorted(set(pages_region_fallback))
    document_status = "ROUTING_REQUIRED" if (fallback_pages or routed_region_pages) else "NATIVE_COMPLETE"

    return {
        "stage": 8,
        "name": "quality_gate",
        "version": STAGE8_VERSION,
        "quality_gate_schema_version": QUALITY_GATE_SCHEMA_VERSION,
        "source_file": manifest.get("source_file"),
        "page_count": manifest.get("page_count"),
        "artifact_role": "page_and_region_quality_gate_and_routing_plan",
        "quality_gate_completed": True,
        "scope": "hard_gate_plus_uncertain_only_generic_region_fallback_v3",
        "pdf_reopened": uncertain_count > 0,
        "raster_inspected": raster_probe_completed_count > 0,
        "raster_probe_scope": "uncertain_pages_only",
        "raster_probe_provider": "pdfplumber_plus_pillow_no_ocr",
        "ocr_executed": False,
        "fallback_executed": False,
        "content_repaired": False,
        "input": {
            "stage7_manifest": str(input_path),
            "stage7_version": manifest.get("version"),
            "stage7_schema_version": manifest.get("manifest_schema_version"),
            "stage7_artifact_role": manifest.get("artifact_role"),
            "pdf": pdf_identity,
        },
        "policy": {
            "decisions": [
                DECISION_NATIVE_PASS,
                DECISION_NATIVE_PASS_WITH_NON_TEXT,
                DECISION_OCR_REQUIRED,
                DECISION_LAYOUT_FALLBACK_REQUIRED,
            ],
            "geometry_region_classifications": [
                REGION_FULL_PAGE_SCAN,
                REGION_TINY_FRAGMENT,
                REGION_SMALL,
                REGION_MEDIUM,
                REGION_LARGE,
            ],
            "raster_probe_classifications": [
                RASTER_LOW_INFORMATION,
                RASTER_AUXILIARY_IMAGE,
                RASTER_CONTENT_BEARING,
                RASTER_AMBIGUOUS_CONTENT,
                RASTER_INLINE_CLUSTER_MEMBER,
                RASTER_COVERED_INLINE_CONTEXT,
                RASTER_SKIPPED_PAGE_OCR,
            ],
            "final_region_actions": [
                REGION_ACTION_PAGE_OCR,
                REGION_ACTION_PRESERVE,
                FINAL_REGION_ACTION_FALLBACK,
                FINAL_REGION_ACTION_DEFER_INLINE_CLUSTER,
                FINAL_REGION_ACTION_COVERED_INLINE_CONTEXT,
            ],
            "principles": [
                "Stage8 judges final page usability; it does not redo Stage7 accounting.",
                "NON_TEXT_UNASSESSED alone never triggers whole-page OCR.",
                "scan_like + weak native content + dominant non-text evidence routes to OCR.",
                "native/structure integrity failures route to layout fallback.",
                "ACCOUNTED_FINAL_FLOW is provenance, not an automatic quality failure.",
                "complexity prior is context, not a failure unless upstream explicitly marks it as such.",
                "Hard PASS and hard FALLBACK are decided only from Stage1~7 evidence; they never need the visual probe.",
                "Only UNCERTAIN_NEEDS_PROBE pages are rendered locally; this avoids probing pages whose route is already known.",
                "Geometry is a triage signal only; small regions are not declared safe by size alone.",
                "Lightweight probe reuses pdfplumber + Pillow visual features only; it does not OCR, recognize text, call a parser, or claim semantic truth.",
                "Raster text/structure/photo scores are non-binding hints; Stage8 does not choose OCR vs layout vs vision parser.",
                "Only low-information or clear continuous-tone auxiliary images may be preserved directly; otherwise uncertain/content-bearing regions become generic Stage9 fallback candidates.",
                "Tiny raster fragments use generic accounted-text adjacency/overlap evidence to form inline contexts; singleton contexts are allowed only when spatial evidence is strong.",
                "A small standalone raster already covered by the same inline text context is suppressed from duplicate Stage9 fallback.",
                "Native page routing and whole-page content completeness are separate concepts.",
            ],
            "thresholds": {
                "image_dominant_largest_ratio": IMAGE_DOMINANT_LARGEST_RATIO,
                "image_dominant_total_ratio": IMAGE_DOMINANT_TOTAL_RATIO,
                "full_page_scan_min_region_area_ratio": FULL_PAGE_SCAN_MIN_AREA_RATIO,
                "tiny_non_text_max_area_ratio": TINY_NON_TEXT_MAX_AREA_RATIO,
                "small_non_text_max_area_ratio": SMALL_NON_TEXT_MAX_AREA_RATIO,
                "medium_non_text_max_area_ratio": MEDIUM_NON_TEXT_MAX_AREA_RATIO,
                "fragment_cluster_min_count": FRAGMENT_CLUSTER_MIN_COUNT,
                "fragment_cluster_max_total_area_ratio": FRAGMENT_CLUSTER_MAX_TOTAL_AREA_RATIO,
                "probe_dpi": probe_dpi,
                "max_adaptive_probe_dpi": MAX_ADAPTIVE_PROBE_DPI,
                "text_score_threshold": TEXT_SCORE_THRESHOLD,
                "structure_score_threshold": STRUCTURE_SCORE_THRESHOLD,
                "photo_score_threshold": PHOTO_SCORE_THRESHOLD,
                "auxiliary_photo_min_score": AUXILIARY_PHOTO_MIN_SCORE,
                "auxiliary_photo_min_entropy": AUXILIARY_PHOTO_MIN_ENTROPY,
                "auxiliary_photo_max_text_score": AUXILIARY_PHOTO_MAX_TEXT_SCORE,
                "min_text_row_bands": MIN_TEXT_ROW_BANDS,
                "min_structure_line_ratio": MIN_STRUCTURE_LINE_RATIO,
                "inline_text_vertical_gap_pt": INLINE_TEXT_VERTICAL_GAP_PT,
                "inline_text_horizontal_gap_pt": INLINE_TEXT_HORIZONTAL_GAP_PT,
                "inline_context_padding_pt": INLINE_CONTEXT_PADDING_PT,
                "inline_cluster_min_members": INLINE_CLUSTER_MIN_MEMBERS,
                "inline_singleton_min_vertical_overlap_ratio": INLINE_SINGLETON_MIN_VERTICAL_OVERLAP_RATIO,
                "inline_singleton_min_horizontal_overlap_ratio": INLINE_SINGLETON_MIN_HORIZONTAL_OVERLAP_RATIO,
                "inline_singleton_max_tight_gap_pt": INLINE_SINGLETON_MAX_TIGHT_GAP_PT,
                "inline_context_coverage_ratio": INLINE_CONTEXT_COVERAGE_RATIO,
                "inline_context_max_covered_area_ratio": INLINE_CONTEXT_MAX_COVERED_AREA_RATIO,
            },
        },
        "summary": {
            "decision_counts": dict(decision_counts),
            "route_counts": dict(route_counts),
            "gate_state_counts": dict(gate_state_counts),
            "pages_by_decision": pages_by_decision,
            "fallback_required_page_count": len(fallback_pages),
            "fallback_required_pages": sorted(fallback_pages),
            "non_text_region_count": sum(region_class_counts.values()),
            "geometry_region_classification_counts": dict(region_class_counts),
            "raster_probe_classification_counts": dict(raster_class_counts),
            "final_region_action_counts": dict(region_action_counts),
            "raster_probe_completed_region_count": raster_probe_completed_count,
            "raster_probe_skipped_region_count": raster_probe_skipped_count,
            "raster_probe_skipped_page_ocr_region_count": skipped_page_ocr_count,
            "region_fallback_required_page_count": len(pages_region_fallback),
            "region_fallback_required_pages": sorted(set(pages_region_fallback)),
            "inline_raster_cluster_count": inline_cluster_count,
            "inline_raster_cluster_member_count": inline_cluster_member_count,
            "inline_raster_cluster_probe_completed_count": inline_cluster_probe_completed_count,
            "covered_by_inline_context_region_count": covered_by_inline_context_count,
            "inline_raster_cluster_page_count": len(set(pages_with_inline_clusters)),
            "inline_raster_cluster_pages": sorted(set(pages_with_inline_clusters)),
            "fragment_cluster_page_count": len(pages_with_fragment_clusters),
            "fragment_cluster_pages": sorted(pages_with_fragment_clusters),
            "document_status": document_status,
            "note": (
                "Stage8 v0.3.2 keeps HARD_PASS / HARD_FALLBACK / UNCERTAIN_NEEDS_PROBE and generic preserve/fallback routing. "
                "Tiny rasters form generic inline contexts from spatial evidence, including strong singleton contexts; small regions already covered by the same context are deduplicated before Stage9."
            ),
        },
        "pages": page_results,
    }


def render_markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines: list[str] = []

    lines.append("# Stage 8 Quality Gate")
    lines.append("")
    lines.append(f"- 文件：{result.get('source_file')}")
    lines.append(f"- 页数：{result.get('page_count')}")
    lines.append(f"- Stage8 版本：{result.get('version')}")
    lines.append(f"- Scope：{result.get('scope')}")
    lines.append(f"- Document status：{summary.get('document_status')}")
    lines.append("")
    lines.append("> Stage8 v0.3.2 先用 Stage1~7 证据区分 HARD_PASS / HARD_FALLBACK / UNCERTAIN_NEEDS_PROBE；只对 UNCERTAIN 页做轻量视觉 probe。Probe 只回答 preserve 还是 generic region fallback，不再提前决定 OCR/layout/vision；tiny 公式/行内 raster 会按通用空间证据形成局部上下文后一次交给 Stage9，并对上下文已覆盖的小区域去重。")
    lines.append("")
    lines.append("| page | gate-state | type | section | decision | route | route-conf | completeness | useful-native | non-text | region-fallback | inline-contexts | preserve |")
    lines.append("|---:|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|")

    for page in result.get("pages", []):
        obs = page.get("observations", {})
        nta = page.get("non_text_assessment", {})
        lines.append(
            "| {page} | {gate} | {ptype} | {section} | {decision} | {route} | {conf} | {complete} | {useful} | {nontext} | {rfb} | {clusters} | {preserve} |".format(
                page=page.get("page_number"),
                gate=page.get("gate_state"),
                ptype=obs.get("primary_type"),
                section=obs.get("section_id") or "",
                decision=page.get("decision"),
                route=page.get("route"),
                conf=page.get("route_confidence"),
                complete=nta.get("content_completeness"),
                useful=obs.get("useful_native_word_count"),
                nontext=obs.get("non_text_unassessed_region_count"),
                rfb=len(nta.get("region_fallback_required_region_ids") or []),
                clusters=len(nta.get("inline_raster_clusters") or []),
                preserve=len(nta.get("preserve_region_ids") or []),
            )
        )

    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    lines.append("## Region Raster Probe")
    lines.append("")
    lines.append("| page | region | geom-class | raster-class | final-action | area | text | struct | photo | hints | conf |")
    lines.append("|---:|---|---|---|---|---:|---:|---:|---:|---|---|")
    for page in result.get("pages", []):
        nta = page.get("non_text_assessment") or {}
        for region in nta.get("regions", []):
            geom = region.get("geometry") or {}
            probe = region.get("raster_probe") or {}
            metrics = probe.get("metrics") or {}
            hints = probe.get("probe_hints") or {}
            hint_text = ",".join(k for k in ("text_like", "structure_like", "photo_like", "conflicting_signals") if hints.get(k)) or "-"
            lines.append(
                "| {page} | {rid} | {gcls} | {rcls} | {action} | {area:.4f} | {ts:.3f} | {ss:.3f} | {ps:.3f} | {hints} | {conf} |".format(
                    page=page.get("page_number"), rid=region.get("region_id"), gcls=region.get("classification"),
                    rcls=probe.get("classification"), action=region.get("action"), area=safe_float(geom.get("area_ratio")),
                    ts=safe_float(metrics.get("text_score")), ss=safe_float(metrics.get("structure_score")),
                    ps=safe_float(metrics.get("photo_score")), hints=hint_text, conf=probe.get("probe_confidence"),
                )
            )

    lines.append("")
    lines.append("## Inline Raster Contexts")
    lines.append("")
    found_cluster = False
    for page in result.get("pages", []):
        for cluster in (page.get("non_text_assessment") or {}).get("inline_raster_clusters") or []:
            found_cluster = True
            lines.append(f"### Page {page.get('page_number')} — {cluster.get('cluster_id')}")
            lines.append("")
            lines.append(f"- mode：{cluster.get('context_mode')}")
            lines.append(f"- members：{', '.join(cluster.get('member_region_ids') or [])}")
            lines.append(f"- context regions：{', '.join(cluster.get('context_region_ids') or [])}")
            lines.append(f"- context bbox：{json.dumps(cluster.get('context_bbox'), ensure_ascii=False)}")
            lines.append(f"- action：{cluster.get('action')}")
            lines.append(f"- reason：{cluster.get('reason')}")
            crop = ((cluster.get("raster_probe") or {}).get("debug_crop"))
            if crop:
                lines.append(f"- debug crop：{crop}")
            lines.append("")
    if not found_cluster:
        lines.append("无。")
        lines.append("")

    lines.append("## Page Fallback")
    lines.append("")
    fallback_pages = summary.get("fallback_required_pages", [])
    if fallback_pages:
        for page_number in fallback_pages:
            page = next((item for item in result.get("pages", []) if item.get("page_number") == page_number), None)
            if not page:
                continue
            lines.append(f"### Page {page_number} — {page.get('decision')}")
            lines.append("")
            lines.append(f"- route：{page.get('route')}")
            lines.append(f"- route confidence：{page.get('route_confidence')}")
            lines.append(f"- reason：{page.get('reason')}")
            fact_codes = [fact.get("code") for fact in page.get("risk_facts", []) if fact.get("severity") in {"high", "medium"}]
            lines.append("- risk facts：" + (", ".join(str(x) for x in fact_codes) or "none"))
            lines.append("")
    else:
        lines.append("无。")
        lines.append("")

    lines.append("## Region Fallback Required")
    lines.append("")
    found = False
    for page in result.get("pages", []):
        nta = page.get("non_text_assessment") or {}
        ids = nta.get("region_fallback_required_region_ids") or []
        clusters = nta.get("inline_raster_clusters") or []
        if ids or clusters:
            found = True
            parts = []
            if ids:
                parts.append("regions=" + ", ".join(ids))
            if clusters:
                parts.append("contexts=" + ", ".join(str(c.get("cluster_id")) for c in clusters))
            covered = nta.get("covered_by_inline_context_region_ids") or []
            if covered:
                parts.append("covered=" + ", ".join(covered))
            lines.append(f"- Page {page.get('page_number')}: {'; '.join(parts)}")
    if not found:
        lines.append("无。")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_quality_gate(
    *,
    manifest_path: Path,
    pdf_path: Path | None,
    output_dir: Path,
    probe_dpi: int = DEFAULT_PROBE_DPI,
    save_probe_crops: bool = False,
) -> dict[str, Any]:
    """Run Stage 8 through the package API while preserving probe artifacts."""
    if probe_dpi < 96 or probe_dpi > 400:
        raise ValueError("--probe-dpi 建议范围为 96~400。")

    manifest_path = Path(manifest_path)
    resolved_pdf = Path(pdf_path) if pdf_path is not None else None
    output_dir = Path(output_dir)
    manifest = load_json(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_crop_dir = output_dir / "probe_crops" if save_probe_crops else None
    result = build_quality_gate(
        manifest,
        manifest_path,
        resolved_pdf,
        probe_dpi,
        debug_crop_dir,
    )
    (output_dir / "quality_gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "quality_gate.md").write_text(
        render_markdown(result),
        encoding="utf-8",
    )
    return result
