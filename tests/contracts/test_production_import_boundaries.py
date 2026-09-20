import ast
from pathlib import Path


FORBIDDEN_IMPORT_PARTS = {
    "ground_truth",
    "evaluator",
    "holdout",
    "benchmark",
}


def test_runtime_modules_do_not_import_evaluation_code() -> None:
    violations: list[str] = []

    source_paths = sorted(Path("pdffast/fallback").glob("*.py"))
    source_paths += sorted(Path("pdffast/providers").glob("*.py"))
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                parts = set(name.lower().replace("-", "_").split("."))
                if parts & FORBIDDEN_IMPORT_PARTS:
                    violations.append(f"{source_path}:{node.lineno}:{name}")

    assert violations == []
