from pathlib import Path

import pytest


def _run_profiler():
    try:
        from pdffast.native.profiler import run_profiler
    except ModuleNotFoundError as exc:
        pytest.fail(f"profiler API is not implemented: {exc}")
    return run_profiler


def test_profiler_rejects_missing_pdf(tmp_path: Path) -> None:
    """Catches delayed failures after output directories have been touched."""
    run_profiler = _run_profiler()
    with pytest.raises(FileNotFoundError, match="PDF 不存在"):
        run_profiler(
            pdf_path=tmp_path / "missing.pdf",
            profile_output=tmp_path / "profile.json",
            snapshot_output=tmp_path / "snapshot.jsonl",
        )


def test_profiler_rejects_non_pdf_input(tmp_path: Path) -> None:
    """Catches accidental parsing of an unsupported input as PDF."""
    run_profiler = _run_profiler()
    text_file = tmp_path / "input.txt"
    text_file.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ValueError, match="输入文件不是 PDF"):
        run_profiler(
            pdf_path=text_file,
            profile_output=tmp_path / "profile.json",
            snapshot_output=tmp_path / "snapshot.jsonl",
        )

