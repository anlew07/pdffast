"""Discover document sections from headings observed in the native PDF scan.

The numbered heading recognition and coherent sequence selection are retained from
the former generic section alignment path. No declared section inventory is used.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from statistics import median
from typing import Any


_CN_NUM = "一二三四五六七八九十百零〇"
_TOP_LEVEL_PATTERNS = (
    re.compile(rf"^\s*([{_CN_NUM}]+)\s*[、．.]\s*(\S.*?)\s*$"),
    re.compile(rf"^\s*第([{_CN_NUM}]+)章\s*(\S.*?)\s*$"),
)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
_INNER_PAGE_NUMBER_RE = re.compile(r"^\s*-\s*(\d+)\s*-\s*$")
_DECIMAL_ITEM_RE = re.compile(r"^\s*(\d+)\.\s*\d+")


def _ordinal(text: str) -> int | None:
    value = unicodedata.normalize("NFKC", text).strip()
    token = next((match.group(1) for pattern in _TOP_LEVEL_PATTERNS if (match := pattern.match(value))), None)
    if not token:
        return None
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100}
    total = current = 0
    for char in token:
        if char in digits:
            current = digits[char]
        elif char in units:
            total += (current or 1) * units[char]
            current = 0
        else:
            return None
    return total + current or None


def _observed_heading(page: dict[str, Any]) -> str | None:
    candidates = []
    for raw_line in str(page.get("native_text") or "").splitlines():
        line = raw_line.strip()
        if not line or _PAGE_NUMBER_RE.match(line):
            continue
        candidates.append(line)
        if len(candidates) >= 8:
            break
    for line in candidates:
        if len(line) <= 60 and _ordinal(line) is not None:
            return line
    return None


def _observed_visual_heading(page: dict[str, Any]) -> str | None:
    """Accept an unnumbered page title only with strong native layout evidence."""
    lines = [line.strip() for line in str(page.get("native_text") or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    title = lines[0]
    if not 4 <= len(title) <= 30 or sum("\u4e00" <= ch <= "\u9fff" for ch in title) < 4:
        return None
    if any(char in title for char in "。；：，,;:!?！？"):
        return None
    words = page.get("words") or []
    chars = page.get("chars") or []
    if not words or not chars or str(words[0].get("text") or "").strip() != title:
        return None
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    first = words[0]
    center = (float(first.get("x0") or 0) + float(first.get("x1") or 0)) / 2
    top = float(first.get("top") or 0)
    if abs(center - width / 2) > width * 0.12 or top > height * 0.2:
        return None
    title_sizes = [float(char.get("size") or 0) for char in chars if abs(float(char.get("top") or 0) - top) <= 3]
    body_sizes = [float(char.get("size") or 0) for char in chars if float(char.get("top") or 0) > top + 20 and float(char.get("size") or 0) < 40]
    if not title_sizes or not body_sizes or median(title_sizes) < median(body_sizes) * 1.25:
        return None
    return title


def _coherent_sequence(observed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the longest page and ordinal increasing chain (old generic heuristic)."""
    if len(observed) <= 1:
        return observed
    lengths = [1] * len(observed)
    previous = [-1] * len(observed)
    for index, item in enumerate(observed):
        for earlier in range(index):
            prior = observed[earlier]
            if prior["page_number"] >= item["page_number"] or prior["ordinal"] >= item["ordinal"]:
                continue
            if lengths[earlier] + 1 > lengths[index]:
                lengths[index] = lengths[earlier] + 1
                previous[index] = earlier
    end = max(range(len(observed)), key=lambda i: (lengths[i], observed[i]["ordinal"], -observed[i]["page_number"]))
    selected = []
    while end >= 0:
        selected.append(observed[end])
        end = previous[end]
    return list(reversed(selected))


