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
from pdffast.canonical.document_units import resolve_document_units_from_artifacts
from pdffast.fallback.executor import ProviderExecutionResult, execute_provider_plan
from pdffast.fallback.planner import create_fallback_plan, write_fallback_plan
from pdffast.fallback.policy import create_provider_execution_plan, write_provider_execution_plan
from pdffast.fallback.router import CapabilityPlan, create_capability_plan, write_capability_plan
from pdffast.native.profiler import run_profiler
from pdffast.native.sections import run_section_discovery
from pdffast.native.structure import run_page_structure
from pdffast.native.tables import run_table_recovery
from pdffast.native.text_flow import TextFlowResult, create_text_flow_result, write_text_flow_result
from pdffast.pipeline.context import PipelineContext
from pdffast.quality.evidence import create_evidence_report, write_evidence_report
from pdffast.quality.gate import QualityReport, evaluate_evidence_report, write_quality_report
from pdffast.render.llm_ready import build_rendered_document
from pdffast.runtime import capture_runtime_output, observe_parse, runtime_progress
from pdffast.errors import ParseExecutionError
from pdffast.result import ParseResult


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_stage10(
    context: PipelineContext, *, selection: ProviderExecutionResult | None = None,
    section_alignment: dict[str, Any] | None = None,
    text_flow: TextFlowResult | None = None,
    quality_report: QualityReport | None = None,
    capability_plan: CapabilityPlan | None = None,
) -> dict[str, Any]:
    """Build canonical JSON, Markdown, manifest, and structural audit for one run."""

    a = context.artifacts
    native = a.native
    observable = a.observability
    providers = a.providers
    result_paths = a.result
    diagnostics = a.diagnostics
    coverage = ()
    admissions = ()
    if section_alignment is not None or native.sections.is_file():
        coverage, admissions = resolve_document_units_from_artifacts(
            native.sections,
            native.text_flow,
            providers.selected_index,
            providers.selected_dir,
            selected_index=selection.selected_index if selection is not None else None,
            selected_predictions=selection.selected_predictions if selection is not None else None,
            native_structure=section_alignment,
            native_flow=text_flow.normalized_flow if text_flow is not None else None,
        )
    runtime_progress("canonical_started", "canonical")
    canonical = build_document(
        native.text_flow,
        observable.quality,
        observable.capability_plan,
        providers.selected_index,
        providers.selected_dir,
        document_units=coverage,
        admissions=admissions,
        selected_index_data=selection.selected_index if selection is not None else None,
        selected_predictions=selection.selected_predictions if selection is not None else None,
        native_flow_data=text_flow.normalized_flow if text_flow is not None else None,
        quality_data=quality_report.data if quality_report is not None else None,
        plan_data=capability_plan.data if capability_plan is not None else None,
    )
    canonical_dir = result_paths.canonical_snapshot.parent
    canonical_dir.mkdir(parents=True, exist_ok=True)
    result_paths.canonical_snapshot.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    runtime_progress("canonical_completed", "canonical")

    runtime_progress("renderer_started", "renderer")
    markdown, manifest = build_rendered_document(canonical)
    render_dir = result_paths.rendered_snapshot.parent
    render_dir.mkdir(parents=True, exist_ok=True)
    result_paths.rendered_snapshot.write_text(markdown, encoding="utf-8")
    manifest["inputs"] = {"canonical_document": str(result_paths.canonical_snapshot)}
    manifest["outputs"] = {
        "llm_ready_markdown": str(result_paths.rendered_snapshot),
        "render_manifest": str(observable.render_manifest),
    }
    observable.render_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    runtime_progress("renderer_completed", "renderer")

    runtime_progress("audit_started", "audit")
    result = audit(
        text_flow.normalized_flow if text_flow is not None else _load(native.text_flow),
        quality_report.data if quality_report is not None else _load(observable.quality),
        canonical,
        manifest,
        markdown=markdown,
    )
    audit_dir = observable.structure_audit.parent
    audit_dir.mkdir(parents=True, exist_ok=True)
    observable.structure_audit.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    runtime_progress("audit_completed", "audit")
    runtime_progress("result_writing_started", "result_writing")
    result_paths.dir.mkdir(parents=True, exist_ok=True)
    result_paths.document_json.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result_paths.document_md.write_text(markdown, encoding="utf-8")
    result_paths.audit_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    public_manifest: dict[str, Any] = {
        "run_id": context.run_id,
        "case_id": context.case_id,
        "output_mode": context.output_mode,
        "result": {
            "document": str(result_paths.document_json),
            "markdown": str(result_paths.document_md),
            "audit": str(result_paths.audit_json),
        },
    }
    if context.output_mode in {"diagnostic", "full"}:
        public_manifest["diagnostics"] = {"log": str(diagnostics.pipeline_log)}
    result_paths.manifest_json.write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "canonical": canonical,
        "markdown": markdown,
        "render_manifest": manifest,
        "structure_audit": result,
        "result_dir": result_paths.dir,
        "result_document": result_paths.document_json,
        "result_markdown": result_paths.document_md,
        "result_audit": result_paths.audit_json,
        "result_manifest": result_paths.manifest_json,
        "pipeline_log": diagnostics.pipeline_log,
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
    native = a.native
    observable = a.observability
    providers = a.providers
    diagnostics = a.diagnostics
    try:
        with observe_parse(
            context.run_id,
            log_path=diagnostics.pipeline_log if context.capture_output else None,
        ), capture_runtime_output(diagnostics.pipeline_log, enabled=context.capture_output):
            runtime_progress("native_analysis_started", "native_observation")
            snapshot_pages: dict[int, dict[str, Any]] = {}
            snapshot_meta: dict[str, Any] = {}
            profile = run_profiler(
                pdf_path=context.pdf,
                profile_output=native.profile,
                snapshot_output=native.snapshot,
                table_mode=context.table_mode,
                snapshot_pages=snapshot_pages,
                snapshot_meta=snapshot_meta,
            )
            runtime_progress("native_observation_completed", "section_discovery")
            section_alignment = run_section_discovery(
                profile_path=native.profile,
                snapshot_path=native.snapshot,
                output_path=native.sections,
                profile=profile,
                snapshot_pages=snapshot_pages,
            )
            runtime_progress("section_discovery_completed", "page_structure")
            page_structure = run_page_structure(
                snapshot_path=native.snapshot,
                profile_path=native.profile,
                alignment_path=native.sections,
                output_path=native.page_structure,
                snapshot_meta=snapshot_meta,
                snapshot_pages=snapshot_pages,
                section_alignment=section_alignment,
                profile=profile,
            )
            runtime_progress("page_structure_completed", "table_recovery")
            table_result = run_table_recovery(structure_path=native.page_structure, snapshot_path=native.snapshot, output_dir=native.tables.parent, page_structure=page_structure, snapshot_pages=snapshot_pages)
            runtime_progress("table_recovery_completed", "text_flow")
            text_flow_result = create_text_flow_result(snapshot_path=native.snapshot, structure_path=native.page_structure, table_result_path=native.tables, table_result=table_result, snapshot_meta=snapshot_meta, snapshot_pages=snapshot_pages, page_structure=page_structure)
            write_text_flow_result(text_flow_result, diagnostics.text_flow_dir)
            runtime_progress("native_analysis_finished", "native_analysis")
            runtime_progress("evidence_started", "evidence")
            evidence_report = create_evidence_report(profile_path=native.profile, snapshot_path=native.snapshot, alignment_path=native.sections, structure_path=native.page_structure, stage5_path=native.tables, stage6_dir=diagnostics.text_flow_dir, text_flow=text_flow_result, table_result=table_result, profile=profile, snapshot_meta=snapshot_meta, snapshot_pages=snapshot_pages, section_alignment=section_alignment, page_structure=page_structure)
            del snapshot_meta, snapshot_pages, page_structure
            write_evidence_report(evidence_report, observable.evidence.parent)
            runtime_progress("evidence_completed", "quality")
            quality_report = evaluate_evidence_report(evidence_report, manifest_path=observable.evidence, pdf_path=context.pdf, output_dir=observable.quality.parent, probe_dpi=context.region_dpi, save_probe_crops=True)
            write_quality_report(quality_report, observable.quality.parent)
            runtime_progress("quality_completed", "quality")
            runtime_progress("fallback_planning_started", "fallback_planning")
            fallback_plan = create_fallback_plan(quality_report=quality_report, quality_gate_path=observable.quality, pdf_path=context.pdf, output_dir=observable.fallback_plan.parent, page_dpi=context.page_dpi, region_dpi=context.region_dpi, render_inputs=True)
            write_fallback_plan(fallback_plan, observable.fallback_plan.parent)
            runtime_progress("fallback_planning_completed", "fallback_planning")
            runtime_progress("capability_routing_started", "capability_routing")
            capability_plan = create_capability_plan(fallback_plan=fallback_plan, manifest_path=observable.fallback_plan)
            write_capability_plan(capability_plan, observable.capability_plan.parent)
            runtime_progress("capability_routing_completed", "provider_policy")
            execution_plan = create_provider_execution_plan(capability_plan, context.route_candidates)
            write_provider_execution_plan(execution_plan, observable.execution_plan.parent)

            if not execute_providers:
                raise RuntimeError("Stage 9 provider execution is disabled; pass execute_providers=True with explicit runtime dependencies")
            if provider_configs is None or registry is None or normalizer is None:
                raise ValueError("provider_configs, registry, and normalizer are required when execute_providers=True")
            runtime_progress("provider_execution_started", "provider_execution")
            production = execute_provider_plan(execution_plan=execution_plan, provider_configs=provider_configs, registry=registry, normalizer=normalizer, output_dir=providers.execution_dir)
            final = run_stage10(
                context, selection=production, section_alignment=section_alignment,
                text_flow=text_flow_result, quality_report=quality_report,
                capability_plan=capability_plan,
            )
            final["production_manifest"] = production.manifest
            return ParseResult.from_pipeline(context, final)
    except ParseExecutionError:
        raise
    except Exception as exc:
        if context.capture_output:
            diagnostics.pipeline_log.parent.mkdir(parents=True, exist_ok=True)
            with diagnostics.pipeline_log.open("a", encoding="utf-8") as stream:
                traceback.print_exc(file=stream)
        raise ParseExecutionError(
            f"PDF 解析失败：{type(exc).__name__}: {exc}",
            run_dir=context.run_dir,
            log_path=diagnostics.pipeline_log,
        ) from exc
