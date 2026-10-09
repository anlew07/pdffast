"""Coverage intersects pages; it never assigns page, record, or section ownership."""

from dataclasses import replace

from pdffast.structure_reconciliation.document_units import DocumentUnit, section_parent_map
from pdffast.structure_reconciliation.page_relations import PageRelationDecision
from pdffast.structure_reconciliation.coverage import resolve_document_coverages


def _unit(page: int, *, status: str = "ANCHOR_CONFIRMED") -> DocumentUnit:
    return DocumentUnit(
        document_id=f"document:p{page}", role="UNKNOWN", source="RECOVERED",
        anchor_ref=f"anchor:p{page}", anchor_page=page,
        title_parts=("标题",), evidence_refs=(f"candidate:p{page}",),
        range_status="UNRESOLVED", page_range=None, section_ids=(),
        anchor_status=status,
    )


def _edge(left: int, decision: str, ref: str | None = None) -> PageRelationDecision:
    return PageRelationDecision(
        left_page=left, right_page=left + 1, decision=decision,
        continuity_evidence=(), boundary_evidence=(), context_evidence=(),
        conflicts=(ref,) if decision == "CONFLICT" and ref else (),
        reason="fixture", evidence_refs=(ref or f"edge:{left}-{left + 1}",),
    )


def _resolved(unit: DocumentUnit, page_count: int, *edges: PageRelationDecision):
    return resolve_document_coverages((unit,), edges, page_count=page_count)[0]


def test_confirmed_anchor_seeds_coverage() -> None:
    result = _resolved(_unit(2), 3)
    assert result.unit.page_range == (2, 2)
    assert result.unit.range_status == "PARTIAL"


def test_proposed_anchor_does_not_seed_coverage() -> None:
    result = _resolved(_unit(2, status="PROPOSED"), 3, _edge(1, "BOUNDARY"), _edge(2, "BOUNDARY"))
    assert result.unit.range_status == "UNRESOLVED"
    assert result.unit.page_range is None


def test_continuity_expands_confirmed_span() -> None:
    result = _resolved(_unit(2), 4, _edge(1, "BOUNDARY"), _edge(2, "CONTINUITY"), _edge(3, "BOUNDARY"))
    assert result.unit.page_range == (2, 3)
    assert result.unit.range_status == "RESOLVED"


def test_boundary_closes_extent() -> None:
    result = _resolved(_unit(2), 3, _edge(1, "BOUNDARY"))
    assert result.left_extent == "CLOSED"
    assert result.left_stop_reason == "BOUNDARY"


def test_insufficient_stops_expansion_as_partial() -> None:
    result = _resolved(_unit(2), 4, _edge(1, "BOUNDARY"), _edge(2, "INSUFFICIENT"), _edge(3, "CONTINUITY"))
    assert result.unit.page_range == (2, 2)
    assert result.unit.range_status == "PARTIAL"
    assert result.right_extent == "OPEN"
    assert result.right_stop_reason == "INSUFFICIENT"


def test_conflict_stops_expansion_and_preserves_ref() -> None:
    result = _resolved(_unit(2), 3, _edge(1, "BOUNDARY"), _edge(2, "CONFLICT", "conflict:2-3"))
    assert result.unit.page_range == (2, 2)
    assert result.unit.range_status == "PARTIAL"
    assert result.right_extent == "CONFLICT"
    assert "conflict:2-3" in result.used_evidence_refs


def test_bof_can_close_left_extent() -> None:
    result = _resolved(_unit(1), 2, _edge(1, "INSUFFICIENT"))
    assert result.left_extent == "CLOSED"
    assert result.left_stop_reason == "BOF"


def test_eof_can_close_right_extent() -> None:
    result = _resolved(_unit(2), 2, _edge(1, "INSUFFICIENT"))
    assert result.right_extent == "CLOSED"
    assert result.right_stop_reason == "EOF"


def test_both_closed_extents_produce_resolved() -> None:
    result = _resolved(_unit(2), 3, _edge(1, "BOUNDARY"), _edge(2, "BOUNDARY"))
    assert result.unit.range_status == "RESOLVED"
    assert result.unit.page_range == (2, 2)


def test_one_unknown_extent_produces_partial() -> None:
    result = _resolved(_unit(2), 3, _edge(1, "BOUNDARY"), _edge(2, "INSUFFICIENT"))
    assert result.unit.range_status == "PARTIAL"
    assert result.unit.page_range == (2, 2)


def test_resolved_single_page_range_is_valid() -> None:
    result = _resolved(_unit(1), 1)
    assert result.unit.range_status == "RESOLVED"
    assert result.unit.page_range == (1, 1)
    assert (result.left_stop_reason, result.right_stop_reason) == ("BOF", "EOF")


def test_page_range_does_not_assign_records() -> None:
    records = [{"record_id": "one", "source_page": 1}, {"record_id": "two", "source_page": 1}]
    result = _resolved(_unit(1), 1)
    assert result.unit.page_range == (1, 1)
    assert all("document_id" not in record for record in records)


def test_page_range_does_not_assign_section_parent() -> None:
    result = _resolved(_unit(1), 1)
    assert result.unit.section_ids == ()
    assert section_parent_map((result.unit,)) == {}


def test_overlapping_document_ranges_are_not_semantically_forbidden() -> None:
    first = replace(_unit(2), range_status="RESOLVED", page_range=(2, 3))
    second = replace(_unit(3), range_status="RESOLVED", page_range=(3, 4))
    assert first.page_range[1] == second.page_range[0] == 3
    assert section_parent_map((first, second)) == {}


def test_resolution_preserves_edge_evidence_refs() -> None:
    result = _resolved(_unit(2), 3, _edge(1, "BOUNDARY", "left:anchor"), _edge(2, "INSUFFICIENT", "right:unknown"))
    assert result.used_evidence_refs == ("left:anchor", "right:unknown")


def test_same_input_produces_same_coverage_result() -> None:
    unit = _unit(2)
    edges = (_edge(1, "BOUNDARY"), _edge(2, "CONTINUITY"))
    assert _resolved(unit, 3, *edges) == _resolved(unit, 3, *edges)
