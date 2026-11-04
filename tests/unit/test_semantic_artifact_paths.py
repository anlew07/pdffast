"""Semantic path names retain the public result path contract."""

from dataclasses import fields
from pathlib import Path

from pdffast.pipeline.artifacts import ArtifactPaths


def test_semantic_paths_resolve_to_v3_layout(tmp_path: Path) -> None:
    run_dir = tmp_path / "one-run"
    paths = ArtifactPaths.for_run(run_dir)
    expected = {
        "result.document_json": ("result_document", "result/document.json"),
        "result.document_md": ("result_markdown", "result/document.md"),
        "result.audit_json": ("result_audit", "result/audit.json"),
        "result.manifest_json": ("result_manifest", "result/manifest.json"),
        "result.canonical_snapshot": ("canonical_document", "canonical/canonical_document.json"),
        "result.rendered_snapshot": ("llm_ready", "render/llm_ready.md"),
        "native.profile": ("profile", "native/profile/page_profile.json"),
        "native.snapshot": ("snapshot", "native/profile/page_snapshot.jsonl"),
        "native.sections": ("section_alignment", "native/sections/section_alignment.json"),
        "native.page_structure": ("page_structure", "native/structure/page_structure.json"),
        "native.tables": ("table_result", "native/tables/result.json"),
        "native.text_flow": ("normalized_flow", "native/text_flow/normalized_text_flow.json"),
        "observability.evidence": ("evidence_manifest", "quality/evidence/evidence_manifest.json"),
        "observability.quality": ("quality_gate", "quality/gate/quality_gate.json"),
        "observability.fallback_plan": ("fallback_manifest", "fallback/planning/fallback_execution_manifest.json"),
        "observability.capability_plan": ("provider_plan", "fallback/routing/provider_plan.json"),
        "observability.execution_plan": ("runtime_policy", "fallback/policy/runtime_escalation_policy.json"),
        "observability.production_manifest": ("production_manifest", "providers/execution/production_execution_manifest.json"),
        "observability.render_manifest": ("render_manifest", "render/render_manifest.json"),
        "observability.structure_audit": ("structure_audit", "audit/structure_boundary_audit.json"),
        "providers.selected_index": ("selected_prediction_index", "providers/execution/selected_prediction_index.json"),
        "providers.selected_dir": ("selected_predictions_dir", "providers/execution/selected_predictions"),
        "providers.production_manifest": ("production_manifest", "providers/execution/production_execution_manifest.json"),
        "diagnostics.pipeline_log": ("pipeline_log", "diagnostics/logs/pipeline.log"),
    }
    for semantic, (flat_name, relative) in expected.items():
        group, name = semantic.split(".")
        new = getattr(getattr(paths, group), name)
        assert new == run_dir / relative, semantic
        assert new == getattr(paths, flat_name), semantic


def test_provider_dynamic_paths_keep_one_physical_artifact(tmp_path: Path) -> None:
    paths = ArtifactPaths.for_run(tmp_path / "one-run")
    execution = tmp_path / "one-run/providers/execution"
    assert paths.providers.execution_dir == execution
    assert paths.providers.raw_dir == execution / "provider_raw"
    assert paths.providers.raw_manifest == execution / "provider_raw/runtime_manifest.json"
    assert paths.providers.raw_result("task_001") == execution / "provider_raw/task_001.json"
    selected = execution / "selected_predictions/task_001.json"
    assert paths.providers.selected_prediction("task_001") == selected
    # Normalized attempts live inside the selected wrapper, not in a second file.
    assert paths.providers.normalized_prediction("task_001") == selected


def test_semantic_groups_do_not_change_full_mode_public_artifact_keys(tmp_path: Path) -> None:
    paths = ArtifactPaths.for_run(tmp_path / "one-run")
    before = {field.name for field in fields(ArtifactPaths)}
    _ = paths.result, paths.native, paths.observability, paths.diagnostics, paths.providers
    assert set(paths.as_dict()) == before
    assert "result" not in paths.as_dict()
    assert "providers" not in paths.as_dict()
