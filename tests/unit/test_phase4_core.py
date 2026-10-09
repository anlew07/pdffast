from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from pdffast.audit.structure_boundary import audit
from pdffast.canonical.builder import build_document
from pdffast.render.llm_ready import build_rendered_document, validate_canonical
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10


REFERENCE = Path("/Users/admin/Workspace/pdffast")
RUN = REFERENCE / "outputs/pipeline_runs/case_008_final_bench_v1"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in {"path", "source_file", "sha256", "canonical_sha256", "manifest_path", "selected_prediction_file"}}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def test_canonical_builder_matches_reference_artifact_shape() -> None:
    doc = build_document(
        RUN / "06_stage6/normalized_text_flow.json",
        RUN / "08_stage8/quality_gate.json",
        RUN / "09_2_provider_plan/provider_plan.json",
        RUN / "09_8_production_fallback/selected_prediction_index.json",
        RUN / "09_8_production_fallback/selected_predictions",
    )
    expected = load(RUN / "10_1_canonical/canonical_document.json")
    for key in ("records", "sections", "fallback_overlays", "summary", "status", "stage", "substage"):
        assert semantic(doc[key]) == semantic(expected[key]), key
    assert expected["schema_version"] == "1.0"
    assert doc["schema_version"] == "1.1"
    assert doc["document_units"] == []


def test_renderer_is_pure_and_matches_reference_markdown() -> None:
    doc = load(RUN / "10_1_canonical/canonical_document.json")
    validate_canonical(doc)
    markdown, manifest = build_rendered_document(doc)
    expected = (RUN / "10_2_llm_ready/llm_ready.md").read_text(encoding="utf-8")
    assert markdown == expected
    assert manifest["validation"]["pass"] is True


def test_renderer_does_not_invent_heading_for_unresolved_section() -> None:
    doc = load(RUN / "10_1_canonical/canonical_document.json")
    doc["sections"][0]["section_title"] = None
    doc["sections"][0]["section_id"] = None
    markdown, _ = build_rendered_document(doc)
    assert not markdown.startswith("# 未命名章节")
    assert not markdown.startswith("# None")


def test_structure_audit_passes_on_reference_artifacts() -> None:
    result = audit(
        load(RUN / "06_stage6/normalized_text_flow.json"),
        load(RUN / "08_stage8/quality_gate.json"),
        load(RUN / "10_1_canonical/canonical_document.json"),
        load(RUN / "10_2_llm_ready/render_manifest.json"),
    )
    assert result["validation"]["pass"] is True


def test_stage10_core_works_when_installed_outside_legacy_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Catches Stage 10 silently loading its implementation from the legacy repo."""
    from pdffast.canonical import builder

    isolated_package_file = tmp_path / "site-packages/pdffast/canonical/builder.py"
    isolated_package_file.parent.mkdir(parents=True)
    isolated_package_file.touch()
    shutil.copyfile(
        Path(builder.__file__).with_name("_stage10_builder.py"),
        isolated_package_file.with_name("_stage10_builder.py"),
    )
    monkeypatch.setattr(builder, "__file__", str(isolated_package_file))

    document = builder.build_document(
        RUN / "06_stage6/normalized_text_flow.json",
        RUN / "08_stage8/quality_gate.json",
        RUN / "09_2_provider_plan/provider_plan.json",
        RUN / "09_8_production_fallback/selected_prediction_index.json",
        RUN / "09_8_production_fallback/selected_predictions",
    )

    assert document["status"] == "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING"
    assert document["summary"]["native_record_count"] > 0


def test_stage10_runner_writes_only_declared_artifacts(tmp_path: Path) -> None:
    context = PipelineContext.create(
        project_root=REFERENCE,
        pdf=REFERENCE / "benchmark/samples/real/case_002.pdf",
        output_root=tmp_path,
        run_id="phase4-test",
        case_id="case008",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
    )
    # Point only at existing reference stage 1-9 artifacts; no provider is initialized.
    import dataclasses
    a = context.artifacts
    mapping = {
        "normalized_flow": RUN / "06_stage6/normalized_text_flow.json",
        "quality_gate": RUN / "08_stage8/quality_gate.json",
        "provider_plan": RUN / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": RUN / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": RUN / "09_8_production_fallback/selected_predictions",
    }
    context = dataclasses.replace(context, artifacts=dataclasses.replace(a, **mapping))
    result = run_stage10(context)
    assert result["structure_audit"]["validation"]["pass"] is True
    assert context.artifacts.llm_ready.is_file()
    public_manifest = load(context.artifacts.result_manifest)
    assert "diagnostics" not in public_manifest


def test_cli_requires_explicit_artifact_mode() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_pipeline.py", "sample.pdf"],
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 2
    assert "--from-artifacts" in result.stderr
