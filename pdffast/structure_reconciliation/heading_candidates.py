"""Read selected whole-page predictions as unaccepted heading evidence.

This module deliberately has no section writer or pipeline integration. A
candidate is only evidence for a later reconciliation decision.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class RecoveredHeadingCandidate:
    page_number: int
    text: str
    task_id: str
    task_type: str
    provider: str
    evidence_kind: str
    source_reference: str | None
    prediction_reference: str | None
    provider_confidence: float | None
    raw_bbox: dict[str, Any] | None
    bbox_coordinate_space: str | None
    block_index: int | None
    signals: dict[str, Any]
    score: float
    status: str = "CANDIDATE"


@dataclass(frozen=True)
class RecoveredHeadingDiagnostic:
    page_number: int
    task_id: str
    provider: str | None
    text: str | None
    evidence_kind: str | None
    status: str
    reason: str


@dataclass(frozen=True)
class RecoveredHeadingReport:
    candidates: tuple[RecoveredHeadingCandidate, ...]
    diagnostics: tuple[RecoveredHeadingDiagnostic, ...]


def _items(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping) or value.get("availability") != "AVAILABLE":
        return []
    return [item for item in value.get("items", []) if isinstance(item, Mapping)]


def _bbox(item: Mapping[str, Any]) -> dict[str, Any] | None:
    bbox = item.get("bbox")
    if not isinstance(bbox, Mapping):
        return None
    try:
        result = {key: float(bbox[key]) for key in ("x0", "top", "x1", "bottom")}
    except (KeyError, TypeError, ValueError):
        return None
    if result["x1"] <= result["x0"] or result["bottom"] <= result["top"]:
        return None
    return result


def _confidence(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def extract_recovered_heading_candidates(
    native_flow: Mapping[str, Any],
    selected_predictions: Iterable[Mapping[str, Any]],
    *,
    prediction_references: Mapping[str, str] | None = None,
) -> RecoveredHeadingReport:
    """Inspect selected predictions without changing Native or Canonical data."""
    ownership = {
        int(page["page_number"]): page.get("section_id")
        for page in native_flow.get("page_index", [])
        if isinstance(page, Mapping) and page.get("page_number") is not None
    }
    candidates: list[RecoveredHeadingCandidate] = []
    diagnostics: list[RecoveredHeadingDiagnostic] = []

    for wrapper in selected_predictions:
        page = int(wrapper.get("page_number") or 0)
        task_id = str(wrapper.get("task_id") or "")
        task_type = str(wrapper.get("task_type") or "")
        provider = wrapper.get("selected_provider")
        prediction = wrapper.get("selected_canonical")
        if not isinstance(prediction, Mapping):
            prediction = {}

        def reject(reason: str, text: str | None = None, kind: str | None = None) -> None:
            diagnostics.append(RecoveredHeadingDiagnostic(
                page, task_id, str(provider) if provider else None,
                text, kind, "REJECTED", reason,
            ))

        if task_type != "PAGE_FALLBACK":
            reject("not_whole_page_fallback")
            continue
        if wrapper.get("terminal_fallback_applied"):
            reject("terminal_fallback")
            continue
        if page not in ownership:
            reject("native_page_missing")
            continue
        if ownership[page] is not None:
            reject("native_section_already_owned")
            continue
        if not provider or not prediction:
            reject("no_selected_prediction")
            continue

        source = prediction.get("source_artifacts") or {}
        source_reference = str(source.get("task_result")) if isinstance(source, Mapping) and source.get("task_result") else None
        reference = (
            prediction_references.get(task_id)
            if prediction_references is not None
            else wrapper.get("prediction_reference")
        )
        prediction_reference = str(reference) if reference else None
        text_channel = prediction.get("text") or {}
        source_format = str(text_channel.get("source_format") or "") if isinstance(text_channel, Mapping) else ""
        blocks = _items(prediction.get("reading_blocks"))
        spatial = prediction.get("spatial_text") or {}
        spatial_items = _items(spatial)
        has_structure = bool(blocks or spatial_items)

        heading_block_count = 0
        for block_index, block in enumerate(blocks):
            if block.get("kind") != "heading":
                continue
            heading_block_count += 1
            value = block.get("text")
            if not isinstance(value, str) or not value.strip():
                reject("empty_heading_block", None, "EXPLICIT_HEADING_BLOCK")
                continue
            kind = "MARKDOWN_HEADING" if source_format == "markdown" else "EXPLICIT_HEADING_BLOCK"
            candidates.append(RecoveredHeadingCandidate(
                page_number=page, text=value, task_id=task_id, task_type=task_type,
                provider=str(provider), evidence_kind=kind,
                source_reference=source_reference, prediction_reference=prediction_reference,
                provider_confidence=_confidence(block.get("confidence")), raw_bbox=None,
                bbox_coordinate_space=None, block_index=block_index,
                signals={"original_kind": "heading", "level": block.get("level"),
                         "block_id": block.get("block_id"),
                         "origin": "provider_markdown_via_normalizer" if kind == "MARKDOWN_HEADING" else "provider_structured_block"},
                score=0.7, status="CANDIDATE",
            ))
        if blocks and not heading_block_count:
            reject("no_heading_block")

        if spatial_items:
            coordinate_system = spatial.get("coordinate_system") if isinstance(spatial, Mapping) else None
            if coordinate_system != "provider_image_pixels":
                reject("unsupported_coordinate_space", kind="OCR_VISUAL_LINE")
                continue
            valid = [(item, box) for item in spatial_items if (box := _bbox(item)) is not None]
            if not valid:
                reject("invalid_spatial_geometry", kind="OCR_VISUAL_LINE")
                continue
            heights = [box["bottom"] - box["top"] for _, box in valid]
            median_height = statistics.median(heights)
            left = min(box["x0"] for _, box in valid)
            right = max(box["x1"] for _, box in valid)
            top = min(box["top"] for _, box in valid)
            bottom = max(box["bottom"] for _, box in valid)
            width = max(right - left, 1.0)
            span = max(bottom - top, 1.0)
            for item, box in valid:
                value = item.get("text")
                if not isinstance(value, str) or not value.strip():
                    reject("empty_spatial_text", kind="OCR_VISUAL_LINE")
                    continue
                confidence = _confidence(item.get("confidence"))
                relative_height = (box["bottom"] - box["top"]) / median_height
                top_position = (box["top"] - top) / span
                center_offset = abs((box["x0"] + box["x1"]) / 2 - (left + right) / 2) / width
                signals = {
                    "relative_line_height": round(relative_height, 4),
                    "top_in_observed_ocr_extent": round(top_position, 4),
                    "center_offset_in_observed_ocr_extent": round(center_offset, 4),
                    "observed_ocr_line_count": len(valid),
                    "relative_coordinate_basis": spatial.get("relative_coordinate_basis"),
                }
                reason = None
                if confidence is not None and confidence < 0.8:
                    reason = "low_confidence"
                elif len(value.strip()) < 3 or len(value.strip()) > 80:
                    reason = "fragment_or_dense_line"
                elif not (top_position <= 0.35 and relative_height >= 1.2
                          and (center_offset <= 0.22 or relative_height >= 1.5)):
                    reason = "not_visually_prominent"
                if reason:
                    reject(reason, value, "OCR_VISUAL_LINE")
                    continue
                candidates.append(RecoveredHeadingCandidate(
                    page_number=page, text=value, task_id=task_id, task_type=task_type,
                    provider=str(provider), evidence_kind="OCR_VISUAL_LINE",
                    source_reference=source_reference, prediction_reference=prediction_reference,
                    provider_confidence=confidence, raw_bbox=box,
                    bbox_coordinate_space="PROVIDER_INPUT_IMAGE", block_index=None,
                    signals=signals,
                    score=round(min(0.69, 0.25 + 0.12 * relative_height
                                    + 0.12 * (1 - top_position) + 0.12 * (1 - center_offset)), 4),
                    status="CANDIDATE",
                ))
        if not has_structure:
            reject("no_structural_heading_evidence")

    return RecoveredHeadingReport(tuple(candidates), tuple(diagnostics))


def diagnose_recovered_heading_candidates(
    native_flow_path: Path,
    selected_index_path: Path,
    selected_predictions_dir: Path,
) -> RecoveredHeadingReport:
    """Read existing artifacts for a development review; never write output."""
    native_flow = json.loads(Path(native_flow_path).read_text(encoding="utf-8"))
    index = json.loads(Path(selected_index_path).read_text(encoding="utf-8"))
    selected_dir = Path(selected_predictions_dir)
    wrappers = []
    for item in index["items"]:
        path = selected_dir / f"{item['task_id']}.json"
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        wrapper["prediction_reference"] = str(path)
        wrappers.append(wrapper)
    return extract_recovered_heading_candidates(native_flow, wrappers)
