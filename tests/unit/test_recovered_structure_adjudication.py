"""A recovered proposal is a review decision, never a Canonical section."""

from copy import deepcopy
from dataclasses import replace

from pdffast.structure_reconciliation.heading_candidates import RecoveredHeadingCandidate
from pdffast.structure_reconciliation.adjudication import adjudicate_recovered_heading_candidates


def _native(*owners: str | None) -> dict:
    return {"page_index": [
        {"page_number": page, "section_id": owner}
        for page, owner in enumerate(owners, 1)
    ], "sections": [{"section_id": owner} for owner in owners if owner]}


def _ocr(page: int, text: str, *, top: float = 100, height: float = 42,
         x0: float = 200, x1: float = 800, relative_top: float = .04,
         center_offset: float = .03, relative_height: float = 1.5,
         confidence: float = .99) -> RecoveredHeadingCandidate:
    return RecoveredHeadingCandidate(
        page_number=page, text=text, task_id=f"page-{page}", task_type="PAGE_FALLBACK",
        provider="fixture", evidence_kind="OCR_VISUAL_LINE", source_reference="raw.json",
        prediction_reference="selected.json", provider_confidence=confidence,
        raw_bbox={"x0": x0, "top": top, "x1": x1, "bottom": top + height},
        bbox_coordinate_space="PROVIDER_INPUT_IMAGE", block_index=None,
        signals={"relative_line_height": relative_height,
                 "top_in_observed_ocr_extent": relative_top,
                 "center_offset_in_observed_ocr_extent": center_offset,
                 "observed_ocr_line_count": 30}, score=.65,
    )


def _heading(page: int, text: str, *, block_index: int = 0, level: int = 1,
             kind: str = "MARKDOWN_HEADING") -> RecoveredHeadingCandidate:
    return RecoveredHeadingCandidate(
        page_number=page, text=text, task_id=f"page-{page}", task_type="PAGE_FALLBACK",
        provider="fixture", evidence_kind=kind, source_reference="raw.json",
        prediction_reference="selected.json", provider_confidence=.999,
        raw_bbox=None, bbox_coordinate_space=None, block_index=block_index,
        signals={"level": level, "original_kind": "heading"}, score=.7,
    )


def test_repeated_page_decoration_is_rejected_without_literal_rule() -> None:
    native = _native(None, None, None)
    items = [_ocr(p, "正式版", relative_top=.33, relative_height=11) for p in (1, 2, 3)]
    report = adjudicate_recovered_heading_candidates(items, native_flow=native)
    assert len(report.proposals) == 3
    assert all(p.decision == "REJECTED" and p.reason == "repeated_page_decoration" for p in report.proposals)


def test_high_ocr_confidence_alone_does_not_accept_structure() -> None:
    high = adjudicate_recovered_heading_candidates(
        [_ocr(1, "可能是标题", confidence=.99999)], native_flow=_native(None),
    ).proposals[0]
    lower = adjudicate_recovered_heading_candidates(
        [_ocr(1, "可能是标题", confidence=.81)], native_flow=_native(None),
    ).proposals[0]
    assert high.decision == lower.decision == "AMBIGUOUS"
    assert high.structure_strength == lower.structure_strength == "INSUFFICIENT"


def test_adjacent_title_lines_form_one_ordered_composite_proposal() -> None:
    first = _ocr(1, "陕西省教育厅服务地方专项计划项目", top=324, height=41, x0=530, x1=1064)
    second = _ocr(1, "合同书", top=382, height=46, x0=691, x1=904, relative_top=.03)
    report = adjudicate_recovered_heading_candidates([first, second], native_flow=_native(None))
    assert len(report.proposals) == 1
    proposal = report.proposals[0]
    assert proposal.decision == "ACCEPTED_PROPOSAL"
    assert proposal.title_parts == (first.text, second.text)
    assert proposal.suggested_role == "DOCUMENT_BOUNDARY_CANDIDATE"
    assert len(proposal.candidate_refs) == 2
    assert len(report.candidate_judgments) == 2
    assert len({j.proposal_id for j in report.candidate_judgments}) == 1


def test_provider_heading_requires_additional_structure_evidence() -> None:
    report = adjudicate_recovered_heading_candidates(
        [_heading(1, "一篇论文的实际标题")], native_flow=_native(None),
    )
    assert report.proposals[0].decision == "AMBIGUOUS"
    assert report.proposals[0].suggested_role in {"DOCUMENT_BOUNDARY_CANDIDATE", "UNKNOWN"}
    assert report.proposals[0].reason == "provider_heading_without_independent_boundary_evidence"


