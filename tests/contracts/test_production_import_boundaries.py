import ast
from pathlib import Path


FORBIDDEN_IMPORT_PARTS = {
    "ground_truth",
    "evaluator",
    "holdout",
    "benchmark",
}

FORBIDDEN_SERVICE_IMPORT_ROOTS = {
    "celery",
    "fastapi",
    "starlette",
}

FORBIDDEN_HTTP_ADAPTER_TYPES = {
    "HTTPRequest",
    "HTTPResponse",
    "Request",
    "Response",
    "UploadFile",
}

CORE_PACKAGES = {
    "parser", "pipeline", "native", "template", "quality", "fallback",
    "providers", "canonical", "render", "audit",
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


def test_core_package_does_not_import_service_frameworks_or_http_types() -> None:
    violations: list[str] = []

    source_paths = sorted(
        path for path in Path("pdffast").rglob("*.py")
        if (
            path.relative_to("pdffast").parts[0] in CORE_PACKAGES
            or path.relative_to("pdffast") == Path("parser.py")
        )
    )
    for source_path in source_paths:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0].lower()
                    if root in FORBIDDEN_SERVICE_IMPORT_ROOTS:
                        violations.append(
                            f"{source_path}:{node.lineno}:import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".", 1)[0].lower()
                if root in FORBIDDEN_SERVICE_IMPORT_ROOTS:
                    violations.append(
                        f"{source_path}:{node.lineno}:from {module}"
                    )
                for alias in node.names:
                    if alias.name in FORBIDDEN_HTTP_ADAPTER_TYPES:
                        violations.append(
                            f"{source_path}:{node.lineno}:import type {alias.name}"
                        )

    assert violations == []
