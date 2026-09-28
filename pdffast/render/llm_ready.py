"""Stage 10.2 renderer, shipped with PDFFast Core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_implementation() -> ModuleType:
    path = Path(__file__).with_name("_stage10_renderer.py")
    spec = importlib.util.spec_from_file_location("pdffast_stage10_renderer", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载内置 Markdown 渲染器：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_canonical(doc: dict[str, Any]) -> None:
    _load_implementation().validate_canonical(doc)


def build_rendered_document(doc: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Render canonical data to Markdown and a deterministic manifest."""
    return _load_implementation().build_rendered_document(doc)
