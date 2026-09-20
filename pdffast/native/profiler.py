from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from statistics import mean, median
from typing import Any

import pdfplumber


# =============================================================================
# 视觉行基础参数
# =============================================================================

# 把 top 位置接近的 word 粗略聚合为同一水平行。
LINE_Y_TOLERANCE = 3.0

# 同一水平行中，如果两个 word 之间存在明显大间隔，
# 就拆成多个视觉行片段。
#
# 注意：
# 这套视觉行目前主要用于 short_line_ratio 等描述性特征，
# multi_column 已经不再直接依赖视觉行片段判断。
MIN_HORIZONTAL_GAP = 18.0
HORIZONTAL_GAP_PAGE_RATIO = 0.04

# 用于描述页面左右区域。
CENTER_MARGIN_RATIO = 0.04

# “短行”暂时使用几何宽度定义，而不是字符数。
# 这样对中文、英文相对更中性。
SHORT_LINE_WIDTH_RATIO = 0.35


# =============================================================================
# 多栏粗检测参数
# =============================================================================

# 一行中候选“栏间空隙”的最小尺寸。
COLUMN_GAP_MIN = 10.0
COLUMN_GAP_PAGE_RATIO = 0.015

# 栏间空隙应该大致位于页面中央区域。
# 暂时允许 30% ~ 70%，避免把页面边缘空白误认为栏间距。
COLUMN_CENTER_MIN_RATIO = 0.30
COLUMN_CENTER_MAX_RATIO = 0.70

# 太短的行不作为多栏证据。
COLUMN_MIN_ROW_TEXT_CHARS = 6

# 栏间空隙左右两边至少都需要有一定文本。
COLUMN_MIN_SIDE_TEXT_CHARS = 4

# 左右文字区域至少占页面一定宽度，
# 避免几个孤立字段制造假的“双栏”。
COLUMN_MIN_SIDE_WIDTH_RATIO = 0.10

# 第一版仍然保持保守，但不再要求左右栏文字严格同行。
COLUMN_MIN_NATIVE_CHARS = 500

# 至少需要一定数量的实际栏间空隙证据。
COLUMN_MIN_SUPPORT_ROWS = 7

# 因为左右两栏的基线并不一定严格对齐，
# 所以 support ratio 只能作为较弱的辅助条件。
COLUMN_MIN_SUPPORT_RATIO = 0.08

# 少量标题、图片、公式会打断连续双栏区域，
# 因此这里不再要求覆盖超过三分之一页面。
COLUMN_MIN_VERTICAL_SPAN = 0.12

# 真正的双栏 gutter 应该长期稳定在接近同一水平位置。
# ±4% 页面宽度内的证据占比至少达到这个值。
COLUMN_SPLIT_CONSISTENCY_TOLERANCE = 0.04
COLUMN_MIN_SPLIT_CONSISTENCY = 0.65

# 第一版主要识别常见的近似左右双栏。
# 过于偏向页面边缘的稳定空隙更可能是字段、缩进或侧栏。
COLUMN_STABLE_SPLIT_MIN_RATIO = 0.38
COLUMN_STABLE_SPLIT_MAX_RATIO = 0.62

# 表格 / 网格页面通常同时具有较多矢量对象和大量短文本片段。
VECTOR_DENSE_THRESHOLD = 80
VECTOR_FRAGMENTED_SHORT_RATIO = 0.70


# =============================================================================
# 页面主类型粗分类参数
# =============================================================================

# 图片覆盖达到这个比例后，
# 认为图片已经明显主导页面。
PRIMARY_IMAGE_DOMINANT_RATIO = 0.65

# 图片主导页面中，如果 native 字符本身非常少，
# 优先认为是 scan_like。
PRIMARY_SCAN_LOW_NATIVE_CHARS = 80

# 即使 native 字符很多，如果绝大多数都压在大图内部，
# 且图片外几乎没有独立文字，
# 也更像扫描图 + OCR / text layer。
PRIMARY_SCAN_MAX_OUTSIDE_CHARS = 40
PRIMARY_SCAN_HIGH_OVERLAP_RATIO = 0.90

# 图片已经主导页面，但图片外仍存在较多独立 native text，
# 则认为图片和文字都承担主要内容。
PRIMARY_MIXED_MIN_OUTSIDE_CHARS = 80

# 图片不主导时，只要 native text 达到一定规模，
# 就认为主要是 native_text。
PRIMARY_NATIVE_MIN_CHARS = 120

# native text 很少时，
# 即使图片没有达到 65% 的“图片主导”标准，
# 只要图片已经覆盖较明显区域，
# 页面主要信息也很可能来自图片。
PRIMARY_LOW_TEXT_IMAGE_MIN_RATIO = 0.20
# 图片虽然没有达到“主导页面”的 65%，
# 但已经占据明显区域，同时图片外仍有较多独立文字，
# 则页面应视为图文混合。
PRIMARY_MIXED_MIN_IMAGE_RATIO = 0.30

# 矢量页面：
# native text 很少、raster image 不主导，
# 但存在大量 vector objects。
PRIMARY_VECTOR_MAX_NATIVE_CHARS = 80
PRIMARY_VECTOR_MAX_IMAGE_RATIO = 0.30
PRIMARY_VECTOR_MIN_OBJECTS = 500
def round_number(
    value: float,
    digits: int = 4,
) -> float:
    return round(
        float(value),
        digits,
    )


