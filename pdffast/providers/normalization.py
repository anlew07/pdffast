#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stage 9.5.1
Provider Result -> CanonicalPrediction

Behavior-locked migration of the approved Provider adapters. This slice starts
with rapidocr_ch_light; the remaining approved adapters are added under the
same parity contract.
- Manifest selected_task list is the authority.
- Standardization only:
    * no re-OCR
    * no image re-understanding
    * no semantic structure guessing
    * no Ground Truth access
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import statistics
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


VERSION = "0.8.2"
SCHEMA_VERSION = "1.1"

SUPPORTED_PROVIDERS = {
    "rapidocr_ch_light",
}

STATUS_MAP = {
    "SUCCESS": "SUCCESS",
    "SUCCESS_WITH_WARNINGS": "SUCCESS_WITH_WARNINGS",
    "FAILED": "ERROR",
    "ERROR": "ERROR",
    "TIMEOUT": "TIMEOUT",
}

AVAILABILITY_VALUES = {
    "AVAILABLE",
    "UNSUPPORTED",
    "NOT_EMITTED",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def selected_task_map(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    tasks = manifest.get("selected_tasks")
    if not isinstance(tasks, list):
        raise ValueError("benchmark manifest missing selected_tasks[]")

    result: dict[str, dict[str, Any]] = {}
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError("selected_tasks item must be object")

        task_id = item.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("selected_tasks item missing task_id")

        if task_id in result:
            raise ValueError(f"duplicate selected task_id: {task_id}")

        result[task_id] = item

    return result


def validate_manifest(
    manifest: dict[str, Any],
    provider: str,
) -> dict[str, dict[str, Any]]:
    if manifest.get("name") != "provider_benchmark":
        raise ValueError(
            "not a provider_benchmark manifest: "
            f"name={manifest.get('name')!r}"
        )

    task_map = selected_task_map(manifest)

    selected_task_count = manifest.get("selected_task_count")
    if selected_task_count != len(task_map):
        raise ValueError(
            "selected_task_count mismatch: "
            f"manifest={selected_task_count}, actual={len(task_map)}"
        )

    selection = manifest.get("selection") or {}
    requested = selection.get("requested_providers") or []

    if provider not in requested:
        raise ValueError(
            f"provider {provider!r} is not in "
            f"manifest requested_providers={requested}"
        )

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unsupported adapter {provider!r}; "
            f"supported={sorted(SUPPORTED_PROVIDERS)}"
        )

    return task_map


def availability(
    availability_value: str,
    items: list[Any],
) -> dict[str, Any]:
    if availability_value not in AVAILABILITY_VALUES:
        raise ValueError(
            f"invalid availability={availability_value}"
        )

    return {
        "availability": availability_value,
        "items": items,
    }


def text_payload(
    status: str,
    content: Any,
    confidence: Any,
    *,
    raw_content: str | None = None,
    source_format: str = "plain_text",
) -> dict[str, Any]:
    # Empty text can still be a valid AVAILABLE output, especially
    # for no-text regions.
    if status in {"SUCCESS", "SUCCESS_WITH_WARNINGS"} and isinstance(
        content, str
    ):
        return {
            "availability": "AVAILABLE",
            "content": content,
            "raw_content": (
                raw_content
                if isinstance(raw_content, str)
                else content
            ),
            "source_format": source_format,
            "confidence": (
                confidence
                if isinstance(confidence, (int, float))
                else None
            ),
        }

    return {
        "availability": "NOT_EMITTED",
        "content": "",
        "raw_content": (
            raw_content
            if isinstance(raw_content, str)
            else ""
        ),
        "source_format": source_format,
        "confidence": None,
    }


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def strip_html(fragment: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(fragment)
    parser.close()
    return html.unescape(parser.text())


TABLE_RE = re.compile(
    r"<table\b[^>]*>.*?</table>",
    flags=re.IGNORECASE | re.DOTALL,
)

ROW_RE = re.compile(
    r"<tr\b[^>]*>(.*?)</tr>",
    flags=re.IGNORECASE | re.DOTALL,
)

CELL_RE = re.compile(
    r"<t([dh])\b([^>]*)>(.*?)</t\1>",
    flags=re.IGNORECASE | re.DOTALL,
)

BLOCK_FORMULA_RE = re.compile(
    r"\$\$(.*?)\$\$",
    flags=re.DOTALL,
)

INLINE_FORMULA_RE = re.compile(
    r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
    flags=re.DOTALL,
)

IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(([^)]*)\)"
)

