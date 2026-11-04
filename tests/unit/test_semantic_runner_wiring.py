"""Top-level orchestration can use semantic artifact groups exclusively."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from pdffast.errors import ParseExecutionError
from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.fallback.router import CapabilityPlan
from pdffast.native.text_flow import TextFlowResult
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext
from pdffast.quality.gate import QualityReport


ROOT = Path(__file__).resolve().parents[2]


class SemanticOnlyPaths:
    """Disallow flat path aliases while preserving the real group properties."""

    def __init__(self, paths):
        self.paths = paths

    def __getattr__(self, name: str):
        if name in {"result", "native", "observability", "providers", "diagnostics"}:
            return getattr(self.paths, name)
        raise AssertionError(f"runner used a flat artifact alias: {name}")


def test_pipeline_entry_uses_semantic_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / "input.pdf", output_root=tmp_path,
        run_id="semantic-entry", case_id="input", page_dpi=200, region_dpi=300,
        rapidocr_workers=1, table_mode="auto", capture_output=False,
    )
    context = replace(context, artifacts=SemanticOnlyPaths(context.artifacts))
    seen = {}

    def stop_after_profiler(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after profiler wiring")

    monkeypatch.setattr(runner, "run_profiler", stop_after_profiler)
    with pytest.raises(ParseExecutionError, match="stop after profiler wiring"):
        runner.run_core_pipeline(context)
    assert seen["profile_output"] == tmp_path / "semantic-entry/01_stage1/page_profile.json"
    assert seen["snapshot_output"] == tmp_path / "semantic-entry/01_stage1/page_snapshot.jsonl"


def test_stage10_uses_semantic_paths_for_real_case_002_objects(tmp_path: Path) -> None:
    source = ROOT / "outputs/final_structure_regression/case_002"
    files = {
        "section_alignment": source / "03_stage3/section_alignment.json",
        "normalized_flow": source / "06_stage6/normalized_text_flow.json",
        "quality_gate": source / "08_stage8/quality_gate.json",
        "provider_plan": source / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": source / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": source / "09_8_production_fallback/selected_predictions",
    }
    if not all(path.exists() for path in files.values()):
        pytest.skip("case_002 existing execution artifacts unavailable")
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    index = read(files["selected_prediction_index"])
    wrappers = [read(files["selected_predictions_dir"] / f"{item['task_id']}.json") for item in index["items"]]
    flow = TextFlowResult({}, {}, {}, {}, read(files["normalized_flow"]))
    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / "case_002.pdf", output_root=tmp_path,
        run_id="semantic-stage10", case_id="case_002", page_dpi=200, region_dpi=300,
        rapidocr_workers=1, table_mode="auto", capture_output=False,
    )
    context = replace(context, artifacts=SemanticOnlyPaths(replace(context.artifacts, **files)))
    result = runner.run_stage10(
        context,
        selection=ProviderExecutionResult({}, index, wrappers),
        section_alignment=read(files["section_alignment"]),
        text_flow=flow,
        quality_report=QualityReport(read(files["quality_gate"])),
        capability_plan=CapabilityPlan(read(files["provider_plan"])),
    )
    assert result["canonical"] == read(tmp_path / "semantic-stage10/result/document.json")
    assert result["markdown"] == (tmp_path / "semantic-stage10/result/document.md").read_text(encoding="utf-8")
    assert result["structure_audit"] == read(tmp_path / "semantic-stage10/result/audit.json")
