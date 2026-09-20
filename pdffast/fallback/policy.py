#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PDFFAST Stage 9.6.3 Runtime Escalation Policy Builder
Version: 0.1.2
Schema: 1.0

Changes from v0.1.0
-------------------
1) REGION no longer uses "structure_priority=high" as a reason to put Marker
   first. None of the current enabled providers emits canonical relations, so
   a structure-oriented hint cannot justify a heavier primary provider.
2) Every REGION policy has an explicit terminal preservation fallback:
      PRESERVE_SOURCE_REGION_UNRESOLVED
   If OCR/text recovery remains empty or operationally unusable after the
   provider chain, the original region evidence is preserved instead of
   treating the document content as lost.
3) REGION OCR text is explicitly "enrichment", never a replacement for the
   original visual region while canonical structure is unresolved.
4) INLINE remains Marker-first in v0.1.1. The four DEV INLINE tasks have no
   reliable upstream hint that separates the two cases where lighter OCR is
   better from the two cases where Marker preserves more literal/math content.
   Formula quality is still unevaluated, so v0.1.1 refuses to overfit a split
   from DEV Ground Truth.
5) PAGE OCR policy is unchanged.
6) Stage8 LAYOUT_FALLBACK_REQUIRED is now routed through PAGE_DOCUMENT_LAYOUT_PARSE,
   using layout-capable providers and a structure-channel acceptance contract.

Runtime Ground Truth use remains forbidden.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

VERSION = "0.1.2"
SCHEMA_VERSION = "1.0"

BENCHMARKED_ROUTE_FRONTIER_MEMBERS = {
    "PAGE_DOCUMENT_OCR": {
        "rapidocr_ch_light",
        "mineru_local",
        "paddleocr_vl_16",
    },
    "REGION_MULTIMODAL_PARSE": {
        "rapidocr_ch_light",
        "mineru_local",
        "marker_local",
        "paddleocr_v5_mobile",
    },
    "INLINE_CONTEXT_PARSE": {
        "rapidocr_ch_light",
        "marker_local",
        "paddleocr_v5_mobile",
    },
}

ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE = "PAGE_DOCUMENT_LAYOUT_PARSE"
SUPPORTED_ROUTES = set(BENCHMARKED_ROUTE_FRONTIER_MEMBERS) | {
    ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE,
}



def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return obj


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def validate_provider_plan(plan: dict[str, Any]) -> None:
    if plan.get("stage") != 9 or plan.get("name") != "provider_router":
        raise ValueError("Input is not a Stage 9 provider plan")
    if plan.get("version") not in {"0.2.0", "0.2.1"}:
        raise ValueError(
            f"Unsupported provider plan version: {plan.get('version')!r}"
        )
    if plan.get("status") != "ROUTED_PROVIDER_UNBOUND":
        raise ValueError(
            f"Provider plan status must be ROUTED_PROVIDER_UNBOUND, got "
            f"{plan.get('status')!r}"
        )

    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Provider plan tasks missing/empty")

    seen = set()
    for task in tasks:
        tid = task.get("task_id")
        if not isinstance(tid, str) or not tid:
            raise ValueError("Provider-plan task missing task_id")
        if tid in seen:
            raise ValueError(f"Duplicate provider-plan task_id: {tid}")
        seen.add(tid)

        if task.get("status") != "ROUTED":
            raise ValueError(f"{tid}: task status is not ROUTED")

        route = task.get("capability_route")
        if route not in SUPPORTED_ROUTES:
            raise ValueError(f"{tid}: unsupported capability_route={route!r}")


def validate_candidates(candidates: dict[str, Any]) -> None:
    if candidates.get("stage") != 9 or candidates.get("substage") != "9.6.2":
        raise ValueError("Input is not a Stage 9.6.2 candidate report")
    if candidates.get("version") != "0.1.0":
        raise ValueError(
            f"Unsupported Stage 9.6.2 version: {candidates.get('version')!r}"
        )

    routes = candidates.get("routes")
    if not isinstance(routes, dict):
        raise ValueError("Candidate report routes missing")

    for route, expected_members in BENCHMARKED_ROUTE_FRONTIER_MEMBERS.items():
        if route not in routes:
            raise ValueError(f"Candidate report missing route {route}")

        frontier = set(
            (((routes[route].get("frontiers") or {}).get("quality_latency") or {})
             .get("frontier"))
            or []
        )
        if frontier != expected_members:
            raise ValueError(
                f"{route}: reviewed quality+latency frontier changed; "
                f"expected={sorted(expected_members)}, "
                f"actual={sorted(frontier)}"
            )


