#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stage 5 — Table Recovery v0.4.0
===============================

本版在 v0.3.9 基线上增加三项通用能力：
1. 保留 v0.3.8 的 logical row provenance 与跨页恢复逻辑；
2. 新增页内 table bottom overflow recovery：当 Stage1 原生 word 仅因 table candidate
   底边略早结束而落在最后一行 cell 外时，使用几何连续性将其恢复回对应 cell。
   该恢复不读取具体字符串、不按 case/page 特判，并记录 source_word_indices 作为 ownership 证据。

    删除 v0.2.3 中“空 cell 用 chars 几何补全”的逻辑。

原因：
    - extracted_data 里的空 cell 不一定是漏解析；
    - 可能是 rowspan / colspan 占位、真实空字段、异常表格候选、
      扫描/乱码附件页中的伪 cell；
    - case_003 已验证：几何补全在复杂附件页会产生明显误补风险。

因此本版原则变为：

    1. Stage 1 extracted_data 仍是单页表格的基础内容来源；
    2. 非空 cell 原样保留；
    3. 空 cell 也原样保留为空；
    4. 不用 chars / words 猜测空 cell 内容；仅允许对 table bottom 外、与最后一行
       已有 cell 文本在几何上连续的 Stage1 native words 做保守 overflow continuation；
    5. 不重新打开 PDF；
    6. 无表格页继续直接使用 Stage 1 native_text；
    7. Stage 5.2 只负责“稳定保留单页表格结构”，不负责修正文。

当前仍不做：
    - 水印 / 页眉 / 页脚
    - 正文 text flow
    - OCR / CID 乱码
    - rowspan / colspan 语义恢复
    - 跨页表格之外的正文流重建
    - Quality Gate
