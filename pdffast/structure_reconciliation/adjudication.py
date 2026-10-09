"""Turn recovered heading candidates into non-authoritative structure proposals.

This module consumes E4B candidates. It neither reads Provider output again nor
changes Native ownership, page ranges, Canonical, or rendered documents.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .heading_candidates import RecoveredHeadingCandidate


@dataclass(frozen=True)
class RecoveredSectionProposal:
    proposal_id: str
    page_number: int
    title_parts: tuple[str, ...]
    candidate_refs: tuple[str, ...]
    suggested_role: str
    evidence_kinds: tuple[str, ...]
    providers: tuple[str, ...]
    task_ids: tuple[str, ...]
    signals: dict[str, Any]
    conflicts: tuple[str, ...]
    structure_strength: str
    decision: str
    reason: str


@dataclass(frozen=True)
class CandidateJudgment:
    candidate_ref: str
    page_number: int
    text: str
    evidence_kind: str
    proposal_id: str
    decision: str
    reason: str


@dataclass(frozen=True)
class RecoveredStructureReport:
    proposals: tuple[RecoveredSectionProposal, ...]
    candidate_judgments: tuple[CandidateJudgment, ...]


@dataclass(frozen=True)
class _Entry:
    ref: str
    candidate: RecoveredHeadingCandidate


def _text_key(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _signal(candidate: RecoveredHeadingCandidate, key: str, default: float = 0.0) -> float:
    value = candidate.signals.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _order(entry: _Entry) -> tuple[int, float, str]:
    candidate = entry.candidate
    if candidate.raw_bbox:
        return (0, float(candidate.raw_bbox["top"]), entry.ref)
    return (1, float(candidate.block_index or 0), entry.ref)


def _can_combine(first: _Entry, second: _Entry) -> bool:
    a, b = first.candidate, second.candidate
    if a.evidence_kind != "OCR_VISUAL_LINE" or b.evidence_kind != "OCR_VISUAL_LINE":
        return False
    if a.task_id != b.task_id or a.bbox_coordinate_space != b.bbox_coordinate_space:
        return False
    if a.bbox_coordinate_space != "PROVIDER_INPUT_IMAGE" or not a.raw_bbox or not b.raw_bbox:
        return False
    heights = [float(box["bottom"]) - float(box["top"]) for box in (a.raw_bbox, b.raw_bbox)]
    if any(height <= 0 for height in heights):
        return False
    gap = float(b.raw_bbox["top"]) - float(a.raw_bbox["bottom"])
    if not (-0.15 * min(heights) <= gap <= 1.5 * min(heights)):
        return False
    for candidate, height in ((a, heights[0]), (b, heights[1])):
        width = float(candidate.raw_bbox["x1"]) - float(candidate.raw_bbox["x0"])
        if width / height < 1.3:
            return False
        if _signal(candidate, "top_in_observed_ocr_extent", 1) > .30:
            return False
        if _signal(candidate, "center_offset_in_observed_ocr_extent", 1) > .12:
            return False
        if not 1.2 <= _signal(candidate, "relative_line_height") <= 4:
            return False
    return True


def _rejection_reason(
    candidate: RecoveredHeadingCandidate,
    *,
    owner: str | None,
    owner_known: bool,
    repeated_pages: int,
) -> str | None:
    if not owner_known:
        return "native_page_missing"
    if owner is not None:
        return "reliable_native_section"
    if candidate.task_type != "PAGE_FALLBACK":
        return "not_whole_page_fallback"
    text = candidate.text.strip()
    if not text or re.fullmatch(r"\d+(?:\s*[/.-]\s*\d+)?", text):
        return "page_number_or_empty_fragment"
    if candidate.evidence_kind != "OCR_VISUAL_LINE":
        if (len(text) >= 30 and any(mark in text for mark in ("，", ","))
                and text.endswith(("。", "."))
                and int(candidate.signals.get("level") or 0) >= 2):
            return "provider_heading_body_like_sentence"
        return None
    height = _signal(candidate, "relative_line_height")
    position = _signal(candidate, "top_in_observed_ocr_extent")
    center = _signal(candidate, "center_offset_in_observed_ocr_extent")
    if len(_text_key(text)) <= 12 and repeated_pages >= 3 and (
        height >= 4 or position >= .30 or center >= .3
    ):
        return "repeated_page_decoration"
    if text.isascii() and text.isupper() and len(text) <= 6 and center > .25:
        return "corner_mark_or_logo"
    if (len(text) <= 4 and _signal(candidate, "observed_ocr_line_count") >= 40
            and height < 1.4 and center > .12):
        return "short_field_or_interface_fragment"
    if (text.endswith((":", "：")) and len(text) <= 15) or (
        re.match(r"^[^:：]{2,12}[:：]", text) and position > .25
    ):
        return "field_label_or_salutation"
    if len(text) > 75 and position > .20 and height < 1.35:
        return "body_like_line"
    return None


def _role(group: list[_Entry]) -> str:
    if len(group) > 1:
        return "DOCUMENT_BOUNDARY_CANDIDATE"
    candidate = group[0].candidate
    if candidate.evidence_kind in {"MARKDOWN_HEADING", "EXPLICIT_HEADING_BLOCK"}:
        if int(candidate.signals.get("level") or 0) >= 2:
            return "LOCAL_HEADING"
        if candidate.block_index == 0:
            return "DOCUMENT_BOUNDARY_CANDIDATE"
        return "UNKNOWN"
    if (_signal(candidate, "top_in_observed_ocr_extent", 1) <= .20
            and _signal(candidate, "center_offset_in_observed_ocr_extent", 1) <= .12):
        return "DOCUMENT_BOUNDARY_CANDIDATE"
    return "UNKNOWN"


def adjudicate_recovered_heading_candidates(
    candidates: Iterable[RecoveredHeadingCandidate],
    *,
    native_flow: Mapping[str, Any],
) -> RecoveredStructureReport:
    """Propose anchors from E4B evidence without assigning any page ownership."""
    ownership = {
        int(page["page_number"]): page.get("section_id")
        for page in native_flow.get("page_index", [])
        if isinstance(page, Mapping) and page.get("page_number") is not None
    }
    entries_by_page: dict[int, list[_Entry]] = defaultdict(list)
    text_pages: dict[str, set[int]] = defaultdict(set)
    for index, candidate in enumerate(candidates):
        ref = f"p{candidate.page_number:04d}:{candidate.task_id}:{index:04d}"
        entries_by_page[candidate.page_number].append(_Entry(ref, candidate))
        text_pages[_text_key(candidate.text)].add(candidate.page_number)

    proposals: list[RecoveredSectionProposal] = []
    judgments: list[CandidateJudgment] = []
    candidate_pages = set(entries_by_page)

    for page, page_entries in sorted(entries_by_page.items()):
        rejected: list[tuple[_Entry, str]] = []
        viable: list[_Entry] = []
        owner = ownership.get(page)
        for entry in sorted(page_entries, key=_order):
            reason = _rejection_reason(
                entry.candidate, owner=owner, owner_known=page in ownership,
                repeated_pages=len(text_pages[_text_key(entry.candidate.text)]),
            )
            if reason:
                rejected.append((entry, reason))
            else:
                viable.append(entry)

        groups: list[list[_Entry]] = []
        for entry in viable:
            if groups and _can_combine(groups[-1][-1], entry):
                groups[-1].append(entry)
            else:
                groups.append([entry])
        competing = len(groups) > 1 and any(len(group) > 1 for group in groups)
        # Two unrelated single candidates on one page are also a conflict unless
        # they are an obvious provider-reported hierarchy (level 1 + level 2).
        if len(groups) > 1 and all(group[0].candidate.evidence_kind == "OCR_VISUAL_LINE" for group in groups):
            competing = True
        if len(groups) > 1 and sum(
            group[0].candidate.evidence_kind in {"MARKDOWN_HEADING", "EXPLICIT_HEADING_BLOCK"}
            and int(group[0].candidate.signals.get("level") or 0) == 1
            for group in groups
        ) > 1:
            competing = True

        planned: list[tuple[list[_Entry], str | None]] = [([entry], reason) for entry, reason in rejected]
        planned.extend((group, None) for group in groups)
        planned.sort(key=lambda item: _order(item[0][0]))

        for number, (group, rejected_reason) in enumerate(planned, 1):
            proposal_id = f"recovered:p{page:04d}:{number:02d}"
            if rejected_reason:
                decision, reason, strength = "REJECTED", rejected_reason, "NONE"
            elif len(group) > 1 and not competing:
                decision, reason, strength = "ACCEPTED_PROPOSAL", "adjacent_visual_title_lines", "STRONG"
            elif competing:
                decision, reason, strength = "AMBIGUOUS", "competing_nonadjacent_candidates", "INSUFFICIENT"
            elif group[0].candidate.evidence_kind in {"MARKDOWN_HEADING", "EXPLICIT_HEADING_BLOCK"}:
                decision, reason, strength = "AMBIGUOUS", "provider_heading_without_independent_boundary_evidence", "INSUFFICIENT"
            else:
                decision, reason, strength = "AMBIGUOUS", "single_visual_line_without_boundary_evidence", "INSUFFICIENT"

            conflicts = (f"reliable_native_section:{owner}",) if rejected_reason == "reliable_native_section" else (
                ("competing_nonadjacent_candidates",) if competing and not rejected_reason else ()
            )
            proposal = RecoveredSectionProposal(
                proposal_id=proposal_id, page_number=page,
                title_parts=tuple(entry.candidate.text for entry in group),
                candidate_refs=tuple(entry.ref for entry in group),
                suggested_role=_role(group) if not rejected_reason else "UNKNOWN",
                evidence_kinds=tuple(dict.fromkeys(entry.candidate.evidence_kind for entry in group)),
                providers=tuple(dict.fromkeys(entry.candidate.provider for entry in group)),
                task_ids=tuple(dict.fromkeys(entry.candidate.task_id for entry in group)),
                signals={
                    "candidate_count": len(group),
                    "previous_native_owner": ownership.get(page - 1),
                    "next_native_owner": ownership.get(page + 1),
                    "adjacent_recovered_candidate_pages": tuple(
                        neighbor for neighbor in (page - 1, page + 1) if neighbor in candidate_pages
                    ),
                    "same_text_page_count": max(len(text_pages[_text_key(entry.candidate.text)]) for entry in group),
                    "provider_heading_is_evidence_only": any(
                        entry.candidate.evidence_kind in {"MARKDOWN_HEADING", "EXPLICIT_HEADING_BLOCK"}
                        for entry in group
                    ),
                },
                conflicts=conflicts, structure_strength=strength,
                decision=decision, reason=reason,
            )
            proposals.append(proposal)
            judgments.extend(CandidateJudgment(
                candidate_ref=entry.ref, page_number=page, text=entry.candidate.text,
                evidence_kind=entry.candidate.evidence_kind, proposal_id=proposal_id,
                decision=decision, reason=reason,
            ) for entry in group)

    return RecoveredStructureReport(tuple(proposals), tuple(judgments))