def provider_chain_entry(
    provider: str,
    role: str,
    purpose: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "role": role,
        "purpose": purpose,
    }


def common_runtime_escalation() -> dict[str, Any]:
    return {
        "hard_triggers": [
            {
                "code": "PROVIDER_EXECUTION_ERROR",
                "condition": (
                    "canonical.status not in "
                    "SUCCESS/SUCCESS_WITH_WARNINGS"
                ),
            },
            {
                "code": "TEXT_CHANNEL_UNAVAILABLE",
                "condition": (
                    "text.availability != AVAILABLE when text is required"
                ),
            },
            {
                "code": "EMPTY_TEXT_WHEN_REQUIRED",
                "condition": (
                    "text.content is empty/whitespace and "
                    "output_contract.empty_text_requires_warning=true"
                ),
            },
        ],
        "soft_observations": [
            {
                "code": "WARNINGS_PRESENT",
                "condition": "canonical.warnings is non-empty",
                "action": (
                    "retain warning in final provenance; do not auto-reject "
                    "solely because a warning exists"
                ),
            }
        ],
        "forbidden_runtime_signals": [
            "ground_truth",
            "TEXT_NED",
            "key_fact_recall",
            "literal_presence_recall",
            "human_review_label",
        ],
    }


def page_policy(task: dict[str, Any]) -> dict[str, Any]:
    hints = task.get("route_hints") or {}
    return {
        "policy_class": "PAGE_FAST_OCR_ESCALATION",
        "provider_chain": [
            provider_chain_entry(
                "rapidocr_ch_light",
                "PRIMARY_FAST_PATH",
                "low-latency page text recovery",
            ),
            provider_chain_entry(
                "mineru_local",
                "SECONDARY_FALLBACK",
                "richer page parse when fast OCR is operationally incomplete",
            ),
            provider_chain_entry(
                "paddleocr_vl_16",
                "HEAVY_FALLBACK",
                "last-resort heavy page parse; high latency remains visible",
            ),
        ],
        "runtime_escalation": common_runtime_escalation(),
        "acceptance": {
            "required": [
                "provider status is SUCCESS or SUCCESS_WITH_WARNINGS",
                "text.availability == AVAILABLE",
                "text.content is non-empty",
            ],
            "notes": [
                "PAGE policy is unchanged from v0.1.0.",
                "Table and reading-order QUALITY remain unverified.",
                "Do not escalate solely because structural channels were not emitted.",
            ],
        },
        "terminal_fallback": None,
        "capability_gaps": [
            "TABLE_QUALITY_NOT_VERIFIED",
            "READING_ORDER_QUALITY_NOT_VERIFIED",
        ],
        "source_hints": hints,
    }


def page_layout_policy(task: dict[str, Any]) -> dict[str, Any]:
    hints = task.get("route_hints") or {}
    return {
        "policy_class": "PAGE_LAYOUT_PARSE_ESCALATION",
        "provider_chain": [
            provider_chain_entry(
                "mineru_local",
                "PRIMARY_LAYOUT_PARSE",
                "full-page layout parse with explicit reading-block/table emission when available",
            ),
            provider_chain_entry(
                "marker_local",
                "SECONDARY_LAYOUT_PARSE",
                "alternate document-layout parse with explicit reading-block emission",
            ),
            provider_chain_entry(
                "docling_local",
                "TERTIARY_LAYOUT_PARSE",
                "last-resort document-layout parse; accepted only when the canonical output satisfies the structure contract",
            ),
        ],
        "runtime_escalation": common_runtime_escalation(),
        "acceptance": {
            "required": [
                "provider status is SUCCESS or SUCCESS_WITH_WARNINGS",
                "text.availability == AVAILABLE",
                "text.content is non-empty",
                "at least one required structure channel is AVAILABLE with non-empty items",
            ],
            "notes": [
                "This route is used only for Stage8 LAYOUT_FALLBACK_REQUIRED pages.",
                "Flat OCR alone is not sufficient for acceptance.",
                "The frozen DEV route benchmark did not contain this route; provider order is an explicit capability contract, not a quality ranking.",
            ],
        },
        "terminal_fallback": None,
        "capability_gaps": [
            "PAGE_LAYOUT_ROUTE_NOT_FROZEN_BENCHMARKED",
            "SEMANTIC_RELATIONS_NOT_REQUIRED_FOR_PAGE_LAYOUT_ACCEPTANCE",
        ],
        "source_hints": hints,
    }