"""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path
from typing import Any


VERSION = "0.4.1"


# =============================================================================
# IO
# =============================================================================


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")

    return value


def load_snapshot(path: Path) -> dict[int, dict[str, Any]]:
    pages: dict[int, dict[str, Any]] = {}

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()

            if not line:
                continue

            record = json.loads(line)

            if record.get("record_type") != "page":
                continue

            pages[int(record["page_number"])] = record

    return pages


# =============================================================================
# Text helpers
# =============================================================================


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = (
        str(value)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    lines = [line.rstrip() for line in text.split("\n")]

    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def display_cell_text(value: Any) -> str:
    """
    仅用于 Markdown 展示：
    把 cell 内部物理换行显示为单个空格。

    不改变 result.json 中原始 cell 内容。
    不做中文/英文/日期/手机号/具体字符串语义修复。
    """
    text = clean_text(value)

    if not text:
        return ""

    parts = [
        part.strip()
        for part in text.split("\n")
        if part.strip()
    ]

    return " ".join(parts)


# =============================================================================
# Geometry helper
# =============================================================================


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def normalize_bbox(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        raw = (
            value.get("x0"),
            value.get("top"),
            value.get("x1"),
            value.get("bottom"),
        )

    elif isinstance(value, (list, tuple)) and len(value) == 4:
        raw = tuple(value)

    else:
        return None

    if not all(finite_number(item) for item in raw):
        return None

    x0, top, x1, bottom = map(float, raw)

    if x1 <= x0 or bottom <= top:
        return None

    return {
        "x0": x0,
        "top": top,
        "x1": x1,
        "bottom": bottom,
    }



# =============================================================================
# Stage 5.2.1 — Page-local table bottom overflow recovery
# =============================================================================
#
# 目标：
#   pdfplumber 的 table candidate 偶尔会把底边截在最后一行文字之前，
#   导致同一 cell 的最后一小段 native text 落在 table bbox 外。
#
# 这里只做“证据驱动的几何续接”，不做语义补写：
#   - 仅检查最后一个几何 row；
#   - 候选必须来自 Stage1 native words；
#   - 候选中心必须仍落在某个最后 row cell 的水平范围内；
#   - 与该 cell 当前最底部视觉行的垂直距离必须接近正常行距；
#   - x 起点/水平覆盖必须与该 cell 尾行一致；
#   - 字高必须近似；
#   - 一旦连续性中断就停止，不跨越到后续正文。
#
# 所有阈值都是通用几何阈值，不依赖 case/page/字段/具体字符串。
# =============================================================================

TABLE_OVERFLOW_ROW_Y_TOLERANCE = 3.0
TABLE_OVERFLOW_MIN_VERTICAL_GAP = 8.0
TABLE_OVERFLOW_MAX_VERTICAL_GAP = 16.0
TABLE_OVERFLOW_VERTICAL_GAP_FACTOR = 1.40
TABLE_OVERFLOW_MIN_X_ALIGN_TOLERANCE = 8.0
TABLE_OVERFLOW_X_ALIGN_CELL_RATIO = 0.12
TABLE_OVERFLOW_MIN_HORIZONTAL_OVERLAP = 0.65
TABLE_OVERFLOW_MIN_HEIGHT_SIMILARITY = 0.65
TABLE_OVERFLOW_SCAN_DEPTH_FACTOR = 3.0
TABLE_OVERFLOW_MIN_SCAN_DEPTH = 30.0
TABLE_OVERFLOW_TABLE_EDGE_EPSILON = 0.5


def bbox_center(
    bbox: dict[str, float],
) -> tuple[float, float]:
    return (
        (bbox["x0"] + bbox["x1"]) / 2.0,
        (bbox["top"] + bbox["bottom"]) / 2.0,
    )


def bbox_center_inside(
    subject: dict[str, float],
    container: dict[str, float],
) -> bool:
    center_x, center_y = bbox_center(subject)

    return (
        container["x0"] <= center_x <= container["x1"]
        and container["top"] <= center_y <= container["bottom"]
    )


def group_word_items_by_visual_row(
    items: list[tuple[int, dict[str, Any], dict[str, float]]],
) -> list[list[tuple[int, dict[str, Any], dict[str, float]]]]:
    if not items:
        return []

    ordered = sorted(
        items,
        key=lambda item: (
            item[2]["top"],
            item[2]["x0"],
        ),
    )

    rows: list[
        list[tuple[int, dict[str, Any], dict[str, float]]]
    ] = []

    for item in ordered:
        if not rows:
            rows.append([item])
            continue

        current = rows[-1]
        mean_top = sum(
            entry[2]["top"]
            for entry in current
        ) / len(current)

        if (
            abs(item[2]["top"] - mean_top)
            <= TABLE_OVERFLOW_ROW_Y_TOLERANCE
        ):
            current.append(item)
        else:
            rows.append([item])

    return rows


def horizontal_overlap_ratio_of_ranges(
    left_x0: float,
    left_x1: float,
    right_x0: float,
    right_x1: float,
) -> float:
    overlap = max(
        0.0,
        min(left_x1, right_x1)
        - max(left_x0, right_x0),
    )

    minimum_width = min(
        max(0.0, left_x1 - left_x0),
        max(0.0, right_x1 - right_x0),
    )

    if minimum_width <= 0:
        return 0.0

    return overlap / minimum_width


def join_native_word_fragments(
    fragments: list[str],
) -> str:
    """
    仅把同一视觉行上的 Stage1 word 片段连接起来。

    中文/标点边界直接相接；
    两侧都以 ASCII 字母/数字结束和开始时保留一个空格，
    避免把英文 token 人为粘连。
    """
    result = ""

    for raw in fragments:
        text = clean_text(raw).strip()

        if not text:
            continue

        if not result:
            result = text
            continue

        left = result[-1]
        right = text[0]

        if (
            left.isascii()
            and right.isascii()
            and left.isalnum()
            and right.isalnum()
        ):
            result += " " + text
        else:
            result += text

    return result


def recover_table_bottom_overflow(
    raw_page: dict[str, Any],
    table: dict[str, Any],
) -> tuple[
    list[list[str]],
    list[dict[str, Any]],
]:
    """
    对单个 Stage1 table candidate 做保守的底边续行恢复。

    返回：
        recovered_rows
        recoveries

    recoveries 中记录 source_word_indices，后续阶段可以把这些
    raw words 视为已被 table materialization 消费，避免正文重复。
    """
    rows = extracted_rows(table)

    if not rows:
        return rows, []

    raw_geometry_rows = table.get("rows")

    if not isinstance(raw_geometry_rows, list):
        return rows, []

    usable_row_count = min(
        len(rows),
        len(raw_geometry_rows),
    )

    if usable_row_count <= 0:
        return rows, []

    last_row_index = usable_row_count - 1
    raw_last_row = raw_geometry_rows[last_row_index]

    if not isinstance(raw_last_row, dict):
        return rows, []

    raw_cells = raw_last_row.get("cells")

    if not isinstance(raw_cells, list):
        return rows, []

    table_bbox = normalize_bbox(
        table.get("bbox")
    )

    if table_bbox is None:
        return rows, []

    words: list[
        tuple[int, dict[str, Any], dict[str, float]]
    ] = []

    for word_index, word in enumerate(
        raw_page.get("words", [])
    ):
        if not isinstance(word, dict):
            continue

        text = clean_text(word.get("text"))

        if not text.strip():
            continue

        bbox = normalize_bbox(word)

        if bbox is None:
            continue

        words.append(
            (
                word_index,
                word,
                bbox,
            )
        )

    if not words:
        return rows, []

    recoveries: list[dict[str, Any]] = []
    claimed_word_indices: set[int] = set()

    for cell_index, raw_cell_bbox in enumerate(
        raw_cells
    ):
        if cell_index >= len(rows[last_row_index]):
            break

        cell_bbox = normalize_bbox(
            raw_cell_bbox
        )

        if cell_bbox is None:
            continue

        in_cell_words = [
            item
            for item in words
            if bbox_center_inside(
                item[2],
                cell_bbox,
            )
        ]

        if not in_cell_words:
            continue

        # 当前 cell 中最靠下的一条视觉行，作为 continuation anchor。
        max_top = max(
            item[2]["top"]
            for item in in_cell_words
        )

        tail_words = [
            item
            for item in in_cell_words
            if (
                abs(
                    item[2]["top"]
                    - max_top
                )
                <= TABLE_OVERFLOW_ROW_Y_TOLERANCE
            )
        ]

        if not tail_words:
            continue

        previous_bottom = max(
            item[2]["bottom"]
            for item in tail_words
        )
        previous_x0 = min(
            item[2]["x0"]
            for item in tail_words
        )
        previous_x1 = max(
            item[2]["x1"]
            for item in tail_words
        )

        tail_heights = [
            item[2]["bottom"]
            - item[2]["top"]
            for item in tail_words
            if (
                item[2]["bottom"]
                > item[2]["top"]
            )
        ]

        if not tail_heights:
            continue

        median_height = float(
            statistics.median(
                tail_heights
            )
        )

        scan_depth = max(
            TABLE_OVERFLOW_MIN_SCAN_DEPTH,
            TABLE_OVERFLOW_SCAN_DEPTH_FACTOR
            * median_height,
        )

        outside_candidates: list[
            tuple[int, dict[str, Any], dict[str, float]]
        ] = []

        for item in words:
            word_index, _, bbox = item

            if word_index in claimed_word_indices:
                continue

            center_x, _ = bbox_center(
                bbox
            )

            if not (
                cell_bbox["x0"]
                <= center_x
                <= cell_bbox["x1"]
            ):
                continue

            # 只看 table bottom 之外的原生 word。
            if (
                bbox["top"]
                < table_bbox["bottom"]
                - TABLE_OVERFLOW_TABLE_EDGE_EPSILON
            ):
                continue

            if (
                bbox["top"]
                > table_bbox["bottom"]
                + scan_depth
            ):
                continue

            outside_candidates.append(
                item
            )

        candidate_rows = (
            group_word_items_by_visual_row(
                outside_candidates
            )
        )

        accepted_rows: list[
            list[
                tuple[
                    int,
                    dict[str, Any],
                    dict[str, float],
                ]
            ]
        ] = []

        accepted_diagnostics: list[
            dict[str, Any]
        ] = []

        for candidate_row in candidate_rows:
            row_top = min(
                item[2]["top"]
                for item in candidate_row
            )
            row_bottom = max(
                item[2]["bottom"]
                for item in candidate_row
            )
            row_x0 = min(
                item[2]["x0"]
                for item in candidate_row
            )
            row_x1 = max(
                item[2]["x1"]
                for item in candidate_row
            )

            row_heights = [
                item[2]["bottom"]
                - item[2]["top"]
                for item in candidate_row
                if (
                    item[2]["bottom"]
                    > item[2]["top"]
                )
            ]

            if not row_heights:
                continue

            row_height = float(
                statistics.median(
                    row_heights
                )
            )

            vertical_gap = (
                row_top
                - previous_bottom
            )

            # 对已经与 anchor 垂直重叠的候选不做恢复。
            if vertical_gap < -1.0:
                continue

            vertical_limit = max(
                TABLE_OVERFLOW_MIN_VERTICAL_GAP,
                min(
                    TABLE_OVERFLOW_MAX_VERTICAL_GAP,
                    TABLE_OVERFLOW_VERTICAL_GAP_FACTOR
                    * max(
                        median_height,
                        row_height,
                    ),
                ),
            )

            cell_width = (
                cell_bbox["x1"]
                - cell_bbox["x0"]
            )

            x_align_tolerance = max(
                TABLE_OVERFLOW_MIN_X_ALIGN_TOLERANCE,
                TABLE_OVERFLOW_X_ALIGN_CELL_RATIO
                * cell_width,
            )

            horizontal_overlap = (
                horizontal_overlap_ratio_of_ranges(
                    previous_x0,
                    previous_x1,
                    row_x0,
                    row_x1,
                )
            )

            aligned = (
                abs(
                    row_x0
                    - previous_x0
                )
                <= x_align_tolerance
                or horizontal_overlap
                >= TABLE_OVERFLOW_MIN_HORIZONTAL_OVERLAP
            )

            height_similarity = (
                min(
                    median_height,
                    row_height,
                )
                / max(
                    median_height,
                    row_height,
                )
                if max(
                    median_height,
                    row_height,
                ) > 0
                else 0.0
            )

            # 第一条失去连续性的候选即停止。
            # 这样不会越过新段落继续向下“捞字”。
            if (
                vertical_gap
                > vertical_limit
                or not aligned
                or height_similarity
                < TABLE_OVERFLOW_MIN_HEIGHT_SIMILARITY
            ):
                break

            accepted_rows.append(
                candidate_row
            )
            accepted_diagnostics.append(
                {
                    "vertical_gap":
                        vertical_gap,
                    "vertical_limit":
                        vertical_limit,
                    "x_alignment_delta":
                        abs(
                            row_x0
                            - previous_x0
                        ),
                    "x_alignment_tolerance":
                        x_align_tolerance,
                    "horizontal_overlap_ratio":
                        horizontal_overlap,
                    "height_similarity":
                        height_similarity,
                }
            )

            for item in candidate_row:
                claimed_word_indices.add(
                    item[0]
                )

            previous_bottom = row_bottom
            previous_x0 = row_x0
            previous_x1 = row_x1
            median_height = (
                median_height
                + row_height
            ) / 2.0

        if not accepted_rows:
            continue

        recovered_lines: list[str] = []
        source_word_indices: list[int] = []

        for accepted_row in accepted_rows:
            ordered_row = sorted(
                accepted_row,
                key=lambda item:
                    item[2]["x0"],
            )

            recovered_text = (
                join_native_word_fragments(
                    [
                        str(
                            item[1].get(
                                "text",
                                "",
                            )
                        )
                        for item in ordered_row
                    ]
                )
            )

            if recovered_text:
                recovered_lines.append(
                    recovered_text
                )

            source_word_indices.extend(
                item[0]
                for item in ordered_row
            )

        if not recovered_lines:
            continue

        existing = clean_text(
            rows[last_row_index][cell_index]
        )

        recovered_text = "\n".join(
            recovered_lines
        )

        if existing:
            rows[last_row_index][cell_index] = (
                existing.rstrip()
                + "\n"
                + recovered_text
            )
        else:
            rows[last_row_index][cell_index] = (
                recovered_text
            )

        recoveries.append(
            {
                "recovery_type":
                    "table_bottom_overflow_continuation",
                "row_index":
                    last_row_index,
                "cell_index":
                    cell_index,
                "source_word_indices":
                    source_word_indices,
                "recovered_text":
                    recovered_text,
                "table_bbox":
                    table_bbox,
                "cell_bbox":
                    cell_bbox,
                "evidence":
                    accepted_diagnostics,
            }
        )

    return rows, recoveries


def recovered_word_index_set(
    recoveries: list[dict[str, Any]],
) -> set[int]:
    result: set[int] = set()

    for recovery in recoveries:
        for value in recovery.get(
            "source_word_indices",
            [],
        ):
            if isinstance(value, int):
                result.add(value)

    return result


# =============================================================================
# Stage 1 table access
# =============================================================================


def safe_table_index(
    table: dict[str, Any],
    fallback: int,
) -> int:
    try:
        return int(table.get("table_index", fallback))
    except (TypeError, ValueError):
        return fallback


def index_raw_tables(
    raw_page: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}

    for fallback, table in enumerate(
        raw_page.get("table_candidates", [])
    ):
        if not isinstance(table, dict):
            continue

        result[
            safe_table_index(table, fallback)
        ] = table

    return result


def extracted_rows(
    table: dict[str, Any],
) -> list[list[str]]:
    """
    Stage 5.2 v0.2.4：
    只读取 Stage 1 extracted_data，不再二次重建 cell。
    """
    data = table.get("extracted_data")

    if not isinstance(data, list):
        return []

    rows: list[list[str]] = []

    for row in data:
        if isinstance(row, list):
            rows.append(
                [
                    clean_text(cell)
                    for cell in row
                ]
            )
        else:
            rows.append([clean_text(row)])

    return rows



# =============================================================================
# Stage 5.3.1 — Cross-page table fragment confirmation + association
# =============================================================================


EDGE_ROW_WINDOW = 4

# 通用结构阈值，不依赖 case/page/字段/具体字符串。
# 两个阈值之间保留较宽灰区：
#   >= 0.90  -> confirmed
#   <= 0.60  -> rejected
#   中间      -> unresolved
SCHEMA_CONFIRM_THRESHOLD = 0.90
SCHEMA_REJECT_THRESHOLD = 0.60

# Stage 5.3.1 schema-transition fallback:
# 不降低全局 0.90 阈值，只处理同一已观察章节中
# 由 Stage5 补出来的 fallback candidate，且必须同时满足几何连续性。
SCHEMA_TRANSITION_MIN_SIMILARITY = 0.70
SCHEMA_TRANSITION_MIN_X_OVERLAP = 0.90
SCHEMA_TRANSITION_MIN_WIDTH_SIMILARITY = 0.85
SCHEMA_TRANSITION_FROM_BOTTOM_RATIO = 0.08
SCHEMA_TRANSITION_TO_TOP_RATIO = 0.10


def index_structure_blocks(
    structure: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for page in structure.get("pages", []):
        if not isinstance(page, dict):
            continue

        try:
            page_number = int(page["page_number"])
        except (KeyError, TypeError, ValueError):
            continue

        for block in page.get("blocks", []):
            if not isinstance(block, dict):
                continue

            block_id = block.get("block_id")

            if not isinstance(block_id, str) or not block_id:
                continue

            result[block_id] = {
                "page_number": page_number,
                "block": block,
            }

    return result


def get_raw_table(
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
    table_index: int,
) -> dict[str, Any] | None:
    raw_page = snapshot_pages.get(page_number)

    if raw_page is None:
        return None

    return index_raw_tables(raw_page).get(table_index)


def validate_cross_page_candidate_refs(
    candidate: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    """
    这里只验证 Stage 4 候选引用是否真实存在。
    是否真的是同一张跨页表，交给后面的 schema confirmation。
    """
    if not isinstance(candidate, dict):
        return None

    if candidate.get("candidate_type") != "table_continuation":
        return None

    from_page = candidate.get("from_page")
    to_page = candidate.get("to_page")
    from_block_id = candidate.get("from_block_id")
    to_block_id = candidate.get("to_block_id")

    if not isinstance(from_page, int) or not isinstance(to_page, int):
        return None

    if to_page != from_page + 1:
        return None

    if not isinstance(from_block_id, str) or not isinstance(to_block_id, str):
        return None

    from_entry = block_index.get(from_block_id)
    to_entry = block_index.get(to_block_id)

    if from_entry is None or to_entry is None:
        return None

    if from_entry["page_number"] != from_page:
        return None

    if to_entry["page_number"] != to_page:
        return None

    from_block = from_entry["block"]
    to_block = to_entry["block"]

    if from_block.get("block_type") != "table":
        return None

    if to_block.get("block_type") != "table":
        return None

    from_table_index = from_block.get("source_table_index")
    to_table_index = to_block.get("source_table_index")

    if not isinstance(from_table_index, int):
        return None

    if not isinstance(to_table_index, int):
        return None

    from_table = get_raw_table(
        snapshot_pages,
        from_page,
        from_table_index,
    )
    to_table = get_raw_table(
        snapshot_pages,
        to_page,
        to_table_index,
    )

    if from_table is None or to_table is None:
        return None

    return {
        "candidate_id": candidate.get("candidate_id"),
        "from": {
            "page_number": from_page,
            "block_id": from_block_id,
            "table_index": from_table_index,
        },
        "to": {
            "page_number": to_page,
            "block_id": to_block_id,
            "table_index": to_table_index,
        },
        "from_table": from_table,
        "to_table": to_table,
    }


def row_partition_signature(
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """
    把一行表格压缩成“列宽比例”。

    只读取 Stage 1 cell bbox，不读取 cell 文本。
    """
    raw_cells = row.get("cells")

    if not isinstance(raw_cells, list):
        return None

    cells: list[dict[str, float]] = []

    for raw_cell in raw_cells:
        bbox = normalize_bbox(raw_cell)

        if bbox is not None:
            cells.append(bbox)

    # 一个大合并格没有列结构信息。
    if len(cells) < 2:
        return None

    cells.sort(
        key=lambda bbox: (
            bbox["x0"],
            bbox["x1"],
        )
    )

    widths = [
        bbox["x1"] - bbox["x0"]
        for bbox in cells
    ]

    total_width = sum(widths)

    if total_width <= 0:
        return None

    return {
        "column_count": len(widths),
        "proportions": [
            width / total_width
            for width in widths
        ],
    }


def edge_row_signatures(
    table: dict[str, Any],
    side: str,
) -> list[dict[str, Any]]:
    """
    只看分页边界附近的少量行：
      from -> 最后几行
      to   -> 最前几行
    """
    rows = table.get("rows")

    if not isinstance(rows, list):
        return []

    valid_rows = [
        row
        for row in rows
        if isinstance(row, dict)
    ]

    if side == "tail":
        selected = valid_rows[-EDGE_ROW_WINDOW:]
    elif side == "head":
        selected = valid_rows[:EDGE_ROW_WINDOW]
    else:
        raise ValueError(f"未知 side：{side}")

    signatures: list[dict[str, Any]] = []

    for row in selected:
        signature = row_partition_signature(row)

        if signature is not None:
            signatures.append(signature)

    return signatures


def partition_similarity(
    left: list[float],
    right: list[float],
) -> float | None:
    """
    归一化列宽结构相似度。

    similarity = 1 - TV distance
               = 1 - 0.5 * sum(|a_i - b_i|)

    结果范围 [0, 1]：
      1 -> 列宽结构完全一致
      0 -> 极不一致
    """
    if not left or len(left) != len(right):
        return None

    distance = 0.5 * sum(
        abs(a - b)
        for a, b in zip(left, right)
    )

    return max(
        0.0,
        min(1.0, 1.0 - distance),
    )


def compare_edge_schemas(
    from_table: dict[str, Any],
    to_table: dict[str, Any],
) -> dict[str, Any]:
    """
    在上一页尾部与下一页头部寻找最佳“同列数 + 同列宽结构”匹配。

    没有可比较结构时，不猜，返回 unresolved。
    """
    tail = edge_row_signatures(
        from_table,
        "tail",
    )
    head = edge_row_signatures(
        to_table,
        "head",
    )

    best: dict[str, Any] | None = None

    for left in tail:
        for right in head:
            if (
                left["column_count"]
                != right["column_count"]
            ):
                continue

            similarity = partition_similarity(
                left["proportions"],
                right["proportions"],
            )

            if similarity is None:
                continue

            current = {
                "schema_similarity": similarity,
                "matched_column_count":
                    left["column_count"],
            }

            if (
                best is None
                or current["schema_similarity"]
                > best["schema_similarity"]
            ):
                best = current

    if best is None:
        return {
            "status": "unresolved",
            "schema_similarity": None,
            "matched_column_count": None,
        }

    similarity = best["schema_similarity"]

    if similarity >= SCHEMA_CONFIRM_THRESHOLD:
        status = "confirmed"
    elif similarity <= SCHEMA_REJECT_THRESHOLD:
        status = "rejected"
    else:
        status = "unresolved"

    return {
        "status": status,
        **best,
    }



def horizontal_bbox_similarity(
    left_bbox: dict[str, float],
    right_bbox: dict[str, float],
) -> dict[str, float]:
    left_width = (
        left_bbox["x1"]
        - left_bbox["x0"]
    )
    right_width = (
        right_bbox["x1"]
        - right_bbox["x0"]
    )

    if left_width <= 0 or right_width <= 0:
        return {
            "x_overlap_ratio": 0.0,
            "width_similarity": 0.0,
        }

    overlap = max(
        0.0,
        min(
            left_bbox["x1"],
            right_bbox["x1"],
        )
        - max(
            left_bbox["x0"],
            right_bbox["x0"],
        ),
    )

    x_overlap_ratio = (
        overlap
        / min(left_width, right_width)
    )

    width_similarity = (
        min(left_width, right_width)
        / max(left_width, right_width)
    )

    return {
        "x_overlap_ratio":
            max(
                0.0,
                min(1.0, x_overlap_ratio),
            ),
        "width_similarity":
            max(
                0.0,
                min(1.0, width_similarity),
            ),
    }


def page_height(
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
) -> float | None:
    page = snapshot_pages.get(page_number)

    if not isinstance(page, dict):
        return None

    value = page.get("height")

    if finite_number(value):
        height = float(value)

        if height > 0:
            return height

    return None


def table_bbox_from_refs(
    refs: dict[str, Any],
    side: str,
) -> dict[str, float] | None:
    table_key = (
        "from_table"
        if side == "from"
        else "to_table"
    )

    table = refs.get(table_key)

    if isinstance(table, dict):
        bbox = normalize_bbox(
            table.get("bbox")
        )

        if bbox is not None:
            return bbox

    return None


def block_bbox_from_index(
    refs: dict[str, Any],
    side: str,
    block_index: dict[str, dict[str, Any]],
) -> dict[str, float] | None:
    ref = refs.get(side)

    if not isinstance(ref, dict):
        return None

    block_id = ref.get("block_id")

    if not isinstance(block_id, str):
        return None

    entry = block_index.get(block_id)

    if not isinstance(entry, dict):
        return None

    block = entry.get("block")

    if not isinstance(block, dict):
        return None

    return normalize_bbox(
        block.get("bbox")
    )


def best_table_bbox(
    refs: dict[str, Any],
    side: str,
    block_index: dict[str, dict[str, Any]],
) -> dict[str, float] | None:
    """
    优先使用 Stage1 table bbox；
    缺失时回退到 Stage4 table block bbox。
    """
    bbox = table_bbox_from_refs(
        refs,
        side,
    )

    if bbox is not None:
        return bbox

    return block_bbox_from_index(
        refs,
        side,
        block_index,
    )


def confirm_same_section_schema_transition(
    candidate: dict[str, Any],
    refs: dict[str, Any],
    comparison: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    """
    处理一种真实但容易落入 schema 灰区的跨页表：

    同一张表在后续页进入“大合并 cell / 说明区域”后，
    边界 row 的列宽结构会发生变化，导致纯 schema score
    从 >=0.90 降到 0.60~0.90 的灰区。

    只允许 Stage5 same-section fallback candidate 使用此确认。
    不能影响 Stage4 原候选，也不能降低全局 schema 阈值。
    """
    if (
        candidate.get("candidate_source")
        != "stage5_same_section_fallback"
    ):
        return None

    if candidate.get("same_section") is not True:
        return None

    if comparison.get("status") != "unresolved":
        return None

    similarity = comparison.get(
        "schema_similarity"
    )

    if not isinstance(
        similarity,
        (int, float),
    ):
        return None

    if (
        similarity
        < SCHEMA_TRANSITION_MIN_SIMILARITY
    ):
        return None

    matched_column_count = comparison.get(
        "matched_column_count"
    )

    if (
        not isinstance(
            matched_column_count,
            int,
        )
        or matched_column_count < 2
    ):
        return None

    from_ref = refs.get("from")
    to_ref = refs.get("to")

    if not isinstance(from_ref, dict):
        return None

    if not isinstance(to_ref, dict):
        return None

    from_page = int(
        from_ref["page_number"]
    )
    to_page = int(
        to_ref["page_number"]
    )

    from_height = page_height(
        snapshot_pages,
        from_page,
    )
    to_height = page_height(
        snapshot_pages,
        to_page,
    )

    if (
        from_height is None
        or to_height is None
    ):
        return None

    from_bbox = best_table_bbox(
        refs,
        "from",
        block_index,
    )
    to_bbox = best_table_bbox(
        refs,
        "to",
        block_index,
    )

    if (
        from_bbox is None
        or to_bbox is None
    ):
        return None

    horizontal = horizontal_bbox_similarity(
        from_bbox,
        to_bbox,
    )

    if (
        horizontal["x_overlap_ratio"]
        < SCHEMA_TRANSITION_MIN_X_OVERLAP
    ):
        return None

    if (
        horizontal["width_similarity"]
        < SCHEMA_TRANSITION_MIN_WIDTH_SIMILARITY
    ):
        return None

    from_bottom_gap = (
        from_height
        - from_bbox["bottom"]
    )
    to_top_gap = to_bbox["top"]

    from_near_bottom = (
        from_bottom_gap
        <= from_height
        * SCHEMA_TRANSITION_FROM_BOTTOM_RATIO
    )
    to_near_top = (
        to_top_gap
        <= to_height
        * SCHEMA_TRANSITION_TO_TOP_RATIO
    )

    # 两端都要有明显分页连续性。
    if not (
        from_near_bottom
        and to_near_top
    ):
        return None

    return {
        "status": "confirmed",
        "confirmation_mode":
            "same_section_schema_transition",
        "x_overlap_ratio":
            horizontal["x_overlap_ratio"],
        "width_similarity":
            horizontal["width_similarity"],
        "from_bottom_gap":
            from_bottom_gap,
        "to_top_gap":
            to_top_gap,
    }


def confirm_cross_page_edge(
    candidate: dict[str, Any],
    block_index: dict[str, dict[str, Any]],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    refs = validate_cross_page_candidate_refs(
        candidate,
        block_index,
        snapshot_pages,
    )

    candidate_id = (
        candidate.get("candidate_id")
        if isinstance(candidate, dict)
        else None
    )

    if refs is None:
        return {
            "candidate_id": candidate_id,
            "candidate_source":
                (
                    candidate.get(
                        "candidate_source",
                        "stage4",
                    )
                    if isinstance(
                        candidate,
                        dict,
                    )
                    else "stage4"
                ),
            "status": "invalid_reference",
            "schema_similarity": None,
            "matched_column_count": None,
            "confirmation_mode":
                "invalid_reference",
        }

    comparison = compare_edge_schemas(
        refs["from_table"],
        refs["to_table"],
    )

    status = comparison["status"]
    confirmation_mode = (
        "schema_match"
        if status == "confirmed"
        else "schema_reject"
        if status == "rejected"
        else "schema_unresolved"
    )

    transition = (
        confirm_same_section_schema_transition(
            candidate,
            refs,
            comparison,
            block_index,
            snapshot_pages,
        )
    )

    extra: dict[str, Any] = {}

    if transition is not None:
        status = "confirmed"
        confirmation_mode = (
            transition[
                "confirmation_mode"
            ]
        )
        extra = {
            "transition_x_overlap_ratio":
                transition[
                    "x_overlap_ratio"
                ],
            "transition_width_similarity":
                transition[
                    "width_similarity"
                ],
            "transition_from_bottom_gap":
                transition[
                    "from_bottom_gap"
                ],
            "transition_to_top_gap":
                transition[
                    "to_top_gap"
                ],
        }

    return {
        "candidate_id": refs["candidate_id"],
        "candidate_source":
            candidate.get(
                "candidate_source",
                "stage4",
            ),
        "status": status,
        "confirmation_mode":
            confirmation_mode,
        "schema_similarity":
            comparison.get(
                "schema_similarity"
            ),
        "matched_column_count":
            comparison.get(
                "matched_column_count"
            ),
        "from": refs["from"],
        "to": refs["to"],
        **extra,
    }


def fragment_key(
    fragment: dict[str, Any],
) -> tuple[int, str]:
    return (
        int(fragment["page_number"]),
        str(fragment["block_id"]),
    )


def build_groups_from_confirmed_edges(
    confirmed_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    adjacency: dict[
        tuple[int, str],
        set[tuple[int, str]],
    ] = {}

    fragments: dict[
        tuple[int, str],
        dict[str, Any],
    ] = {}

    edge_ids_by_node: dict[
        tuple[int, str],
        set[str],
    ] = {}

    for edge in confirmed_edges:
        left = edge["from"]
        right = edge["to"]

        left_key = fragment_key(left)
        right_key = fragment_key(right)

        fragments[left_key] = left
        fragments[right_key] = right

        adjacency.setdefault(
            left_key,
            set(),
        ).add(right_key)

        adjacency.setdefault(
            right_key,
            set(),
        ).add(left_key)

        candidate_id = edge.get("candidate_id")

        if isinstance(candidate_id, str):
            edge_ids_by_node.setdefault(
                left_key,
                set(),
            ).add(candidate_id)

            edge_ids_by_node.setdefault(
                right_key,
                set(),
            ).add(candidate_id)

    groups: list[dict[str, Any]] = []
    visited: set[tuple[int, str]] = set()

    for start in sorted(adjacency):
        if start in visited:
            continue

        stack = [start]
        component: list[
            tuple[int, str]
        ] = []
        component_edge_ids: set[str] = set()

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)
            component.append(current)

            component_edge_ids.update(
                edge_ids_by_node.get(
                    current,
                    set(),
                )
            )

            for neighbor in adjacency.get(
                current,
                set(),
            ):
                if neighbor not in visited:
                    stack.append(neighbor)

        component.sort()

        groups.append(
            {
                "group_id":
                    f"logical_table_{len(groups) + 1:03d}",
                "status":
                    "confirmed_association",
                "fragments": [
                    fragments[key]
                    for key in component
                ],
                "source_candidate_ids":
                    sorted(component_edge_ids),
            }
        )

    return groups



def page_document_structure(
    page: dict[str, Any],
) -> dict[str, Any]:
    value = page.get("document_structure")

    if isinstance(value, dict):
        return value

    return {}


def page_section_id(
    page: dict[str, Any],
) -> str | None:
    value = page_document_structure(
        page
    ).get("section_id")

    if isinstance(value, str) and value:
        return value

    return None


def page_zone_type(
    page: dict[str, Any],
) -> str | None:
    value = page_document_structure(
        page
    ).get("zone_type")

    if isinstance(value, str) and value:
        return value

    return None


def table_blocks_on_page(
    page: dict[str, Any],
) -> list[dict[str, Any]]:
    result = [
        block
        for block in page.get("blocks", [])
        if (
            isinstance(block, dict)
            and block.get("block_type") == "table"
            and isinstance(
                block.get("block_id"),
                str,
            )
            and isinstance(
                block.get("source_table_index"),
                int,
            )
        )
    ]

    def sort_key(
        block: dict[str, Any],
    ) -> tuple[float, float, str]:
        bbox = normalize_bbox(
            block.get("bbox")
        )

        if bbox is None:
            return (
                float("inf"),
                float("inf"),
                str(block["block_id"]),
            )

        return (
            bbox["top"],
            bbox["x0"],
            str(block["block_id"]),
        )

    result.sort(key=sort_key)
    return result


def candidate_pair_key(
    candidate: dict[str, Any],
) -> tuple[int, str, int, str] | None:
    try:
        return (
            int(candidate["from_page"]),
            str(candidate["from_block_id"]),
            int(candidate["to_page"]),
            str(candidate["to_block_id"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def discover_same_section_fallback_candidates(
    structure: dict[str, Any],
    existing_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    补 Stage 4 的保守召回盲区。

    某些跨页表格虽然属于同一逻辑表，但上一页 table 并没有
    真正贴住页面底部，所以 Stage 4 不一定生成 boundary candidate。

    fallback 仅在以下条件成立时补候选：
      1. 两页物理相邻；
      2. section_id 相同；
      3. 两页属于同一已观察章节；
      4. 两页都有 table block；
      5. 只连接上一页最后一个 table 与下一页第一个 table；
      6. Stage 4 尚未生成同一对 block 的 candidate。

    这里只补 candidate。
    是否真属于同一张表，仍由原有 schema confirmation 判断。
    """
    page_index: dict[int, dict[str, Any]] = {}

    for page in structure.get("pages", []):
        if not isinstance(page, dict):
            continue

        try:
            page_number = int(
                page["page_number"]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        page_index[page_number] = page

    existing_keys = {
        key
        for key in (
            candidate_pair_key(candidate)
            for candidate in existing_candidates
        )
        if key is not None
    }

    supplemental: list[dict[str, Any]] = []

    for page_number in sorted(page_index):
        next_page_number = page_number + 1

        page = page_index[page_number]
        next_page = page_index.get(
            next_page_number
        )

        if next_page is None:
            continue

        section_id = page_section_id(page)

        if (
            section_id is None
            or section_id
            != page_section_id(next_page)
        ):
            continue

        from_tables = table_blocks_on_page(
            page
        )
        to_tables = table_blocks_on_page(
            next_page
        )

        if not from_tables or not to_tables:
            continue

        from_block = from_tables[-1]
        to_block = to_tables[0]

        key = (
            page_number,
            str(from_block["block_id"]),
            next_page_number,
            str(to_block["block_id"]),
        )

        if key in existing_keys:
            continue

        supplemental.append(
            {
                "candidate_id": (
                    "stage5_fallback_"
                    f"p{page_number:04d}_"
                    f"{from_block['block_id']}_"
                    f"p{next_page_number:04d}_"
                    f"{to_block['block_id']}"
                ),
                "candidate_type":
                    "table_continuation",
                "candidate_source":
                    "stage5_same_section_fallback",
                "from_page":
                    page_number,
                "from_block_id":
                    from_block["block_id"],
                "to_page":
                    next_page_number,
                "to_block_id":
                    to_block["block_id"],
                "same_section":
                    True,
            }
        )

        existing_keys.add(key)

    return supplemental


def build_cross_page_table_groups(
    structure: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    stage4_candidates = structure.get(
        "cross_page_table_candidates",
        [],
    )

    if not isinstance(stage4_candidates, list):
        stage4_candidates = []

    stage4_candidates = [
        candidate
        for candidate in stage4_candidates
        if isinstance(candidate, dict)
    ]

    supplemental_candidates = (
        discover_same_section_fallback_candidates(
            structure,
            stage4_candidates,
        )
    )

    candidates = (
        stage4_candidates
        + supplemental_candidates
    )

    block_index = index_structure_blocks(
        structure
    )

    edge_results = [
        confirm_cross_page_edge(
            candidate,
            block_index,
            snapshot_pages,
        )
        for candidate in candidates
    ]

    confirmed_edges = [
        edge
        for edge in edge_results
        if edge["status"] == "confirmed"
    ]

    groups = build_groups_from_confirmed_edges(
        confirmed_edges
    )

    return {
        "stage4_candidate_count":
            len(stage4_candidates),
        "supplemental_candidate_count":
            len(supplemental_candidates),
        "candidate_count":
            len(candidates),
        "confirmed_count": sum(
            edge["status"] == "confirmed"
            for edge in edge_results
        ),
        "rejected_count": sum(
            edge["status"] == "rejected"
            for edge in edge_results
        ),
        "unresolved_count": sum(
            edge["status"] == "unresolved"
            for edge in edge_results
        ),
        "invalid_reference_count": sum(
            edge["status"] == "invalid_reference"
            for edge in edge_results
        ),
        "edge_results": edge_results,
        "groups": groups,
    }


# =============================================================================
# Stage 5.3.2 — Cross-page boundary row continuation detection
# =============================================================================


ROW_CONTEXT_WINDOW = 5

# 只判断明显情况，灰区保留 UNRESOLVED。
ROW_PARTIAL_THRESHOLD = 0.72
ROW_COMPLETE_THRESHOLD = 0.85

# PDF point 坐标下的边界判定。
EDGE_NEAR_MARGIN = 10.0
EDGE_CLEAR_MARGIN = 12.0
EDGE_OVERFLOW_TOL = 1.0

# 底部伪 row：只允许非常稀疏的边界行进入过滤。
# 不看具体字符串，不识别页码格式。
ARTIFACT_MAX_NONEMPTY_CELLS = 1
ARTIFACT_MIN_GEOMETRIC_CELLS = 3


def extracted_data_rows(
    table: dict[str, Any],
) -> list[list[str]]:
    data = table.get("extracted_data")

    if not isinstance(data, list):
        return []

    result: list[list[str]] = []

    for row in data:
        if isinstance(row, list):
            result.append(
                [
                    clean_text(cell)
                    for cell in row
                ]
            )
        else:
            result.append(
                [clean_text(row)]
            )

    return result


def row_geometry_bbox(
    raw_cells: list[Any],
) -> dict[str, float] | None:
    boxes = [
        bbox
        for bbox in (
            normalize_bbox(cell)
            for cell in raw_cells
        )
        if bbox is not None
    ]

    if not boxes:
        return None

    return {
        "x0": min(bbox["x0"] for bbox in boxes),
        "top": min(bbox["top"] for bbox in boxes),
        "x1": max(bbox["x1"] for bbox in boxes),
        "bottom": max(bbox["bottom"] for bbox in boxes),
    }


def row_partition_signature_from_cells(
    raw_cells: list[Any],
) -> list[float] | None:
    boxes = [
        bbox
        for bbox in (
            normalize_bbox(cell)
            for cell in raw_cells
        )
        if bbox is not None
    ]

    if len(boxes) < 2:
        return None

    boxes.sort(
        key=lambda bbox: (
            bbox["x0"],
            bbox["x1"],
        )
    )

    widths = [
        bbox["x1"] - bbox["x0"]
        for bbox in boxes
    ]

    total = sum(widths)

    if total <= 0:
        return None

    return [
        width / total
        for width in widths
    ]


def table_row_records(
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    把 Stage 1 的 row geometry 与 extracted_data 对齐。

    只使用：
      - cell bbox
      - cell 是否为空

    不使用具体文本语义。
    """
    geometry_rows = table.get("rows")
    data_rows = extracted_data_rows(table)

    if not isinstance(geometry_rows, list):
        return []

    records: list[dict[str, Any]] = []

    for row_index, geometry_row in enumerate(
        geometry_rows
    ):
        if not isinstance(geometry_row, dict):
            continue

        raw_cells = geometry_row.get("cells")

        if not isinstance(raw_cells, list):
            continue

        bbox = row_geometry_bbox(raw_cells)

        if bbox is None:
            continue

        data_row = (
            data_rows[row_index]
            if row_index < len(data_rows)
            else []
        )

        geometric_cell_count = 0
        nonempty_cell_count = 0

        for cell_index, raw_cell in enumerate(
            raw_cells
        ):
            if normalize_bbox(raw_cell) is None:
                continue

            geometric_cell_count += 1

            value = (
                data_row[cell_index]
                if cell_index < len(data_row)
                else ""
            )

            if clean_text(value):
                nonempty_cell_count += 1

        if geometric_cell_count <= 0:
            continue

        records.append(
            {
                "row_index": row_index,
                "bbox": bbox,
                "geometric_cell_count":
                    geometric_cell_count,
                "nonempty_cell_count":
                    nonempty_cell_count,
                "fill_ratio":
                    nonempty_cell_count
                    / geometric_cell_count,
                "partition_signature":
                    row_partition_signature_from_cells(
                        raw_cells
                    ),
            }
        )

    return records


def row_record_schema_similarity(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float | None:
    left_signature = left.get(
        "partition_signature"
    )
    right_signature = right.get(
        "partition_signature"
    )

    if not isinstance(left_signature, list):
        return None

    if not isinstance(right_signature, list):
        return None

    return partition_similarity(
        left_signature,
        right_signature,
    )


def nonempty_record_indices(
    records: list[dict[str, Any]],
) -> list[int]:
    return [
        index
        for index, record in enumerate(records)
        if record["nonempty_cell_count"] > 0
    ]


def local_reference_fill(
    records: list[dict[str, Any]],
    boundary_index: int,
    side: str,
) -> float | None:
    """
    只拿“同 schema”的邻近 row 做参照。

    避免标题行、合并行、另一种子表结构污染基准。
    """
    target = records[boundary_index]

    if side == "tail":
        candidates = records[
            max(0, boundary_index - ROW_CONTEXT_WINDOW):
            boundary_index
        ]
    elif side == "head":
        candidates = records[
            boundary_index + 1:
            boundary_index + 1 + ROW_CONTEXT_WINDOW
        ]
    else:
        raise ValueError(f"未知 side：{side}")

    comparable: list[float] = []

    for candidate in candidates:
        if candidate["nonempty_cell_count"] <= 0:
            continue

        similarity = row_record_schema_similarity(
            target,
            candidate,
        )

        if (
            similarity is not None
            and similarity >= SCHEMA_CONFIRM_THRESHOLD
        ):
            comparable.append(
                candidate["fill_ratio"]
            )

    if not comparable:
        return None

    return float(statistics.median(comparable))


def build_boundary_profile(
    records: list[dict[str, Any]],
    boundary_index: int,
    page_height: float,
    side: str,
) -> dict[str, Any]:
    record = records[boundary_index]

    reference_fill = local_reference_fill(
        records,
        boundary_index,
        side,
    )

    if (
        reference_fill is None
        or reference_fill <= 0
    ):
        relative_fill = None
    else:
        relative_fill = (
            record["fill_ratio"]
            / reference_fill
        )

    bbox = record["bbox"]

    if side == "tail":
        edge_distance = (
            page_height - bbox["bottom"]
        )
        near_edge = (
            bbox["bottom"]
            >= page_height - EDGE_NEAR_MARGIN
        )
        overflow = (
            bbox["bottom"]
            > page_height + EDGE_OVERFLOW_TOL
        )
        clear_of_edge = (
            bbox["bottom"]
            <= page_height - EDGE_CLEAR_MARGIN
        )
    else:
        edge_distance = bbox["top"]
        near_edge = (
            bbox["top"] <= EDGE_NEAR_MARGIN
        )
        overflow = (
            bbox["top"] < -EDGE_OVERFLOW_TOL
        )
        clear_of_edge = (
            bbox["top"] >= EDGE_CLEAR_MARGIN
        )

    return {
        "row_index": record["row_index"],
        "bbox": bbox,
        "geometric_cell_count":
            record["geometric_cell_count"],
        "nonempty_cell_count":
            record["nonempty_cell_count"],
        "fill_ratio": record["fill_ratio"],
        "reference_fill_ratio":
            reference_fill,
        "relative_fill": relative_fill,
        "edge_distance": edge_distance,
        "near_page_edge": near_edge,
        "crosses_page_edge": overflow,
        "clear_of_page_edge": clear_of_edge,
    }


def previous_nonempty_record_index(
    records: list[dict[str, Any]],
    index: int,
) -> int | None:
    for candidate in range(
        index - 1,
        -1,
        -1,
    ):
        if (
            records[candidate][
                "nonempty_cell_count"
            ]
            > 0
        ):
            return candidate

    return None


def first_nonempty_record_index(
    records: list[dict[str, Any]],
) -> int | None:
    for index, record in enumerate(records):
        if record["nonempty_cell_count"] > 0:
            return index

    return None


def last_nonempty_record_index(
    records: list[dict[str, Any]],
) -> int | None:
    for index in range(
        len(records) - 1,
        -1,
        -1,
    ):
        if (
            records[index][
                "nonempty_cell_count"
            ]
            > 0
        ):
            return index

    return None


def should_skip_tail_artifact(
    tail_record: dict[str, Any],
    head_record: dict[str, Any],
    from_page_height: float,
) -> bool:
    """
    排除一种常见的底部伪 row：

    - 最后一行只有极少 cell 有内容；
    - 该行几何范围已经贴到/越过页面底部；
    - 下一页第一条真实表格 row 明显从页面内部开始。

    这能避免页脚、页码等被 table extractor 包进最后一行后，
    被误当成跨页断行。

    注意：
    不识别“1/29”这类字符串，只看几何与稀疏程度。
    """
    return (
        tail_record["nonempty_cell_count"]
        <= ARTIFACT_MAX_NONEMPTY_CELLS
        and tail_record["geometric_cell_count"]
        >= ARTIFACT_MIN_GEOMETRIC_CELLS
        and tail_record["bbox"]["bottom"]
        >= from_page_height - EDGE_OVERFLOW_TOL
        and head_record["bbox"]["top"]
        >= EDGE_CLEAR_MARGIN
    )


def classify_boundary_row_relation(
    from_table: dict[str, Any],
    to_table: dict[str, Any],
    from_page_height: float,
    to_page_height: float,
) -> dict[str, Any]:
    """
    Stage 5.3.2 v0.3.3

    只判断：
      ROW_CONTINUATION
      NEW_ROW
      UNRESOLVED

    核心证据：
      1. 边界 row 的真实 cell geometry；
      2. row 是否贴近/越过页面边界；
      3. row 相对同 schema 邻近行是否明显不完整；
      4. 底部极稀疏伪 row 是否应先排除。

    不读取具体文本语义。
    """
    from_records = table_row_records(
        from_table
    )
    to_records = table_row_records(
        to_table
    )

    tail_index = last_nonempty_record_index(
        from_records
    )
    head_index = first_nonempty_record_index(
        to_records
    )

    if (
        tail_index is None
        or head_index is None
    ):
        return {
            "status": "UNRESOLVED",
            "from_boundary": None,
            "to_boundary": None,
            "skipped_tail_artifact": None,
        }

    tail_record = from_records[tail_index]
    head_record = to_records[head_index]

    skipped_tail_artifact = None

    if should_skip_tail_artifact(
        tail_record,
        head_record,
        from_page_height,
    ):
        previous_index = (
            previous_nonempty_record_index(
                from_records,
                tail_index,
            )
        )

        if previous_index is not None:
            skipped_tail_artifact = {
                "row_index":
                    tail_record["row_index"],
                "bbox":
                    tail_record["bbox"],
                "geometric_cell_count":
                    tail_record[
                        "geometric_cell_count"
                    ],
                "nonempty_cell_count":
                    tail_record[
                        "nonempty_cell_count"
                    ],
            }

            tail_index = previous_index
            tail_record = from_records[
                tail_index
            ]

    from_profile = build_boundary_profile(
        from_records,
        tail_index,
        from_page_height,
        "tail",
    )

    to_profile = build_boundary_profile(
        to_records,
        head_index,
        to_page_height,
        "head",
    )

    from_relative = from_profile.get(
        "relative_fill"
    )
    to_relative = to_profile.get(
        "relative_fill"
    )

    # 强证据：
    # 两侧 row 都真实跨出物理页面边界，基本可以确认是同一 row 被切开。
    strong_geometry_split = (
        from_profile["crosses_page_edge"]
        and to_profile["crosses_page_edge"]
    )

    from_partial = (
        isinstance(from_relative, (int, float))
        and from_relative <= ROW_PARTIAL_THRESHOLD
        and from_profile["near_page_edge"]
    )

    to_partial = (
        isinstance(to_relative, (int, float))
        and to_relative <= ROW_PARTIAL_THRESHOLD
        and to_profile["near_page_edge"]
    )

    if (
        strong_geometry_split
        or from_partial
        or to_partial
    ):
        status = "ROW_CONTINUATION"

    else:
        from_complete = (
            from_relative is None
            or from_relative
            >= ROW_COMPLETE_THRESHOLD
        )

        to_complete = (
            to_relative is None
            or to_relative
            >= ROW_COMPLETE_THRESHOLD
        )

        # 两边真正的边界 row 都明显位于页面内部，
        # 且没有“不完整”证据，应视为分页处开启新 row。
        if (
            from_profile["clear_of_page_edge"]
            and to_profile["clear_of_page_edge"]
            and from_complete
            and to_complete
        ):
            status = "NEW_ROW"

        # 如果刚刚排除了底部伪 row，而下一页真实 row
        # 又明确从页面内部开始，同样按 NEW_ROW 处理。
        elif (
            skipped_tail_artifact is not None
            and to_profile["clear_of_page_edge"]
            and from_complete
            and to_complete
        ):
            status = "NEW_ROW"

        # 两边都完整，而且都没有贴住分页边界。
        elif (
            from_complete
            and to_complete
            and not from_profile["near_page_edge"]
            and not to_profile["near_page_edge"]
        ):
            status = "NEW_ROW"

        else:
            status = "UNRESOLVED"

    return {
        "status": status,
        "from_boundary": from_profile,
        "to_boundary": to_profile,
        "skipped_tail_artifact":
            skipped_tail_artifact,
    }


def page_height_from_raw(
    raw_page: dict[str, Any] | None,
) -> float | None:
    if not isinstance(raw_page, dict):
        return None

    value = raw_page.get("height")

    if finite_number(value):
        height = float(value)

        if height > 0:
            return height

    return None


def detect_confirmed_boundary_rows(
    snapshot_pages: dict[int, dict[str, Any]],
    edge_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    只处理 Stage 5.3.1 已 CONFIRMED 的边。

    rejected / unresolved 不进入 5.3.2。
    """
    results: list[dict[str, Any]] = []

    for edge in edge_results:
        if edge.get("status") != "confirmed":
            continue

        from_ref = edge.get("from")
        to_ref = edge.get("to")

        if not isinstance(from_ref, dict):
            continue

        if not isinstance(to_ref, dict):
            continue

        from_page_number = int(
            from_ref["page_number"]
        )
        to_page_number = int(
            to_ref["page_number"]
        )

        from_raw_page = snapshot_pages.get(
            from_page_number
        )
        to_raw_page = snapshot_pages.get(
            to_page_number
        )

        from_table = get_raw_table(
            snapshot_pages,
            from_page_number,
            int(from_ref["table_index"]),
        )
        to_table = get_raw_table(
            snapshot_pages,
            to_page_number,
            int(to_ref["table_index"]),
        )

        from_page_height = page_height_from_raw(
            from_raw_page
        )
        to_page_height = page_height_from_raw(
            to_raw_page
        )

        if (
            from_table is None
            or to_table is None
            or from_page_height is None
            or to_page_height is None
        ):
            relation = {
                "status": "UNRESOLVED",
                "from_boundary": None,
                "to_boundary": None,
                "skipped_tail_artifact": None,
            }
        else:
            relation = classify_boundary_row_relation(
                from_table,
                to_table,
                from_page_height,
                to_page_height,
            )

        results.append(
            {
                "candidate_id":
                    edge.get("candidate_id"),
                "from": from_ref,
                "to": to_ref,
                "relation":
                    relation["status"],
                "from_boundary":
                    relation["from_boundary"],
                "to_boundary":
                    relation["to_boundary"],
                "skipped_tail_artifact":
                    relation[
                        "skipped_tail_artifact"
                    ],
            }
        )

    return results


def boundary_relation_counts(
    results: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {
        "ROW_CONTINUATION": 0,
        "NEW_ROW": 0,
        "UNRESOLVED": 0,
    }

    for item in results:
        relation = item.get("relation")

        if relation in counts:
            counts[relation] += 1

    return counts



# =============================================================================
# Stage 5.3.4 — Logical-table boundary footer filter
# =============================================================================


FOOTER_PAGE_MARKER_RE = re.compile(
    r"^\s*(\d{1,4})\s*/\s*(\d{1,4})\s*$"
)

# 只在页面最底部区域寻找页码候选。
FOOTER_BOTTOM_ZONE_RATIO = 0.90

# 页码通常独占一行。允许少量 y 浮动。
FOOTER_LINE_Y_TOLERANCE = 4.0

# 判断页码是否落入某个 cell bbox 时的少量容差。
FOOTER_CELL_TOLERANCE = 2.0


def word_text(
    word: dict[str, Any],
) -> str:
    return clean_text(
        word.get("text")
    ).strip()


def word_center_y(
    word_bbox: dict[str, float],
) -> float:
    return (
        word_bbox["top"]
        + word_bbox["bottom"]
    ) / 2.0


def footer_page_markers(
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    从 Stage1 words 中识别页脚页码。

    只接受：
      - 位于页面底部 10%；
      - 文本形态为 N/M；
      - 该 y 行基本独占（避免把正文中的 3/19 当成页脚）。

    不使用 case/page 特判，也不删除物理页原文。
    """
    height = raw_page.get("height")

    if not finite_number(height):
        return []

    page_height_value = float(height)

    if page_height_value <= 0:
        return []

    words = raw_page.get("words")

    if not isinstance(words, list):
        return []

    normalized_words: list[
        tuple[dict[str, Any], dict[str, float]]
    ] = []

    for word in words:
        if not isinstance(word, dict):
            continue

        bbox = normalize_bbox(word)

        if bbox is None:
            continue

        normalized_words.append(
            (word, bbox)
        )

    bottom_threshold = (
        page_height_value
        * FOOTER_BOTTOM_ZONE_RATIO
    )

    result: list[dict[str, Any]] = []

    for word, bbox in normalized_words:
        if bbox["top"] < bottom_threshold:
            continue

        value = word_text(word)
        match = FOOTER_PAGE_MARKER_RE.fullmatch(
            value
        )

        if match is None:
            continue

        numerator = int(match.group(1))
        denominator = int(match.group(2))

        if (
            numerator < 0
            or denominator <= 0
            or numerator > denominator
        ):
            continue

        center_y = word_center_y(bbox)

        same_line_other_words = 0

        for other_word, other_bbox in normalized_words:
            if other_word is word:
                continue

            other_center_y = word_center_y(
                other_bbox
            )

            if (
                abs(other_center_y - center_y)
                <= FOOTER_LINE_Y_TOLERANCE
                and word_text(other_word)
            ):
                same_line_other_words += 1

        # 真正页脚页码一般独占一行。
        if same_line_other_words > 0:
            continue

        result.append(
            {
                "text": value,
                "numerator": numerator,
                "denominator": denominator,
                "bbox": bbox,
            }
        )

    return result


def point_inside_bbox(
    x: float,
    y: float,
    bbox: dict[str, float],
    tolerance: float = 0.0,
) -> bool:
    return (
        bbox["x0"] - tolerance
        <= x
        <= bbox["x1"] + tolerance
        and bbox["top"] - tolerance
        <= y
        <= bbox["bottom"] + tolerance
    )


def footer_markers_for_cell(
    raw_page: dict[str, Any],
    cell_bbox: dict[str, float],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for marker in footer_page_markers(
        raw_page
    ):
        bbox = marker["bbox"]

        center_x = (
            bbox["x0"] + bbox["x1"]
        ) / 2.0
        center_y = word_center_y(bbox)

        if point_inside_bbox(
            center_x,
            center_y,
            cell_bbox,
            FOOTER_CELL_TOLERANCE,
        ):
            result.append(marker)

    return result


def remove_one_footer_marker(
    value: str,
    numerator: int,
    denominator: int,
) -> tuple[str, bool]:
    """
    只移除一个已由 geometry 确认的 N/M 页脚 token。

    不重排其它文字，不重建 cell。
    """
    text_value = clean_text(value)

    pattern = re.compile(
        rf"(?<![A-Za-z0-9])"
        rf"{numerator}\s*/\s*{denominator}"
        rf"(?![A-Za-z0-9])"
    )

    match = pattern.search(text_value)

    if match is None:
        return text_value, False

    before = text_value[:match.start()]
    after = text_value[match.end():]

    # 只整理删除点两侧的空白，避免
    # "IEEE 3/29 Transactions" -> "IEEE  Transactions"。
    left = before.rstrip(" \t")
    right = after.lstrip(" \t")

    if (
        left
        and right
        and not left.endswith("\n")
        and not right.startswith("\n")
        and (
            len(left) != len(before)
            or len(right) != len(after)
        )
    ):
        joined = left + " " + right
    else:
        joined = left + right

    return clean_text(joined), True


def clean_logical_cell_footer(
    value: Any,
    raw_page: dict[str, Any],
    cell_bbox: dict[str, float],
) -> tuple[str, int]:
    """
    仅清理 logical-table cell 中，
    geometry 已确认落在该 cell 的页脚 N/M token。
    """
    result = clean_text(value)
    removed = 0

    for marker in footer_markers_for_cell(
        raw_page,
        cell_bbox,
    ):
        result, changed = (
            remove_one_footer_marker(
                result,
                int(marker["numerator"]),
                int(marker["denominator"]),
            )
        )

        if changed:
            removed += 1

    return result, removed


def clean_logical_table_row(
    raw_page: dict[str, Any],
    table: dict[str, Any],
    row_index: int,
    row: list[str],
) -> tuple[list[str], int]:
    """
    对 logical table 的普通 row 做页脚页码清理。

    只改逻辑视图，不改 Stage1 evidence 和 result.md。
    """
    rows = table.get("rows")

    if not isinstance(rows, list):
        return [
            clean_text(cell)
            for cell in row
        ], 0

    if row_index < 0 or row_index >= len(rows):
        return [
            clean_text(cell)
            for cell in row
        ], 0

    geometry_row = rows[row_index]

    if not isinstance(geometry_row, dict):
        return [
            clean_text(cell)
            for cell in row
        ], 0

    raw_cells = geometry_row.get("cells")

    if not isinstance(raw_cells, list):
        return [
            clean_text(cell)
            for cell in row
        ], 0

    cleaned: list[str] = []
    removed = 0

    for cell_index, value in enumerate(row):
        cell_bbox = (
            normalize_bbox(
                raw_cells[cell_index]
            )
            if cell_index < len(raw_cells)
            else None
        )

        if cell_bbox is None:
            cleaned.append(
                clean_text(value)
            )
            continue

        cell_text, cell_removed = (
            clean_logical_cell_footer(
                value,
                raw_page,
                cell_bbox,
            )
        )

        cleaned.append(cell_text)
        removed += cell_removed

    return cleaned, removed


# =============================================================================
# Stage 5.3.3 — Cross-page row / cell recovery
# =============================================================================


CELL_MAP_MIN_SOURCE_COVERAGE = 0.50


def continuation_row_key(
    page_number: int,
    table_index: int,
    row_index: int,
) -> tuple[int, int, int]:
    return (
        int(page_number),
        int(table_index),
        int(row_index),
    )


def raw_row_cells(
    table: dict[str, Any],
    row_index: int,
) -> list[dict[str, Any]]:
    """
    返回一个 row 中真实存在的几何 cell。

    每个 cell 保留：
      - bbox
      - extracted_data 对应文本
      - 原始 cell_index

    不用 chars/words 重写文本。
    """
    rows = table.get("rows")
    data_rows = extracted_data_rows(table)

    if not isinstance(rows, list):
        return []

    if row_index < 0 or row_index >= len(rows):
        return []

    geometry_row = rows[row_index]

    if not isinstance(geometry_row, dict):
        return []

    raw_cells = geometry_row.get("cells")

    if not isinstance(raw_cells, list):
        return []

    data_row = (
        data_rows[row_index]
        if row_index < len(data_rows)
        else []
    )

    result: list[dict[str, Any]] = []

    for cell_index, raw_cell in enumerate(raw_cells):
        bbox = normalize_bbox(raw_cell)

        if bbox is None:
            continue

        value = (
            data_row[cell_index]
            if cell_index < len(data_row)
            else ""
        )

        result.append(
            {
                "cell_index": cell_index,
                "bbox": bbox,
                "text": clean_text(value),
            }
        )

    result.sort(
        key=lambda item: (
            item["bbox"]["x0"],
            item["bbox"]["x1"],
        )
    )

    return result


def horizontal_source_coverage(
    source_bbox: dict[str, float],
    target_bbox: dict[str, float],
) -> float:
    source_width = (
        source_bbox["x1"]
        - source_bbox["x0"]
    )

    if source_width <= 0:
        return 0.0

    overlap = max(
        0.0,
        min(
            source_bbox["x1"],
            target_bbox["x1"],
        )
        - max(
            source_bbox["x0"],
            target_bbox["x0"],
        ),
    )

    return overlap / source_width


def choose_merge_layout(
    fragment_cells: list[
        list[dict[str, Any]]
    ],
) -> list[dict[str, Any]]:
    """
    用“有效几何 cell 更少”的边界 row 作为合并布局。

    原因：
    pdfplumber 对跨页/合并单元格常会产生：
      6 格 <-> 12 格
      8 格 <-> 12 格

    有效几何 cell 更少的一侧通常代表更紧凑的真实逻辑列。
    相同数量时选更早的 fragment，保持稳定。
    """
    usable = [
        cells
        for cells in fragment_cells
        if cells
    ]

    if not usable:
        return []

    chosen = min(
        usable,
        key=lambda cells: len(cells),
    )

    return [
        {
            "bbox": dict(cell["bbox"]),
            "texts": [],
        }
        for cell in chosen
    ]


def merge_continuation_fragments(
    fragments: list[dict[str, Any]],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    将同一逻辑 row 的多个分页 fragment 合并为一行。

    关键原则：
    - 只对 Stage 5.3.2 已确认的 ROW_CONTINUATION 使用；
    - cell 对齐仅靠横向 geometry；
    - 文本片段按物理页顺序拼在同一个 cell 中；
    - 不做中文/英文智能断词修复，页间文本用换行连接；
    - 映射不了的 fragment 不丢弃，记录为 partial。
    """
    prepared: list[dict[str, Any]] = []
    all_fragment_cells: list[
        list[dict[str, Any]]
    ] = []

    for fragment in fragments:
        page_number = int(fragment["page_number"])
        table_index = int(fragment["table_index"])
        row_index = int(fragment["row_index"])

        table = get_raw_table(
            snapshot_pages,
            page_number,
            table_index,
        )

        if table is None:
            continue

        cells = raw_row_cells(
            table,
            row_index,
        )

        raw_page = snapshot_pages.get(
            page_number
        )

        if isinstance(raw_page, dict):
            cleaned_cells: list[
                dict[str, Any]
            ] = []
            footer_removed_count = 0

            for cell in cells:
                cleaned_text, removed = (
                    clean_logical_cell_footer(
                        cell["text"],
                        raw_page,
                        cell["bbox"],
                    )
                )

                cleaned_cell = dict(cell)
                cleaned_cell["text"] = (
                    cleaned_text
                )
                cleaned_cells.append(
                    cleaned_cell
                )
                footer_removed_count += removed

            cells = cleaned_cells
        else:
            footer_removed_count = 0

        prepared.append(
            {
                "page_number": page_number,
                "table_index": table_index,
                "row_index": row_index,
                "cells": cells,
                "footer_removed_count":
                    footer_removed_count,
            }
        )
        all_fragment_cells.append(cells)

    layout = choose_merge_layout(
        all_fragment_cells
    )

    if not layout:
        return {
            "status": "unresolved",
            "cells": [],
            "source_fragments": [
                {
                    "page_number":
                        item["page_number"],
                    "table_index":
                        item["table_index"],
                    "row_index":
                        item["row_index"],
                }
                for item in prepared
            ],
            "unmapped_fragment_count": 0,
            "source_cell_mappings": [],
            "footer_removed_count": sum(
                item.get(
                    "footer_removed_count",
                    0,
                )
                for item in prepared
            ),
        }

    unmapped: list[dict[str, Any]] = []
    source_cell_mappings: list[dict[str, int]] = []

    for item in prepared:
        for cell in item["cells"]:
            text_value = clean_text(
                cell["text"]
            )

            if not text_value:
                continue

            best_index = None
            best_coverage = 0.0

            for target_index, target in enumerate(
                layout
            ):
                coverage = horizontal_source_coverage(
                    cell["bbox"],
                    target["bbox"],
                )

                if coverage > best_coverage:
                    best_coverage = coverage
                    best_index = target_index

            if (
                best_index is None
                or best_coverage
                < CELL_MAP_MIN_SOURCE_COVERAGE
            ):
                unmapped.append(
                    {
                        "page_number":
                            item["page_number"],
                        "table_index":
                            item["table_index"],
                        "row_index":
                            item["row_index"],
                        "cell_index":
                            cell["cell_index"],
                        "text":
                            text_value,
                    }
                )
                continue

            layout[best_index]["texts"].append(
                text_value
            )
            source_cell_mappings.append(
                {
                    "page_number":
                        int(item["page_number"]),
                    "table_index":
                        int(item["table_index"]),
                    "row_index":
                        int(item["row_index"]),
                    "cell_index":
                        int(cell["cell_index"]),
                    "logical_column_index":
                        int(best_index),
                }
            )

    merged_cells = [
        "\n".join(target["texts"])
        for target in layout
    ]

    return {
        "status": (
            "merged"
            if not unmapped
            else "partial"
        ),
        "cells": merged_cells,
        "source_fragments": [
            {
                "page_number":
                    item["page_number"],
                "table_index":
                    item["table_index"],
                "row_index":
                    item["row_index"],
            }
            for item in prepared
        ],
        "unmapped_fragment_count":
            len(unmapped),
        "unmapped_fragments": unmapped,
        "source_cell_mappings":
            source_cell_mappings,
        "footer_removed_count": sum(
            item.get(
                "footer_removed_count",
                0,
            )
            for item in prepared
        ),
    }


def build_continuation_components(
    boundary_results: list[dict[str, Any]],
) -> list[list[dict[str, int]]]:
    """
    将 ROW_CONTINUATION 边连接成 row-fragment 连通分量。

    这样即使某一条 row 跨 3 页，也只会恢复成一条逻辑 row。
    """
    adjacency: dict[
        tuple[int, int, int],
        set[tuple[int, int, int]],
    ] = {}

    node_payload: dict[
        tuple[int, int, int],
        dict[str, int],
    ] = {}

    for item in boundary_results:
        if item.get("relation") != "ROW_CONTINUATION":
            continue

        from_ref = item.get("from")
        to_ref = item.get("to")
        from_boundary = item.get(
            "from_boundary"
        )
        to_boundary = item.get(
            "to_boundary"
        )

        if not isinstance(from_ref, dict):
            continue

        if not isinstance(to_ref, dict):
            continue

        if not isinstance(from_boundary, dict):
            continue

        if not isinstance(to_boundary, dict):
            continue

        from_key = continuation_row_key(
            int(from_ref["page_number"]),
            int(from_ref["table_index"]),
            int(from_boundary["row_index"]),
        )
        to_key = continuation_row_key(
            int(to_ref["page_number"]),
            int(to_ref["table_index"]),
            int(to_boundary["row_index"]),
        )

        node_payload[from_key] = {
            "page_number": from_key[0],
            "table_index": from_key[1],
            "row_index": from_key[2],
        }
        node_payload[to_key] = {
            "page_number": to_key[0],
            "table_index": to_key[1],
            "row_index": to_key[2],
        }

        adjacency.setdefault(
            from_key,
            set(),
        ).add(to_key)

        adjacency.setdefault(
            to_key,
            set(),
        ).add(from_key)

    components: list[
        list[dict[str, int]]
    ] = []
    visited: set[
        tuple[int, int, int]
    ] = set()

    for start in sorted(adjacency):
        if start in visited:
            continue

        stack = [start]
        component_keys: list[
            tuple[int, int, int]
        ] = []

        while stack:
            current = stack.pop()

            if current in visited:
                continue

            visited.add(current)
            component_keys.append(current)

            for neighbor in adjacency.get(
                current,
                set(),
            ):
                if neighbor not in visited:
                    stack.append(neighbor)

        component_keys.sort()

        components.append(
            [
                node_payload[key]
                for key in component_keys
            ]
        )

    return components


def skipped_artifact_row_keys(
    boundary_results: list[dict[str, Any]],
) -> set[tuple[int, int, int]]:
    """
    Stage 5.3.2 已明确识别出的底部伪 row，
    在 logical table 中不再当作表格数据行。

    物理 pages 仍完整保留，不删除原始内容。
    """
    result: set[
        tuple[int, int, int]
    ] = set()

    for item in boundary_results:
        artifact = item.get(
            "skipped_tail_artifact"
        )
        from_ref = item.get("from")

        if not isinstance(artifact, dict):
            continue

        if not isinstance(from_ref, dict):
            continue

        row_index = artifact.get(
            "row_index"
        )

        if not isinstance(row_index, int):
            continue

        result.add(
            continuation_row_key(
                int(from_ref["page_number"]),
                int(from_ref["table_index"]),
                row_index,
            )
        )

    return result


def build_cross_page_logical_tables(
    groups: list[dict[str, Any]],
    boundary_results: list[dict[str, Any]],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    构造跨页逻辑表。

    pages/result.md 继续保留物理页视图；
    真正恢复后的跨页表只写入 cross_page_logical_tables。
    """
    components = build_continuation_components(
        boundary_results
    )

    node_to_component: dict[
        tuple[int, int, int],
        int,
    ] = {}

    recovered_components: dict[
        int,
        dict[str, Any],
    ] = {}

    for component_index, component in enumerate(
        components
    ):
        merged = merge_continuation_fragments(
            component,
            snapshot_pages,
        )

        recovered_components[
            component_index
        ] = merged

        for fragment in component:
            key = continuation_row_key(
                fragment["page_number"],
                fragment["table_index"],
                fragment["row_index"],
            )
            node_to_component[
                key
            ] = component_index

    artifact_keys = skipped_artifact_row_keys(
        boundary_results
    )

    logical_tables: list[dict[str, Any]] = []
    emitted_components: set[int] = set()

    for group in groups:
        logical_rows: list[list[str]] = []
        logical_row_sources: list[dict[str, Any]] = []
        merged_row_count = 0
        partial_merge_count = 0
        footer_removed_count = 0

        for fragment in group.get(
            "fragments",
            [],
        ):
            if not isinstance(fragment, dict):
                continue

            page_number = int(
                fragment["page_number"]
            )
            table_index = int(
                fragment["table_index"]
            )

            table = get_raw_table(
                snapshot_pages,
                page_number,
                table_index,
            )

            if table is None:
                continue

            raw_page_for_recovery = (
                snapshot_pages.get(
                    page_number
                )
            )

            if isinstance(
                raw_page_for_recovery,
                dict,
            ):
                rows, _ = (
                    recover_table_bottom_overflow(
                        raw_page_for_recovery,
                        table,
                    )
                )
            else:
                rows = extracted_data_rows(
                    table
                )

            for row_index, row in enumerate(rows):
                key = continuation_row_key(
                    page_number,
                    table_index,
                    row_index,
                )

                if key in artifact_keys:
                    continue

                component_index = (
                    node_to_component.get(key)
                )

                if component_index is None:
                    raw_page = (
                        snapshot_pages.get(
                            page_number
                        )
                    )

                    if isinstance(
                        raw_page,
                        dict,
                    ):
                        cleaned_row, removed = (
                            clean_logical_table_row(
                                raw_page,
                                table,
                                row_index,
                                row,
                            )
                        )
                    else:
                        cleaned_row = [
                            clean_text(cell)
                            for cell in row
                        ]
                        removed = 0

                    logical_rows.append(
                        cleaned_row
                    )
                    logical_row_sources.append(
                        {
                            "start_page":
                                page_number,
                            "source_fragments": [
                                {
                                    "page_number":
                                        page_number,
                                    "table_index":
                                        table_index,
                                    "row_index":
                                        row_index,
                                }
                            ],
                            "merged":
                                False,
                        }
                    )
                    footer_removed_count += (
                        removed
                    )
                    continue

                if (
                    component_index
                    in emitted_components
                ):
                    continue

                recovered = recovered_components[
                    component_index
                ]

                logical_rows.append(
                    list(
                        recovered.get(
                            "cells",
                            [],
                        )
                    )
                )
                recovered_sources = [
                    {
                        "page_number":
                            int(item["page_number"]),
                        "table_index":
                            int(item["table_index"]),
                        "row_index":
                            int(item["row_index"]),
                    }
                    for item in recovered.get(
                        "source_fragments",
                        [],
                    )
                    if isinstance(item, dict)
                ]
                logical_row_sources.append(
                    {
                        "start_page": (
                            min(
                                item["page_number"]
                                for item
                                in recovered_sources
                            )
                            if recovered_sources
                            else page_number
                        ),
                        "source_fragments":
                            recovered_sources,
                        "merged":
                            True,
                        "merge_status":
                            recovered.get(
                                "status"
                            ),
                        "source_cell_mappings":
                            recovered.get(
                                "source_cell_mappings",
                                [],
                            ),
                    }
                )

                emitted_components.add(
                    component_index
                )
                merged_row_count += 1
                footer_removed_count += int(
                    recovered.get(
                        "footer_removed_count",
                        0,
                    )
                )

                if (
                    recovered.get("status")
                    != "merged"
                ):
                    partial_merge_count += 1

        logical_tables.append(
            {
                "group_id":
                    group.get("group_id"),
                "source_pages": [
                    int(item["page_number"])
                    for item in group.get(
                        "fragments",
                        []
                    )
                    if isinstance(item, dict)
                ],
                "merged_row_count":
                    merged_row_count,
                "partial_merge_count":
                    partial_merge_count,
                "footer_removed_count":
                    footer_removed_count,
                "source_fragments": [
                    {
                        "page_number":
                            int(item["page_number"]),
                        "table_index":
                            int(item["table_index"]),
                        "block_id":
                            item.get("block_id"),
                    }
                    for item in group.get(
                        "fragments",
                        []
                    )
                    if isinstance(item, dict)
                ],
                "rows": logical_rows,
                "row_sources":
                    logical_row_sources,
            }
        )

    return {
        "logical_tables": logical_tables,
        "merged_row_count": sum(
            table["merged_row_count"]
            for table in logical_tables
        ),
        "partial_merge_count": sum(
            table["partial_merge_count"]
            for table in logical_tables
        ),
        "footer_removed_count": sum(
            table["footer_removed_count"]
            for table in logical_tables
        ),
        "component_count":
            len(components),
    }


def render_cross_page_logical_tables(
    logical_tables: list[dict[str, Any]],
) -> str:
    """
    仅用于人工检查 Stage 5.3.3 的恢复结果。

    不替代 result.md。
    result.md 仍然是逐物理页视图。
    """
    lines: list[str] = []

    for table in logical_tables:
        group_id = table.get(
            "group_id",
            "logical_table",
        )

        lines.append(
            f"# {group_id}"
        )
        lines.append("")

        pages = table.get(
            "source_pages",
            [],
        )

        if pages:
            lines.append(
                "来源页："
                + " → ".join(
                    str(page)
                    for page in pages
                )
            )
            lines.append("")

        rendered = render_table_rows(
            table.get("rows", [])
        )

        if rendered:
            lines.append(rendered)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# =============================================================================
# Page composition
# =============================================================================


def block_sort_key(
    block: dict[str, Any],
) -> tuple[int, float, float]:
    order = block.get("spatial_order")

    if isinstance(order, int):
        return order, 0.0, 0.0

    bbox = normalize_bbox(block.get("bbox"))

    if bbox is None:
        return 999999, 0.0, 0.0

    return (
        999999,
        bbox["top"],
        bbox["x0"],
    )



def _point_inside_bbox(x: float, y: float, bbox: dict[str, float]) -> bool:
    return bbox["x0"] <= x <= bbox["x1"] and bbox["top"] <= y <= bbox["bottom"]


def _checkbox_marker(state: str) -> str:
    if state == "checked":
        return "☑"
    if state == "unchecked":
        return "☐"
    return "[?]"


def annotate_table_rows_with_checkbox_controls(
    raw_table: dict[str, Any],
    rows: list[list[str]],
    controls: list[dict[str, Any]],
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """
    把 Stage4 已确认的 native vector checkbox 状态物化到 Stage5 table rows。

    只使用：
      - checkbox / label 几何；
      - Stage1 table cell 几何；
      - label 原生文本。

    不读取业务字段名，不按 case/page/string 特判。
    """
    if not rows or not isinstance(controls, list):
        return rows, []

    table_bbox = normalize_bbox(raw_table.get("bbox"))
    geometry_rows = raw_table.get("rows")
    if table_bbox is None or not isinstance(geometry_rows, list):
        return rows, []

    result = [list(row) for row in rows]
    annotations: list[dict[str, Any]] = []

    for control in controls:
        if not isinstance(control, dict):
            continue
        control_bbox = normalize_bbox(control.get("bbox"))
        label_bbox = normalize_bbox(control.get("label_bbox"))
        label = clean_text(control.get("label_text"))
        state = str(control.get("state") or "unknown")
        if control_bbox is None or label_bbox is None or not label:
            continue

        cx = (control_bbox["x0"] + control_bbox["x1"]) / 2.0
        cy = (control_bbox["top"] + control_bbox["bottom"]) / 2.0
        if not _point_inside_bbox(cx, cy, table_bbox):
            continue

        lx = (label_bbox["x0"] + label_bbox["x1"]) / 2.0
        ly = (label_bbox["top"] + label_bbox["bottom"]) / 2.0

        cell_hits: list[tuple[float, int, int]] = []
        for row_index, geometry_row in enumerate(geometry_rows):
            if not isinstance(geometry_row, dict):
                continue
            raw_cells = geometry_row.get("cells")
            if not isinstance(raw_cells, list):
                continue
            for cell_index, raw_cell in enumerate(raw_cells):
                cell_bbox = normalize_bbox(raw_cell)
                if cell_bbox is None:
                    continue
                if _point_inside_bbox(lx, ly, cell_bbox) or _point_inside_bbox(cx, cy, cell_bbox):
                    area = max(1e-9, (cell_bbox["x1"] - cell_bbox["x0"]) * (cell_bbox["bottom"] - cell_bbox["top"]))
                    cell_hits.append((area, row_index, cell_index))

        target: tuple[int, int] | None = None
        if cell_hits:
            _, row_index, cell_index = min(cell_hits)
            if row_index < len(result) and cell_index < len(result[row_index]):
                target = (row_index, cell_index)

        # 几何 cell 缺失时，允许唯一文本 cell 兜底；仍然只匹配真实 label。
        if target is None:
            text_hits: list[tuple[int, int]] = []
            for row_index, row in enumerate(result):
                for cell_index, cell in enumerate(row):
                    lines = [clean_text(line) for line in str(cell or "").splitlines()]
                    if label in lines:
                        text_hits.append((row_index, cell_index))
            if len(text_hits) == 1:
                target = text_hits[0]

        if target is None:
            continue

        row_index, cell_index = target
        cell_text = str(result[row_index][cell_index] or "")
        raw_lines = cell_text.splitlines()
        marker = _checkbox_marker(state)
        changed = False
        new_lines: list[str] = []
        for line in raw_lines:
            if clean_text(line) == label:
                if not line.lstrip().startswith(("☑", "☐", "[?]")):
                    new_lines.append(f"{marker} {line.strip()}")
                    changed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        if not changed and clean_text(cell_text) == label:
            new_lines = [f"{marker} {label}"]
            changed = True

        if not changed:
            continue

        result[row_index][cell_index] = "\n".join(new_lines)
        annotations.append({
            "control_id": control.get("control_id"),
            "state": state,
            "label_text": label,
            "row_index": row_index,
            "cell_index": cell_index,
            "source": "stage4_native_vector_checkbox",
        })

    return result, annotations


def build_page_items(
    structure_page: dict[str, Any],
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = structure_page.get("blocks", [])

    if not isinstance(blocks, list):
        blocks = []

    table_blocks = [
        block
        for block in blocks
        if (
            isinstance(block, dict)
            and block.get("block_type") == "table"
        )
    ]

    gridless_candidates = structure_page.get(
        "gridless_table_candidates",
        [],
    )
    if not isinstance(gridless_candidates, list):
        gridless_candidates = []

    checkbox_controls = structure_page.get(
        "checkbox_controls",
        [],
    )
    if not isinstance(checkbox_controls, list):
        checkbox_controls = []

    # 无任何表格结构页：Stage5 不重新组织普通正文。
    if not table_blocks and not gridless_candidates:
        native_text = clean_text(
            raw_page.get("native_text")
        )

        if native_text:
            return [
                {
                    "type": "text",
                    "text": native_text,
                }
            ]

        fallback_items: list[dict[str, Any]] = []

        for block in sorted(
            (
                item
                for item in blocks
                if isinstance(item, dict)
            ),
            key=block_sort_key,
        ):
            if block.get("block_type") != "text":
                continue

            text = clean_text(block.get("text"))

            if text:
                fallback_items.append(
                    {
                        "type": "text",
                        "text": text,
                        "source_word_indices": [
                            value
                            for value in block.get("source_word_indices", [])
                            if isinstance(value, int)
                        ],
                        "bbox": block.get("bbox"),
                    }
                )

        return fallback_items

    raw_tables = index_raw_tables(raw_page)

    # 先完成当前页所有 ruled table overflow recovery，
    # 再决定哪些 Stage4 text block 已被 table ownership 吸收。
    recovered_tables: dict[int, dict[str, Any]] = {}
    claimed_word_indices: set[int] = set()

    for block in table_blocks:
        source_index = block.get("source_table_index")

        if not isinstance(source_index, int):
            continue

        raw_table = raw_tables.get(source_index)

        if raw_table is None:
            continue

        recovered_rows, recoveries = recover_table_bottom_overflow(
            raw_page,
            raw_table,
        )

        recovered_tables[source_index] = {
            "rows": recovered_rows,
            "recoveries": recoveries,
        }

        claimed_word_indices.update(
            recovered_word_index_set(recoveries)
        )

    # Stage4 v0.2.5+ 的无线框表格 candidate 已经明确记录 native word ownership。
    # Stage5 直接接收这些二维 row/cell，不按字段名或具体 glyph 特判。
    for candidate in gridless_candidates:
        if not isinstance(candidate, dict):
            continue
        for value in candidate.get("source_word_indices", []):
            if isinstance(value, int) and value >= 0:
                claimed_word_indices.add(value)

    items: list[dict[str, Any]] = []

    for block in sorted(
        (
            item
            for item in blocks
            if isinstance(item, dict)
        ),
        key=block_sort_key,
    ):
        block_type = block.get("block_type")

        if block_type == "text":
            source_word_indices = [
                value
                for value in block.get("source_word_indices", [])
                if isinstance(value, int)
            ]

            if (
                source_word_indices
                and set(source_word_indices).issubset(claimed_word_indices)
            ):
                continue

            text = clean_text(block.get("text"))

            if text:
                items.append(
                    {
                        "type": "text",
                        "text": text,
                        "source_word_indices": source_word_indices,
                        "bbox": block.get("bbox"),
                    }
                )

            continue

        if block_type != "table":
            continue

        source_index = block.get("source_table_index")

        if not isinstance(source_index, int):
            continue

        raw_table = raw_tables.get(source_index)

        if raw_table is None:
            continue

        recovered = recovered_tables.get(source_index)

        if recovered is None:
            rows = extracted_rows(raw_table)
            recoveries: list[dict[str, Any]] = []
        else:
            rows = recovered["rows"]
            recoveries = recovered["recoveries"]

        rows, checkbox_annotations = annotate_table_rows_with_checkbox_controls(
            raw_table=raw_table,
            rows=rows,
            controls=checkbox_controls,
        )

        item = {
            "type": "table",
            "table_index": source_index,
            "table_origin": "stage1_ruled_table_candidate",
            "rows": rows,
            "bbox": block.get("bbox") or raw_table.get("bbox"),
        }

        if checkbox_annotations:
            item["checkbox_annotations"] = checkbox_annotations

        if recoveries:
            item["boundary_overflow_recoveries"] = recoveries

        items.append(item)

    # 补充 Stage4 gridless candidates。
    # synthetic table_index 只在当前物理页内作为稳定引用使用，负数避免与 Stage1 table index 冲突。
    for fallback_index, candidate in enumerate(gridless_candidates):
        if not isinstance(candidate, dict):
            continue

        rows = candidate.get("rows", [])
        if not isinstance(rows, list) or not rows:
            continue

        try:
            candidate_index = int(candidate.get("candidate_index", fallback_index))
        except (TypeError, ValueError):
            candidate_index = fallback_index

        synthetic_index = -(candidate_index + 1)

        item = {
            "type": "table",
            "table_index": synthetic_index,
            "table_origin": "stage4_gridless_table_candidate",
            "gridless_candidate_id": candidate.get("candidate_id"),
            "rows": rows,
            "bbox": candidate.get("bbox"),
            "column_count": candidate.get("column_count"),
            "candidate_score": candidate.get("candidate_score"),
            "source_word_indices": [
                value
                for value in candidate.get("source_word_indices", [])
                if isinstance(value, int)
            ],
            "row_source_word_indices": candidate.get(
                "row_source_word_indices",
                [],
            ),
            "cell_source_word_indices": candidate.get(
                "cell_source_word_indices",
                [],
            ),
        }
        items.append(item)

    if not items:
        native_text = clean_text(
            raw_page.get("native_text")
        )

        if native_text:
            items.append(
                {
                    "type": "text",
                    "text": native_text,
                }
            )

    return items


def build_document(
    structure: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    raw_pages = structure.get("pages", [])

    if not isinstance(raw_pages, list):
        raw_pages = []

    structure_pages = sorted(
        (
            page
            for page in raw_pages
            if isinstance(page, dict)
        ),
        key=lambda page: int(page["page_number"]),
    )

    pages: list[dict[str, Any]] = []

    for structure_page in structure_pages:
        page_number = int(
            structure_page["page_number"]
        )

        raw_page = snapshot_pages.get(page_number)

        if raw_page is None:
            pages.append(
                {
                    "page_number": page_number,
                    "items": [],
                }
            )
            continue

        pages.append(
            {
                "page_number": page_number,
                "items": build_page_items(
                    structure_page,
                    raw_page,
                ),
            }
        )

    table_boundary_overflow_recoveries: list[
        dict[str, Any]
    ] = []

    for page in pages:
        page_number = int(
            page["page_number"]
        )

        for item in page.get(
            "items",
            [],
        ):
            if not isinstance(item, dict):
                continue

            if item.get("type") != "table":
                continue

            table_index = item.get(
                "table_index"
            )

            for recovery in item.get(
                "boundary_overflow_recoveries",
                [],
            ):
                if not isinstance(
                    recovery,
                    dict,
                ):
                    continue

                table_boundary_overflow_recoveries.append(
                    {
                        "page_number":
                            page_number,
                        "table_index":
                            table_index,
                        **recovery,
                    }
                )

    cross_page = build_cross_page_table_groups(
        structure,
        snapshot_pages,
    )

    boundary_results = detect_confirmed_boundary_rows(
        snapshot_pages,
        cross_page["edge_results"],
    )

    boundary_counts = boundary_relation_counts(
        boundary_results
    )

    recovery = build_cross_page_logical_tables(
        cross_page["groups"],
        boundary_results,
        snapshot_pages,
    )

    return {
        "stage": 5,
        "version": VERSION,
        "source_file": structure.get("source_file"),
        "page_count": len(pages),

        # Stage 5.2 已封印：不再补空 cell。
        "geometry_filled_cell_count": 0,

        # Stage 5.2.1：页内 table bottom overflow recovery。
        "table_boundary_overflow_recovery_count":
            len(
                table_boundary_overflow_recoveries
            ),
        "table_boundary_overflow_recovered_word_count":
            sum(
                len(
                    item.get(
                        "source_word_indices",
                        [],
                    )
                )
                for item
                in table_boundary_overflow_recoveries
            ),
        "table_boundary_overflow_recovered_page_count":
            len(
                {
                    int(
                        item["page_number"]
                    )
                    for item
                    in table_boundary_overflow_recoveries
                }
            ),
        "table_boundary_overflow_recoveries":
            table_boundary_overflow_recoveries,

        # Stage5 v0.4.1：Stage4 native vector checkbox 状态物化。
        "checkbox_annotation_count": sum(
            len(item.get("checkbox_annotations", []))
            for page in pages
            for item in page.get("items", [])
            if isinstance(item, dict) and item.get("type") == "table"
        ),
        "checkbox_annotation_pages": sorted(
            {
                int(page["page_number"])
                for page in pages
                if any(
                    isinstance(item, dict)
                    and item.get("type") == "table"
                    and item.get("checkbox_annotations")
                    for item in page.get("items", [])
                )
            }
        ),

        # Stage5 v0.4.1：Stage4 无线框表格候选 materialization。
        "gridless_table_materialized_count": sum(
            1
            for page in pages
            for item in page.get("items", [])
            if isinstance(item, dict)
            and item.get("type") == "table"
            and item.get("table_origin") == "stage4_gridless_table_candidate"
        ),
        "gridless_table_materialized_pages": sorted(
            {
                int(page["page_number"])
                for page in pages
                if any(
                    isinstance(item, dict)
                    and item.get("type") == "table"
                    and item.get("table_origin") == "stage4_gridless_table_candidate"
                    for item in page.get("items", [])
                )
            }
        ),

        # Stage 5.3.1：候选确认与逻辑表组。
        "cross_page_table_stage4_candidate_count":
            cross_page["stage4_candidate_count"],
        "cross_page_table_supplemental_candidate_count":
            cross_page["supplemental_candidate_count"],
        "cross_page_table_candidate_count":
            cross_page["candidate_count"],
        "cross_page_table_confirmed_edge_count":
            cross_page["confirmed_count"],
        "cross_page_table_rejected_edge_count":
            cross_page["rejected_count"],
        "cross_page_table_unresolved_edge_count":
            cross_page["unresolved_count"],
        "cross_page_table_invalid_reference_count":
            cross_page["invalid_reference_count"],
        "cross_page_table_group_count":
            len(cross_page["groups"]),
        "cross_page_table_edge_results":
            cross_page["edge_results"],
        "cross_page_table_groups":
            cross_page["groups"],

        # Stage 5.3.2：只判断 confirmed 边界 row 关系。
        "cross_page_boundary_count":
            len(boundary_results),
        "cross_page_row_continuation_count":
            boundary_counts["ROW_CONTINUATION"],
        "cross_page_new_row_count":
            boundary_counts["NEW_ROW"],
        "cross_page_row_unresolved_count":
            boundary_counts["UNRESOLVED"],
        "cross_page_boundary_results":
            boundary_results,

        # Stage 5.3.3：实际恢复后的跨页逻辑表。
        # 原 pages 仍保留物理页结果，互不覆盖。
        "cross_page_logical_table_count":
            len(recovery["logical_tables"]),
        "cross_page_merged_row_count":
            recovery["merged_row_count"],
        "cross_page_partial_merge_count":
            recovery["partial_merge_count"],
        "cross_page_logical_footer_removed_count":
            recovery["footer_removed_count"],
        "cross_page_logical_tables":
            recovery["logical_tables"],

        # 物理页结果保持不变，便于逐页核对。
        "pages": pages,
    }


# =============================================================================
# Markdown
# =============================================================================


def render_table_rows(
    rows: list[list[str]],
) -> str:
    lines: list[str] = []

    for row in rows:
        cells = [
            display_cell_text(cell)
            for cell in row
        ]

        # 只去掉尾部连续空 cell。
        # 中间空 cell 仍保留 Tab，尽量保留列关系。
        while cells and cells[-1] == "":
            cells.pop()

        if not cells:
            continue

        line = "\t".join(cells)

        # 仅修 Markdown 展示：
        # 行首 Tab 会被 Markdown 当成缩进代码块。
        # 这里去掉行首 Tab，不影响 result.json，也不影响后续结构处理。
        line = line.lstrip("\t")

        lines.append(line)

    return "\n".join(lines)


def render_item(
    item: dict[str, Any],
) -> str:
    item_type = item.get("type")

    if item_type == "text":
        return clean_text(item.get("text"))

    if item_type == "table":
        return render_table_rows(
            item.get("rows", [])
        )

    return ""


def render_markdown(
    document: dict[str, Any],
) -> str:
    lines: list[str] = []

    for page in document.get("pages", []):
        page_number = int(page["page_number"])

        lines.append(
            f"<!-- page: {page_number} -->"
        )
        lines.append("")

        parts = [
            render_item(item)
            for item in page.get("items", [])
            if isinstance(item, dict)
        ]

        parts = [
            part
            for part in parts
            if part.strip()
        ]

        if parts:
            lines.append("\n\n".join(parts))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# =============================================================================
# Main
# =============================================================================


def run_table_recovery(
    *,
    structure_path: Path,
    snapshot_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run Stage 5 through the package API while preserving all artifacts."""
    structure = load_json(Path(structure_path))
    snapshot_pages = load_snapshot(Path(snapshot_path))
    document = build_document(
        structure,
        snapshot_pages,
    )

    expected_page_count = int(
        structure.get("page_count", 0) or 0
    )
    if expected_page_count and document["page_count"] != expected_page_count:
        raise ValueError(
            "Stage 4 页数与 Stage 5 输出页数不一致："
            f"{expected_page_count} != {document['page_count']}"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    (output_dir / "result.json").write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "result.md").write_text(
        render_markdown(document),
        encoding="utf-8",
    )
    (output_dir / "logical_tables.md").write_text(
        render_cross_page_logical_tables(
            document["cross_page_logical_tables"]
        ),
        encoding="utf-8",
    )
    return document
