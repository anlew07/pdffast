"""Guard active V3 code, tests, and operational docs against stale local paths."""

from pathlib import Path


def test_current_v3_surfaces_do_not_reference_legacy_workspaces_or_runs() -> None:
    root = Path(__file__).resolve().parents[2]
    forbidden = (
        "/Users/admin/Workspace/pdffast",
        "/Users/admin/Workspace/pdffast-v2",
        "pdffast-v2",
        "case_008_final_bench_v1",
        "outputs/final_structure_regression",
        "~/Workspace/resource",
    )
    paths = []
    for directory in ("pdffast", "scripts", "configs", "tests/unit", "tests/contracts"):
        paths.extend((root / directory).rglob("*.py" if directory in {"pdffast", "scripts", "tests/unit", "tests/contracts"} else "*.json"))
    paths.extend(
        root / path for path in (
            "README.md",
            "docs/QUICKSTART_ZH.md",
            "docs/PROVIDER_RUNTIME_ENVIRONMENTS.md",
            "docs/PIPELINE.md",
            "docs/ARCHITECTURE.md",
        )
    )
    violations = []
    for path in paths:
        if path.resolve() == Path(__file__).resolve() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(root)} contains {token!r}")
    assert violations == []