def test_recovered_proposal_cannot_override_native_section() -> None:
    native = _native("native-1")
    original = deepcopy(native)
    report = adjudicate_recovered_heading_candidates(
        [_ocr(1, "恢复的标题")], native_flow=native,
    )
    assert report.proposals[0].decision == "REJECTED"
    assert report.proposals[0].conflicts == ("reliable_native_section:native-1",)
    assert native == original


def test_competing_nonadjacent_candidates_remain_ambiguous() -> None:
    report = adjudicate_recovered_heading_candidates([
        _ocr(1, "第一处疑似标题", top=50),
        _ocr(1, "另一处疑似标题", top=600, relative_top=.28),
    ], native_flow=_native(None))
    assert len(report.proposals) == 2
    assert all(p.decision == "AMBIGUOUS" for p in report.proposals)
    assert all("competing_nonadjacent_candidates" in p.conflicts for p in report.proposals)


def test_repeated_same_title_on_two_pages_remains_independent() -> None:
    report = adjudicate_recovered_heading_candidates([
        _ocr(1, "陕西省科学技术奖"), _ocr(2, "陕西省科学技术奖"),
    ], native_flow=_native(None, None))
    assert len(report.proposals) == 2
    assert len({p.proposal_id for p in report.proposals}) == 2
    assert all(p.decision == "AMBIGUOUS" for p in report.proposals)


def test_proposal_preserves_original_candidate_text() -> None:
    parts = [_ocr(1, " 原文第一行 ", top=100), _ocr(1, "原文／第二行", top=150, relative_top=.1)]
    report = adjudicate_recovered_heading_candidates(parts, native_flow=_native(None))
    assert report.proposals[0].title_parts == (" 原文第一行 ", "原文／第二行")


def test_local_heading_is_not_promoted_to_document_boundary() -> None:
    report = adjudicate_recovered_heading_candidates([
        _heading(1, "I. INTRODUCTION", block_index=5, level=2),
    ], native_flow=_native(None))
    assert report.proposals[0].decision == "AMBIGUOUS"
    assert report.proposals[0].suggested_role == "LOCAL_HEADING"


def test_short_field_label_in_dense_ocr_is_rejected() -> None:
    candidate = replace(_ocr(1, "单位名称", relative_top=.11, relative_height=1.3,
                             center_offset=.14),
                        signals={"relative_line_height": 1.3,
                                 "top_in_observed_ocr_extent": .11,
                                 "center_offset_in_observed_ocr_extent": .14,
                                 "observed_ocr_line_count": 73})
    report = adjudicate_recovered_heading_candidates([candidate], native_flow=_native(None))
    assert report.proposals[0].decision == "REJECTED"
    assert report.proposals[0].reason == "short_field_or_interface_fragment"


def test_conflicting_provider_heading_blocks_are_explicitly_ambiguous() -> None:
    first = _heading(1, "第一个候选", block_index=0)
    second = replace(_heading(1, "不同的候选", block_index=0), provider="other_provider", task_id="other-task")
    report = adjudicate_recovered_heading_candidates([first, second], native_flow=_native(None))
    assert len(report.proposals) == 2
    assert all(p.decision == "AMBIGUOUS" for p in report.proposals)
    assert all("competing_nonadjacent_candidates" in p.conflicts for p in report.proposals)


def test_provider_heading_that_is_a_body_sentence_is_rejected() -> None:
    text = "为N张连续帧中面部ROI的差，外观分支则直接将当前帧中面部ROI作为输入。"
    report = adjudicate_recovered_heading_candidates([
        _heading(1, text, block_index=4, level=2),
    ], native_flow=_native(None))
    assert report.proposals[0].decision == "REJECTED"
    assert report.proposals[0].reason == "provider_heading_body_like_sentence"


def test_adjudication_does_not_write_canonical(tmp_path) -> None:
    canonical = tmp_path / "canonical_document.json"
    canonical.write_bytes(b'{"sections": ["native-only"]}')
    before = canonical.read_bytes()
    adjudicate_recovered_heading_candidates([_ocr(1, "标题")], native_flow=_native(None))
    assert canonical.read_bytes() == before
