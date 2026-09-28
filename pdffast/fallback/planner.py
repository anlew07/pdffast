#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber
from pdffast.quality.gate import QualityReport


@dataclass(frozen=True)
class FallbackPlan:
    data: dict[str, Any]

STAGE = 9
VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"

TASK_PAGE_FALLBACK = "PAGE_FALLBACK"
TASK_REGION_FALLBACK = "REGION_FALLBACK"
TASK_INLINE_CONTEXT_FALLBACK = "INLINE_CONTEXT_FALLBACK"

STATUS_PREPARED = "PREPARED"

DEFAULT_PAGE_DPI = 300
DEFAULT_REGION_DPI = 300


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


def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def bbox_to_tuple(bbox: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        safe_float(bbox.get("x0")),
        safe_float(bbox.get("top")),
        safe_float(bbox.get("x1")),
        safe_float(bbox.get("bottom")),
    )


def validate_stage8(qg: dict[str, Any]) -> None:
    if safe_int(qg.get("stage"), -1) != 8:
        raise ValueError("Stage9 输入必须是 Stage8 quality_gate.json")
    if qg.get("artifact_role") != "page_and_region_quality_gate_and_routing_plan":
        raise ValueError("Stage8 artifact_role 不匹配")
    if qg.get("quality_gate_completed") is not True:
        raise ValueError("Stage8 quality_gate_completed 必须为 true")
    if qg.get("fallback_executed") is True:
        raise ValueError("Stage8 输入不应已经执行 fallback")
    pages = qg.get("pages")
    if not isinstance(pages, list):
        raise ValueError("Stage8 缺少 pages 列表")
    pc = safe_int(qg.get("page_count"), -1)
    if pc != len(pages):
        raise ValueError(f"Stage8 page_count 不一致：header={pc}, pages={len(pages)}")


def stable_task_id(kind: str, page_number: int, source_id: str) -> str:
    raw = f"{kind}|{page_number}|{source_id}".encode("utf-8")
    short = hashlib.sha1(raw).hexdigest()[:12]
    return f"s9_{page_number:04d}_{kind.lower()}_{short}"


def make_page_task(page: dict[str, Any]) -> dict[str, Any]:
    pn = safe_int(page.get("page_number"))
    return {
        "task_id": stable_task_id(TASK_PAGE_FALLBACK, pn, f"page:{pn}"),
        "task_type": TASK_PAGE_FALLBACK,
        "status": STATUS_PREPARED,
        "page_number": pn,
        "source_id": f"page:{pn}",
        "source_bbox": None,
        "stage8_decision": page.get("decision"),
        "stage8_route": page.get("route"),
        "stage8_gate_state": page.get("gate_state"),
        "reason": page.get("reason"),
        "execution_scope": "full_page",
        "provider_route": "UNASSIGNED",
        "input_image": None,
    }


def make_region_task(page: dict[str, Any], region: dict[str, Any]) -> dict[str, Any]:
    pn = safe_int(page.get("page_number"))
    rid = str(region.get("region_id"))
    return {
        "task_id": stable_task_id(TASK_REGION_FALLBACK, pn, rid),
        "task_type": TASK_REGION_FALLBACK,
        "status": STATUS_PREPARED,
        "page_number": pn,
        "source_id": rid,
        "source_bbox": region.get("bbox"),
        "region_type": region.get("region_type"),
        "geometry_classification": region.get("classification"),
        "raster_classification": (region.get("raster_probe") or {}).get("classification"),
        "probe_hints": (region.get("raster_probe") or {}).get("probe_hints") or {},
        "reason": (region.get("raster_probe") or {}).get("reason") or region.get("rationale"),
        "execution_scope": "region",
        "provider_route": "UNASSIGNED",
        "input_image": None,
    }


