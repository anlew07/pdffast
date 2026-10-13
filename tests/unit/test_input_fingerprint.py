import hashlib
import json

import pytest

from pdffast.application.parse_service import ParseService
from pdffast.config import ParserConfig


@pytest.mark.parametrize("size", [0, 9, 2 * 1024 * 1024 + 7])
def test_input_fingerprint_saved_before_pipeline_even_on_failure(tmp_path, monkeypatch, size):
    payload = b"x" * size
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(payload)
    def fail(context, **kwargs):
        metadata = context.input_metadata
        assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
        assert metadata["byte_size"] == len(payload)
        saved = json.loads(context.artifacts.result.manifest_json.read_text())
        assert saved["input"] == metadata
        assert saved["run_id"] == "fingerprint"
        raise RuntimeError("pipeline failed")
    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", fail)
    with pytest.raises(RuntimeError, match="pipeline failed"):
        ParseService(ParserConfig(output_root=tmp_path / "out")).parse(pdf, run_id="fingerprint")
    assert (tmp_path / "out/fingerprint/result/manifest.json").is_file()


def test_missing_input_has_explicit_unknown_size(tmp_path, monkeypatch):
    def check(context, **kwargs):
        assert context.input_metadata["status"] == "FAILED"
        assert context.input_metadata["sha256"] is None
        assert context.input_metadata["byte_size"] is None
        assert "FileNotFoundError" in context.input_metadata["error"]
    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", check)
    ParseService(ParserConfig(output_root=tmp_path / "out")).parse(tmp_path / "missing.pdf")


def test_fingerprint_survives_configuration_failure(tmp_path):
    from pdffast.errors import ConfigurationError
    from pdffast.pipeline.artifacts import ArtifactPaths
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-source")
    with pytest.raises(ConfigurationError):
        ParseService(ParserConfig(project_root=tmp_path / "no-config", output_root=tmp_path / "out")).parse(pdf, run_id="bad-config")
    manifest = ArtifactPaths.for_run(tmp_path / "out/bad-config").result.manifest_json
    assert json.loads(manifest.read_text())["input"]["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()


def test_final_manifest_preserves_runtime_input_metadata(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from pdffast.pipeline.context import PipelineContext
    from pdffast.pipeline.runner import run_stage10
    context = PipelineContext.create(project_root=tmp_path, pdf=tmp_path / "input.pdf",
        output_root=tmp_path, run_id="final", case_id=None, page_dpi=200,
        region_dpi=300, rapidocr_workers=1, table_mode="auto")
    metadata = {"status": "COMPLETE", "algorithm": "sha256", "sha256": "a" * 64, "byte_size": 123}
    context = replace(context, input_metadata=metadata)
    for path in (context.artifacts.observability.render_manifest,
                 context.artifacts.observability.structure_audit):
        path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("pdffast.pipeline.runner.build_document", lambda *a, **k: {"unchanged": True})
    monkeypatch.setattr("pdffast.pipeline.runner.build_rendered_document", lambda *a: ("unchanged", {}))
    monkeypatch.setattr("pdffast.pipeline.runner.audit", lambda *a, **k: {"validation": {"pass": True}})
    result = run_stage10(context, text_flow=SimpleNamespace(normalized_flow={}),
                         quality_report=SimpleNamespace(data={}))
    assert json.loads(context.artifacts.result.manifest_json.read_text())["input"] == metadata
    assert result["markdown"] == "unchanged"
    assert result["canonical"] == {"unchanged": True}