def region_policy(task: dict[str, Any]) -> dict[str, Any]:
    hints = task.get("route_hints") or {}

    text_priority = hints.get("text_recovery_priority")
    structure_priority = hints.get("structure_recovery_priority")
    conflict = bool(hints.get("conflicting_visual_signals"))
    continuous_tone = bool(hints.get("continuous_tone_present_hint"))

    # v0.1.1 principle:
    # structure/high visual complexity can justify keeping the source region
    # and a richer fallback, but NOT a heavier primary provider because no
    # enabled provider can currently satisfy canonical relation recovery.
    if text_priority == "high":
        policy_class = "REGION_TEXT_FIRST"
        chain = [
            provider_chain_entry(
                "rapidocr_ch_light",
                "PRIMARY_FAST_TEXT",
                "fast region text recovery",
            ),
            provider_chain_entry(
                "paddleocr_v5_mobile",
                "SECONDARY_TEXT_FALLBACK",
                "alternate OCR when primary is operationally incomplete",
            ),
            provider_chain_entry(
                "marker_local",
                "RICHER_TEXT_FALLBACK",
                "last text-enrichment fallback; not structural resolution",
            ),
        ]

    elif (
        structure_priority == "high"
        or conflict
        or continuous_tone
    ):
        policy_class = "REGION_COMPLEX_GAP_AWARE"
        chain = [
            provider_chain_entry(
                "rapidocr_ch_light",
                "PRIMARY_FAST_TEXT",
                (
                    "fast text enrichment; visual/structural source is always "
                    "preserved independently"
                ),
            ),
            provider_chain_entry(
                "marker_local",
                "SECONDARY_TEXT_ENRICHMENT",
                (
                    "richer emitted blocks/text fallback; canonical relations "
                    "remain unsupported"
                ),
            ),
        ]

    else:
        policy_class = "REGION_GENERIC_GAP_AWARE"
        chain = [
            provider_chain_entry(
                "rapidocr_ch_light",
                "PRIMARY_FAST_TEXT",
                "generic region text enrichment",
            ),
            provider_chain_entry(
                "marker_local",
                "SECONDARY_TEXT_ENRICHMENT",
                (
                    "richer text fallback if primary is operationally "
                    "incomplete"
                ),
            ),
        ]

    runtime = common_runtime_escalation()
    runtime["non_resolvable_trigger"] = {
        "code": "EXPLICIT_STRUCTURE_REQUIRED_BUT_RELATIONS_UNAVAILABLE",
        "condition": (
            "route_hints.recover_region_structure == true and current enabled "
            "providers emit no canonical relations"
        ),
        "action": (
            "never claim structural recovery; preserve original region and "
            "mark unresolved capability gap"
        ),
    }

    return {
        "policy_class": policy_class,
        "provider_chain": chain,
        "runtime_escalation": runtime,
        "acceptance": {
            "text_role": "OPTIONAL_ENRICHMENT_OVER_PRESERVED_SOURCE_REGION",
            "text_enrichment_acceptance": [
                "provider status is SUCCESS or SUCCESS_WITH_WARNINGS",
                "text.availability == AVAILABLE",
                (
                    "non-empty text may enrich the LLM-ready representation, "
                    "but does not replace the source visual region"
                ),
            ],
            "structural_acceptance": "UNRESOLVED_WITH_CURRENT_PROVIDER_SET",
            "required_final_provenance": [
                "always preserve original region reference/input image path",
                "mark canonical relations unavailable",
                (
                    "do not serialize inferred parent-child/arrow/field-value "
                    "relations from flat OCR text"
                ),
            ],
        },
        "terminal_fallback": {
            "action": "PRESERVE_SOURCE_REGION_UNRESOLVED",
            "when": (
                "provider chain is exhausted because text is empty/unavailable "
                "or provider execution fails"
            ),
            "pipeline_semantics": "CONTENT_PRESERVED_NOT_PROVIDER_SUCCESS",
            "output": [
                "retain source region/image reference",
                "retain provider warnings/attempt provenance",
                "emit no invented text",
                "emit no invented relations",
                "mark text recovery unresolved if no usable text exists",
                "mark structural recovery unresolved",
            ],
        },
        "capability_gaps": [
            "EXPLICIT_RELATION_OUTPUT_GAP",
        ],
        "source_hints": hints,
    }


