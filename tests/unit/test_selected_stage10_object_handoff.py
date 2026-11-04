"""The fresh Stage 10 path shares the execution selection without reloading it."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_stage10


ROOT = Path(__file__).resolve().parents[2]


def _inputs(case: int):
    root = ROOT / f"outputs/final_structure_regression/case_{case:03d}"
    files = {
        "section_alignment": root / "03_stage3/section_alignment.json",
        "normalized_flow": root / "06_stage6/normalized_text_flow.json",
        "quality_gate": root / "08_stage8/quality_gate.json",
        "provider_plan": root / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": root / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": root / "09_8_production_fallback/selected_predictions",
    }
    if not all(path.exists() for path in files.values()):
        pytest.skip(f"case_{case:03d} existing execution artifacts unavailable")
    index = json.loads(files["selected_prediction_index"].read_text(encoding="utf-8"))
    wrappers = [
        json.loads((files["selected_predictions_dir"] / f"{item['task_id']}.json").read_text(encoding="utf-8"))
        for item in index["items"]
    ]
    return files, ProviderExecutionResult({}, index, wrappers)


@pytest.mark.parametrize("case", [2, 3, 4])
def test_selected_predictions_pass_directly_to_stage10_with_file_parity(
    case: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    files, selection = _inputs(case)
    before_selection = copy.deepcopy((selection.selected_index, selection.selected_predictions))
    selected_paths = [files["selected_prediction_index"], *(
        files["selected_predictions_dir"] / f"{item['task_id']}.json"
        for item in selection.selected_index["items"]
    )]
    before_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in selected_paths}
    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / f"case_{case:03d}.pdf",
        output_root=tmp_path, run_id="stage10-parity", case_id=f"case_{case:03d}",
        page_dpi=200, region_dpi=300, rapidocr_workers=1, table_mode="auto",
    )
    context = replace(context, artifacts=replace(context.artifacts, **files))
    file_result = run_stage10(context)
    outputs = (context.artifacts.result_document, context.artifacts.result_markdown,
               context.artifacts.render_manifest, context.artifacts.result_audit)
    file_bytes = tuple(path.read_bytes() for path in outputs)

    original_read_text = Path.read_text
    original_open = Path.open
    forbidden = {path.resolve() for path in selected_paths}

    def guard_read_text(path: Path, *args, **kwargs):
        if path.resolve() in forbidden:
            raise AssertionError(f"fresh Stage 10 reloaded selected artifact: {path}")
        return original_read_text(path, *args, **kwargs)

    def guard_open(path: Path, mode="r", *args, **kwargs):
        if path.resolve() in forbidden and "r" in mode:
            raise AssertionError(f"fresh Stage 10 reopened selected artifact: {path}")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_text", guard_read_text)
        patcher.setattr(Path, "open", guard_open)
        object_result = run_stage10(context, selection=selection)

    assert tuple(path.read_bytes() for path in outputs) == file_bytes
    assert object_result["canonical"] == file_result["canonical"]
    assert object_result["markdown"] == file_result["markdown"]
    assert object_result["structure_audit"] == file_result["structure_audit"]
    assert (selection.selected_index, selection.selected_predictions) == before_selection
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in selected_paths} == before_hashes
    if case == 3:
        assert [unit["anchor"]["page"] for unit in object_result["canonical"]["document_units"]] == [27, 29, 30, 36, 66]


def test_object_path_preserves_task_closure_and_terminal_unresolved(tmp_path: Path) -> None:
    files, selection = _inputs(3)
    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / "case_003.pdf", output_root=tmp_path,
        run_id="stage10-closure", case_id="case_003", page_dpi=200,
        region_dpi=300, rapidocr_workers=1, table_mode="auto",
    )
    context = replace(context, artifacts=replace(context.artifacts, **files))
    result = run_stage10(context, selection=selection)
    assert result["canonical"]["summary"]["terminal_preserve_count"] == 2
    assert result["canonical"]["summary"]["fallback_task_count"] == 54

    missing = ProviderExecutionResult({}, selection.selected_index, selection.selected_predictions[:-1])
    with pytest.raises((ValueError, FileNotFoundError), match="task|prediction|selected"):
        run_stage10(context, selection=missing)


def test_production_runner_passes_execution_selection_to_stage10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pdffast.pipeline import runner
    from pdffast.errors import ParseExecutionError

    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / "input.pdf", output_root=tmp_path,
        run_id="selection-wiring", case_id="input", page_dpi=200,
        region_dpi=300, rapidocr_workers=1, table_mode="auto", capture_output=False,
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
    monkeypatch.setattr(runner, "create_provider_execution_plan", lambda *args: object())
    monkeypatch.setattr(runner, "write_provider_execution_plan", lambda *args: None)
    monkeypatch.setattr(runner, "execute_provider_plan", lambda **kwargs: selection)

    def capture_stage10(actual_context, *, selection, section_alignment, text_flow, quality_report, capability_plan):
        assert actual_context is context
        assert selection is expected
        assert section_alignment == {}
        raise RuntimeError("selection reached Stage 10")

    expected = selection
    monkeypatch.setattr(runner, "run_stage10", capture_stage10)
    with pytest.raises(ParseExecutionError, match="selection reached Stage 10"):
        runner.run_core_pipeline(
            context, provider_configs={}, registry=object(),
            normalizer=lambda *args: {}, execute_providers=True,
        )
