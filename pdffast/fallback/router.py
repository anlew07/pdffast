#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from pdffast.fallback.planner import FallbackPlan


@dataclass(frozen=True)
class CapabilityPlan:
    data: dict[str, Any]

STAGE = 9
VERSION = "0.2.1"
SCHEMA_VERSION = "1.0"

TASK_PAGE_FALLBACK = "PAGE_FALLBACK"
TASK_REGION_FALLBACK = "REGION_FALLBACK"
TASK_INLINE_CONTEXT_FALLBACK = "INLINE_CONTEXT_FALLBACK"

ROUTE_PAGE_DOCUMENT_OCR = "PAGE_DOCUMENT_OCR"
ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE = "PAGE_DOCUMENT_LAYOUT_PARSE"
ROUTE_REGION_MULTIMODAL_PARSE = "REGION_MULTIMODAL_PARSE"
ROUTE_INLINE_CONTEXT_PARSE = "INLINE_CONTEXT_PARSE"

STATUS_ROUTED = "ROUTED"
PROVIDER_UNBOUND = "UNBOUND"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return data


def safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def validate_execution_manifest(doc: dict[str, Any]) -> None:
    if safe_int(doc.get("stage"), -1) != 9:
        raise ValueError("输入必须是 Stage9 fallback_execution_manifest.json")
    if doc.get("artifact_role") != "fallback_execution_unit_manifest":
        raise ValueError("artifact_role 不匹配：必须是 fallback_execution_unit_manifest")
    if not str(doc.get("version", "")).startswith("0.1."):
        raise ValueError(f"当前 router 期望 Stage9 execution manifest v0.1.x，实际={doc.get('version')}")
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Stage9 execution manifest 缺少 tasks")
    summary = doc.get("summary") or {}
    declared = safe_int(summary.get("task_count"), -1)
    if declared != len(tasks):
        raise ValueError(f"task_count 不一致：summary={declared}, tasks={len(tasks)}")

    ids: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("tasks 中存在非对象项")
        tid = str(task.get("task_id") or "")
        if not tid:
            raise ValueError("存在缺少 task_id 的任务")
        ids.append(tid)
        if task.get("status") != "PREPARED":
            raise ValueError(f"任务尚未处于 PREPARED：{tid} status={task.get('status')}")
        if not task.get("input_image"):
            raise ValueError(f"任务缺少统一渲染输入：{tid}")

    dup_ids = sorted({x for x in ids if ids.count(x) > 1})
    if dup_ids:
        raise ValueError(f"输入任务 ID 重复：{dup_ids}")


def route_for_task(task: dict[str, Any]) -> tuple[str, str]:
    """只根据 Stage9 已物化的 execution scope 选择能力类型，不重做 Stage8 语义判断。"""
    ttype = task.get("task_type")
    if ttype == TASK_PAGE_FALLBACK:
        decision = str(task.get("stage8_decision") or "")
        route = str(task.get("stage8_route") or "")
        if decision == "OCR_REQUIRED":
            return (
                ROUTE_PAGE_DOCUMENT_OCR,
                "Stage8 明确要求整页 OCR；使用文档 OCR 能力恢复页面文本与基础阅读顺序。",
            )
        if decision == "LAYOUT_FALLBACK_REQUIRED":
            return (
                ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE,
                "Stage8 明确要求 layout fallback；必须使用能够恢复整页阅读顺序/块结构的 layout parser，不能降级为纯平面 OCR。",
            )
        raise ValueError(
            f"PAGE_FALLBACK 缺少受支持的 Stage8 decision："
            f"task={task.get('task_id')} decision={decision!r} route={route!r}"
        )
    if ttype == TASK_INLINE_CONTEXT_FALLBACK:
        # 不假定一定是公式；只要求 provider 能理解局部图像 + 周边文字上下文，且最好具备数学符号能力。
        return (
            ROUTE_INLINE_CONTEXT_PARSE,
            "该任务是 tiny raster 与 native-text 组成的局部上下文；需要上下文感知的多模态解析能力，避免逐 glyph 解析。",
        )
    if ttype == TASK_REGION_FALLBACK:
        # 不再根据 text_like / structure_like 强行分 OCR/layout，避免 Stage8 v0.3.0 的误路由问题。
        return (
            ROUTE_REGION_MULTIMODAL_PARSE,
            "Stage8 已确认该局部 raster 不能安全忽略；使用统一多模态区域解析，text/structure/photo 仅作为执行提示。",
        )
    raise ValueError(f"未知 task_type：{ttype}")


