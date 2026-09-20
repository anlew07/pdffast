from pathlib import Path

import pytest


def _context_type():
    try:
        from pdffast.pipeline.context import PipelineContext
    except ModuleNotFoundError as exc:
        pytest.fail(f"PipelineContext is not implemented: {exc}")
    return PipelineContext


def test_context_resolves_paths_and_sanitizes_case_id(tmp_path: Path) -> None:
    """Catches unstable defaults or unsafe case IDs entering run paths."""
    PipelineContext = _context_type()
    project = tmp_path / "pdffast-v2"
    pdf = project / "benchmark/samples/科研 case 007.pdf"
    ctx = PipelineContext.create(
        project_root=project,
        pdf=pdf,
        output_root=project / "outputs",
        run_id="case_007_fixed",
        case_id=None,
        page_dpi=150,
        region_dpi=150,
        rapidocr_workers=1,
        table_mode="auto",
    )

    assert ctx.case_id == "_case_007"
    assert ctx.pdf == pdf.resolve()
    assert ctx.run_dir == project.resolve() / "outputs/case_007_fixed"
    assert ctx.templates == project.resolve() / "configs/templates.json"
    assert ctx.providers == project.resolve() / "configs/providers.json"
    assert ctx.route_candidates == (
        project.resolve()
        / "configs/frozen/stage9_route_candidates_prod_v001.json"
    )
    assert ctx.artifacts.llm_ready == (
        ctx.run_dir / "10_2_llm_ready/llm_ready.md"
    )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"page_dpi": 0}, "page_dpi"),
        ({"region_dpi": -1}, "region_dpi"),
        ({"rapidocr_workers": 0}, "rapidocr_workers"),
        ({"table_mode": "sometimes"}, "table_mode"),
    ],
)
def test_context_rejects_invalid_runtime_parameters(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    """Catches invalid values before they reach a production stage."""
    PipelineContext = _context_type()
    kwargs: dict[str, object] = {
        "project_root": tmp_path / "project",
        "pdf": tmp_path / "input.pdf",
        "output_root": tmp_path / "outputs",
        "run_id": "fixed",
        "case_id": "case",
        "page_dpi": 150,
        "region_dpi": 150,
        "rapidocr_workers": 1,
        "table_mode": "auto",
    }
    kwargs.update(override)

    with pytest.raises(ValueError, match=message):
        PipelineContext.create(**kwargs)