LINK_RE = re.compile(
    r"\[([^\]]+)\]\(([^)]+)\)"
)


def _int_attr(attrs: str, name: str) -> int:
    m = re.search(
        rf"\b{name}\s*=\s*[\"']?(\d+)",
        attrs,
        flags=re.IGNORECASE,
    )
    if not m:
        return 1
    try:
        return int(m.group(1))
    except ValueError:
        return 1


def parse_html_table(
    table_html: str,
    table_index: int,
) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []

    for row_index, row_match in enumerate(
        ROW_RE.finditer(table_html)
    ):
        row_html = row_match.group(1)
        cells: list[dict[str, Any]] = []

        for cell_index, cell_match in enumerate(
            CELL_RE.finditer(row_html)
        ):
            tag = cell_match.group(1).lower()
            attrs = cell_match.group(2)
            inner = cell_match.group(3)

            cell_text = re.sub(
                r"\s+",
                " ",
                strip_html(inner),
            ).strip()

            cells.append(
                {
                    "row_index": row_index,
                    "cell_index": cell_index,
                    "kind": (
                        "header"
                        if tag == "h"
                        else "cell"
                    ),
                    "text": cell_text,
                    "rowspan": _int_attr(attrs, "rowspan"),
                    "colspan": _int_attr(attrs, "colspan"),
                }
            )

        rows.append(cells)

    return {
        "table_id": f"table_{table_index:03d}",
        "representation": "html",
        "html": table_html,
        "rows": rows,
    }


def table_plain_text(
    table_item: dict[str, Any],
) -> str:
    lines: list[str] = []

    for row in table_item.get("rows", []):
        values = [
            str(cell.get("text", "")).strip()
            for cell in row
            if str(cell.get("text", "")).strip()
        ]
        if values:
            lines.append("\t".join(values))

    return "\n".join(lines)


