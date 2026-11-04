"""Canonical-to-Markdown structural boundary audit for PDFFast V3."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_implementation() -> ModuleType:
    path = Path(__file__).with_name("_boundary_audit_impl.py")
    spec = importlib.util.spec_from_file_location("pdffast_boundary_audit", path)
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
    """Audit native, recovered and rendered structure using loaded objects."""
    return _load_implementation().audit(
        native, quality_gate, canonical, render_manifest, markdown=markdown
    )