def inline_policy(task: dict[str, Any]) -> dict[str, Any]:
    hints = task.get("route_hints") or {}

    runtime = common_runtime_escalation()
    runtime["soft_observations"] = [
        *runtime["soft_observations"],
        {
            "code": "FORMULA_CHANNEL_NOT_EMITTED",
            "condition": (
                "math_symbol_support_preferred=true and "
                "formulas.availability != AVAILABLE"
            ),
            "action": (
                "retain as formula-capability warning; current frozen GT does "
                "not justify treating formula availability as correctness"
            ),
        },
    ]

    return {
        "policy_class": "INLINE_MATH_CONTEXT",
        "provider_chain": [
            provider_chain_entry(
                "marker_local",
                "PRIMARY_CONTEXT_PARSE",
                (
                    "math-aware inline/context parse; DEV emitted formula "
                    "channel on all four INLINE samples"
                ),
            ),
            provider_chain_entry(
                "rapidocr_ch_light",
                "FAST_TEXT_RESCUE",
                "recover surrounding text if primary is operationally unusable",
            ),
            provider_chain_entry(
                "paddleocr_v5_mobile",
                "SECONDARY_TEXT_RESCUE",
                "alternate text recovery if earlier attempts fail operationally",
            ),
        ],
        "runtime_escalation": runtime,
        "acceptance": {
            "required": [
                "provider status is SUCCESS or SUCCESS_WITH_WARNINGS",
                "text.availability == AVAILABLE",
                "text.content is non-empty",
            ],
            "notes": [
                (
                    "INLINE policy intentionally remains unified because the "
                    "current upstream hints do not reliably separate DEV cases "
                    "where lighter OCR outperforms Marker from cases where "
                    "Marker preserves more literal/math content."
                ),
                (
                    "Do not split INLINE by task_id, member count, or DEV GT. "
                    "Such a split would be benchmark overfitting."
                ),
                (
                    "Marker-first remains provisional until formula MATH/CDM "
                    "quality has a canonical frozen reference."
                ),
            ],
        },
        "terminal_fallback": None,
        "capability_gaps": [
            "FORMULA_QUALITY_NOT_VERIFIED",
            "INLINE_POLICY_DISCRIMINATOR_NOT_AVAILABLE",
        ],
        "source_hints": hints,
    }


def task_policy(task: dict[str, Any]) -> dict[str, Any]:
    route = task["capability_route"]

    if route == "PAGE_DOCUMENT_OCR":
        policy = page_policy(task)
    elif route == ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE:
        policy = page_layout_policy(task)
    elif route == "REGION_MULTIMODAL_PARSE":
        policy = region_policy(task)
    elif route == "INLINE_CONTEXT_PARSE":
        policy = inline_policy(task)
    else:
        raise ValueError(f"Unsupported route: {route}")

    return {
        "task_id": task["task_id"],
        "task_type": task.get("task_type"),
        "page_number": task.get("page_number"),
        "source_id": task.get("source_id"),
        "input_image": task.get("input_image"),
        "stage8_decision": task.get("stage8_decision"),
        "stage8_route": task.get("stage8_route"),
        "stage8_gate_state": task.get("stage8_gate_state"),
        "capability_route": route,
        "output_contract": task.get("output_contract"),
        **policy,
    }