def group_words_into_rows(
    words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """
    根据 word bbox 的 top 坐标，
    把 word 粗略聚合为水平文本行。
    """
    valid_words = [
        word
        for word in words
        if all(
            isinstance(
                word.get(key),
                (int, float),
            )
            for key in (
                "x0",
                "x1",
                "top",
                "bottom",
            )
        )
    ]

    if not valid_words:
        return []

    sorted_words = sorted(
        valid_words,
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
            <= LINE_Y_TOLERANCE
        ):
            current_row.append(
                word
            )
        else:
            rows.append(
                [word]
            )

    return rows


def extract_visual_lines(
    words: list[dict[str, Any]],
    page_width: float,
) -> list[dict[str, Any]]:
    """
    根据 word bbox 构造粗略视觉行。

    两步：

    1. 按 top 坐标把 word 聚成水平 row。
    2. row 内如果出现较大的水平间隔，
       则拆成多个 line segment。

    注意：
    这里主要用于 short_line_ratio
    等页面描述特征。

    multi_column 使用独立的“栏间空隙”逻辑判断，
    不再直接依赖这里拆出的视觉行。
    """
    rows = group_words_into_rows(
        words
    )

    if not rows:
        return []

    visual_lines: list[
        dict[str, Any]
    ] = []

    split_gap = max(
        MIN_HORIZONTAL_GAP,
        page_width
        * HORIZONTAL_GAP_PAGE_RATIO,
    )

    for row in rows:
        row = sorted(
            row,
            key=lambda word: float(
                word["x0"]
            ),
        )

        segments: list[
            list[dict[str, Any]]
        ] = []

        current_segment: list[
            dict[str, Any]
        ] = []

        for word in row:
            if not current_segment:
                current_segment.append(
                    word
                )
                continue

            previous = (
                current_segment[-1]
            )

            gap = (
                float(word["x0"])
                - float(
                    previous["x1"]
                )
            )

            if gap > split_gap:
                segments.append(
                    current_segment
                )

                current_segment = [
                    word
                ]

            else:
                current_segment.append(
                    word
                )

        if current_segment:
            segments.append(
                current_segment
            )

        for segment in segments:
            x0 = min(
                float(word["x0"])
                for word in segment
            )

            x1 = max(
                float(word["x1"])
                for word in segment
            )

            top = min(
                float(word["top"])
                for word in segment
            )

            bottom = max(
                float(word["bottom"])
                for word in segment
            )

            text = " ".join(
                str(
                    word.get(
                        "text",
                        "",
                    )
                ).strip()
                for word in segment
                if str(
                    word.get(
                        "text",
                        "",
                    )
                ).strip()
            )

            visual_lines.append(
                {
                    "x0": x0,
                    "x1": x1,
                    "top": top,
                    "bottom": bottom,
                    "width": max(
                        0.0,
                        x1 - x0,
                    ),
                    "text": text,
                }
            )

    return visual_lines


def get_clipped_image_rects(
    images: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> list[
    tuple[
        float,
        float,
        float,
        float,
    ]
]:
    """
    获取图片 bbox，并裁剪到页面有效范围。
    """
    image_rects: list[
        tuple[
            float,
            float,
            float,
            float,
        ]
    ] = []

    for image in images:
        try:
            x0 = max(
                0.0,
                float(
                    image["x0"]
                ),
            )

            x1 = min(
                page_width,
                float(
                    image["x1"]
                ),
            )

            top = max(
                0.0,
                float(
                    image["top"]
                ),
            )

            bottom = min(
                page_height,
                float(
                    image["bottom"]
                ),
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        if (
            x1 <= x0
            or bottom <= top
        ):
            continue

        image_rects.append(
            (
                x0,
                x1,
                top,
                bottom,
            )
        )

    return image_rects


def calculate_rectangle_union_area(
    rects: list[
        tuple[
            float,
            float,
            float,
            float,
        ]
    ],
) -> float:
    """
    计算多个轴对齐矩形 bbox 的并集面积。

    相比直接把所有图片面积相加，
    这样不会因为图片 bbox 互相重叠
    而重复计算覆盖率。

    对普通 PDF 页面来说 image object 数量通常不大，
    所以这一版实现仍然非常便宜。
    """
    if not rects:
        return 0.0

    x_points = sorted(
        {
            x
            for x0, x1, _, _ in rects
            for x in (
                x0,
                x1,
            )
        }
    )

    total_area = 0.0

    for left_x, right_x in zip(
        x_points,
        x_points[1:],
    ):
        if right_x <= left_x:
            continue

        middle_x = (
            left_x
            + right_x
        ) / 2

        y_intervals = [
            (
                top,
                bottom,
            )
            for (
                x0,
                x1,
                top,
                bottom,
            ) in rects
            if (
                x0
                < middle_x
                < x1
            )
        ]

        if not y_intervals:
            continue

        y_intervals.sort()

        (
            current_top,
            current_bottom,
        ) = y_intervals[0]

        merged_height = 0.0

        for (
            top,
            bottom,
        ) in y_intervals[1:]:

            if (
                top
                <= current_bottom
            ):
                current_bottom = max(
                    current_bottom,
                    bottom,
                )

            else:
                merged_height += (
                    current_bottom
                    - current_top
                )

                current_top = top
                current_bottom = bottom

        merged_height += (
            current_bottom
            - current_top
        )

        total_area += (
            right_x
            - left_x
        ) * merged_height

    return total_area


def calculate_image_features(
    images: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> dict[str, float]:
    """
    提取图片覆盖特征。

    image_ratio:
        所有图片 bbox 的并集面积 / 页面面积。

    largest_image_ratio:
        页面中最大单张图片 bbox 面积 / 页面面积。

    两者必须分开：

    - image_count 很大但 largest_image_ratio 很小，
      可能只是大量小图标。

    - image_count 只有 1，
      但 largest_image_ratio 接近 1，
      则可能是一张整页扫描图。
    """
    page_area = (
        page_width
        * page_height
    )

    if page_area <= 0:
        return {
            "image_ratio": 0.0,
            "largest_image_ratio": 0.0,
        }

    image_rects = (
        get_clipped_image_rects(
            images=images,
            page_width=page_width,
            page_height=page_height,
        )
    )

    if not image_rects:
        return {
            "image_ratio": 0.0,
            "largest_image_ratio": 0.0,
        }

    union_area = (
        calculate_rectangle_union_area(
            image_rects
        )
    )

    largest_area = max(
        (
            x1 - x0
        )
        * (
            bottom - top
        )
        for (
            x0,
            x1,
            top,
            bottom,
        ) in image_rects
    )

    return {
        "image_ratio":
            round_number(
                union_area
                / page_area
            ),

        "largest_image_ratio":
            round_number(
                largest_area
                / page_area
            ),
    }


def calculate_text_image_overlap_features(
    chars: list[dict[str, Any]],
    images: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    """
    计算 native text 与图片区域的空间重叠关系。

    char_in_image_ratio:
        字符 bbox 中心点落入任意图片 bbox 的字符比例。

    native_char_count_outside_images:
        字符 bbox 中心点不在任何图片 bbox 内的字符数量。

    这里使用字符中心点而不是 bbox 面积相交：
    计算非常便宜，同时不容易因为字符 bbox
    仅仅擦到图片边缘就被判为位于图片内部。

    注意：
    这些都只是 Page Profiler 的客观几何特征，
    不能直接等同于扫描页或解析质量结论。
    """
    native_char_count = len(
        chars
    )

    if native_char_count == 0:
        return {
            "char_in_image_ratio": 0.0,
            "native_char_count_outside_images": 0,
        }

    image_rects = (
        get_clipped_image_rects(
            images=images,
            page_width=page_width,
            page_height=page_height,
        )
    )

    if not image_rects:
        return {
            "char_in_image_ratio": 0.0,
            "native_char_count_outside_images":
                native_char_count,
        }

    char_in_image_count = 0

    for char in chars:
        try:
            char_x0 = float(
                char["x0"]
            )

            char_x1 = float(
                char["x1"]
            )

            char_top = float(
                char["top"]
            )

            char_bottom = float(
                char["bottom"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        center_x = (
            char_x0
            + char_x1
        ) / 2

        center_y = (
            char_top
            + char_bottom
        ) / 2

        is_inside_image = any(
            (
                x0
                <= center_x
                <= x1
            )
            and (
                top
                <= center_y
                <= bottom
            )
            for (
                x0,
                x1,
                top,
                bottom,
            ) in image_rects
        )

        if is_inside_image:
            char_in_image_count += 1

    native_char_count_outside_images = (
        native_char_count
        - char_in_image_count
    )

    return {
        "char_in_image_ratio":
            round_number(
                char_in_image_count
                / native_char_count
            ),

        "native_char_count_outside_images":
            native_char_count_outside_images,
    }


def calculate_line_features(
    visual_lines: list[dict[str, Any]],
    page_width: float,
) -> dict[str, Any]:
    """
    计算页面文本行的基础几何描述特征。

    注意：
    left/right/cross 当前只是原始描述特征，
    不再直接决定 multi_column。
    """
    if (
        not visual_lines
        or page_width <= 0
    ):
        return {
            "text_line_count": 0,
            "avg_line_length": 0.0,
            "short_line_ratio": 0.0,
            "left_line_ratio": 0.0,
            "right_line_ratio": 0.0,
            "cross_center_ratio": 0.0,
        }

    line_count = len(
        visual_lines
    )

    line_lengths = [
        len(
            line["text"]
        )
        for line in visual_lines
        if line["text"]
    ]

    avg_line_length = (
        mean(
            line_lengths
        )
        if line_lengths
        else 0.0
    )

    short_line_count = sum(
        1
        for line in visual_lines
        if (
            line["width"]
            / page_width
            <= SHORT_LINE_WIDTH_RATIO
        )
    )

    center_x = (
        page_width
        / 2
    )

    center_margin = (
        page_width
        * CENTER_MARGIN_RATIO
    )

    left_count = 0
    right_count = 0
    cross_center_count = 0

    for line in visual_lines:
        x0 = float(
            line["x0"]
        )

        x1 = float(
            line["x1"]
        )

        if (
            x1
            <= center_x
            - center_margin
        ):
            left_count += 1

        if (
            x0
            >= center_x
            + center_margin
        ):
            right_count += 1

        if (
            x0 < center_x
            and x1 > center_x
        ):
            cross_center_count += 1

    return {
        "text_line_count":
            line_count,

        "avg_line_length":
            round_number(
                avg_line_length
            ),

        "short_line_ratio":
            round_number(
                short_line_count
                / line_count
            ),

        "left_line_ratio":
            round_number(
                left_count
                / line_count
            ),

        "right_line_ratio":
            round_number(
                right_count
                / line_count
            ),

        "cross_center_ratio":
            round_number(
                cross_center_count
                / line_count
            ),
    }


def calculate_column_features(
    words: list[dict[str, Any]],
    page_width: float,
    page_height: float,
    native_char_count: int,
    vector_object_count: int,
    short_line_ratio: float,
) -> dict[str, Any]:
    """
    使用“稳定栏间空隙”
    粗略判断 native text 多栏页面。

    真正的双栏正文通常同时具有：

    1. 页面左右持续存在文本；
    2. 左右区域之间存在明显水平空隙；
    3. 栏间空隙的位置长期比较稳定；
    4. 这种结构覆盖一定纵向范围。

    表格、字段页和普通正文也可能偶然出现
    较大的水平空隙，
    所以这里重点增加 split_x 的稳定性判断。
    """
    if (
        page_width <= 0
        or page_height <= 0
    ):
        return {
            "column_split_support_rows": 0,
            "column_split_support_ratio": 0.0,
            "column_split_vertical_span": 0.0,
            "column_split_x_ratio": 0.0,
            "column_split_consistency_ratio": 0.0,
            "multi_column_candidate": False,
            "multi_column": False,
        }

    rows = group_words_into_rows(
        words
    )

    gap_threshold = max(
        COLUMN_GAP_MIN,
        page_width
        * COLUMN_GAP_PAGE_RATIO,
    )

    eligible_row_count = 0

    support_rows: list[
        dict[str, float]
    ] = []

    for row in rows:
        row = sorted(
            row,
            key=lambda word: float(
                word["x0"]
            ),
        )

        row_text = "".join(
            str(
                word.get(
                    "text",
                    "",
                )
            ).strip()
            for word in row
        )

        if (
            len(
                row_text
            )
            < COLUMN_MIN_ROW_TEXT_CHARS
        ):
            continue

        eligible_row_count += 1

        best_gap: (
            tuple[
                float,
                float,
            ]
            | None
        ) = None

        for (
            left_word,
            right_word,
        ) in zip(
            row,
            row[1:],
        ):
            gap = (
                float(
                    right_word["x0"]
                )
                - float(
                    left_word["x1"]
                )
            )

            split_x = (
                float(
                    left_word["x1"]
                )
                + float(
                    right_word["x0"]
                )
            ) / 2

            split_ratio = (
                split_x
                / page_width
            )

            if not (
                COLUMN_CENTER_MIN_RATIO
                <= split_ratio
                <= COLUMN_CENTER_MAX_RATIO
            ):
                continue

            if (
                best_gap is None
                or gap
                > best_gap[0]
            ):
                best_gap = (
                    gap,
                    split_x,
                )

        if best_gap is None:
            continue

        gap, split_x = (
            best_gap
        )

        if gap < gap_threshold:
            continue

        left_words = [
            word
            for word in row
            if float(
                word["x1"]
            ) <= split_x
        ]

        right_words = [
            word
            for word in row
            if float(
                word["x0"]
            ) >= split_x
        ]

        if (
            not left_words
            or not right_words
        ):
            continue

        left_text = "".join(
            str(
                word.get(
                    "text",
                    "",
                )
            ).strip()
            for word in left_words
        )

        right_text = "".join(
            str(
                word.get(
                    "text",
                    "",
                )
            ).strip()
            for word in right_words
        )

        if (
            len(
                left_text
            )
            < COLUMN_MIN_SIDE_TEXT_CHARS
            or len(
                right_text
            )
            < COLUMN_MIN_SIDE_TEXT_CHARS
        ):
            continue

        left_width = (
            max(
                float(
                    word["x1"]
                )
                for word in left_words
            )
            -
            min(
                float(
                    word["x0"]
                )
                for word in left_words
            )
        )

        right_width = (
            max(
                float(
                    word["x1"]
                )
                for word in right_words
            )
            -
            min(
                float(
                    word["x0"]
                )
                for word in right_words
            )
        )

        if (
            left_width
            < page_width
            * COLUMN_MIN_SIDE_WIDTH_RATIO
            or
            right_width
            < page_width
            * COLUMN_MIN_SIDE_WIDTH_RATIO
        ):
            continue

        support_rows.append(
            {
                "top":
                    min(
                        float(
                            word["top"]
                        )
                        for word in row
                    ),

                "bottom":
                    max(
                        float(
                            word["bottom"]
                        )
                        for word in row
                    ),

                "split_x":
                    split_x,
            }
        )

    support_count = len(
        support_rows
    )

    if eligible_row_count > 0:
        support_ratio = (
            support_count
            / eligible_row_count
        )
    else:
        support_ratio = 0.0

    if support_count >= 2:
        vertical_span = (
            max(
                row["bottom"]
                for row in support_rows
            )
            -
            min(
                row["top"]
                for row in support_rows
            )
        ) / page_height
    else:
        vertical_span = 0.0

    if support_rows:
        split_ratios = [
            row["split_x"]
            / page_width
            for row in support_rows
        ]

        split_x_ratio = median(
            split_ratios
        )

        consistent_split_count = sum(
            1
            for split_ratio in split_ratios
            if (
                abs(
                    split_ratio
                    - split_x_ratio
                )
                <= COLUMN_SPLIT_CONSISTENCY_TOLERANCE
            )
        )

        split_consistency_ratio = (
            consistent_split_count
            / support_count
        )

    else:
        split_x_ratio = 0.0
        split_consistency_ratio = 0.0

    multi_column_candidate = (
        native_char_count
        >= COLUMN_MIN_NATIVE_CHARS

        and support_count
        >= COLUMN_MIN_SUPPORT_ROWS

        and support_ratio
        >= COLUMN_MIN_SUPPORT_RATIO

        and vertical_span
        >= COLUMN_MIN_VERTICAL_SPAN

        and split_consistency_ratio
        >= COLUMN_MIN_SPLIT_CONSISTENCY

        and COLUMN_STABLE_SPLIT_MIN_RATIO
        <= split_x_ratio
        <= COLUMN_STABLE_SPLIT_MAX_RATIO
    )

    # 大量矢量对象 + 大量短文本片段，
    # 很容易是表格、表单或网格结构。
    #
    # 当前并不把页面直接判断为 table_like，
    # 这里只避免它污染 multi_column。
    vector_fragment_mimic = (
        vector_object_count
        >= VECTOR_DENSE_THRESHOLD

        and short_line_ratio
        >= VECTOR_FRAGMENTED_SHORT_RATIO
    )

    multi_column = (
        multi_column_candidate
        and not vector_fragment_mimic
    )

    return {
        "column_split_support_rows":
            support_count,

        "column_split_support_ratio":
            round_number(
                support_ratio
            ),

        "column_split_vertical_span":
            round_number(
                vertical_span
            ),

        "column_split_x_ratio":
            round_number(
                split_x_ratio
            ),

        "column_split_consistency_ratio":
            round_number(
                split_consistency_ratio
            ),

        "multi_column_candidate":
            multi_column_candidate,

        "multi_column":
            multi_column,
    }

def classify_primary_type(
    native_char_count: int,
    image_ratio: float,
    char_in_image_ratio: float,
    native_char_count_outside_images: int,
    vector_object_count: int,
) -> str:
    """
    根据低成本页面特征判断页面主要内容载体。

    返回：
        native_text
        scan_like
        mixed_image_text
        vector_graphics
        sparse

    primary_type 只描述页面主要形态，
    不等同于解析质量判断。
    """

    # -------------------------------------------------------------------------
    # 1. 矢量图形页面
    # -------------------------------------------------------------------------

    vector_graphics_like = (
        native_char_count
        <= PRIMARY_VECTOR_MAX_NATIVE_CHARS

        and image_ratio
        < PRIMARY_VECTOR_MAX_IMAGE_RATIO

        and vector_object_count
        >= PRIMARY_VECTOR_MIN_OBJECTS
    )

    if vector_graphics_like:
        return "vector_graphics"

    # -------------------------------------------------------------------------
    # 2. 图片明显主导页面
    # -------------------------------------------------------------------------

    image_dominant = (
        image_ratio
        >= PRIMARY_IMAGE_DOMINANT_RATIO
    )

    if image_dominant:
        low_native_text = (
            native_char_count
            <= PRIMARY_SCAN_LOW_NATIVE_CHARS
        )

        text_mostly_inside_image = (
            char_in_image_ratio
            >= PRIMARY_SCAN_HIGH_OVERLAP_RATIO

            and
            native_char_count_outside_images
            <= PRIMARY_SCAN_MAX_OUTSIDE_CHARS
        )

        if (
            low_native_text
            or text_mostly_inside_image
        ):
            return "scan_like"

        if (
            native_char_count_outside_images
            >= PRIMARY_MIXED_MIN_OUTSIDE_CHARS
        ):
            return "mixed_image_text"

        return "scan_like"

    # -------------------------------------------------------------------------
    # 3. native text 极少，但页面已经存在较明显图片内容
    # -------------------------------------------------------------------------

    low_text_image_page = (
            native_char_count
            <= PRIMARY_SCAN_LOW_NATIVE_CHARS

            and image_ratio
            >= PRIMARY_LOW_TEXT_IMAGE_MIN_RATIO
    )

    if low_text_image_page:
        return "scan_like"

    # -------------------------------------------------------------------------
    # 4. 中等以上图片覆盖 + 图片外存在独立 native text
    # -------------------------------------------------------------------------

    mixed_image_text = (
            image_ratio
            >= PRIMARY_MIXED_MIN_IMAGE_RATIO

            and native_char_count_outside_images
            >= PRIMARY_MIXED_MIN_OUTSIDE_CHARS
    )

    if mixed_image_text:
        return "mixed_image_text"

    # -------------------------------------------------------------------------
    # 5. 原生文本页面
    # -------------------------------------------------------------------------
    if (
        native_char_count
        >= PRIMARY_NATIVE_MIN_CHARS
    ):
        return "native_text"

    # -------------------------------------------------------------------------
    # 6. 真正稀疏页面
    # -------------------------------------------------------------------------

    return "sparse"


# =============================================================================
# Single-Pass Page Snapshot
# =============================================================================

PAGE_SCAN_VERSION = "0.1.0"
PROFILE_SCHEMA_VERSION = "1.1"
SNAPSHOT_SCHEMA_VERSION = "1.0"
PROFILER_VERSION = "0.3.2"

# 表格候选不是 Page Profiler 分类算法的一部分。
# 这里只决定在单次 page loop 中，是否顺手运行 pdfplumber TableFinder。
TABLE_AUTO_MIN_VECTOR_OBJECTS = 4


def to_json_safe(
    value: Any,
) -> Any:
    """
    把 pdfplumber / pdfminer 对象转换为 JSON 安全值。
    """
    if value is None:
        return None

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            to_json_safe(
                item
            )
            for item in value
        ]

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key):
                to_json_safe(
                    item
                )
            for (
                key,
                item,
            ) in value.items()
        }

    return str(
        value
    )


def pick_fields(
    source: dict[str, Any],
    fields: list[str],
) -> dict[str, Any]:
    """
    只保存后续结构恢复真正可能需要的底层字段，
    不直接序列化 pdfplumber 内部对象。
    """
    return {
        field:
            to_json_safe(
                source[
                    field
                ]
            )
        for field in fields
        if field in source
    }


def bbox_to_dict(
    bbox: Any,
) -> dict[str, float] | None:
    """
    将 (x0, top, x1, bottom) 转成统一 bbox。
    """
    if not isinstance(
        bbox,
        (
            list,
            tuple,
        ),
    ):
        return None

    if len(
        bbox
    ) != 4:
        return None

    try:
        return {
            "x0":
                float(
                    bbox[0]
                ),

            "top":
                float(
                    bbox[1]
                ),

            "x1":
                float(
                    bbox[2]
                ),

            "bottom":
                float(
                    bbox[3]
                ),
        }

    except (
        TypeError,
        ValueError,
    ):
        return None


def extract_table_rows(
    table: Any,
) -> list[dict[str, Any]]:
    """
    保存 TableFinder 当前给出的 row/cell 几何。

    不做 rowspan / colspan 修复。
    """
    rows: list[
        dict[str, Any]
    ] = []

    for row_index, row in enumerate(
        getattr(
            table,
            "rows",
            [],
        )
    ):
        rows.append(
            {
                "row_index":
                    row_index,

                "cells":
                    [
                        bbox_to_dict(
                            cell
                        )
                        for cell
                        in getattr(
                            row,
                            "cells",
                            [],
                        )
                    ],
            }
        )

    return rows


def extract_table_candidates(
    page: pdfplumber.page.Page,
) -> list[dict[str, Any]]:
    """
    保存 pdfplumber 当前默认 TableFinder 候选。

    这里只保存候选和原始 cell 几何，
    不把它视为最终表格结构。
    """
    result: list[
        dict[str, Any]
    ] = []

    for table_index, table in enumerate(
        page.find_tables()
    ):
        cells = [
            bbox_to_dict(
                cell
            )
            for cell
            in getattr(
                table,
                "cells",
                [],
            )
        ]

        try:
            extracted_data = (
                table.extract()
            )

        except Exception as exc:
            extracted_data = None
            extract_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

        else:
            extract_error = None

        result.append(
            {
                "table_index":
                    table_index,

                "bbox":
                    bbox_to_dict(
                        getattr(
                            table,
                            "bbox",
                            None,
                        )
                    ),

                "cell_count":
                    len(
                        cells
                    ),

                "cells":
                    cells,

                "rows":
                    extract_table_rows(
                        table
                    ),

                "extracted_data":
                    to_json_safe(
                        extracted_data
                    ),

                "extract_error":
                    extract_error,
            }
        )

    return result


def capture_page_evidence(
    page: pdfplumber.page.Page,
    table_mode: str,
) -> dict[str, Any]:
    """
    在同一个 pdfplumber Page 上一次性收集后续可复用证据。

    这里是整个 pdffast 的基础扫描层。

    Stage 2 / Stage 3 / Stage 4 不应该重新打开 PDF。
    """
    page_width = float(
        page.width
    )

    page_height = float(
        page.height
    )

    native_text = (
        page.extract_text()
        or ""
    )

    raw_words = (
        page.extract_words()
    )

    chars = [
        pick_fields(
            char,
            [
                "text",
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "width",
                "height",
                "fontname",
                "size",
                "upright",
                "adv",
                "matrix",
                "stroking_color",
                "non_stroking_color",
            ],
        )
        for char in page.chars
    ]

    words = [
        pick_fields(
            word,
            [
                "text",
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "direction",
            ],
        )
        for word in raw_words
    ]

    images = [
        pick_fields(
            image,
            [
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "width",
                "height",
                "srcsize",
                "bits",
                "colorspace",
                "imagemask",
                "name",
            ],
        )
        for image in page.images
    ]

    lines = [
        pick_fields(
            line,
            [
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "width",
                "height",
                "linewidth",
                "stroking_color",
                "non_stroking_color",
            ],
        )
        for line in page.lines
    ]

    rects = [
        pick_fields(
            rect,
            [
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "width",
                "height",
                "linewidth",
                "fill",
                "stroke",
                "stroking_color",
                "non_stroking_color",
            ],
        )
        for rect in page.rects
    ]

    curves = [
        pick_fields(
            curve,
            [
                "x0",
                "x1",
                "top",
                "bottom",
                "doctop",
                "width",
                "height",
                "linewidth",
                "fill",
                "stroke",
                "stroking_color",
                "non_stroking_color",
                "pts",
                "path",
            ],
        )
        for curve in page.curves
    ]

    vector_object_count = (
        len(
            lines
        )
        +
        len(
            rects
        )
        +
        len(
            curves
        )
    )

    should_run_tables = (
        table_mode
        == "all"

        or (
            table_mode
            == "auto"

            and vector_object_count
            >= TABLE_AUTO_MIN_VECTOR_OBJECTS
        )
    )

    table_candidates: list[
        dict[str, Any]
    ] = []

    table_status = (
        "skipped"
    )

    table_error = None

    if should_run_tables:
        try:
            table_candidates = (
                extract_table_candidates(
                    page
                )
            )

            table_status = (
                "completed"
            )

        except Exception as exc:
            table_status = (
                "error"
            )

            table_error = (
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    return {
        "record_type":
            "page",

        "page_number":
            int(
                page.page_number
            ),

        "width":
            page_width,

        "height":
            page_height,

        "rotation":
            int(
                getattr(
                    page,
                    "rotation",
                    0,
                )
                or 0
            ),

        "native_text":
            native_text,

        "chars":
            chars,

        "words":
            words,

        "images":
            images,

        "lines":
            lines,

        "rects":
            rects,

        "curves":
            curves,

        "table_candidates":
            table_candidates,

        "table_detection":
            {
                "mode":
                    table_mode,

                "status":
                    table_status,

                "error":
                    table_error,
            },
    }


def profile_page_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """
    使用已经收集好的 evidence 计算 Page Profiler v0.3.2。

    分类算法和此前冻结版保持一致；
    变化只是“不再重新访问 PDF Page”。
    """
    page_width = float(
        evidence[
            "width"
        ]
    )

    page_height = float(
        evidence[
            "height"
        ]
    )

    chars = evidence[
        "chars"
    ]

    words = evidence[
        "words"
    ]

    images = evidence[
        "images"
    ]

    lines = evidence[
        "lines"
    ]

    rects = evidence[
        "rects"
    ]

    curves = evidence[
        "curves"
    ]

    text = str(
        evidence.get(
            "native_text",
            "",
        )
    )

    native_char_count = len(
        chars
    )

    vector_object_count = (
        len(
            lines
        )
        +
        len(
            rects
        )
        +
        len(
            curves
        )
    )

    visual_lines = (
        extract_visual_lines(
            words=words,
            page_width=page_width,
        )
    )

    image_features = (
        calculate_image_features(
            images=images,
            page_width=page_width,
            page_height=page_height,
        )
    )

    text_image_overlap_features = (
        calculate_text_image_overlap_features(
            chars=chars,
            images=images,
            page_width=page_width,
            page_height=page_height,
        )
    )

    line_features = (
        calculate_line_features(
            visual_lines=visual_lines,
            page_width=page_width,
        )
    )

    column_features = (
        calculate_column_features(
            words=words,
            page_width=page_width,
            page_height=page_height,
            native_char_count=
                native_char_count,
            vector_object_count=
                vector_object_count,
            short_line_ratio=float(
                line_features[
                    "short_line_ratio"
                ]
            ),
        )
    )

    primary_type = (
        classify_primary_type(
            native_char_count=
                native_char_count,

            image_ratio=float(
                image_features[
                    "image_ratio"
                ]
            ),

            char_in_image_ratio=float(
                text_image_overlap_features[
                    "char_in_image_ratio"
                ]
            ),

            native_char_count_outside_images=int(
                text_image_overlap_features[
                    "native_char_count_outside_images"
                ]
            ),

            vector_object_count=
                vector_object_count,
        )
    )

    return {
        "page_number":
            int(
                evidence[
                    "page_number"
                ]
            ),

        "width":
            round_number(
                page_width,
                2,
            ),

        "height":
            round_number(
                page_height,
                2,
            ),

        # Stage 2 直接复用，不再重新打开 PDF。
        "native_text":
            text,

        "native_char_count":
            native_char_count,

        "primary_type":
            primary_type,

        "text_length":
            len(
                text.strip()
            ),

        "word_count":
            len(
                words
            ),

        "image_count":
            len(
                images
            ),

        **image_features,

        **text_image_overlap_features,

        "line_object_count":
            len(
                lines
            ),

        "rect_object_count":
            len(
                rects
            ),

        "curve_object_count":
            len(
                curves
            ),

        "vector_object_count":
            vector_object_count,

        **line_features,

        **column_features,

        # 仅作为后续路由提示，不参与 v0.3.2 primary_type。
        "table_candidate_count":
            len(
                evidence.get(
                    "table_candidates",
                    [],
                )
            ),

        "table_detection_status":
            evidence.get(
                "table_detection",
                {},
            ).get(
                "status",
                "unknown",
            ),
    }


def scan_and_profile_pdf(
    pdf_path: Path,
    snapshot_output: Path,
    table_mode: str,
) -> dict[str, Any]:
    """
    单次打开 PDF、单次 page loop：

    1. 保存 Raw Evidence JSONL
    2. 同时计算 Page Profile

    后续阶段只读这些产物，不再重复解析 PDF。
    """
    pages: list[
        dict[str, Any]
    ] = []

    snapshot_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with pdfplumber.open(
        pdf_path
    ) as pdf, snapshot_output.open(
        "w",
        encoding="utf-8",
    ) as snapshot_file:

        page_count = len(
            pdf.pages
        )

        meta = {
            "record_type":
                "meta",

            "snapshot_schema_version":
                SNAPSHOT_SCHEMA_VERSION,

            "page_scan_version":
                PAGE_SCAN_VERSION,

            "profiler_version":
                PROFILER_VERSION,

            "source_file":
                pdf_path.name,

            "page_count":
                page_count,

            "parser":
                {
                    "name":
                        "pdfplumber",

                    "version":
                        getattr(
                            pdfplumber,
                            "__version__",
                            "unknown",
                        ),
                },

            "table_mode":
                table_mode,

            "coordinate_system":
                {
                    "x_origin":
                        "left",

                    "y_origin":
                        "top",

                    "bbox_order":
                        [
                            "x0",
                            "top",
                            "x1",
                            "bottom",
                        ],

                    "unit":
                        "PDF point",
                },
        }

        snapshot_file.write(
            json.dumps(
                meta,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
            + "\n"
        )

        for page in pdf.pages:
            evidence = (
                capture_page_evidence(
                    page=
                        page,

                    table_mode=
                        table_mode,
                )
            )

            profile = (
                profile_page_evidence(
                    evidence
                )
            )

            pages.append(
                profile
            )

            snapshot_file.write(
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                )
                + "\n"
            )

    return {
        "page_scan_version":
            PAGE_SCAN_VERSION,

        "profiler_version":
            PROFILER_VERSION,

        "profile_schema_version":
            PROFILE_SCHEMA_VERSION,

        "source_file":
            pdf_path.name,

        "page_count":
            len(
                pages
            ),

        "snapshot_file":
            str(
                snapshot_output
            ),

        "table_mode":
            table_mode,

        "pages":
            pages,
    }


def text_display_width(
    text: str,
) -> int:
    """
    计算终端中的实际显示宽度。

    中文等全角字符按 2 个字符宽度计算，
    解决中文表头和数字列错位的问题。
    """
    return sum(
        2
        if (
            unicodedata.east_asian_width(
                char
            )
            in {
                "W",
                "F",
            }
        )
        else 1
        for char in text
    )


def align_right(
    value: Any,
    width: int,
) -> str:
    """
    按终端实际显示宽度右对齐。
    """
    text = str(
        value
    )

    padding = max(
        0,
        width
        - text_display_width(
            text
        ),
    )

    return (
        " " * padding
        + text
    )


def print_summary(
    result: dict[str, Any],
) -> None:
    columns = [
        ("页码", 4),
        ("字符数", 7),
        ("词数", 7),
        ("图片数", 7),
        ("图片占比", 9),
        ("最大图占比", 11),

        # v0.2.2 新增
        ("图内字占比", 11),
        ("图外字符", 9),

        ("矢量数", 8),
        ("文本行", 7),
        ("短行占比", 9),
        ("左侧占比", 9),
        ("右侧占比", 9),
        ("跨中线", 7),
        ("栏证据", 8),
        ("栏占比", 8),
        ("纵跨度", 8),
        ("多栏", 7),

        # v0.3.0 新增
        ("页面类型", 10),
    ]

    table_width = (
        sum(
            width
            for _, width
            in columns
        )
        + len(columns)
        - 1
    )

    print()

    print(
        "=" * table_width
    )

    print(
        f"页面分析器 | "
        f"{result['source_file']} "
        f"| 页数="
        f"{result['page_count']} "
        f"| 版本="
        f"{result['profiler_version']}"
    )

    print(
        "=" * table_width
    )

    header = " ".join(
        align_right(
            title,
            width,
        )
        for (
            title,
            width,
        ) in columns
    )

    print(
        header
    )

    print(
        "-" * table_width
    )

    primary_type_names = {
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

    for page in result["pages"]:
        primary_type_display = (
            primary_type_names.get(
                page["primary_type"],
                page["primary_type"],
            )
        )

        values = [
            page[
                "page_number"
            ],

            page[
                "native_char_count"
            ],

            page[
                "word_count"
            ],

            page[
                "image_count"
            ],

            f"{page['image_ratio']:.3f}",

            f"{page['largest_image_ratio']:.3f}",

            f"{page['char_in_image_ratio']:.3f}",

            page[
                "native_char_count_outside_images"
            ],

            page[
                "vector_object_count"
            ],

            page[
                "text_line_count"
            ],

            f"{page['short_line_ratio']:.3f}",

            f"{page['left_line_ratio']:.3f}",

            f"{page['right_line_ratio']:.3f}",

            f"{page['cross_center_ratio']:.3f}",

            page[
                "column_split_support_rows"
            ],

            f"{page['column_split_support_ratio']:.3f}",

            f"{page['column_split_vertical_span']:.3f}",

            (
                "是"
                if page[
                    "multi_column"
                ]
                else "否"
            ),

            primary_type_display,
        ]

        print(
            " ".join(
                align_right(
                    value,
                    width,
                )
                for (
                    value,
                    (_, width),
                ) in zip(
                    values,
                    columns,
                )
            )
        )

    print(
        "=" * table_width
    )


def run_profiler(
    *,
    pdf_path: Path,
    profile_output: Path,
    snapshot_output: Path,
    table_mode: str = "auto",
) -> dict[str, Any]:
    """Create the production Page Profile and Raw Evidence Snapshot artifacts."""

    pdf_path = Path(pdf_path)
    profile_output = Path(profile_output)
    snapshot_output = Path(snapshot_output)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"输入文件不是 PDF: {pdf_path}")
    if table_mode not in {"off", "auto", "all"}:
        raise ValueError(f"未知 table_mode: {table_mode}")

    result = scan_and_profile_pdf(
        pdf_path=pdf_path,
        snapshot_output=snapshot_output,
        table_mode=table_mode,
    )
    profile_output.parent.mkdir(parents=True, exist_ok=True)
    profile_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result

