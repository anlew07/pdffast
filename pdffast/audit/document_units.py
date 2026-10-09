"""Semantic audit for Canonical DocumentUnit rendering."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from pdffast.canonical.document_units import validate_document_units
from pdffast.render.llm_ready import build_rendered_document


_MARKER = re.compile(
    r"(?ms)^<!-- pdffast-document-unit: (?P<id>[^;\n]+); anchor-page: (?P<page>\d+) -->\n"
    r"(?P<body>.*?)^【PDFFast文档边界结束】\n\n?"
)
_SOURCE_PAGE = re.compile(r"<!-- source-page: (\d+) -->|<!-- source-pages: (\d+)-(\d+) -->")


def _provenance_is_traceable(unit: dict[str, Any]) -> bool:
    anchor = unit["anchor"]
    refs = set(anchor["evidence_refs"])
    anchor_ref = anchor["anchor_ref"]
    proposal_ref = anchor_ref.removeprefix("recovered-anchor:")
    candidates = anchor["candidate_refs"]
    page = anchor["page"]
    if anchor_ref not in refs or proposal_ref not in refs or not set(candidates).issubset(refs):
        return False
    tasks = []
    for candidate in candidates:
        match = re.fullmatch(rf"p{page:04d}:([^:]+):\d{{4}}", candidate)
        if match is None:
            return False
        tasks.append(match.group(1))
    linked = refs - {anchor_ref, proposal_ref, *candidates}
    return any(task in ref for task in tasks for ref in linked)


def _near_source_page(markdown: str, position: int, page: int) -> bool:
    comments = list(_SOURCE_PAGE.finditer(markdown))
    adjacent = (
        next((item for item in reversed(comments) if item.start() < position), None),
        next((item for item in comments if item.start() > position), None),
    )
    for item in adjacent:
        if item is None:
            continue
        if item.group(1) is not None and int(item.group(1)) == page:
            return True
        if item.group(2) is not None and int(item.group(2)) <= page <= int(item.group(3)):
            return True
    return False


def audit_document_units(canonical: dict[str, Any], markdown: str | None) -> dict[str, Any]:
    """Check published units against their Markdown presentation without rerunning discovery."""
    errors: list[str] = []
    units = canonical.get("document_units") or []
    if not isinstance(units, list):
        units = []
        errors.append("document_units must be an array")
    if "document_units" in canonical:
        try:
            validate_document_units(canonical)
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"DocumentUnit schema invalid: {exc}")

    for field in ("records", "sections"):
        for item in canonical.get(field) or []:
            if isinstance(item, dict) and any(key in item for key in ("document_id", "document_unit_id", "parent_document_id")):
                errors.append(f"DocumentUnit ownership inferred in {field}")
                break
    if "section_parent_map" in canonical:
        errors.append("DocumentUnit section parent mapping is not confirmed")

    if any(error.startswith("DocumentUnit schema invalid") or error == "document_units must be an array" for error in errors):
        return {
            "status": "FAIL", "units": len(units),
            "rendered_markers": markdown.count("<!-- pdffast-document-unit:") if markdown is not None else 0,
            "provenance_checked": 0, "body_unchanged": None, "errors": errors,
        }

    provenance_checked = 0
    for unit in units:
        if not unit["anchor"]["title_parts"]:
            errors.append(f"DocumentUnit title_parts must be nonempty: {unit['document_id']}")
        if _provenance_is_traceable(unit):
            provenance_checked += 1
        else:
            errors.append(f"DocumentUnit evidence refs disconnected: {unit['document_id']}")

    rendered_markers = 0
    body_unchanged: bool | None = None
    if markdown is None:
        if units:
            errors.append("DocumentUnit Markdown unavailable for semantic audit")
    else:
        matches = list(_MARKER.finditer(markdown))
        rendered_markers = len(matches)
        starts = markdown.count("<!-- pdffast-document-unit:")
        headers = markdown.count("【PDFFast文档边界元数据")
        ends = markdown.count("【PDFFast文档边界结束】")
        if len({starts, headers, ends, rendered_markers}) != 1:
            errors.append("DocumentUnit marker delimiters malformed or unmatched")
        by_id = {unit["document_id"]: unit for unit in units if isinstance(unit, dict) and isinstance(unit.get("document_id"), str)}
        counts = Counter(match.group("id") for match in matches)
        for document_id in by_id:
            if counts[document_id] != 1:
                errors.append(f"DocumentUnit marker count must equal one: {document_id}")
        for document_id in counts:
            if document_id not in by_id:
                errors.append(f"Unknown DocumentUnit marker: {document_id}")
        pages = []
        for match in matches:
            unit = by_id.get(match.group("id"))
            if unit is None or not isinstance(unit.get("anchor"), dict) or not isinstance(unit.get("page_range"), dict):
                continue
            anchor = unit["anchor"]
            page = anchor.get("page")
            if not isinstance(page, int):
                continue
            pages.append(int(match.group("page")))
            span = unit["page_range"]
            coverage = f"{span.get('start_page')}–{span.get('end_page')}页"
            if unit.get("range_status") == "PARTIAL":
                extent = f"已确认覆盖：{coverage}；完整范围未确定"
            else:
                extent = f"当前证据确认覆盖：{coverage}（非独占）"
            expected_body = (
                f"【PDFFast文档边界元数据｜锚点第{page}页｜页内具体边界未确定｜{extent}】\n"
                + "\n".join(f"标题原文 {i}：{part}" for i, part in enumerate(anchor.get("title_parts") or [], 1))
                + "\n"
            )
            if int(match.group("page")) != page or match.group("body") != expected_body:
                errors.append(f"DocumentUnit marker semantics differ from Canonical: {match.group('id')}")
            if not _near_source_page(markdown, match.start(), page):
                errors.append(f"DocumentUnit marker is away from anchor page: {match.group('id')}")
            if re.search(r"(?m)^#{1,6}\s", match.group("body")):
                errors.append(f"DocumentUnit marker became a Section heading: {match.group('id')}")
        if pages != sorted(pages):
            errors.append("DocumentUnit marker pages are out of rendering order")
        stripped = _MARKER.sub("", markdown)
        baseline = dict(canonical)
        baseline["document_units"] = []
        baseline_markdown, _ = build_rendered_document(baseline)
        body_unchanged = stripped == baseline_markdown
        if not body_unchanged:
            errors.append("DocumentUnit markers changed base record or fallback Markdown")

    return {
        "status": "PASS" if not errors else "FAIL",
        "units": len(units),
        "rendered_markers": rendered_markers,
        "provenance_checked": provenance_checked,
        "body_unchanged": body_unchanged,
        "errors": errors,
    }
