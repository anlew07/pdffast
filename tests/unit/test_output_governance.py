import logging
import sys
from pathlib import Path

import pytest

from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError, ParseExecutionError
from pdffast.parser import PDFFastParser
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_core_pipeline
from pdffast.result import ParseResult
from pdffast.runtime import capture_runtime_output


def test_parser_config_defaults_to_minimal_and_capture(tmp_path: Path) -> None:
    config = ParserConfig(project_root=tmp_path)
    assert config.output_mode == "minimal"
    assert config.capture_output is True
    assert config.output_root == Path("outputs")


@pytest.mark.parametrize("mode", ["unknown", "", "MINIMAL"])
def test_parser_config_rejects_unknown_output_mode(tmp_path: Path, mode: str) -> None:
    with pytest.raises(ConfigurationError, match="output_mode"):
        ParserConfig(project_root=tmp_path, output_mode=mode)


def test_parser_accepts_parser_config_as_public_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = object()
    normalizer = object()
    config = ParserConfig(
        project_root=tmp_path / "project",
        output_root=tmp_path / "configured-outputs",
        output_mode="diagnostic",
        capture_output=False,
        page_dpi=180,
        region_dpi=320,
        rapidocr_workers=2,
        table_mode="all",
        provider_configs={"provider": {"runtime_enabled": True}},
        registry=registry,
        normalizer=normalizer,
    )
    captured: dict[str, object] = {}

    def fake_run(context: PipelineContext, **kwargs: object) -> str:
        captured["context"] = context
        captured.update(kwargs)
        return "parsed"

    monkeypatch.setattr("pdffast.parser.run_core_pipeline", fake_run)

    result = PDFFastParser(config=config).parse(
        tmp_path / "input.pdf",
        run_id="configured-run",
    )

    context = captured["context"]
    assert isinstance(context, PipelineContext)
    assert result == "parsed"
    assert context.output_root == (tmp_path / "configured-outputs").resolve()
    assert context.output_mode == "diagnostic"
    assert context.capture_output is False
    assert context.page_dpi == 180
    assert context.region_dpi == 320
    assert context.rapidocr_workers == 2
    assert context.table_mode == "all"
    assert captured["registry"] is registry
    assert captured["normalizer"] is normalizer


def test_public_execution_error_carries_run_and_log_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    log_path = run_dir / "diagnostics/logs/pipeline.log"
    error = ParseExecutionError("解析失败", run_dir=run_dir, log_path=log_path)
    assert error.run_dir == run_dir
    assert error.log_path == log_path
    assert "解析失败" in str(error)


def test_context_exposes_output_contract(tmp_path: Path) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="fixed",
        case_id="case",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
        output_mode="diagnostic",
        capture_output=True,
    )
    assert context.output_mode == "diagnostic"
    assert context.capture_output is True
    assert context.artifacts.result_dir == context.run_dir / "result"
    assert context.artifacts.pipeline_log == context.run_dir / "diagnostics/logs/pipeline.log"


def test_runtime_capture_keeps_stage_output_out_of_terminal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "pipeline.log"
    with capture_runtime_output(log_path):
        print("旧阶段调试输出")
        logging.getLogger("pdffast.test").warning("Provider warning")

    captured = capsys.readouterr()
    assert "旧阶段调试输出" not in captured.out
    assert "Provider warning" not in captured.err
    log = log_path.read_text(encoding="utf-8")
    assert "旧阶段调试输出" in log
    assert "Provider warning" in log


def test_runtime_capture_temporarily_silences_existing_root_handlers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = logging.getLogger()
    terminal_handler = logging.StreamHandler(sys.stderr)
    root.addHandler(terminal_handler)
    try:
        with capture_runtime_output(tmp_path / "pipeline.log"):
            logging.getLogger("pdffast.hosted").warning("host-visible warning")

        logging.getLogger("pdffast.hosted").warning("handler restored")
    finally:
        root.removeHandler(terminal_handler)
        terminal_handler.close()

    captured = capsys.readouterr()
    assert "host-visible warning" not in captured.err
    assert "handler restored" in captured.err
    assert "host-visible warning" in (tmp_path / "pipeline.log").read_text(
        encoding="utf-8"
    )


def test_pipeline_failure_writes_traceback_to_run_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id="failed",
        case_id="case",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )

    def fail_profiler(**kwargs: object) -> None:
        raise RuntimeError("synthetic stage failure")

    monkeypatch.setattr("pdffast.pipeline.runner.run_profiler", fail_profiler)

    with pytest.raises(ParseExecutionError) as error:
        run_core_pipeline(context)

    assert error.value.run_dir == context.run_dir
    assert error.value.log_path == context.artifacts.pipeline_log
    log = context.artifacts.pipeline_log.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log
    assert "RuntimeError: synthetic stage failure" in log


@pytest.mark.parametrize(
    ("mode", "has_log", "has_internal"),
    [
        ("minimal", False, False),
        ("diagnostic", True, False),
        ("full", True, True),
    ],
)
def test_parse_result_exposes_mode_appropriate_artifacts(
    tmp_path: Path, mode: str, has_log: bool, has_internal: bool
) -> None:
    context = PipelineContext.create(
        project_root=tmp_path / "project",
        pdf=tmp_path / "input.pdf",
        output_root=tmp_path / "outputs",
        run_id=mode,
        case_id="case",
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
        output_mode=mode,
    )
    result = ParseResult.from_pipeline(
        context,
        {
            "canonical": {"records": []},
            "markdown": "# 文档",
            "structure_audit": {"validation": {"pass": True}},
            "render_manifest": {},
            "production_manifest": {},
        },
    )

    assert result.markdown == "# 文档"
    assert result["markdown"] == result.markdown
    assert "result_markdown" in result.artifacts
    assert ("pipeline_log" in result.artifacts) is has_log
    assert ("profile" in result.artifacts) is has_internal
