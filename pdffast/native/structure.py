from __future__ import annotations

import json
import math
import unicodedata
from contextlib import nullcontext
from pathlib import Path
from statistics import mean
from typing import Any, Iterator, TextIO


# =============================================================================
# Page Structure Builder v0.2.5
# =============================================================================
#
# 输入：
#
#   Stage 1 Raw Evidence JSONL
#       +
#   Stage 1 Page Profile JSON
#       +
#   Stage 3 Section Alignment JSON
#       ↓
#   Page Structure Candidate JSON
#
# 本阶段只回答：
#
#   “这一页有哪些主要结构块，它们在哪里？”
#
# 当前识别：
#
#   - text
#   - table
#   - image
#   - vector   （仅对 Stage 1 已判定为 vector_graphics 的页面保守启用）
#   - gridless_table_candidate（无线框/无边线但具有稳定二维列结构的候选）
#
# 本阶段明确不做：
#
#   - OCR
#   - rowspan / colspan 恢复
#   - 表头识别
#   - 跨页表格拼接
#   - 乱码 / 字体编码异常修复
#   - 图片内容理解
#   - 公式语义识别
#   - 最终 reading order
#   - Quality Gate
#   - LLM-ready Document
#
# 核心原则：
#
#   1. 不重新打开 PDF。
#   2. Raw Evidence 是事实，Structure Block 是候选结构。
#   3. table_candidate != 最终正确表格。
#   4. 不复制完整 chars / table cells；text block 仅保留轻量 source_word_indices provenance。
#   5. Raw Evidence JSONL 按页流式读取，避免把整份字符级证据一次性装入内存。
#
# =============================================================================


BUILDER_VERSION = "0.2.6"
STRUCTURE_SCHEMA_VERSION = "0.7"


# =============================================================================
# 页面边界 / 跨页候选参数
# =============================================================================

# Stage 4 输出中的 bbox 必须是“当前物理页局部 bbox”。
# Raw Evidence 中的原始几何不会被修改。
PAGE_BBOX_EPSILON = 1e-6

# 距离页面上下边界在该比例以内，认为结构块“触边”。
# 这是跨页恢复提示，不是最终跨页结论。
PAGE_EDGE_TOUCH_RATIO = 0.02

# 相邻两页的 table block 建立“跨页候选”时：
# 前页 table 必须触底 / 底部越界，
# 后页 table 允许从页面顶部 25% 范围内开始，
# 因为真实申请书经常会有页眉或少量标题。
CROSS_PAGE_TABLE_NEXT_TOP_RATIO = 0.25

# 两个 table fragment 水平方向至少重合多少。
CROSS_PAGE_TABLE_MIN_X_OVERLAP = 0.65

# 两个 table fragment 宽度相似度至少多少：
# min(widthA, widthB) / max(widthA, widthB)
CROSS_PAGE_TABLE_MIN_WIDTH_SIMILARITY = 0.70



# =============================================================================
# Text line / block 参数
# =============================================================================

# word top 坐标差在此范围内，粗略视作同一视觉 row。
TEXT_LINE_Y_TOLERANCE = 3.0

# 同一 row 内出现明显水平空隙时拆成多个视觉 line segment。
# 这样比把整行所有 words 直接拼在一起更适合：
#   - 表单
#   - 左右分离字段
#   - 多栏页面
TEXT_MIN_HORIZONTAL_GAP = 18.0
TEXT_HORIZONTAL_GAP_PAGE_RATIO = 0.04

# text block 合并时的最小垂直容忍。
TEXT_BLOCK_MIN_VERTICAL_GAP = 5.0

# 动态垂直阈值 = 平均行高 * 此系数。
TEXT_BLOCK_LINE_HEIGHT_FACTOR = 1.5

# 两个相邻文本行若水平覆盖足够接近，可考虑合并。
TEXT_BLOCK_MIN_HORIZONTAL_OVERLAP = 0.15

# 即使 overlap 不高，只要左边界足够接近也允许合并。
TEXT_BLOCK_X_ALIGNMENT_RATIO = 0.04


# =============================================================================
# Gridless / borderless table candidate 参数
# =============================================================================
#
# 这里不依赖“是否画了表格线”，只看 native words 的二维重复排布。
# Stage4 只产出 candidate，不在这里做跨页拼接、语义表头判断或 OCR。
#
# 目标场景：
#   - 无横线/竖线，但连续多行稳定对齐成 3~8 列；
#   - 某些列可能大量为空（例如互斥 checkbox 列）；
#   - √ / □ / ☑ 等短 glyph 通过 x 位置归属列，而不是变成散落正文。
GRIDLESS_MIN_ROWS = 6
GRIDLESS_MIN_COLUMNS = 3
GRIDLESS_MAX_COLUMNS = 8
GRIDLESS_MIN_WORDS_PER_ROW = 3
GRIDLESS_MAX_WORDS_PER_ROW = 10
GRIDLESS_MIN_ROW_SPAN_RATIO = 0.34
GRIDLESS_MIN_GOOD_ROW_RATIO = 0.72
GRIDLESS_MIN_SUPPORTED_COLUMNS = 3
GRIDLESS_COLUMN_SUPPORT_RATIO = 0.50
GRIDLESS_STRONG_COLUMN_SUPPORT_RATIO = 0.78
GRIDLESS_MIN_STRONG_COLUMNS = 2
GRIDLESS_MAX_ROW_GAP_ABS = 64.0
GRIDLESS_MAX_ROW_GAP_HEIGHT_FACTOR = 5.0
GRIDLESS_MAX_HEADER_SCAN_ROWS = 3
GRIDLESS_MAX_CANDIDATE_OVERLAP = 0.65


# =============================================================================
# Image / region 参数
# =============================================================================

# 极小 image object 不升级成 Stage 4 image block。
# 原始 image evidence 仍保存在 Stage 1，不会丢失。
MIN_IMAGE_AREA_RATIO = 0.0005

# image 若几乎完整位于 table candidate 内，
# Stage 4 不再额外生成一个独立 image block，避免重复结构。
IMAGE_TABLE_CONTAINMENT_THRESHOLD = 0.90

# vector_graphics 页面中，位于 table candidate 内的 vector object 不重复计入
# aggregate vector block。
VECTOR_TABLE_CONTAINMENT_THRESHOLD = 0.90


# =============================================================================
# 基础读取
# =============================================================================


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"文件不存在: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def read_snapshot_meta(
    file: TextIO,
    path: Path,
) -> dict[str, Any]:
    """
    Stage 1 Snapshot JSONL 第一条有效记录必须是 meta。

    这样 Stage 4 后续可以继续按页流式消费，
    不需要把整份 Raw Evidence 读进内存。
    """
    for line_number, line in enumerate(
        file,
        start=1,
    ):
        line = line.strip()

        if not line:
            continue

        try:
            record = json.loads(
                line
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Raw Evidence JSONL 第 {line_number} 行解析失败: {exc}"
            ) from exc

        if record.get(
            "record_type"
        ) != "meta":
            raise ValueError(
                f"Raw Evidence JSONL 第一条有效记录不是 meta: {path}"
            )

        return record

    raise ValueError(
        f"Raw Evidence JSONL 为空: {path}"
    )


def iter_snapshot_pages(
    file: TextIO,
) -> Iterator[dict[str, Any]]:
    """
    在 meta 已经被读取后，继续逐行读取 page record。
    """
    for line_number, line in enumerate(
        file,
        start=2,
    ):
        line = line.strip()

        if not line:
            continue

        try:
            record = json.loads(
                line
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Raw Evidence JSONL 后续记录解析失败（约第 {line_number} 行）: {exc}"
            ) from exc

        if record.get(
            "record_type"
        ) != "page":
            continue

        page_number = record.get(
            "page_number"
        )

        if not isinstance(
            page_number,
            int,
        ):
            raise ValueError(
                "Raw Evidence page record 缺少有效 page_number。"
            )

        yield record


