"""Preview recovered anchors without rewriting Native or Canonical structure."""

from copy import deepcopy
from dataclasses import replace

from pdffast.structure_reconciliation.adjudication import RecoveredSectionProposal
from pdffast.structure_reconciliation.preview import (
    RecoveredDocumentAnchor,
    RecoveredSectionAnchor,
    preview_reconciled_structure,
)


def _native(*owners: str | None) -> dict:
    sections = [
        {"section_id": owner, "title": f"原生标题 {owner}", "start_page": page,
         "end_page": page, "anchor_page": page, "match_mode": "generic_native_heading"}
        for page, owner in enumerate(owners, 1) if owner
    ]
    unresolved = [
        {"region_type": "generic_region", "start_page": page, "end_page": page,
         "reason": "原生证据不足"}
        for page, owner in enumerate(owners, 1) if owner is None
    ]
    return {
        "source_file": "fixture.pdf", "page_count": len(owners),
        "sections": sections, "unresolved_regions": unresolved,
        "pages": [{"page_number": page, "section_id": owner,
                   "title": f"原生标题 {owner}" if owner else None}
                  for page, owner in enumerate(owners, 1)],
    }


def _proposal(page: int, *parts: str, proposal_id: str | None = None,
              decision: str = "ACCEPTED_PROPOSAL",
              role: str = "DOCUMENT_BOUNDARY_CANDIDATE",
              candidate_refs: tuple[str, ...] | None = None) -> RecoveredSectionProposal:
    return RecoveredSectionProposal(
        proposal_id=proposal_id or f"proposal-{page}", page_number=page,
        title_parts=parts, candidate_refs=candidate_refs or tuple(f"ref-{page}-{i}" for i in range(len(parts))),
        suggested_role=role, evidence_kinds=("OCR_VISUAL_LINE",), providers=("fixture",),
        task_ids=(f"task-{page}",), signals={}, conflicts=(), structure_strength="STRONG",
        decision=decision, reason="fixture",
    )


def test_native_structure_always_wins_conflict() -> None:
    native = _native("native-1")
    result = preview_reconciled_structure(native, [_proposal(1, "恢复标题")])
    assert result.native_sections == tuple(native["sections"])
    assert result.recovered_anchors == ()
    assert result.conflicts[0].reason == "native_ownership_wins"
    assert result.conflicts[0].native_section_id == "native-1"


def test_accepted_proposal_on_unresolved_page_forms_preview_anchor() -> None:
    result = preview_reconciled_structure(_native(None), [_proposal(1, "原文标题")])
    assert len(result.recovered_anchors) == 1
    anchor = result.recovered_anchors[0]
    assert anchor.page_number == 1
    assert anchor.source == "RECOVERED"
    assert anchor.proposal_id == "proposal-1"
    assert result.unresolved_pages_without_anchor == ()


def test_ambiguous_proposal_is_not_promoted() -> None:
    result = preview_reconciled_structure(
        _native(None), [_proposal(1, "待判标题", decision="AMBIGUOUS")],
    )
    assert result.recovered_anchors == ()
    assert result.ignored_proposals[0].reason == "proposal_not_accepted"
    assert result.unresolved_pages_without_anchor == (1,)


def test_rejected_proposal_is_not_promoted() -> None:
    result = preview_reconciled_structure(
        _native(None), [_proposal(1, "伪标题", decision="REJECTED")],
    )
    assert result.recovered_anchors == ()
    assert result.ignored_proposals[0].decision == "REJECTED"


def test_document_boundary_is_distinct_from_native_section() -> None:
    result = preview_reconciled_structure(_native(None), [_proposal(1, "附件标题")])
    assert isinstance(result.recovered_anchors[0], RecoveredDocumentAnchor)
    assert not isinstance(result.recovered_anchors[0], RecoveredSectionAnchor)
    assert result.recovered_anchors[0].anchor_kind == "recovered_document_anchor"
    assert result.recovered_anchors[0].suggested_role == "DOCUMENT_BOUNDARY_CANDIDATE"
    assert result.native_sections == ()