def build_route_hints(task: dict[str, Any]) -> dict[str, Any]:
    hints = task.get("probe_hints") or {}
    if not isinstance(hints, dict):
        hints = {}

    decision = str(task.get("stage8_decision") or "")
    is_layout_page = (
        task.get("task_type") == TASK_PAGE_FALLBACK
        and decision == "LAYOUT_FALLBACK_REQUIRED"
    )

    result: dict[str, Any] = {
        "preserve_spatial_structure": (
            task.get("task_type") != TASK_PAGE_FALLBACK or is_layout_page
        ),
        "text_recovery_priority": "high" if hints.get("text_like") is True else "normal",
        "structure_recovery_priority": (
            "high" if is_layout_page or hints.get("structure_like") is True else "normal"
        ),
        "continuous_tone_present_hint": hints.get("photo_like") is True,
        "conflicting_visual_signals": hints.get("conflicting_signals") is True,
        "hints_are_non_binding": True,
    }

    if task.get("task_type") == TASK_PAGE_FALLBACK:
        result.update(
            {
                "recover_reading_order": True,
                "recover_tables": True,
                "recover_page_text": True,
                "layout_recovery_required": is_layout_page,
                "stage8_decision": decision,
            }
        )
    elif task.get("task_type") == TASK_INLINE_CONTEXT_FALLBACK:
        result.update(
            {
                "recover_inline_context": True,
                "math_symbol_support_preferred": True,
                "member_region_ids": list(task.get("member_region_ids") or []),
                "context_region_ids": list(task.get("context_region_ids") or []),
            }
        )
    else:
        result.update(
            {
                "recover_region_text": True,
                "recover_region_structure": True,
            }
        )

    return result


def output_contract_for_route(route: str) -> dict[str, Any]:
    common = {
        "required": ["status", "text"],
        "optional": ["confidence", "warnings", "provider_raw_ref"],
        "text_encoding": "utf-8",
        "empty_text_requires_warning": True,
    }
    if route == ROUTE_PAGE_DOCUMENT_OCR:
        return {
            **common,
            "optional": common["optional"] + ["blocks", "tables", "reading_order"],
            "scope": "full_page",
            "structure_required": False,
        }
    if route == ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE:
        return {
            **common,
            "optional": common["optional"] + ["blocks", "tables", "reading_order"],
            "scope": "full_page",
            "structure_required": True,
            "required_structure_channels_any": ["reading_blocks", "tables"],
        }
    if route == ROUTE_REGION_MULTIMODAL_PARSE:
        return {
            **common,
            "optional": common["optional"] + ["semantic_type", "structure", "description"],
            "scope": "region",
        }
    if route == ROUTE_INLINE_CONTEXT_PARSE:
        return {
            **common,
            "optional": common["optional"] + ["latex", "structure", "context_text"],
            "scope": "inline_context",
        }
    raise ValueError(f"未知 capability_route：{route}")


def route_tasks(doc: dict[str, Any]) -> list[dict[str, Any]]:
    routed: list[dict[str, Any]] = []
    for task in doc.get("tasks") or []:
        route, reason = route_for_task(task)
        routed.append(
            {
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "page_number": task["page_number"],
                "source_id": task["source_id"],
                "source_bbox": task.get("source_bbox"),
                "input_image": task.get("input_image"),
                "stage8_decision": task.get("stage8_decision"),
                "stage8_route": task.get("stage8_route"),
                "stage8_gate_state": task.get("stage8_gate_state"),
                "capability_route": route,
                "route_reason": reason,
                "route_hints": build_route_hints(task),
                "provider_binding": {
                    "status": PROVIDER_UNBOUND,
                    "provider_name": None,
                    "adapter": None,
                    "model_or_engine": None,
                },
                "output_contract": output_contract_for_route(route),
                "status": STATUS_ROUTED,
            }
        )
    return routed


