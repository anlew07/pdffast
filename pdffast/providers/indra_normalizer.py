"""Normalize Indra's emitted markdown and line geometry without re-OCR.

Empty OCR text remains empty and must fail the existing Stage 9.8 gate.
No fabricated tables, formulas or relations.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .normalization import (
    SCHEMA_VERSION, VERSION, STATUS_MAP, availability,
    extract_tables, extract_formulas, extract_reading_blocks,
    markdown_to_plain_text, source_sha256, text_payload,
)

def normalize_indra(
    *, result: dict[str, Any], manifest_task: dict[str, Any],
    manifest_path: Path, result_path: Path,
    known_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    provider = result.get("provider") or {}
    if provider.get("name") != "indra_local":
        raise ValueError("Indra normalizer received another Provider")
    raw_status = str(result.get("status") or "").upper()
    canonical_status = STATUS_MAP.get(raw_status, "ERROR")
    markdown = str(result.get("text") or "")
    response = result.get("worker_response") or {}
    if not isinstance(response, dict):
        response = {}
    tables = extract_tables(markdown)
    formulas = extract_formulas(markdown)
    blocks = extract_reading_blocks(markdown)
    normalized_text = markdown_to_plain_text(markdown, tables)
    # A page may have plain OCR text but no markdown blocks; preserve it.
    plain_text = str(response.get("plain_text") or "").strip()
    if not normalized_text.strip() and plain_text:
        normalized_text = plain_text
    raw_lines = response.get("lines") or []
    items = []
    for index, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        box = line.get("box") or []
        if not text or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        items.append({
            "item_id": f"indra_line_{index + 1:04d}",
            "text": text, "bbox": dict(zip(("x0", "top", "x1", "bottom"), box)),
            "confidence": line.get("conf"), "provider_order": index,
        })

    task_id = str(result.get("task_id") or "")
    prediction = {
        "schema_version": SCHEMA_VERSION, "stage": 9, "substage": "9.5.1",
        "name": "canonical_prediction", "version": VERSION,
        "task_id": task_id,
        "task_type": result.get("task_type") or manifest_task.get("task_type"),
        "page_number": result.get("page_number", manifest_task.get("page_number")),
        "source_id": result.get("source_id") or manifest_task.get("source_id"),
        "capability_route": result.get("capability_route") or manifest_task.get("capability_route"),
        "provider": {
            "name": "indra_local", "kind": provider.get("kind") or "indra_worker",
            "model_or_engine": provider.get("model_or_engine") or "indra-ocr",
            "adapter": "indra_local_v1",
        },
        "status": canonical_status, "raw_status": raw_status,
        "elapsed_seconds": result.get("elapsed_seconds"),
        "text": text_payload(canonical_status, normalized_text, None,
                             raw_content=markdown, source_format="markdown"),
        "spatial_text": {
            "availability": "AVAILABLE" if items else "NOT_EMITTED",
            "items": items, "coordinate_system": "provider_image_pixels",
            "semantics": "OCR_LINE_BOXES_NO_INFERRED_RELATIONS",
        },
        "tables": availability("AVAILABLE" if tables else "NOT_EMITTED", tables),
        "formulas": availability("AVAILABLE" if formulas else "NOT_EMITTED", formulas),
        "reading_blocks": availability("AVAILABLE" if blocks else "NOT_EMITTED", blocks),
        "relations": availability("UNSUPPORTED", []),
        "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
        "exception": result.get("exception"),
        "diagnostics": {
            "line_count": len(items), "explicit_table_count": len(tables),
            "explicit_formula_count": len(formulas),
            "ocr_source": response.get("source"),
            "quality_warning": "A non-empty result does not establish transcription accuracy",
        },
        "source_artifacts": {
            "benchmark_manifest": str(manifest_path),
            "benchmark_manifest_sha256": source_sha256(manifest_path, known_hashes),
            "task_result": str(result_path),
            "task_result_sha256": source_sha256(result_path, known_hashes),
            "provider_raw_refs": list(response.get("raw_refs") or result.get("raw_refs") or []),
            "input_image": result.get("input_image") or manifest_task.get("input_image"),
        },
        "normalization_policy": {
            "re_ocr": False, "infer_tables_from_plain_text": False,
            "infer_relations_from_geometry": False,
            "preserve_raw_markdown": True,
        },
    }
    return prediction