def test_section_candidate_forms_section_anchor_without_becoming_native_section() -> None:
    result = preview_reconciled_structure(_native(None), [
        _proposal(1, "PDF 中的章节", role="SECTION_CANDIDATE"),
    ])
    assert result.recovered_anchors[0].anchor_kind == "recovered_section_anchor"
    assert isinstance(result.recovered_anchors[0], RecoveredSectionAnchor)
    assert result.native_sections == ()
    assert result.native_pages[0]["section_id"] is None


def test_composite_proposal_stays_one_anchor_with_original_parts() -> None:
    result = preview_reconciled_structure(_native(None), [
        _proposal(1, "陕西省教育厅服务地方专项计划项目", "合同书", candidate_refs=("ref-a", "ref-b")),
    ])
    assert len(result.recovered_anchors) == 1
    assert result.recovered_anchors[0].original_text_parts == (
        "陕西省教育厅服务地方专项计划项目", "合同书",
    )
    assert result.recovered_anchors[0].candidate_refs == ("ref-a", "ref-b")


def test_same_title_on_different_pages_remains_independent() -> None:
    result = preview_reconciled_structure(_native(None, None), [
        _proposal(1, "通知", proposal_id="first"),
        _proposal(2, "通知", proposal_id="second"),
    ])
    assert [(a.page_number, a.proposal_id) for a in result.recovered_anchors] == [(1, "first"), (2, "second")]
    assert len({a.anchor_id for a in result.recovered_anchors}) == 2


def test_recovered_anchor_has_no_guessed_range() -> None:
    result = preview_reconciled_structure(_native(None, None, None), [_proposal(1, "附件封面")])
    anchor = result.recovered_anchors[0]
    assert anchor.range_status == "UNRESOLVED"
    assert anchor.page_range is None
    assert result.unresolved_pages_without_anchor == (2, 3)
    assert len(result.unresolved_regions) == 3


def test_same_unresolved_page_competing_proposals_are_conflicts() -> None:
    result = preview_reconciled_structure(_native(None), [
        _proposal(1, "甲", proposal_id="first"),
        _proposal(1, "乙", proposal_id="second"),
    ])
    assert result.recovered_anchors == ()
    assert result.conflicts[0].reason == "competing_accepted_proposals_same_page"
    assert result.conflicts[0].proposal_ids == ("first", "second")


def test_accepted_local_or_unknown_role_is_not_top_level_anchor() -> None:
    result = preview_reconciled_structure(_native(None, None), [
        _proposal(1, "页内标题", role="LOCAL_HEADING"),
        _proposal(2, "未定标题", role="UNKNOWN"),
    ])
    assert result.recovered_anchors == ()
    assert [item.reason for item in result.ignored_proposals] == ["role_not_anchor", "role_not_anchor"]


def test_duplicate_candidate_ref_cannot_back_two_anchors() -> None:
    result = preview_reconciled_structure(_native(None, None), [
        _proposal(1, "标题甲", candidate_refs=("shared-ref",)),
        _proposal(2, "标题乙", candidate_refs=("shared-ref",)),
    ])
    assert result.recovered_anchors == ()
    assert result.conflicts[0].reason == "competing_accepted_proposals_same_evidence"


def test_accepted_proposal_with_existing_conflict_is_not_promoted() -> None:
    proposal = replace(_proposal(1, "冲突标题"), conflicts=("competing_evidence",))
    result = preview_reconciled_structure(_native(None), [proposal])
    assert result.recovered_anchors == ()
    assert result.conflicts[0].reason == "proposal_evidence_conflict"


def test_preview_does_not_modify_native_structure() -> None:
    native = _native("native-1", None)
    before = deepcopy(native)
    preview_reconciled_structure(native, [_proposal(2, "恢复标题")])
    assert native == before


def test_preview_does_not_modify_canonical(tmp_path) -> None:
    canonical = tmp_path / "canonical_document.json"
    canonical.write_bytes(b'{"sections": ["native-only"]}')
    before = canonical.read_bytes()
    preview_reconciled_structure(_native(None), [_proposal(1, "恢复标题")])
    assert canonical.read_bytes() == before
