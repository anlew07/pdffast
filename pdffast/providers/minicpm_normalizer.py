"""Canonical normalization for the opt-in MiniCPM-OCR image-recognition plugin.

No hallucinated tables, reading blocks, semantic relations or formula structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .normalization import (
    SCHEMA_VERSION, VERSION, STATUS_MAP, availability,
    source_sha256, text_payload,
)


def normalize(
    *,
    result: dict[str, Any],
    manifest_task: dict[str, Any],
    manifest_path: Path,
    result_path: Path,
    known_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    provider = result.get("provider")
    if not isinstance(provider, dict) or provider.get("name") != "minicpm_ocr_local":
        raise ValueError("MiniCPM normalizer received incorrect Provider")
    status = str(result.get("status") or "").upper()
    canonical_status = STATUS_MAP.get(status, "ERROR")
    text = result.get("text") if isinstance(result.get("text"), str) else ""
    warnings = result.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    structure = result.get("structure")
    if not isinstance(structure, dict):
        structure = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": 9, "substage": "9.5.1",
        "name": "canonical_prediction", "version": VERSION,
        "task_id": result.get("task_id"),
        "task_type": manifest_task.get("task_type"),
        "page_number": manifest_task.get("page_number"),
        "source_id": manifest_task.get("source_id"),
        "capability_route": manifest_task.get("capability_route"),
        "provider": {
            "name": provider["name"], "kind": provider.get("kind"),
            "model_or_engine": provider.get("model_or_engine"),
            "adapter": "minicpm_ocr_single_image_v1",
        },
        "status": canonical_status,
        "raw_status": status,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "text": text_payload(
            canonical_status, text, None,
            raw_content=text, source_format="plain_text",
        ),
        "tables": availability("NOT_EMITTED", []),
        "formulas": availability("NOT_EMITTED", []),
        "reading_blocks": availability("NOT_EMITTED", []),
        "relations": availability("UNSUPPORTED", []),
        "warnings": warnings, "exception": result.get("exception"),
        "diagnostics": {
            "quality_hints": {},
            "provider_structure_summary": structure,
            "recognition_scope": "SINGLE_IMAGE_NOT_FULL_DOCUMENT_SDK",
        },
        "source_artifacts": {
            "benchmark_manifest": str(manifest_path),
            "benchmark_manifest_sha256": source_sha256(manifest_path, known_hashes),
            "task_result": str(result_path),
            "task_result_sha256": source_sha256(result_path, known_hashes),
            "provider_raw_refs": [],
            "input_image": manifest_task.get("input_image"),
        },
        "normalization_policy": {
            "re_ocr": False,
            "infer_table_structure_from_text": False,
            "infer_reading_order_from_text": False,
            "infer_formulas_from_text": False,
            "infer_relations_from_text": False,
        },
    }
