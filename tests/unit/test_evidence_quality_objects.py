from pathlib import Path

from pdffast.quality import evidence, gate
from pdffast.native import text_flow


def test_evidence_object_flows_to_quality_without_manifest_json_and_matches_wrappers(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = {
        "stage": 7,
        "name": "native_evidence_manifest",
        "version": "0.3.2",
        "manifest_schema_version": "1.2",
        "artifact_role": "native_pipeline_final_evidence_manifest",
        "final_flow_accounting_completed": True,
        "quality_gate_completed": False,
        "source_file": "empty.pdf",
        "page_count": 0,
        "pages": [],
        "summary": {"valid_raw_word_count": 0, "accounted_word_count": 0},
    }
    monkeypatch.setattr(evidence, "load_json", lambda path: {})
    monkeypatch.setattr(evidence, "load_snapshot", lambda path: ({}, {}))
    monkeypatch.setattr(evidence, "build_manifest", lambda **kwargs: manifest)
    paths = {
        "profile_path": tmp_path / "profile.json",
        "snapshot_path": tmp_path / "snapshot.jsonl",
        "template_path": tmp_path / "template.json",
        "alignment_path": tmp_path / "alignment.json",
        "structure_path": tmp_path / "structure.json",
        "stage5_path": tmp_path / "stage5.json",
        "stage6_dir": tmp_path / "stage6",
    }
    evidence_dir = tmp_path / "evidence"
    quality_dir = tmp_path / "quality"
    manifest_path = evidence_dir / "evidence_manifest.json"

    report = evidence.create_evidence_report(**paths)
    assert isinstance(report, evidence.EvidenceReport)
    assert not manifest_path.exists()
    quality = gate.evaluate_evidence_report(
        report, manifest_path=manifest_path, pdf_path=None, output_dir=quality_dir
    )
    assert isinstance(quality, gate.QualityReport)
    assert quality.data["summary"]["document_status"] == "NATIVE_COMPLETE"
    assert not manifest_path.exists()
    assert not (quality_dir / "quality_gate.json").exists()

    evidence.write_evidence_report(report, evidence_dir)
    gate.write_quality_report(quality, quality_dir)
    artifacts = [
        manifest_path,
        evidence_dir / "evidence_manifest.md",
        quality_dir / "quality_gate.json",
        quality_dir / "quality_gate.md",
    ]
    expected_bytes = {path: path.read_bytes() for path in artifacts}
    evidence.run_evidence_manifest(**paths, output_dir=evidence_dir)
    gate.run_quality_gate(
        manifest_path=manifest_path, pdf_path=None, output_dir=quality_dir
    )
    assert {path: path.read_bytes() for path in artifacts} == expected_bytes


def test_evidence_uses_text_flow_object_without_stage6_json(tmp_path: Path, monkeypatch) -> None:
    flow = text_flow.TextFlowResult(
        noise={"source_file": "sample.pdf", "pages": []},
        reading_order={"source_file": "sample.pdf", "pages": []},
        paragraphs={"source_file": "sample.pdf", "pages": []},
        cross_page_paragraphs={},
        normalized_flow={"source_file": "sample.pdf", "records": []},
    )
    captured = {}
    monkeypatch.setattr(evidence, "load_json", lambda path: {})
    monkeypatch.setattr(evidence, "load_snapshot", lambda path: ({}, {}))

    def fake_build_manifest(**kwargs):
        captured.update(kwargs)
        return {"stage": 7}

    monkeypatch.setattr(evidence, "build_manifest", fake_build_manifest)
    stage6_dir = tmp_path / "stage6"
    report = evidence.create_evidence_report(
        profile_path=tmp_path / "profile.json",
        snapshot_path=tmp_path / "snapshot.jsonl",
        template_path=tmp_path / "template.json",
        alignment_path=tmp_path / "alignment.json",
        structure_path=tmp_path / "structure.json",
        stage5_path=tmp_path / "stage5.json",
        stage6_dir=stage6_dir,
        text_flow=flow,
    )

    assert report.data == {"stage": 7}
    assert captured["noise"] is flow.noise
    assert captured["reading"] is flow.reading_order
    assert captured["paragraphs"] is flow.paragraphs
    assert captured["normalized"] is flow.normalized_flow
    assert not stage6_dir.exists()
