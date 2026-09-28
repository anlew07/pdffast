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
    sections = []
    unresolved = []
    if not observed:
        if page_count:
            unresolved.append({"region_type": "generic_region", "start_page": 1, "end_page": page_count, "reason": "没有可靠的原生一级标题证据。"})
    elif observed[0]["page_number"] > 1:
        unresolved.append({"region_type": "generic_region", "start_page": 1, "end_page": observed[0]["page_number"] - 1, "reason": "首个已观察章节标题之前的页面没有可靠章节边界。"})
    for index, item in enumerate(observed):
        start = item["page_number"]
        next_item = observed[index + 1] if index + 1 < len(observed) else None
        next_page = next_item["page_number"] if next_item is not None else None
        end = next_page - 1 if next_page is not None else page_count
        if item["ordinal"] is None or (next_item is not None and next_item["document_boundary"]):
            end = start
            if next_page is not None and next_page > start + 1:
                unresolved.append({
                    "region_type": "generic_region",
                    "start_page": start + 1,
                    "end_page": next_page - 1,
                    "reason": "新文档边界之前的页面缺少可靠章节归属。" if next_item["document_boundary"] else "视觉标题后的页面缺少可靠的章节延续证据。",
                })
        if next_page is None and start < page_count:
            end = start
            unresolved.append({
                "region_type": "generic_region",
                "start_page": start + 1,
                "end_page": page_count,
                "reason": "最后一个已观察标题之后缺少可靠的章节延续证据。",
            })
        sections.append({
            "section_id": f"observed_section_{index + 1:03d}",
            "title": item["heading"],
            "canonical_title": None,
            "zone_type": None,
            "order": None,
            "start_page": start,
            "end_page": end,
            "anchor_page": start,
            "boundary_source": "next_observed_native_heading_minus_one" if index + 1 < len(observed) else "document_end",
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


def run_section_discovery(*, profile_path: Path, snapshot_path: Path, output_path: Path) -> dict[str, Any]:
    profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    result = discover_sections(
        source_file=str(profile.get("source_file") or ""),
        page_count=int(profile["page_count"]),
        snapshot_pages=load_snapshot_pages(snapshot_path),
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
