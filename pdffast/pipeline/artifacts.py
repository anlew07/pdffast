"""Stable filesystem contract for one PDFFast pipeline run."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactPaths:
    """All production artifact locations for one immutable run directory."""

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