def build_report(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    policies = [task_policy(t) for t in plan["tasks"]]

    class_counts = Counter(p["policy_class"] for p in policies)
    route_counts = Counter(p["capability_route"] for p in policies)
    first_provider_counts = Counter(
        p["provider_chain"][0]["provider"]
        for p in policies
        if p.get("provider_chain")
    )
    terminal_fallback_counts = Counter(
        (p.get("terminal_fallback") or {}).get("action")
        for p in policies
        if p.get("terminal_fallback")
    )

    unresolved_structure_tasks = [
        p["task_id"]
        for p in policies
        if p["capability_route"] == "REGION_MULTIMODAL_PARSE"
        and p["acceptance"].get("structural_acceptance")
        == "UNRESOLVED_WITH_CURRENT_PROVIDER_SET"
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "stage": 9,
        "substage": "9.6.3",
        "name": "runtime_escalation_policy",
        "version": VERSION,
        "source_file": plan.get("source_file"),
        "source_versions": {
            "provider_plan_version": plan.get("version"),
            "route_candidate_version": candidates.get("version"),
        },
        "revision_notes": [
            "REGION heavy-first behavior removed.",
            (
                "REGION terminal preservation fallback added so empty OCR does "
                "not mean source content is lost."
            ),
            (
                "INLINE remains Marker-first because no runtime-safe upstream "
                "discriminator exists in current hints."
            ),
            "PAGE OCR policy unchanged.",
            "Stage8 LAYOUT_FALLBACK_REQUIRED now has an independent PAGE_DOCUMENT_LAYOUT_PARSE policy; flat OCR is never accepted as a substitute.",
        ],
        "principles": {
            "runtime_only_observable_signals": True,
            "ground_truth_forbidden_at_runtime": True,
            "no_weighted_score": True,
            "no_semantic_relation_inference_from_flat_ocr": True,
            "capability_gaps_are_explicit": True,
            "source_region_preserved_for_all_region_tasks": True,
            "no_dev_task_id_overfitting": True,
            "policy_is_provisional_until_stage_9_6_4_validation": True,
        },
        "summary": {
            "task_count": len(policies),
            "route_counts": dict(sorted(route_counts.items())),
            "policy_class_counts": dict(sorted(class_counts.items())),
            "first_provider_counts": dict(sorted(first_provider_counts.items())),
            "terminal_fallback_counts": dict(
                sorted(terminal_fallback_counts.items())
            ),
            "unresolved_structure_task_count": len(
                unresolved_structure_tasks
            ),
            "unresolved_structure_task_ids": unresolved_structure_tasks,
        },
        "route_basis": {
            **{
                route: {
                    "quality_latency_frontier": (
                        candidates["routes"][route]["frontiers"]
                        ["quality_latency"]["frontier"]
                    ),
                    "known_gaps": [
                        g["code"]
                        for g in candidates["routes"][route].get("gaps", [])
                    ],
                    "basis": "FROZEN_DEV_ROUTE_BENCHMARK",
                }
                for route in BENCHMARKED_ROUTE_FRONTIER_MEMBERS
            },
            ROUTE_PAGE_DOCUMENT_LAYOUT_PARSE: {
                "quality_latency_frontier": None,
                "known_gaps": ["PAGE_LAYOUT_ROUTE_NOT_FROZEN_BENCHMARKED"],
                "basis": "EXPLICIT_LAYOUT_CAPABILITY_CONTRACT",
            },
        },
        "tasks": policies,
    }


def make_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]

    lines = [
        "# Stage 9.6.3 Runtime Escalation Policy",
        "",
        f"Version: `{report['version']}` | Source file: `{report.get('source_file')}`",
        "",
        (
            "This remains provisional until Stage 9.6.4 replay validation. "
            "Ground Truth is forbidden from runtime decisions."
        ),
        "",
        "## Summary",
        "",
        "```text",
        f"Tasks                         {s['task_count']}",
        f"Route counts                  {s['route_counts']}",
        f"Policy class counts           {s['policy_class_counts']}",
        f"First-provider counts         {s['first_provider_counts']}",
        f"Terminal fallback counts      {s['terminal_fallback_counts']}",
        f"Unresolved structure tasks    {s['unresolved_structure_task_count']}",
        "```",
        "",
        "## Route policy",
        "",
        "```text",
        "PAGE OCR",
        "  rapidocr_ch_light -> mineru_local -> paddleocr_vl_16",
        "",
        "PAGE LAYOUT",
        "  mineru_local -> marker_local -> docling_local",
        "  acceptance requires text + explicit reading_blocks/tables",
        "",
        "REGION text-first",
        "  rapidocr_ch_light -> paddleocr_v5_mobile -> marker_local",
        "",
        "REGION complex/generic",
        "  rapidocr_ch_light -> marker_local",
        "",
        "REGION terminal fallback",
        "  PRESERVE_SOURCE_REGION_UNRESOLVED",
        "",
        "INLINE",
        "  marker_local -> rapidocr_ch_light -> paddleocr_v5_mobile",
        "```",
        "",
        "## Revision rationale",
        "",
        (
            "- REGION `structure_priority=high` no longer makes Marker primary. "
            "No enabled provider currently emits canonical relations."
        ),
        (
            "- REGION OCR is enrichment over a preserved source region. If all "
            "provider attempts remain empty/unusable, the region is preserved "
            "and explicitly marked unresolved instead of being dropped."
        ),
        (
            "- INLINE is not split using DEV-specific patterns because current "
            "upstream hints do not provide a reliable runtime discriminator."
        ),
        (
            "- PAGE OCR remains unchanged because the frozen benchmark supports that route. "
            "PAGE layout is a separate capability route and is not inferred from OCR success."
        ),
        "",
    ]
    return "\n".join(lines)


def run_runtime_policy(
    *,
    provider_plan_path: Path,
    route_candidates_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run Stage 9.6.3 from the provider plan and frozen route candidates."""
    provider_plan_path = Path(provider_plan_path)
    route_candidates_path = Path(route_candidates_path)
    output_dir = Path(output_dir)
    plan = load_json(provider_plan_path)
    candidates = load_json(route_candidates_path)
    validate_provider_plan(plan)
    validate_candidates(candidates)
    report = build_report(plan, candidates)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "runtime_escalation_policy.json", report)
    (output_dir / "runtime_escalation_policy.md").write_text(
        make_markdown(report),
        encoding="utf-8",
    )
    return report

