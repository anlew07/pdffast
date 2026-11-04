from __future__ import annotations

from pathlib import Path

from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.pipeline import runner


def test_v3_finalization_has_semantic_internal_entrypoint(tmp_path: Path) -> None:
    assert callable(runner.finalize_document)
    assert not hasattr(runner, "run_stage10")


def test_new_runs_use_semantic_directories_but_keep_public_results(tmp_path: Path) -> None:
    run_dir = tmp_path / "one-run"
    artifacts = ArtifactPaths.for_run(run_dir)
    for name, path in artifacts.as_dict().items():
        assert "stage" not in str(path.relative_to(run_dir)).lower(), name
    assert artifacts.result_document == run_dir / "result/document.json"
    assert artifacts.result_markdown == run_dir / "result/document.md"
    assert artifacts.result_audit == run_dir / "result/audit.json"
    assert artifacts.result_manifest == run_dir / "result/manifest.json"


def test_implementation_file_names_describe_responsibilities() -> None:
    root = Path(__file__).resolve().parents[2] / "pdffast"
    for folder, filename in (
        ("canonical", "_document_builder_impl.py"),
        ("render", "_markdown_renderer_impl.py"),
        ("audit", "_boundary_audit_impl.py"),
    ):
        assert (root / folder / filename).is_file()
