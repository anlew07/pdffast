"""Stage 10.2.1 structural boundary audit shipped with PDFFast Core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_implementation() -> ModuleType:
    path = Path(__file__).with_name("_stage10_audit.py")
    spec = importlib.util.spec_from_file_location("pdffast_stage10_audit", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载内置结构边界审计器：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(
    native: dict[str, Any],
    quality_gate: dict[str, Any],
    canonical: dict[str, Any],
    render_manifest: dict[str, Any],
    *,
    markdown: str | None = None,
) -> dict[str, Any]:
    """Audit stage boundaries using already-loaded artifacts."""
    return _load_implementation().audit(
        native, quality_gate, canonical, render_manifest, markdown=markdown
    )
