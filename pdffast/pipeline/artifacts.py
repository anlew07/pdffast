"""Stable filesystem contract for one PDFFast pipeline run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResultArtifactPaths:
    """Public results and their existing internal assembly snapshots."""

    dir: Path
    document_json: Path
    document_md: Path
    audit_json: Path
    manifest_json: Path
    canonical_snapshot: Path
    rendered_snapshot: Path


@dataclass(frozen=True)
class NativeArtifactPaths:
    """Native observations and recovered document structure."""

    profile: Path
    snapshot: Path
    sections: Path
    page_structure: Path
    tables: Path
    text_flow: Path


@dataclass(frozen=True)
class ObservabilityArtifactPaths:
    """Evidence, decisions, execution plans, rendering, and audit records."""

    evidence: Path
    quality: Path
    fallback_plan: Path
    capability_plan: Path
    execution_plan: Path
    production_manifest: Path
    render_manifest: Path
    structure_audit: Path


@dataclass(frozen=True)
class DiagnosticArtifactPaths:
    """Debug views, probes, task inputs, and the captured runtime log."""

    text_flow_dir: Path
    probe_crops_dir: Path
    fallback_inputs_dir: Path
    pipeline_log: Path


@dataclass(frozen=True)
class ProviderArtifactPaths:
    """Persisted Provider evidence at the historical execution location."""

    execution_dir: Path
    raw_dir: Path
    raw_manifest: Path
    selected_dir: Path
    selected_index: Path
    production_manifest: Path

    def raw_result(self, task_id: str) -> Path:
        return self.raw_dir / f"{task_id}.json"

    def selected_prediction(self, task_id: str) -> Path:
        return self.selected_dir / f"{task_id}.json"

    def normalized_prediction(self, task_id: str) -> Path:
        """Normalized attempts are embedded in the selected wrapper, not a second file."""
        return self.selected_prediction(task_id)


@dataclass(frozen=True)
class ArtifactPaths:
    """Existing physical paths; flat attributes remain compatibility aliases."""

    profile: Path
    snapshot: Path
    section_alignment: Path
    page_structure: Path
    table_result: Path
    normalized_flow: Path
    evidence_manifest: Path
    quality_gate: Path
    fallback_manifest: Path
    provider_plan: Path
    runtime_policy: Path
    production_manifest: Path
    selected_prediction_index: Path
    selected_predictions_dir: Path
    canonical_document: Path
    render_manifest: Path
    llm_ready: Path
    structure_audit: Path
    logs_dir: Path

    @property
    def result_dir(self) -> Path:
        return self.canonical_document.parents[1] / "result"

    @property
    def result_document(self) -> Path:
        return self.result_dir / "document.json"

    @property
    def result_markdown(self) -> Path:
        return self.result_dir / "document.md"

    @property
    def result_audit(self) -> Path:
        return self.result_dir / "audit.json"

    @property
    def result_manifest(self) -> Path:
        return self.result_dir / "manifest.json"

    @property
    def pipeline_log(self) -> Path:
        return self.logs_dir.parent / "diagnostics" / "logs" / "pipeline.log"

    @property
    def result(self) -> ResultArtifactPaths:
        return ResultArtifactPaths(
            dir=self.result_dir,
            document_json=self.result_document,
            document_md=self.result_markdown,
            audit_json=self.result_audit,
            manifest_json=self.result_manifest,
            canonical_snapshot=self.canonical_document,
            rendered_snapshot=self.llm_ready,
        )

    @property
    def native(self) -> NativeArtifactPaths:
        return NativeArtifactPaths(
            profile=self.profile,
            snapshot=self.snapshot,
            sections=self.section_alignment,
            page_structure=self.page_structure,
            tables=self.table_result,
            text_flow=self.normalized_flow,
        )

    @property
    def observability(self) -> ObservabilityArtifactPaths:
        return ObservabilityArtifactPaths(
            evidence=self.evidence_manifest,
            quality=self.quality_gate,
            fallback_plan=self.fallback_manifest,
            capability_plan=self.provider_plan,
            execution_plan=self.runtime_policy,
            production_manifest=self.production_manifest,
            render_manifest=self.render_manifest,
            structure_audit=self.structure_audit,
        )

    @property
    def diagnostics(self) -> DiagnosticArtifactPaths:
        return DiagnosticArtifactPaths(
            text_flow_dir=self.normalized_flow.parent,
            probe_crops_dir=self.quality_gate.parent / "probe_crops",
            fallback_inputs_dir=self.fallback_manifest.parent / "inputs",
            pipeline_log=self.pipeline_log,
        )

    @property
    def providers(self) -> ProviderArtifactPaths:
        execution_dir = self.production_manifest.parent
        raw_dir = execution_dir / "provider_raw"
        return ProviderArtifactPaths(
            execution_dir=execution_dir,
            raw_dir=raw_dir,
            raw_manifest=raw_dir / "runtime_manifest.json",
            selected_dir=self.selected_predictions_dir,
            selected_index=self.selected_prediction_index,
            production_manifest=self.production_manifest,
        )

    @classmethod
    def for_run(cls, run_dir: Path) -> "ArtifactPaths":
        run_dir = Path(run_dir)
        resolved = run_dir.resolve()
        if resolved == Path(resolved.anchor):
            raise ValueError("run_dir must not be the filesystem root")

        return cls(
            profile=run_dir / "01_stage1/page_profile.json",
            snapshot=run_dir / "01_stage1/page_snapshot.jsonl",
            section_alignment=run_dir / "03_stage3/section_alignment.json",
            page_structure=run_dir / "04_stage4/page_structure.json",
            table_result=run_dir / "05_stage5/result.json",
            normalized_flow=run_dir / "06_stage6/normalized_text_flow.json",
            evidence_manifest=run_dir / "07_stage7/evidence_manifest.json",
            quality_gate=run_dir / "08_stage8/quality_gate.json",
            fallback_manifest=(
                run_dir / "09_1_fallback_units/fallback_execution_manifest.json"
            ),
            provider_plan=run_dir / "09_2_provider_plan/provider_plan.json",
            runtime_policy=(
                run_dir / "09_6_3_runtime_policy/runtime_escalation_policy.json"
            ),
            production_manifest=(
                run_dir
                / "09_8_production_fallback/production_execution_manifest.json"
            ),
            selected_prediction_index=(
                run_dir / "09_8_production_fallback/selected_prediction_index.json"
            ),
            selected_predictions_dir=(
                run_dir / "09_8_production_fallback/selected_predictions"
            ),
            canonical_document=run_dir / "10_1_canonical/canonical_document.json",
            render_manifest=run_dir / "10_2_llm_ready/render_manifest.json",
            llm_ready=run_dir / "10_2_llm_ready/llm_ready.md",
            structure_audit=(
                run_dir
                / "10_2_1_structure_audit/structure_boundary_audit.json"
            ),
            logs_dir=run_dir / "logs",
        )

    def as_dict(self) -> dict[str, Path]:
        """Return a defensive, field-ordered mapping of artifact names to paths."""

        return asdict(self)
