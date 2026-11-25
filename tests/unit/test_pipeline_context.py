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
    project = tmp_path / "pdffast-v3-test"
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


@pytest.mark.parametrize("locked", [False, True])
def test_parse_service_uses_one_expanded_output_root_for_reservation_and_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locked: bool,
) -> None:
    """The reserved run directory and Core context must resolve ~/ identically."""
    from types import SimpleNamespace

    from pdffast.application import parse_service as parse_service_module
    from pdffast.application.parse_service import ParseService
    from pdffast.config import ParserConfig

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"test-pdf")
    monkeypatch.setattr(
        parse_service_module,
        "_fingerprint",
        lambda _path: {
            "algorithm": "sha256",
            "sha256": "a" * 64,
            "byte_size": 8,
            "status": "COMPLETE",
        },
    )

    captured: dict[str, object] = {}
    sentinel = object()

    def fake_run_core_pipeline(context, **_kwargs):
        captured["context"] = context
        return sentinel

    monkeypatch.setattr(
        parse_service_module, "run_core_pipeline", fake_run_core_pipeline,
    )

    provider_profile = Path("configs/profiles/production.indra-triple.json") if locked else None
    config = ParserConfig(
        output_root=Path("~/pdffast-output"),
        provider_profile=provider_profile,
    )

    if locked:
        project_root = tmp_path / "project"
        project_root.mkdir()
        registry = SimpleNamespace(plugin_normalizers={})
        snapshot = SimpleNamespace(
            root=project_root,
            configs={},
            registry=registry,
            chains={},
        )
        monkeypatch.setattr(
            parse_service_module, "load_production_profile", lambda _config: snapshot,
        )
        monkeypatch.setattr(
            parse_service_module, "preflight_snapshot",
            lambda _snapshot, _config: {"status": "PASS"},
        )

    result = ParseService(config).parse(pdf, run_id="tilde-output-root")

    expected_root = (home / "pdffast-output").resolve()
    context = captured["context"]
    assert result is sentinel
    assert context.output_root == expected_root
    assert context.run_dir == expected_root / "tilde-output-root"
    assert context.run_dir.is_dir()
    if not locked:
        assert context.artifacts.result.manifest_json.is_file()
