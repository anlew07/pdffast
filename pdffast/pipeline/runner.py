"""Core orchestration for the final Phase 4 artifacts.

Stage 1-9 remain owned by their existing migration APIs. This runner deliberately starts
at the Stage 10 boundary so service adapters can call the same pure Core functions later.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from pdffast.audit.structure_boundary import audit
from pdffast.canonical.builder import build_document
from pdffast.fallback.executor import execute_provider_plan
from pdffast.fallback.planner import create_fallback_plan, write_fallback_plan
from pdffast.fallback.policy import create_provider_execution_plan, write_provider_execution_plan
from pdffast.fallback.router import create_capability_plan, write_capability_plan
from pdffast.native.profiler import run_profiler
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import create_text_flow_result, write_text_flow_result
from pdffast.pipeline.context import PipelineContext
from pdffast.quality.evidence import create_evidence_report, write_evidence_report
from pdffast.quality.gate import evaluate_evidence_report, write_quality_report
from pdffast.render.llm_ready import build_rendered_document
from pdffast.runtime import capture_runtime_output
from pdffast.errors import ParseExecutionError
from pdffast.result import ParseResult
from pdffast.template.aligner import run_section_alignment
from pdffast.template.detector import run_template_analysis


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_stage10(context: PipelineContext) -> dict[str, Any]:
    """Build canonical JSON, Markdown, manifest, and structural audit for one run."""

    a = context.artifacts
    canonical = build_document(
        a.normalized_flow,
        a.quality_gate,
        a.provider_plan,
        a.selected_prediction_index,
        a.selected_predictions_dir,
    )
    canonical_dir = a.canonical_document.parent
    canonical_dir.mkdir(parents=True, exist_ok=True)
    a.canonical_document.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    markdown, manifest = build_rendered_document(canonical)
    render_dir = a.llm_ready.parent
    render_dir.mkdir(parents=True, exist_ok=True)
    a.llm_ready.write_text(markdown, encoding="utf-8")
    manifest["inputs"] = {"canonical_document": str(a.canonical_document)}
    manifest["outputs"] = {
        "llm_ready_markdown": str(a.llm_ready),
        "render_manifest": str(a.render_manifest),
    }
    a.render_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result = audit(
        _load(a.normalized_flow),
        _load(a.quality_gate),
        canonical,
        manifest,
    )
    audit_dir = a.structure_audit.parent
    audit_dir.mkdir(parents=True, exist_ok=True)
    a.structure_audit.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    a.result_dir.mkdir(parents=True, exist_ok=True)
    a.result_document.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    a.result_markdown.write_text(markdown, encoding="utf-8")
    a.result_audit.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    public_manifest: dict[str, Any] = {
        "run_id": context.run_id,
        "case_id": context.case_id,
        "output_mode": context.output_mode,
        "result": {
            "document": str(a.result_document),
            "markdown": str(a.result_markdown),
            "audit": str(a.result_audit),
        },
    }
    if context.output_mode in {"diagnostic", "full"}:
        public_manifest["diagnostics"] = {"log": str(a.pipeline_log)}
    a.result_manifest.write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "canonical": canonical,
        "markdown": markdown,
        "render_manifest": manifest,
        "structure_audit": result,
        "result_dir": a.result_dir,
        "result_document": a.result_document,
        "result_markdown": a.result_markdown,
        "result_audit": a.result_audit,
        "result_manifest": a.result_manifest,
        "pipeline_log": a.pipeline_log,
        "output_mode": context.output_mode,
    }


def run_core_pipeline(
    context: PipelineContext,
    *,
    provider_configs: dict[str, dict[str, Any]] | None = None,
    registry: Any | None = None,
    normalizer: Any | None = None,
    execute_providers: bool = False,
) -> dict[str, Any]:
    """Run the migrated Core stages from PDF through Stage 10.

    Provider execution is explicit because it can start heavyweight workers. When
    ``execute_providers`` is false, the pipeline stops after producing the Stage 9
    policy and requires pre-existing selected predictions for Stage 10.
    """

    a = context.artifacts
    try:
        with capture_runtime_output(a.pipeline_log, enabled=context.capture_output):
            run_profiler(pdf_path=context.pdf, profile_output=a.profile, snapshot_output=a.snapshot, table_mode=context.table_mode)
            run_template_analysis(profile_path=a.profile, template_path=context.templates, output_path=a.template_analysis)
            run_section_alignment(analysis_path=a.template_analysis, template_path=context.templates, snapshot_path=a.snapshot, output_path=a.section_alignment)
            run_page_structure(snapshot_path=a.snapshot, profile_path=a.profile, alignment_path=a.section_alignment, output_path=a.page_structure)
            run_table_recovery(structure_path=a.page_structure, snapshot_path=a.snapshot, output_dir=a.table_result.parent)
            text_flow_result = create_text_flow_result(snapshot_path=a.snapshot, structure_path=a.page_structure, table_result_path=a.table_result)
            write_text_flow_result(text_flow_result, a.normalized_flow.parent)
            evidence_report = create_evidence_report(profile_path=a.profile, snapshot_path=a.snapshot, template_path=context.templates, alignment_path=a.section_alignment, structure_path=a.page_structure, stage5_path=a.table_result, stage6_dir=a.normalized_flow.parent, text_flow=text_flow_result)
            write_evidence_report(evidence_report, a.evidence_manifest.parent)
            quality_report = evaluate_evidence_report(evidence_report, manifest_path=a.evidence_manifest, pdf_path=context.pdf, output_dir=a.quality_gate.parent, probe_dpi=context.region_dpi, save_probe_crops=True)
            write_quality_report(quality_report, a.quality_gate.parent)
            fallback_plan = create_fallback_plan(quality_report=quality_report, quality_gate_path=a.quality_gate, pdf_path=context.pdf, output_dir=a.fallback_manifest.parent, page_dpi=context.page_dpi, region_dpi=context.region_dpi, render_inputs=True)
            write_fallback_plan(fallback_plan, a.fallback_manifest.parent)
            capability_plan = create_capability_plan(fallback_plan=fallback_plan, manifest_path=a.fallback_manifest)
            write_capability_plan(capability_plan, a.provider_plan.parent)
            execution_plan = create_provider_execution_plan(capability_plan, context.route_candidates)
            write_provider_execution_plan(execution_plan, a.runtime_policy.parent)

            if not execute_providers:
                raise RuntimeError("Stage 9 provider execution is disabled; pass execute_providers=True with explicit runtime dependencies")
            if provider_configs is None or registry is None or normalizer is None:
                raise ValueError("provider_configs, registry, and normalizer are required when execute_providers=True")
            production = execute_provider_plan(execution_plan=execution_plan, provider_configs=provider_configs, registry=registry, normalizer=normalizer, output_dir=a.production_manifest.parent)
            final = run_stage10(context)
            final["production_manifest"] = production.manifest
            return ParseResult.from_pipeline(context, final)
    except ParseExecutionError:
        raise
    except Exception as exc:
        if context.capture_output:
            a.pipeline_log.parent.mkdir(parents=True, exist_ok=True)
            with a.pipeline_log.open("a", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        raise ParseExecutionError(
            f"PDF 解析失败：{type(exc).__name__}: {exc}",
            run_dir=context.run_dir,
            log_path=a.pipeline_log,
        ) from exc
