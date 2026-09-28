"""Stage 10.1 canonical document builder, shipped with PDFFast Core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_implementation() -> ModuleType:
    path = Path(__file__).with_name("_stage10_builder.py")
    spec = importlib.util.spec_from_file_location("pdffast_stage10_builder", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载内置规范文档构建器：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_document(
    native_flow: Path,
    quality_gate: Path,
    provider_plan: Path,
    selected_index: Path,
    selected_dir: Path,
) -> dict[str, Any]:
    """Build canonical data from the completed native and fallback artifacts."""
    return _load_implementation().build_document(
        Path(native_flow),
        Path(quality_gate),
        Path(provider_plan),
        Path(selected_index),
        Path(selected_dir),
    )
