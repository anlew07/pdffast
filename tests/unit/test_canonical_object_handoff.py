from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.fallback.router import CapabilityPlan
from pdffast.native.text_flow import TextFlowResult
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10
from pdffast.quality.gate import QualityReport


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="object-handoff",
        case_id="synthetic",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
    )


def _write_inputs(context: PipelineContext, inputs: dict) -> list[Path]:
    artifacts = context.artifacts
    values = (
        (artifacts.native.text_flow, inputs["native_flow"], False),
        (artifacts.observability.quality, inputs["quality_gate"], False),
        (artifacts.observability.capability_plan, inputs["capability_plan"], False),
        (artifacts.providers.selected_index, inputs["selected_index"], True),
    )
    for path, value, trailing_newline in values:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(value, ensure_ascii=False, indent=2)
        path.write_text(encoded + ("\n" if trailing_newline else ""), encoding="utf-8")

    for wrapper in inputs["selected_predictions"]:
        path = artifacts.providers.selected_prediction(wrapper["task_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")

    return [
        artifacts.providers.selected_index,
        *(artifacts.providers.selected_prediction(x["task_id"]) for x in inputs["selected_predictions"]),
    ]


def _selection(inputs: dict) -> ProviderExecutionResult:
    return ProviderExecutionResult(
        manifest={"status": "COMPLETED"},
        selected_index=inputs["selected_index"],
        selected_predictions=inputs["selected_predictions"],
    )


def _object_inputs(inputs: dict):
    return {
        "selection": _selection(inputs),
        "text_flow": TextFlowResult({}, {}, {}, {}, inputs["native_flow"]),
        "quality_report": QualityReport(inputs["quality_gate"]),
        "capability_plan": CapabilityPlan(inputs["capability_plan"]),
    }


def test_selected_predictions_use_in_memory_objects_without_reloading_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, v3_pipeline_inputs: dict,
) -> None:
    context = _context(tmp_path)
    selected_paths = _write_inputs(context, v3_pipeline_inputs)
    file_result = run_stage10(context)
    outputs = (
        context.artifacts.result.canonical_snapshot,
        context.artifacts.result.rendered_snapshot,
        context.artifacts.observability.render_manifest,
        context.artifacts.observability.structure_audit,
        context.artifacts.result.document_json,
        context.artifacts.result.document_md,
        context.artifacts.result.audit_json,
        context.artifacts.result.manifest_json,
    )
    file_bytes = tuple(path.read_bytes() for path in outputs)
    before_selection = copy.deepcopy((
        v3_pipeline_inputs["selected_index"],
        v3_pipeline_inputs["selected_predictions"],
    ))

    original_read_text = Path.read_text
    original_open = Path.open
    forbidden = {path.resolve() for path in selected_paths}

    def guard_read_text(path: Path, *args, **kwargs):
        if path.resolve() in forbidden:
            raise AssertionError(f"canonical path reloaded selected artifact: {path}")
        return original_read_text(path, *args, **kwargs)

    def guard_open(path: Path, mode="r", *args, **kwargs):
        if path.resolve() in forbidden and "r" in mode:
            raise AssertionError(f"canonical path reopened selected artifact: {path}")
        return original_open(path, mode, *args, **kwargs)

    object_args = _object_inputs(v3_pipeline_inputs)
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_text", guard_read_text)
        patcher.setattr(Path, "open", guard_open)
        object_result = run_stage10(context, **object_args)

    assert tuple(path.read_bytes() for path in outputs) == file_bytes
    assert object_result["canonical"] == file_result["canonical"]
    assert object_result["markdown"] == file_result["markdown"]
    assert object_result["structure_audit"] == file_result["structure_audit"]
    assert (
        v3_pipeline_inputs["selected_index"],
        v3_pipeline_inputs["selected_predictions"],
    ) == before_selection
    assert object_result["canonical"]["summary"]["terminal_preserve_count"] == 1
    assert object_result["structure_audit"]["validation"]["pass"] is True


def test_in_memory_selection_rejects_missing_task_result(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    context = _context(tmp_path)
    inputs = _object_inputs(v3_pipeline_inputs)
    missing = ProviderExecutionResult(
        manifest={"status": "COMPLETED"},
        selected_index=inputs["selection"].selected_index,
        selected_predictions=[],
    )

    with pytest.raises(ValueError, match="task ids"):
        run_stage10(
            context,
            selection=missing,
            text_flow=inputs["text_flow"],
            quality_report=inputs["quality_report"],
            capability_plan=inputs["capability_plan"],
        )


def test_production_runner_passes_execution_selection_to_canonical_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdffast.errors import ParseExecutionError
    from pdffast.pipeline import runner

    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="selection-wiring",
        case_id="input",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
    )
    selection = ProviderExecutionResult({"status": "COMPLETED"}, {"items": []}, [])
    monkeypatch.setattr(runner, "run_profiler", lambda **kwargs: {})
    monkeypatch.setattr(runner, "run_section_discovery", lambda **kwargs: {})
    monkeypatch.setattr(runner, "run_page_structure", lambda **kwargs: {})
    monkeypatch.setattr(runner, "run_table_recovery", lambda **kwargs: {})
    monkeypatch.setattr(runner, "create_text_flow_result", lambda **kwargs: object())
    monkeypatch.setattr(runner, "write_text_flow_result", lambda *args: None)
    monkeypatch.setattr(runner, "create_evidence_report", lambda **kwargs: object())
    monkeypatch.setattr(runner, "write_evidence_report", lambda *args: None)
    monkeypatch.setattr(runner, "evaluate_evidence_report", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner, "write_quality_report", lambda *args: None)
    monkeypatch.setattr(runner, "create_fallback_plan", lambda **kwargs: object())
    monkeypatch.setattr(runner, "write_fallback_plan", lambda *args: None)
    monkeypatch.setattr(runner, "create_capability_plan", lambda **kwargs: object())
    monkeypatch.setattr(runner, "write_capability_plan", lambda *args: None)
    monkeypatch.setattr(runner, "create_provider_execution_plan", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner, "write_provider_execution_plan", lambda *args: None)
    monkeypatch.setattr(runner, "execute_provider_plan", lambda **kwargs: selection)

    def capture_canonical_boundary(
        actual_context, *, selection, section_alignment, text_flow, quality_report, capability_plan,
    ):
        assert actual_context is context
        assert selection is expected
        assert section_alignment == {}
        raise RuntimeError("selection reached canonical boundary")

    expected = selection
    monkeypatch.setattr(runner, "run_stage10", capture_canonical_boundary)
    with pytest.raises(ParseExecutionError, match="selection reached canonical boundary"):
        runner.run_core_pipeline(
            context,
            provider_configs={},
            registry=object(),
            normalizer=lambda *args: {},
            execute_providers=True,
        )