def make_context_task(page: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    pn = safe_int(page.get("page_number"))
    cid = str(ctx.get("cluster_id") or ctx.get("context_id"))
    return {
        "task_id": stable_task_id(TASK_INLINE_CONTEXT_FALLBACK, pn, cid),
        "task_type": TASK_INLINE_CONTEXT_FALLBACK,
        "status": STATUS_PREPARED,
        "page_number": pn,
        "source_id": cid,
        "source_bbox": ctx.get("context_bbox"),
        "context_mode": ctx.get("context_mode"),
        "member_region_ids": list(ctx.get("member_region_ids") or []),
        "context_region_ids": list(ctx.get("context_region_ids") or []),
        "reason": ctx.get("reason"),
        "execution_scope": "inline_context",
        "provider_route": "UNASSIGNED",
        "input_image": None,
    }


def collect_tasks(qg: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for page in qg.get("pages") or []:
        if page.get("gate_state") == "HARD_FALLBACK":
            tasks.append(make_page_task(page))
            continue

        assess = page.get("non_text_assessment") or {}
        regions = assess.get("regions") or []
        for region in regions:
            if region.get("action") == "REGION_FALLBACK_REQUIRED":
                tasks.append(make_region_task(page, region))

        contexts = assess.get("inline_raster_clusters") or assess.get("inline_raster_contexts") or []
        for ctx in contexts:
            if ctx.get("action") == "REGION_FALLBACK_REQUIRED":
                tasks.append(make_context_task(page, ctx))

    return tasks


def validate_task_uniqueness(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    task_ids = [t["task_id"] for t in tasks]
    keys = [(t["task_type"], t["page_number"], t["source_id"]) for t in tasks]
    dup_task_ids = sorted({x for x in task_ids if task_ids.count(x) > 1})
    dup_keys = sorted({x for x in keys if keys.count(x) > 1})
    if dup_task_ids or dup_keys:
        raise ValueError(f"Stage9 task 重复：task_ids={dup_task_ids}, keys={dup_keys}")

    type_counts: dict[str, int] = {}
    for t in tasks:
        type_counts[t["task_type"]] = type_counts.get(t["task_type"], 0) + 1

    return {
        "task_count": len(tasks),
        "task_type_counts": type_counts,
        "duplicate_task_id_count": 0,
        "duplicate_task_key_count": 0,
    }


def render_task_inputs(
    pdf_path: Path,
    tasks: list[dict[str, Any]],
    out_dir: Path,
    page_dpi: int,
    region_dpi: int,
) -> None:
    page_dir = out_dir / "inputs" / "page"
    region_dir = out_dir / "inputs" / "region"
    context_dir = out_dir / "inputs" / "context"
    for d in (page_dir, region_dir, context_dir):
        d.mkdir(parents=True, exist_ok=True)

    by_page: dict[int, list[dict[str, Any]]] = {}
    for t in tasks:
        by_page.setdefault(t["page_number"], []).append(t)

    with pdfplumber.open(str(pdf_path)) as pdf:
        if len(pdf.pages) < max(by_page or [0]):
            raise ValueError("PDF 页数小于 Stage9 任务最大页码")

        for pn in sorted(by_page):
            page = pdf.pages[pn - 1]
            for task in by_page[pn]:
                ttype = task["task_type"]
                if ttype == TASK_PAGE_FALLBACK:
                    img = page.to_image(resolution=page_dpi).original
                    path = page_dir / f"p{pn:04d}_page.png"
                else:
                    bbox = task.get("source_bbox")
                    if not isinstance(bbox, dict):
                        raise ValueError(f"任务缺少 bbox：{task['task_id']}")
                    clip = bbox_to_tuple(bbox)
                    cropped = page.crop(clip, strict=False)
                    img = cropped.to_image(resolution=region_dpi).original
                    if ttype == TASK_REGION_FALLBACK:
                        path = region_dir / f"p{pn:04d}_{task['source_id']}.png"
                    elif ttype == TASK_INLINE_CONTEXT_FALLBACK:
                        path = context_dir / f"p{pn:04d}_{task['source_id']}.png"
                    else:
                        raise ValueError(f"未知 task_type：{ttype}")

                img.save(path)
                task["input_image"] = str(path)
                task["render"] = {
                    "renderer": "pdfplumber",
                    "dpi": page_dpi if ttype == TASK_PAGE_FALLBACK else region_dpi,
                }


def build_markdown(doc: dict[str, Any]) -> str:
    s = doc["summary"]
    lines = [
        "# Stage 9 Fallback Execution Preparation",
        "",
        f"- 文件：{doc['source_file']}",
        f"- 页数：{doc['page_count']}",
        f"- Stage9 版本：{doc['version']}",
        f"- 状态：{doc['status']}",
        "",
        "> v0.1.0 只把 Stage8 已确认的 fallback 路由物化为稳定 execution units，并渲染统一输入图；不在本版本内选择/调用第三方 OCR、layout 或 vision provider。",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(s, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Tasks",
        "",
        "| task | type | page | source | provider | input |",
        "|---|---|---:|---|---|---|",
    ]
    for t in doc["tasks"]:
        lines.append(
            f"| {t['task_id']} | {t['task_type']} | {t['page_number']} | {t['source_id']} | {t['provider_route']} | {t.get('input_image') or '-'} |"
        )
    return "\n".join(lines) + "\n"


def create_fallback_plan(
    *,
    quality_report: QualityReport,
    quality_gate_path: Path,
    pdf_path: Path,
    output_dir: Path,
    page_dpi: int = DEFAULT_PAGE_DPI,
    region_dpi: int = DEFAULT_REGION_DPI,
    render_inputs: bool = True,
) -> FallbackPlan:
    """Build Stage 9.1 from a QualityReport without reading Stage 8 JSON."""
    quality_gate_path = Path(quality_gate_path)
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    qg = quality_report.data
    validate_stage8(qg)

    if render_inputs and not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在：{pdf_path}")

    tasks = collect_tasks(qg)
    summary = validate_task_uniqueness(tasks)
    output_dir.mkdir(parents=True, exist_ok=True)
    if render_inputs:
        render_task_inputs(pdf_path, tasks, output_dir, page_dpi, region_dpi)

    summary.update(
        {
            "page_fallback_task_count": summary["task_type_counts"].get(TASK_PAGE_FALLBACK, 0),
            "region_fallback_task_count": summary["task_type_counts"].get(TASK_REGION_FALLBACK, 0),
            "inline_context_fallback_task_count": summary["task_type_counts"].get(TASK_INLINE_CONTEXT_FALLBACK, 0),
            "rendered_input_count": sum(1 for task in tasks if task.get("input_image")),
            "provider_assigned_count": sum(
                1 for task in tasks if task.get("provider_route") != "UNASSIGNED"
            ),
        }
    )
    doc = {
        "stage": STAGE,
        "name": "fallback_executor",
        "version": VERSION,
        "fallback_execution_schema_version": SCHEMA_VERSION,
        "artifact_role": "fallback_execution_unit_manifest",
        "status": "PREPARED_FOR_PROVIDER_EXECUTION",
        "source_file": qg.get("source_file"),
        "page_count": qg.get("page_count"),
        "input": {
            "quality_gate": str(quality_gate_path),
            "quality_gate_version": qg.get("version"),
            "quality_gate_schema_version": qg.get("quality_gate_schema_version"),
            "pdf": str(pdf_path),
        },
        "principles": [
            "Stage9 consumes Stage8 routing; it does not re-run quality judgment.",
            "One Stage8 page fallback becomes one full-page execution unit.",
            "One standalone REGION_FALLBACK_REQUIRED becomes one region execution unit.",
            "One inline raster context becomes one context execution unit regardless of member glyph count.",
            "PRESERVE_WITH_NATIVE and COVERED_BY_INLINE_RASTER_CONTEXT never become execution units.",
            "Provider selection/execution is intentionally deferred to the next Stage9 provider layer.",
        ],
        "summary": summary,
        "tasks": tasks,
    }
    return FallbackPlan(doc)


def write_fallback_plan(plan: FallbackPlan, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = plan.data
    (output_dir / "fallback_execution_manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "fallback_execution_manifest.md").write_text(
        build_markdown(doc),
        encoding="utf-8",
    )


def run_fallback_planning(
    *,
    quality_gate_path: Path,
    pdf_path: Path,
    output_dir: Path,
    page_dpi: int = DEFAULT_PAGE_DPI,
    region_dpi: int = DEFAULT_REGION_DPI,
    render_inputs: bool = True,
) -> dict[str, Any]:
    """Compatibility API reading Stage 8 JSON and writing Stage 9.1 artifacts."""
    quality_gate_path = Path(quality_gate_path)
    plan = create_fallback_plan(
        quality_report=QualityReport(load_json(quality_gate_path)),
        quality_gate_path=quality_gate_path,
        pdf_path=pdf_path,
        output_dir=output_dir,
        page_dpi=page_dpi,
        region_dpi=region_dpi,
        render_inputs=render_inputs,
    )
    write_fallback_plan(plan, output_dir)
    return plan.data
