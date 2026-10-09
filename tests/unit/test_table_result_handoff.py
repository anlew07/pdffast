"""Stage 5's serialized result is retained without being the runtime input."""

import json
from pathlib import Path

import pytest

from pdffast.errors import ParseExecutionError
from pdffast.native import text_flow
from pdffast.pipeline import runner
from pdffast.pipeline.context import PipelineContext
from pdffast.quality import evidence


def test_table_result_passes_directly_to_text_flow_without_stage5_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table_path = tmp_path / "05/result.json"
    table_result = {"source_file": "input.pdf", "pages": [{"page_number": 1, "items": []}]}
    snapshot_meta = {"record_type": "meta", "source_file": "input.pdf", "page_count": 1}
    snapshot_pages = {1: {"record_type": "page", "page_number": 1, "native_text": "内容"}}
    page_structure = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    seen = []
    monkeypatch.setattr(text_flow, "load_snapshot", lambda path: (_ for _ in ()).throw(AssertionError("snapshot JSONL was reopened")))

    def load_json(path: Path) -> dict:
        raise AssertionError(f"TextFlow reopened {path}")

    monkeypatch.setattr(text_flow, "load_json", load_json)
    def build_result(meta: dict, pages: dict, structure: dict) -> dict:
        assert meta is snapshot_meta
        assert pages is snapshot_pages
        assert structure is page_structure
        return {"noise": True}

    monkeypatch.setattr(text_flow, "build_result", build_result)
    monkeypatch.setattr(text_flow, "build_reading_order_result", lambda *args: {"reading": True})
    monkeypatch.setattr(text_flow, "build_paragraph_result", lambda *args: {"paragraphs": True})
    monkeypatch.setattr(text_flow, "build_cross_page_paragraph_result", lambda *args: {"cross_page": True})
    monkeypatch.setattr(text_flow, "build_normalized_text_flow_result", lambda *args: {"records": []})

    def finalize(flow: dict, stage5: dict, snapshot: dict, noise: dict) -> dict:
        seen.append(stage5)
        return {**flow, "table_page_count": len(stage5["pages"])}

    monkeypatch.setattr(text_flow, "stage66_finalize_native_flow", finalize)
    flow = text_flow.create_text_flow_result(
        snapshot_path=tmp_path / "snapshot.jsonl",
        structure_path=tmp_path / "structure.json",
        table_result_path=table_path,
        table_result=table_result,
        snapshot_meta=snapshot_meta,
        snapshot_pages=snapshot_pages,
        page_structure=page_structure,
    )

    assert seen == [table_result]
    assert seen[0] is table_result
    assert flow.normalized_flow == {"records": [], "table_page_count": 1}
    assert not table_path.exists()


