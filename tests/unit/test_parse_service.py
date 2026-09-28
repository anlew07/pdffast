from pathlib import Path

from pdffast import PDFFastParser, ParseResult, ParserConfig
from pdffast.application.parse_service import ParseService


def test_parser_delegates_public_arguments_and_returns_parse_result(
    tmp_path: Path, monkeypatch
) -> None:
    expected = ParseResult(canonical={}, markdown="ok", audit={}, artifacts={})
    calls = {}

    def fake_parse(self, pdf_path, *, run_id, case_id):
        calls.update(config=self.config, pdf_path=pdf_path, run_id=run_id, case_id=case_id)
        return expected

    monkeypatch.setattr("pdffast.application.parse_service.ParseService.parse", fake_parse)
    pdf = tmp_path / "input.pdf"
    result = PDFFastParser(output_root=tmp_path / "out", output_mode="full").parse(
        pdf, run_id="run-1", case_id="case-1"
    )

    assert result is expected
    assert isinstance(result, ParseResult)
    assert calls["pdf_path"] == pdf
    assert calls["run_id"] == "run-1"
    assert calls["case_id"] == "case-1"
    assert calls["config"].output_root == tmp_path / "out"
    assert calls["config"].output_mode == "full"


def test_parse_service_loads_bundled_config_without_starting_providers(
    tmp_path: Path, monkeypatch
) -> None:
    expected = ParseResult(canonical={}, markdown="ok", audit={}, artifacts={})
    captured = {}

    def fake_run(context, **kwargs):
        captured.update(context=context, **kwargs)
        return expected

    monkeypatch.setattr("pdffast.application.parse_service.run_core_pipeline", fake_run)
    result = ParseService(ParserConfig(output_root=tmp_path)).parse(tmp_path / "input.pdf")

    assert result is expected
    assert captured["context"].providers.is_file()
    assert len(captured["provider_configs"]) == 6
    assert captured["execute_providers"] is True
