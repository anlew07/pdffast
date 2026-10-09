"""Resolve confirmed page intersection spans without assigning content ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .document_units import DocumentUnit
from .page_relations import PageRelationDecision


@dataclass(frozen=True)
class DocumentCoverageResult:
    unit: DocumentUnit
    left_extent: str
    right_extent: str
    left_stop_reason: str
    right_stop_reason: str
    used_evidence_refs: tuple[str, ...]


def _walk(
    anchor_page: int,
    direction: int,
    page_count: int,
    edges: dict[tuple[int, int], PageRelationDecision],
) -> tuple[int, str, str, tuple[str, ...]]:
    page = anchor_page
    refs: list[str] = []
    while True:
        if page == (1 if direction < 0 else page_count):
            return page, "CLOSED", "BOF" if direction < 0 else "EOF", tuple(refs)
        left, right = (page - 1, page) if direction < 0 else (page, page + 1)
        edge = edges.get((left, right))
        if edge is None:
            return page, "OPEN", "MISSING_EDGE", tuple(refs)
        refs.extend(edge.evidence_refs)
        if edge.decision == "CONTINUITY":
            page += direction
        elif edge.decision == "BOUNDARY":
            return page, "CLOSED", "BOUNDARY", tuple(refs)
        elif edge.decision == "CONFLICT":
            return page, "CONFLICT", "CONFLICT", tuple(refs)
        elif edge.decision == "INSUFFICIENT":
            return page, "OPEN", "INSUFFICIENT", tuple(refs)
        else:
            raise ValueError(f"unsupported page relation decision: {edge.decision}")


def resolve_document_coverages(
    units: Iterable[DocumentUnit],
    decisions: Iterable[PageRelationDecision],
    *,
    page_count: int,
) -> tuple[DocumentCoverageResult, ...]:
    """Expand admitted anchor seeds across continuity edges only.

    A range is a span of confirmed page intersections, never exclusive page
    or record ownership. The returned units are new frozen values; inputs stay
    unchanged. An unknown or conflicting edge stops that direction immediately.
    """
    if page_count < 1:
        raise ValueError("page_count must be positive")
    edges: dict[tuple[int, int], PageRelationDecision] = {}
    for edge in decisions:
        key = (edge.left_page, edge.right_page)
        if edge.right_page != edge.left_page + 1 or not (1 <= edge.left_page < edge.right_page <= page_count):
            raise ValueError("page relation edge is outside this PDF")
        if key in edges:
            raise ValueError(f"duplicate page relation edge: {key}")
        edges[key] = edge

    results = []
    for unit in units:
        if unit.source != "RECOVERED" or unit.anchor_status != "ANCHOR_CONFIRMED":
            results.append(DocumentCoverageResult(
                unit, "NOT_EVALUATED", "NOT_EVALUATED",
                "NO_ADMITTED_ANCHOR", "NO_ADMITTED_ANCHOR", (),
            ))
            continue
        if unit.anchor_page is None or not 1 <= unit.anchor_page <= page_count:
            raise ValueError("admitted anchor page is outside this PDF")
        left_page, left_extent, left_reason, left_refs = _walk(unit.anchor_page, -1, page_count, edges)
        right_page, right_extent, right_reason, right_refs = _walk(unit.anchor_page, 1, page_count, edges)
        status = "RESOLVED" if left_extent == right_extent == "CLOSED" else "PARTIAL"
        resolved_unit = replace(unit, range_status=status, page_range=(left_page, right_page))
        results.append(DocumentCoverageResult(
            resolved_unit, left_extent, right_extent, left_reason, right_reason,
            tuple(dict.fromkeys((*left_refs, *right_refs))),
        ))
    return tuple(results)
