#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

STAGE = 10
SUBSTAGE = "10.1"
VERSION = "0.1.6"
SCHEMA_VERSION = "1.1"
ARTIFACT_ROLE = "canonical_document_with_native_and_fallback_provenance"


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


def sha256_artifact_data(value: Mapping[str, Any]) -> str:
    """Hash the exact JSON bytes emitted by Stage 6, Quality, and Capability writers."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")).hexdigest()


def safe_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def nonempty_text(canonical: dict[str, Any] | None) -> str:
    if not isinstance(canonical, dict):
        return ""
    text = canonical.get("text") or {}
    if not isinstance(text, dict):
        return ""
    content = text.get("content")
    return str(content).strip() if content is not None else ""


def compact_canonical(canonical: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(canonical, dict):
        return None
    out = {
        "schema_version": canonical.get("schema_version"),
        "version": canonical.get("version"),
        "status": canonical.get("status"),
        "provider": copy.deepcopy(canonical.get("provider")),
        "elapsed_seconds": canonical.get("elapsed_seconds"),
        "text": copy.deepcopy(canonical.get("text")),
        "tables": copy.deepcopy(canonical.get("tables")),
        "formulas": copy.deepcopy(canonical.get("formulas")),
        "reading_blocks": copy.deepcopy(canonical.get("reading_blocks")),
        "spatial_text": copy.deepcopy(canonical.get("spatial_text")),
        "relations": copy.deepcopy(canonical.get("relations")),
        "diagnostics": copy.deepcopy(canonical.get("diagnostics")),
        "warnings": copy.deepcopy(canonical.get("warnings")),
        "exception": copy.deepcopy(canonical.get("exception")),
        "normalization_policy": copy.deepcopy(canonical.get("normalization_policy")),
    }
    return out


def bbox_area(b: dict[str, Any] | None) -> float:
    if not isinstance(b, dict):
        return 0.0
    try:
        return max(0.0, float(b["x1"]) - float(b["x0"])) * max(0.0, float(b["bottom"]) - float(b["top"]))
    except Exception:
        return 0.0


def bbox_intersection_area(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    try:
        x0 = max(float(a["x0"]), float(b["x0"]))
        y0 = max(float(a["top"]), float(b["top"]))
        x1 = min(float(a["x1"]), float(b["x1"]))
        y1 = min(float(a["bottom"]), float(b["bottom"]))
    except Exception:
        return 0.0
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def bbox_close(a: dict[str, Any] | None, b: dict[str, Any] | None, tol: float = 2.0) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    try:
        return all(abs(float(a[k]) - float(b[k])) <= tol for k in ("x0", "top", "x1", "bottom"))
    except Exception:
        return False


def record_pages(record: dict[str, Any]) -> list[int]:
    if isinstance(record.get("source_pages"), list):
        return [int(x) for x in record["source_pages"]]
    if record.get("source_page") is not None:
        return [int(record["source_page"])]
    return []


def record_bbox_on_page(record: dict[str, Any], page_number: int) -> dict[str, Any] | None:
    # Paragraphs spanning pages have page-local fragment geometry. Always prefer it.
    frags = record.get("source_fragment_geometry")
    if isinstance(frags, list):
        for f in frags:
            if isinstance(f, dict) and int(f.get("page_number", -1)) == page_number and isinstance(f.get("bbox"), dict):
                return f["bbox"]
    if page_number in record_pages(record) and isinstance(record.get("bbox"), dict):
        return record["bbox"]
    return None


def validate_inputs(
    native: dict[str, Any],
    qg: dict[str, Any],
    plan: dict[str, Any],
    selected_index: dict[str, Any],
    selected_wrappers: dict[str, dict[str, Any]],
) -> None:
    source_files = {
        str(native.get("source_file") or ""),
        str(qg.get("source_file") or ""),
        str(plan.get("source_file") or ""),
        str(selected_index.get("source_file") or ""),
    }
    if len(source_files) != 1 or "" in source_files:
        raise ValueError(f"source_file 不一致：{source_files}")
    page_counts = {int(native.get("page_count", -1)), int(qg.get("page_count", -1)), int(plan.get("page_count", -1))}
    if len(page_counts) != 1 or -1 in page_counts:
        raise ValueError(f"page_count 不一致：{page_counts}")
    if native.get("artifact_role") != "native_parser_final_flow":
        raise ValueError("native-flow 必须是 Stage6 native_parser_final_flow")
    if native.get("final_llm_document") is not False:
        raise ValueError("native-flow.final_llm_document 预期为 false")
    if int(qg.get("stage", -1)) != 8 or qg.get("name") != "quality_gate":
        raise ValueError("quality-gate 不是 Stage8 quality_gate")
    if int(plan.get("stage", -1)) != 9 or plan.get("artifact_role") != "fallback_provider_capability_plan":
        raise ValueError("provider-plan 不是 Stage9 fallback_provider_capability_plan")
    if int(selected_index.get("stage", -1)) != 9 or str(selected_index.get("substage")) != "9.8":
        raise ValueError("selected-index 不是 Stage9.8 selected_prediction_index")

    plan_tasks = safe_list(plan.get("tasks"))
    idx_items = safe_list(selected_index.get("items"))
    declared = int(selected_index.get("task_count", -1))
    if declared != len(idx_items):
        raise ValueError(f"selected-index task_count 不一致：declared={declared}, items={len(idx_items)}")
    plan_ids = {str(x.get("task_id")) for x in plan_tasks}
    index_ids = {str(x.get("task_id")) for x in idx_items}
    wrapper_ids = set(selected_wrappers)
    if plan_ids != index_ids or plan_ids != wrapper_ids:
        raise ValueError(
            "Stage9 task ids 不闭合："
            f"plan={len(plan_ids)} index={len(index_ids)} wrappers={len(wrapper_ids)} "
            f"plan-index={sorted(plan_ids-index_ids)[:5]} index-plan={sorted(index_ids-plan_ids)[:5]} "
            f"plan-wrapper={sorted(plan_ids-wrapper_ids)[:5]} wrapper-plan={sorted(wrapper_ids-plan_ids)[:5]}"
        )
    if len(plan_ids) != len(plan_tasks):
        raise ValueError("provider-plan 存在重复 task_id")

    plan_by_id = {str(x["task_id"]): x for x in plan_tasks}
    for tid, w in selected_wrappers.items():
        if str(w.get("task_id")) != tid:
            raise ValueError(f"selected wrapper task_id 不一致：{tid}")
        if w.get("ground_truth_used") is not False:
            raise ValueError(f"生产 selected prediction 不得使用 Ground Truth：{tid}")
        if bool(w.get("pipeline_failure")):
            # Canonical builder can represent failures, but this case is not allowed to silently proceed.
            raise ValueError(f"Stage9.8 存在 pipeline_failure，需先处理：{tid}")
        ptask = plan_by_id[tid]
        for key in ("task_type", "page_number", "source_id", "capability_route"):
            if w.get(key) != ptask.get(key):
                raise ValueError(f"task metadata 不一致：{tid} field={key} wrapper={w.get(key)} plan={ptask.get(key)}")
        terminal = bool(w.get("terminal_fallback_applied"))
        canonical = w.get("selected_canonical")
        if terminal:
            if str(w.get("task_type")) != "REGION_FALLBACK":
                raise ValueError(f"仅 REGION 允许 terminal preserve：{tid}")
            if canonical is not None or w.get("selected_provider") is not None:
                raise ValueError(f"terminal preserve 不应有 selected canonical/provider：{tid}")
            if w.get("terminal_fallback_action") != "PRESERVE_SOURCE_REGION_UNRESOLVED":
                raise ValueError(f"terminal fallback action 非预期：{tid}")
        else:
            if not isinstance(canonical, dict):
                raise ValueError(f"非 terminal task 缺少 selected_canonical：{tid}")
            if not nonempty_text(canonical):
                raise ValueError(f"非 terminal task selected text 为空：{tid}")


def build_qg_region_index(qg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for page in safe_list(qg.get("pages")):
        pn = int(page.get("page_number"))
        assessment = page.get("non_text_assessment") or {}
        for reg in safe_list(assessment.get("regions")):
            rid = str(reg.get("region_id") or "")
            if not rid:
                continue
            if rid in out:
                raise ValueError(f"Quality Gate region_id 重复：{rid}")
            item = copy.deepcopy(reg)
            item["page_number"] = pn
            out[rid] = item
    return out


def build_record_index(native: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[int, list[str]]]:
    records = copy.deepcopy(safe_list(native.get("records")))
    by_id: dict[str, dict[str, Any]] = {}
    by_page: dict[int, list[str]] = defaultdict(list)
    for i, rec in enumerate(records):
        rid = str(rec.get("record_id") or "")
        if not rid or rid in by_id:
            raise ValueError(f"native record_id 缺失或重复：{rid}")
        rec["stage10_record_index"] = i
        rec["stage10_resolution"] = {
            "mode": "NATIVE",
            "render_policy": "USE_NATIVE_RECORD",
            "fallback_task_ids": [],
        }
        by_id[rid] = rec
        for pn in record_pages(rec):
            by_page[pn].append(rid)
    return records, by_id, by_page


def qg_region_expected_record_types(qg_region: dict[str, Any]) -> set[str]:
    """Return Stage6 non-text record types that can legitimately anchor this Stage8 region.

    Stage8 region fallback is built from Stage7 NON_TEXT_UNASSESSED evidence. In the
    normal pipeline that is image/vector (or a future unknown non-text block), not a
    materialized table. Keep table_ref out of this mapping so flat region OCR never
    replaces an already materialized native table.
    """
    region_type = str(qg_region.get("region_type") or "").strip().lower()
    if region_type:
        candidate = f"{region_type}_ref"
        if candidate != "table_ref":
            return {candidate}
    return {"image_ref", "vector_ref", "object_ref", "unknown_ref"}


def map_qg_region_to_native_record(
    region_id: str,
    qg_region: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_page: dict[int, list[str]],
    allowed_record_types: set[str] | None = None,
) -> str:
    pn = int(qg_region["page_number"])
    source_refs = [str(x) for x in safe_list(qg_region.get("source_refs"))]
    block_ids = [x.split("stage4:block:", 1)[1] for x in source_refs if x.startswith("stage4:block:")]

    expected_types = qg_region_expected_record_types(qg_region)
    if allowed_record_types is not None:
        expected_types &= set(allowed_record_types)
    if not expected_types:
        raise ValueError(
            f"region -> native non-text ref 类型不匹配：region={region_id} "
            f"region_type={qg_region.get('region_type')} allowed={sorted(allowed_record_types or [])}"
        )

    # Strong provenance path: Stage7/8 carries the original Stage4 block id.
    candidates: list[str] = []
    for rec_id in by_page.get(pn, []):
        rec = by_id[rec_id]
        if str(rec.get("record_type") or "") not in expected_types:
            continue
        if rec.get("source_block_id") in block_ids or rec.get("block_id") in block_ids:
            candidates.append(rec_id)

    # Conservative geometry fallback for legacy/unrepresented source refs. Never choose
    # by nearest distance: exact-ish bbox agreement is required and ambiguity still fails.
    if not candidates:
        target_bbox = qg_region.get("bbox")
        for rec_id in by_page.get(pn, []):
            rec = by_id[rec_id]
            if str(rec.get("record_type") or "") not in expected_types:
                continue
            if bbox_close(record_bbox_on_page(rec, pn), target_bbox):
                candidates.append(rec_id)

    # Deduplicate in case block_id/source_block_id aliases hit the same record.
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError(
            "region -> native non-text ref 映射必须唯一："
            f"region={region_id} region_type={qg_region.get('region_type')} "
            f"expected_types={sorted(expected_types)} candidates={candidates}"
        )
    return candidates[0]


def region_can_be_detached_overlay(qg_region: dict[str, Any]) -> bool:
    """Return True only for non-text evidence that Stage7 explicitly kept outside Stage6 flow.

    Stage7 may add source-only visual evidence such as ``stage1_unrepresented_image``
    after Stage4/Stage6 have already decided their own native record topology. Such a
    region can legitimately receive Stage9 OCR even though there is no Stage6 ``*_ref``
    record to attach it to. In that case Stage10 must preserve it as an explicit
    page-local overlay rather than guessing a native anchor or dropping the result.

    Materialized tables/text/native-residual overlays are deliberately excluded.
    """
    region_type = str(qg_region.get("region_type") or "").strip().lower()
    if region_type in {"", "text", "table", "native_residual"}:
        return False

    refs = [str(x) for x in safe_list(qg_region.get("source_refs"))]
    # Stage8 v0.3.2 preserves source_refs but not Stage7 region_origin. These
    # provenance prefixes are therefore the stable runtime evidence that the
    # region was never a Stage6-native record.
    return any(
        ref.startswith("stage1:image:")
        or ref.startswith("stage1:vector:")
        or ref.startswith("stage4:degenerate:")
        for ref in refs
    ) and not any(ref.startswith("stage4:block:") for ref in refs)


def build_document(
    native_path: Path,
    qg_path: Path,
    plan_path: Path,
    selected_index_path: Path,
    selected_dir: Path,
    *,
    selected_index_data: Mapping[str, Any] | None = None,
    selected_predictions: Iterable[Mapping[str, Any]] | None = None,
    native_flow_data: Mapping[str, Any] | None = None,
    quality_data: Mapping[str, Any] | None = None,
    plan_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    native = native_flow_data if native_flow_data is not None else load_json(native_path)
    qg = quality_data if quality_data is not None else load_json(qg_path)
    plan = plan_data if plan_data is not None else load_json(plan_path)
    if (selected_index_data is None) != (selected_predictions is None):
        raise ValueError("selected_index_data and selected_predictions must be supplied together")
    selected_index = selected_index_data if selected_index_data is not None else load_json(selected_index_path)

    selected_wrappers: dict[str, dict[str, Any]] = {}
    if selected_predictions is None:
        for item in safe_list(selected_index.get("items")):
            tid = str(item.get("task_id") or "")
            p = selected_dir / f"{tid}.json"
            if not p.exists():
                raise FileNotFoundError(f"selected prediction 缺失：{p}")
            selected_wrappers[tid] = load_json(p)
    else:
        for wrapper in selected_predictions:
            tid = str(wrapper.get("task_id") or "")
            if not tid or tid in selected_wrappers:
                raise ValueError(f"selected prediction task_id 缺失或重复：{tid}")
            selected_wrappers[tid] = wrapper

    validate_inputs(native, qg, plan, selected_index, selected_wrappers)
    qg_regions = build_qg_region_index(qg)
    records, by_id, by_page = build_record_index(native)
    plan_by_id = {str(x["task_id"]): x for x in safe_list(plan.get("tasks"))}
    qg_page_by_num = {int(x["page_number"]): x for x in safe_list(qg.get("pages"))}

    # Inline-context bookkeeping is raster/image-specific. Build that index with an
    # explicit image_ref constraint; REGION_FALLBACK itself may also anchor to vector_ref.
    image_region_map: dict[str, str] = {}
    qg_region_to_record: dict[str, str] = {}
    for region_id, reg in qg_regions.items():
        try:
            rec_id = map_qg_region_to_native_record(
                region_id, reg, by_id, by_page, allowed_record_types={"image_ref"}
            )
        except ValueError:
            # Vector regions and tiny/unmaterialized raster regions are intentionally absent
            # from this image-only index.
            continue
        qg_region_to_record[region_id] = rec_id
        if rec_id in image_region_map:
            raise ValueError(f"一个 Stage6 image_ref 映射到多个 QG regions：{rec_id}")
        image_region_map[rec_id] = region_id

    native_image_ids = [r["record_id"] for r in records if r.get("record_type") == "image_ref"]
    missing_qg_for_image = [rid for rid in native_image_ids if rid not in image_region_map]
    if missing_qg_for_image:
        raise ValueError(f"Stage6 image_ref 无 Stage8 region 映射：{missing_qg_for_image[:10]}")

    page_fallbacks: dict[int, dict[str, Any]] = {}
    region_fallbacks: dict[str, dict[str, Any]] = {}
    inline_contexts: list[dict[str, Any]] = []

    selected_provider_counts: Counter[str] = Counter()
    runtime_outcome_counts: Counter[str] = Counter()
    task_type_counts: Counter[str] = Counter()
    terminal_count = 0

    for tid in [str(x["task_id"]) for x in safe_list(plan.get("tasks"))]:
        task = plan_by_id[tid]
        wrapper = selected_wrappers[tid]
        task_type = str(task["task_type"])
        pn = int(task["page_number"])
        task_type_counts[task_type] += 1
        runtime_outcome_counts[str(wrapper.get("runtime_outcome"))] += 1
        if wrapper.get("selected_provider"):
            selected_provider_counts[str(wrapper["selected_provider"])] += 1
        if wrapper.get("terminal_fallback_applied"):
            terminal_count += 1

        common = {
            "task_id": tid,
            "task_type": task_type,
            "page_number": pn,
            "source_id": task.get("source_id"),
            "source_bbox": copy.deepcopy(task.get("source_bbox")),
            "input_image": task.get("input_image"),
            "capability_route": task.get("capability_route"),
            "stage8_decision": task.get("stage8_decision"),
            "stage8_route": task.get("stage8_route"),
            "stage8_gate_state": task.get("stage8_gate_state"),
            "route_hints": copy.deepcopy(task.get("route_hints")),
            "policy_class": wrapper.get("policy_class"),
            "provider_chain": copy.deepcopy(wrapper.get("provider_chain")),
            "attempt_count": wrapper.get("attempt_count"),
            "escalated": bool(wrapper.get("escalated")),
            "selected_provider": wrapper.get("selected_provider"),
            "runtime_outcome": wrapper.get("runtime_outcome"),
            "terminal_fallback_applied": bool(wrapper.get("terminal_fallback_applied")),
            "source_content_preserved": bool(wrapper.get("source_content_preserved")),
            "pipeline_failure": bool(wrapper.get("pipeline_failure")),
            "capability_gaps": copy.deepcopy(wrapper.get("capability_gaps")),
            "fallback_content": compact_canonical(wrapper.get("selected_canonical")),
            "selected_prediction_file": str((selected_dir / f"{tid}.json")),
        }

        if task_type == "PAGE_FALLBACK":
            if pn in page_fallbacks:
                raise ValueError(f"同一页存在多个 PAGE_FALLBACK：p{pn}")
            qgp = qg_page_by_num.get(pn) or {}
            decision = str(qgp.get("decision") or "")
            capability_route = str(task.get("capability_route") or "")

            if decision == "OCR_REQUIRED":
                if capability_route != "PAGE_DOCUMENT_OCR":
                    raise ValueError(
                        f"OCR_REQUIRED 页 capability_route 非 PAGE_DOCUMENT_OCR："
                        f"p{pn}={capability_route}"
                    )
                fallback_kind = "OCR"
                source_mode = "PAGE_FALLBACK_SOURCE"
                render_policy = "AUTHORITATIVE_PAGE_OCR_FALLBACK_TEXT"
                source_render_policy = "SUPPRESS_NATIVE_USE_PAGE_OCR_FALLBACK"
            elif decision == "LAYOUT_FALLBACK_REQUIRED":
                if capability_route != "PAGE_DOCUMENT_LAYOUT_PARSE":
                    raise ValueError(
                        f"LAYOUT_FALLBACK_REQUIRED 页 capability_route 非 PAGE_DOCUMENT_LAYOUT_PARSE："
                        f"p{pn}={capability_route}"
                    )
                fallback_kind = "LAYOUT"
                source_mode = "PAGE_LAYOUT_FALLBACK_SOURCE"
                render_policy = "AUTHORITATIVE_PAGE_LAYOUT_FALLBACK"
                source_render_policy = "SUPPRESS_NATIVE_USE_PAGE_LAYOUT_FALLBACK"
            else:
                raise ValueError(
                    f"PAGE_FALLBACK 页 Stage8 decision 不受支持：p{pn}={decision!r}"
                )

            # Keep Stage6 records as provenance, but the accepted full-page fallback becomes
            # authoritative for this physical page. Layout-required pages are deliberately
            # distinct from OCR-required pages so flat OCR cannot masquerade as layout recovery.
            page_record_ids = list(by_page.get(pn, []))
            if not page_record_ids:
                raise ValueError(f"PAGE_FALLBACK 页没有 Stage6 records：p{pn}")
            common["source_native_record_ids"] = page_record_ids
            common["fallback_kind"] = fallback_kind
            common["quality_gate_decision"] = decision
            common["render_policy"] = render_policy
            page_fallbacks[pn] = common
            for rec_id in page_record_ids:
                rec = by_id[rec_id]
                # Only mark a source record as fully superseded if it belongs exclusively to this page.
                if record_pages(rec) == [pn]:
                    rec["stage10_resolution"] = {
                        "mode": source_mode,
                        "render_policy": source_render_policy,
                        "fallback_task_ids": [tid],
                        "fallback_kind": fallback_kind,
                        "quality_gate_decision": decision,
                        "selected_provider": wrapper.get("selected_provider"),
                        "runtime_outcome": wrapper.get("runtime_outcome"),
                        "fallback_content": compact_canonical(wrapper.get("selected_canonical")),
                    }

        elif task_type == "REGION_FALLBACK":
            source_id = str(task.get("source_id") or "")
            reg = qg_regions.get(source_id)
            if reg is None:
                raise ValueError(f"REGION_FALLBACK source_id 不在 Quality Gate：{tid} {source_id}")
            if reg.get("action") != "REGION_FALLBACK_REQUIRED":
                raise ValueError(f"REGION_FALLBACK 对应 QG action 非 REGION_FALLBACK_REQUIRED：{source_id}={reg.get('action')}")
            rec_id: str | None = None
            mapping_error: str | None = None
            try:
                rec_id = map_qg_region_to_native_record(source_id, reg, by_id, by_page)
            except ValueError as exc:
                # A Stage7 source-only visual can legitimately have no Stage6 native ref.
                # Do not invent/guess an anchor. Keep it as an explicit detached overlay
                # and let Stage10.2 serialize it with an unresolved-position boundary.
                if not region_can_be_detached_overlay(reg):
                    raise
                mapping_error = str(exc)

            common["source_native_record_id"] = rec_id
            common["anchor_status"] = (
                "STAGE6_NATIVE_NON_TEXT_REF"
                if rec_id is not None
                else "DETACHED_SOURCE_REGION_NOT_IN_STAGE6_FLOW"
            )
            common["detached_from_stage6"] = rec_id is None
            if mapping_error:
                common["anchor_diagnostic"] = mapping_error
            common["quality_gate_region"] = {
                "region_id": source_id,
                "action": reg.get("action"),
                "region_type": reg.get("region_type"),
                "source_image_index": reg.get("source_image_index"),
                "source_refs": copy.deepcopy(reg.get("source_refs")),
                "classification": reg.get("classification"),
                "raster_classification": (reg.get("raster_probe") or {}).get("classification"),
                "bbox": copy.deepcopy(reg.get("bbox")),
            }
            if wrapper.get("terminal_fallback_applied"):
                common["render_policy"] = "PRESERVE_VISUAL_EMIT_UNRESOLVED_PLACEHOLDER"
                mode = "REGION_PRESERVED_UNRESOLVED"
            else:
                common["render_policy"] = "PRESERVE_VISUAL_WITH_TEXT_ENRICHMENT"
                mode = "REGION_TEXT_ENRICHMENT"
            region_fallbacks[source_id] = common
            if rec_id is not None:
                rec = by_id[rec_id]
                rec["stage10_resolution"] = {
                    "mode": mode,
                    "render_policy": common["render_policy"],
                    "fallback_task_ids": [tid],
                    "source_region_id": source_id,
                    "source_region_type": reg.get("region_type"),
                    "selected_provider": wrapper.get("selected_provider"),
                    "runtime_outcome": wrapper.get("runtime_outcome"),
                    "fallback_content": compact_canonical(wrapper.get("selected_canonical")),
                    "source_visual_preserved": True,
                    "capability_gaps": copy.deepcopy(wrapper.get("capability_gaps")),
                }

        elif task_type == "INLINE_CONTEXT_FALLBACK":
            context_bbox = task.get("source_bbox")
            if not isinstance(context_bbox, dict):
                raise ValueError(f"INLINE_CONTEXT_FALLBACK 缺少 source_bbox：{tid}")
            member_region_ids = [str(x) for x in safe_list((task.get("route_hints") or {}).get("member_region_ids"))]
            context_region_ids = [str(x) for x in safe_list((task.get("route_hints") or {}).get("context_region_ids"))]
            member_image_record_ids: list[str] = []
            covered_image_record_ids: list[str] = []
            unmaterialized_member_region_ids: list[str] = []
            for rgid in member_region_ids:
                rec_id = qg_region_to_record.get(rgid)
                if rec_id:
                    member_image_record_ids.append(rec_id)
                else:
                    unmaterialized_member_region_ids.append(rgid)

            # Stage8 may suppress a standalone non-text region because the same visual content is
            # already fully covered by this inline context. Those Stage6 image_ref records must not
            # survive as separate placeholders in the final renderer.
            covered_region_ids: list[str] = []
            context_source_id = str(task.get("source_id") or "")
            for rgid, qgr in qg_regions.items():
                covered = qgr.get("covered_by_inline_context")
                if not isinstance(covered, dict) or str(covered.get("cluster_id") or "") != context_source_id:
                    continue
                covered_region_ids.append(rgid)
                rec_id = qg_region_to_record.get(rgid)
                if rec_id:
                    covered_image_record_ids.append(rec_id)

            overlaps: list[dict[str, Any]] = []
            fully_contained: list[str] = []
            partial: list[str] = []
            for rec_id in by_page.get(pn, []):
                rec = by_id[rec_id]
                rb = record_bbox_on_page(rec, pn)
                inter = bbox_intersection_area(rb, context_bbox)
                if inter <= 0:
                    continue
                area = bbox_area(rb)
                ratio = inter / area if area > 0 else 0.0
                overlaps.append({
                    "record_id": rec_id,
                    "record_type": rec.get("record_type"),
                    "overlap_ratio_of_record": round(ratio, 6),
                })
                if ratio >= 0.95:
                    fully_contained.append(rec_id)
                else:
                    partial.append(rec_id)

            common.update({
                "render_policy": "CONTEXT_ENRICHMENT_NO_AUTOMATIC_NATIVE_TEXT_REWRITE",
                "member_region_ids": member_region_ids,
                "context_region_ids": context_region_ids,
                "member_image_record_ids": member_image_record_ids,
                "covered_region_ids": covered_region_ids,
                "covered_image_record_ids": covered_image_record_ids,
                "unmaterialized_member_region_ids": unmaterialized_member_region_ids,
                "overlap_diagnostics": overlaps,
                "fully_contained_native_record_ids": fully_contained,
                "partially_overlapping_native_record_ids": partial,
                "merge_note": (
                    "Stage10.1 preserves native text and stores the richer inline-context parse as an overlay. "
                    "It does not automatically rewrite partially overlapping native paragraphs; Stage10.2 may "
                    "perform only conservative, provenance-preserving rendering/deduplication."
                ),
            })
            inline_contexts.append(common)
            for rec_id in member_image_record_ids + covered_image_record_ids:
                rec = by_id[rec_id]
                existing = rec.get("stage10_resolution") or {}
                task_ids = list(existing.get("fallback_task_ids") or [])
                if tid not in task_ids:
                    task_ids.append(tid)
                is_covered = rec_id in covered_image_record_ids
                rec["stage10_resolution"] = {
                    "mode": "INLINE_CONTEXT_COVERED" if is_covered else "INLINE_CONTEXT_MEMBER",
                    "render_policy": "SUPPRESS_STANDALONE_IMAGE_REF_USE_INLINE_CONTEXT_OVERLAY",
                    "fallback_task_ids": task_ids,
                }
        else:
            raise ValueError(f"未知 Stage9 task_type：{task_type}")

    # Native image refs which were explicitly preserved by Stage8 remain visual references.
    preserved_native_visuals = 0
    inline_image_refs = 0
    page_fallback_image_refs = 0
    page_layout_fallback_image_refs = 0
    region_image_refs = 0
    for rec in records:
        if rec.get("record_type") != "image_ref":
            continue
        mode = str((rec.get("stage10_resolution") or {}).get("mode") or "NATIVE")
        if mode == "NATIVE":
            qg_region_id = image_region_map.get(str(rec["record_id"]))
            qgr = qg_regions.get(qg_region_id or "") or {}
            action = qgr.get("action")
            rec["stage10_resolution"] = {
                "mode": "PRESERVED_NATIVE_VISUAL",
                "render_policy": "EMIT_VISUAL_REFERENCE_PLACEHOLDER",
                "fallback_task_ids": [],
                "source_region_id": qg_region_id,
                "quality_gate_action": action,
            }
            preserved_native_visuals += 1
        elif mode in {"INLINE_CONTEXT_MEMBER", "INLINE_CONTEXT_COVERED"}:
            inline_image_refs += 1
        elif mode == "PAGE_FALLBACK_SOURCE":
            page_fallback_image_refs += 1
        elif mode == "PAGE_LAYOUT_FALLBACK_SOURCE":
            page_layout_fallback_image_refs += 1
        elif mode in {"REGION_TEXT_ENRICHMENT", "REGION_PRESERVED_UNRESOLVED"}:
            region_image_refs += 1

    # Build page-level routing index for the renderer.
    page_index_native = {int(x["page_number"]): x for x in safe_list(native.get("page_index"))}
    section_by_page: dict[int, dict[str, Any]] = {}
    for section in safe_list(native.get("sections")):
        for pn in safe_list(section.get("page_numbers")):
            section_by_page[int(pn)] = {
                "section_key": section.get("section_key"),
                "section_id": section.get("section_id"),
                "section_title": section.get("section_title"),
                "zone_type": section.get("zone_type"),
            }

    regions_by_page: dict[int, list[str]] = defaultdict(list)
    for source_id, info in region_fallbacks.items():
        regions_by_page[int(info["page_number"])].append(source_id)
    inline_by_page: dict[int, list[str]] = defaultdict(list)
    for ctx in inline_contexts:
        inline_by_page[int(ctx["page_number"])].append(str(ctx["task_id"]))

    pages: list[dict[str, Any]] = []
    for pn in range(1, int(native["page_count"]) + 1):
        qgp = qg_page_by_num.get(pn) or {}
        sec = section_by_page.get(pn) or {}
        pages.append({
            "page_number": pn,
            "section": sec,
            "native_page_status": (page_index_native.get(pn) or {}).get("status"),
            "quality_gate_decision": qgp.get("decision"),
            "quality_gate_route": qgp.get("route"),
            "render_mode": "PAGE_FALLBACK" if pn in page_fallbacks else "NATIVE_WITH_OPTIONAL_OVERLAYS",
            "native_record_ids": list(by_page.get(pn, [])),
            "page_fallback_task_id": page_fallbacks.get(pn, {}).get("task_id"),
            "region_fallback_source_ids": sorted(regions_by_page.get(pn, [])),
            "inline_context_task_ids": sorted(inline_by_page.get(pn, [])),
        })

    # Consistency summary.
    stage10_modes = Counter(str((r.get("stage10_resolution") or {}).get("mode")) for r in records)
    region_record_type_counts = Counter(
        str(r.get("record_type") or "")
        for r in records
        if str((r.get("stage10_resolution") or {}).get("mode") or "")
        in {"REGION_TEXT_ENRICHMENT", "REGION_PRESERVED_UNRESOLVED"}
    )
    wrapper_count = len(selected_wrappers)
    source_files = {
        "native_flow": {"path": str(native_path), "sha256": sha256_file(native_path) if native_flow_data is None else sha256_artifact_data(native_flow_data), "version": native.get("version")},
        "quality_gate": {"path": str(qg_path), "sha256": sha256_file(qg_path) if quality_data is None else sha256_artifact_data(quality_data), "version": qg.get("version")},
        "provider_plan": {"path": str(plan_path), "sha256": sha256_file(plan_path) if plan_data is None else sha256_artifact_data(plan_data), "version": plan.get("version")},
        "selected_prediction_index": {"path": str(selected_index_path), "sha256": (
            sha256_file(selected_index_path) if selected_index_data is None else
            hashlib.sha256((json.dumps(selected_index_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).hexdigest()
        )},
        "selected_prediction_dir": str(selected_dir),
    }

    output = {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "substage": SUBSTAGE,
        "name": "canonical_document_builder",
        "version": VERSION,
        "artifact_role": ARTIFACT_ROLE,
        "status": "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING",
        "source_file": native.get("source_file"),
        "page_count": native.get("page_count"),
        "principles": [
            "Stage10.1 never re-opens the PDF and never runs OCR or a parser.",
            "Native Stage6 records remain the provenance backbone.",
            "Whole-page OCR fallback is authoritative only on Stage8 OCR_REQUIRED pages.",
            "Whole-page layout fallback is authoritative only on Stage8 LAYOUT_FALLBACK_REQUIRED pages and remains semantically distinct from flat OCR.",
            "Region fallback enriches a preserved Stage6 non-text anchor when one exists; Stage7 source-only visuals remain explicit detached overlays and are never force-mapped to unrelated native records.",
            "Unresolved regions remain explicit source-preserved placeholders; no text is invented.",
            "Inline-context fallback is stored as a richer overlay; partially overlapping native paragraphs are not automatically rewritten in Stage10.1.",
            "No Ground Truth, benchmark labels, or holdout labels are used at runtime.",
        ],
        "inputs": source_files,
        "summary": {
            "native_record_count": len(records),
            "native_record_type_counts": dict(Counter(str(r.get("record_type")) for r in records)),
            "stage10_resolution_mode_counts": dict(stage10_modes),
            "fallback_task_count": wrapper_count,
            "fallback_task_type_counts": dict(task_type_counts),
            "selected_provider_counts": dict(selected_provider_counts),
            "runtime_outcome_counts": dict(runtime_outcome_counts),
            "page_fallback_count": len(page_fallbacks),
            "page_ocr_fallback_count": sum(1 for x in page_fallbacks.values() if x.get("fallback_kind") == "OCR"),
            "page_layout_fallback_count": sum(1 for x in page_fallbacks.values() if x.get("fallback_kind") == "LAYOUT"),
            "region_fallback_count": len(region_fallbacks),
            "detached_region_fallback_count": sum(
                1 for x in region_fallbacks.values() if not x.get("source_native_record_id")
            ),
            "region_fallback_record_type_counts": dict(region_record_type_counts),
            "inline_context_count": len(inline_contexts),
            "terminal_preserve_count": terminal_count,
            "pipeline_failure_count": 0,
            "preserved_native_visual_count": preserved_native_visuals,
            "page_fallback_source_image_ref_count": page_fallback_image_refs,
            "page_layout_fallback_source_image_ref_count": page_layout_fallback_image_refs,
            "region_image_ref_count": region_image_refs,
            "inline_context_member_image_ref_count": inline_image_refs,
            "ground_truth_used": False,
        },
        "sections": copy.deepcopy(native.get("sections")),
        "pages": pages,
        "records": records,
        "document_units": [],
        "fallback_overlays": {
            "page_fallbacks": [page_fallbacks[p] for p in sorted(page_fallbacks)],
            "region_fallbacks": [region_fallbacks[k] for k in sorted(region_fallbacks, key=lambda x: (region_fallbacks[x]["page_number"], x))],
            "inline_contexts": sorted(inline_contexts, key=lambda x: (x["page_number"], float((x.get("source_bbox") or {}).get("top", 0.0)), x["task_id"])),
        },
        "renderer_contract": {
            "next_stage": "10.2",
            "native_pages": "render Stage6 records in preserved semantic order, applying region/inline overlays conservatively",
            "page_fallback_pages": "OCR_REQUIRED pages render accepted OCR text; LAYOUT_FALLBACK_REQUIRED pages render accepted layout-parser output under an explicit structure boundary",
            "region_enrichment": "render anchored region enrichment at the Stage6 visual position; source-only regions without a Stage6 record render as explicit page-local detached overlays with unresolved relative position",
            "terminal_region": "render an explicit unresolved visual placeholder; never synthesize text",
            "inline_context": "prefer rich reading_blocks/formulas where available; do not duplicate partially overlapping native text without conservative deduplication",
        },
    }

    # Final generic production invariants.
    # Stage10.1 must agree with the topology of the CURRENT provider plan;
    # no case/page/task-count constants are allowed here.
    expected_page = int(task_type_counts.get("PAGE_FALLBACK", 0))
    expected_region = int(task_type_counts.get("REGION_FALLBACK", 0))
    expected_inline = int(task_type_counts.get("INLINE_CONTEXT_FALLBACK", 0))

    actual_page = len(page_fallbacks)
    actual_region = len(region_fallbacks)
    actual_inline = len(inline_contexts)

    if (
        actual_page != expected_page
        or actual_region != expected_region
        or actual_inline != expected_inline
    ):
        raise ValueError(
            "Stage10.1 fallback topology 与当前 provider-plan 不一致："
            f"expected PAGE={expected_page} REGION={expected_region} INLINE={expected_inline}; "
            f"actual PAGE={actual_page} REGION={actual_region} INLINE={actual_inline}"
        )

    accounted_fallback_tasks = actual_page + actual_region + actual_inline
    if accounted_fallback_tasks != wrapper_count:
        raise ValueError(
            "Stage10.1 fallback task accounting 不闭合："
            f"wrappers={wrapper_count} accounted={accounted_fallback_tasks}"
        )

    wrapper_terminal_count = sum(
        1
        for w in selected_wrappers.values()
        if bool(w.get("terminal_fallback_applied"))
    )
    if terminal_count != wrapper_terminal_count:
        raise ValueError(
            "Stage10.1 terminal preserve accounting 不一致："
            f"observed={terminal_count} wrappers={wrapper_terminal_count}"
        )

    if len(records) != int(native.get("record_count", -1)):
        raise ValueError(
            "native record_count 不一致："
            f"declared={native.get('record_count')} actual={len(records)}"
        )

    return output


def render_review_md(doc: dict[str, Any]) -> str:
    s = doc["summary"]
    lines = [
        "# Stage 10.1 Canonical Document Review",
        "",
        f"- Source: `{doc['source_file']}`",
        f"- Pages: {doc['page_count']}",
        f"- Status: `{doc['status']}`",
        f"- Native records: {s['native_record_count']}",
        f"- Stage9.8 tasks: {s['fallback_task_count']}",
        f"- PAGE fallback: {s['page_fallback_count']}",
        f"- REGION fallback: {s['region_fallback_count']} (detached={s.get('detached_region_fallback_count', 0)})",
        f"- INLINE context: {s['inline_context_count']}",
        f"- Terminal source preserve: {s['terminal_preserve_count']}",
        f"- Pipeline failures: {s['pipeline_failure_count']}",
        f"- Ground Truth used: {s['ground_truth_used']}",
        "",
        "## Runtime outcomes",
        "",
    ]
    for k, v in sorted(s["runtime_outcome_counts"].items()):
        lines.append(f"- `{k}`: {v}")
    lines += ["", "## Page fallback", ""]
    for item in doc["fallback_overlays"]["page_fallbacks"]:
        text = nonempty_text(item.get("fallback_content"))
        lines.append(f"- p{item['page_number']:04d} `{item['task_id']}` provider=`{item['selected_provider']}` chars={len(text)}")
    lines += ["", "## Region fallback", ""]
    for item in doc["fallback_overlays"]["region_fallbacks"]:
        text = nonempty_text(item.get("fallback_content"))
        lines.append(
            f"- p{item['page_number']:04d} `{item['source_id']}` -> `{item['source_native_record_id']}` "
            f"outcome=`{item['runtime_outcome']}` provider=`{item['selected_provider']}` chars={len(text)}"
        )
    lines += ["", "## Inline context overlays", ""]
    for item in doc["fallback_overlays"]["inline_contexts"]:
        text = nonempty_text(item.get("fallback_content"))
        lines.append(
            f"- p{item['page_number']:04d} `{item['task_id']}` provider=`{item['selected_provider']}` chars={len(text)} "
            f"full_overlap={len(item['fully_contained_native_record_ids'])} partial_overlap={len(item['partially_overlapping_native_record_ids'])}"
        )
    lines += ["", "## Next", "", "Stage 10.2 will render `llm_ready.md` from this canonical document without re-running PDF parsing/OCR.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage 10.1 canonical document builder")
    ap.add_argument("--native-flow", required=True, type=Path)
    ap.add_argument("--quality-gate", required=True, type=Path)
    ap.add_argument("--provider-plan", required=True, type=Path)
    ap.add_argument("--selected-index", required=True, type=Path)
    ap.add_argument("--selected-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    doc = build_document(
        args.native_flow,
        args.quality_gate,
        args.provider_plan,
        args.selected_index,
        args.selected_dir,
    )
    s = doc["summary"]
    print("=" * 120)
    print(f"Stage 10.1 Canonical Document Builder | version={VERSION} | source={doc['source_file']}")
    print("=" * 120)
    print(f"Native records      | {s['native_record_count']} | {s['native_record_type_counts']}")
    print(f"Fallback tasks      | {s['fallback_task_count']} | {s['fallback_task_type_counts']}")
    print(f"Page fallback       | {s['page_fallback_count']}")
    print(f"Region fallback     | {s['region_fallback_count']} | detached={s.get('detached_region_fallback_count', 0)}")
    print(f"Inline contexts     | {s['inline_context_count']}")
    print(f"Terminal preserve   | {s['terminal_preserve_count']}")
    print(f"Pipeline failures   | {s['pipeline_failure_count']}")
    print(f"Providers           | {s['selected_provider_counts']}")
    print(f"Outcomes            | {s['runtime_outcome_counts']}")
    print(f"Resolution modes    | {s['stage10_resolution_mode_counts']}")
    print("Ground truth        | NOT USED")
    print("Validation          | PASS")
    if args.validate_only:
        print("Write final         | NO")
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        json_path = args.output / "canonical_document.json"
        md_path = args.output / "canonical_document_review.md"
        write_json(json_path, doc)
        md_path.write_text(render_review_md(doc), encoding="utf-8")
        print(f"JSON                | {json_path}")
        print(f"Review Markdown     | {md_path}")
        print("Write final         | YES")
    print("Next                | Stage 10.2 LLM-ready renderer")
    print("=" * 120)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        raise