def build_page_index(
    data: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    result: dict[
        int,
        dict[str, Any],
    ] = {}

    for page in data.get(
        "pages",
        [],
    ):
        page_number = page.get(
            "page_number"
        )

        if isinstance(
            page_number,
            int,
        ):
            result[
                page_number
            ] = page

    return result


# =============================================================================
# BBox
# =============================================================================


def round_number(
    value: float,
    digits: int = 4,
) -> float:
    return round(
        float(value),
        digits,
    )


def make_bbox(
    x0: float,
    top: float,
    x1: float,
    bottom: float,
) -> dict[str, float]:
    return {
        "x0": round_number(x0),
        "top": round_number(top),
        "x1": round_number(x1),
        "bottom": round_number(bottom),
    }


def normalize_bbox(
    value: Any,
) -> dict[str, float] | None:
    """
    支持：

        {x0, top, x1, bottom}

    或：

        [x0, top, x1, bottom]
    """
    if isinstance(
        value,
        dict,
    ):
        try:
            return make_bbox(
                float(value["x0"]),
                float(value["top"]),
                float(value["x1"]),
                float(value["bottom"]),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return None

    if (
        isinstance(
            value,
            (
                list,
                tuple,
            ),
        )
        and len(value) == 4
    ):
        try:
            return make_bbox(
                float(value[0]),
                float(value[1]),
                float(value[2]),
                float(value[3]),
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    return None


def bbox_width(
    bbox: dict[str, float],
) -> float:
    return max(
        0.0,
        bbox["x1"]
        - bbox["x0"],
    )


def bbox_height(
    bbox: dict[str, float],
) -> float:
    return max(
        0.0,
        bbox["bottom"]
        - bbox["top"],
    )


def bbox_area(
    bbox: dict[str, float],
) -> float:
    return (
        bbox_width(bbox)
        * bbox_height(bbox)
    )


def bbox_union(
    bboxes: list[dict[str, float]],
) -> dict[str, float] | None:
    if not bboxes:
        return None

    return make_bbox(
        min(
            bbox["x0"]
            for bbox in bboxes
        ),
        min(
            bbox["top"]
            for bbox in bboxes
        ),
        max(
            bbox["x1"]
            for bbox in bboxes
        ),
        max(
            bbox["bottom"]
            for bbox in bboxes
        ),
    )


def intersection_area(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    x0 = max(
        first["x0"],
        second["x0"],
    )

    top = max(
        first["top"],
        second["top"],
    )

    x1 = min(
        first["x1"],
        second["x1"],
    )

    bottom = min(
        first["bottom"],
        second["bottom"],
    )

    if (
        x1 <= x0
        or bottom <= top
    ):
        return 0.0

    return (
        x1 - x0
    ) * (
        bottom - top
    )


def containment_ratio(
    subject: dict[str, float],
    container: dict[str, float],
) -> float:
    """
    intersection / area(subject)

    用于判断：

        subject 是否基本被 container 包含。
    """
    subject_area = bbox_area(
        subject
    )

    if subject_area <= 0:
        return 0.0

    return (
        intersection_area(
            subject,
            container,
        )
        / subject_area
    )


def horizontal_overlap_ratio(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    overlap = max(
        0.0,
        min(
            first["x1"],
            second["x1"],
        )
        - max(
            first["x0"],
            second["x0"],
        ),
    )

    minimum_width = min(
        bbox_width(first),
        bbox_width(second),
    )

    if minimum_width <= 0:
        return 0.0

    return (
        overlap
        / minimum_width
    )


def point_inside_bbox(
    x: float,
    y: float,
    bbox: dict[str, float],
) -> bool:
    return (
        bbox["x0"]
        <= x
        <= bbox["x1"]
        and bbox["top"]
        <= y
        <= bbox["bottom"]
    )


# =============================================================================
# Page-local BBox / Boundary Fragment
# =============================================================================


def bbox_is_finite(
    bbox: dict[str, float],
) -> bool:
    return all(
        math.isfinite(
            float(
                bbox[
                    key
                ]
            )
        )
        for key in (
            "x0",
            "top",
            "x1",
            "bottom",
        )
    )


def bbox_overflow_info(
    bbox: dict[str, float],
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    """
    计算原始 block bbox 相对当前物理页的越界量。

    注意：
        越界本身不等于错误。

    对跨页表格、跨页文本片段、贴边图片来说，
    这是一条需要留给 Stage 5 的结构证据。
    """
    left = max(
        0.0,
        -float(
            bbox[
                "x0"
            ]
        ),
    )

    top = max(
        0.0,
        -float(
            bbox[
                "top"
            ]
        ),
    )

    right = max(
        0.0,
        float(
            bbox[
                "x1"
            ]
        )
        - page_width,
    )

    bottom = max(
        0.0,
        float(
            bbox[
                "bottom"
            ]
        )
        - page_height,
    )

    max_overflow = max(
        left,
        top,
        right,
        bottom,
    )

    return {
        "has_overflow":
            max_overflow
            > PAGE_BBOX_EPSILON,

        "left":
            round_number(
                left
            ),

        "top":
            round_number(
                top
            ),

        "right":
            round_number(
                right
            ),

        "bottom":
            round_number(
                bottom
            ),

        "max_overflow":
            round_number(
                max_overflow
            ),
    }


def clip_bbox_to_page(
    bbox: dict[str, float],
    page_width: float,
    page_height: float,
) -> dict[str, float]:
    """
    把结构块几何裁剪到“当前物理页”。

    这里只裁剪 bbox；
    text / table candidate / source reference 都不会删除。

    原始 bbox 若发生越界，会另外保存到 original_bbox。
    """
    return make_bbox(
        max(
            0.0,
            min(
                page_width,
                float(
                    bbox[
                        "x0"
                    ]
                ),
            ),
        ),
        max(
            0.0,
            min(
                page_height,
                float(
                    bbox[
                        "top"
                    ]
                ),
            ),
        ),
        max(
            0.0,
            min(
                page_width,
                float(
                    bbox[
                        "x1"
                    ]
                ),
            ),
        ),
        max(
            0.0,
            min(
                page_height,
                float(
                    bbox[
                        "bottom"
                    ]
                ),
            ),
        ),
    )


def add_page_local_geometry(
    block: dict[str, Any],
    page_width: float,
    page_height: float,
) -> None:
    """
    Stage 4 中每个 block 同时保留两层含义：

        original_bbox
            原始结构几何，仅在发生越界时保存。

        bbox
            当前物理页上的局部结构几何，
            后续 Stage 4 / Stage 5 的页内计算使用它。

    因此：
        “bbox 越过物理页”
    不再自动解释为 Stage 4 失败。
    """
    bbox = normalize_bbox(
        block.get(
            "bbox"
        )
    )

    if bbox is None:
        return

    overflow = bbox_overflow_info(
        bbox=
            bbox,

        page_width=
            page_width,

        page_height=
            page_height,
    )

    block[
        "boundary_overflow"
    ] = overflow

    if overflow[
        "has_overflow"
    ]:
        block[
            "original_bbox"
        ] = bbox

        block[
            "bbox"
        ] = clip_bbox_to_page(
            bbox=
                bbox,

            page_width=
                page_width,

            page_height=
                page_height,
        )

        block[
            "bbox_clipped"
        ] = True

        block[
            "boundary_fragment"
        ] = True

    else:
        block[
            "bbox"
        ] = bbox

        block[
            "bbox_clipped"
        ] = False

        block[
            "boundary_fragment"
        ] = False

    page_bbox = normalize_bbox(
        block.get(
            "bbox"
        )
    )

    if page_bbox is None:
        return

    x_margin = max(
        1.0,
        page_width
        * PAGE_EDGE_TOUCH_RATIO,
    )

    y_margin = max(
        1.0,
        page_height
        * PAGE_EDGE_TOUCH_RATIO,
    )

    block[
        "boundary_touch"
    ] = {
        "top":
            bool(
                overflow[
                    "top"
                ]
                > 0
                or page_bbox[
                    "top"
                ]
                <= y_margin
            ),

        "bottom":
            bool(
                overflow[
                    "bottom"
                ]
                > 0
                or page_bbox[
                    "bottom"
                ]
                >= page_height
                - y_margin
            ),

        "left":
            bool(
                overflow[
                    "left"
                ]
                > 0
                or page_bbox[
                    "x0"
                ]
                <= x_margin
            ),

        "right":
            bool(
                overflow[
                    "right"
                ]
                > 0
                or page_bbox[
                    "x1"
                ]
                >= page_width
                - x_margin
            ),
    }


def summarize_boundary_fragments(
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    type_counts = {
        "text":
            0,

        "table":
            0,

        "image":
            0,

        "vector":
            0,
    }

    fragment_block_ids: list[
        str
    ] = []

    for block in blocks:
        if not block.get(
            "boundary_fragment",
            False,
        ):
            continue

        block_type = str(
            block.get(
                "block_type",
                "",
            )
        )

        if block_type in type_counts:
            type_counts[
                block_type
            ] += 1

        block_id = str(
            block.get(
                "block_id",
                "",
            )
        )

        if block_id:
            fragment_block_ids.append(
                block_id
            )

    return {
        "has_boundary_fragments":
            bool(
                fragment_block_ids
            ),

        "fragment_count":
            len(
                fragment_block_ids
            ),

        "type_counts":
            type_counts,

        "block_ids":
            fragment_block_ids,
    }


def same_section(
    first_page: dict[str, Any],
    second_page: dict[str, Any],
) -> bool:
    first_structure = first_page.get(
        "document_structure",
        {},
    )

    second_structure = second_page.get(
        "document_structure",
        {},
    )

    first_section = first_structure.get(
        "section_id"
    )

    second_section = second_structure.get(
        "section_id"
    )

    if (
        first_section
        and second_section
    ):
        return (
            first_section
            == second_section
        )

    first_type = first_structure.get(
        "structure_type"
    )

    second_type = second_structure.get(
        "structure_type"
    )

    return bool(
        first_type
        and second_type
        and first_type
        == second_type
    )


def table_width_similarity(
    first_bbox: dict[str, float],
    second_bbox: dict[str, float],
) -> float:
    first_width = bbox_width(
        first_bbox
    )

    second_width = bbox_width(
        second_bbox
    )

    maximum = max(
        first_width,
        second_width,
    )

    if maximum <= 0:
        return 0.0

    return (
        min(
            first_width,
            second_width,
        )
        / maximum
    )


def add_cross_page_hint(
    block: dict[str, Any],
    hint: dict[str, Any],
) -> None:
    hints = block.setdefault(
        "cross_page_hints",
        [],
    )

    hints.append(
        hint
    )


def build_cross_page_table_candidates(
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    只建立“可能跨页”的候选关系，不在 Stage 4 合并表格。

    判断依据：
        1. 两页相邻；
        2. 同一章节/区域；
        3. 前页 table 触底或发生底部越界；
        4. 后页 table 位于页面顶部区域；
        5. 左右范围高度重合；
        6. 表格宽度相近。

    Stage 5 才继续判断：
        - 是否真的是同一张表
        - 是否跨 row
        - 是否跨 cell
        - 是否需要拼接文本
    """
    candidates: list[
        dict[str, Any]
    ] = []

    for previous_page, next_page in zip(
        pages,
        pages[
            1:
        ],
    ):
        if not same_section(
            previous_page,
            next_page,
        ):
            continue

        previous_tables = [
            block
            for block in previous_page.get(
                "blocks",
                [],
            )
            if block.get(
                "block_type"
            )
            == "table"
            and (
                block.get(
                    "boundary_touch",
                    {}
                ).get(
                    "bottom",
                    False,
                )
                or block.get(
                    "boundary_overflow",
                    {}
                ).get(
                    "bottom",
                    0.0,
                )
                > 0
            )
        ]

        next_page_height = float(
            next_page.get(
                "height",
                0.0,
            )
            or 0.0
        )

        next_tables = [
            block
            for block in next_page.get(
                "blocks",
                [],
            )
            if block.get(
                "block_type"
            )
            == "table"
            and (
                block.get(
                    "boundary_touch",
                    {}
                ).get(
                    "top",
                    False,
                )
                or (
                    next_page_height
                    > 0
                    and float(
                        block.get(
                            "bbox",
                            {},
                        ).get(
                            "top",
                            next_page_height,
                        )
                    )
                    <= next_page_height
                    * CROSS_PAGE_TABLE_NEXT_TOP_RATIO
                )
            )
        ]

        used_next_ids: set[
            str
        ] = set()

        for previous_block in previous_tables:
            previous_bbox = normalize_bbox(
                previous_block.get(
                    "bbox"
                )
            )

            if previous_bbox is None:
                continue

            best_match: tuple[
                float,
                dict[str, Any],
                float,
                float,
            ] | None = None

            for next_block in next_tables:
                next_block_id = str(
                    next_block.get(
                        "block_id",
                        "",
                    )
                )

                if (
                    not next_block_id
                    or next_block_id
                    in used_next_ids
                ):
                    continue

                next_bbox = normalize_bbox(
                    next_block.get(
                        "bbox"
                    )
                )

                if next_bbox is None:
                    continue

                x_overlap = horizontal_overlap_ratio(
                    previous_bbox,
                    next_bbox,
                )

                width_similarity = (
                    table_width_similarity(
                        previous_bbox,
                        next_bbox,
                    )
                )

                if (
                    x_overlap
                    < CROSS_PAGE_TABLE_MIN_X_OVERLAP
                    or width_similarity
                    < CROSS_PAGE_TABLE_MIN_WIDTH_SIMILARITY
                ):
                    continue

                score = (
                    0.65
                    * x_overlap
                    + 0.35
                    * width_similarity
                )

                if (
                    best_match is None
                    or score
                    > best_match[
                        0
                    ]
                ):
                    best_match = (
                        score,
                        next_block,
                        x_overlap,
                        width_similarity,
                    )

            if best_match is None:
                continue

            (
                score,
                next_block,
                x_overlap,
                width_similarity,
            ) = best_match

            previous_block_id = str(
                previous_block[
                    "block_id"
                ]
            )

            next_block_id = str(
                next_block[
                    "block_id"
                ]
            )

            used_next_ids.add(
                next_block_id
            )

            candidate_id = (
                "cross_table_"
                f"p{previous_page['page_number']:04d}_"
                f"{previous_block_id}_"
                f"p{next_page['page_number']:04d}_"
                f"{next_block_id}"
            )

            candidate = {
                "candidate_id":
                    candidate_id,

                "candidate_type":
                    "table_continuation",

                "candidate_type_cn":
                    "跨页表格延续候选",

                "from_page":
                    previous_page[
                        "page_number"
                    ],

                "from_block_id":
                    previous_block_id,

                "to_page":
                    next_page[
                        "page_number"
                    ],

                "to_block_id":
                    next_block_id,

                "same_section":
                    True,

                "x_overlap_ratio":
                    round_number(
                        x_overlap
                    ),

                "width_similarity":
                    round_number(
                        width_similarity
                    ),

                "candidate_score":
                    round_number(
                        score
                    ),

                "status":
                    "candidate_only",

                "status_cn":
                    "候选，待阶段5确认",
            }

            candidates.append(
                candidate
            )

            add_cross_page_hint(
                previous_block,
                {
                    "candidate_id":
                        candidate_id,

                    "direction":
                        "to_next_page",

                    "direction_cn":
                        "延续到下一页",

                    "paired_block_id":
                        next_block_id,
                },
            )

            add_cross_page_hint(
                next_block,
                {
                    "candidate_id":
                        candidate_id,

                    "direction":
                        "from_previous_page",

                    "direction_cn":
                        "承接上一页",

                    "paired_block_id":
                        previous_block_id,
                },
            )

    return candidates


def summarize_document_boundary_fragments(
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    page_numbers: list[
        int
    ] = []

    total_count = 0

    type_counts = {
        "text":
            0,

        "table":
            0,

        "image":
            0,

        "vector":
            0,
    }

    for page in pages:
        summary = page.get(
            "boundary_summary",
            {},
        )

        fragment_count = int(
            summary.get(
                "fragment_count",
                0,
            )
            or 0
        )

        if fragment_count > 0:
            page_numbers.append(
                int(
                    page[
                        "page_number"
                    ]
                )
            )

        total_count += fragment_count

        page_type_counts = summary.get(
            "type_counts",
            {},
        )

        for block_type in type_counts:
            type_counts[
                block_type
            ] += int(
                page_type_counts.get(
                    block_type,
                    0,
                )
                or 0
            )

    return {
        "fragment_count":
            total_count,

        "page_count":
            len(
                page_numbers
            ),

        "pages":
            page_numbers,

        "type_counts":
            type_counts,
    }




# =============================================================================
# Complexity Prior / Degenerate Candidate
# =============================================================================


def build_complexity_prior(
    section_page: dict[str, Any],
) -> dict[str, Any]:
    """
    基于 Stage 3 文档结构给出“解析复杂度先验”。

    complexity_prior 不是质量判定，也不表示页面一定有问题。
    它只表示后续 Stage 5 / OCR / Quality Gate / fallback
    对该区域应保持多高的复杂结构警惕。
    """
    zone_type = str(
        section_page.get("zone_type", "") or ""
    )

    if zone_type == "free":
        return {
            "level": "high",
            "level_cn": "高",
            "source": "zone_prior",
            "reason_code": "free_zone",
            "reason_cn": "自由区内部结构不固定，后续解析应提高复杂结构警惕。",
            "is_quality_failure": False,
        }

    if zone_type == "semi_free":
        return {
            "level": "medium",
            "level_cn": "中",
            "source": "zone_prior",
            "reason_code": "semi_free_zone",
            "reason_cn": "半自由区允许正文、表格、图片等混合结构。",
            "is_quality_failure": False,
        }

    return {
        "level": "normal",
        "level_cn": "常规",
        "source": "zone_prior",
        "reason_code": "regular_page",
        "reason_cn": "常规页面区域。",
        "is_quality_failure": False,
    }


def bbox_has_positive_area(
    bbox: Any,
) -> bool:
    normalized = normalize_bbox(bbox)
    if normalized is None:
        return False
    if not bbox_is_finite(normalized):
        return False
    return bool(
        normalized["x1"] > normalized["x0"]
        and normalized["bottom"] > normalized["top"]
    )


def safe_table_source_index(
    table: dict[str, Any],
    fallback_index: int,
) -> int:
    value = table.get("table_index", fallback_index)
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback_index


def build_degenerate_candidate_record(
    *,
    page_number: int,
    sequence: int,
    block: dict[str, Any],
    reason_code: str,
    reason_cn: str,
    raw_bbox: Any = None,
    page_bbox: Any = None,
    complexity_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    将无法作为正常 page block 的候选单独隔离。

    不修复乱码、不伪造 bbox、不删除 Stage 1 Raw Evidence。
    """
    candidate: dict[str, Any] = {
        "candidate_id": f"p{page_number:04d}_d{sequence:03d}",
        "candidate_type": "degenerate_structure_candidate",
        "candidate_type_cn": "退化结构候选",
        "block_type": str(block.get("block_type", "unknown")),
        "source": block.get("source"),
        "reason_code": reason_code,
        "reason_cn": reason_cn,
        "status": "quarantined",
        "status_cn": "已隔离，未作为正常结构块",
        "raw_bbox": raw_bbox if raw_bbox is not None else block.get("bbox"),
        "page_bbox": page_bbox,
        "requires_followup": True,
    }

    if isinstance(block.get("source_table_index"), int):
        candidate["source_table_index"] = block["source_table_index"]
    if isinstance(block.get("source_image_index"), int):
        candidate["source_image_index"] = block["source_image_index"]
    if block.get("candidate_extract_error"):
        candidate["candidate_extract_error"] = block.get("candidate_extract_error")

    if str(block.get("block_type", "")) == "text":
        value = str(block.get("text", ""))
        if value:
            candidate["text_preview"] = value[:200]

    if complexity_prior:
        candidate["complexity_prior_level"] = complexity_prior.get("level")
        candidate["complexity_prior_level_cn"] = complexity_prior.get("level_cn")

    return candidate


def partition_page_blocks(
    *,
    blocks: list[dict[str, Any]],
    page_number: int,
    page_width: float,
    page_height: float,
    complexity_prior: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    normal block：当前物理页存在有效正面积。
    boundary fragment：原始 bbox 越页，但当前页仍有有效可见部分。
    degenerate candidate：bbox 无效/非有限/无正面积，或裁剪后无可见正面积。
    """
    normal_blocks: list[dict[str, Any]] = []
    degenerate_candidates: list[dict[str, Any]] = []

    for block in blocks:
        raw_bbox = normalize_bbox(block.get("bbox"))
        reason_code = None
        reason_cn = None

        if raw_bbox is None:
            reason_code = "invalid_source_bbox"
            reason_cn = "源候选 bbox 格式无效。"
        elif not bbox_is_finite(raw_bbox):
            reason_code = "non_finite_source_bbox"
            reason_cn = "源候选 bbox 含 NaN 或无穷值。"
        elif not bbox_has_positive_area(raw_bbox):
            reason_code = "non_positive_source_bbox"
            reason_cn = "源候选 bbox 没有有效正面积。"

        if reason_code is not None:
            degenerate_candidates.append(
                build_degenerate_candidate_record(
                    page_number=page_number,
                    sequence=len(degenerate_candidates)+1,
                    block=block,
                    reason_code=reason_code,
                    reason_cn=str(reason_cn),
                    raw_bbox=block.get("bbox"),
                    page_bbox=None,
                    complexity_prior=complexity_prior,
                )
            )
            continue

        add_page_local_geometry(
            block=block,
            page_width=page_width,
            page_height=page_height,
        )
        page_bbox = normalize_bbox(block.get("bbox"))

        if not bbox_has_positive_area(page_bbox):
            degenerate_candidates.append(
                build_degenerate_candidate_record(
                    page_number=page_number,
                    sequence=len(degenerate_candidates)+1,
                    block=block,
                    reason_code="no_visible_page_intersection",
                    reason_cn=(
                        "源候选与当前物理页没有有效正面积交集；"
                        "已保留原始来源，但不作为正常页面结构块。"
                    ),
                    raw_bbox=block.get("original_bbox") or raw_bbox,
                    page_bbox=page_bbox,
                    complexity_prior=complexity_prior,
                )
            )
            continue

        normal_blocks.append(block)

    return normal_blocks, degenerate_candidates


def collect_unrepresented_raw_table_candidates(
    *,
    raw_page: dict[str, Any],
    represented_source_indices: set[int],
    page_number: int,
    start_sequence: int,
    complexity_prior: dict[str, Any],
) -> list[dict[str, Any]]:
    """保留 build_table_blocks 因 bbox 无法 normalize 而跳过的 Stage 1 表格候选。"""
    result: list[dict[str, Any]] = []

    for fallback_index, table in enumerate(raw_page.get("table_candidates", [])):
        source_index = safe_table_source_index(table, fallback_index)
        if source_index in represented_source_indices:
            continue

        pseudo_block = {
            "block_type": "table",
            "source": "stage1_table_candidate",
            "source_table_index": source_index,
            "bbox": table.get("bbox"),
            "candidate_extract_error": table.get("extract_error"),
        }

        result.append(
            build_degenerate_candidate_record(
                page_number=page_number,
                sequence=start_sequence+len(result),
                block=pseudo_block,
                reason_code="unusable_stage1_table_bbox",
                reason_cn=(
                    "Stage 1 表格候选存在，但 bbox 无法转换为正常 Stage 4 页面结构块。"
                ),
                raw_bbox=table.get("bbox"),
                page_bbox=None,
                complexity_prior=complexity_prior,
            )
        )

    return result


def summarize_degenerate_candidates(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    type_counts = {"text":0,"table":0,"image":0,"vector":0,"unknown":0}
    reason_counts: dict[str, int] = {}

    for candidate in candidates:
        block_type = str(candidate.get("block_type", "unknown"))
        if block_type not in type_counts:
            block_type = "unknown"
        type_counts[block_type] += 1

        reason_code = str(candidate.get("reason_code", "unknown"))
        reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1

    return {
        "candidate_count": len(candidates),
        "type_counts": type_counts,
        "reason_counts": reason_counts,
        "candidate_ids": [
            str(item.get("candidate_id", ""))
            for item in candidates
            if item.get("candidate_id")
        ],
    }


def summarize_document_degenerate_candidates(
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    page_numbers: list[int] = []
    total_count = 0
    type_counts = {"text":0,"table":0,"image":0,"vector":0,"unknown":0}
    reason_counts: dict[str, int] = {}

    for page in pages:
        summary = page.get("degenerate_summary", {})
        count = int(summary.get("candidate_count", 0) or 0)
        if count > 0:
            page_numbers.append(int(page["page_number"]))
        total_count += count

        for block_type in type_counts:
            type_counts[block_type] += int(
                summary.get("type_counts", {}).get(block_type, 0) or 0
            )
        for reason_code, reason_count in summary.get("reason_counts", {}).items():
            key = str(reason_code)
            reason_counts[key] = reason_counts.get(key, 0) + int(reason_count)

    return {
        "candidate_count": total_count,
        "page_count": len(page_numbers),
        "pages": page_numbers,
        "type_counts": type_counts,
        "reason_counts": reason_counts,
    }


# =============================================================================
# Table Blocks
# =============================================================================


def build_table_blocks(
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Stage 1 已经顺手运行过 pdfplumber TableFinder。

    Stage 4 不重新找一次表格，也不复制完整 cell/row 数据。

    这里只把现有 candidate 提升成 table block candidate，
    并保留 source_table_index 作为 Stage 5 回查 Raw Evidence 的引用。
    """
    result: list[
        dict[str, Any]
    ] = []

    for fallback_index, table in enumerate(
        raw_page.get(
            "table_candidates",
            [],
        )
    ):
        bbox = normalize_bbox(
            table.get(
                "bbox"
            )
        )

        if bbox is None:
            continue

        source_table_index = (
            safe_table_source_index(
                table,
                fallback_index,
            )
        )

        rows = table.get(
            "rows",
            [],
        )

        result.append(
            {
                "block_type": "table",
                "bbox": bbox,
                "source": "stage1_table_candidate",
                "source_table_index": source_table_index,
                "cell_count": int(
                    table.get(
                        "cell_count",
                        0,
                    )
                    or 0
                ),
                "row_count": (
                    len(rows)
                    if isinstance(rows, list)
                    else 0
                ),
                "candidate_extract_error": table.get(
                    "extract_error"
                ),
                "structure_status": "unresolved",
                "structure_confidence": "candidate",
            }
        )

    return result


# =============================================================================
# Image Blocks
# =============================================================================


def object_bbox(
    value: dict[str, Any],
) -> dict[str, float] | None:
    try:
        return make_bbox(
            float(value["x0"]),
            float(value["top"]),
            float(value["x1"]),
            float(value["bottom"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def build_image_blocks(
    raw_page: dict[str, Any],
    table_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    page_width = float(
        raw_page.get(
            "width",
            0.0,
        )
    )

    page_height = float(
        raw_page.get(
            "height",
            0.0,
        )
    )

    page_area = (
        page_width
        * page_height
    )

    if page_area <= 0:
        return []

    result: list[
        dict[str, Any]
    ] = []

    for image_index, image in enumerate(
        raw_page.get(
            "images",
            [],
        )
    ):
        bbox = object_bbox(
            image
        )

        if bbox is None:
            continue

        area_ratio = (
            bbox_area(bbox)
            / page_area
        )

        if (
            area_ratio
            < MIN_IMAGE_AREA_RATIO
        ):
            continue

        inside_table = any(
            containment_ratio(
                bbox,
                table_block["bbox"],
            )
            >= IMAGE_TABLE_CONTAINMENT_THRESHOLD
            for table_block in table_blocks
        )

        if inside_table:
            continue

        result.append(
            {
                "block_type": "image",
                "bbox": bbox,
                "source": "stage1_image_object",
                "source_image_index": image_index,
                "page_area_ratio": round_number(
                    area_ratio
                ),
                "structure_confidence": "high",
            }
        )

    return result


# =============================================================================
# Vector block（保守 fallback）
# =============================================================================


def build_vector_blocks(
    raw_page: dict[str, Any],
    profile_page: dict[str, Any],
    table_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    只在 Stage 1 已明确判定：

        primary_type == vector_graphics

    时建立一个 aggregate vector block。

    这样避免：

        普通表单页的大量 rect/line

    全部被重复当作 vector block。

    当前不做图形内部语义分析。
    """
    if str(
        profile_page.get(
            "primary_type",
            "",
        )
    ) != "vector_graphics":
        return []

    usable_bboxes: list[
        dict[str, float]
    ] = []

    counts = {
        "lines": 0,
        "rects": 0,
        "curves": 0,
    }

    for field in (
        "lines",
        "rects",
        "curves",
    ):
        for item in raw_page.get(
            field,
            [],
        ):
            bbox = object_bbox(
                item
            )

            if bbox is None:
                continue

            inside_table = any(
                containment_ratio(
                    bbox,
                    table_block["bbox"],
                )
                >= VECTOR_TABLE_CONTAINMENT_THRESHOLD
                for table_block in table_blocks
            )

            if inside_table:
                continue

            usable_bboxes.append(
                bbox
            )

            counts[field] += 1

    union_bbox = bbox_union(
        usable_bboxes
    )

    if union_bbox is None:
        return []

    return [
        {
            "block_type": "vector",
            "bbox": union_bbox,
            "source": "stage1_vector_objects",
            "vector_object_count": sum(
                counts.values()
            ),
            "vector_object_breakdown": counts,
            "structure_status": "aggregate_candidate",
            "structure_confidence": "medium",
        }
    ]


# =============================================================================
# Text word filtering
# =============================================================================


def valid_word(
    word: dict[str, Any],
) -> bool:
    if not str(
        word.get(
            "text",
            "",
        )
    ).strip():
        return False

    return all(
        isinstance(
            word.get(key),
            (
                int,
                float,
            ),
        )
        for key in (
            "x0",
            "x1",
            "top",
            "bottom",
        )
    )


def word_bbox(
    word: dict[str, Any],
) -> dict[str, float] | None:
    if not valid_word(
        word
    ):
        return None

    return object_bbox(
        word
    )


def is_word_inside_table(
    word: dict[str, Any],
    table_blocks: list[dict[str, Any]],
) -> bool:
    """
    使用 word bbox 中心点，而不是整块 overlap。

    原因：

    table candidate bbox 若稍微扩张，
    不应该顺手吞掉表格外相邻正文。
    """
    bbox = word_bbox(
        word
    )

    if bbox is None:
        return False

    center_x = (
        bbox["x0"]
        + bbox["x1"]
    ) / 2

    center_y = (
        bbox["top"]
        + bbox["bottom"]
    ) / 2

    return any(
        point_inside_bbox(
            center_x,
            center_y,
            table_block["bbox"],
        )
        for table_block in table_blocks
    )


def filter_text_words(
    words: list[dict[str, Any]],
    table_blocks: list[dict[str, Any]],
    excluded_word_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    """
    只排除 table 内文字，并保留 Stage 1 word provenance。

    source_word_index 使用 word 在 Stage 1 page.words 中的稳定下标。
    后续 Stage6 应优先沿用这一明确来源，而不是仅凭 bbox
    从整页 raw words 中重新猜测归属。

    不排除 image 内文字：

    - 扫描件可能自带 OCR/text layer
    - mixed_image_text 可能存在真实 native text overlay

    Stage 4 应保留这些证据，再通过 primary_type 标低置信度，
    而不是提前删掉。
    """
    result: list[
        dict[str, Any]
    ] = []

    excluded_word_indices = excluded_word_indices or set()

    for source_word_index, word in enumerate(words):
        if not valid_word(
            word
        ):
            continue

        if source_word_index in excluded_word_indices:
            continue

        if is_word_inside_table(
            word,
            table_blocks,
        ):
            continue

        # 不修改 Stage 1 原始 evidence；只在 Stage 4 内部副本上
        # 附加稳定来源索引。
        indexed_word = dict(word)
        indexed_word[
            "_source_word_index"
        ] = source_word_index

        result.append(
            indexed_word
        )

    return result



# =============================================================================
# Gridless / borderless table candidates
# =============================================================================


def gridless_word_center_x(word: dict[str, Any]) -> float:
    return (float(word["x0"]) + float(word["x1"])) / 2.0


def gridless_row_bbox(row: list[dict[str, Any]]) -> dict[str, float] | None:
    return bbox_union(
        [
            bbox
            for word in row
            if (bbox := word_bbox(word)) is not None
        ]
    )


def gridless_join_cell_words(words: list[dict[str, Any]]) -> str:
    """只按视觉顺序拼接同一候选 cell 内的 native word，不做语义修复。"""
    ordered = sorted(words, key=lambda item: float(item["x0"]))
    parts = [str(item.get("text", "")).strip() for item in ordered]
    parts = [part for part in parts if part]
    if not parts:
        return ""

    # 中文/符号之间通常不需要强插空格；英文词之间保留一个空格。
    text = parts[0]
    for part in parts[1:]:
        left = text[-1:] if text else ""
        right = part[:1]
        if (
            left
            and right
            and left.isascii()
            and right.isascii()
            and left.isalnum()
            and right.isalnum()
        ):
            text += " " + part
        else:
            text += part
    return text


def gridless_column_boundaries(centers: list[float]) -> list[float]:
    centers = sorted(centers)
    return [
        (centers[index] + centers[index + 1]) / 2.0
        for index in range(len(centers) - 1)
    ]


def gridless_assign_column(center_x: float, boundaries: list[float]) -> int:
    for index, boundary in enumerate(boundaries):
        if center_x < boundary:
            return index
    return len(boundaries)


def gridless_text_reliable(rows: list[list[str]]) -> bool:
    """只拦截明显损坏的 native text layer，不尝试修复乱码。"""
    text = "".join(
        value
        for row in rows
        for value in row
        if isinstance(value, str)
    )
    if not text:
        return False

    # pdfplumber 对坏字体映射常直接暴露 (cid:NNN)。这种页面应该留给
    # Quality Gate / fallback，而不是在 Stage4 被提升成“可靠无线框表格”。
    if text.count("(cid:") >= 2:
        return False

    meaningful = 0
    strange = 0
    for char in text:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        code = ord(char)
        is_cjk = 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF
        if is_cjk or char.isalnum() or char in "√☑☐□■●○+-_/（）()：:，,.;；%％&·'\"":
            meaningful += 1
        elif category.startswith(("L", "N")):
            meaningful += 1
        else:
            strange += 1

    total = meaningful + strange
    if total <= 0:
        return False

    return (strange / total) <= 0.28


def gridless_candidate_overlap_ratio(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    left_bbox = normalize_bbox(left.get("bbox"))
    right_bbox = normalize_bbox(right.get("bbox"))
    if left_bbox is None or right_bbox is None:
        return 0.0

    x0 = max(left_bbox["x0"], right_bbox["x0"])
    y0 = max(left_bbox["top"], right_bbox["top"])
    x1 = min(left_bbox["x1"], right_bbox["x1"])
    y1 = min(left_bbox["bottom"], right_bbox["bottom"])
    if x1 <= x0 or y1 <= y0:
        return 0.0

    intersection = (x1 - x0) * (y1 - y0)
    left_area = max(1e-9, bbox_width(left_bbox) * bbox_height(left_bbox))
    right_area = max(1e-9, bbox_width(right_bbox) * bbox_height(right_bbox))
    return intersection / min(left_area, right_area)


def detect_gridless_table_candidates(
    raw_page: dict[str, Any],
    existing_table_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    从 Stage1 native words 中寻找“没有表格线、但二维列结构稳定”的候选。

    规则只使用：
      - 连续视觉 row；
      - x 方向稳定列带；
      - 行间距连续性；
      - 多行重复列占用。

    不读取具体字段名、不按页码/case 特判、不做 OCR。
    """
    page_width = float(raw_page.get("width", 0.0) or 0.0)
    if page_width <= 0:
        return []

    indexed_words: list[dict[str, Any]] = []
    for source_word_index, word in enumerate(raw_page.get("words", [])):
        if not valid_word(word):
            continue
        if is_word_inside_table(word, existing_table_blocks):
            continue
        copied = dict(word)
        copied["_source_word_index"] = source_word_index
        indexed_words.append(copied)

    visual_rows = group_words_into_rows(indexed_words)
    eligible: list[dict[str, Any]] = []

    for row in visual_rows:
        row = sorted(row, key=lambda item: float(item["x0"]))
        if not (GRIDLESS_MIN_WORDS_PER_ROW <= len(row) <= GRIDLESS_MAX_WORDS_PER_ROW):
            continue
        bbox = gridless_row_bbox(row)
        if bbox is None:
            continue
        span_ratio = bbox_width(bbox) / page_width
        if span_ratio < GRIDLESS_MIN_ROW_SPAN_RATIO:
            continue
        heights = [
            bbox_height(value)
            for item in row
            if (value := word_bbox(item)) is not None
        ]
        if not heights:
            continue
        eligible.append(
            {
                "words": row,
                "bbox": bbox,
                "top": bbox["top"],
                "height": mean(heights),
            }
        )

    if len(eligible) < GRIDLESS_MIN_ROWS:
        return []

    sequences: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for row in eligible:
        if not current:
            current = [row]
            continue

        previous = current[-1]
        gap = float(row["top"]) - float(previous["top"])
        typical_height = mean([float(previous["height"]), float(row["height"])])
        max_gap = max(
            GRIDLESS_MAX_ROW_GAP_ABS,
            typical_height * GRIDLESS_MAX_ROW_GAP_HEIGHT_FACTOR,
        )

        if 0 <= gap <= max_gap:
            current.append(row)
        else:
            if len(current) >= GRIDLESS_MIN_ROWS:
                sequences.append(current)
            current = [row]

    if len(current) >= GRIDLESS_MIN_ROWS:
        sequences.append(current)

    candidates: list[dict[str, Any]] = []

    for sequence in sequences:
        header_pool = sequence[:GRIDLESS_MAX_HEADER_SCAN_ROWS]
        anchor_row = max(
            enumerate(header_pool),
            key=lambda pair: (len(pair[1]["words"]), -pair[0]),
        )[1]
        anchor_words = anchor_row["words"]
        if not (GRIDLESS_MIN_COLUMNS <= len(anchor_words) <= GRIDLESS_MAX_COLUMNS):
            continue

        anchor_words = sorted(anchor_words, key=lambda word: float(word["x0"]))
        centers = [gridless_word_center_x(word) for word in anchor_words]

        # 列边界优先使用“表头 token 之间的真实水平空隙”，
        # 而不是单纯取中心点中线。这样即使某个 body word 因水印附着而变宽，
        # 只要它的起点仍在原列，就不会被错误推到下一列。
        anchor_start_gaps = [
            float(anchor_words[index + 1]["x0"]) - float(anchor_words[index]["x0"])
            for index in range(len(anchor_words) - 1)
        ]
        min_anchor_gap = min(anchor_start_gaps, default=0.0)
        if min_anchor_gap < max(10.0, page_width * 0.018):
            continue

        boundaries = [
            (float(anchor_words[index]["x1"]) + float(anchor_words[index + 1]["x0"])) / 2.0
            for index in range(len(anchor_words) - 1)
        ]
        width = len(centers)
        mapped_rows: list[list[str]] = []
        mapped_row_indices: list[list[int]] = []
        mapped_cell_indices: list[list[list[int]]] = []
        mapped_row_bboxes: list[dict[str, float]] = []
        column_support = [0] * width
        good_row_count = 0

        for row in sequence:
            cells_words: list[list[dict[str, Any]]] = [[] for _ in range(width)]
            for word in row["words"]:
                col = gridless_assign_column(float(word["x0"]), boundaries)
                col = max(0, min(width - 1, col))
                cells_words[col].append(word)

            cells = [gridless_join_cell_words(values) for values in cells_words]
            nonempty = [index for index, value in enumerate(cells) if value]
            if len(nonempty) < GRIDLESS_MIN_COLUMNS:
                continue

            # 若大量 token 被挤进同一列，说明这行更像普通段落而非二维 row。
            if any(len(values) > 2 for values in cells_words):
                continue

            good_row_count += 1
            for index in nonempty:
                column_support[index] += 1

            mapped_rows.append(cells)
            cell_indices = [
                sorted(
                    int(word["_source_word_index"])
                    for word in values
                    if isinstance(word.get("_source_word_index"), int)
                )
                for values in cells_words
            ]
            mapped_cell_indices.append(cell_indices)
            mapped_row_indices.append(
                sorted(
                    value
                    for values in cell_indices
                    for value in values
                )
            )
            mapped_row_bboxes.append(row["bbox"])

        if good_row_count < GRIDLESS_MIN_ROWS:
            continue

        good_ratio = good_row_count / max(1, len(sequence))
        if good_ratio < GRIDLESS_MIN_GOOD_ROW_RATIO:
            continue

        supported_columns = sum(
            1
            for count in column_support
            if count / good_row_count >= GRIDLESS_COLUMN_SUPPORT_RATIO
        )
        strong_columns = sum(
            1
            for count in column_support
            if count / good_row_count >= GRIDLESS_STRONG_COLUMN_SUPPORT_RATIO
        )
        if supported_columns < GRIDLESS_MIN_SUPPORTED_COLUMNS:
            continue
        if strong_columns < GRIDLESS_MIN_STRONG_COLUMNS:
            continue

        bbox = bbox_union(mapped_row_bboxes)
        if bbox is None:
            continue

        source_word_indices = sorted(
            {
                value
                for row_indices in mapped_row_indices
                for value in row_indices
            }
        )

        if not gridless_text_reliable(mapped_rows):
            continue

        score = (
            0.45 * min(1.0, good_ratio)
            + 0.35 * min(1.0, supported_columns / max(1, width))
            + 0.20 * min(1.0, good_row_count / 12.0)
        )

        candidates.append(
            {
                "candidate_type": "gridless_table",
                "bbox": bbox,
                "rows": mapped_rows,
                "row_source_word_indices": mapped_row_indices,
                "cell_source_word_indices": mapped_cell_indices,
                "source_word_indices": source_word_indices,
                "column_count": width,
                "row_count": len(mapped_rows),
                "column_centers": [round(value, 3) for value in centers],
                "column_support": column_support,
                "candidate_score": round(score, 4),
                "structure_confidence": "high" if score >= 0.82 else "medium",
                "detection_policy": "stable_native_word_column_bands",
            }
        )

    # 大面积重叠候选只保留分数更高、行数更多的那个。
    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            float(item.get("candidate_score", 0.0)),
            int(item.get("row_count", 0)),
        ),
        reverse=True,
    ):
        if any(
            gridless_candidate_overlap_ratio(candidate, kept)
            >= GRIDLESS_MAX_CANDIDATE_OVERLAP
            for kept in selected
        ):
            continue
        selected.append(candidate)

    selected.sort(key=lambda item: (item["bbox"]["top"], item["bbox"]["x0"]))
    for index, candidate in enumerate(selected):
        candidate["candidate_index"] = index
        candidate["candidate_id"] = f"gridless_table_{index:03d}"

    return selected


# =============================================================================
# Text lines
# =============================================================================


def group_words_into_rows(
    words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    if not words:
        return []

    sorted_words = sorted(
        words,
        key=lambda word: (
            float(word["top"]),
            float(word["x0"]),
        ),
    )

    rows: list[
        list[dict[str, Any]]
    ] = []

    for word in sorted_words:
        word_top = float(
            word["top"]
        )

        if not rows:
            rows.append(
                [word]
            )
            continue

        current_row = rows[-1]

        row_top = mean(
            float(item["top"])
            for item in current_row
        )

        if (
            abs(
                word_top
                - row_top
            )
            <= TEXT_LINE_Y_TOLERANCE
        ):
            current_row.append(
                word
            )
        else:
            rows.append(
                [word]
            )

    return rows


def split_row_into_segments(
    row: list[dict[str, Any]],
    page_width: float,
) -> list[list[dict[str, Any]]]:
    if not row:
        return []

    row = sorted(
        row,
        key=lambda word: float(
            word["x0"]
        ),
    )

    gap_threshold = max(
        TEXT_MIN_HORIZONTAL_GAP,
        page_width
        * TEXT_HORIZONTAL_GAP_PAGE_RATIO,
    )

    segments: list[
        list[dict[str, Any]]
    ] = []

    current: list[
        dict[str, Any]
    ] = []

    for word in row:
        if not current:
            current.append(
                word
            )
            continue

        previous = current[-1]

        gap = (
            float(word["x0"])
            - float(previous["x1"])
        )

        if gap > gap_threshold:
            segments.append(
                current
            )
            current = [
                word
            ]
        else:
            current.append(
                word
            )

    if current:
        segments.append(
            current
        )

    return segments


def create_text_line(
    words: list[dict[str, Any]],
) -> dict[str, Any] | None:
    valid_bboxes = [
        bbox
        for word in words
        if (
            bbox := word_bbox(word)
        )
        is not None
    ]

    bbox = bbox_union(
        valid_bboxes
    )

    if bbox is None:
        return None

    ordered_words = sorted(
        words,
        key=lambda word: float(
            word["x0"]
        ),
    )

    text = " ".join(
        str(
            word.get(
                "text",
                "",
            )
        ).strip()
        for word in ordered_words
        if str(
            word.get(
                "text",
                "",
            )
        ).strip()
    )

    if not text:
        return None

    source_word_indices = sorted(
        {
            int(word["_source_word_index"])
            for word in ordered_words
            if isinstance(
                word.get("_source_word_index"),
                int,
            )
        }
    )

    return {
        "text": text,
        "bbox": bbox,
        "word_count": len(
            ordered_words
        ),
        "source_word_indices": source_word_indices,
    }


def build_text_lines(
    words: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    rows = group_words_into_rows(
        words
    )

    lines: list[
        dict[str, Any]
    ] = []

    for row in rows:
        for segment in split_row_into_segments(
            row,
            page_width,
        ):
            line = create_text_line(
                segment
            )

            if line is not None:
                lines.append(
                    line
                )

    lines.sort(
        key=lambda line: (
            line["bbox"]["top"],
            line["bbox"]["x0"],
        )
    )

    return lines


# =============================================================================
# Column assignment
# =============================================================================


def assign_column(
    bbox: dict[str, float],
    page_width: float,
    multi_column: bool,
    split_x_ratio: float,
) -> str:
    """
    Stage 4 不重新检测 multi-column。

    直接复用 Stage 1：

        multi_column
        column_split_x_ratio

    并额外保留 spanning，避免把跨双栏标题硬塞进左/右栏。
    """
    if not multi_column:
        return "single"

    if (
        split_x_ratio <= 0
        or split_x_ratio >= 1
    ):
        return "unknown"

    split_x = (
        page_width
        * split_x_ratio
    )

    if bbox["x1"] <= split_x:
        return "left"

    if bbox["x0"] >= split_x:
        return "right"

    return "spanning"


# =============================================================================
# Text blocks
# =============================================================================


def can_merge_text_lines(
    previous: dict[str, Any],
    current: dict[str, Any],
    page_width: float,
) -> bool:
    if (
        previous["column"]
        != current["column"]
    ):
        return False

    previous_bbox = previous[
        "bbox"
    ]

    current_bbox = current[
        "bbox"
    ]

    vertical_gap = (
        current_bbox["top"]
        - previous_bbox["bottom"]
    )

    # 行发生轻微 bbox 重叠时，允许继续评估。
    if vertical_gap < 0:
        vertical_gap = 0.0

    avg_height = mean(
        [
            bbox_height(
                previous_bbox
            ),
            bbox_height(
                current_bbox
            ),
        ]
    )

    max_vertical_gap = max(
        TEXT_BLOCK_MIN_VERTICAL_GAP,
        avg_height
        * TEXT_BLOCK_LINE_HEIGHT_FACTOR,
    )

    if (
        vertical_gap
        > max_vertical_gap
    ):
        return False

    horizontal_overlap = (
        horizontal_overlap_ratio(
            previous_bbox,
            current_bbox,
        )
    )

    if page_width > 0:
        x_alignment_ratio = (
            abs(
                previous_bbox["x0"]
                - current_bbox["x0"]
            )
            / page_width
        )
    else:
        x_alignment_ratio = 1.0

    return (
        horizontal_overlap
        >= TEXT_BLOCK_MIN_HORIZONTAL_OVERLAP
        or x_alignment_ratio
        <= TEXT_BLOCK_X_ALIGNMENT_RATIO
    )


def create_text_block(
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    bbox = bbox_union(
        [
            line["bbox"]
            for line in lines
        ]
    )

    if bbox is None:
        raise ValueError(
            "text block bbox 构建失败。"
        )

    source_word_indices = sorted(
        {
            int(source_word_index)
            for line in lines
            for source_word_index in line.get(
                "source_word_indices",
                [],
            )
            if isinstance(
                source_word_index,
                int,
            )
        }
    )

    return {
        "block_type": "text",
        "bbox": bbox,
        "text": "\n".join(
            line["text"]
            for line in lines
        ),
        "line_count": len(lines),
        "word_count": sum(
            int(
                line["word_count"]
            )
            for line in lines
        ),
        "source_word_indices": source_word_indices,
        "column": lines[0][
            "column"
        ],
        "source": "stage1_words",
        "structure_confidence": "medium",
    }


def merge_text_lines(
    lines: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    if not lines:
        return []

    blocks: list[
        dict[str, Any]
    ] = []

    current_lines = [
        lines[0]
    ]

    for line in lines[1:]:
        previous = current_lines[-1]

        if can_merge_text_lines(
            previous,
            line,
            page_width,
        ):
            current_lines.append(
                line
            )
        else:
            blocks.append(
                create_text_block(
                    current_lines
                )
            )
            current_lines = [
                line
            ]

    if current_lines:
        blocks.append(
            create_text_block(
                current_lines
            )
        )

    return blocks


def build_text_blocks(
    raw_page: dict[str, Any],
    profile_page: dict[str, Any],
    table_blocks: list[dict[str, Any]],
    excluded_word_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    page_width = float(
        raw_page.get(
            "width",
            0.0,
        )
    )

    words = filter_text_words(
        raw_page.get(
            "words",
            [],
        ),
        table_blocks,
        excluded_word_indices=excluded_word_indices,
    )

    lines = build_text_lines(
        words,
        page_width,
    )

    multi_column = bool(
        profile_page.get(
            "multi_column",
            False,
        )
    )

    try:
        split_x_ratio = float(
            profile_page.get(
                "column_split_x_ratio",
                0.0,
            )
            or 0.0
        )
    except (
        TypeError,
        ValueError,
    ):
        split_x_ratio = 0.0

    for line in lines:
        line["column"] = assign_column(
            line["bbox"],
            page_width,
            multi_column,
            split_x_ratio,
        )

    # 多栏页面必须按 column 分组再合并，
    # 否则左右栏相近的 y 坐标很容易错误串起来。
    if multi_column:
        groups: dict[
            str,
            list[dict[str, Any]],
        ] = {
            "spanning": [],
            "left": [],
            "right": [],
            "unknown": [],
        }

        for line in lines:
            groups.setdefault(
                line["column"],
                [],
            ).append(
                line
            )

        blocks: list[
            dict[str, Any]
        ] = []

        for column_name in (
            "spanning",
            "left",
            "right",
            "unknown",
        ):
            column_lines = groups.get(
                column_name,
                [],
            )

            column_lines.sort(
                key=lambda line: (
                    line["bbox"]["top"],
                    line["bbox"]["x0"],
                )
            )

            blocks.extend(
                merge_text_lines(
                    column_lines,
                    page_width,
                )
            )

        return blocks

    return merge_text_lines(
        lines,
        page_width,
    )


# =============================================================================
# Block order / stable IDs
# =============================================================================


def spatial_block_sort_key(
    block: dict[str, Any],
) -> tuple[
    float,
    float,
    int,
]:
    """
    只建立稳定的空间顺序：top -> x0。

    这不是最终 reading order。
    """
    bbox = block[
        "bbox"
    ]

    type_priority = {
        "text": 0,
        "table": 1,
        "image": 2,
        "vector": 3,
    }.get(
        str(
            block.get(
                "block_type",
                "",
            )
        ),
        9,
    )

    return (
        float(bbox["top"]),
        float(bbox["x0"]),
        type_priority,
    )


def assign_block_ids(
    page_number: int,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks.sort(
        key=spatial_block_sort_key
    )

    for index, block in enumerate(
        blocks,
        start=1,
    ):
        block["block_id"] = (
            f"p{page_number:04d}_"
            f"b{index:03d}"
        )

        block["spatial_order"] = index

    return blocks


# =============================================================================
# Page Structure
# =============================================================================


def get_table_structure_status(
    raw_page: dict[str, Any],
    table_blocks: list[dict[str, Any]],
    degenerate_candidates: list[dict[str, Any]] | None = None,
) -> str:
    """
    “没有 table block”不能直接解释成“页面没有表格”。

    Stage 1 的 table_mode=auto 可能跳过某些页面。
    """
    if table_blocks:
        return "candidate_only"

    degenerate_table_count = sum(
        1
        for item in (degenerate_candidates or [])
        if str(item.get("block_type", "")) == "table"
    )

    if degenerate_table_count > 0:
        return "candidate_degenerate"

    table_detection = raw_page.get(
        "table_detection",
        {},
    )

    status = str(
        table_detection.get(
            "status",
            "unknown",
        )
    )

    if status == "skipped":
        return "not_scanned"

    if status == "error":
        return "detection_error"

    if status == "completed":
        return "no_candidate"

    return "unknown"



# =============================================================================
# Native vector checkbox detection
# =============================================================================

CHECKBOX_MIN_SIDE = 4.0
CHECKBOX_MAX_SIDE = 18.0
CHECKBOX_MAX_BORDER_THICKNESS = 1.8
CHECKBOX_EDGE_TOL = 2.0
CHECKBOX_LABEL_MAX_GAP = 36.0
CHECKBOX_TICK_MARGIN = 1.8


def _obj_bbox(obj: dict[str, Any]) -> dict[str, float] | None:
    return normalize_bbox(obj)


def _bbox_center(bbox: dict[str, float]) -> tuple[float, float]:
    return (
        (bbox["x0"] + bbox["x1"]) / 2.0,
        (bbox["top"] + bbox["bottom"]) / 2.0,
    )


def _bbox_intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["x1"] <= b["x0"]
        or b["x1"] <= a["x0"]
        or a["bottom"] <= b["top"]
        or b["bottom"] <= a["top"]
    )


def _expanded_bbox(bbox: dict[str, float], margin: float) -> dict[str, float]:
    return {
        "x0": bbox["x0"] - margin,
        "top": bbox["top"] - margin,
        "x1": bbox["x1"] + margin,
        "bottom": bbox["bottom"] + margin,
    }


def _horizontal_checkbox_edge(bbox: dict[str, float]) -> bool:
    width = bbox_width(bbox)
    height = bbox_height(bbox)
    return (
        CHECKBOX_MIN_SIDE <= width <= CHECKBOX_MAX_SIDE
        and 0.0 < height <= CHECKBOX_MAX_BORDER_THICKNESS
    )


def _vertical_checkbox_edge(bbox: dict[str, float]) -> bool:
    width = bbox_width(bbox)
    height = bbox_height(bbox)
    return (
        CHECKBOX_MIN_SIDE <= height <= CHECKBOX_MAX_SIDE
        and 0.0 < width <= CHECKBOX_MAX_BORDER_THICKNESS
    )


def _curve_is_diagonal_mark(curve: dict[str, Any], bbox: dict[str, float]) -> bool:
    """只识别具有二维面积/斜向点序列的小型内部记号，不把边框当 tick。"""
    width = bbox_width(bbox)
    height = bbox_height(bbox)
    if width < 1.4 or height < 1.4:
        return False
    if width > CHECKBOX_MAX_SIDE or height > CHECKBOX_MAX_SIDE:
        return False

    pts = curve.get("pts")
    if not isinstance(pts, list) or len(pts) < 2:
        return True

    has_diagonal = False
    normalized_pts: list[tuple[float, float]] = []
    for pt in pts:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            normalized_pts.append((float(pt[0]), float(pt[1])))
        except (TypeError, ValueError):
            continue
    for (x0, y0), (x1, y1) in zip(normalized_pts, normalized_pts[1:]):
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        if dx >= 0.8 and dy >= 0.8:
            has_diagonal = True
            break
    return has_diagonal


def detect_native_checkbox_controls(raw_page: dict[str, Any]) -> list[dict[str, Any]]:
    """
    从 Stage1 curves 中检测小方框及内部勾线。

    只使用几何：四边框 + 内部斜向小曲线 + 邻近 native label。
    不使用字段名、页码、case_id 或业务字符串。
    """
    curves = raw_page.get("curves", [])
    if not isinstance(curves, list):
        return []

    boxed: list[tuple[int, dict[str, Any], dict[str, float]]] = []
    for index, curve in enumerate(curves):
        if not isinstance(curve, dict):
            continue
        bbox = _obj_bbox(curve)
        if bbox is None:
            continue
        boxed.append((index, curve, bbox))

    horizontal = [item for item in boxed if _horizontal_checkbox_edge(item[2])]
    vertical = [item for item in boxed if _vertical_checkbox_edge(item[2])]

    candidates: list[dict[str, Any]] = []
    seen: list[dict[str, float]] = []

    for top_index, top_curve, top_bbox in horizontal:
        top_y = (top_bbox["top"] + top_bbox["bottom"]) / 2.0
        for bottom_index, bottom_curve, bottom_bbox in horizontal:
            if bottom_index == top_index:
                continue
            bottom_y = (bottom_bbox["top"] + bottom_bbox["bottom"]) / 2.0
            if bottom_y <= top_y:
                continue

            side = bottom_y - top_y
            avg_width = (bbox_width(top_bbox) + bbox_width(bottom_bbox)) / 2.0
            if not (CHECKBOX_MIN_SIDE <= side <= CHECKBOX_MAX_SIDE):
                continue
            if abs(avg_width - side) > 3.0:
                continue
            if (
                abs(top_bbox["x0"] - bottom_bbox["x0"]) > CHECKBOX_EDGE_TOL
                or abs(top_bbox["x1"] - bottom_bbox["x1"]) > CHECKBOX_EDGE_TOL
            ):
                continue

            x0 = (top_bbox["x0"] + bottom_bbox["x0"]) / 2.0
            x1 = (top_bbox["x1"] + bottom_bbox["x1"]) / 2.0
            box = {
                "x0": x0,
                "top": top_y,
                "x1": x1,
                "bottom": bottom_y,
            }

            left_matches = []
            right_matches = []
            for edge_index, edge_curve, edge_bbox in vertical:
                cx, _ = _bbox_center(edge_bbox)
                if (
                    abs(edge_bbox["top"] - box["top"]) <= CHECKBOX_EDGE_TOL
                    and abs(edge_bbox["bottom"] - box["bottom"]) <= CHECKBOX_EDGE_TOL
                ):
                    if abs(cx - box["x0"]) <= CHECKBOX_EDGE_TOL:
                        left_matches.append((edge_index, edge_bbox))
                    if abs(cx - box["x1"]) <= CHECKBOX_EDGE_TOL:
                        right_matches.append((edge_index, edge_bbox))

            if not left_matches or not right_matches:
                continue

            duplicate = False
            for existing in seen:
                if (
                    abs(existing["x0"] - box["x0"]) <= 1.2
                    and abs(existing["x1"] - box["x1"]) <= 1.2
                    and abs(existing["top"] - box["top"]) <= 1.2
                    and abs(existing["bottom"] - box["bottom"]) <= 1.2
                ):
                    duplicate = True
                    break
            if duplicate:
                continue
            seen.append(box)

            border_indices = {
                top_index,
                bottom_index,
                left_matches[0][0],
                right_matches[0][0],
            }
            expanded = _expanded_bbox(box, CHECKBOX_TICK_MARGIN)
            tick_indices: list[int] = []
            for curve_index, curve, curve_bbox in boxed:
                if curve_index in border_indices:
                    continue
                if not _bbox_intersects(expanded, curve_bbox):
                    continue
                if _curve_is_diagonal_mark(curve, curve_bbox):
                    tick_indices.append(curve_index)

            candidates.append({
                "bbox": box,
                "state": "checked" if tick_indices else "unchecked",
                "confidence": "high",
                "border_curve_indices": sorted(border_indices),
                "tick_curve_indices": sorted(tick_indices),
            })

    words = raw_page.get("words", [])
    if not isinstance(words, list):
        words = []
    page_width = float(raw_page.get("width", 0.0) or 0.0)
    max_gap = max(CHECKBOX_LABEL_MAX_GAP, page_width * 0.06)

    result: list[dict[str, Any]] = []
    page_number = int(raw_page.get("page_number", 0) or 0)
    for candidate_index, candidate in enumerate(
        sorted(candidates, key=lambda item: (item["bbox"]["top"], item["bbox"]["x0"]))
    ):
        box = candidate["bbox"]
        _, box_cy = _bbox_center(box)
        best: tuple[float, float, int, dict[str, Any], dict[str, float]] | None = None

        for word_index, word in enumerate(words):
            if not isinstance(word, dict) or not valid_word(word):
                continue
            wb = word_bbox(word)
            if wb is None:
                continue
            word_cx, word_cy = _bbox_center(wb)
            gap = wb["x0"] - box["x1"]
            if gap < -0.5 or gap > max_gap:
                continue
            vertical_delta = abs(word_cy - box_cy)
            allowed_delta = max(5.0, bbox_height(wb) * 0.70, bbox_height(box) * 0.70)
            if vertical_delta > allowed_delta:
                continue
            score = (gap, vertical_delta, word_index, word, wb)
            if best is None or score[:2] < best[:2]:
                best = score

        control = {
            "control_id": f"p{page_number:04d}_cb{candidate_index + 1:03d}",
            **candidate,
            "label_text": None,
            "label_word_index": None,
            "label_bbox": None,
            "semantics": "NATIVE_VECTOR_CHECKBOX_GEOMETRY",
        }
        if best is not None:
            _, _, word_index, word, wb = best
            control["label_text"] = str(word.get("text") or "").strip() or None
            control["label_word_index"] = word_index
            control["label_bbox"] = wb
        result.append(control)

    return result


def build_page_structure(
    raw_page: dict[str, Any],
    profile_page: dict[str, Any],
    section_page: dict[str, Any],
) -> dict[str, Any]:
    page_number = int(
        raw_page["page_number"]
    )

    page_width = float(
        raw_page.get(
            "width",
            profile_page.get(
                "width",
                0.0,
            ),
        )
    )

    page_height = float(
        raw_page.get(
            "height",
            profile_page.get(
                "height",
                0.0,
            ),
        )
    )

    primary_type = str(
        profile_page.get(
            "primary_type",
            "unknown",
        )
    )

    complexity_prior = (
        build_complexity_prior(
            section_page
        )
    )

    checkbox_controls = detect_native_checkbox_controls(raw_page)

    # -------------------------------------------------------------------------
    # 1. Table
    # -------------------------------------------------------------------------

    table_blocks = build_table_blocks(
        raw_page
    )

    # Stage4 v0.2.6：补充“无线框表格候选”与 native vector checkbox 控件。
    # 这里只基于 native words 的稳定二维列带生成 candidate；
    # 不与 Stage1 table candidate 竞争，也不做跨页拼接。
    gridless_table_candidates = (
        detect_gridless_table_candidates(
            raw_page,
            table_blocks,
        )
        if not bool(profile_page.get("multi_column", False))
        else []
    )
    gridless_owned_word_indices = {
        value
        for candidate in gridless_table_candidates
        for value in candidate.get("source_word_indices", [])
        if isinstance(value, int)
    }

    # -------------------------------------------------------------------------
    # 2. Image
    # -------------------------------------------------------------------------

    image_blocks = build_image_blocks(
        raw_page,
        table_blocks,
    )

    # -------------------------------------------------------------------------
    # 3. Text
    # -------------------------------------------------------------------------

    text_blocks = build_text_blocks(
        raw_page,
        profile_page,
        table_blocks,
        excluded_word_indices=gridless_owned_word_indices,
    )

    # scan_like 页面 native text 可能只是 OCR/text layer。
    # 保留证据，但降低结构置信度。
    if primary_type == "scan_like":
        for block in text_blocks:
            block[
                "structure_confidence"
            ] = "low"

            block[
                "text_role"
            ] = "possible_scan_text_layer"

    # -------------------------------------------------------------------------
    # 4. Vector（只对 vector_graphics）
    # -------------------------------------------------------------------------

    vector_blocks = build_vector_blocks(
        raw_page,
        profile_page,
        table_blocks,
    )

    preliminary_blocks = (
        text_blocks
        + table_blocks
        + image_blocks
        + vector_blocks
    )

    # -------------------------------------------------------------------------
    # 5. 页面边界规范化 + 退化候选隔离
    # -------------------------------------------------------------------------

    (
        blocks,
        degenerate_candidates,
    ) = partition_page_blocks(
        blocks=preliminary_blocks,
        page_number=page_number,
        page_width=page_width,
        page_height=page_height,
        complexity_prior=complexity_prior,
    )

    represented_table_indices = {
        int(item["source_table_index"])
        for item in blocks
        if item.get("block_type") == "table"
        and isinstance(item.get("source_table_index"), int)
    }
    represented_table_indices.update(
        int(item["source_table_index"])
        for item in degenerate_candidates
        if item.get("block_type") == "table"
        and isinstance(item.get("source_table_index"), int)
    )

    degenerate_candidates.extend(
        collect_unrepresented_raw_table_candidates(
            raw_page=raw_page,
            represented_source_indices=represented_table_indices,
            page_number=page_number,
            start_sequence=len(degenerate_candidates)+1,
            complexity_prior=complexity_prior,
        )
    )

    blocks = assign_block_ids(
        page_number,
        blocks,
    )

    boundary_summary = summarize_boundary_fragments(blocks)
    degenerate_summary = summarize_degenerate_candidates(degenerate_candidates)

    type_counts = {
        "text": 0,
        "table": 0,
        "image": 0,
        "vector": 0,
    }

    for block in blocks:
        block_type = str(
            block.get(
                "block_type",
                "",
            )
        )

        if block_type in type_counts:
            type_counts[
                block_type
            ] += 1

    table_detection = raw_page.get(
        "table_detection",
        {},
    )

    return {
        "page_number": page_number,
        "width": page_width,
        "height": page_height,
        "rotation": int(
            raw_page.get(
                "rotation",
                0,
            )
            or 0
        ),

        # Stage4 v0.2.6 supplemental native-layout evidence.
        "checkbox_control_count": len(checkbox_controls),
        "checkbox_controls": checkbox_controls,
        "gridless_table_candidate_count": len(gridless_table_candidates),
        "gridless_table_candidates": gridless_table_candidates,

        # ---------------------------------------------------------------------
        # Stage 1 prior
        # ---------------------------------------------------------------------

        "page_profile": {
            "primary_type": primary_type,
            "multi_column": bool(
                profile_page.get(
                    "multi_column",
                    False,
                )
            ),
            "column_split_x_ratio": profile_page.get(
                "column_split_x_ratio",
                0.0,
            ),
            "native_char_count": profile_page.get(
                "native_char_count"
            ),
            "image_ratio": profile_page.get(
                "image_ratio"
            ),
            "vector_object_count": profile_page.get(
                "vector_object_count"
            ),
        },

        # ---------------------------------------------------------------------
        # Stage 3 document structure
        # ---------------------------------------------------------------------

        "document_structure": {
            "structure_type": section_page.get(
                "structure_type"
            ),
            "section_id": section_page.get(
                "section_id"
            ),
            "section_title": section_page.get(
                "title"
            ),
            "zone_type": section_page.get(
                "zone_type"
            ),
            "boundary_confidence": section_page.get(
                "boundary_confidence"
            ),
            "match_mode": section_page.get(
                "match_mode"
            ),

            "complexity_prior": complexity_prior,
        },

        # ---------------------------------------------------------------------
        # Stage 4 candidate blocks
        # ---------------------------------------------------------------------

        "block_count": len(blocks),
        "block_type_counts": type_counts,
        "blocks": blocks,

        # ---------------------------------------------------------------------
        # 页面边界片段
        # ---------------------------------------------------------------------

        "boundary_summary":
            boundary_summary,

        # ---------------------------------------------------------------------
        # 退化结构候选
        # ---------------------------------------------------------------------

        "degenerate_candidates": degenerate_candidates,
        "degenerate_summary": degenerate_summary,

        # ---------------------------------------------------------------------
        # Status
        # ---------------------------------------------------------------------

        "reading_order_status": "not_resolved",
        "table_structure_status": get_table_structure_status(
            raw_page,
            [
                block
                for block in blocks
                if block.get("block_type") == "table"
            ],
            degenerate_candidates,
        ),
        "table_detection": {
            "mode": table_detection.get(
                "mode"
            ),
            "status": table_detection.get(
                "status"
            ),
            "error": table_detection.get(
                "error"
            ),
        },

        # ---------------------------------------------------------------------
        # 不复制完整底层 evidence，仅保留统计。
        # ---------------------------------------------------------------------

        "raw_evidence_counts": {
            "chars": len(
                raw_page.get(
                    "chars",
                    [],
                )
            ),
            "words": len(
                raw_page.get(
                    "words",
                    [],
                )
            ),
            "images": len(
                raw_page.get(
                    "images",
                    [],
                )
            ),
            "lines": len(
                raw_page.get(
                    "lines",
                    [],
                )
            ),
            "rects": len(
                raw_page.get(
                    "rects",
                    [],
                )
            ),
            "curves": len(
                raw_page.get(
                    "curves",
                    [],
                )
            ),
            "table_candidates": len(
                raw_page.get(
                    "table_candidates",
                    [],
                )
            ),
        },
    }


# =============================================================================
# Input validation + entire document
# =============================================================================


def validate_lightweight_inputs(
    snapshot_meta: dict[str, Any],
    profile_result: dict[str, Any],
    aligner_result: dict[str, Any],
) -> tuple[
    int,
    str,
]:
    try:
        snapshot_page_count = int(
            snapshot_meta["page_count"]
        )
        profile_page_count = int(
            profile_result["page_count"]
        )
        aligner_page_count = int(
            aligner_result["page_count"]
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Stage 1 / Stage 3 输入缺少有效 page_count。"
        ) from exc

    if not (
        snapshot_page_count
        == profile_page_count
        == aligner_page_count
    ):
        raise ValueError(
            "输入页数不一致: "
            f"snapshot={snapshot_page_count}, "
            f"profile={profile_page_count}, "
            f"alignment={aligner_page_count}"
        )

    source_file = str(
        snapshot_meta.get(
            "source_file",
            "",
        )
    )

    profile_source_file = str(
        profile_result.get(
            "source_file",
            "",
        )
    )

    aligner_source_file = str(
        aligner_result.get(
            "source_file",
            "",
        )
    )

    if not source_file:
        raise ValueError(
            "Raw Evidence meta 缺少 source_file。"
        )

    if source_file != profile_source_file:
        raise ValueError(
            "Raw Evidence 与 Page Profile source_file 不一致: "
            f"{source_file} != {profile_source_file}"
        )

    if source_file != aligner_source_file:
        raise ValueError(
            "Raw Evidence 与 Section Alignment source_file 不一致: "
            f"{source_file} != {aligner_source_file}"
        )

    return (
        snapshot_page_count,
        source_file,
    )


def build_document_structure(
    snapshot_path: Path,
    profile_path: Path,
    aligner_path: Path,
    *,
    snapshot_meta: dict[str, Any] | None = None,
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
    section_alignment: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if (snapshot_meta is None) != (snapshot_pages is None):
        raise ValueError("snapshot_meta and snapshot_pages must be provided together")
    if snapshot_pages is None and not snapshot_path.exists():
        raise FileNotFoundError(
            f"Raw Evidence JSONL 不存在: {snapshot_path}"
        )

    profile_result = (
        profile if profile is not None
        else load_json(profile_path)
    )

    aligner_result = (
        section_alignment if section_alignment is not None
        else load_json(aligner_path)
    )

    profile_pages = build_page_index(
        profile_result
    )

    section_pages = build_page_index(
        aligner_result
    )

    snapshot_input = (
        nullcontext(None) if snapshot_pages is not None
        else snapshot_path.open("r", encoding="utf-8")
    )
    with snapshot_input as snapshot_file:
        if snapshot_pages is None:
            snapshot_meta = read_snapshot_meta(snapshot_file, snapshot_path)
            raw_pages = iter_snapshot_pages(snapshot_file)
        else:
            raw_pages = snapshot_pages.values()

        (
            page_count,
            source_file,
        ) = validate_lightweight_inputs(
            snapshot_meta,
            profile_result,
            aligner_result,
        )

        expected_pages = set(
            range(
                1,
                page_count + 1,
            )
        )

        if set(
            profile_pages.keys()
        ) != expected_pages:
            raise ValueError(
                "Page Profile pages[] 不是完整连续的 1..page_count。"
            )

        if set(
            section_pages.keys()
        ) != expected_pages:
            raise ValueError(
                "Section Alignment pages[] 不是完整连续的 1..page_count。"
            )

        pages: list[
            dict[str, Any]
        ] = []

        seen_snapshot_pages: set[
            int
        ] = set()

        for raw_page in raw_pages:
            page_number = int(
                raw_page["page_number"]
            )

            if page_number in seen_snapshot_pages:
                raise ValueError(
                    f"Raw Evidence 出现重复页面: PDF第{page_number}页。"
                )

            seen_snapshot_pages.add(
                page_number
            )

            profile_page = profile_pages.get(
                page_number
            )

            section_page = section_pages.get(
                page_number
            )

            if profile_page is None:
                raise ValueError(
                    f"Page Profile 缺少 PDF第{page_number}页。"
                )

            if section_page is None:
                raise ValueError(
                    f"Section Alignment 缺少 PDF第{page_number}页。"
                )

            pages.append(
                build_page_structure(
                    raw_page,
                    profile_page,
                    section_page,
                )
            )

        if seen_snapshot_pages != expected_pages:
            missing = sorted(
                expected_pages
                - seen_snapshot_pages
            )

            extra = sorted(
                seen_snapshot_pages
                - expected_pages
            )

            raise ValueError(
                "Raw Evidence 页映射不完整。"
                f" missing={missing}, extra={extra}"
            )

    pages.sort(
        key=lambda page: int(
            page["page_number"]
        )
    )

    boundary_summary = (
        summarize_document_boundary_fragments(
            pages
        )
    )

    degenerate_summary = (
        summarize_document_degenerate_candidates(
            pages
        )
    )

    cross_page_table_candidates = (
        build_cross_page_table_candidates(
            pages
        )
    )

    result = {
        "builder_version": BUILDER_VERSION,
        "structure_schema_version": STRUCTURE_SCHEMA_VERSION,
        "source_file": source_file,
        "page_count": page_count,
        "inputs": {
            "raw_evidence": str(
                snapshot_path
            ),
            "page_profile": str(
                profile_path
            ),
            "section_alignment": str(
                aligner_path
            ),
        },
        "upstream_versions": {
            "snapshot_schema_version": snapshot_meta.get(
                "snapshot_schema_version"
            ),
            "page_scan_version": snapshot_meta.get(
                "page_scan_version"
            ),
            "profiler_version": profile_result.get(
                "profiler_version"
            ),
            "section_aligner_version": aligner_result.get(
                "aligner_version"
            ),
        },
        "structure_mode": aligner_result.get(
            "structure_mode"
        ),

        "boundary_summary":
            boundary_summary,

        "degenerate_summary":
            degenerate_summary,

        "cross_page_table_candidate_count":
            len(
                cross_page_table_candidates
            ),

        "cross_page_table_candidates":
            cross_page_table_candidates,

        "checkbox_control_count": sum(
            int(page.get("checkbox_control_count", 0) or 0)
            for page in pages
        ),
        "checkbox_checked_count": sum(
            1
            for page in pages
            for control in page.get("checkbox_controls", [])
            if isinstance(control, dict) and control.get("state") == "checked"
        ),
        "checkbox_control_pages": [
            int(page["page_number"])
            for page in pages
            if int(page.get("checkbox_control_count", 0) or 0) > 0
        ],

        "gridless_table_candidate_count": sum(
            int(page.get("gridless_table_candidate_count", 0) or 0)
            for page in pages
        ),
        "gridless_table_candidate_pages": [
            int(page["page_number"])
            for page in pages
            if int(page.get("gridless_table_candidate_count", 0) or 0) > 0
        ],

        "pages":
            pages,
    }

    # Stage 4 这里只做“结构构建自检”：
    # 检查输入是否完整、block 是否自洽、bbox 是否有效、
    # table candidate 是否在 Stage 4 中丢失等。
    #
    # 这不是 Quality Gate：
    # 不代表表格内容正确、阅读顺序正确、OCR 正确。
    result[
        "validation"
    ] = validate_stage4_result(
        result
    )

    return result


# =============================================================================
# Stage 4 Validation
# =============================================================================


def validate_block_bbox(
    bbox: Any,
    page_width: float,
    page_height: float,
    *,
    require_inside_page: bool = True,
    tolerance: float = 1.0,
) -> tuple[
    bool,
    str | None,
]:
    """
    验证 bbox 的结构合法性。

    Stage 4 v0.2.2 开始区分：

        bbox
            当前物理页局部几何，必须位于页面内。

        original_bbox
            原始几何，允许因为跨页结构而越过当前物理页。

    因此：
        original_bbox 越界 != Stage 4 FAIL。
    """
    normalized = normalize_bbox(
        bbox
    )

    if normalized is None:
        return (
            False,
            "bbox 格式无效",
        )

    if not bbox_is_finite(
        normalized
    ):
        return (
            False,
            "bbox 含 NaN 或无穷值",
        )

    if (
        normalized[
            "x1"
        ]
        <= normalized[
            "x0"
        ]
        or normalized[
            "bottom"
        ]
        <= normalized[
            "top"
        ]
    ):
        return (
            False,
            "bbox 面积无效",
        )

    if not require_inside_page:
        return (
            True,
            None,
        )

    if (
        normalized[
            "x0"
        ]
        < -tolerance
        or normalized[
            "top"
        ]
        < -tolerance
        or normalized[
            "x1"
        ]
        > page_width
        + tolerance
        or normalized[
            "bottom"
        ]
        > page_height
        + tolerance
    ):
        return (
            False,
            "当前页 bbox 超出页面范围",
        )

    return (
        True,
        None,
    )


def validate_stage4_page(
    page: dict[str, Any],
) -> dict[str, Any]:
    """
    对单页做 Stage 4 内部一致性验证。

    FAIL：
        Stage 4 自己构建出的数据已经不自洽，
        不应该直接进入下一阶段。

    WARN：
        数据结构可继续使用，
        但存在值得后续检查的页面。

    PASS：
        Stage 4 自身结构检查通过。

    注意：
        PASS 不等于“PDF 已解析正确”。
    """
    errors: list[
        dict[str, str]
    ] = []

    warnings: list[
        dict[str, str]
    ] = []

    page_number = int(
        page[
            "page_number"
        ]
    )

    page_width = float(
        page.get(
            "width",
            0.0,
        )
    )

    page_height = float(
        page.get(
            "height",
            0.0,
        )
    )

    blocks = page.get(
        "blocks",
        [],
    )

    if not isinstance(
        blocks,
        list,
    ):
        errors.append(
            {
                "code":
                    "blocks_not_list",

                "message":
                    "blocks 不是列表。",
            }
        )

        blocks = []

    # -------------------------------------------------------------------------
    # 1. block_count / type_counts
    # -------------------------------------------------------------------------

    declared_block_count = int(
        page.get(
            "block_count",
            0,
        )
        or 0
    )

    if declared_block_count != len(
        blocks
    ):
        errors.append(
            {
                "code":
                    "block_count_mismatch",

                "message":
                    (
                        "block_count 与实际 blocks 数量不一致："
                        f"{declared_block_count} != {len(blocks)}"
                    ),
            }
        )

    actual_type_counts = {
        "text": 0,
        "table": 0,
        "image": 0,
        "vector": 0,
    }

    block_ids: list[
        str
    ] = []

    for block in blocks:
        block_type = str(
            block.get(
                "block_type",
                "",
            )
        )

        if block_type in actual_type_counts:
            actual_type_counts[
                block_type
            ] += 1

        else:
            warnings.append(
                {
                    "code":
                        "unknown_block_type",

                    "message":
                        f"发现未知 block_type={block_type!r}。",
                }
            )

        block_id = str(
            block.get(
                "block_id",
                "",
            )
        )

        if not block_id:
            errors.append(
                {
                    "code":
                        "missing_block_id",

                    "message":
                        "存在缺少 block_id 的结构块。",
                }
            )
        else:
            block_ids.append(
                block_id
            )

        # -------------------------------------------------------------
        # 当前物理页 bbox 必须合法且位于页面内。
        # -------------------------------------------------------------

        bbox_ok, bbox_error = (
            validate_block_bbox(
                block.get(
                    "bbox"
                ),
                page_width,
                page_height,
                require_inside_page=True,
            )
        )

        if not bbox_ok:
            errors.append(
                {
                    "code":
                        "invalid_page_bbox",

                    "message":
                        (
                            f"{block_id or '<无ID>'}："
                            f"{bbox_error}"
                        ),
                }
            )

        # -------------------------------------------------------------
        # original_bbox 允许越过当前物理页；
        # 只检查格式、有限值和面积。
        # -------------------------------------------------------------

        original_bbox = block.get(
            "original_bbox"
        )

        if original_bbox is not None:
            original_ok, original_error = (
                validate_block_bbox(
                    original_bbox,
                    page_width,
                    page_height,
                    require_inside_page=False,
                )
            )

            if not original_ok:
                errors.append(
                    {
                        "code":
                            "invalid_original_bbox",

                        "message":
                            (
                                f"{block_id or '<无ID>'}："
                                f"原始 bbox 无效：{original_error}"
                            ),
                    }
                )

        bbox_clipped = bool(
            block.get(
                "bbox_clipped",
                False,
            )
        )

        boundary_fragment = bool(
            block.get(
                "boundary_fragment",
                False,
            )
        )

        overflow_info = block.get(
            "boundary_overflow",
            {},
        )

        has_overflow = bool(
            overflow_info.get(
                "has_overflow",
                False,
            )
        )

        if bbox_clipped != boundary_fragment:
            errors.append(
                {
                    "code":
                        "boundary_flag_mismatch",

                    "message":
                        (
                            f"{block_id or '<无ID>'}："
                            "bbox_clipped 与 boundary_fragment 不一致。"
                        ),
                }
            )

        if has_overflow:
            if not bbox_clipped:
                errors.append(
                    {
                        "code":
                            "overflow_not_clipped",

                        "message":
                            (
                                f"{block_id or '<无ID>'}："
                                "检测到原始 bbox 越界，但没有生成页内 bbox。"
                            ),
                    }
                )

            if original_bbox is None:
                errors.append(
                    {
                        "code":
                            "missing_original_bbox",

                        "message":
                            (
                                f"{block_id or '<无ID>'}："
                                "边界片段缺少 original_bbox。"
                            ),
                    }
                )

        elif bbox_clipped:
            errors.append(
                {
                    "code":
                        "unexpected_bbox_clipped",

                    "message":
                        (
                            f"{block_id or '<无ID>'}："
                            "没有检测到越界却标记 bbox_clipped=True。"
                        ),
                }
            )

        if (
            block_type
            == "text"
            and not str(
                block.get(
                    "text",
                    "",
                )
            ).strip()
        ):
            errors.append(
                {
                    "code":
                        "empty_text_block",

                    "message":
                        f"{block_id or '<无ID>'} 文本块为空。",
                }
            )

        if (
            block_type
            == "table"
            and not isinstance(
                block.get(
                    "source_table_index"
                ),
                int,
            )
        ):
            errors.append(
                {
                    "code":
                        "missing_table_source",

                    "message":
                        (
                            f"{block_id or '<无ID>'} "
                            "缺少有效 source_table_index。"
                        ),
                }
            )

    if len(
        block_ids
    ) != len(
        set(
            block_ids
        )
    ):
        errors.append(
            {
                "code":
                    "duplicate_block_id",

                "message":
                    "同一页面存在重复 block_id。",
            }
        )

    declared_type_counts = page.get(
        "block_type_counts",
        {},
    )

    for block_type, actual_count in (
        actual_type_counts.items()
    ):
        declared_count = int(
            declared_type_counts.get(
                block_type,
                0,
            )
            or 0
        )

        if declared_count != actual_count:
            errors.append(
                {
                    "code":
                        "block_type_count_mismatch",

                    "message":
                        (
                            f"{block_type} 数量不一致："
                            f"{declared_count} != {actual_count}"
                        ),
                }
            )

    # -------------------------------------------------------------------------
    # 2. Stage 3 映射是否仍然存在
    # -------------------------------------------------------------------------

    document_structure = page.get(
        "document_structure",
        {},
    )

    structure_type = document_structure.get(
        "structure_type"
    )

    if (
        structure_type is None
        or str(
            structure_type
        )
        == "unassigned"
    ):
        errors.append(
            {
                "code":
                    "missing_document_structure",

                "message":
                    "该页没有有效的 Stage 3 页面结构映射。",
            }
        )

    # -------------------------------------------------------------------------
    # 3. Table candidate 是否在 Stage 4 中丢失
    # -------------------------------------------------------------------------

    raw_counts = page.get(
        "raw_evidence_counts",
        {},
    )

    raw_table_candidates = int(
        raw_counts.get(
            "table_candidates",
            0,
        )
        or 0
    )

    table_block_count = (
        actual_type_counts[
            "table"
        ]
    )

    degenerate_candidates = page.get(
        "degenerate_candidates",
        [],
    )

    if not isinstance(
        degenerate_candidates,
        list,
    ):
        errors.append(
            {
                "code": "degenerate_candidates_not_list",
                "message": "degenerate_candidates 不是列表。",
            }
        )
        degenerate_candidates = []

    degenerate_table_count = sum(
        1
        for item in degenerate_candidates
        if str(item.get("block_type", "")) == "table"
    )

    accounted_table_candidates = (
        table_block_count
        + degenerate_table_count
    )

    if raw_table_candidates != accounted_table_candidates:
        errors.append(
            {
                "code": "table_candidate_loss",
                "message": (
                    "Stage 1 table candidate 未被完整保留："
                    f"raw={raw_table_candidates}，"
                    f"normal_block={table_block_count}，"
                    f"degenerate={degenerate_table_count}。"
                ),
            }
        )

    # ---------------------------------------------------------------------
    # 3.1 退化候选自身一致性
    # ---------------------------------------------------------------------

    degenerate_ids: list[str] = []

    for candidate in degenerate_candidates:
        candidate_id = str(candidate.get("candidate_id", ""))
        if not candidate_id:
            errors.append(
                {
                    "code": "missing_degenerate_candidate_id",
                    "message": "存在缺少 candidate_id 的退化候选。",
                }
            )
        else:
            degenerate_ids.append(candidate_id)

        if not str(candidate.get("reason_code", "")):
            errors.append(
                {
                    "code": "missing_degenerate_reason",
                    "message": f"{candidate_id or '<无ID>'}：退化候选缺少 reason_code。",
                }
            )

        if (
            str(candidate.get("block_type", "")) == "table"
            and not isinstance(candidate.get("source_table_index"), int)
        ):
            errors.append(
                {
                    "code": "missing_degenerate_table_source",
                    "message": (
                        f"{candidate_id or '<无ID>'}："
                        "退化表格候选缺少 source_table_index。"
                    ),
                }
            )

    if len(degenerate_ids) != len(set(degenerate_ids)):
        errors.append(
            {
                "code": "duplicate_degenerate_candidate_id",
                "message": "同一页面存在重复的退化候选 candidate_id。",
            }
        )

    if degenerate_candidates:
        complexity = page.get("document_structure", {}).get("complexity_prior", {})
        warnings.append(
            {
                "code": "degenerate_candidates_quarantined",
                "message": (
                    f"已隔离 {len(degenerate_candidates)} 个退化结构候选"
                    f"（其中表格={degenerate_table_count}）；"
                    "未伪造 bbox，Stage 1 原始证据仍保留。"
                    f"区域复杂度先验={complexity.get('level_cn', '未知')}。"
                ),
            }
        )

    table_status = str(
        page.get(
            "table_structure_status",
            "unknown",
        )
    )

    table_detection = page.get(
        "table_detection",
        {},
    )

    detection_status = str(
        table_detection.get(
            "status",
            "unknown",
        )
    )

    if table_block_count > 0:
        if table_status != "candidate_only":
            errors.append(
                {
                    "code": "table_status_mismatch",
                    "message": (
                        "存在 table block，"
                        "但 table_structure_status "
                        f"不是 candidate_only：{table_status}"
                    ),
                }
            )

    elif degenerate_table_count > 0:
        if table_status != "candidate_degenerate":
            errors.append(
                {
                    "code": "degenerate_table_status_mismatch",
                    "message": (
                        "仅存在退化 table candidate 时，"
                        "table_structure_status 应为 candidate_degenerate。"
                    ),
                }
            )

    else:
        if table_status in {"candidate_only", "candidate_degenerate"}:
            errors.append(
                {
                    "code": "table_status_mismatch",
                    "message": (
                        "没有正常或退化 table candidate，"
                        f"却标记为 {table_status}。"
                    ),
                }
            )

    if detection_status == "error":
        warnings.append(
            {
                "code":
                    "table_detection_error",

                "message":
                    "Stage 1 表格检测发生异常，当前页表格结构需要后续关注。",
            }
        )

    # -------------------------------------------------------------------------
    # 4. 页面形态与结构块之间的明显异常
    # -------------------------------------------------------------------------

    profile = page.get(
        "page_profile",
        {},
    )

    primary_type = str(
        profile.get(
            "primary_type",
            "unknown",
        )
    )

    raw_char_count = int(
        raw_counts.get(
            "chars",
            0,
        )
        or 0
    )

    raw_image_count = int(
        raw_counts.get(
            "images",
            0,
        )
        or 0
    )

    if (
        primary_type
        == "scan_like"
        and raw_image_count
        <= 0
    ):
        warnings.append(
            {
                "code":
                    "scan_like_without_image",

                "message":
                    "页面被判为扫描型，但 Raw Evidence 中没有 image object。",
            }
        )

    if (
        primary_type
        == "native_text"
        and raw_char_count
        > 0
        and actual_type_counts[
            "text"
        ]
        == 0
        and actual_type_counts[
            "table"
        ]
        == 0
        and len(
            degenerate_candidates
        )
        == 0
    ):
        warnings.append(
            {
                "code":
                    "native_text_without_text_block",

                "message":
                    "原生文本页存在字符，但没有生成 text/table block。",
            }
        )

    if (
        len(
            blocks
        )
        == 0
        and len(
            degenerate_candidates
        )
        == 0
        and (
            raw_char_count
            > 0
            or raw_image_count
            > 0
        )
    ):
        warnings.append(
            {
                "code":
                    "evidence_without_blocks",

                "message":
                    "页面存在底层证据，但 Stage 4 没有生成任何结构块。",
            }
        )

    if errors:
        status = "FAIL"
        status_cn = "未通过"

    elif warnings:
        status = "WARN"
        status_cn = "通过（有警告）"

    else:
        status = "PASS"
        status_cn = "通过"

    return {
        "page_number":
            page_number,

        "status":
            status,

        "status_cn":
            status_cn,

        "error_count":
            len(
                errors
            ),

        "warning_count":
            len(
                warnings
            ),

        "errors":
            errors,

        "warnings":
            warnings,
    }


def validate_stage4_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Stage 4 的验证只说明：

        页面结构候选是否“自洽、完整、可继续处理”。

    特别说明：

        跨页表格 / 跨页文本 / 边界图片产生的原始 bbox 越界，
        只要已经保留 original_bbox 并生成合法 page-local bbox，
        就属于“边界片段信息”，不计为 Stage 4 错误。

    它不说明：

        - 表格行列已经正确
        - rowspan / colspan 已正确
        - 阅读顺序已正确
        - OCR 已正确
        - 页面内容已经可以直接喂给 LLM

    那些属于后续 Quality Gate / Recovery。
    """
    page_results = [
        validate_stage4_page(
            page
        )
        for page in result.get(
            "pages",
            [],
        )
    ]

    failed_pages = [
        item[
            "page_number"
        ]
        for item in page_results
        if item[
            "status"
        ]
        == "FAIL"
    ]

    warning_pages = [
        item[
            "page_number"
        ]
        for item in page_results
        if item[
            "status"
        ]
        == "WARN"
    ]

    passed_pages = [
        item[
            "page_number"
        ]
        for item in page_results
        if item[
            "status"
        ]
        == "PASS"
    ]

    total_errors = sum(
        int(
            item[
                "error_count"
            ]
        )
        for item in page_results
    )

    total_warnings = sum(
        int(
            item[
                "warning_count"
            ]
        )
        for item in page_results
    )

    if failed_pages:
        overall_status = "FAIL"
        overall_status_cn = "未通过"
        can_continue = False

    elif warning_pages:
        overall_status = "WARN"
        overall_status_cn = "通过（有警告）"
        can_continue = True

    else:
        overall_status = "PASS"
        overall_status_cn = "通过"
        can_continue = True

    return {
        "validation_scope":
            "stage4_internal_consistency",

        "validation_scope_cn":
            "阶段4结构构建内部一致性",

        "quality_gate_completed":
            False,

        "quality_gate_note":
            (
                "当前验证不代表最终解析质量通过；"
                "只验证 Stage 4 输出是否自洽并可进入后续结构恢复。"
            ),

        "overall_status":
            overall_status,

        "overall_status_cn":
            overall_status_cn,

        "can_continue_to_next_stage":
            can_continue,

        "page_count":
            len(
                page_results
            ),

        "passed_page_count":
            len(
                passed_pages
            ),

        "warning_page_count":
            len(
                warning_pages
            ),

        "failed_page_count":
            len(
                failed_pages
            ),

        "error_count":
            total_errors,

        "warning_count":
            total_warnings,

        "passed_pages":
            passed_pages,

        "warning_pages":
            warning_pages,

        "failed_pages":
            failed_pages,

        "pages":
            page_results,
    }


# =============================================================================
# Terminal Summary
# =============================================================================


def text_display_width(
    text: str,
) -> int:
    """
    计算终端实际显示宽度。

    中文 / 全角字符通常占 2 格，
    普通英文、数字占 1 格。
    """
    return sum(
        2
        if unicodedata.east_asian_width(
            char
        )
        in {
            "W",
            "F",
        }
        else 1

        for char in str(
            text
        )
    )


def align_text(
    value: Any,
    width: int,
    align: str = "left",
) -> str:
    """
    按真实终端显示宽度对齐中英文。
    """
    text = str(
        value
    )

    # 超过列宽时按真实显示宽度截断，
    # 避免中文标题把终端表格撑歪。
    if text_display_width(
        text
    ) > width:
        target_width = max(
            1,
            width
            - 1,
        )

        kept: list[
            str
        ] = []

        kept_width = 0

        for char in text:
            char_width = (
                text_display_width(
                    char
                )
            )

            if (
                kept_width
                + char_width
                > target_width
            ):
                break

            kept.append(
                char
            )

            kept_width += char_width

        text = (
            "".join(
                kept
            )
            + "…"
        )

    current_width = (
        text_display_width(
            text
        )
    )

    padding = max(
        0,
        width
        - current_width
    )

    if align == "right":
        return (
            " " * padding
            + text
        )

    if align == "center":
        left_padding = (
            padding
            // 2
        )

        right_padding = (
            padding
            - left_padding
        )

        return (
            " " * left_padding
            + text
            + " " * right_padding
        )

    return (
        text
        + " " * padding
    )


def display_primary_type(
    primary_type: str,
) -> str:
    mapping = {
        "native_text":
            "原生文本",

        "scan_like":
            "扫描型",

        "mixed_image_text":
            "图文混合",

        "vector_graphics":
            "矢量图形",

        "sparse":
            "稀疏",
    }

    return mapping.get(
        primary_type,
        primary_type,
    )


def display_zone_type(
    zone_type: Any,
) -> str:
    mapping = {
        "semi_free":
            "半自由区",

        "free":
            "自由区",
    }

    value = (
        str(
            zone_type
        )
        if zone_type
        else "-"
    )

    return mapping.get(
        value,
        value,
    )


def display_complexity_prior(
    value: Any,
) -> str:
    if isinstance(value, dict):
        level = str(value.get("level", "unknown"))
    else:
        level = str(value)

    mapping = {
        "normal": "常规",
        "medium": "中",
        "high": "高",
        "very_high": "很高",
        "unknown": "未知",
    }
    return mapping.get(level, level)


def display_table_status(
    status: str,
) -> str:
    mapping = {
        "candidate_only":
            "候选待恢复",

        "candidate_degenerate":
            "退化候选",

        "not_scanned":
            "未检测",

        "detection_error":
            "检测异常",

        "no_candidate":
            "未发现候选",

        "unknown":
            "未知",
    }

    return mapping.get(
        status,
        status,
    )


def display_validation_status(
    status: str,
) -> str:
    mapping = {
        "PASS":
            "通过",

        "WARN":
            "有警告",

        "FAIL":
            "未通过",
    }

    return mapping.get(
        status,
        status,
    )


def print_validation_details(
    validation: dict[str, Any],
) -> None:
    """
    只打印有问题页面，避免终端刷屏。
    """
    page_results = validation.get(
        "pages",
        [],
    )

    issue_pages = [
        item
        for item in page_results
        if item.get(
            "status"
        )
        != "PASS"
    ]

    if not issue_pages:
        return

    print()
    print(
        "需要关注的页面："
    )

    for item in issue_pages:
        page_number = item[
            "page_number"
        ]

        for error in item.get(
            "errors",
            [],
        ):
            print(
                f"  PDF第{page_number:>3}页 "
                f"| 错误 "
                f"| {error['message']}"
            )

        for warning in item.get(
            "warnings",
            [],
        ):
            print(
                f"  PDF第{page_number:>3}页 "
                f"| 警告 "
                f"| {warning['message']}"
            )


def print_summary(
    result: dict[str, Any],
) -> None:
    columns = [
        (
            "页码",
            4,
            "right",
        ),
        (
            "页面类型",
            10,
            "left",
        ),
        (
            "多栏",
            4,
            "center",
        ),
        (
            "章节/区域",
            22,
            "left",
        ),
        (
            "区域类型",
            10,
            "left",
        ),
        (
            "复杂度",
            6,
            "center",
        ),
        (
            "文本块",
            6,
            "right",
        ),
        (
            "表格块",
            6,
            "right",
        ),
        (
            "图片块",
            6,
            "right",
        ),
        (
            "矢量块",
            6,
            "right",
        ),
        (
            "表格状态",
            12,
            "left",
        ),
        (
            "边界片段",
            8,
            "right",
        ),
        (
            "退化候选",
            8,
            "right",
        ),
        (
            "页验证",
            8,
            "left",
        ),
    ]

    separator = " | "

    table_width = (
        sum(
            width
            for (
                _,
                width,
                _,
            ) in columns
        )
        +
        text_display_width(
            separator
        )
        * (
            len(
                columns
            )
            - 1
        )
    )

    print()
    print(
        "=" * table_width
    )

    print(
        f"页面结构构建器 | "
        f"{result['source_file']} "
        f"| 页数="
        f"{result['page_count']} "
        f"| 版本="
        f"{result['builder_version']}"
    )

    print(
        "=" * table_width
    )

    header = separator.join(
        align_text(
            title,
            width,
            align,
        )
        for (
            title,
            width,
            align,
        ) in columns
    )

    print(
        header
    )

    print(
        "-" * table_width
    )

    totals = {
        "text": 0,
        "table": 0,
        "image": 0,
        "vector": 0,
    }

    validation = result.get(
        "validation",
        {}
    )

    page_validation_index = {
        int(
            item[
                "page_number"
            ]
        ):
            str(
                item.get(
                    "status",
                    "PASS",
                )
            )

        for item in validation.get(
            "pages",
            [],
        )
    }

    for page in result[
        "pages"
    ]:
        counts = page[
            "block_type_counts"
        ]

        for key in totals:
            totals[
                key
            ] += int(
                counts[
                    key
                ]
            )

        profile = page[
            "page_profile"
        ]

        structure = page[
            "document_structure"
        ]

        primary_type = (
            display_primary_type(
                str(
                    profile.get(
                        "primary_type",
                        "unknown",
                    )
                )
            )
        )

        multi_column = (
            "是"
            if profile.get(
                "multi_column"
            )
            else "否"
        )

        section_display = (
            structure.get(
                "section_title"
            )
            or structure.get(
                "section_id"
            )
            or structure.get(
                "structure_type"
            )
            or "-"
        )

        zone_display = (
            display_zone_type(
                structure.get(
                    "zone_type"
                )
            )
        )

        complexity_display = (
            display_complexity_prior(
                structure.get(
                    "complexity_prior",
                    {},
                )
            )
        )

        table_status = (
            display_table_status(
                str(
                    page.get(
                        "table_structure_status",
                        "unknown",
                    )
                )
            )
        )

        page_validation = (
            display_validation_status(
                page_validation_index.get(
                    int(
                        page[
                            "page_number"
                        ]
                    ),
                    "PASS",
                )
            )
        )

        values = [
            page[
                "page_number"
            ],
            primary_type,
            multi_column,
            section_display,
            zone_display,
            complexity_display,
            counts[
                "text"
            ],
            counts[
                "table"
            ],
            counts[
                "image"
            ],
            counts[
                "vector"
            ],
            table_status,
            page.get(
                "boundary_summary",
                {},
            ).get(
                "fragment_count",
                0,
            ),
            page.get(
                "degenerate_summary",
                {},
            ).get(
                "candidate_count",
                0,
            ),
            page_validation,
        ]

        print(
            separator.join(
                align_text(
                    value,
                    width,
                    align,
                )
                for (
                    value,
                    (
                        _,
                        width,
                        align,
                    ),
                ) in zip(
                    values,
                    columns,
                )
            )
        )

    print(
        "-" * table_width
    )

    print(
        "结构块总计："
        f"文本={totals['text']} "
        f"| 表格={totals['table']} "
        f"| 图片={totals['image']} "
        f"| 矢量={totals['vector']}"
    )

    print(
        "输入一致性检查：通过"
    )

    boundary_summary = result.get(
        "boundary_summary",
        {},
    )

    print(
        "页面边界片段："
        f"{boundary_summary.get('fragment_count', 0)} 个 "
        f"| 涉及 {boundary_summary.get('page_count', 0)} 页 "
        f"| 表格={boundary_summary.get('type_counts', {}).get('table', 0)} "
        f"| 文本={boundary_summary.get('type_counts', {}).get('text', 0)} "
        f"| 图片={boundary_summary.get('type_counts', {}).get('image', 0)} "
        f"| 矢量={boundary_summary.get('type_counts', {}).get('vector', 0)}"
    )

    degenerate_summary = result.get(
        "degenerate_summary",
        {},
    )

    print(
        "退化结构候选："
        f"{degenerate_summary.get('candidate_count', 0)} 个 "
        f"| 涉及 {degenerate_summary.get('page_count', 0)} 页 "
        f"| 表格={degenerate_summary.get('type_counts', {}).get('table', 0)} "
        f"| 文本={degenerate_summary.get('type_counts', {}).get('text', 0)} "
        f"| 图片={degenerate_summary.get('type_counts', {}).get('image', 0)} "
        f"| 矢量={degenerate_summary.get('type_counts', {}).get('vector', 0)}"
    )

    print(
        "跨页表格候选："
        f"{result.get('cross_page_table_candidate_count', 0)} 个"
    )

    print(
        "无线框表格候选："
        f"{result.get('gridless_table_candidate_count', 0)} 个 "
        f"| 涉及 {len(result.get('gridless_table_candidate_pages', []))} 页"
    )

    overall_status = str(
        validation.get(
            "overall_status",
            "PASS",
        )
    )

    print(
        "阶段4结构验证："
        f"{validation.get('overall_status_cn', display_validation_status(overall_status))}"
    )

    print(
        "验证页面统计："
        f"通过={validation.get('passed_page_count', 0)} "
        f"| 有警告={validation.get('warning_page_count', 0)} "
        f"| 未通过={validation.get('failed_page_count', 0)}"
    )

    print(
        "验证问题统计："
        f"错误={validation.get('error_count', 0)} "
        f"| 警告={validation.get('warning_count', 0)}"
    )

    print(
        "是否可以进入下一阶段："
        + (
            "是"
            if validation.get(
                "can_continue_to_next_stage",
                False,
            )
            else "否"
        )
    )

    print(
        "说明：这里验证的是 Stage 4 输出是否自洽，"
        "不是最终解析质量，也不是 Quality Gate。"
    )

    print(
        "边界说明：跨页/越页结构保留为“页面边界片段”；"
        "无有效页面面积的异常候选保留为“退化结构候选”。"
    )

    print(
        "复杂度说明：可行性分析报告与附件内容使用更高复杂度先验，"
        "该先验只影响后续解析警惕程度，不代表页面质量失败。"
    )

    print_validation_details(
        validation
    )

    cross_page_candidates = result.get(
        "cross_page_table_candidates",
        [],
    )

    if cross_page_candidates:
        print()
        print(
            "跨页表格候选："
        )

        max_display = 20

        for candidate in cross_page_candidates[
            :max_display
        ]:
            print(
                f"  PDF第{candidate['from_page']:>3}页 "
                f"{candidate['from_block_id']} "
                f"→ PDF第{candidate['to_page']:>3}页 "
                f"{candidate['to_block_id']} "
                f"| 横向重合={candidate['x_overlap_ratio']:.3f} "
                f"| 宽度相似={candidate['width_similarity']:.3f} "
                f"| 候选分={candidate['candidate_score']:.3f}"
            )

        if (
            len(
                cross_page_candidates
            )
            > max_display
        ):
            print(
                f"  ……其余 "
                f"{len(cross_page_candidates) - max_display} "
                f"个候选已写入 JSON。"
            )

    print(
        "=" * table_width
    )


# =============================================================================
# CLI
# =============================================================================


def run_page_structure(
    *,
    snapshot_path: Path,
    profile_path: Path,
    alignment_path: Path,
    output_path: Path,
    snapshot_meta: dict[str, Any] | None = None,
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
    section_alignment: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Stage 4 through the package API while preserving its artifact format."""
    result = build_document_structure(
        snapshot_path=Path(snapshot_path),
        profile_path=Path(profile_path),
        aligner_path=Path(alignment_path),
        snapshot_meta=snapshot_meta,
        snapshot_pages=snapshot_pages,
        section_alignment=section_alignment,
        profile=profile,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result