def test_table_result_passes_directly_to_evidence_without_stage5_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table_path = tmp_path / "05/result.json"
    table_result = {"source_file": "input.pdf", "pages": [{"page_number": 1, "items": []}]}
    profile = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    snapshot_meta = {"record_type": "meta", "source_file": "input.pdf", "page_count": 1}
    snapshot_pages = {1: {"record_type": "page", "page_number": 1, "native_text": "内容"}}
    alignment = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    page_structure = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    captured = {}

    def load_json(path: Path) -> dict:
        raise AssertionError(f"Evidence reopened {path}")

    monkeypatch.setattr(evidence, "load_json", load_json)
    monkeypatch.setattr(evidence, "load_snapshot", lambda path: (_ for _ in ()).throw(AssertionError("Evidence reopened snapshot JSONL")))

    def build_manifest(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {"accounted_tables": len(kwargs["stage5"]["pages"])}

    monkeypatch.setattr(evidence, "build_manifest", build_manifest)
    flow = text_flow.TextFlowResult({"noise": True}, {"reading": True}, {"paragraphs": True}, {}, {"records": []})
    report = evidence.create_evidence_report(
        profile_path=tmp_path / "profile.json",
        snapshot_path=tmp_path / "snapshot.jsonl",
        alignment_path=tmp_path / "alignment.json",
        structure_path=tmp_path / "structure.json",
        stage5_path=table_path,
        stage6_dir=tmp_path / "06",
        text_flow=flow,
        table_result=table_result,
        profile=profile,
        snapshot_meta=snapshot_meta,
        snapshot_pages=snapshot_pages,
        section_alignment=alignment,
        page_structure=page_structure,
    )

    assert captured["profile"] is profile
    assert captured["snapshot_meta"] is snapshot_meta
    assert captured["snapshot_pages"] is snapshot_pages
    assert captured["alignment"] is alignment
    assert captured["structure"] is page_structure
    assert captured["stage5"] is table_result
    assert captured["noise"] is flow.noise
    assert captured["reading"] is flow.reading_order
    assert captured["paragraphs"] is flow.paragraphs
    assert captured["normalized"] is flow.normalized_flow
    assert captured["input_paths"]["stage5_result"] == str(table_path)
    assert report.data == {"accounted_tables": 1}
    assert not table_path.exists()


def test_runner_hands_same_table_result_to_text_flow_and_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path,
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="handoff",
        case_id="input",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
        capture_output=False,
    )
    table_result = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    page_structure = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    profile = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    alignment = {"source_file": "input.pdf", "page_count": 1, "pages": []}
    snapshot_page = {"record_type": "page", "page_number": 1, "native_text": "内容"}
    seen = []
    flow = text_flow.TextFlowResult({}, {}, {}, {}, {})
    def write_profiler(**kwargs: object) -> dict:
        kwargs["snapshot_pages"][1] = snapshot_page
        kwargs["snapshot_meta"].update({"record_type": "meta", "source_file": "input.pdf", "page_count": 1})
        path = kwargs["snapshot_output"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot_page) + "\n", encoding="utf-8")
        return profile

    monkeypatch.setattr(runner, "run_profiler", write_profiler)
    monkeypatch.setattr(runner, "run_section_discovery", lambda **kwargs: alignment)
    def write_structure(**kwargs: object) -> dict:
        path = kwargs["output_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(page_structure), encoding="utf-8")
        return page_structure

    monkeypatch.setattr(runner, "run_page_structure", write_structure)

    def write_table(**kwargs: object) -> dict:
        assert kwargs.get("page_structure") is page_structure
        assert kwargs.get("snapshot_pages", {}).get(1) is snapshot_page
        assert kwargs["structure_path"].is_file()
        assert kwargs["snapshot_path"].is_file()
        path = kwargs["output_dir"] / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table_result) + "\n", encoding="utf-8")
        return table_result

    def make_flow(**kwargs: object) -> text_flow.TextFlowResult:
        assert kwargs.get("snapshot_pages", {}).get(1) is snapshot_page
        assert kwargs.get("snapshot_meta", {}).get("source_file") == "input.pdf"
        assert kwargs.get("page_structure") is page_structure
        seen.append(kwargs["table_result"])
        return flow

    def make_evidence(**kwargs: object) -> evidence.EvidenceReport:
        seen.append(kwargs["table_result"])
        assert kwargs["text_flow"] is flow
        assert kwargs.get("profile") is profile
        assert kwargs.get("snapshot_pages", {}).get(1) is snapshot_page
        assert kwargs.get("snapshot_meta", {}).get("source_file") == "input.pdf"
        assert kwargs.get("section_alignment") is alignment
        assert kwargs.get("page_structure") is page_structure
        return evidence.EvidenceReport({"source_file": "input.pdf"})

    monkeypatch.setattr(runner, "run_table_recovery", write_table)
    monkeypatch.setattr(runner, "create_text_flow_result", make_flow)
    monkeypatch.setattr(runner, "write_text_flow_result", lambda *args: None)
    monkeypatch.setattr(runner, "create_evidence_report", make_evidence)
    monkeypatch.setattr(runner, "write_evidence_report", lambda *args: None)
    monkeypatch.setattr(runner, "evaluate_evidence_report", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stop after evidence")))

    with pytest.raises(ParseExecutionError, match="stop after evidence"):
        runner.run_core_pipeline(context)

    assert seen == [table_result, table_result]
    assert all(value is table_result for value in seen)
    assert json.loads(context.artifacts.page_structure.read_text(encoding="utf-8")) == page_structure
    assert json.loads(context.artifacts.table_result.read_text(encoding="utf-8")) == table_result
