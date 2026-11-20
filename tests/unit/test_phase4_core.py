from __future__ import annotations

import json
import os
import pytest
import shutil
import subprocess
import sys
from pathlib import Path

from pdffast.audit.structure_boundary import audit
from pdffast.canonical.builder import build_document
from pdffast.render.llm_ready import build_rendered_document, validate_canonical
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10


# Historical Stage 6-10 artifacts are external test inputs and are not part of
# the Git repository. No absolute paths to an old development workspace.
# When available, set PDFFAST_PHASE4_RUN_DIR to the archived run directory.
# Only the runner integration test also requires PDFFAST_PHASE4_SOURCE_PDF.
REFERENCE_FILES = (
    "06_stage6/normalized_text_flow.json",
    "08_stage8/quality_gate.json",
    "09_2_provider_plan/provider_plan.json",
    "09_8_production_fallback/selected_prediction_index.json",
    "10_1_canonical/canonical_document.json",
    "10_2_llm_ready/llm_ready.md",
    "10_2_llm_ready/render_manifest.json",
)


@pytest.fixture(scope="module")
def reference_run() -> Path:
    value = os.environ.get("PDFFAST_PHASE4_RUN_DIR")
    if not value:
        pytest.skip(
            "External Phase 4 reference artifacts are not provided; "
            "set PDFFAST_PHASE4_RUN_DIR to run historical parity tests"
        )
    path = Path(value).expanduser().resolve()
    required = [path / name for name in REFERENCE_FILES]
    required.append(path / "09_8_production_fallback/selected_predictions")
    missing = [str(file) for file in required if not file.exists()]
    if missing:
        pytest.fail("PDFFAST_PHASE4_RUN_DIR points to incomplete reference artifacts: "
                    + ", ".join(missing))
    return path


@pytest.fixture
def reference_pdf() -> Path:
    value = os.environ.get("PDFFAST_PHASE4_SOURCE_PDF")
    if not value:
        pytest.skip(
            "Runner parity needs an external reference PDF; "
            "set PDFFAST_PHASE4_SOURCE_PDF"
        )
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        pytest.fail(f"PDFFAST_PHASE4_SOURCE_PDF does not exist: {path}")
    return path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in {"path", "source_file", "sha256", "canonical_sha256", "manifest_path", "selected_prediction_file"}}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def test_canonical_builder_matches_reference_artifact_shape(reference_run: Path) -> None:
    doc = build_document(
        reference_run / "06_stage6/normalized_text_flow.json",
        reference_run / "08_stage8/quality_gate.json",
        reference_run / "09_2_provider_plan/provider_plan.json",
        reference_run / "09_8_production_fallback/selected_prediction_index.json",
        reference_run / "09_8_production_fallback/selected_predictions",
    )
    expected = load(reference_run / "10_1_canonical/canonical_document.json")
    for key in ("records", "sections", "fallback_overlays", "summary", "status", "stage", "substage"):
        assert semantic(doc[key]) == semantic(expected[key]), key
    assert expected["schema_version"] == "1.0"
    assert doc["schema_version"] == "1.1"
    assert doc["document_units"] == []


def test_renderer_is_pure_and_matches_reference_markdown(reference_run: Path) -> None:
    doc = load(reference_run / "10_1_canonical/canonical_document.json")
    validate_canonical(doc)
    markdown, manifest = build_rendered_document(doc)
    expected = (reference_run / "10_2_llm_ready/llm_ready.md").read_text(encoding="utf-8")
    assert markdown == expected
    assert manifest["validation"]["pass"] is True


def test_renderer_does_not_invent_heading_for_unresolved_section(reference_run: Path) -> None:
    doc = load(reference_run / "10_1_canonical/canonical_document.json")
    doc["sections"][0]["section_title"] = None
    doc["sections"][0]["section_id"] = None
    markdown, _ = build_rendered_document(doc)
    assert not markdown.startswith("# 未命名章节")
    assert not markdown.startswith("# None")


def test_structure_audit_passes_on_reference_artifacts(reference_run: Path) -> None:
    result = audit(
        load(reference_run / "06_stage6/normalized_text_flow.json"),
        load(reference_run / "08_stage8/quality_gate.json"),
        load(reference_run / "10_1_canonical/canonical_document.json"),
        load(reference_run / "10_2_llm_ready/render_manifest.json"),
    )
    assert result["validation"]["pass"] is True


def test_stage10_core_works_when_installed_outside_legacy_workspace(
    tmp_path: Path,
    monkeypatch,
    reference_run: Path,
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
        reference_run / "06_stage6/normalized_text_flow.json",
        reference_run / "08_stage8/quality_gate.json",
        reference_run / "09_2_provider_plan/provider_plan.json",
        reference_run / "09_8_production_fallback/selected_prediction_index.json",
        reference_run / "09_8_production_fallback/selected_predictions",
    )

    assert document["status"] == "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING"
    assert document["summary"]["native_record_count"] > 0


def test_stage10_runner_writes_only_declared_artifacts(
    tmp_path: Path,
    reference_run: Path,
    reference_pdf: Path,
) -> None:
    context = PipelineContext.create(
        project_root=Path(__file__).resolve().parents[2],
        pdf=reference_pdf,
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
        "normalized_flow": reference_run / "06_stage6/normalized_text_flow.json",
        "quality_gate": reference_run / "08_stage8/quality_gate.json",
        "provider_plan": reference_run / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": reference_run / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": reference_run / "09_8_production_fallback/selected_predictions",
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
