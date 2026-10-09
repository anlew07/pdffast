"""Add confirmed document coverage as an independent Canonical dimension."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping

from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates
from pdffast.structure_reconciliation.anchor_admission import (
    DocumentAnchorAdmissionDecision, admit_recovered_document_anchors,
)
from pdffast.structure_reconciliation.coverage import DocumentCoverageResult, resolve_document_coverages
from pdffast.structure_reconciliation.document_units import create_document_units
from pdffast.structure_reconciliation.heading_candidates import (
    diagnose_recovered_heading_candidates, extract_recovered_heading_candidates,
)
from pdffast.structure_reconciliation.page_relations import decide_page_relations
from pdffast.structure_reconciliation.preview import preview_reconciled_structure


DOCUMENT_UNIT_SCHEMA_VERSION = "1.1"


def resolve_document_units_from_artifacts(
    native_structure_path: Path,
    native_flow_path: Path,
    selected_index_path: Path,
    selected_predictions_dir: Path,
    *,
    selected_index: Mapping[str, Any] | None = None,
    selected_predictions: Iterable[Mapping[str, Any]] | None = None,
    native_structure: Mapping[str, Any] | None = None,
    native_flow: Mapping[str, Any] | None = None,
) -> tuple[tuple[DocumentCoverageResult, ...], tuple[DocumentAnchorAdmissionDecision, ...]]:
    """Derive admitted document coverage from the existing, read-only evidence chain."""
    native_structure = native_structure if native_structure is not None else json.loads(Path(native_structure_path).read_text(encoding="utf-8"))
    native_flow = native_flow if native_flow is not None else json.loads(Path(native_flow_path).read_text(encoding="utf-8"))
    if (selected_index is None) != (selected_predictions is None):
        raise ValueError("selected_index and selected_predictions must be supplied together")
    if selected_index is None:
        headings = diagnose_recovered_heading_candidates(
            native_flow_path, selected_index_path, selected_predictions_dir,
        )
    else:
        references = {
            str(item["task_id"]): str(Path(selected_predictions_dir) / f"{item['task_id']}.json")
            for item in selected_index["items"]
        }
        headings = extract_recovered_heading_candidates(
            native_flow, selected_predictions, prediction_references=references,
        )
    proposals = adjudicate_recovered_heading_candidates(headings.candidates, native_flow=native_flow)
    preview = preview_reconciled_structure(native_structure, proposals.proposals)
    admissions = admit_recovered_document_anchors(preview, proposals.proposals, headings.candidates)
    units = create_document_units(preview, admissions=admissions)
    relations = decide_page_relations(preview)
    coverage = resolve_document_coverages(units, relations, page_count=int(native_structure["page_count"]))
    return coverage, admissions


def with_document_units(
    canonical: Mapping[str, Any],
    coverage: Iterable[DocumentCoverageResult],
    admissions: Iterable[DocumentAnchorAdmissionDecision],
) -> dict[str, Any]:
    """Publish only admitted, covered units; preserve all existing content fields."""
    admitted = {
        item.anchor_ref: item for item in admissions
        if item.status == "ANCHOR_CONFIRMED" and item.anchor_ref
    }
    output = deepcopy(dict(canonical))
    output["schema_version"] = DOCUMENT_UNIT_SCHEMA_VERSION
    items = []
    for result in coverage:
        unit = result.unit
        if (unit.source != "RECOVERED" or unit.anchor_status != "ANCHOR_CONFIRMED"
                or unit.range_status not in {"PARTIAL", "RESOLVED"}
                or unit.page_range is None):
            continue
        admission = admitted.get(unit.anchor_ref)
        if (admission is None or admission.page_number != unit.anchor_page
                or admission.candidate_refs != unit.evidence_refs):
            continue
        items.append({
            "document_id": unit.document_id,
            "role": unit.role,
            "source": unit.source,
            "anchor": {
                "page": unit.anchor_page,
                "title_parts": list(unit.title_parts),
                "anchor_ref": unit.anchor_ref,
                "candidate_refs": list(unit.evidence_refs),
                "evidence_refs": list(admission.evidence_refs),
                "bbox_coordinate_space": admission.bbox_coordinate_space,
            },
            "anchor_status": unit.anchor_status,
            "range_status": unit.range_status,
            "page_range": {"start_page": unit.page_range[0], "end_page": unit.page_range[1]},
            "coverage_evidence_refs": list(result.used_evidence_refs),
        })
    output["document_units"] = sorted(items, key=lambda item: (item["anchor"]["page"], item["document_id"]))
    validate_document_units(output)
    return output


def validate_document_units(canonical: Mapping[str, Any]) -> None:
    """Validate the additive document-unit shape without assigning ownership."""
    if canonical.get("schema_version") != DOCUMENT_UNIT_SCHEMA_VERSION:
        raise ValueError("document_units require Canonical schema 1.1")
    items = canonical.get("document_units")
    if not isinstance(items, list):
        raise ValueError("document_units must be an array")
    page_count = int(canonical.get("page_count") or 0)
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("document unit must be an object")
        document_id = item.get("document_id")
        if not isinstance(document_id, str) or not document_id or document_id in seen:
            raise ValueError("document unit ID missing or duplicated")
        seen.add(document_id)
        if item.get("source") != "RECOVERED" or item.get("role") not in {"PRIMARY", "ATTACHED", "UNKNOWN"}:
            raise ValueError("invalid document unit source or role")
        if item.get("anchor_status") != "ANCHOR_CONFIRMED" or item.get("range_status") not in {"PARTIAL", "RESOLVED"}:
            raise ValueError("unconfirmed document unit cannot be published")
        anchor = item.get("anchor")
        if not isinstance(anchor, dict) or not isinstance(anchor.get("page"), int):
            raise ValueError("document anchor page missing")
        page = anchor["page"]
        if not 1 <= page <= page_count:
            raise ValueError("document anchor page outside PDF")
        if (not isinstance(anchor.get("title_parts"), list)
                or not all(isinstance(part, str) and part for part in anchor["title_parts"])
                or not isinstance(anchor.get("anchor_ref"), str)
                or not anchor["anchor_ref"]):
            raise ValueError("document anchor title or reference missing")
        for key in ("candidate_refs", "evidence_refs"):
            if not isinstance(anchor.get(key), list) or not anchor[key] or not all(isinstance(ref, str) and ref for ref in anchor[key]):
                raise ValueError(f"document anchor {key} missing")
        if anchor.get("bbox_coordinate_space") != "PROVIDER_INPUT_IMAGE":
            raise ValueError("document anchor coordinate space missing")
        span = item.get("page_range")
        if not isinstance(span, dict):
            raise ValueError("document coverage span missing")
        start, end = span.get("start_page"), span.get("end_page")
        if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= page <= end <= page_count:
            raise ValueError("invalid document coverage span")
        refs = item.get("coverage_evidence_refs")
        if not isinstance(refs, list) or not all(isinstance(ref, str) and ref for ref in refs):
            raise ValueError("invalid coverage evidence refs")
