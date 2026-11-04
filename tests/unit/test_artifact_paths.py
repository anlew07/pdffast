import dataclasses
from pathlib import Path

import pytest


def _artifact_paths_type():
    try:
        from pdffast.pipeline.artifacts import ArtifactPaths
    except ModuleNotFoundError as exc:
        pytest.fail(f"ArtifactPaths is not implemented: {exc}")
    return ArtifactPaths


def test_artifact_paths_match_v3_semantic_layout(tmp_path: Path) -> None:
    """Guards the V3 semantic run layout, independently of legacy snapshots."""
    ArtifactPaths = _artifact_paths_type()
    run_dir = tmp_path / "outputs" / "case_007_20260920_120000"
    paths = ArtifactPaths.for_run(run_dir)

    expected = {
        "profile": run_dir / "native/profile/page_profile.json",
        "snapshot": run_dir / "native/profile/page_snapshot.jsonl",
        "section_alignment": run_dir / "native/sections/section_alignment.json",
        "page_structure": run_dir / "native/structure/page_structure.json",
        "table_result": run_dir / "native/tables/result.json",
        "normalized_flow": run_dir / "native/text_flow/normalized_text_flow.json",
        "evidence_manifest": run_dir / "quality/evidence/evidence_manifest.json",
        "quality_gate": run_dir / "quality/gate/quality_gate.json",
        "fallback_manifest": run_dir / "fallback/planning/fallback_execution_manifest.json",
        "provider_plan": run_dir / "fallback/routing/provider_plan.json",
        "runtime_policy": run_dir / "fallback/policy/runtime_escalation_policy.json",
        "production_manifest": run_dir / "providers/execution/production_execution_manifest.json",
        "selected_prediction_index": run_dir / "providers/execution/selected_prediction_index.json",
        "selected_predictions_dir": run_dir / "providers/execution/selected_predictions",
        "canonical_document": run_dir / "canonical/canonical_document.json",
        "render_manifest": run_dir / "render/render_manifest.json",
        "llm_ready": run_dir / "render/llm_ready.md",
        "structure_audit": run_dir / "audit/structure_boundary_audit.json",
        "logs_dir": run_dir / "logs",
    }
    assert paths.as_dict() == expected


def test_artifact_paths_are_frozen(tmp_path: Path) -> None:
    """Catches accidental path mutation after a run starts."""
    ArtifactPaths = _artifact_paths_type()
    paths = ArtifactPaths.for_run(tmp_path / "run")
    with pytest.raises(dataclasses.FrozenInstanceError):
        paths.profile = tmp_path / "other.json"


def test_filesystem_root_is_rejected() -> None:
    """Catches broad output targets that could overwrite system paths."""
    ArtifactPaths = _artifact_paths_type()
    with pytest.raises(ValueError, match="run_dir"):
        ArtifactPaths.for_run(Path("/"))
