"""The V3 runner uses semantic artifact groups and in-memory handoff objects."""

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


class SemanticOnlyPaths:
    """Reject flat path aliases while exposing V3 semantic artifact groups."""

    def __init__(self, paths):
        self.paths = paths

    def __getattr__(self, name: str):
        if name in {"result", "native", "observability", "providers", "diagnostics"}:
            return getattr(self.paths, name)
        raise AssertionError(f"runner used a flat artifact alias: {name}")


def test_pipeline_entry_uses_semantic_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path,
        run_id="semantic-entry",
        case_id="input",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
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


def test_canonical_boundary_uses_semantic_paths_with_v3_objects(
    tmp_path: Path, v3_pipeline_inputs: dict,
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path,
        run_id="semantic-canonical",
        case_id="synthetic",
        page_dpi=200,
        region_dpi=300,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
    )
    paths = context.artifacts
    context = replace(context, artifacts=SemanticOnlyPaths(paths))
    inputs = v3_pipeline_inputs
    selection = ProviderExecutionResult(
        {"status": "COMPLETED"}, inputs["selected_index"], inputs["selected_predictions"],
    )
    result = runner.run_stage10(
        context,
        selection=selection,
        text_flow=TextFlowResult({}, {}, {}, {}, inputs["native_flow"]),
        quality_report=QualityReport(inputs["quality_gate"]),
        capability_plan=CapabilityPlan(inputs["capability_plan"]),
    )

    assert result["canonical"] == json.loads(paths.result.document_json.read_text(encoding="utf-8"))
    assert result["markdown"] == paths.result.document_md.read_text(encoding="utf-8")
    assert result["structure_audit"] == json.loads(paths.result.audit_json.read_text(encoding="utf-8"))