def extract_tables(
    markdown_text: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for i, match in enumerate(
        TABLE_RE.finditer(markdown_text),
        start=1,
    ):
        result.append(
            parse_html_table(
                match.group(0),
                i,
            )
        )

    return result


def extract_formulas(
    markdown_text: str,
) -> list[dict[str, Any]]:
    formulas: list[dict[str, Any]] = []
    block_spans: list[tuple[int, int]] = []

    for i, match in enumerate(
        BLOCK_FORMULA_RE.finditer(markdown_text),
        start=1,
    ):
        latex_value = match.group(1).strip()
        formulas.append(
            {
                "formula_id": f"formula_block_{i:03d}",
                "kind": "block",
                "latex": latex_value,
            }
        )
        block_spans.append(match.span())

    # Avoid double-counting inline $...$ inside $$...$$.
    masked = list(markdown_text)
    for start, end in block_spans:
        for idx in range(start, end):
            masked[idx] = " "
    inline_source = "".join(masked)

    inline_count = 0
    for match in INLINE_FORMULA_RE.finditer(inline_source):
        latex_value = match.group(1).strip()
        if not latex_value:
            continue

        inline_count += 1
        formulas.append(
            {
                "formula_id": (
                    f"formula_inline_{inline_count:03d}"
                ),
                "kind": "inline",
                "latex": latex_value,
            }
        )

    return formulas


def markdown_to_plain_text(
    markdown_text: str,
    tables: list[dict[str, Any]],
) -> str:
    text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")

    # Replace only explicit provider-emitted table markup with
    # deterministic row/cell text. No table reconstruction is done.
    table_iter = iter(tables)

    def repl_table(_: re.Match[str]) -> str:
        item = next(table_iter)
        return "\n" + table_plain_text(item) + "\n"

    text = TABLE_RE.sub(repl_table, text)

    # Images: keep alt text only. Empty alt -> no text.
    text = IMAGE_RE.sub(
        lambda m: m.group(1).strip(),
        text,
    )

    # Links: keep visible label only.
    text = LINK_RE.sub(
        lambda m: m.group(1),
        text,
    )

    # Formula delimiters are syntax, formula body is provider output.
    text = BLOCK_FORMULA_RE.sub(
        lambda m: "\n" + m.group(1).strip() + "\n",
        text,
    )
    text = INLINE_FORMULA_RE.sub(
        lambda m: m.group(1).strip(),
        text,
    )

    # Strip generic residual HTML tags deterministically.
    text = strip_html(text)

    # Remove common Markdown presentation markers only.
    text = re.sub(
        r"(?m)^\s{0,3}#{1,6}\s+",
        "",
        text,
    )
    text = re.sub(
        r"(?m)^\s*>\s?",
        "",
        text,
    )
    text = re.sub(
        r"(?m)^\s*[-*+]\s+",
        "",
        text,
    )

    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("~~", "")
    text = text.replace("`", "")

    # Normalize only presentation whitespace here.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return html.unescape(text).strip()


def _plain_blocks_from_segment(
    segment: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for raw_block in re.split(r"\n\s*\n", segment):
        block = raw_block.strip()
        if not block:
            continue

        heading = re.match(
            r"^\s{0,3}(#{1,6})\s+(.*)$",
            block,
            flags=re.DOTALL,
        )

        if heading:
            level = len(heading.group(1))
            block_text = markdown_to_plain_text(
                heading.group(2),
                [],
            )
            result.append(
                {
                    "kind": "heading",
                    "level": level,
                    "text": block_text,
                }
            )
        else:
            block_text = markdown_to_plain_text(
                block,
                [],
            )
            if block_text:
                result.append(
                    {
                        "kind": "paragraph",
                        "text": block_text,
                    }
                )

    return result


SPECIAL_BLOCK_RE = re.compile(
    r"(<table\b[^>]*>.*?</table>"
    r"|\$\$.*?\$\$"
    r"|!\[[^\]]*\]\([^)]*\))",
    flags=re.IGNORECASE | re.DOTALL,
)


def extract_reading_blocks(
    markdown_text: str,
) -> list[dict[str, Any]]:
    """
    Deterministic segmentation of explicit provider-emitted Markdown/HTML
    blocks. This is not semantic reading-order inference.
    """
    result: list[dict[str, Any]] = []
    cursor = 0
    table_index = 0
    formula_index = 0
    image_index = 0

    for match in SPECIAL_BLOCK_RE.finditer(markdown_text):
        before = markdown_text[cursor:match.start()]
        result.extend(_plain_blocks_from_segment(before))

        token = match.group(0)

        if token.lower().startswith("<table"):
            table_index += 1
            table_item = parse_html_table(
                token,
                table_index,
            )
            result.append(
                {
                    "kind": "table",
                    "table_id": table_item["table_id"],
                    "text": table_plain_text(table_item),
                }
            )

        elif token.startswith("$$"):
            formula_index += 1
            formula_body = token[2:-2].strip()
            result.append(
                {
                    "kind": "formula",
                    "formula_id": (
                        f"formula_block_{formula_index:03d}"
                    ),
                    "text": formula_body,
                }
            )

        elif token.startswith("!["):
            image_index += 1
            m = IMAGE_RE.fullmatch(token)
            alt_text = ""
            path = ""
            if m:
                alt_text = m.group(1).strip()
                path = m.group(2).strip()

            result.append(
                {
                    "kind": "image",
                    "image_id": f"image_{image_index:03d}",
                    "text": alt_text,
                    "path": path,
                }
            )

        cursor = match.end()

    result.extend(
        _plain_blocks_from_segment(
            markdown_text[cursor:]
        )
    )

    for order, block in enumerate(result):
        block["block_id"] = f"block_{order + 1:03d}"
        block["order"] = order

    return result



def _bbox_from_polygon(raw_box: Any) -> tuple[list[list[float]], dict[str, float] | None]:
    polygon: list[list[float]] = []
    if isinstance(raw_box, dict):
        try:
            bbox = {
                "x0": float(raw_box["x0"]),
                "top": float(raw_box["top"]),
                "x1": float(raw_box["x1"]),
                "bottom": float(raw_box["bottom"]),
            }
            return polygon, bbox
        except Exception:
            return polygon, None
    if isinstance(raw_box, (list, tuple)):
        for point in raw_box:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                try:
                    polygon.append([float(point[0]), float(point[1])])
                except (TypeError, ValueError):
                    pass
    if not polygon:
        return [], None
    xs = [pt[0] for pt in polygon]
    ys = [pt[1] for pt in polygon]
    return polygon, {
        "x0": min(xs),
        "top": min(ys),
        "x1": max(xs),
        "bottom": max(ys),
    }


def _resolve_raw_ref(ref: str, *, result_path: Path, manifest_path: Path) -> Path | None:
    p = Path(ref)
    candidates = [p]
    if not p.is_absolute():
        candidates.extend([
            Path.cwd() / p,
            result_path.parent / p,
            manifest_path.parent / p,
        ])
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _normalize_spatial_items(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        polygon, bbox = _bbox_from_polygon(raw.get("polygon"))
        if bbox is None:
            _, bbox = _bbox_from_polygon(raw.get("bbox"))
        confidence = raw.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = None
        out.append({
            "item_id": str(raw.get("item_id") or f"ocr_{len(out) + 1:03d}"),
            "text": text,
            "confidence": confidence,
            "polygon": polygon,
            "bbox": bbox,
            "provider_order": raw.get("provider_order", len(out)),
        })
    return out


def _rapidocr_spatial_items(
    result: dict[str, Any],
    *,
    result_path: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    structure = result.get("structure")
    if isinstance(structure, dict):
        direct = structure.get("spatial_text_items")
        if isinstance(direct, list):
            normalized = _normalize_spatial_items(direct)
            if normalized:
                return normalized, "task_result.structure.spatial_text_items"

    # Backward compatibility with Stage9.3 <= 0.1.17: RapidOCR already wrote
    # txts/scores/boxes into provider raw result.json, but the task-result kept
    # only summary counts.  Reuse that evidence; never re-run OCR here.
    for ref in result.get("provider_raw_refs") or []:
        if not isinstance(ref, str) or not ref.lower().endswith(".json"):
            continue
        raw_path = _resolve_raw_ref(ref, result_path=result_path, manifest_path=manifest_path)
        if raw_path is None:
            continue
        try:
            payload = load_json(raw_path)
        except Exception:
            continue

        direct = payload.get("spatial_text_items")
        if isinstance(direct, list):
            normalized = _normalize_spatial_items(direct)
            if normalized:
                return normalized, f"provider_raw_ref:{raw_path}"

        txts = payload.get("txts")
        scores = payload.get("scores")
        boxes = payload.get("boxes")
        if not isinstance(txts, list) or not isinstance(boxes, list):
            continue
        if not isinstance(scores, list):
            scores = []
        items: list[dict[str, Any]] = []
        for idx, raw_txt in enumerate(txts):
            text = str(raw_txt).strip()
            if not text:
                continue
            polygon, bbox = _bbox_from_polygon(boxes[idx] if idx < len(boxes) else None)
            score = scores[idx] if idx < len(scores) else None
            if not isinstance(score, (int, float)):
                score = None
            items.append({
                "item_id": f"ocr_{len(items) + 1:03d}",
                "text": text,
                "confidence": score,
                "polygon": polygon,
                "bbox": bbox,
                "provider_order": idx,
            })
        if items:
            return items, f"provider_raw_ref:{raw_path}"
    return [], "NOT_AVAILABLE"


def _spatial_layout_diagnostics(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [x for x in items if isinstance(x.get("bbox"), dict)]
    if not valid:
        return {
            "item_count": len(items),
            "geometry_item_count": 0,
            "structure_risk": "UNKNOWN",
            "risk_reasons": ["NO_BOX_GEOMETRY"],
        }

    x0 = min(float(x["bbox"]["x0"]) for x in valid)
    x1 = max(float(x["bbox"]["x1"]) for x in valid)
    y0 = min(float(x["bbox"]["top"]) for x in valid)
    y1 = max(float(x["bbox"]["bottom"]) for x in valid)
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)

    heights: list[float] = []
    centers_x: list[float] = []
    centers_y: list[float] = []
    short_count = 0
    numeric_symbol_heavy = 0

    for item in valid:
        b = item["bbox"]
        bx0, bx1 = float(b["x0"]), float(b["x1"])
        by0, by1 = float(b["top"]), float(b["bottom"])
        rb = {
            "x0": round((bx0 - x0) / width, 6),
            "top": round((by0 - y0) / height, 6),
            "x1": round((bx1 - x0) / width, 6),
            "bottom": round((by1 - y0) / height, 6),
        }
        item["relative_bbox"] = rb
        heights.append(max(1.0, by1 - by0))
        centers_x.append((bx0 + bx1) / 2.0)
        centers_y.append((by0 + by1) / 2.0)
        text = str(item.get("text") or "")
        compact = "".join(ch for ch in text if not ch.isspace())
        if len(compact) <= 12:
            short_count += 1
        if compact:
            numeric_symbol = sum(
                1 for ch in compact
                if ch.isdigit() or ch in ".,%+-−–—σΣ×*/()[]{}:=<>"
            )
            if numeric_symbol / len(compact) >= 0.55:
                numeric_symbol_heavy += 1

    median_h = statistics.median(heights) if heights else 1.0
    row_tol = max(2.0, median_h * 0.70)
    ordered = sorted(valid, key=lambda x: (
        (float(x["bbox"]["top"]) + float(x["bbox"]["bottom"])) / 2.0,
        float(x["bbox"]["x0"]),
    ))
    rows: list[list[dict[str, Any]]] = []
    row_centers: list[float] = []
    for item in ordered:
        b = item["bbox"]
        cy = (float(b["top"]) + float(b["bottom"])) / 2.0
        if not rows or abs(cy - row_centers[-1]) > row_tol:
            rows.append([item])
            row_centers.append(cy)
        else:
            rows[-1].append(item)
            row_centers[-1] = sum(
                (float(x["bbox"]["top"]) + float(x["bbox"]["bottom"])) / 2.0
                for x in rows[-1]
            ) / len(rows[-1])

    multi_item_rows = sum(1 for row in rows if len(row) >= 2)
    n = len(valid)
    short_ratio = short_count / n if n else 0.0
    numeric_ratio = numeric_symbol_heavy / n if n else 0.0
    x_spread = (max(centers_x) - min(centers_x)) / width if len(centers_x) >= 2 else 0.0
    multi_row_ratio = multi_item_rows / len(rows) if rows else 0.0

    reasons: list[str] = []
    high = False
    if n >= 6 and short_ratio >= 0.65 and len(rows) >= 3 and x_spread >= 0.35 and multi_row_ratio >= 0.20:
        high = True
        reasons.append("MANY_SHORT_LABELS_SPREAD_IN_2D")
    if n >= 6 and numeric_ratio >= 0.50 and x_spread >= 0.25:
        high = True
        reasons.append("NUMERIC_SYMBOL_DENSE_2D_REGION")
    if n >= 10 and len(rows) >= 5 and x_spread >= 0.45:
        high = True
        reasons.append("DENSE_MULTIROW_MULTICOLUMN_LABELS")

    if high:
        risk = "HIGH"
    elif n >= 4 and (x_spread >= 0.35 or multi_item_rows >= 2):
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {
        "item_count": len(items),
        "geometry_item_count": n,
        "row_count": len(rows),
        "multi_item_row_count": multi_item_rows,
        "short_item_ratio": round(short_ratio, 6),
        "numeric_symbol_heavy_ratio": round(numeric_ratio, 6),
        "x_center_spread_ratio": round(x_spread, 6),
        "multi_item_row_ratio": round(multi_row_ratio, 6),
        "structure_risk": risk,
        "risk_reasons": reasons,
        "semantics": "GEOMETRY_ONLY_NO_READING_ORDER_NO_RELATIONS",
    }




def _machine_code_safety_diagnostics(
    *,
    provider_structure: dict[str, Any] | None,
    spatial_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize machine-code evidence and add a conservative OCR-only safety guard.

    This function does not inspect the image and never selects a barcode value from
    OCR text. A decoded value is trusted only when Stage9.3 explicitly reports a
    machine-code decoder result. For older Stage9.3 artifacts, multiple conflicting
    long numeric OCR candidates trigger suppression rather than a guessed identifier.
    """
    structure = provider_structure if isinstance(provider_structure, dict) else {}
    raw_probe = structure.get("machine_code")
    probe = raw_probe if isinstance(raw_probe, dict) else {}

    decoded_values = []
    for value in probe.get("decoded_values") or []:
        value = str(value or "").strip()
        if value and value not in decoded_values:
            decoded_values.append(value)

    probe_status = str(probe.get("status") or "").upper()
    probe_kind = str(probe.get("kind") or "").upper() or None

    numeric_candidates: list[str] = []
    nonempty_count = 0
    for item in spatial_items:
        text = re.sub(r"\s+", "", str(item.get("text") or ""))
        if not text:
            continue
        nonempty_count += 1
        if re.fullmatch(r"\d{8,32}", text):
            if text not in numeric_candidates:
                numeric_candidates.append(text)

    numeric_ratio = (len(numeric_candidates) / nonempty_count) if nonempty_count else 0.0
    lengths = {len(x) for x in numeric_candidates}
    conflict = (
        len(numeric_candidates) >= 2
        and nonempty_count <= 5
        and numeric_ratio >= 0.8
        and len(lengths) == 1
    )

    if probe_status == "VERIFIED_DECODE" and decoded_values:
        action = "USE_VERIFIED_MACHINE_CODE_DECODE"
        reason = "PROVIDER_DECODER_VERIFIED_VALUE"
    elif probe_status in {"DETECTED_UNDECODED", "BARCODE_LIKE"}:
        action = "SUPPRESS_UNVERIFIED_MACHINE_CODE_OCR"
        reason = probe_status
    elif conflict:
        action = "SUPPRESS_AMBIGUOUS_LONG_NUMERIC_OCR"
        reason = "MULTIPLE_CONFLICTING_LONG_NUMERIC_CANDIDATES"
    else:
        action = "NONE"
        reason = "NO_MACHINE_CODE_SAFETY_SIGNAL"

    return {
        "action": action,
        "reason": reason,
        "kind": probe_kind,
        "provider_probe_status": probe_status or None,
        "decoded_values": decoded_values,
        "long_numeric_candidate_count": len(numeric_candidates),
        # Keep the raw candidates in structured evidence for review, but Stage10.2
        # may suppress them from LLM-facing Markdown when action requires it.
        "long_numeric_candidates": numeric_candidates,
        "nonempty_spatial_item_count": nonempty_count,
        "numeric_candidate_ratio": round(numeric_ratio, 6),
        "provider_probe": probe,
        "semantics": "SAFETY_GUARD_NO_OCR_VALUE_SELECTION",
    }


def normalize_rapidocr(
    result: dict[str, Any],
    manifest_task: dict[str, Any],
    manifest_path: Path,
    result_path: Path,
) -> dict[str, Any]:
    task_id = result.get("task_id")
    provider_obj = result.get("provider") or {}

    provider_name = provider_obj.get("name")
    provider_kind = provider_obj.get("kind")
    provider_model = provider_obj.get("model_or_engine")

    if provider_name != "rapidocr_ch_light":
        raise ValueError(
            f"{task_id}: rapidocr adapter received "
            f"provider={provider_name!r}"
        )

    raw_status = str(
        result.get("status") or ""
    ).upper()
    canonical_status = STATUS_MAP.get(
        raw_status,
        "ERROR",
    )

    warnings = result.get("warnings")
    if not isinstance(warnings, list):
        warnings = []

    exception = result.get("exception")
    quality_hints = result.get("quality_hints")
    structure = result.get("structure")

    raw_text = (
        result.get("text")
        if isinstance(result.get("text"), str)
        else ""
    )

    spatial_items, spatial_source = _rapidocr_spatial_items(
        result,
        result_path=result_path,
        manifest_path=manifest_path,
    )
    spatial_diag = _spatial_layout_diagnostics(spatial_items)
    machine_code_diag = _machine_code_safety_diagnostics(
        provider_structure=structure if isinstance(structure, dict) else {},
        spatial_items=spatial_items,
    )

    prediction = {
        "schema_version": SCHEMA_VERSION,
        "stage": 9,
        "substage": "9.5.1",
        "name": "canonical_prediction",
        "version": VERSION,

        "task_id": task_id,
        "task_type": (
            result.get("task_type")
            or manifest_task.get("task_type")
        ),
        "page_number": result.get(
            "page_number",
            manifest_task.get("page_number"),
        ),
        "source_id": (
            result.get("source_id")
            or manifest_task.get("source_id")
        ),
        "capability_route": (
            result.get("capability_route")
            or manifest_task.get("capability_route")
        ),

        "provider": {
            "name": provider_name,
            "kind": provider_kind,
            "model_or_engine": provider_model,
            "adapter": "rapidocr_ch_light_v1",
        },

        "status": canonical_status,
        "raw_status": raw_status,
        "elapsed_seconds": result.get("elapsed_seconds"),

        "text": text_payload(
            canonical_status,
            raw_text,
            result.get("confidence"),
            raw_content=raw_text,
            source_format="plain_text",
        ),

        # RapidOCR does not emit semantic reading order or relations.  It does
        # emit line-box geometry, which is preserved separately as spatial_text
        # so later stages can avoid flattening diagrams/charts into fake prose.
        "spatial_text": {
            "availability": "AVAILABLE" if spatial_items else "NOT_EMITTED",
            "items": spatial_items,
            "coordinate_system": "provider_image_pixels",
            "relative_coordinate_basis": "ocr_item_union_bbox",
            "semantics": "GEOMETRY_ONLY_NO_READING_ORDER_NO_RELATIONS",
        },
        "tables": availability(
            "UNSUPPORTED",
            [],
        ),
        "formulas": availability(
            "UNSUPPORTED",
            [],
        ),
        "reading_blocks": availability(
            "NOT_EMITTED",
            [],
        ),
        "relations": availability(
            "UNSUPPORTED",
            [],
        ),

        "warnings": warnings,
        "exception": exception,

        "diagnostics": {
            "quality_hints": (
                quality_hints
                if isinstance(quality_hints, dict)
                else {}
            ),
            "provider_structure_summary": (
                structure
                if isinstance(structure, dict)
                else {}
            ),
            "spatial_text_source": spatial_source,
            "spatial_layout": spatial_diag,
            "machine_code": machine_code_diag,
        },

        "source_artifacts": {
            "benchmark_manifest": str(manifest_path),
            "benchmark_manifest_sha256": (
                sha256_file(manifest_path)
            ),
            "task_result": str(result_path),
            "task_result_sha256": (
                sha256_file(result_path)
            ),
            "provider_raw_refs": (
                result.get("provider_raw_refs") or []
            ),
            "input_image": (
                result.get("input_image")
                or manifest_task.get("input_image")
            ),
        },

        "normalization_policy": {
            "re_ocr": False,
            "secondary_image_understanding": False,
            "infer_tables_from_text": False,
            "infer_formulas_from_text": False,
            "infer_relations_from_text": False,
            "split_plain_text_into_fake_reading_blocks": False,
            "preserve_provider_spatial_text_geometry": True,
            "infer_semantic_relations_from_geometry": False,
            "select_machine_code_value_from_plain_ocr": False,
            "suppress_ambiguous_machine_code_ocr_in_llm_render": True,
        },
    }

    return prediction


def validate_task_result(
    result: dict[str, Any],
    task_map: dict[str, dict[str, Any]],
    provider: str,
) -> dict[str, Any]:
    task_id = result.get("task_id")

    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task result missing task_id")

    # Manifest is authoritative. This prevents stale files from an old
    # 75-task RapidOCR run or any other previous benchmark run from
    # entering the current DEV evaluation.
    if task_id not in task_map:
        raise ValueError(
            f"{task_id}: task is NOT in "
            "manifest.selected_tasks; refusing stale/unselected result"
        )

    provider_obj = result.get("provider")
    if not isinstance(provider_obj, dict):
        raise ValueError(
            f"{task_id}: missing provider object"
        )

    if provider_obj.get("name") != provider:
        raise ValueError(
            f"{task_id}: provider mismatch: "
            f"result={provider_obj.get('name')!r}, "
            f"requested={provider!r}"
        )

    manifest_task = task_map[task_id]

    for key in (
        "task_type",
        "page_number",
        "source_id",
        "capability_route",
    ):
        a = result.get(key)
        b = manifest_task.get(key)

        if (
            a is not None
            and b is not None
            and a != b
        ):
            raise ValueError(
                f"{task_id}: task identity mismatch "
                f"for {key}: result={a!r}, manifest={b!r}"
            )

    return manifest_task


def validate_canonical(
    pred: dict[str, Any],
) -> None:
    required = [
        "task_id",
        "provider",
        "status",
        "text",
        "tables",
        "formulas",
        "reading_blocks",
        "relations",
        "source_artifacts",
    ]

    for key in required:
        if key not in pred:
            raise ValueError(
                f"canonical prediction missing {key}"
            )

    for key in (
        "tables",
        "formulas",
        "reading_blocks",
        "relations",
    ):
        obj = pred[key]

        if not isinstance(obj, dict):
            raise ValueError(
                f"{key} must be object"
            )

        if (
            obj.get("availability")
            not in AVAILABILITY_VALUES
        ):
            raise ValueError(
                f"{key}.availability invalid"
            )

        if not isinstance(
            obj.get("items"),
            list,
        ):
            raise ValueError(
                f"{key}.items must be list"
            )

    txt = pred["text"]

    if not isinstance(txt, dict):
        raise ValueError("text must be object")

    if (
        txt.get("availability")
        not in AVAILABILITY_VALUES
    ):
        raise ValueError(
            "text.availability invalid"
        )

    if not isinstance(
        txt.get("content"),
        str,
    ):
        raise ValueError(
            "text.content must be string"
        )

    if not isinstance(
        txt.get("raw_content"),
        str,
    ):
        raise ValueError(
            "text.raw_content must be string"
        )


def normalize_prediction(
    *,
    manifest: dict[str, Any],
    manifest_path: Path,
    task_map: dict[str, dict[str, Any]],
    provider: str,
    result_path: Path,
) -> dict[str, Any]:
    """Normalize one approved raw Provider result into CanonicalPrediction."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"no adapter for provider={provider}")

    result_path = Path(result_path)
    manifest_path = Path(manifest_path)
    result = load_json(result_path)
    manifest_task = validate_task_result(result, task_map, provider)
    prediction = normalize_rapidocr(
        result=result,
        manifest_task=manifest_task,
        manifest_path=manifest_path,
        result_path=result_path,
    )
    validate_canonical(prediction)
    return prediction
