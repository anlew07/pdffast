"""Fresh Stage 10 consumes existing runtime objects; file entry remains available."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pdffast.fallback.executor import ProviderExecutionResult
from pdffast.fallback.router import CapabilityPlan
from pdffast.native.text_flow import TextFlowResult
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline import runner
from pdffast.pipeline.runner import run_stage10
from pdffast.quality.gate import QualityReport


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("case", [2, 3, 4])
def test_stage10_remaining_objects_match_file_path_without_runtime_reloads(
    case: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = ROOT / f"outputs/final_structure_regression/case_{case:03d}"
    files = {
        "section_alignment": source / "03_stage3/section_alignment.json",
        "normalized_flow": source / "06_stage6/normalized_text_flow.json",
        "quality_gate": source / "08_stage8/quality_gate.json",
        "provider_plan": source / "09_2_provider_plan/provider_plan.json",
        "selected_prediction_index": source / "09_8_production_fallback/selected_prediction_index.json",
        "selected_predictions_dir": source / "09_8_production_fallback/selected_predictions",
    }
    if not all(path.exists() for path in files.values()):
        pytest.skip(f"case_{case:03d} existing artifacts unavailable")
    alignment = json.loads(files["section_alignment"].read_text(encoding="utf-8"))
    flow_data = json.loads(files["normalized_flow"].read_text(encoding="utf-8"))
    flow = TextFlowResult({}, {}, {}, {}, flow_data)
    quality = QualityReport(json.loads(files["quality_gate"].read_text(encoding="utf-8")))
    capability = CapabilityPlan(json.loads(files["provider_plan"].read_text(encoding="utf-8")))
    index = json.loads(files["selected_prediction_index"].read_text(encoding="utf-8"))
    wrappers = [json.loads((files["selected_predictions_dir"] / f"{item['task_id']}.json").read_text(encoding="utf-8"))
                for item in index["items"]]
    selection = ProviderExecutionResult({}, index, wrappers)
    original_objects = copy.deepcopy((alignment, flow_data, quality.data, capability.data, index, wrappers))
    input_paths = [*list(files.values())[:-1], *(
        files["selected_predictions_dir"] / f"{item['task_id']}.json" for item in index["items"]
    )]
    before_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths}

    context = PipelineContext.create(
        project_root=ROOT, pdf=tmp_path / f"case_{case:03d}.pdf", output_root=tmp_path,
        run_id="stage10-remaining", case_id=f"case_{case:03d}", page_dpi=200,
        region_dpi=300, rapidocr_workers=1, table_mode="auto",
    )
    context = replace(context, artifacts=replace(context.artifacts, **files))
    legacy = run_stage10(context)
    outputs = (context.artifacts.result_document, context.artifacts.result_markdown,
               context.artifacts.render_manifest, context.artifacts.result_audit)
    expected_bytes = tuple(path.read_bytes() for path in outputs)

    guarded = {path.resolve() for path in input_paths}
    original_read_text, original_open = Path.read_text, Path.open
    original_audit = runner.audit
    audit_inputs = {}

    def check_audit(native, qg, canonical, manifest, *, markdown):
        audit_inputs.update(native=native, quality=qg, canonical=canonical, manifest=manifest, markdown=markdown)
        before = copy.deepcopy((native, qg, canonical, manifest))
        result = original_audit(native, qg, canonical, manifest, markdown=markdown)
        assert (native, qg, canonical, manifest) == before
        return result

    def check_read(path: Path):
        target = path.resolve()
        if target not in guarded:
            return
        raise AssertionError(f"fresh Stage 10 reloaded runtime artifact: {path}")

    def guard_read_text(path: Path, *args, **kwargs):
        check_read(path)
        return original_read_text(path, *args, **kwargs)

    def guard_open(path: Path, mode="r", *args, **kwargs):
        if "r" in mode:
            check_read(path)
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "read_text", guard_read_text)
        patcher.setattr(Path, "open", guard_open)
        patcher.setattr(runner, "audit", check_audit)
        fresh = run_stage10(
            context, selection=selection, section_alignment=alignment,
            text_flow=flow, quality_report=quality, capability_plan=capability,
        )

    assert tuple(path.read_bytes() for path in outputs) == expected_bytes
    assert (fresh["canonical"], fresh["markdown"], fresh["structure_audit"]) == (
        legacy["canonical"], legacy["markdown"], legacy["structure_audit"])
    assert (alignment, flow_data, quality.data, capability.data, index, wrappers) == original_objects
    assert audit_inputs["native"] is flow.normalized_flow
    assert audit_inputs["quality"] is quality.data
    assert audit_inputs["canonical"] is fresh["canonical"]
    assert audit_inputs["markdown"] == fresh["markdown"]
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_paths} == before_hashes
    if case == 3:
        assert fresh["canonical"]["summary"]["terminal_preserve_count"] == 2
        assert [unit["anchor"]["page"] for unit in fresh["canonical"]["document_units"]] == [27, 29, 30, 36, 66]
