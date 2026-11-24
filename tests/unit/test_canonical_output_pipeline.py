from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from pdffast.audit.structure_boundary import audit
from pdffast.canonical.builder import build_document
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10
from pdffast.render.llm_ready import build_rendered_document, validate_canonical
from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.fallback.router import CapabilityPlan
from pdffast.native.text_flow import TextFlowResult
from pdffast.quality.gate import QualityReport


def _build_canonical(inputs: dict, root: Path) -> dict:
    return build_document(
        root / "native-flow.json",
        root / "quality-gate.json",
        root / "capability-plan.json",
        root / "selected-index.json",
        root / "selected-predictions",
        selected_index_data=inputs["selected_index"],
        selected_predictions=inputs["selected_predictions"],
        native_flow_data=inputs["native_flow"],
        quality_data=inputs["quality_gate"],
        plan_data=inputs["capability_plan"],
    )


def _objects(inputs: dict):
    selection = ProviderExecutionResult(
        manifest={"status": "COMPLETED"},
        selected_index=inputs["selected_index"],
        selected_predictions=inputs["selected_predictions"],
    )
    text_flow = TextFlowResult({}, {}, {}, {}, inputs["native_flow"])
    quality = QualityReport(inputs["quality_gate"])
    capability = CapabilityPlan(inputs["capability_plan"])
    return selection, text_flow, quality, capability


def test_canonical_builder_consumes_v3_in_memory_inputs(tmp_path: Path, v3_pipeline_inputs: dict) -> None:
    document = _build_canonical(v3_pipeline_inputs, tmp_path)

    assert document["status"] == "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING"
    assert document["schema_version"] == "1.1"
    assert document["summary"]["native_record_count"] == 2
    assert document["summary"]["fallback_task_count"] == 1
    assert document["summary"]["terminal_preserve_count"] == 1
    assert document["records"][1]["stage10_resolution"]["mode"] == "REGION_PRESERVED_UNRESOLVED"
    assert document["document_units"] == []


def test_renderer_is_pure_and_accepts_v3_canonical_output(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    document = _build_canonical(v3_pipeline_inputs, tmp_path)
    before = deepcopy(document)

    validate_canonical(document)
    markdown, manifest = build_rendered_document(document)

    assert document == before
    assert manifest["validation"]["pass"] is True
    assert "V3 原生正文" in markdown


def test_renderer_does_not_invent_a_heading_for_unresolved_section(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    document = _build_canonical(v3_pipeline_inputs, tmp_path)
    document["sections"][0]["section_title"] = None
    markdown, _ = build_rendered_document(document)

    assert "# None" not in markdown
    assert "# 未命名章节" not in markdown


def test_structure_audit_accepts_v3_object_inputs(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    inputs = v3_pipeline_inputs
    document = _build_canonical(inputs, tmp_path)
    markdown, manifest = build_rendered_document(document)

    result = audit(
        inputs["native_flow"],
        inputs["quality_gate"],
        document,
        manifest,
        markdown=markdown,
    )

    assert result["validation"]["pass"] is True


def test_canonical_builder_loads_implementation_relative_to_installed_package(
    tmp_path: Path, monkeypatch, v3_pipeline_inputs: dict,
) -> None:
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
        tmp_path / "native-flow.json",
        tmp_path / "quality-gate.json",
        tmp_path / "capability-plan.json",
        tmp_path / "selected-index.json",
        tmp_path / "selected-predictions",
        selected_index_data=v3_pipeline_inputs["selected_index"],
        selected_predictions=v3_pipeline_inputs["selected_predictions"],
        native_flow_data=v3_pipeline_inputs["native_flow"],
        quality_data=v3_pipeline_inputs["quality_gate"],
        plan_data=v3_pipeline_inputs["capability_plan"],
    )

    assert document["status"] == "CANONICAL_DOCUMENT_READY_FOR_LLM_RENDERING"
    assert document["summary"]["native_record_count"] == 2


def test_v3_runner_writes_only_declared_outputs(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="v3-output-contract",
        case_id="synthetic",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
    )
    selection, text_flow, quality, capability = _objects(v3_pipeline_inputs)
    result = run_stage10(
        context,
        selection=selection,
        text_flow=text_flow,
        quality_report=quality,
        capability_plan=capability,
    )

    expected = {
        context.artifacts.result.canonical_snapshot,
        context.artifacts.result.rendered_snapshot,
        context.artifacts.observability.render_manifest,
        context.artifacts.observability.structure_audit,
        context.artifacts.result.document_json,
        context.artifacts.result.document_md,
        context.artifacts.result.audit_json,
        context.artifacts.result.manifest_json,
    }
    actual = {path for path in context.run_dir.rglob("*") if path.is_file()}
    assert actual == expected
    assert "diagnostics" not in json.loads(context.artifacts.result.manifest_json.read_text(encoding="utf-8"))
    assert result["structure_audit"]["validation"]["pass"] is True


def test_cli_missing_pdf_does_not_advertise_unimplemented_artifact_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/run_pipeline.py", "missing-input.pdf"],
        text=True,
        capture_output=True,
        cwd=root,
        check=False,
    )

    assert result.returncode == 2
    assert "PDF 不存在" in result.stderr
    assert "--from-artifacts" not in result.stderr
