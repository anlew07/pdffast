import ast
from pathlib import Path


FORBIDDEN_IMPORT_PARTS = {
    "ground_truth",
    "evaluator",
    "holdout",
    "benchmark",
}


def test_fallback_production_modules_do_not_import_evaluation_code() -> None:
    fallback_root = Path("pdffast/fallback")
    violations: list[str] = []

    for source_path in sorted(fallback_root.glob("*.py")):
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
