"""Stage 10.1 canonical document builder, shipped with PDFFast Core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping

from pdffast.canonical.document_units import with_document_units
from pdffast.structure_reconciliation.anchor_admission import DocumentAnchorAdmissionDecision
from pdffast.structure_reconciliation.coverage import DocumentCoverageResult


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
    *,
    document_units: Iterable[DocumentCoverageResult] = (),
    admissions: Iterable[DocumentAnchorAdmissionDecision] = (),
    selected_index_data: Mapping[str, Any] | None = None,
    selected_predictions: Iterable[Mapping[str, Any]] | None = None,
    native_flow_data: Mapping[str, Any] | None = None,
    quality_data: Mapping[str, Any] | None = None,
    plan_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build canonical data from the completed native and fallback artifacts."""
    base = _load_implementation().build_document(
        Path(native_flow),
        Path(quality_gate),
        Path(provider_plan),
        Path(selected_index),
        Path(selected_dir),
        selected_index_data=selected_index_data,
        selected_predictions=selected_predictions,
        native_flow_data=native_flow_data,
        quality_data=quality_data,
        plan_data=plan_data,
    )
    return with_document_units(base, document_units, admissions)