def summarize(routed: list[dict[str, Any]]) -> dict[str, Any]:
    route_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    provider_bound = 0
    seen: set[str] = set()

    for task in routed:
        tid = task["task_id"]
        if tid in seen:
            raise ValueError(f"路由后 task_id 重复：{tid}")
        seen.add(tid)
        route = task["capability_route"]
        ttype = task["task_type"]
        route_counts[route] = route_counts.get(route, 0) + 1
        type_counts[ttype] = type_counts.get(ttype, 0) + 1
        if (task.get("provider_binding") or {}).get("status") != PROVIDER_UNBOUND:
            provider_bound += 1

    return {
        "task_count": len(routed),
        "task_type_counts": type_counts,
        "capability_route_counts": route_counts,
        "routed_task_count": sum(route_counts.values()),
        "unrouted_task_count": len(routed) - sum(route_counts.values()),
        "provider_bound_count": provider_bound,
        "provider_unbound_count": len(routed) - provider_bound,
        "duplicate_task_id_count": 0,
    }


def build_markdown(plan: dict[str, Any]) -> str:
    s = plan["summary"]
    lines = [
        "# Stage 9 Provider Capability Routing",
        "",
        f"- 文件：{plan['source_file']}",
        f"- Stage9 Router 版本：{plan['version']}",
        f"- 状态：{plan['status']}",
        "",
        "> v0.2.1 保留 Stage8 PAGE 语义：OCR_REQUIRED → PAGE_DOCUMENT_OCR，LAYOUT_FALLBACK_REQUIRED → PAGE_DOCUMENT_LAYOUT_PARSE；REGION/INLINE 逻辑不变，不调用第三方 provider。",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(s, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Routes",
        "",
        "| task | type | page | source | capability | provider |",
        "|---|---|---:|---|---|---|",
    ]
    for t in plan["tasks"]:
        binding = t.get("provider_binding") or {}
        provider = binding.get("provider_name") or binding.get("status") or "-"
        lines.append(
            f"| {t['task_id']} | {t['task_type']} | {t['page_number']} | {t['source_id']} | {t['capability_route']} | {provider} |"
        )
    return "\n".join(lines) + "\n"


def create_capability_plan(
    *,
    fallback_plan: FallbackPlan,
    manifest_path: Path,
) -> CapabilityPlan:
    """Route Stage 9.1 tasks without reading the execution manifest."""
    manifest_path = Path(manifest_path)
    doc = fallback_plan.data
    validate_execution_manifest(doc)
    routed = route_tasks(doc)
    summary = summarize(routed)

    if summary["unrouted_task_count"] != 0:
        raise ValueError(f"存在未路由任务：{summary['unrouted_task_count']}")
    if summary["routed_task_count"] != safe_int(
        (doc.get("summary") or {}).get("task_count"), -1
    ):
        raise ValueError("路由任务数与 execution manifest task_count 不一致")

    plan = {
        "stage": STAGE,
        "name": "provider_router",
        "version": VERSION,
        "provider_routing_schema_version": SCHEMA_VERSION,
        "artifact_role": "fallback_provider_capability_plan",
        "status": "ROUTED_PROVIDER_UNBOUND",
        "source_file": doc.get("source_file"),
        "page_count": doc.get("page_count"),
        "input": {
            "fallback_execution_manifest": str(manifest_path),
            "fallback_execution_version": doc.get("version"),
            "fallback_execution_schema_version": doc.get(
                "fallback_execution_schema_version"
            ),
        },
        "principles": [
            "Provider routing consumes Stage9 execution units; it does not re-run Stage8 quality judgment.",
            "PAGE_FALLBACK routes to document OCR/layout capability because Stage8 already made the page-level OCR decision.",
            "REGION_FALLBACK routes to one unified multimodal region capability; Stage8 text/structure/photo hints remain non-binding.",
            "INLINE_CONTEXT_FALLBACK routes to context-aware multimodal parsing; math support is preferred but formula semantics are not assumed.",
            "This layer assigns capability requirements, not vendor/provider names.",
            "Third-party provider outputs must be normalized to a stable contract before merge with native results.",
        ],
        "summary": summary,
        "tasks": routed,
    }
    return CapabilityPlan(plan)


def write_capability_plan(capability_plan: CapabilityPlan, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = capability_plan.data
    (output_dir / "provider_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "provider_plan.md").write_text(
        build_markdown(plan),
        encoding="utf-8",
    )


def run_capability_routing(
    *,
    manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Compatibility API reading Stage 9.1 JSON and writing Stage 9.2 artifacts."""
    plan = create_capability_plan(
        fallback_plan=FallbackPlan(load_json(Path(manifest_path))),
        manifest_path=manifest_path,
    )
    write_capability_plan(plan, output_dir)
    return plan.data