def _standalone_numbered_divider(page: dict[str, Any], heading: str) -> bool:
    """Require layout evidence for a numbering restart, not just a new 一."""
    lines = [line.strip() for line in str(page.get("native_text") or "").splitlines() if line.strip()]
    words = page.get("words") or []
    chars = page.get("chars") or []
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    if not lines or lines[0] != heading or len(lines) > 8 or len(page.get("native_text") or "") > 160:
        return False
    if not words or not chars or width <= 0 or height <= 0 or str(words[0].get("text") or "").strip() != heading:
        return False
    first = words[0]
    center = (float(first.get("x0") or 0) + float(first.get("x1") or 0)) / 2
    top = float(first.get("top") or 0)
    title_sizes = [float(char.get("size") or 0) for char in chars if abs(float(char.get("top") or 0) - top) <= 3]
    return (
        abs(center - width / 2) <= width * 0.12
        and height * 0.25 <= top <= height * 0.6
        and bool(title_sizes)
        and median(title_sizes) >= 18
    )


def _heading_candidates(*, page_count: int, snapshot_pages: dict[int, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    numbered = []
    for page_number in range(1, page_count + 1):
        heading = _observed_heading(snapshot_pages.get(page_number, {}))
        if heading:
            numbered.append({"page_number": page_number, "heading": heading, "ordinal": _ordinal(heading)})

    contexts: list[list[dict[str, Any]]] = [[]]
    for candidate in numbered:
        previous = contexts[-1][-1] if contexts[-1] else None
        restart = (
            previous is not None
            and candidate["ordinal"] == 1
            and previous["ordinal"] > 1
            and _standalone_numbered_divider(snapshot_pages[candidate["page_number"]], candidate["heading"])
        )
        if restart:
            contexts.append([])
        candidate["sequence_context"] = len(contexts) - 1
        candidate["document_boundary"] = restart
        contexts[-1].append(candidate)

    selected = []
    diagnostics = []
    for context in contexts:
        accepted = {item["page_number"] for item in _coherent_sequence(context)}
        for candidate in context:
            is_accepted = candidate["page_number"] in accepted
            if is_accepted:
                selected.append(candidate)
            reason = (
                "numbering_restart_at_standalone_divider" if candidate["document_boundary"]
                else "numbering_sequence" if is_accepted
                else "numbering_reset_without_document_boundary" if candidate["ordinal"] == 1 and candidate["sequence_context"] == 0
                else "not_in_coherent_sequence"
            )
            diagnostics.append({
                "page": candidate["page_number"], "text": candidate["heading"],
                "number": candidate["ordinal"], "visual_score": None,
                "sequence_context": candidate["sequence_context"],
                "accepted": is_accepted, "reason": reason,
            })

    numbered_pages = {item["page_number"] for item in selected}
    for page_number in range(1, page_count + 1):
        if page_number in numbered_pages:
            continue
        heading = _observed_visual_heading(snapshot_pages.get(page_number, {}))
        if heading:
            selected.append({"page_number": page_number, "heading": heading, "ordinal": None, "document_boundary": False})
            diagnostics.append({
                "page": page_number, "text": heading, "number": None,
                "visual_score": "strong", "sequence_context": None,
                "accepted": True, "reason": "observed_visual_heading",
            })
    selected.sort(key=lambda item: item["page_number"])
    diagnostics.sort(key=lambda item: (item["page"], item["number"] is None))
    return selected, diagnostics


def diagnose_section_candidates(*, page_count: int, snapshot_pages: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return development diagnostics without changing the section artifact schema."""
    _, diagnostics = _heading_candidates(page_count=page_count, snapshot_pages=snapshot_pages)
    return diagnostics


def _page_evidence(page: dict[str, Any]) -> dict[str, Any]:
    lines = [line.strip() for line in str(page.get("native_text") or "").splitlines() if line.strip()]
    content = [line for line in lines if len(line) > 1 and not _PAGE_NUMBER_RE.match(line) and not _INNER_PAGE_NUMBER_RE.match(line)]
    outer = next((tuple(map(int, line.split("/"))) for line in reversed(lines) if _PAGE_NUMBER_RE.match(line)), None)
    inner = next((int(match.group(1)) for line in reversed(lines) if (match := _INNER_PAGE_NUMBER_RE.match(line))), None)
    item_number = next((int(match.group(1)) for line in content[:4] if (match := _DECIMAL_ITEM_RE.match(line))), None)
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    sizes = [float(char.get("size") or 0) for char in page.get("chars") or [] if 5 <= float(char.get("size") or 0) <= 40 and str(char.get("text") or "").strip()]
    image_cover = 0.0
    if width > 0 and height > 0:
        for image in page.get("images") or []:
            area = max(0.0, float(image.get("x1") or 0) - float(image.get("x0") or 0)) * max(0.0, float(image.get("bottom") or 0) - float(image.get("top") or 0))
            image_cover = max(image_cover, min(1.0, area / (width * height)))

    cover_like = False
    words = page.get("words") or []
    if content and len(content[0]) >= 4 and words and width > 0 and height > 0 and str(words[0].get("text") or "").strip() == content[0]:
        first = words[0]
        top = float(first.get("top") or 0)
        center = (float(first.get("x0") or 0) + float(first.get("x1") or 0)) / 2
        title_sizes = [float(char.get("size") or 0) for char in page.get("chars") or [] if abs(float(char.get("top") or 0) - top) <= 3]
        later_sizes = [float(char.get("size") or 0) for char in page.get("chars") or [] if float(char.get("top") or 0) > top + 30 and 5 <= float(char.get("size") or 0) <= 40]
        cover_like = (
            abs(center - width / 2) <= width * 0.12
            and height * 0.12 <= top <= height * 0.5
            and bool(title_sizes) and bool(later_sizes)
            and median(title_sizes) >= 20
            and median(title_sizes) >= median(later_sizes) * 1.4
        )
    return {
        "width": width, "height": height, "content_chars": sum(map(len, content)),
        "outer_page": outer, "inner_page": inner, "item_number": item_number,
        "font_size": median(sizes) if sizes else None, "image_cover": image_cover,
        "cover_like": cover_like,
    }


def _continuation_evidence(previous: dict[str, Any], current: dict[str, Any], anchor: dict[str, Any]) -> tuple[bool, list[str], list[str], str]:
    signals: list[str] = []
    boundaries: list[str] = []
    dimensions_known = all(previous[key] > 0 and current[key] > 0 for key in ("width", "height"))
    same_dimensions = dimensions_known and all(abs(previous[key] - current[key]) / previous[key] <= 0.06 for key in ("width", "height"))
    if dimensions_known and not same_dimensions:
        boundaries.append("page_dimensions_changed")
    if current["cover_like"]:
        boundaries.append("cover_like_page")
    if current["content_chars"] < (20 if dimensions_known else 1):
        boundaries.append("insufficient_native_content")
    if current["image_cover"] >= 0.8 and previous["image_cover"] < 0.2 and current["item_number"] is None:
        boundaries.append("new_image_dominant_page")

    inner_continuous = previous["inner_page"] is not None and current["inner_page"] == previous["inner_page"] + 1
    outer_continuous = (
        previous["outer_page"] is not None and current["outer_page"] is not None
        and current["outer_page"] == (previous["outer_page"][0] + 1, previous["outer_page"][1])
    )
    if inner_continuous:
        signals.append("internal_page_number_consecutive")
    if outer_continuous:
        signals.append("pdf_page_number_consecutive")
    if same_dimensions:
        signals.append("page_dimensions_stable")
    font_close = (
        previous["font_size"] is None or current["font_size"] is None
        or max(previous["font_size"], current["font_size"]) / min(previous["font_size"], current["font_size"]) <= 1.6
    )
    if font_close and previous["font_size"] is not None and current["font_size"] is not None:
        signals.append("font_size_stable")
    if anchor["ordinal"] is not None and current["item_number"] == anchor["ordinal"]:
        signals.append("item_number_matches_section")
    if boundaries:
        return False, signals, boundaries, boundaries[0]
    if inner_continuous and same_dimensions:
        if anchor["ordinal"] is not None and current["item_number"] == anchor["ordinal"]:
            return True, signals, boundaries, "internal_page_and_item_number_continuity"
        if anchor["ordinal"] is None and font_close:
            return True, signals, boundaries, "internal_page_and_layout_continuity"
    if anchor["ordinal"] is not None:
        if outer_continuous and same_dimensions and font_close and current["image_cover"] < 0.8:
            return True, signals, boundaries, "numbered_section_layout_continuity"
        if not dimensions_known and previous["width"] == current["width"] == 0 and current["content_chars"] > 0:
            return True, signals, boundaries, "numbered_section_minimal_snapshot_continuity"
    return False, signals, boundaries, "insufficient_continuation_evidence"


def _resolve_page_ownership(*, observed: list[dict[str, Any]], page_count: int, snapshot_pages: dict[int, dict[str, Any]]) -> tuple[list[int], list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = {page: _page_evidence(snapshot_pages.get(page, {})) for page in range(1, page_count + 1)}
    owners: list[int | None] = [None] * (page_count + 1)
    diagnostics: list[dict[str, Any]] = []
    reasons: dict[int, str] = {}
    for index, anchor in enumerate(observed):
        start = anchor["page_number"]
        next_anchor = observed[index + 1] if index + 1 < len(observed) else None
        limit = next_anchor["page_number"] - 1 if next_anchor else page_count
        owners[start] = index
        anchor_id = f"observed_section_{index + 1:03d}"
        heading_type = "numbered" if anchor["ordinal"] is not None else "visual"
        diagnostics.append({"page": start, "anchor_id": anchor_id, "anchor_page": start, "heading_type": heading_type,
                            "continuity_signals": [], "boundary_signals": ["observed_heading"],
                            "decision": "NEW_SECTION", "reason": "observed_native_heading"})
        stopped = False
        for page in range(start + 1, limit + 1):
            can_continue, signals, boundaries, reason = _continuation_evidence(evidence[page - 1], evidence[page], anchor)
            if next_anchor is not None and next_anchor["document_boundary"]:
                boundaries.append("new_document_boundary_ahead")
                can_continue = False
                reason = "new_document_boundary_ahead"
            if stopped:
                can_continue = False
                reason = "propagation_already_stopped"
            if can_continue:
                owners[page] = index
                decision = "CONTINUE"
            else:
                stopped = True
                reasons[page] = reason
                decision = "UNRESOLVED"
            diagnostics.append({"page": page, "anchor_id": anchor_id, "anchor_page": start, "heading_type": heading_type,
                                "continuity_signals": signals, "boundary_signals": boundaries,
                                "decision": decision, "reason": reason})
    diagnosed_pages = {item["page"] for item in diagnostics}
    for page in range(1, page_count + 1):
        if page not in diagnosed_pages:
            diagnostics.append({"page": page, "anchor_id": None, "anchor_page": None, "heading_type": None,
                                "continuity_signals": [], "boundary_signals": [], "decision": "UNRESOLVED",
                                "reason": "before_first_observed_heading" if observed else "no_observed_heading"})
    diagnostics.sort(key=lambda item: item["page"])

    unresolved = []
    page = 1
    while page <= page_count:
        if owners[page] is not None:
            page += 1
            continue
        start = page
        while page <= page_count and owners[page] is None:
            page += 1
        if not observed:
            reason = "没有可靠的原生一级标题证据。"
        elif start < observed[0]["page_number"]:
            reason = "首个已观察章节标题之前的页面没有可靠章节边界。"
        elif start in reasons and reasons[start] == "new_document_boundary_ahead":
            reason = "新文档边界之前的页面缺少可靠章节归属。"
        elif start in reasons and start > observed[-1]["page_number"]:
            reason = "最后一个已观察标题之后缺少可靠的章节延续证据。"
        else:
            reason = "逐页延续证据不足，页面归属未确认。"
        unresolved.append({"region_type": "generic_region", "start_page": start, "end_page": page - 1, "reason": reason})
    ends = [max(page for page, owner in enumerate(owners) if owner == index) for index in range(len(observed))]
    return ends, unresolved, diagnostics


def diagnose_page_ownership(*, page_count: int, snapshot_pages: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Explain each page decision without adding diagnostics to production artifacts."""
    observed, _ = _heading_candidates(page_count=page_count, snapshot_pages=snapshot_pages)
    _, _, diagnostics = _resolve_page_ownership(observed=observed, page_count=page_count, snapshot_pages=snapshot_pages)
    return diagnostics


def load_snapshot_pages(path: Path) -> dict[int, dict[str, Any]]:
    pages = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("record_type") == "page":
            pages[int(item["page_number"])] = item
    return pages


def discover_sections(*, source_file: str, page_count: int, snapshot_pages: dict[int, dict[str, Any]]) -> dict[str, Any]:
    observed, _ = _heading_candidates(page_count=page_count, snapshot_pages=snapshot_pages)
    ends, unresolved, _ = _resolve_page_ownership(observed=observed, page_count=page_count, snapshot_pages=snapshot_pages)
    sections = []
    for index, item in enumerate(observed):
        start = item["page_number"]
        next_item = observed[index + 1] if index + 1 < len(observed) else None
        next_page = next_item["page_number"] if next_item is not None else None
        end = ends[index]
        sections.append({
            "section_id": f"observed_section_{index + 1:03d}",
            "title": item["heading"],
            "canonical_title": None,
            "zone_type": None,
            "order": None,
            "start_page": start,
            "end_page": end,
            "anchor_page": start,
            "boundary_source": "continuation_evidence_boundary" if end < (next_page - 1 if next_page is not None else page_count) else "next_observed_native_heading_minus_one" if next_page is not None else "document_end",
            "boundary_confidence": "high" if item["ordinal"] is not None else "medium",
            "match_mode": "generic_native_heading" if item["ordinal"] is not None else "generic_visual_heading",
            "structure_evidence": "observed_native_top_level_heading" if item["ordinal"] is not None else "observed_native_visual_heading",
            "candidate_sources": [],
            "is_distinctive": False,
        })
    pages = []
    for page_number in range(1, page_count + 1):
        section = next((section for section in sections if section["start_page"] <= page_number <= section["end_page"]), None)
        pages.append({
            "page_number": page_number,
            "structure_type": "section" if section else "generic_region",
            "section_id": section["section_id"] if section else None,
            "title": section["title"] if section else None,
            "zone_type": None,
            **({"boundary_confidence": section["boundary_confidence"], "match_mode": section["match_mode"]} if section else {}),
        })
    return {
        "aligner_version": "generic-1.0",
        "source_file": source_file,
        "page_count": page_count,
        "structure_mode": "generic",
        "section_count": len(sections),
        "sections": sections,
        "unresolved_regions": unresolved,
        "pages": pages,
    }


def run_section_discovery(
    *,
    profile_path: Path,
    snapshot_path: Path,
    output_path: Path,
    profile: dict[str, Any] | None = None,
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = (
        profile if profile is not None
        else json.loads(Path(profile_path).read_text(encoding="utf-8"))
    )
    result = discover_sections(
        source_file=str(profile.get("source_file") or ""),
        page_count=int(profile["page_count"]),
        snapshot_pages=(
            snapshot_pages if snapshot_pages is not None
            else load_snapshot_pages(snapshot_path)
        ),
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
