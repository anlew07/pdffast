import dataclasses
from pathlib import Path

import pytest


def _artifact_paths_type():
    try:
        from pdffast.pipeline.artifacts import ArtifactPaths
    except ModuleNotFoundError as exc:
        pytest.fail(f"ArtifactPaths is not implemented: {exc}")
    return ArtifactPaths


def test_artifact_paths_match_reference_layout(tmp_path: Path) -> None:
    """Catches path drift that would make old/new artifacts incomparable."""
    ArtifactPaths = _artifact_paths_type()
    run_dir = tmp_path / "outputs" / "case_007_20260920_120000"
    paths = ArtifactPaths.for_run(run_dir)

    expected = {
        "profile": run_dir / "01_stage1/page_profile.json",
        "snapshot": run_dir / "01_stage1/page_snapshot.jsonl",
        "section_alignment": run_dir / "03_stage3/section_alignment.json",
        "page_structure": run_dir / "04_stage4/page_structure.json",
        "table_result": run_dir / "05_stage5/result.json",
        "normalized_flow": run_dir / "06_stage6/normalized_text_flow.json",
        "evidence_manifest": run_dir / "07_stage7/evidence_manifest.json",
        "quality_gate": run_dir / "08_stage8/quality_gate.json",
        "fallback_manifest": run_dir / "09_1_fallback_units/fallback_execution_manifest.json",
        "provider_plan": run_dir / "09_2_provider_plan/provider_plan.json",
        "runtime_policy": run_dir / "09_6_3_runtime_policy/runtime_escalation_policy.json",
        "production_manifest": run_dir / "09_8_production_fallback/production_execution_manifest.json",
        "selected_prediction_index": run_dir / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": run_dir / "09_8_production_fallback/selected_predictions",
        "canonical_document": run_dir / "10_1_canonical/canonical_document.json",
        "render_manifest": run_dir / "10_2_llm_ready/render_manifest.json",
        "llm_ready": run_dir / "10_2_llm_ready/llm_ready.md",
        "structure_audit": run_dir / "10_2_1_structure_audit/structure_boundary_audit.json",
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
