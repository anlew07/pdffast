#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stage 6 — Text Flow & Noise Normalization
Pipeline v0.6.15

这是 Stage6 在人工 readable audit 后的第二轮 regression-fix candidate；不针对具体 case/page/string 写补丁。

当前实现：
- Stage 6.1 Noise Candidate Detection（算法基线 0.1.2，SEALED）
- Stage 6.2 Reading Order Recovery（native baseline 0.2.9）
- Stage 6.3 Line → Paragraph Reconstruction（算法 0.3.16，REGRESSION CANDIDATE）
- Stage 6.4 Cross-page Ordinary Paragraph Continuation（算法 0.1.2，SEALED）
- Stage 6.5 Broken Word / Character Repair（SKIPPED BY DESIGN）
- Stage 6.6 Final Native Flow Materialization（算法 0.3.6）

Stage6.5 不实现字符级修复：
- 保留机械换行 / 分页断裂；
- 不猜词、不补字、不自动改专业术语、人名、缩写或公式。

统一原则：
1. Stage1 / Stage4 原始证据不可变。
2. Stage6.1 只识别噪声证据。
3. Stage6.2 只解决普通页 / 常见多栏页的 reading order；
   mixed / complex layout 保持 partial，交给后续 Quality Gate → fallback。
4. Stage6.3 先确定 logical text authority：
   - native text：Stage1 words；
   - data_table：保留 table flow unit；
   - layout_container：Stage1 table extracted_data。
5. layout_container 内 raw words 只能提供缩进 / 行距等弱段落边界证据，
   不允许重新改变 extracted_data 的文本顺序。
6. 同一区域 native text 的去重必须发生在“paragraph 已经重建之后”，
   不能在 Stage4 text-unit 粒度提前整块删除；仍要求“几何覆盖 + 文本高匹配”双证据。
7. watermark 仅按 Stage6.1 已确认 occurrence 的字符级几何/字体/旋转证据过滤；不按字符值全局替换。
8. Stage6.2 的 partial 必须向 Stage6.3 继承。
9. Stage6.4 只合并“高置信普通正文”的跨页 continuation：
   - 只处理相邻页；
   - 只处理同 section 的 semi_free 区域；
   - 只处理 main + single-column + native_text；
   - 页边界前后不能有 table/image/vector；
   - Stage6.3 的 is_geometric_heading 不作为跨页硬拒绝条件；
   - 下一页仍通过独立的文本结构规则识别标题/编号项；
   - 上一页尾行必须接近正文右边界，下一页首行不能表现出明显首行缩进；
   - 上一页尾行若已经有强句末标点，则保守不合并。
10. Stage6.4 不修改 Stage6.3 physical paragraphs，只生成独立 logical continuation view。
11. Stage6.5 按设计跳过：不做断词 / 字符级修复，避免错误修改原文。
12. Stage6.6 负责形成 Stage1~6 的最终 native flow：
    - 复用 Stage6.4 logical paragraphs；
    - 正式消费 Stage5 table recovery，把 table_ref 对应的 native table 内容物化到最终结构化结果；
    - 将 Stage6.1 已确认 auto_remove occurrence 在源 table cell 上的清理正式落实到最终 table rows；
    - Stage5 logical cross-page table 按 row start_page 物化，保留 source fragments / row provenance；
    - paragraph 已完整表达的 layout/overlap table 在本阶段标记为 suppressed，不再由 readable renderer 二次判断；
    - 已物化的 native table 只对“几何落在源表格内、且去除已确认噪声后文本确实存在于最终 table_text”的 raw word 建立 ownership；
      仅当 paragraph 的全部 source words 都被这种最终 table authority 覆盖时才抑制；
    - 若 PDF 将“表格正文片段 + confirmed watermark 字符”合并成单个 raw word，导致 raw-word bbox 被水印拉伸而 ownership 未命中，
      Stage6.6 还会使用“source_word provenance + confirmed-noise 实际移除 + cleaned raw text 与 paragraph 精确一致 + materialized table 已表达该文本”
      的四重证据抑制残余 paragraph；不按 case/page/固定字符串删除；
    - image / vector 继续只保留引用占位；
    - normalized_text_flow.json 是 Stage1~6 的最终 native 机器结果，不是最终 LLM Document。
13. readable_final.md 只是 normalized_text_flow.json 的人类可读渲染：
    - 不读取 Stage5 / Stage1 / noise 再做修复；
    - 不新增删除、去重、表格恢复或噪声清理逻辑；
    - 只改变展示格式。
14. Stage6 不做 OCR、不做语义补写、不做 Quality Gate。

目标：
- 识别页码候选；
- 识别重复页眉 / 页脚候选，并区分 exact / pattern 分组；
- 识别重复斜向大字水印候选；
- 为候选增加 action，但仍不删除、不改正文；
- 不重新打开 PDF；
- 不做 OCR；
- Stage 6.2 恢复页内 block reading order；
- Stage 6.3 基于 Stage1 words + Stage6.2 reading order 重建行与段落；
- Stage 6.4 高置信恢复跨页普通正文 continuation；
- Stage6.3 physical paragraphs 保持不变，Stage6.4 只生成 logical paragraph view；
- Stage 6.5 明确跳过，不做断词/字符级语义修复；
- Stage 6.6 物化 Stage5 table recovery，形成 Stage1~6 最终 native flow；
- readable_final.md 仅渲染 Stage6 最终机器结果，不再额外修复；
- 不做 Quality Gate。

输入：
1. Stage 1 Raw Evidence JSONL
2. Stage 4 Page Structure JSON
3. Stage 5 Table Recovery result.json

输出：
- noise_candidates.json
- noise_candidates.md
- reading_order.json / reading_order.md
- paragraphs.json / paragraphs.md
- cross_page_paragraphs.json / cross_page_paragraphs.md
- normalized_text_flow.json / normalized_text_flow.md
- readable_final.md
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TextFlowResult:
    noise: dict[str, Any]
    reading_order: dict[str, Any]
    paragraphs: dict[str, Any]
    cross_page_paragraphs: dict[str, Any]
    normalized_flow: dict[str, Any]


PIPELINE_VERSION = "0.6.15"
STAGE61_VERSION = "0.1.2"
STAGE62_VERSION = "0.2.10"
STAGE63_VERSION = "0.3.16"
STAGE64_VERSION = "0.1.2"
STAGE65_STATUS = "skipped_by_design"
STAGE66_VERSION = "0.3.6"

# 兼容旧内部引用。正式输出使用各 sub-stage 的算法版本。
VERSION = PIPELINE_VERSION

# 页眉 / 页脚只在页面边缘区域判断。
HEADER_ZONE_RATIO = 0.12
FOOTER_ZONE_RATIO = 0.88

# 重复页眉 / 页脚至少跨 3 页。
REPEAT_MIN_PAGES = 3

# repeated header/footer 只有“原始文本完全一致”
# 且页面连续/近连续时，才允许建议 KEEP_FIRST。
KEEP_FIRST_MIN_PAGES = 5
KEEP_FIRST_MAX_PAGE_GAP = 2

# 位置聚类桶。只用于把“同一位置附近”的重复文本聚在一起。
POSITION_BUCKET = 0.04

# 大字斜向水印。
WATERMARK_MIN_FONT_SIZE = 24.0
WATERMARK_MIN_PAGES = 3
WATERMARK_BODY_MIN_RATIO = 0.12
WATERMARK_BODY_MAX_RATIO = 0.88

# word 行聚合。
LINE_Y_TOLERANCE = 3.0

# =============================================================================
# Stage 6.2 Reading Order
# =============================================================================

# 多栏页中，足够宽的 block 视为跨栏 block。
READING_SPAN_MIN_WIDTH_RATIO = 0.58

# bbox 跨过页面中线，且本身已有一定宽度时，
# 也视为跨栏 block。
READING_CROSS_MID_MIN_WIDTH_RATIO = 0.34

# 判断 block 与跨栏 separator 是否发生明显纵向重叠。
READING_VERTICAL_OVERLAP_TOLERANCE = 2.0

# 宽 text block 的“中缝证据”。
# 只针对 Stage4 已经变成宽 block 的 text：
# 如果多行都呈现“左边一簇 + 右边一簇，中间没有单词跨过页面中线”，
# 则把它视为 Stage4 的双栏粘连，而不是真正跨栏标题。
READING_WORD_BLOCK_TOLERANCE = 2.0
READING_GUTTER_LINE_Y_TOLERANCE = 5.0
READING_GUTTER_MIN_ABS = 8.0
READING_GUTTER_MIN_RATIO = 0.012
READING_GUTTER_MIN_EVIDENCE_LINES = 2
READING_GUTTER_MIN_EVIDENCE_RATIO = 0.50

# 只有 1 条 bilateral line 时，要求更强中缝证据。
# 用于修复 Stage4 把“左栏尾句 + 右栏尾句”粘成一个宽 text block 的情况。
READING_SINGLE_LINE_GUTTER_MIN_ABS = 10.0
READING_SINGLE_LINE_GUTTER_MIN_RATIO = 0.016
READING_SINGLE_LINE_MIN_TEXT_CHARS_PER_SIDE = 8

# 若当前 block 内确实存在已识别 watermark 干扰，
# 单行 gutter 对“较短一侧”的最小字符数可保守降低。
READING_NOISE_ASSISTED_SINGLE_LINE_MIN_CHARS_PER_SIDE = 4

# noise-inflated span 降回单侧时，
# 过滤水印后该侧至少要有这么多正文字符。
READING_NOISE_INFLATED_MIN_TEXT_CHARS = 8

# ----------------------------------------------------------------------
# Boundary footer table
#
# 目标：
# 某些 PDF 的页脚本身由线框/单元格排版，Stage1/Stage4 会合理地把它识别为 table。
# Stage6.2 只在“极底部 + 很薄 + 几乎整页宽 + 原始几何越过底边 + 极少行”
# 这些强证据同时成立时，才把它从逻辑 reading order 排除。
#
# 注意：
# - 不匹配任何具体文字；
# - 不按固定页码判断；
# - 原始 Stage1 / Stage4 证据不删除；
# - 若 Stage4 已把该 block 标成跨页 table candidate，则绝不自动排除。
# ----------------------------------------------------------------------
BOUNDARY_FOOTER_TOP_MIN_RATIO = 0.90
BOUNDARY_FOOTER_MAX_HEIGHT_RATIO = 0.10
BOUNDARY_FOOTER_MIN_WIDTH_RATIO = 0.90
BOUNDARY_FOOTER_STRONG_WIDTH_RATIO = 0.98
BOUNDARY_FOOTER_MIN_BOTTOM_OVERFLOW = 1.0
BOUNDARY_FOOTER_MAX_ROWS = 2
BOUNDARY_FOOTER_HORIZONTAL_OVERFLOW_TOL = 1.0

# ----------------------------------------------------------------------
# Bottom ancillary / footer text
#
# 解决多栏论文页常见问题：
# 左/右栏主正文之外，页底还存在作者信息、收稿信息、单位、版权声明等。
#
# 这里只使用几何 + 字号证据：
# - 不匹配任何具体期刊名、作者信息、版权文本或其他样本字符串；
# - ancillary 不删除，只移动到主正文之后；
# - 极底部、跨栏、明显小字号的 footer text 才从 logical flow 排除；
# - 原始 Stage1 / Stage4 evidence 始终保留。
# ----------------------------------------------------------------------
BOTTOM_FLOW_MAIN_REF_MAX_TOP_RATIO = 0.65
BOTTOM_ANCILLARY_MIN_TOP_RATIO = 0.66
BOTTOM_ANCILLARY_EXTREME_TOP_RATIO = 0.88
# strong：字号明显小于主正文。
# moderate：字号只略小，但必须同时满足“对侧正文继续 + 连续 run”。
BOTTOM_ANCILLARY_STRONG_FONT_RATIO = 0.88
BOTTOM_ANCILLARY_MODERATE_FONT_RATIO = 0.92

BOTTOM_ANCILLARY_MIN_ITEM_CHARS = 8

BOTTOM_ANCILLARY_STRONG_MIN_RUN_ITEMS = 2
BOTTOM_ANCILLARY_STRONG_MIN_RUN_CHARS = 80

BOTTOM_ANCILLARY_MODERATE_MIN_RUN_ITEMS = 3
BOTTOM_ANCILLARY_MODERATE_MIN_RUN_CHARS = 120

BOTTOM_ANCILLARY_OPPOSITE_CONTINUE_RATIO = 0.04

# 图 / 图表区域保护：
# 小字号如果实际落在 image/vector 的二维区域中，更可能是图内标签、坐标、图例，
# 不能因为“小字号 + 靠下”就当 ancillary。
BOTTOM_FLOW_FIGURE_PROTECT_MIN_TEXT_COVERAGE = 0.20
BOTTOM_FLOW_FIGURE_PROTECT_CENTER_INSIDE = True

# 已确认 ancillary run 的“向下连续扩展”。
#
# 用途：
# 某些页底辅助信息前半段满足“对侧正文继续”，后半段由于右栏正文已经接近页底，
# 不再满足该条件，但它仍然是同一段连续的小字号辅助信息。
#
# 扩展只允许：
# - 同一栏；
# - 位于已确认 ancillary run 的下方；
# - 与上一段距离较近；
# - 字号与 ancillary run 相近；
# - 字号仍明显小于该栏主正文；
# - 不落在 image/vector 区域。
#
# 不使用任何具体文字或样本特征。
BOTTOM_ANCILLARY_TAIL_MAX_GAP_RATIO = 0.07
BOTTOM_ANCILLARY_TAIL_FONT_TOLERANCE_RATIO = 0.10
BOTTOM_ANCILLARY_TAIL_MIN_TOP_RATIO = 0.66

# v0.2.9：
# PDF text block 的 bbox 可能彼此纵向重叠，因此不能要求
# next.top >= previous.bottom 才叫“向下连续”。
#
# 改为：
# - 候选 top 必须继续向下推进；
# - 若 bbox 重叠，则 effective_gap=0；
# - 若不重叠，再用真实 gap 控制断层；
# - 不允许同 top / 往回的 block 被 tail extension 吸收。
BOTTOM_ANCILLARY_TAIL_MIN_TOP_PROGRESS_RATIO = 0.001

BOUNDARY_FOOTER_TEXT_MIN_TOP_RATIO = 0.90
BOUNDARY_FOOTER_TEXT_MIN_BOTTOM_RATIO = 0.94
BOUNDARY_FOOTER_TEXT_MAX_HEIGHT_RATIO = 0.08
BOUNDARY_FOOTER_TEXT_MIN_WIDTH_RATIO = 0.50
BOUNDARY_FOOTER_TEXT_MAX_FONT_RATIO = 0.90
BOUNDARY_FOOTER_TEXT_MIN_CHARS = 8
BOUNDARY_FOOTER_COMPANION_Y_TOL_RATIO = 0.03

# reading order 只输出结构顺序，不在本阶段改 Stage4 block。

# =============================================================================
# Stage 6.3 Line → Paragraph Reconstruction
# =============================================================================
#
# 设计原则：
# - Stage6.2 决定“先读谁、后读谁”；
# - Stage6.3 不重新判断复杂 Layout；
# - 内容来自 Stage1 words，不重新打开 PDF；
# - 一个 Stage1 word 在本页最多分配给一个 text reading unit，避免 bbox 重叠导致重复；
# - 只做几何行/段重建，不做 OCR、不猜语义、不修断词；
# - Stage6.2 若本页已经 partial，Stage6.3 不把它“洗成 completed”。

PARAGRAPH_WORD_BBOX_TOLERANCE = 1.5
PARAGRAPH_WORD_MIN_OVERLAP_COVERAGE = 0.45

# 同一行的 y-center 容差：
# 最终取 max(固定值, word_height * ratio)。
PARAGRAPH_LINE_Y_TOLERANCE = 2.5
PARAGRAPH_LINE_Y_HEIGHT_RATIO = 0.42

# v0.3.14：行聚合除了 center_y，还要求垂直区间本身一致。
# 旧逻辑仅凭 center_y 会在异常高 bbox / 跨行 word 出现时，
# 把不同物理行误并成同一 line，随后造成正文语序重排。
PARAGRAPH_LINE_MIN_VERTICAL_OVERLAP_RATIO = 0.55
PARAGRAPH_LINE_EDGE_TOL_HEIGHT_RATIO = 0.45
PARAGRAPH_LINE_TALL_WORD_RATIO = 1.80
PARAGRAPH_LINE_TALL_EDGE_TOL_HEIGHT_RATIO = 0.30

# 行间距明显大于正常行高时，认为是新段。
PARAGRAPH_BREAK_GAP_HEIGHT_RATIO = 0.90

# 跨 Stage6.2 text unit 合并要求更严格。
PARAGRAPH_CROSS_UNIT_MAX_GAP_HEIGHT_RATIO = 0.55
PARAGRAPH_CROSS_UNIT_MAX_LEFT_SHIFT_HEIGHT_RATIO = 1.20

# 几何标题：
# 短、相对居中，或字号显著高于页面正文参考。
# 这里只作为“不要与正文粘在一起”的保护，不做语义标题识别。
PARAGRAPH_HEADING_MAX_CHAR_COUNT = 120
PARAGRAPH_HEADING_MAX_WIDTH_RATIO = 0.72
PARAGRAPH_HEADING_CENTER_TOL_RATIO = 0.12
PARAGRAPH_HEADING_FONT_RATIO = 1.18

# v0.3.12：仅“居中 + 较短”不再足以判定标题。
# 普通正文在窄版心/短行时也可能天然居中，旧逻辑会把整页正文逐行切段。
# 居中型标题需要同时满足更短、更窄，且字号至少略高于正文参考。
PARAGRAPH_CENTERED_HEADING_MAX_CHAR_COUNT = 60
PARAGRAPH_CENTERED_HEADING_MAX_WIDTH_RATIO = 0.58
PARAGRAPH_CENTERED_HEADING_MIN_FONT_RATIO = 1.05

# 行首明显缩进可作为新段弱证据。
PARAGRAPH_INDENT_BREAK_HEIGHT_RATIO = 1.15

# empty text unit 不能一律判整页 partial。
#
# Stage6.2 的 logical split / bbox overlap 会让一个 raw word 同时落入多个
# text unit；Stage6.3 为避免重复，只把它唯一分配给最具体的 unit。
# 因而另一个 unit 可能“空”，但文字并没有丢。
#
# 只有：
# - 该 empty unit 没有任何 Stage1 word 候选；
# - 且它自身仍有非平凡 text_preview；
# - 且属于 main flow；
# 才作为 Stage6.3 自己新增的风险。
PARAGRAPH_EMPTY_UNIT_RISK_MIN_CHARS = 4

# =============================================================================
# Stage6.3 Table Geometry: data_table vs layout_container
# =============================================================================
#
# 一些申报书会用“表格边框”包住一整块长正文。
# pdfplumber 把它识别为 table geometry 并没有错，但在最终文本流中，
# 这种结构更接近“布局容器”而不是真正二维数据表。
#
# 判定必须保守：
# - 行数/列数很少；
# - 非空 cell 很少；
# - 至少一个 cell 是明显长正文；
# - 长正文占绝大多数文本；
# - 一维容器（1 列）可以直接作为强证据；
# - 2 列情况仅在 semi_free/free 区域允许降级为 layout container。
#
# 这一步不修改 Stage4 / Stage5 原始 table 证据，只改变 Stage6.3 logical flow。
LAYOUT_CONTAINER_MAX_ROWS = 3
LAYOUT_CONTAINER_MAX_COLUMNS = 2
LAYOUT_CONTAINER_MAX_NONEMPTY_CELLS = 4
LAYOUT_CONTAINER_MIN_TOTAL_CHARS = 300
LAYOUT_CONTAINER_MIN_LONGEST_CELL_CHARS = 250
LAYOUT_CONTAINER_MIN_LONGEST_SHARE = 0.60
LAYOUT_CONTAINER_SEMIFREE_ZONES = {
    "semi_free",
    "free",
}
LAYOUT_CONTAINER_TABLE_BBOX_IOU = 0.85

# layout_container 内部段落恢复：
# 顺序继续以 Stage1 extracted_data 为准；
# raw words 只提供“首行缩进 / 行距”这种弱几何证据。
LAYOUT_PARAGRAPH_VISUAL_MATCH_MIN_SCORE = 0.52
LAYOUT_PARAGRAPH_HEADING_MAX_CHARS = 100
LAYOUT_PARAGRAPH_INDENT_HEIGHT_RATIO = 1.30
LAYOUT_PARAGRAPH_LARGE_GAP_HEIGHT_RATIO = 0.80
LAYOUT_PARAGRAPH_ORDER_INVERSION_TOL_HEIGHT_RATIO = 0.50

# layout_container 已经用 Stage1 extracted_data 作为正文来源后，
# 同一区域内 Stage4/Stage6.2 的 native text 可能再次输出同一批文字，
# 造成重复正文、以及水印碎片重新进入 logical flow。
#
# 只有同时满足“几何上主要位于 container 内 + 文本证据可证明已被
# extracted_data 表示”时才抑制 native text；不会只凭 bbox 相交删除。
LAYOUT_CONTAINER_NATIVE_TEXT_MIN_BBOX_COVERAGE = 0.60
LAYOUT_CONTAINER_NATIVE_TEXT_MIN_PREVIEW_CHARS = 8
LAYOUT_CONTAINER_NATIVE_TEXT_MIN_MATCH_COVERAGE = 0.80

# 常规 geometry coverage 不足时，不直接降低 0.60 全局阈值。
# 只有“文本几乎完全重复 + paragraph 确实与 container 相交
# + paragraph 起点位于 container 内”时，允许走强文本证据路径。
LAYOUT_CONTAINER_NATIVE_TEXT_STRONG_MATCH_COVERAGE = 0.97
LAYOUT_CONTAINER_NATIVE_TEXT_START_TOLERANCE = 1.5


PAGE_RATIO_RE = re.compile(
    r"^\s*(\d{1,4})\s*/\s*(\d{1,4})\s*$"
)

BARE_PAGE_NUMBER_RE = re.compile(
    r"^\s*(\d{1,4})\s*$"
)

INNER_PAGE_NUMBER_RE = re.compile(
    r"^\s*[-–—]\s*(\d{1,4})\s*[-–—]\s*$"
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(value),
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def normalize_bbox(
    value: Any,
) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None

    required = (
        "x0",
        "top",
        "x1",
        "bottom",
    )

    if not all(
        finite_number(value.get(key))
        for key in required
    ):
        return None

    x0 = float(value["x0"])
    top = float(value["top"])
    x1 = float(value["x1"])
    bottom = float(value["bottom"])

    if x1 <= x0 or bottom <= top:
        return None

    return {
        "x0": x0,
        "top": top,
        "x1": x1,
        "bottom": bottom,
    }


def bbox_union(
    bboxes: list[dict[str, float]],
) -> dict[str, float] | None:
    if not bboxes:
        return None

    return {
        "x0": min(
            bbox["x0"]
            for bbox in bboxes
        ),
        "top": min(
            bbox["top"]
            for bbox in bboxes
        ),
        "x1": max(
            bbox["x1"]
            for bbox in bboxes
        ),
        "bottom": max(
            bbox["bottom"]
            for bbox in bboxes
        ),
    }


def bbox_ratios(
    bbox: dict[str, float],
    width: float,
    height: float,
) -> dict[str, float]:
    center_x = (
        bbox["x0"]
        + bbox["x1"]
    ) / 2.0

    center_y = (
        bbox["top"]
        + bbox["bottom"]
    ) / 2.0

    return {
        "x_ratio": (
            center_x / width
            if width > 0
            else 0.0
        ),
        "y_ratio": (
            center_y / height
            if height > 0
            else 0.0
        ),
    }


def position_bucket(
    ratio: float,
) -> int:
    return int(
        round(
            ratio
            / POSITION_BUCKET
        )
    )


def load_json(
    path: Path,
) -> dict[str, Any]:
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise ValueError(
            f"JSON 根节点必须是对象: {path}"
        )

    return value


def load_snapshot(
    path: Path,
) -> tuple[
    dict[str, Any],
    dict[int, dict[str, Any]],
]:
    meta: dict[str, Any] | None = None
    pages: dict[int, dict[str, Any]] = {}

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            line = line.strip()

            if not line:
                continue

            value = json.loads(line)

            if not isinstance(value, dict):
                raise ValueError(
                    f"JSONL 第 {line_number} 行不是对象。"
                )

            record_type = value.get(
                "record_type"
            )

            if record_type == "meta":
                meta = value
                continue

            if record_type != "page":
                continue

            page_number = int(
                value["page_number"]
            )

            if page_number in pages:
                raise ValueError(
                    f"Raw Evidence 重复页面: {page_number}"
                )

            pages[page_number] = value

    if meta is None:
        raise ValueError(
            "Raw Evidence JSONL 缺少 meta record。"
        )

    return meta, pages


def structure_page_index(
    structure: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    result: dict[
        int,
        dict[str, Any],
    ] = {}

    for page in structure.get(
        "pages",
        [],
    ):
        if not isinstance(page, dict):
            continue

        page_number = int(
            page["page_number"]
        )

        result[page_number] = page

    return result


def validate_inputs(
    snapshot_meta: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    structure: dict[str, Any],
) -> str:
    source_file = clean_text(
        snapshot_meta.get(
            "source_file"
        )
    )

    structure_source = clean_text(
        structure.get(
            "source_file"
        )
    )

    if (
        source_file
        and structure_source
        and source_file
        != structure_source
    ):
        raise ValueError(
            "Raw Evidence 与 Page Structure source_file 不一致: "
            f"{source_file} != {structure_source}"
        )

    page_count = int(
        structure.get(
            "page_count",
            len(snapshot_pages),
        )
    )

    expected = set(
        range(
            1,
            page_count + 1,
        )
    )

    if set(snapshot_pages) != expected:
        raise ValueError(
            "Raw Evidence 页面不是完整连续的 1..page_count。"
        )

    structure_pages = structure_page_index(
        structure
    )

    if set(structure_pages) != expected:
        raise ValueError(
            "Page Structure 页面不是完整连续的 1..page_count。"
        )

    return (
        source_file
        or structure_source
        or "unknown.pdf"
    )


# =============================================================================
# Boundary lines
# =============================================================================


def valid_words(
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for word in raw_page.get(
        "words",
        [],
    ):
        if not isinstance(word, dict):
            continue

        text = clean_text(
            word.get("text")
        )

        bbox = normalize_bbox(word)

        if not text or bbox is None:
            continue

        result.append(
            {
                "text": text,
                "bbox": bbox,
            }
        )

    return result


def group_words_into_lines(
    words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    words = sorted(
        words,
        key=lambda item: (
            item["bbox"]["top"],
            item["bbox"]["x0"],
        ),
    )

    lines: list[
        list[dict[str, Any]]
    ] = []

    for word in words:
        center_y = (
            word["bbox"]["top"]
            + word["bbox"]["bottom"]
        ) / 2.0

        if not lines:
            lines.append([word])
            continue

        current = lines[-1]

        current_center = sum(
            (
                item["bbox"]["top"]
                + item["bbox"]["bottom"]
            ) / 2.0
            for item in current
        ) / len(current)

        if (
            abs(
                center_y
                - current_center
            )
            <= LINE_Y_TOLERANCE
        ):
            current.append(word)
        else:
            lines.append([word])

    return lines


def boundary_lines(
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    width = float(
        raw_page.get(
            "width",
            0.0,
        )
        or 0.0
    )
    height = float(
        raw_page.get(
            "height",
            0.0,
        )
        or 0.0
    )

    if width <= 0 or height <= 0:
        return []

    result: list[
        dict[str, Any]
    ] = []

    for words in group_words_into_lines(
        valid_words(raw_page)
    ):
        bbox = bbox_union(
            [
                item["bbox"]
                for item in words
            ]
        )

        if bbox is None:
            continue

        ratio = bbox_ratios(
            bbox,
            width,
            height,
        )

        zone: str | None = None

        if (
            ratio["y_ratio"]
            <= HEADER_ZONE_RATIO
        ):
            zone = "header"

        elif (
            ratio["y_ratio"]
            >= FOOTER_ZONE_RATIO
        ):
            zone = "footer"

        if zone is None:
            continue

        ordered = sorted(
            words,
            key=lambda item:
                item["bbox"]["x0"],
        )

        text = clean_text(
            " ".join(
                item["text"]
                for item in ordered
            )
        )

        if not text:
            continue

        result.append(
            {
                "text": text,
                "bbox": bbox,
                "zone": zone,
                **ratio,
            }
        )

    return result


# =============================================================================
# Page number candidates
# =============================================================================


def is_plausible_ratio_page_number(
    text: str,
) -> tuple[int, int] | None:
    match = PAGE_RATIO_RE.fullmatch(
        text
    )

    if match is None:
        return None

    numerator = int(
        match.group(1)
    )
    denominator = int(
        match.group(2)
    )

    if (
        numerator < 0
        or denominator <= 0
        or numerator > denominator
    ):
        return None

    return numerator, denominator


def detect_ratio_page_numbers(
    snapshot_pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, int, int, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for page_number, raw_page in snapshot_pages.items():
        for line in boundary_lines(
            raw_page
        ):
            parsed = (
                is_plausible_ratio_page_number(
                    line["text"]
                )
            )

            if parsed is None:
                continue

            numerator, denominator = parsed

            key = (
                line["zone"],
                denominator,
                position_bucket(
                    line["x_ratio"]
                ),
                position_bucket(
                    line["y_ratio"]
                ),
            )

            groups[key].append(
                {
                    "page_number":
                        page_number,
                    "printed_value":
                        numerator,
                    "text":
                        line["text"],
                    "bbox":
                        line["bbox"],
                    "x_ratio":
                        line["x_ratio"],
                    "y_ratio":
                        line["y_ratio"],
                }
            )

    candidates: list[
        dict[str, Any]
    ] = []

    for (
        zone,
        denominator,
        _,
        _,
    ), occurrences in groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        # N/M 本身已经很强，但仍要求至少跨 2 页，
        # 避免正文边缘单次出现比例值。
        if len(pages) < 2:
            continue

        candidates.append(
            {
                "type": "page_number",
                "subtype": "ratio",
                "text": f"N/{denominator}",
                "zone": zone,
                "pages": pages,
                "page_count":
                    len(pages),
                "occurrences":
                    occurrences,
                "reason":
                    "页面边缘重复出现 N/M 形式页码",
            }
        )

    return candidates


def sequential_score(
    occurrences: list[dict[str, Any]],
) -> float:
    ordered = sorted(
        occurrences,
        key=lambda item:
            item["page_number"],
    )

    if len(ordered) < 3:
        return 0.0

    good = 0
    total = 0

    for left, right in zip(
        ordered,
        ordered[1:],
    ):
        page_delta = (
            right["page_number"]
            - left["page_number"]
        )

        value_delta = (
            right["printed_value"]
            - left["printed_value"]
        )

        if page_delta <= 0:
            continue

        total += 1

        if page_delta == value_delta:
            good += 1

    return (
        good / total
        if total > 0
        else 0.0
    )


def detect_bare_page_numbers(
    snapshot_pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, int, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for page_number, raw_page in snapshot_pages.items():
        for line in boundary_lines(
            raw_page
        ):
            match = BARE_PAGE_NUMBER_RE.fullmatch(
                line["text"]
            )

            if match is None:
                continue

            value = int(
                match.group(1)
            )

            key = (
                line["zone"],
                position_bucket(
                    line["x_ratio"]
                ),
                position_bucket(
                    line["y_ratio"]
                ),
            )

            groups[key].append(
                {
                    "page_number":
                        page_number,
                    "printed_value":
                        value,
                    "text":
                        line["text"],
                    "bbox":
                        line["bbox"],
                    "x_ratio":
                        line["x_ratio"],
                    "y_ratio":
                        line["y_ratio"],
                }
            )

    candidates: list[
        dict[str, Any]
    ] = []

    for (
        zone,
        _,
        _,
    ), occurrences in groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        if len(pages) < 3:
            continue

        score = sequential_score(
            occurrences
        )

        if score < 0.70:
            continue

        candidates.append(
            {
                "type": "page_number",
                "subtype": "bare_integer",
                "text": "sequential_integer",
                "zone": zone,
                "pages": pages,
                "page_count":
                    len(pages),
                "sequence_score":
                    round(score, 4),
                "occurrences":
                    occurrences,
                "reason":
                    "页面边缘整数随物理页连续递增",
            }
        )

    return candidates



def detect_inner_page_numbers(
    snapshot_pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    识别附件内部装饰页码，例如：

        - 1 -
        - 2 -
        - 3 -

    必须位于页面边缘、位置稳定，并且数值随物理页连续递增。
    """
    groups: dict[
        tuple[str, int, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for page_number, raw_page in snapshot_pages.items():
        for line in boundary_lines(raw_page):
            match = INNER_PAGE_NUMBER_RE.fullmatch(
                line["text"]
            )

            if match is None:
                continue

            value = int(match.group(1))

            key = (
                line["zone"],
                position_bucket(line["x_ratio"]),
                position_bucket(line["y_ratio"]),
            )

            groups[key].append(
                {
                    "page_number": page_number,
                    "printed_value": value,
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "x_ratio": line["x_ratio"],
                    "y_ratio": line["y_ratio"],
                }
            )

    candidates: list[dict[str, Any]] = []

    for (zone, _, _), occurrences in groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        if len(pages) < 3:
            continue

        score = sequential_score(
            occurrences
        )

        if score < 0.70:
            continue

        candidates.append(
            {
                "type": "page_number",
                "subtype":
                    "inner_sequential_decorated_integer",
                "text": "- N -",
                "zone": zone,
                "pages": pages,
                "page_count": len(pages),
                "sequence_score":
                    round(score, 4),
                "occurrences":
                    occurrences,
                "reason":
                    "页面边缘装饰整数随物理页连续递增",
            }
        )

    return candidates


# =============================================================================
# Repeated header / footer
# =============================================================================


def normalized_repeat_text(
    text: str,
) -> str:
    value = clean_text(text)

    # 对重复页眉页脚，数字通常属于日期/编号变化。
    # 只做轻量归一化，不去掉文字。
    value = re.sub(
        r"\d+",
        "#",
        value,
    )

    return value


def max_page_gap(
    pages: list[int],
) -> int | None:
    ordered = sorted(set(pages))

    if len(ordered) < 2:
        return None

    return max(
        right - left
        for left, right in zip(
            ordered,
            ordered[1:],
        )
    )


def detect_repeated_boundary_text(
    snapshot_pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    repeated header/footer 分两层：

    exact:
      原始文本完全相同。
      这是强重复证据，未来才可能 KEEP_FIRST。

    pattern:
      仅“数字替换为 # 后”格式相同，但原始文本不同。
      只能说明版式相似，不能证明是同一附件/同一标题。
      因此只能 REVIEW。

    "- N -" 形式的连续附件页码在这里排除，
    由 detect_inner_page_numbers 单独处理。
    """
    exact_groups: dict[
        tuple[str, str, int, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    pattern_groups: dict[
        tuple[str, str, int, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for page_number, raw_page in snapshot_pages.items():
        for line in boundary_lines(raw_page):
            raw_text = clean_text(
                line["text"]
            )

            if not raw_text:
                continue

            if (
                is_plausible_ratio_page_number(
                    raw_text
                )
                is not None
            ):
                continue

            if BARE_PAGE_NUMBER_RE.fullmatch(
                raw_text
            ):
                continue

            if INNER_PAGE_NUMBER_RE.fullmatch(
                raw_text
            ):
                continue

            if len(raw_text) < 2:
                continue

            x_bucket = position_bucket(
                line["x_ratio"]
            )
            y_bucket = position_bucket(
                line["y_ratio"]
            )

            occurrence = {
                "page_number":
                    page_number,
                "text":
                    raw_text,
                "bbox":
                    line["bbox"],
                "x_ratio":
                    line["x_ratio"],
                "y_ratio":
                    line["y_ratio"],
            }

            exact_groups[
                (
                    line["zone"],
                    raw_text,
                    x_bucket,
                    y_bucket,
                )
            ].append(
                occurrence
            )

            normalized = normalized_repeat_text(
                raw_text
            )

            pattern_groups[
                (
                    line["zone"],
                    normalized,
                    x_bucket,
                    y_bucket,
                )
            ].append(
                occurrence
            )

    candidates: list[dict[str, Any]] = []

    # 强候选：原始文本完全一致。
    for (
        zone,
        raw_text,
        _,
        _,
    ), occurrences in exact_groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        if len(pages) < REPEAT_MIN_PAGES:
            continue

        candidate_type = (
            "repeated_header"
            if zone == "header"
            else "repeated_footer"
        )

        candidates.append(
            {
                "type": candidate_type,
                "subtype":
                    "exact_repeated_boundary_text",
                "grouping_mode": "exact",
                "text": raw_text,
                "zone": zone,
                "pages": pages,
                "page_count": len(pages),
                "max_page_gap":
                    max_page_gap(pages),
                "occurrences":
                    occurrences,
                "reason":
                    "原始边界文本完全相同且跨多页重复出现",
            }
        )

    # 弱候选：归一化后格式相同，但原始文本有差异。
    for (
        zone,
        normalized,
        _,
        _,
    ), occurrences in pattern_groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        if len(pages) < REPEAT_MIN_PAGES:
            continue

        distinct_texts = sorted(
            {
                clean_text(
                    item["text"]
                )
                for item in occurrences
                if clean_text(
                    item["text"]
                )
            }
        )

        # 原文只有一种时，exact candidate 已覆盖。
        if len(distinct_texts) <= 1:
            continue

        candidate_type = (
            "repeated_header"
            if zone == "header"
            else "repeated_footer"
        )

        candidates.append(
            {
                "type": candidate_type,
                "subtype":
                    "pattern_repeated_boundary_text",
                "grouping_mode":
                    "pattern",
                "text":
                    normalized,
                "zone":
                    zone,
                "pages":
                    pages,
                "page_count":
                    len(pages),
                "max_page_gap":
                    max_page_gap(pages),
                "distinct_text_count":
                    len(distinct_texts),
                "distinct_texts":
                    distinct_texts,
                "occurrences":
                    occurrences,
                "reason":
                    "数字归一化后格式相似，但原始文本存在差异",
            }
        )

    return candidates


# =============================================================================
# Watermark candidates
# =============================================================================


def char_rotation_strength(
    char: dict[str, Any],
) -> float:
    matrix = char.get(
        "matrix"
    )

    if (
        not isinstance(matrix, (list, tuple))
        or len(matrix) < 4
    ):
        return 0.0

    try:
        b = abs(
            float(matrix[1])
        )
        c = abs(
            float(matrix[2])
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0.0

    return max(b, c)


def detect_watermarks(
    snapshot_pages: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, str, int],
        list[dict[str, Any]],
    ] = defaultdict(list)

    for page_number, raw_page in snapshot_pages.items():
        width = float(
            raw_page.get(
                "width",
                0.0,
            )
            or 0.0
        )
        height = float(
            raw_page.get(
                "height",
                0.0,
            )
            or 0.0
        )

        if width <= 0 or height <= 0:
            continue

        for char in raw_page.get(
            "chars",
            [],
        ):
            if not isinstance(char, dict):
                continue

            text = clean_text(
                char.get("text")
            )

            if not text:
                continue

            # 当前只针对非常短的大字水印。
            if len(text) > 4:
                continue

            size = char.get("size")

            if not finite_number(size):
                continue

            if (
                float(size)
                < WATERMARK_MIN_FONT_SIZE
            ):
                continue

            rotation = (
                char_rotation_strength(
                    char
                )
            )

            # 斜向 / 旋转文字是强水印信号。
            if rotation < 0.20:
                continue

            bbox = normalize_bbox(char)

            if bbox is None:
                continue

            ratios = bbox_ratios(
                bbox,
                width,
                height,
            )

            if not (
                WATERMARK_BODY_MIN_RATIO
                <= ratios["x_ratio"]
                <= WATERMARK_BODY_MAX_RATIO
                and
                WATERMARK_BODY_MIN_RATIO
                <= ratios["y_ratio"]
                <= WATERMARK_BODY_MAX_RATIO
            ):
                continue

            fontname = clean_text(
                char.get("fontname")
            )

            size_bucket = int(
                round(
                    float(size)
                    / 4.0
                )
            )

            key = (
                text,
                fontname,
                size_bucket,
            )

            groups[key].append(
                {
                    "page_number":
                        page_number,
                    "text":
                        text,
                    "bbox":
                        bbox,
                    "x_ratio":
                        ratios[
                            "x_ratio"
                        ],
                    "y_ratio":
                        ratios[
                            "y_ratio"
                        ],
                    "fontname":
                        fontname,
                    "font_size":
                        float(size),
                    "rotation_strength":
                        rotation,
                }
            )

    candidates: list[
        dict[str, Any]
    ] = []

    for (
        text,
        fontname,
        _,
    ), occurrences in groups.items():
        pages = sorted(
            {
                item["page_number"]
                for item in occurrences
            }
        )

        if len(pages) < WATERMARK_MIN_PAGES:
            continue

        candidates.append(
            {
                "type": "watermark",
                "subtype":
                    "repeated_large_rotated_text",
                "text": text,
                "fontname":
                    fontname,
                "pages":
                    pages,
                "page_count":
                    len(pages),
                "occurrences":
                    occurrences,
                "reason":
                    "大字号旋转文字跨多页重复出现",
            }
        )

    return candidates


# =============================================================================
# Conservative candidate decision
# =============================================================================


def assign_candidate_action(
    candidate: dict[str, Any],
) -> None:
    """
    当前只给建议动作，不真正删除。

    AUTO_REMOVE:
      - ratio / bare / inner sequential page number；
      - 多页重复大字旋转水印。

    KEEP_FIRST:
      - 必须是 repeated header/footer 的 exact 分组；
      - 原始文本完全一致；
      - 至少重复 KEEP_FIRST_MIN_PAGES 页；
      - occurrence 最大页距不超过 KEEP_FIRST_MAX_PAGE_GAP。

    REVIEW:
      - 仅格式相似、原始文本/关键数字不同；
      - 或重复次数/页面连续性不足。
    """
    candidate_type = str(
        candidate.get("type", "")
    )

    if candidate_type in {
        "page_number",
        "watermark",
    }:
        candidate["action"] = "auto_remove"
        candidate["action_reason"] = (
            "几何与序列/重复证据足够强，可在后续规范化结果中自动移除"
        )
        return

    if candidate_type in {
        "repeated_header",
        "repeated_footer",
    }:
        grouping_mode = str(
            candidate.get(
                "grouping_mode",
                "pattern",
            )
        )

        if grouping_mode != "exact":
            candidate["action"] = "review"
            candidate["action_reason"] = (
                "仅格式相似，原始文本或关键数字存在差异；"
                "不能证明属于同一重复内容"
            )
            return

        page_count = int(
            candidate.get(
                "page_count",
                0,
            )
            or 0
        )

        gap = candidate.get(
            "max_page_gap"
        )

        gap_ok = (
            gap is None
            or (
                isinstance(gap, int)
                and gap
                <= KEEP_FIRST_MAX_PAGE_GAP
            )
        )

        if (
            page_count >= KEEP_FIRST_MIN_PAGES
            and gap_ok
        ):
            candidate["action"] = "keep_first"
            candidate["action_reason"] = (
                "原始文本完全一致，且在连续/近连续页面高频重复；"
                "后续可保留第一次并压缩重复项"
            )
        else:
            candidate["action"] = "review"
            candidate["action_reason"] = (
                "原始文本重复，但页数或页面连续性不足；暂不自动压缩"
            )
        return

    candidate["action"] = "review"
    candidate["action_reason"] = (
        "未命中安全自动处理规则"
    )


def assign_candidate_actions(
    candidates: list[dict[str, Any]],
) -> None:
    for candidate in candidates:
        assign_candidate_action(
            candidate
        )


# =============================================================================
# Candidate assembly
# =============================================================================


def add_structure_context(
    candidates: list[dict[str, Any]],
    structure_pages: dict[int, dict[str, Any]],
) -> None:
    for candidate in candidates:
        for occurrence in candidate.get(
            "occurrences",
            [],
        ):
            page_number = int(
                occurrence["page_number"]
            )

            structure_page = (
                structure_pages.get(
                    page_number,
                    {},
                )
            )

            document_structure = (
                structure_page.get(
                    "document_structure",
                    {}
                )
                if isinstance(
                    structure_page,
                    dict,
                )
                else {}
            )

            if not isinstance(
                document_structure,
                dict,
            ):
                document_structure = {}

            occurrence["section_id"] = (
                document_structure.get(
                    "section_id"
                )
            )

            occurrence["zone_type"] = (
                document_structure.get(
                    "zone_type"
                )
            )


def sort_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    priority = {
        "page_number": 0,
        "repeated_header": 1,
        "repeated_footer": 2,
        "watermark": 3,
    }

    return sorted(
        candidates,
        key=lambda item: (
            priority.get(
                str(item.get("type")),
                99,
            ),
            str(item.get("text", "")),
            item.get(
                "pages",
                [999999],
            )[0],
        ),
    )


def assign_candidate_ids(
    candidates: list[dict[str, Any]],
) -> None:
    counters: dict[str, int] = (
        defaultdict(int)
    )

    prefix = {
        "page_number": "page_number",
        "repeated_header": "header",
        "repeated_footer": "footer",
        "watermark": "watermark",
    }

    for candidate in candidates:
        candidate_type = str(
            candidate["type"]
        )

        counters[
            candidate_type
        ] += 1

        candidate["candidate_id"] = (
            f"{prefix.get(candidate_type, 'noise')}_"
            f"{counters[candidate_type]:03d}"
        )


def build_result(
    snapshot_meta: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    structure: dict[str, Any],
) -> dict[str, Any]:
    source_file = validate_inputs(
        snapshot_meta,
        snapshot_pages,
        structure,
    )

    structure_pages = (
        structure_page_index(
            structure
        )
    )

    candidates = (
        detect_ratio_page_numbers(
            snapshot_pages
        )
        + detect_bare_page_numbers(
            snapshot_pages
        )
        + detect_inner_page_numbers(
            snapshot_pages
        )
        + detect_repeated_boundary_text(
            snapshot_pages
        )
        + detect_watermarks(
            snapshot_pages
        )
    )

    candidates = sort_candidates(
        candidates
    )

    assign_candidate_ids(
        candidates
    )

    assign_candidate_actions(
        candidates
    )

    add_structure_context(
        candidates,
        structure_pages,
    )

    type_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    occurrence_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    action_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    for candidate in candidates:
        candidate_type = str(
            candidate["type"]
        )

        type_counts[
            candidate_type
        ] += 1

        occurrence_counts[
            candidate_type
        ] += len(
            candidate.get(
                "occurrences",
                []
            )
        )

        action_counts[
            str(
                candidate.get(
                    "action",
                    "review",
                )
            )
        ] += 1

    return {
        "stage": "6.1",
        "version": STAGE61_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "source_file": source_file,
        "page_count":
            len(snapshot_pages),
        "candidate_count":
            len(candidates),
        "candidate_type_counts":
            dict(type_counts),
        "occurrence_type_counts":
            dict(occurrence_counts),
        "action_counts":
            dict(action_counts),
        "noise_candidates":
            candidates,

        # Stage 6.1 只识别 + 决策，不真正删除。
        "text_modified": False,
        "quality_gate_completed":
            False,
        "stage_status": {
            "algorithm_baseline":
                STAGE61_VERSION,
            "sealed":
                True,
            "scope":
                "noise_candidate_detection_only",
        },
    }



# =============================================================================
# Stage 6.2 — Reading Order Recovery
# =============================================================================


def structure_blocks(
    page: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks = page.get(
        "blocks",
        [],
    )

    if not isinstance(blocks, list):
        return []

    return [
        block
        for block in blocks
        if isinstance(block, dict)
    ]


def block_bbox(
    block: dict[str, Any],
) -> dict[str, float] | None:
    return normalize_bbox(
        block.get("bbox")
    )


def block_center_x(
    bbox: dict[str, float],
) -> float:
    return (
        bbox["x0"]
        + bbox["x1"]
    ) / 2.0


def block_center_y(
    bbox: dict[str, float],
) -> float:
    return (
        bbox["top"]
        + bbox["bottom"]
    ) / 2.0


def reading_column_role(
    block: dict[str, Any],
    bbox: dict[str, float],
    page_width: float,
    multi_column: bool,
) -> str:
    """
    只做几何角色判断：

    single:
      单栏页。

    left / right:
      多栏页中的左栏 / 右栏。

    span:
      明显跨栏的标题、表格、图片等。
    """
    if not multi_column:
        return "single"

    if page_width <= 0:
        return "unknown"

    width = (
        bbox["x1"]
        - bbox["x0"]
    )

    width_ratio = (
        width
        / page_width
    )

    mid = (
        page_width
        / 2.0
    )

    crosses_mid = (
        bbox["x0"]
        < mid
        < bbox["x1"]
    )

    if (
        width_ratio
        >= READING_SPAN_MIN_WIDTH_RATIO
    ):
        return "span"

    if (
        crosses_mid
        and width_ratio
        >= READING_CROSS_MID_MIN_WIDTH_RATIO
    ):
        return "span"

    # Stage 4 对 text block 已经提供 column，
    # 优先复用，不重复发明另一套列判断。
    if (
        block.get("block_type")
        == "text"
    ):
        existing = str(
            block.get(
                "column",
                "",
            )
        )

        if existing in {
            "left",
            "right",
        }:
            return existing

    return (
        "left"
        if block_center_x(bbox) < mid
        else "right"
    )


def vertical_overlap(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    return max(
        0.0,
        min(
            first["bottom"],
            second["bottom"],
        )
        -
        max(
            first["top"],
            second["top"],
        ),
    )


def base_spatial_key(
    item: dict[str, Any],
) -> tuple[float, float, int, str]:
    bbox = item["bbox"]

    type_priority = {
        "text": 0,
        "table": 1,
        "image": 2,
        "vector": 3,
    }

    return (
        bbox["top"],
        bbox["x0"],
        type_priority.get(
            str(
                item["block"].get(
                    "block_type",
                    "",
                )
            ),
            99,
        ),
        str(
            item["block"].get(
                "block_id",
                "",
            )
        ),
    )


def column_key(
    item: dict[str, Any],
) -> tuple[float, float, int, int, str]:
    bbox = item["bbox"]

    return (
        bbox["top"],
        bbox["x0"],
        int(
            item.get(
                "original_index",
                0,
            )
        ),
        int(
            item.get(
                "fragment_rank",
                0,
            )
        ),
        str(
            item["block"].get(
                "block_id",
                "",
            )
        ),
    )



def build_stage62_noise_regions(
    noise_result: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    """
    Stage6.2 只消费 Stage6.1 已经给出 auto_remove 的 watermark bbox。

    这里不删除 Stage1 / Stage4 evidence；
    只是告诉 reading-order gutter detector：
    这些 word 若落在水印 bbox 内，不应参与“是否跨页面中线”的判断。
    """
    regions: dict[
        int,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for candidate in noise_result.get(
        "noise_candidates",
        [],
    ):
        if not isinstance(candidate, dict):
            continue

        if (
            candidate.get("type") != "watermark"
            or candidate.get("action") != "auto_remove"
        ):
            continue

        for occurrence in candidate.get(
            "occurrences",
            [],
        ):
            if not isinstance(occurrence, dict):
                continue

            page_number = occurrence.get(
                "page_number"
            )
            bbox = normalize_bbox(
                occurrence.get("bbox")
            )

            if (
                not isinstance(page_number, int)
                or bbox is None
            ):
                continue

            regions[
                page_number
            ].append(
                {
                    "bbox": bbox,
                    "candidate_id":
                        candidate.get(
                            "candidate_id"
                        ),
                    "text":
                        occurrence.get(
                            "text",
                            candidate.get(
                                "text"
                            ),
                        ),
                    "fontname":
                        occurrence.get(
                            "fontname"
                        ),
                    "font_size":
                        occurrence.get(
                            "font_size"
                        ),
                    "rotation_strength":
                        occurrence.get(
                            "rotation_strength"
                        ),
                }
            )

    return dict(regions)


def bbox_intersection_area(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    width = max(
        0.0,
        min(first["x1"], second["x1"])
        - max(first["x0"], second["x0"]),
    )

    height = max(
        0.0,
        min(first["bottom"], second["bottom"])
        - max(first["top"], second["top"]),
    )

    return width * height


def word_matches_ignored_noise(
    word: dict[str, Any],
    regions: list[dict[str, Any]],
) -> bool:
    word_bbox = word["bbox"]

    center_x = (
        word_bbox["x0"]
        + word_bbox["x1"]
    ) / 2.0

    center_y = (
        word_bbox["top"]
        + word_bbox["bottom"]
    ) / 2.0

    word_text = clean_text(
        word.get("text")
    )

    for region in regions:
        bbox = region.get(
            "bbox"
        )

        if not isinstance(
            bbox,
            dict,
        ):
            continue

        # 普通独立 watermark word。
        if point_inside_bbox(
            center_x,
            center_y,
            bbox,
            tolerance=1.0,
        ):
            return True

        # pdfplumber 有时会把旋转水印字符粘进正常 word，
        # 例如 "applications式due"。
        # 这里只影响 gutter 分类，不删除原始 word。
        noise_text = clean_text(
            region.get("text")
        )

        if (
            noise_text
            and noise_text in word_text
            and bbox_intersection_area(
                word_bbox,
                bbox,
            ) > 0
        ):
            return True

    return False


def raw_word_items(
    raw_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Stage1 raw word 的轻量视图。

    v0.6.7 开始显式保留 source_word_index。
    后续 Stage4/Stage6 的 provenance 以这个稳定页内下标作为 ownership 依据，
    不再只依赖 bbox 重新猜 raw word 属于哪个 text block。
    """
    result: list[dict[str, Any]] = []

    for word_index, word in enumerate(
        raw_page.get(
            "words",
            [],
        )
    ):
        if not isinstance(word, dict):
            continue

        bbox = normalize_bbox(word)
        value = clean_text(
            word.get("text")
        )

        if bbox is None or not value:
            continue

        result.append(
            {
                "text": value,
                "bbox": bbox,
                "source_word_index": word_index,
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
        and
        bbox["top"] - tolerance
        <= y
        <= bbox["bottom"] + tolerance
    )


def words_inside_block(
    raw_page: dict[str, Any],
    bbox: dict[str, float],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for word in raw_word_items(
        raw_page
    ):
        word_bbox = word["bbox"]

        center_x = (
            word_bbox["x0"]
            + word_bbox["x1"]
        ) / 2.0

        center_y = (
            word_bbox["top"]
            + word_bbox["bottom"]
        ) / 2.0

        if not point_inside_bbox(
            center_x,
            center_y,
            bbox,
            READING_WORD_BLOCK_TOLERANCE,
        ):
            continue

        if (
            ignored_noise_regions
            and word_matches_ignored_noise(
                word,
                ignored_noise_regions,
            )
        ):
            continue

        result.append(word)

    return result


def words_to_fragment_text(
    words: list[dict[str, Any]],
) -> str:
    lines = group_words_into_lines(
        words
    )

    rendered: list[str] = []

    for line in lines:
        ordered = sorted(
            line,
            key=lambda item:
                item["bbox"]["x0"],
        )

        value = clean_text(
            " ".join(
                item["text"]
                for item in ordered
            )
        )

        if value:
            rendered.append(
                value
            )

    return "\n".join(
        rendered
    )


def group_words_into_gutter_lines(
    words: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    words = sorted(
        words,
        key=lambda item: (
            item["bbox"]["top"],
            item["bbox"]["x0"],
        ),
    )

    lines: list[
        list[dict[str, Any]]
    ] = []

    for word in words:
        center_y = (
            word["bbox"]["top"]
            + word["bbox"]["bottom"]
        ) / 2.0

        if not lines:
            lines.append([word])
            continue

        current = lines[-1]

        current_center = sum(
            (
                item["bbox"]["top"]
                + item["bbox"]["bottom"]
            ) / 2.0
            for item in current
        ) / len(current)

        if (
            abs(
                center_y
                - current_center
            )
            <= READING_GUTTER_LINE_Y_TOLERANCE
        ):
            current.append(word)
        else:
            lines.append([word])

    return lines


def classify_wide_text_block(
    raw_page: dict[str, Any],
    block_bbox_value: dict[str, float],
    page_width: float,
    ignored_noise_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    区分：

    true_span:
        真正跨栏标题 / 作者行等。
        常见特征：单词会自然穿过页面中线，或者中线附近没有稳定中缝。

    merged_two_column:
        Stage4 把左栏 + 右栏同一纵向区域粘成一个宽 text block。
        常见特征：多行同时在左右两侧有词，但没有任何单词跨过中线，
        且左右两簇之间存在稳定的页面中缝。

    insufficient:
        证据不足，保持原 span，不强拆。
    """
    if page_width <= 0:
        return {
            "classification": "insufficient",
            "reason": "invalid_page_width",
            "word_count": 0,
            "bilateral_line_count": 0,
            "gutter_evidence_line_count": 0,
            "gutter_evidence_ratio": 0.0,
        }

    original_words = words_inside_block(
        raw_page,
        block_bbox_value,
        None,
    )

    words = words_inside_block(
        raw_page,
        block_bbox_value,
        ignored_noise_regions,
    )

    ignored_noise_word_count = max(
        0,
        len(original_words) - len(words),
    )

    if not words:
        return {
            "classification": "insufficient",
            "reason": "no_stage1_words_after_noise_filter",
            "word_count": 0,
            "original_word_count": len(original_words),
            "ignored_noise_word_count": ignored_noise_word_count,
            "bilateral_line_count": 0,
            "gutter_evidence_line_count": 0,
            "gutter_evidence_ratio": 0.0,
            "_words": [],
            "_original_words": original_words,
        }

    mid = page_width / 2.0

    filtered_left_words = [
        item
        for item in words
        if (
            item["bbox"]["x0"]
            + item["bbox"]["x1"]
        ) / 2.0 < mid
    ]

    filtered_right_words = [
        item
        for item in words
        if (
            item["bbox"]["x0"]
            + item["bbox"]["x1"]
        ) / 2.0 >= mid
    ]

    filtered_left_chars = len(
        clean_text(
            " ".join(
                item["text"]
                for item in filtered_left_words
            )
        )
    )

    filtered_right_chars = len(
        clean_text(
            " ".join(
                item["text"]
                for item in filtered_right_words
            )
        )
    )

    # 典型场景：
    # Stage4 block 因旋转水印 bbox 被拉宽成 span，
    # 去掉 watermark 对 gutter 的影响后，正文实际上只落在一侧。
    noise_inflated_side = None

    if ignored_noise_word_count > 0:
        if (
            filtered_left_words
            and not filtered_right_words
            and filtered_left_chars
            >= READING_NOISE_INFLATED_MIN_TEXT_CHARS
        ):
            noise_inflated_side = "left"

        elif (
            filtered_right_words
            and not filtered_left_words
            and filtered_right_chars
            >= READING_NOISE_INFLATED_MIN_TEXT_CHARS
        ):
            noise_inflated_side = "right"

    min_gutter = max(
        READING_GUTTER_MIN_ABS,
        page_width
        * READING_GUTTER_MIN_RATIO,
    )

    bilateral_lines = 0
    gutter_lines = 0
    crossing_lines = 0
    gutter_values: list[float] = []

    line_diagnostics: list[
        dict[str, Any]
    ] = []

    for line in group_words_into_gutter_lines(
        words
    ):
        ordered = sorted(
            line,
            key=lambda item:
                item["bbox"]["x0"],
        )

        left = [
            item
            for item in ordered
            if (
                item["bbox"]["x0"]
                + item["bbox"]["x1"]
            ) / 2.0 < mid
        ]

        right = [
            item
            for item in ordered
            if (
                item["bbox"]["x0"]
                + item["bbox"]["x1"]
            ) / 2.0 >= mid
        ]

        if not left or not right:
            continue

        bilateral_lines += 1

        crossing = [
            item
            for item in ordered
            if (
                item["bbox"]["x0"]
                < mid
                < item["bbox"]["x1"]
            )
        ]

        left_end = max(
            item["bbox"]["x1"]
            for item in left
        )

        right_start = min(
            item["bbox"]["x0"]
            for item in right
        )

        gap = (
            right_start
            - left_end
        )

        if crossing:
            crossing_lines += 1

        is_gutter = (
            not crossing
            and gap >= min_gutter
        )

        if is_gutter:
            gutter_lines += 1
            gutter_values.append(
                gap
            )

        line_diagnostics.append(
            {
                "top":
                    round(
                        min(
                            item["bbox"]["top"]
                            for item in ordered
                        ),
                        3,
                    ),
                "gap":
                    round(
                        gap,
                        3,
                    ),
                "crossing_word_count":
                    len(crossing),
                "gutter_evidence":
                    is_gutter,
            }
        )

    evidence_ratio = (
        gutter_lines
        / bilateral_lines
        if bilateral_lines > 0
        else 0.0
    )

    if noise_inflated_side is not None:
        return {
            "classification":
                f"noise_inflated_{noise_inflated_side}",
            "reason":
                "watermark_inflated_span_bbox_but_filtered_text_is_single_column",
            "word_count":
                len(words),
            "original_word_count":
                len(original_words),
            "ignored_noise_word_count":
                ignored_noise_word_count,
            "filtered_left_word_count":
                len(filtered_left_words),
            "filtered_right_word_count":
                len(filtered_right_words),
            "filtered_left_chars":
                filtered_left_chars,
            "filtered_right_chars":
                filtered_right_chars,
            "bilateral_line_count":
                bilateral_lines,
            "gutter_evidence_line_count":
                gutter_lines,
            "crossing_line_count":
                crossing_lines,
            "gutter_evidence_ratio":
                round(
                    evidence_ratio,
                    4,
                ),
            "line_diagnostics":
                line_diagnostics,
            "_words":
                words,
            "_original_words":
                original_words,
        }

    strong_single_line = False
    strong_single_line_gap = None
    strong_single_line_left_chars = 0
    strong_single_line_right_chars = 0

    if (
        bilateral_lines == 1
        and gutter_lines == 1
        and crossing_lines == 0
    ):
        diagnostic = next(
            (
                item
                for item in line_diagnostics
                if item.get(
                    "gutter_evidence"
                )
            ),
            None,
        )

        if diagnostic is not None:
            strong_single_line_gap = float(
                diagnostic.get(
                    "gap",
                    0.0,
                )
                or 0.0
            )

        ordered_words = sorted(
            words,
            key=lambda item: (
                item["bbox"]["top"],
                item["bbox"]["x0"],
            ),
        )

        left_text = " ".join(
            item["text"]
            for item in ordered_words
            if (
                item["bbox"]["x0"]
                + item["bbox"]["x1"]
            ) / 2.0 < mid
        )

        right_text = " ".join(
            item["text"]
            for item in ordered_words
            if (
                item["bbox"]["x0"]
                + item["bbox"]["x1"]
            ) / 2.0 >= mid
        )

        strong_single_line_left_chars = len(
            clean_text(left_text)
        )
        strong_single_line_right_chars = len(
            clean_text(right_text)
        )

        single_line_min_gutter = max(
            READING_SINGLE_LINE_GUTTER_MIN_ABS,
            page_width
            * READING_SINGLE_LINE_GUTTER_MIN_RATIO,
        )

        single_line_min_chars = (
            READING_NOISE_ASSISTED_SINGLE_LINE_MIN_CHARS_PER_SIDE
            if ignored_noise_word_count > 0
            else READING_SINGLE_LINE_MIN_TEXT_CHARS_PER_SIDE
        )

        strong_single_line = (
            strong_single_line_gap
            is not None
            and strong_single_line_gap
            >= single_line_min_gutter
            and strong_single_line_left_chars
            >= single_line_min_chars
            and strong_single_line_right_chars
            >= single_line_min_chars
        )

    if (
        gutter_lines
        >= READING_GUTTER_MIN_EVIDENCE_LINES
        and evidence_ratio
        >= READING_GUTTER_MIN_EVIDENCE_RATIO
    ):
        classification = (
            "merged_two_column"
        )
        reason = (
            "multiple_lines_show_left_right_clusters_with_center_gutter"
        )

    elif strong_single_line:
        classification = (
            "merged_two_column"
        )
        reason = (
            "strong_single_line_center_gutter"
        )

    elif (
        bilateral_lines > 0
        and crossing_lines > 0
    ):
        classification = (
            "true_span"
        )
        reason = (
            "words_naturally_cross_page_midline"
        )

    else:
        classification = (
            "insufficient"
        )
        reason = (
            "not_enough_center_gutter_evidence"
        )

    return {
        "classification":
            classification,
        "reason":
            reason,
        "word_count":
            len(words),
        "original_word_count":
            len(original_words),
        "ignored_noise_word_count":
            ignored_noise_word_count,
        "filtered_left_word_count":
            len(filtered_left_words),
        "filtered_right_word_count":
            len(filtered_right_words),
        "filtered_left_chars":
            filtered_left_chars,
        "filtered_right_chars":
            filtered_right_chars,
        "bilateral_line_count":
            bilateral_lines,
        "gutter_evidence_line_count":
            gutter_lines,
        "crossing_line_count":
            crossing_lines,
        "gutter_evidence_ratio":
            round(
                evidence_ratio,
                4,
            ),
        "min_required_gutter":
            round(
                min_gutter,
                3,
            ),
        "median_gutter":
            (
                round(
                    sorted(
                        gutter_values
                    )[
                        len(gutter_values)
                        // 2
                    ],
                    3,
                )
                if gutter_values
                else None
            ),
        "strong_single_line":
            strong_single_line,
        "strong_single_line_gap":
            (
                round(
                    strong_single_line_gap,
                    3,
                )
                if strong_single_line_gap
                is not None
                else None
            ),
        "strong_single_line_left_chars":
            strong_single_line_left_chars,
        "strong_single_line_right_chars":
            strong_single_line_right_chars,
        "line_diagnostics":
            line_diagnostics,
        "_words":
            words,
        "_original_words":
            original_words,
    }


def build_logical_text_fragment(
    source_block: dict[str, Any],
    words: list[dict[str, Any]],
    side: str,
) -> dict[str, Any] | None:
    if not words:
        return None

    bbox = bbox_union(
        [
            item["bbox"]
            for item in words
        ]
    )

    if bbox is None:
        return None

    source_block_id = str(
        source_block.get(
            "block_id",
            "unknown",
        )
    )

    suffix = (
        "L"
        if side == "left"
        else "R"
    )

    fragment = dict(
        source_block
    )

    fragment["block_id"] = (
        f"{source_block_id}__{suffix}"
    )
    fragment["source_block_id"] = (
        source_block_id
    )
    fragment["logical_fragment"] = (
        side
    )
    fragment["fragment_only"] = True
    fragment["column"] = side
    fragment["bbox"] = bbox
    fragment["text"] = (
        words_to_fragment_text(
            words
        )
    )
    fragment["source_word_indices"] = [
        int(item["source_word_index"])
        for item in words
        if isinstance(
            item.get("source_word_index"),
            int,
        )
    ]

    return fragment


def split_merged_two_column_block(
    block: dict[str, Any],
    evidence: dict[str, Any],
    page_width: float,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
]:
    # 分类阶段允许过滤 watermark word；
    # 但 fragment 内容必须回到原始 Stage1 words，避免把
    # "applications式due" 这类混合 word 整体丢掉。
    words = evidence.get(
        "_original_words",
        [],
    )

    if (
        not isinstance(words, list)
        or not words
        or page_width <= 0
    ):
        return [], None

    mid = page_width / 2.0

    left_words: list[
        dict[str, Any]
    ] = []

    right_words: list[
        dict[str, Any]
    ] = []

    for word in words:
        bbox = word["bbox"]

        center_x = (
            bbox["x0"]
            + bbox["x1"]
        ) / 2.0

        if center_x < mid:
            left_words.append(
                word
            )
        else:
            right_words.append(
                word
            )

    left_fragment = (
        build_logical_text_fragment(
            block,
            left_words,
            "left",
        )
    )

    right_fragment = (
        build_logical_text_fragment(
            block,
            right_words,
            "right",
        )
    )

    if (
        left_fragment is None
        or right_fragment is None
    ):
        return [], None

    detail = {
        "source_block_id":
            block.get(
                "block_id"
            ),
        "classification":
            "merged_two_column",
        "content_word_source":
            "original_stage1_words",
        "classification_word_count":
            evidence.get(
                "word_count"
            ),
        "original_word_count":
            evidence.get(
                "original_word_count"
            ),
        "ignored_noise_word_count":
            evidence.get(
                "ignored_noise_word_count"
            ),
        "left_fragment_id":
            left_fragment[
                "block_id"
            ],
        "right_fragment_id":
            right_fragment[
                "block_id"
            ],
        "left_word_count":
            len(left_words),
        "right_word_count":
            len(right_words),
        "bilateral_line_count":
            evidence.get(
                "bilateral_line_count"
            ),
        "gutter_evidence_line_count":
            evidence.get(
                "gutter_evidence_line_count"
            ),
        "gutter_evidence_ratio":
            evidence.get(
                "gutter_evidence_ratio"
            ),
        "median_gutter":
            evidence.get(
                "median_gutter"
            ),
    }

    return [
        left_fragment,
        right_fragment,
    ], detail



def build_stage62_auto_remove_occurrences(
    noise_result: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    """
    收集 Stage6.1 已明确判定为 auto_remove 的 occurrence。

    Stage6.2 只把“独立成块的已确认噪声”从逻辑 reading order 中跳过，
    不删除 Stage1 / Stage4 原始证据。
    """
    result: dict[
        int,
        list[dict[str, Any]],
    ] = defaultdict(list)

    for candidate in noise_result.get(
        "noise_candidates",
        [],
    ):
        if not isinstance(candidate, dict):
            continue

        if candidate.get("action") != "auto_remove":
            continue

        candidate_type = str(
            candidate.get(
                "type",
                "",
            )
        )

        # 当前 Stage6.1 中只有这两类具备足够强的自动移除证据。
        if candidate_type not in {
            "page_number",
            "watermark",
        }:
            continue

        for occurrence in candidate.get(
            "occurrences",
            [],
        ):
            if not isinstance(occurrence, dict):
                continue

            page_number = occurrence.get(
                "page_number"
            )
            bbox = normalize_bbox(
                occurrence.get("bbox")
            )

            if (
                not isinstance(page_number, int)
                or bbox is None
            ):
                continue

            result[page_number].append(
                {
                    "candidate_id":
                        candidate.get(
                            "candidate_id"
                        ),
                    "candidate_type":
                        candidate_type,
                    "candidate_subtype":
                        candidate.get(
                            "subtype"
                        ),
                    "candidate_text":
                        candidate.get(
                            "text"
                        ),
                    "occurrence_text":
                        occurrence.get(
                            "text"
                        ),
                    "bbox":
                        bbox,
                }
            )

    return dict(result)


def compact_noise_text(
    value: Any,
) -> str:
    return re.sub(
        r"\s+",
        "",
        clean_text(value),
    )


def bbox_center_inside(
    inner: dict[str, float],
    outer: dict[str, float],
    tolerance: float = 2.0,
) -> bool:
    center_x = (
        inner["x0"]
        + inner["x1"]
    ) / 2.0

    center_y = (
        inner["top"]
        + inner["bottom"]
    ) / 2.0

    return point_inside_bbox(
        center_x,
        center_y,
        outer,
        tolerance,
    )



def original_block_bbox(
    block: dict[str, Any],
) -> dict[str, float] | None:
    """
    Stage4 为越界几何保留 original_bbox。
    boundary footer 判断优先使用 original_bbox，避免 clipped bbox 把越界证据抹掉。
    """
    original = normalize_bbox(
        block.get(
            "original_bbox"
        )
    )

    if original is not None:
        return original

    return block_bbox(
        block
    )


def recursive_contains_exact_string(
    value: Any,
    target: str,
) -> bool:
    if isinstance(value, str):
        return value == target

    if isinstance(value, dict):
        return any(
            recursive_contains_exact_string(
                item,
                target,
            )
            for item in value.values()
        )

    if isinstance(value, list):
        return any(
            recursive_contains_exact_string(
                item,
                target,
            )
            for item in value
        )

    return False


def block_is_stage4_cross_page_table_candidate(
    page: dict[str, Any],
    block: dict[str, Any],
) -> bool:
    """
    Stage6.2 不重新判断跨页表格。
    如果 Stage4 的 cross_page_table_candidates 中明确引用当前 block_id，
    就保守保留，不允许 boundary-footer 自动排除。
    """
    block_id = block.get(
        "block_id"
    )

    if not isinstance(
        block_id,
        str,
    ) or not block_id:
        return False

    candidates = page.get(
        "cross_page_table_candidates"
    )

    if candidates is None:
        return False

    return recursive_contains_exact_string(
        candidates,
        block_id,
    )


def boundary_footer_table_match(
    page: dict[str, Any],
    block: dict[str, Any],
) -> dict[str, Any] | None:
    """
    识别“物理结构像 table、语义用途却是页脚装饰条”的强几何模式。

    所有核心条件必须同时满足：
      1) table block
      2) 位于页面极底部
      3) 很薄
      4) 几乎横跨整页
      5) original bbox 实际越过页面底边
      6) 极少行
      7) Stage4 未明确标成跨页 table candidate

    水平越界不是绝对必需；若没有水平越界，则要求接近真正整页宽。
    """
    if block.get(
        "block_type"
    ) != "table":
        return None

    try:
        page_width = float(
            page.get(
                "width",
                0.0,
            )
            or 0.0
        )

        page_height = float(
            page.get(
                "height",
                0.0,
            )
            or 0.0
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        page_width <= 0
        or page_height <= 0
    ):
        return None

    bbox = original_block_bbox(
        block
    )

    if bbox is None:
        return None

    table_width = max(
        0.0,
        bbox["x1"] - bbox["x0"],
    )

    table_height = max(
        0.0,
        bbox["bottom"] - bbox["top"],
    )

    width_ratio = (
        table_width
        / page_width
    )

    height_ratio = (
        table_height
        / page_height
    )

    top_ratio = (
        bbox["top"]
        / page_height
    )

    bottom_overflow = (
        bbox["bottom"]
        - page_height
    )

    left_overflow = max(
        0.0,
        -bbox["x0"],
    )

    right_overflow = max(
        0.0,
        bbox["x1"] - page_width,
    )

    horizontal_overflow = (
        left_overflow
        >= BOUNDARY_FOOTER_HORIZONTAL_OVERFLOW_TOL
        or right_overflow
        >= BOUNDARY_FOOTER_HORIZONTAL_OVERFLOW_TOL
    )

    try:
        row_count = int(
            block.get(
                "row_count",
                0,
            )
            or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    # 行数拿不到就不自动删，宁可保留。
    if row_count <= 0:
        return None

    if block_is_stage4_cross_page_table_candidate(
        page,
        block,
    ):
        return None

    near_bottom = (
        top_ratio
        >= BOUNDARY_FOOTER_TOP_MIN_RATIO
    )

    thin = (
        height_ratio
        <= BOUNDARY_FOOTER_MAX_HEIGHT_RATIO
    )

    near_full_width = (
        width_ratio
        >= BOUNDARY_FOOTER_MIN_WIDTH_RATIO
    )

    bottom_boundary_abnormal = (
        bottom_overflow
        >= BOUNDARY_FOOTER_MIN_BOTTOM_OVERFLOW
    )

    few_rows = (
        row_count
        <= BOUNDARY_FOOTER_MAX_ROWS
    )

    # 若没有左右越界，则必须更接近整页宽，避免误伤普通底部正文表。
    strong_horizontal_evidence = (
        horizontal_overflow
        or width_ratio
        >= BOUNDARY_FOOTER_STRONG_WIDTH_RATIO
    )

    if not (
        near_bottom
        and thin
        and near_full_width
        and bottom_boundary_abnormal
        and few_rows
        and strong_horizontal_evidence
    ):
        return None

    return {
        "reason":
            "boundary_footer_table",
        "classification":
            "boundary_footer_table",
        "action":
            "auto_remove_from_logical_flow",
        "evidence": {
            "top_ratio":
                round(
                    top_ratio,
                    4,
                ),
            "height_ratio":
                round(
                    height_ratio,
                    4,
                ),
            "width_ratio":
                round(
                    width_ratio,
                    4,
                ),
            "bottom_overflow":
                round(
                    bottom_overflow,
                    3,
                ),
            "left_overflow":
                round(
                    left_overflow,
                    3,
                ),
            "right_overflow":
                round(
                    right_overflow,
                    3,
                ),
            "row_count":
                row_count,
            "near_bottom":
                near_bottom,
            "thin":
                thin,
            "near_full_width":
                near_full_width,
            "bottom_boundary_abnormal":
                bottom_boundary_abnormal,
            "few_rows":
                few_rows,
            "horizontal_overflow":
                horizontal_overflow,
            "stage4_cross_page_candidate":
                False,
        },
    }


def standalone_auto_remove_block_match(
    block: dict[str, Any],
    raw_page: dict[str, Any],
    auto_remove_occurrences: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    只有“独立成块”的已确认噪声才从逻辑 reading order 排除。

    安全约束：
    - 仅处理 text block；
    - page number 必须与 occurrence 文本整体一致；
    - watermark 必须整块只由已确认的 watermark token 组成；
    - 混合正文 + watermark 的 block 不会被整块排除。
    """
    if block.get("block_type") != "text":
        return None

    bbox = block_bbox(block)

    if bbox is None:
        return None

    relevant = [
        item
        for item in auto_remove_occurrences
        if (
            isinstance(
                item.get("bbox"),
                dict,
            )
            and (
                bbox_center_inside(
                    item["bbox"],
                    bbox,
                    tolerance=2.0,
                )
                or bbox_center_inside(
                    bbox,
                    item["bbox"],
                    tolerance=2.0,
                )
            )
        )
    ]

    if not relevant:
        return None

    block_text = clean_text(
        block.get("text")
    )

    if not block_text:
        # 若 Stage4 没有直接保存 text，则退回 Stage1 words。
        words = words_inside_block(
            raw_page,
            bbox,
            None,
        )

        block_text = clean_text(
            " ".join(
                item["text"]
                for item in words
            )
        )

    if not block_text:
        return None

    # --------------------------------------------------------------
    # 1. 独立页码：整块文本必须与 Stage6.1 occurrence 一致。
    #    这样不会误删：
    #    "48/65 This article is copyrighted ..."
    # --------------------------------------------------------------
    for item in relevant:
        if item.get(
            "candidate_type"
        ) != "page_number":
            continue

        occurrence_text = clean_text(
            item.get(
                "occurrence_text"
            )
        )

        if (
            occurrence_text
            and compact_noise_text(
                block_text
            )
            == compact_noise_text(
                occurrence_text
            )
        ):
            return {
                "reason":
                    "standalone_auto_remove_page_number",
                "candidate_ids": [
                    item.get(
                        "candidate_id"
                    )
                ],
                "candidate_types": [
                    "page_number"
                ],
                "matched_texts": [
                    occurrence_text
                ],
            }

    # --------------------------------------------------------------
    # 2. 独立水印块：
    #    block 的每个空格分隔 token 都必须来自当前页已确认的
    #    watermark occurrence；混有普通正文的 block 不会整块排除。
    #    判定依赖 occurrence 证据，不依赖任何固定水印字符值。
    # --------------------------------------------------------------
    watermark_items = [
        item
        for item in relevant
        if item.get(
            "candidate_type"
        ) == "watermark"
    ]

    watermark_texts = {
        clean_text(
            item.get(
                "occurrence_text"
            )
            or item.get(
                "candidate_text"
            )
        )
        for item in watermark_items
        if clean_text(
            item.get(
                "occurrence_text"
            )
            or item.get(
                "candidate_text"
            )
        )
    }

    block_tokens = [
        token
        for token in block_text.split(" ")
        if token
    ]

    if (
        watermark_texts
        and block_tokens
        and all(
            token in watermark_texts
            for token in block_tokens
        )
    ):
        matched_ids = sorted(
            {
                str(
                    item.get(
                        "candidate_id"
                    )
                )
                for item in watermark_items
                if clean_text(
                    item.get(
                        "occurrence_text"
                    )
                    or item.get(
                        "candidate_text"
                    )
                )
                in set(block_tokens)
            }
        )

        return {
            "reason":
                "standalone_auto_remove_watermark",
            "candidate_ids":
                matched_ids,
            "candidate_types": [
                "watermark"
            ],
            "matched_texts":
                sorted(
                    set(block_tokens)
                ),
        }

    return None


def prepare_reading_items(
    page: dict[str, Any],
    raw_page: dict[str, Any],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
    auto_remove_occurrences: list[dict[str, Any]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    width = float(
        page.get(
            "width",
            0.0,
        )
        or 0.0
    )

    profile = page.get(
        "page_profile",
        {},
    )

    if not isinstance(
        profile,
        dict,
    ):
        profile = {}

    multi_column = bool(
        profile.get(
            "multi_column",
            False,
        )
    )

    valid: list[
        dict[str, Any]
    ] = []

    invalid: list[
        dict[str, Any]
    ] = []

    split_details: list[
        dict[str, Any]
    ] = []

    wide_text_diagnostics: list[
        dict[str, Any]
    ] = []

    excluded_noise_blocks: list[
        dict[str, Any]
    ] = []

    effective_auto_remove_occurrences = (
        auto_remove_occurrences
        if isinstance(
            auto_remove_occurrences,
            list,
        )
        else []
    )

    for original_index, block in enumerate(
        structure_blocks(page)
    ):
        bbox = block_bbox(
            block
        )

        if bbox is None:
            invalid.append(
                {
                    "block_id":
                        block.get(
                            "block_id"
                        ),
                    "block_type":
                        block.get(
                            "block_type"
                        ),
                    "reason":
                        "invalid_or_missing_bbox",
                    "original_index":
                        original_index,
                }
            )
            continue

        boundary_table_match = (
            boundary_footer_table_match(
                page,
                block,
            )
        )

        if boundary_table_match is not None:
            excluded_noise_blocks.append(
                {
                    "block_id":
                        block.get(
                            "block_id"
                        ),
                    "block_type":
                        block.get(
                            "block_type"
                        ),
                    "bbox":
                        bbox,
                    "original_bbox":
                        original_block_bbox(
                            block
                        ),
                    "text_preview":
                        None,
                    "reason":
                        boundary_table_match.get(
                            "reason"
                        ),
                    "classification":
                        boundary_table_match.get(
                            "classification"
                        ),
                    "action":
                        boundary_table_match.get(
                            "action"
                        ),
                    "candidate_ids":
                        [],
                    "candidate_types": [
                        "boundary_footer_table"
                    ],
                    "matched_texts":
                        [],
                    "evidence":
                        boundary_table_match.get(
                            "evidence",
                            {},
                        ),
                    "original_index":
                        original_index,
                }
            )

            continue

        noise_match = (
            standalone_auto_remove_block_match(
                block,
                raw_page,
                effective_auto_remove_occurrences,
            )
        )

        if noise_match is not None:
            excluded_noise_blocks.append(
                {
                    "block_id":
                        block.get(
                            "block_id"
                        ),
                    "block_type":
                        block.get(
                            "block_type"
                        ),
                    "bbox":
                        bbox,
                    "text_preview":
                        clean_text(
                            block.get("text")
                        )[:160]
                        if clean_text(
                            block.get("text")
                        )
                        else None,
                    "reason":
                        noise_match.get(
                            "reason"
                        ),
                    "classification":
                        noise_match.get(
                            "reason"
                        ),
                    "action":
                        "auto_remove_from_logical_flow",
                    "candidate_ids":
                        noise_match.get(
                            "candidate_ids",
                            [],
                        ),
                    "candidate_types":
                        noise_match.get(
                            "candidate_types",
                            [],
                        ),
                    "matched_texts":
                        noise_match.get(
                            "matched_texts",
                            [],
                        ),
                    "evidence":
                        {},
                    "original_index":
                        original_index,
                }
            )

            continue

        role = reading_column_role(
            block=block,
            bbox=bbox,
            page_width=width,
            multi_column=multi_column,
        )

        # 只修这一种情况：
        # 多栏页 + text + 原本被几何规则判成 span。
        if (
            multi_column
            and role == "span"
            and block.get(
                "block_type"
            ) == "text"
        ):
            evidence = (
                classify_wide_text_block(
                    raw_page,
                    bbox,
                    width,
                    ignored_noise_regions,
                )
            )

            diagnostic = {
                key: value
                for key, value
                in evidence.items()
                if key != "_words"
            }

            diagnostic[
                "source_block_id"
            ] = block.get(
                "block_id"
            )

            wide_text_diagnostics.append(
                diagnostic
            )

            classification = str(
                evidence.get(
                    "classification",
                    "",
                )
            )

            if classification in {
                "noise_inflated_left",
                "noise_inflated_right",
            }:
                corrected_role = (
                    "left"
                    if classification.endswith(
                        "_left"
                    )
                    else "right"
                )

                valid.append(
                    {
                        "block":
                            block,
                        "bbox":
                            bbox,
                        "role":
                            corrected_role,
                        "original_index":
                            original_index,
                        "fragment_rank":
                            0,
                        "source_block_id":
                            block.get(
                                "block_id"
                            ),
                        "logical_fragment":
                            None,
                        "role_override_reason":
                            classification,
                    }
                )

                continue

            if (
                classification
                == "merged_two_column"
            ):
                fragments, detail = (
                    split_merged_two_column_block(
                        block,
                        evidence,
                        width,
                    )
                )

                if (
                    len(fragments) == 2
                    and detail
                    is not None
                ):
                    split_details.append(
                        detail
                    )

                    for (
                        fragment_rank,
                        fragment,
                    ) in enumerate(
                        fragments
                    ):
                        fragment_bbox = (
                            block_bbox(
                                fragment
                            )
                        )

                        if fragment_bbox is None:
                            continue

                        valid.append(
                            {
                                "block":
                                    fragment,
                                "bbox":
                                    fragment_bbox,
                                "role":
                                    fragment[
                                        "logical_fragment"
                                    ],
                                "original_index":
                                    original_index,
                                "fragment_rank":
                                    fragment_rank,
                                "source_block_id":
                                    block.get(
                                        "block_id"
                                    ),
                                "logical_fragment":
                                    fragment[
                                        "logical_fragment"
                                    ],
                                "role_override_reason":
                                    None,
                            }
                        )

                    continue

        valid.append(
            {
                "block": block,
                "bbox": bbox,
                "role": role,
                "original_index":
                    original_index,
                "fragment_rank": 0,
                "source_block_id":
                    block.get(
                        "block_id"
                    ),
                "logical_fragment":
                    None,
                "role_override_reason":
                    None,
            }
        )

    return (
        valid,
        invalid,
        split_details,
        wide_text_diagnostics,
        excluded_noise_blocks,
    )



def median_number(
    values: list[float],
) -> float | None:
    if not values:
        return None

    ordered = sorted(
        float(value)
        for value in values
    )

    size = len(ordered)
    middle = size // 2

    if size % 2:
        return ordered[middle]

    return (
        ordered[middle - 1]
        + ordered[middle]
    ) / 2.0


def raw_char_bbox(
    char: dict[str, Any],
) -> dict[str, float] | None:
    return normalize_bbox(
        {
            "x0": char.get("x0"),
            "top": char.get("top"),
            "x1": char.get("x1"),
            "bottom": char.get("bottom"),
        }
    )


def char_inside_noise_region(
    char_bbox_value: dict[str, float],
    regions: list[dict[str, Any]],
) -> bool:
    center_x = (
        char_bbox_value["x0"]
        + char_bbox_value["x1"]
    ) / 2.0

    center_y = (
        char_bbox_value["top"]
        + char_bbox_value["bottom"]
    ) / 2.0

    for region in regions:
        bbox = region.get("bbox")

        if not isinstance(bbox, dict):
            continue

        if point_inside_bbox(
            center_x,
            center_y,
            bbox,
            tolerance=1.0,
        ):
            return True

    return False


def item_font_sizes(
    raw_page: dict[str, Any],
    item: dict[str, Any],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
) -> list[float]:
    bbox = item.get("bbox")

    if not isinstance(bbox, dict):
        return []

    result: list[float] = []

    for char in raw_page.get(
        "chars",
        [],
    ):
        if not isinstance(char, dict):
            continue

        value = str(
            char.get("text", "")
        )

        if not value.strip():
            continue

        char_bbox_value = raw_char_bbox(
            char
        )

        if char_bbox_value is None:
            continue

        center_x = (
            char_bbox_value["x0"]
            + char_bbox_value["x1"]
        ) / 2.0

        center_y = (
            char_bbox_value["top"]
            + char_bbox_value["bottom"]
        ) / 2.0

        if not point_inside_bbox(
            center_x,
            center_y,
            bbox,
            tolerance=1.0,
        ):
            continue

        if (
            ignored_noise_regions
            and char_inside_noise_region(
                char_bbox_value,
                ignored_noise_regions,
            )
        ):
            continue

        size = char.get("size")

        if not finite_number(size):
            continue

        result.append(
            float(size)
        )

    return result


def item_font_stat(
    raw_page: dict[str, Any],
    item: dict[str, Any],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sizes = item_font_sizes(
        raw_page,
        item,
        ignored_noise_regions,
    )

    return {
        "median_font_size":
            (
                round(
                    median_number(sizes),
                    4,
                )
                if sizes
                else None
            ),
        "font_char_count":
            len(sizes),
        "_font_sizes":
            sizes,
    }


def vertical_center(
    bbox: dict[str, float],
) -> float:
    return (
        bbox["top"]
        + bbox["bottom"]
    ) / 2.0


def vertically_close(
    first: dict[str, float],
    second: dict[str, float],
    tolerance: float,
) -> bool:
    return abs(
        vertical_center(first)
        - vertical_center(second)
    ) <= tolerance



def bbox_area(
    bbox: dict[str, float],
) -> float:
    return max(
        0.0,
        bbox["x1"] - bbox["x0"],
    ) * max(
        0.0,
        bbox["bottom"] - bbox["top"],
    )


def bbox_center(
    bbox: dict[str, float],
) -> tuple[float, float]:
    return (
        (
            bbox["x0"]
            + bbox["x1"]
        ) / 2.0,
        (
            bbox["top"]
            + bbox["bottom"]
        ) / 2.0,
    )


def point_in_bbox(
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


def item_is_inside_figure_region(
    item: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    保护图内文字。

    只使用 Stage4 已有二维几何：
    - image
    - vector

    若 text item 的中心落在图区域内，
    或 text bbox 有足够比例被图区域覆盖，
    则它不能被 bottom ancillary 规则搬到正文之后。

    不使用任何具体文字、页码、期刊名或样本 block_id。
    """
    if (
        item["block"].get(
            "block_type"
        )
        != "text"
    ):
        return None

    text_bbox = item.get(
        "bbox"
    )

    if not isinstance(
        text_bbox,
        dict,
    ):
        return None

    text_area = bbox_area(
        text_bbox
    )

    center_x, center_y = bbox_center(
        text_bbox
    )

    for other in items:
        if other is item:
            continue

        other_type = other[
            "block"
        ].get(
            "block_type"
        )

        if other_type not in {
            "image",
            "vector",
        }:
            continue

        figure_bbox = other.get(
            "bbox"
        )

        if not isinstance(
            figure_bbox,
            dict,
        ):
            continue

        center_inside = (
            BOTTOM_FLOW_FIGURE_PROTECT_CENTER_INSIDE
            and point_in_bbox(
                center_x,
                center_y,
                figure_bbox,
                tolerance=1.0,
            )
        )

        overlap_area = (
            bbox_intersection_area(
                text_bbox,
                figure_bbox,
            )
        )

        coverage = (
            overlap_area
            / text_area
            if text_area > 0
            else 0.0
        )

        if (
            center_inside
            or coverage
            >= BOTTOM_FLOW_FIGURE_PROTECT_MIN_TEXT_COVERAGE
        ):
            return {
                "protected_by":
                    other[
                        "block"
                    ].get(
                        "block_id"
                    ),
                "protected_type":
                    other_type,
                "text_coverage":
                    round(
                        coverage,
                        4,
                    ),
                "center_inside":
                    center_inside,
            }

    return None


def classify_bottom_flows(
    page: dict[str, Any],
    raw_page: dict[str, Any],
    items: list[dict[str, Any]],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """
    返回：
      active_items:
          仍参与 reading order 的 item（main + ancillary）

      ancillary_items:
          不删除，只在主正文之后输出

      footer_excluded:
          强证据确认的极底部 footer text，从 logical flow 排除

      diagnostics:
          字号参考与判定证据

    仅在多栏页调用。
    """
    try:
        page_width = float(
            page.get("width", 0.0)
            or 0.0
        )

        page_height = float(
            page.get("height", 0.0)
            or 0.0
        )
    except (
        TypeError,
        ValueError,
    ):
        return (
            items,
            [],
            [],
            {
                "status": "skipped",
                "reason": "invalid_page_size",
            },
        )

    if (
        page_width <= 0
        or page_height <= 0
    ):
        return (
            items,
            [],
            [],
            {
                "status": "skipped",
                "reason": "invalid_page_size",
            },
        )

    # --------------------------------------------------------------
    # 1. 给 text item 计算局部字号证据。
    # --------------------------------------------------------------
    for item in items:
        item.setdefault(
            "flow_role",
            "main",
        )

        if (
            item["block"].get(
                "block_type"
            )
            != "text"
        ):
            item[
                "median_font_size"
            ] = None
            item[
                "font_char_count"
            ] = 0
            continue

        stat = item_font_stat(
            raw_page,
            item,
            ignored_noise_regions,
        )

        item[
            "median_font_size"
        ] = stat[
            "median_font_size"
        ]

        item[
            "font_char_count"
        ] = stat[
            "font_char_count"
        ]

        item[
            "_font_sizes"
        ] = stat[
            "_font_sizes"
        ]

    # --------------------------------------------------------------
    # 2. 主栏字号参考。
    # 只使用页面前 65% 内的 left/right text，避免页底脚注反向污染参考。
    # --------------------------------------------------------------
    column_refs: dict[
        str,
        float | None,
    ] = {
        "left": None,
        "right": None,
    }

    for side in (
        "left",
        "right",
    ):
        pooled: list[float] = []

        for item in items:
            if (
                item.get("role") != side
                or item["block"].get(
                    "block_type"
                )
                != "text"
            ):
                continue

            bbox = item["bbox"]

            if (
                bbox["top"]
                / page_height
                >
                BOTTOM_FLOW_MAIN_REF_MAX_TOP_RATIO
            ):
                continue

            pooled.extend(
                item.get(
                    "_font_sizes",
                    [],
                )
            )

        column_refs[side] = (
            median_number(
                pooled
            )
        )

    valid_refs = [
        value
        for value in column_refs.values()
        if (
            value is not None
            and value > 0
        )
    ]

    global_ref = (
        median_number(
            valid_refs
        )
        if valid_refs
        else None
    )

    # 无可靠主文字号参考时，保守不做 bottom-flow 自动判定。
    if (
        global_ref is None
        or global_ref <= 0
    ):
        for item in items:
            item.pop(
                "_font_sizes",
                None,
            )

        return (
            items,
            [],
            [],
            {
                "status": "skipped",
                "reason": "no_reliable_main_font_reference",
                "column_font_reference":
                    column_refs,
            },
        )

    # --------------------------------------------------------------
    # 3. 先识别极底部跨栏 footer text seed。
    # --------------------------------------------------------------
    footer_seed_ids: set[
        str
    ] = set()

    for item in items:
        block = item["block"]

        if (
            block.get("block_type")
            != "text"
            or item.get("role")
            != "span"
        ):
            continue

        bbox = item["bbox"]

        width_ratio = (
            bbox["x1"]
            - bbox["x0"]
        ) / page_width

        height_ratio = (
            bbox["bottom"]
            - bbox["top"]
        ) / page_height

        top_ratio = (
            bbox["top"]
            / page_height
        )

        bottom_ratio = (
            bbox["bottom"]
            / page_height
        )

        font_size = item.get(
            "median_font_size"
        )

        char_count = int(
            item.get(
                "font_char_count",
                0,
            )
            or 0
        )

        if (
            font_size is None
            or char_count
            < BOUNDARY_FOOTER_TEXT_MIN_CHARS
        ):
            continue

        if (
            top_ratio
            >= BOUNDARY_FOOTER_TEXT_MIN_TOP_RATIO
            and bottom_ratio
            >= BOUNDARY_FOOTER_TEXT_MIN_BOTTOM_RATIO
            and height_ratio
            <= BOUNDARY_FOOTER_TEXT_MAX_HEIGHT_RATIO
            and width_ratio
            >= BOUNDARY_FOOTER_TEXT_MIN_WIDTH_RATIO
            and font_size
            <= global_ref
            * BOUNDARY_FOOTER_TEXT_MAX_FONT_RATIO
        ):
            block_id = str(
                block.get(
                    "block_id"
                )
            )

            footer_seed_ids.add(
                block_id
            )

    # --------------------------------------------------------------
    # 4. 同一极底部 band 的小字号 companion 一并视为 footer。
    #    例如一条 footer 被 Stage4 切成 span + 左/右小块。
    # --------------------------------------------------------------
    footer_ids = set(
        footer_seed_ids
    )

    footer_seed_items = [
        item
        for item in items
        if str(
            item["block"].get(
                "block_id"
            )
        )
        in footer_seed_ids
    ]

    if footer_seed_items:
        y_tolerance = (
            page_height
            * BOUNDARY_FOOTER_COMPANION_Y_TOL_RATIO
        )

        for item in items:
            block = item["block"]
            block_id = str(
                block.get(
                    "block_id"
                )
            )

            if (
                block_id in footer_ids
                or block.get(
                    "block_type"
                )
                != "text"
            ):
                continue

            bbox = item["bbox"]

            if (
                bbox["top"]
                / page_height
                <
                BOUNDARY_FOOTER_TEXT_MIN_TOP_RATIO
            ):
                continue

            font_size = item.get(
                "median_font_size"
            )

            if (
                font_size is None
                or font_size
                >
                global_ref
                * BOUNDARY_FOOTER_TEXT_MAX_FONT_RATIO
            ):
                continue

            if any(
                vertically_close(
                    bbox,
                    seed["bbox"],
                    y_tolerance,
                )
                for seed
                in footer_seed_items
            ):
                footer_ids.add(
                    block_id
                )

    footer_excluded: list[
        dict[str, Any]
    ] = []

    remaining: list[
        dict[str, Any]
    ] = []

    for item in items:
        block_id = str(
            item["block"].get(
                "block_id"
            )
        )

        if block_id not in footer_ids:
            remaining.append(
                item
            )
            continue

        is_seed = (
            block_id
            in footer_seed_ids
        )

        footer_excluded.append(
            {
                "block_id":
                    item["block"].get(
                        "block_id"
                    ),
                "block_type":
                    item["block"].get(
                        "block_type"
                    ),
                "bbox":
                    item["bbox"],
                "text_preview":
                    clean_text(
                        item["block"].get(
                            "text"
                        )
                    )[:160]
                    or None,
                "reason":
                    (
                        "boundary_footer_text"
                        if is_seed
                        else
                        "boundary_footer_text_companion"
                    ),
                "classification":
                    "boundary_footer_text",
                "action":
                    "auto_remove_from_logical_flow",
                "candidate_ids":
                    [],
                "candidate_types": [
                    "boundary_footer_text"
                ],
                "matched_texts":
                    [],
                "evidence": {
                    "median_font_size":
                        item.get(
                            "median_font_size"
                        ),
                    "global_main_font_reference":
                        round(
                            global_ref,
                            4,
                        ),
                    "top_ratio":
                        round(
                            item["bbox"]["top"]
                            / page_height,
                            4,
                        ),
                    "bottom_ratio":
                        round(
                            item["bbox"]["bottom"]
                            / page_height,
                            4,
                        ),
                    "role":
                        item.get(
                            "role"
                        ),
                    "seed":
                        is_seed,
                },
                "original_index":
                    item.get(
                        "original_index"
                    ),
            }
        )

    # --------------------------------------------------------------
    # 5. bottom ancillary：
    # 小字号 + 页底区域。
    #
    # 主要证据：
    # A. 对侧主正文仍继续向下；或
    # B. 自己已经处于极底部区域。
    #
    # 单个短小元素不够；至少形成一个 run，防止把普通注释误判。
    # --------------------------------------------------------------
    ancillary_ids: set[
        str
    ] = set()

    ancillary_diagnostics: list[
        dict[str, Any]
    ] = []

    for side in (
        "left",
        "right",
    ):
        own_ref = (
            column_refs.get(side)
            or global_ref
        )

        other_side = (
            "right"
            if side == "left"
            else "left"
        )

        other_ref = (
            column_refs.get(
                other_side
            )
            or global_ref
        )

        candidates: list[
            dict[str, Any]
        ] = []

        for item in remaining:
            if (
                item.get("role") != side
                or item["block"].get(
                    "block_type"
                )
                != "text"
            ):
                continue

            bbox = item["bbox"]

            top_ratio = (
                bbox["top"]
                / page_height
            )

            font_size = item.get(
                "median_font_size"
            )

            char_count = int(
                item.get(
                    "font_char_count",
                    0,
                )
                or 0
            )

            if (
                top_ratio
                < BOTTOM_ANCILLARY_MIN_TOP_RATIO
                or font_size is None
                or char_count
                < BOTTOM_ANCILLARY_MIN_ITEM_CHARS
                or font_size
                > own_ref
                * BOTTOM_ANCILLARY_MODERATE_FONT_RATIO
            ):
                continue

            # 图 / 图表二维区域保护。
            # 典型用途：曲线坐标、图例、标注、图内参数等不能被误搬成 ancillary。
            figure_protection = (
                item_is_inside_figure_region(
                    item,
                    remaining,
                )
            )

            if (
                figure_protection
                is not None
            ):
                continue

            # 对侧是否仍有“正常主文字号”的正文向更低处延伸。
            opposite_continues = any(
                (
                    other.get(
                        "role"
                    )
                    == other_side
                    and other[
                        "block"
                    ].get(
                        "block_type"
                    )
                    == "text"
                    and other.get(
                        "median_font_size"
                    )
                    is not None
                    and other.get(
                        "median_font_size"
                    )
                    >= other_ref * 0.94
                    and other[
                        "bbox"
                    ]["bottom"]
                    >= (
                        bbox["top"]
                        + page_height
                        * BOTTOM_ANCILLARY_OPPOSITE_CONTINUE_RATIO
                    )
                )
                for other
                in remaining
            )

            extreme_bottom = (
                top_ratio
                >= BOTTOM_ANCILLARY_EXTREME_TOP_RATIO
            )

            if not (
                opposite_continues
                or extreme_bottom
            ):
                continue

            font_ratio = (
                font_size
                / own_ref
            )

            evidence_tier = (
                "strong"
                if font_ratio
                <= BOTTOM_ANCILLARY_STRONG_FONT_RATIO
                else "moderate"
            )

            # moderate 不能仅靠“靠近页底”成立；
            # 必须有对侧主正文继续这一条额外证据。
            if (
                evidence_tier
                == "moderate"
                and not opposite_continues
            ):
                continue

            candidates.append(
                {
                    "item": item,
                    "opposite_continues":
                        opposite_continues,
                    "extreme_bottom":
                        extreme_bottom,
                    "font_ratio":
                        font_ratio,
                    "evidence_tier":
                        evidence_tier,
                }
            )

        strong_candidates = [
            entry
            for entry in candidates
            if entry[
                "evidence_tier"
            ]
            == "strong"
        ]

        moderate_candidates = [
            entry
            for entry in candidates
            if entry[
                "evidence_tier"
            ]
            == "moderate"
        ]

        strong_chars = sum(
            int(
                entry[
                    "item"
                ].get(
                    "font_char_count",
                    0,
                )
                or 0
            )
            for entry
            in strong_candidates
        )

        moderate_chars = sum(
            int(
                entry[
                    "item"
                ].get(
                    "font_char_count",
                    0,
                )
                or 0
            )
            for entry
            in moderate_candidates
        )

        strong_run_confirmed = (
            len(
                strong_candidates
            )
            >= BOTTOM_ANCILLARY_STRONG_MIN_RUN_ITEMS
            or strong_chars
            >= BOTTOM_ANCILLARY_STRONG_MIN_RUN_CHARS
        )

        moderate_run_confirmed = (
            len(
                moderate_candidates
            )
            >= BOTTOM_ANCILLARY_MODERATE_MIN_RUN_ITEMS
            or moderate_chars
            >= BOTTOM_ANCILLARY_MODERATE_MIN_RUN_CHARS
        )

        # 若 strong 已形成连续辅助区，则 strong + moderate 可一起纳入。
        # 若只有 moderate，则必须自己形成更强的连续 run。
        if strong_run_confirmed:
            confirmed_candidates = list(
                candidates
            )
        elif moderate_run_confirmed:
            confirmed_candidates = list(
                moderate_candidates
            )
        else:
            confirmed_candidates = []

        if not confirmed_candidates:
            continue

        candidates = confirmed_candidates

        for entry in candidates:
            item = entry[
                "item"
            ]

            block_id = str(
                item["block"].get(
                    "block_id"
                )
            )

            ancillary_ids.add(
                block_id
            )

            item[
                "flow_role"
            ] = "ancillary"

            ancillary_diagnostics.append(
                {
                    "block_id":
                        item["block"].get(
                            "block_id"
                        ),
                    "source_block_id":
                        item.get(
                            "source_block_id"
                        ),
                    "logical_fragment":
                        item.get(
                            "logical_fragment"
                        ),
                    "column":
                        side,
                    "median_font_size":
                        item.get(
                            "median_font_size"
                        ),
                    "column_main_font_reference":
                        round(
                            own_ref,
                            4,
                        ),
                    "font_ratio":
                        round(
                            float(
                                item.get(
                                    "median_font_size"
                                )
                            )
                            / own_ref,
                            4,
                        ),
                    "evidence_tier":
                        entry.get(
                            "evidence_tier"
                        ),
                    "top_ratio":
                        round(
                            item["bbox"]["top"]
                            / page_height,
                            4,
                        ),
                    "opposite_main_continues":
                        entry[
                            "opposite_continues"
                        ],
                    "extreme_bottom":
                        entry[
                            "extreme_bottom"
                        ],
                }
            )

    # --------------------------------------------------------------
    # 6. ancillary tail extension
    #
    # 已经确认 ancillary run 后，允许沿同一栏向下继续吸收“紧邻、同字号级别”
    # 的尾部文本。这里不再要求“对侧正文继续”，因为对侧正文可能刚好已经结束。
    #
    # 关键保护：
    # - 只从已确认 run 向下扩展，不会凭空创建 ancillary；
    # - 碰到字号恢复到主正文级别的 text 就停止；
    # - 间距过大就停止；
    # - image/vector 内文字不扩展；
    # - 只处理同一栏。
    # --------------------------------------------------------------
    for side in (
        "left",
        "right",
    ):
        side_confirmed = [
            item
            for item in remaining
            if (
                item.get(
                    "role"
                )
                == side
                and str(
                    item["block"].get(
                        "block_id"
                    )
                )
                in ancillary_ids
            )
        ]

        if not side_confirmed:
            continue

        own_ref = (
            column_refs.get(
                side
            )
            or global_ref
        )

        run_fonts = [
            float(
                item.get(
                    "median_font_size"
                )
            )
            for item in side_confirmed
            if (
                item.get(
                    "median_font_size"
                )
                is not None
                and float(
                    item.get(
                        "median_font_size"
                    )
                )
                > 0
            )
        ]

        run_font_ref = (
            median_number(
                run_fonts
            )
        )

        if (
            run_font_ref is None
            or run_font_ref <= 0
        ):
            continue

        current_bottom = max(
            float(
                item["bbox"]["bottom"]
            )
            for item in side_confirmed
        )

        # 逻辑向下锚点使用“已确认 ancillary 中最靠下的 top”，
        # 不再使用 max(bottom) 作为候选入口。
        #
        # 原因：PDF/Stage4 text block 的 bbox 可能很高，
        # 后续独立 block 的 top 可能落在前一个 block 的 bbox 内部。
        current_anchor_top = max(
            float(
                item["bbox"]["top"]
            )
            for item in side_confirmed
        )

        min_top_progress = (
            page_height
            * BOTTOM_ANCILLARY_TAIL_MIN_TOP_PROGRESS_RATIO
        )

        tail_candidates = sorted(
            [
                item
                for item in remaining
                if (
                    item.get(
                        "role"
                    )
                    == side
                    and item[
                        "block"
                    ].get(
                        "block_type"
                    )
                    == "text"
                    and str(
                        item[
                            "block"
                        ].get(
                            "block_id"
                        )
                    )
                    not in ancillary_ids
                    and float(
                        item[
                            "bbox"
                        ]["top"]
                    )
                    > (
                        current_anchor_top
                        + min_top_progress
                    )
                )
            ],
            key=lambda item: (
                float(
                    item["bbox"]["top"]
                ),
                float(
                    item["bbox"]["x0"]
                ),
            ),
        )

        for item in tail_candidates:
            bbox = item[
                "bbox"
            ]

            candidate_top = float(
                bbox["top"]
            )

            top_progress = (
                candidate_top
                - current_anchor_top
            )

            if (
                top_progress
                <= min_top_progress
            ):
                continue

            # overlap-aware gap：
            # 若候选 top 仍位于当前 ancillary 纵向覆盖范围内，
            # 说明 bbox 有重叠，但逻辑起点已经继续向下，此时 gap=0。
            overlaps_confirmed_bbox = (
                candidate_top
                < current_bottom
            )

            gap = (
                0.0
                if overlaps_confirmed_bbox
                else (
                    candidate_top
                    - current_bottom
                )
            )

            # 只有真正存在明显空白断层时才停止扩展。
            if (
                gap
                > page_height
                * BOTTOM_ANCILLARY_TAIL_MAX_GAP_RATIO
            ):
                break

            top_ratio = (
                float(
                    bbox["top"]
                )
                / page_height
            )

            if (
                top_ratio
                < BOTTOM_ANCILLARY_TAIL_MIN_TOP_RATIO
            ):
                break

            font_size = item.get(
                "median_font_size"
            )

            char_count = int(
                item.get(
                    "font_char_count",
                    0,
                )
                or 0
            )

            # 遇到无法证明仍属于小字号辅助区的 text 就停止，
            # 不跨越它继续寻找后面的候选。
            if (
                font_size is None
                or char_count
                < BOTTOM_ANCILLARY_MIN_ITEM_CHARS
            ):
                break

            font_size = float(
                font_size
            )

            font_delta_ratio = abs(
                font_size
                - run_font_ref
            ) / run_font_ref

            still_small_vs_main = (
                font_size
                <= own_ref
                * BOTTOM_ANCILLARY_MODERATE_FONT_RATIO
            )

            similar_to_run = (
                font_delta_ratio
                <= BOTTOM_ANCILLARY_TAIL_FONT_TOLERANCE_RATIO
            )

            if not (
                still_small_vs_main
                and similar_to_run
            ):
                break

            figure_protection = (
                item_is_inside_figure_region(
                    item,
                    remaining,
                )
            )

            if (
                figure_protection
                is not None
            ):
                break

            block_id = str(
                item["block"].get(
                    "block_id"
                )
            )

            ancillary_ids.add(
                block_id
            )

            item[
                "flow_role"
            ] = "ancillary"

            ancillary_diagnostics.append(
                {
                    "block_id":
                        item["block"].get(
                            "block_id"
                        ),
                    "source_block_id":
                        item.get(
                            "source_block_id"
                        ),
                    "logical_fragment":
                        item.get(
                            "logical_fragment"
                        ),
                    "column":
                        side,
                    "median_font_size":
                        item.get(
                            "median_font_size"
                        ),
                    "column_main_font_reference":
                        round(
                            own_ref,
                            4,
                        ),
                    "font_ratio":
                        round(
                            font_size
                            / own_ref,
                            4,
                        ),
                    "evidence_tier":
                        "tail_extension",
                    "top_ratio":
                        round(
                            top_ratio,
                            4,
                        ),
                    "opposite_main_continues":
                        False,
                    "extreme_bottom":
                        (
                            top_ratio
                            >= BOTTOM_ANCILLARY_EXTREME_TOP_RATIO
                        ),
                    "tail_gap_ratio":
                        round(
                            gap
                            / page_height,
                            4,
                        ),
                    "tail_top_progress_ratio":
                        round(
                            top_progress
                            / page_height,
                            4,
                        ),
                    "tail_bbox_overlap":
                        overlaps_confirmed_bbox,
                    "tail_font_delta_ratio":
                        round(
                            font_delta_ratio,
                            4,
                        ),
                }
            )

            current_bottom = max(
                current_bottom,
                float(
                    bbox["bottom"]
                ),
            )

            current_anchor_top = max(
                current_anchor_top,
                candidate_top,
            )

            # 扩展后的新 item 也成为 run 的一部分，
            # 让连续多段尾部信息可以链式向下吸收。
            run_fonts.append(
                font_size
            )

            updated_run_font_ref = (
                median_number(
                    run_fonts
                )
            )

            if (
                updated_run_font_ref
                is not None
                and updated_run_font_ref
                > 0
            ):
                run_font_ref = (
                    updated_run_font_ref
                )

    ancillary_items = [
        item
        for item in remaining
        if str(
            item["block"].get(
                "block_id"
            )
        )
        in ancillary_ids
    ]

    active_items = list(
        remaining
    )

    # 临时字号数组不写入最终 JSON。
    for item in items:
        item.pop(
            "_font_sizes",
            None,
        )

    return (
        active_items,
        ancillary_items,
        footer_excluded,
        {
            "status": "completed",
            "column_font_reference": {
                side: (
                    round(
                        value,
                        4,
                    )
                    if value is not None
                    else None
                )
                for side, value
                in column_refs.items()
            },
            "global_main_font_reference":
                round(
                    global_ref,
                    4,
                ),
            "ancillary_count":
                len(
                    ancillary_items
                ),
            "footer_text_excluded_count":
                len(
                    footer_excluded
                ),
            "ancillary_items":
                ancillary_diagnostics,
        },
    )


def order_single_column(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=base_spatial_key,
    )


def order_column_band(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    一个没有跨栏 separator 的 band 中：

        左栏：上 → 下
        然后
        右栏：上 → 下

    若存在 unknown，则最后按普通空间顺序保守附加。
    """
    left = sorted(
        [
            item
            for item in items
            if item["role"] == "left"
        ],
        key=column_key,
    )

    right = sorted(
        [
            item
            for item in items
            if item["role"] == "right"
        ],
        key=column_key,
    )

    unknown = sorted(
        [
            item
            for item in items
            if item["role"]
            not in {
                "left",
                "right",
            }
        ],
        key=base_spatial_key,
    )

    return (
        left
        + right
        + unknown
    )


def order_multi_column(
    items: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    多栏页按“跨栏 block 作为 separator”的方式恢复：

        [跨栏标题]
        左栏 → 右栏
        [跨栏表格/图片]
        左栏 → 右栏

    如果普通栏 block 与 span block 在纵向明显重叠，
    不强行假装确定，记录 ambiguity。
    """
    ancillary_items = [
        item
        for item in items
        if item.get(
            "flow_role"
        )
        == "ancillary"
    ]

    main_items = [
        item
        for item in items
        if item.get(
            "flow_role"
        )
        != "ancillary"
    ]

    spans = sorted(
        [
            item
            for item in main_items
            if item["role"] == "span"
        ],
        key=base_spatial_key,
    )

    column_items = [
        item
        for item in main_items
        if item["role"] != "span"
    ]

    ordered: list[
        dict[str, Any]
    ] = []

    ambiguities: list[
        dict[str, Any]
    ] = []

    remaining = list(
        column_items
    )

    for span in spans:
        span_bbox = span["bbox"]

        before: list[
            dict[str, Any]
        ] = []

        overlapping: list[
            dict[str, Any]
        ] = []

        after: list[
            dict[str, Any]
        ] = []

        for item in remaining:
            bbox = item["bbox"]

            if (
                bbox["bottom"]
                <=
                span_bbox["top"]
                +
                READING_VERTICAL_OVERLAP_TOLERANCE
            ):
                before.append(
                    item
                )
                continue

            if (
                bbox["top"]
                >=
                span_bbox["bottom"]
                -
                READING_VERTICAL_OVERLAP_TOLERANCE
            ):
                after.append(
                    item
                )
                continue

            overlapping.append(
                item
            )

        ordered.extend(
            order_column_band(
                before
            )
        )

        if overlapping:
            ambiguities.append(
                {
                    "span_block_id":
                        span["block"].get(
                            "block_id"
                        ),
                    "overlapping_block_ids":
                        [
                            item[
                                "block"
                            ].get(
                                "block_id"
                            )
                            for item
                            in overlapping
                        ],
                    "reason":
                        "column_block_vertically_overlaps_span_block",
                }
            )

            # 无法确定的部分只按普通空间顺序放在 span 前，
            # 并明确标记 ambiguity，不做虚假高置信推断。
            ordered.extend(
                sorted(
                    overlapping,
                    key=base_spatial_key,
                )
            )

        ordered.append(
            span
        )

        remaining = after

    ordered.extend(
        order_column_band(
            remaining
        )
    )

    # bottom ancillary 不删除，但必须在主正文左右栏都完成后再输出。
    if ancillary_items:
        ordered.extend(
            order_column_band(
                ancillary_items
            )
        )

    return (
        ordered,
        ambiguities,
    )


def reading_item_record(
    item: dict[str, Any],
    reading_order: int,
) -> dict[str, Any]:
    block = item["block"]
    bbox = item["bbox"]

    text = clean_text(
        block.get(
            "text",
            "",
        )
    )

    if len(text) > 100:
        text = (
            text[:97]
            + "..."
        )

    return {
        "reading_order":
            reading_order,
        "block_id":
            block.get(
                "block_id"
            ),
        "source_block_id":
            item.get(
                "source_block_id"
            )
            or block.get(
                "source_block_id"
            )
            or block.get(
                "block_id"
            ),
        "logical_fragment":
            item.get(
                "logical_fragment"
            )
            or block.get(
                "logical_fragment"
            ),
        "block_type":
            block.get(
                "block_type"
            ),
        "column_role":
            item.get(
                "role"
            ),
        "role_override_reason":
            item.get(
                "role_override_reason"
            ),
        "flow_role":
            item.get(
                "flow_role",
                "main",
            ),
        "median_font_size":
            item.get(
                "median_font_size"
            ),
        "bbox":
            bbox,
        "source_word_indices":
            [
                int(value)
                for value in (
                    item.get("source_word_indices")
                    or block.get("source_word_indices")
                    or []
                )
                if isinstance(value, int)
            ],
        "text_preview":
            text
            if text
            else None,
        "original_index":
            item.get(
                "original_index"
            ),
    }


def build_page_reading_order(
    page: dict[str, Any],
    raw_page: dict[str, Any],
    ignored_noise_regions: list[dict[str, Any]] | None = None,
    auto_remove_occurrences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    page_number = int(
        page["page_number"]
    )

    profile = page.get(
        "page_profile",
        {},
    )

    if not isinstance(
        profile,
        dict,
    ):
        profile = {}

    multi_column = bool(
        profile.get(
            "multi_column",
            False,
        )
    )

    (
        items,
        invalid,
        split_details,
        wide_text_diagnostics,
        excluded_noise_blocks,
    ) = prepare_reading_items(
        page,
        raw_page,
        ignored_noise_regions,
        auto_remove_occurrences,
    )

    ambiguities: list[
        dict[str, Any]
    ] = []

    bottom_flow_diagnostics: dict[
        str,
        Any,
    ] = {
        "status": "not_applicable",
        "ancillary_count": 0,
        "footer_text_excluded_count": 0,
    }

    ancillary_items: list[
        dict[str, Any]
    ] = []

    footer_text_excluded: list[
        dict[str, Any]
    ] = []

    if multi_column:
        (
            items,
            ancillary_items,
            footer_text_excluded,
            bottom_flow_diagnostics,
        ) = classify_bottom_flows(
            page,
            raw_page,
            items,
            ignored_noise_regions,
        )

        if footer_text_excluded:
            excluded_noise_blocks.extend(
                footer_text_excluded
            )

        ordered, ambiguities = (
            order_multi_column(
                items
            )
        )

        mode = (
            "two_column_gutter_aware_bottom_flow"
        )

    else:
        ordered = (
            order_single_column(
                items
            )
        )

        mode = "single_column_spatial"

    records = [
        reading_item_record(
            item,
            reading_order=index,
        )
        for index, item
        in enumerate(
            ordered,
            start=1,
        )
    ]

    # v0.2.1 中 split 本身就意味着逻辑 reading units
    # 与 Stage4 block 列表不同，因此单独记录 split。
    logical_split = bool(
        split_details
    )

    original_ids = [
        item["block"].get(
            "block_id"
        )
        for item in items
        if not item.get(
            "logical_fragment"
        )
    ]

    ordered_unsplit_ids = [
        item["block"].get(
            "block_id"
        )
        for item in ordered
        if not item.get(
            "logical_fragment"
        )
    ]

    reordered_without_split = (
        ordered_unsplit_ids
        != original_ids
    )

    reordered = (
        logical_split
        or reordered_without_split
    )

    if invalid:
        status = "partial"
        confidence = "low"

    elif ambiguities:
        status = "partial"
        confidence = "low"

    elif multi_column:
        status = "resolved"
        confidence = "medium"

    else:
        status = "resolved"
        confidence = "high"

    role_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    for item in items:
        role_counts[
            str(item["role"])
        ] += 1

    true_span_text_count = sum(
        1
        for item
        in wide_text_diagnostics
        if item.get(
            "classification"
        )
        == "true_span"
    )

    noise_inflated_left_count = sum(
        1
        for item
        in wide_text_diagnostics
        if item.get(
            "classification"
        )
        == "noise_inflated_left"
    )

    noise_inflated_right_count = sum(
        1
        for item
        in wide_text_diagnostics
        if item.get(
            "classification"
        )
        == "noise_inflated_right"
    )

    insufficient_span_text_count = sum(
        1
        for item
        in wide_text_diagnostics
        if item.get(
            "classification"
        )
        == "insufficient"
    )

    return {
        "page_number":
            page_number,
        "multi_column":
            multi_column,
        "document_structure":
            page.get(
                "document_structure",
                {},
            ),
        "mode":
            mode,
        "status":
            status,
        "confidence":
            confidence,
        "block_count":
            len(
                structure_blocks(
                    page
                )
            ),
        "logical_unit_count":
            len(items),
        "ordered_block_count":
            len(records),
        "invalid_block_count":
            len(invalid),
        "excluded_noise_block_count":
            len(excluded_noise_blocks),
        "ancillary_block_count":
            len(ancillary_items),
        "footer_text_excluded_count":
            len(footer_text_excluded),
        "ambiguity_count":
            len(ambiguities),
        "reordered_from_stage4":
            reordered,
        "reordered_without_split":
            reordered_without_split,
        "split_source_block_count":
            len(split_details),
        "logical_fragment_count":
            len(split_details) * 2,
        "true_span_text_count":
            true_span_text_count,
        "noise_inflated_left_count":
            noise_inflated_left_count,
        "noise_inflated_right_count":
            noise_inflated_right_count,
        "insufficient_span_text_count":
            insufficient_span_text_count,
        "column_role_counts":
            dict(role_counts),
        "reading_order":
            records,
        "split_details":
            split_details,
        "wide_text_diagnostics":
            wide_text_diagnostics,
        "invalid_blocks":
            invalid,
        "excluded_noise_blocks":
            excluded_noise_blocks,
        "bottom_flow_diagnostics":
            bottom_flow_diagnostics,
        "ambiguities":
            ambiguities,

        # Stage6.1 已确认的 watermark region 继续向下游传递。
        # Stage6.3 仅在 char geometry 精确匹配后重写受污染 raw word；
        # layout_container 也只替换完整、已确认污染的 raw word。
        "ignored_noise_regions":
            list(
                ignored_noise_regions
                or []
            ),

        # 只生成 Stage6.2 逻辑 fragment，
        # 不修改 Stage4 原 block。
        "blocks_modified":
            False,
    }


def build_reading_order_result(
    structure: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    noise_result: dict[str, Any],
) -> dict[str, Any]:
    noise_regions = build_stage62_noise_regions(
        noise_result
    )

    auto_remove_occurrences = (
        build_stage62_auto_remove_occurrences(
            noise_result
        )
    )

    pages = [
        build_page_reading_order(
            page,
            snapshot_pages.get(
                int(page["page_number"]),
                {},
            ),
            noise_regions.get(
                int(page["page_number"]),
                [],
            ),
            auto_remove_occurrences.get(
                int(page["page_number"]),
                [],
            ),
        )
        for page
        in structure.get(
            "pages",
            []
        )
        if isinstance(
            page,
            dict,
        )
    ]

    status_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    mode_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    multi_column_pages = 0
    reordered_pages = 0
    total_ambiguities = 0
    total_invalid = 0
    total_excluded_noise_blocks = 0
    total_excluded_page_number_blocks = 0
    total_excluded_watermark_blocks = 0
    total_excluded_boundary_footer_table_blocks = 0
    total_excluded_boundary_footer_text_blocks = 0
    total_ancillary_blocks = 0
    total_split_sources = 0
    total_logical_fragments = 0
    total_true_span_text = 0
    total_noise_inflated_left = 0
    total_noise_inflated_right = 0
    total_insufficient_span_text = 0
    total_noise_regions = sum(
        len(items)
        for items in noise_regions.values()
    )
    pages_with_noise_regions = len(
        noise_regions
    )

    for page in pages:
        status_counts[
            str(page["status"])
        ] += 1

        mode_counts[
            str(page["mode"])
        ] += 1

        if page[
            "multi_column"
        ]:
            multi_column_pages += 1

        if page[
            "reordered_from_stage4"
        ]:
            reordered_pages += 1

        total_ambiguities += int(
            page[
                "ambiguity_count"
            ]
        )

        total_invalid += int(
            page[
                "invalid_block_count"
            ]
        )

        excluded_blocks = page.get(
            "excluded_noise_blocks",
            [],
        )

        total_excluded_noise_blocks += len(
            excluded_blocks
        )

        for excluded in excluded_blocks:
            candidate_types = set(
                excluded.get(
                    "candidate_types",
                    [],
                )
            )

            if "page_number" in candidate_types:
                total_excluded_page_number_blocks += 1

            if "watermark" in candidate_types:
                total_excluded_watermark_blocks += 1

            if (
                "boundary_footer_table"
                in candidate_types
            ):
                total_excluded_boundary_footer_table_blocks += 1

            if (
                "boundary_footer_text"
                in candidate_types
            ):
                total_excluded_boundary_footer_text_blocks += 1

        total_ancillary_blocks += int(
            page.get(
                "ancillary_block_count",
                0,
            )
        )

        total_split_sources += int(
            page.get(
                "split_source_block_count",
                0,
            )
        )

        total_logical_fragments += int(
            page.get(
                "logical_fragment_count",
                0,
            )
        )

        total_true_span_text += int(
            page.get(
                "true_span_text_count",
                0,
            )
        )

        total_noise_inflated_left += int(
            page.get(
                "noise_inflated_left_count",
                0,
            )
        )

        total_noise_inflated_right += int(
            page.get(
                "noise_inflated_right_count",
                0,
            )
        )

        total_insufficient_span_text += int(
            page.get(
                "insufficient_span_text_count",
                0,
            )
        )

    return {
        "stage": "6.2",
        "version": STAGE62_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "source_file":
            structure.get(
                "source_file"
            ),
        "page_count":
            len(pages),
        "multi_column_pages":
            multi_column_pages,
        "reordered_pages":
            reordered_pages,
        "status_counts":
            dict(status_counts),
        "mode_counts":
            dict(mode_counts),
        "ambiguity_count":
            total_ambiguities,
        "invalid_block_count":
            total_invalid,
        "excluded_noise_block_count":
            total_excluded_noise_blocks,
        "excluded_page_number_block_count":
            total_excluded_page_number_blocks,
        "excluded_watermark_block_count":
            total_excluded_watermark_blocks,
        "excluded_boundary_footer_table_block_count":
            total_excluded_boundary_footer_table_blocks,
        "excluded_boundary_footer_text_block_count":
            total_excluded_boundary_footer_text_blocks,
        "ancillary_block_count":
            total_ancillary_blocks,
        "split_source_block_count":
            total_split_sources,
        "logical_fragment_count":
            total_logical_fragments,
        "true_span_text_count":
            total_true_span_text,
        "noise_inflated_left_count":
            total_noise_inflated_left,
        "noise_inflated_right_count":
            total_noise_inflated_right,
        "insufficient_span_text_count":
            total_insufficient_span_text,
        "ignored_watermark_region_count":
            total_noise_regions,
        "pages_with_ignored_watermark_regions":
            pages_with_noise_regions,
        "pages":
            pages,

        # 明确：这不是最终 Quality Gate。
        "quality_gate_completed":
            False,
        "text_modified":
            False,
        "stage_status": {
            "algorithm_baseline":
                STAGE62_VERSION,
            "sealed":
                False,
            "scope":
                "native_normal_page_reading_order",
            "complex_layout_policy":
                "keep_partial_for_quality_gate_fallback",
        },
    }


def render_reading_order_markdown(
    result: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Stage 6.2 Reading Order",
        "",
        f"- 文件：{result.get('source_file')}",
        f"- 页数：{result.get('page_count')}",
        f"- 多栏页：{result.get('multi_column_pages')}",
        f"- 相比 Stage4 顺序发生变化的页：{result.get('reordered_pages')}",
        f"- ambiguity：{result.get('ambiguity_count')}",
        f"- invalid block：{result.get('invalid_block_count')}",
        f"- 从逻辑 reading order 排除的已确认噪声块：{result.get('excluded_noise_block_count')}",
        f"  - page number block：{result.get('excluded_page_number_block_count')}",
        f"  - watermark block：{result.get('excluded_watermark_block_count')}",
        f"  - boundary footer table：{result.get('excluded_boundary_footer_table_block_count')}",
        f"  - boundary footer text：{result.get('excluded_boundary_footer_text_block_count')}",
        f"- bottom ancillary block：{result.get('ancillary_block_count')}",
        f"- 被拆分的 Stage4 宽文本块：{result.get('split_source_block_count')}",
        f"- 新增逻辑 fragments：{result.get('logical_fragment_count')}",
        f"- 确认真跨栏 text：{result.get('true_span_text_count')}",
        f"- 水印虚假拉宽→left：{result.get('noise_inflated_left_count')}",
        f"- 水印虚假拉宽→right：{result.get('noise_inflated_right_count')}",
        f"- 证据不足仍保留 span：{result.get('insufficient_span_text_count')}",
        f"- gutter 判断忽略的 watermark region：{result.get('ignored_watermark_region_count')}",
        f"- 含 ignored watermark 的页：{result.get('pages_with_ignored_watermark_regions')}",
        "- 当前只恢复逻辑 reading units，不合并段落、不改 Stage4 原 block。",
        "",
    ]

    for page in result.get(
        "pages",
        [],
    ):
        lines.extend(
            [
                f"## PDF 第 {page['page_number']} 页",
                "",
                (
                    f"- mode: `{page['mode']}`"
                    f" | status: `{page['status']}`"
                    f" | confidence: `{page['confidence']}`"
                    f" | multi_column: `{page['multi_column']}`"
                ),
                (
                    f"- blocks={page['block_count']}"
                    f" | ordered={page['ordered_block_count']}"
                    f" | ambiguity={page['ambiguity_count']}"
                    f" | invalid={page['invalid_block_count']}"
                    f" | excluded_noise={page['excluded_noise_block_count']}"
                    f" | ancillary={page['ancillary_block_count']}"
                    f" | footer_text={page['footer_text_excluded_count']}"
                    f" | split={page['split_source_block_count']}"
                    f" | reordered={page['reordered_from_stage4']}"
                ),
                "",
                "| 顺序 | block_id | source_block | fragment | 类型 | 列角色 | flow_role | role_override | font | top | x0 | 内容预览 |",
                "|---:|---|---|---|---|---|---|---|---:|---:|---:|---|",
            ]
        )

        for item in page.get(
            "reading_order",
            [],
        ):
            bbox = item[
                "bbox"
            ]

            preview = (
                item.get(
                    "text_preview"
                )
                or ""
            )

            preview = (
                preview
                .replace("|", "\\|")
                .replace("\n", " ")
            )

            lines.append(
                "| "
                + str(
                    item[
                        "reading_order"
                    ]
                )
                + " | "
                + str(
                    item.get(
                        "block_id"
                    )
                    or "-"
                )
                + " | "
                + str(
                    item.get(
                        "source_block_id"
                    )
                    or "-"
                )
                + " | "
                + str(
                    item.get(
                        "logical_fragment"
                    )
                    or "-"
                )
                + " | "
                + str(
                    item.get(
                        "block_type"
                    )
                    or "-"
                )
                + " | "
                + str(
                    item.get(
                        "column_role"
                    )
                    or "-"
                )
                + " | "
                + str(
                    item.get(
                        "flow_role"
                    )
                    or "main"
                )
                + " | "
                + str(
                    item.get(
                        "role_override_reason"
                    )
                    or "-"
                )
                + " | "
                + (
                    f"{float(item['median_font_size']):.2f}"
                    if item.get(
                        "median_font_size"
                    )
                    is not None
                    else "-"
                )
                + " | "
                + f"{float(bbox['top']):.1f}"
                + " | "
                + f"{float(bbox['x0']):.1f}"
                + " | "
                + preview
                + " |"
            )

        bottom_flow = page.get(
            "bottom_flow_diagnostics",
            {},
        )

        if (
            isinstance(
                bottom_flow,
                dict,
            )
            and bottom_flow.get(
                "status"
            )
            == "completed"
            and (
                bottom_flow.get(
                    "ancillary_count",
                    0,
                )
                or bottom_flow.get(
                    "footer_text_excluded_count",
                    0,
                )
            )
        ):
            lines.extend(
                [
                    "",
                    "### Bottom flow",
                    "",
                    (
                        "- main_font_reference="
                        + repr(
                            bottom_flow.get(
                                "column_font_reference"
                            )
                        )
                        + " | ancillary="
                        + str(
                            bottom_flow.get(
                                "ancillary_count",
                                0,
                            )
                        )
                        + " | footer_text="
                        + str(
                            bottom_flow.get(
                                "footer_text_excluded_count",
                                0,
                            )
                        )
                    ),
                ]
            )

            for detail in bottom_flow.get(
                "ancillary_items",
                [],
            ):
                lines.append(
                    "- ancillary="
                    + str(
                        detail.get(
                            "block_id"
                        )
                    )
                    + " | column="
                    + str(
                        detail.get(
                            "column"
                        )
                    )
                    + " | font_ratio="
                    + str(
                        detail.get(
                            "font_ratio"
                        )
                    )
                    + " | tier="
                    + str(
                        detail.get(
                            "evidence_tier"
                        )
                    )
                    + " | top_ratio="
                    + str(
                        detail.get(
                            "top_ratio"
                        )
                    )
                    + " | opposite_continues="
                    + str(
                        detail.get(
                            "opposite_main_continues"
                        )
                    )
                    + (
                        " | tail_gap_ratio="
                        + str(
                            detail.get(
                                "tail_gap_ratio"
                            )
                        )
                        + " | tail_top_progress_ratio="
                        + str(
                            detail.get(
                                "tail_top_progress_ratio"
                            )
                        )
                        + " | tail_bbox_overlap="
                        + str(
                            detail.get(
                                "tail_bbox_overlap"
                            )
                        )
                        + " | tail_font_delta_ratio="
                        + str(
                            detail.get(
                                "tail_font_delta_ratio"
                            )
                        )
                        if detail.get(
                            "evidence_tier"
                        )
                        == "tail_extension"
                        else ""
                    )
                )

        if page.get(
            "excluded_noise_blocks"
        ):
            lines.extend(
                [
                    "",
                    "### Excluded auto-remove noise",
                    "",
                ]
            )

            for excluded in page[
                "excluded_noise_blocks"
            ]:
                lines.append(
                    "- block="
                    + str(
                        excluded.get(
                            "block_id"
                        )
                    )
                    + " | reason="
                    + str(
                        excluded.get(
                            "reason"
                        )
                    )
                    + " | action="
                    + str(
                        excluded.get(
                            "action"
                        )
                    )
                    + " | candidates="
                    + ",".join(
                        str(value)
                        for value in excluded.get(
                            "candidate_ids",
                            [],
                        )
                    )
                    + " | text="
                    + repr(
                        excluded.get(
                            "text_preview",
                            "",
                        )
                    )
                    + (
                        " | evidence="
                        + repr(
                            excluded.get(
                                "evidence"
                            )
                        )
                        if excluded.get(
                            "evidence"
                        )
                        else ""
                    )
                )

        if page.get(
            "split_details"
        ):
            lines.extend(
                [
                    "",
                    "### Logical split",
                    "",
                ]
            )

            for detail in page[
                "split_details"
            ]:
                lines.append(
                    "- source="
                    + str(
                        detail.get(
                            "source_block_id"
                        )
                    )
                    + " -> "
                    + str(
                        detail.get(
                            "left_fragment_id"
                        )
                    )
                    + " + "
                    + str(
                        detail.get(
                            "right_fragment_id"
                        )
                    )
                    + " | gutter_lines="
                    + str(
                        detail.get(
                            "gutter_evidence_line_count"
                        )
                    )
                    + "/"
                    + str(
                        detail.get(
                            "bilateral_line_count"
                        )
                    )
                    + " | ratio="
                    + str(
                        detail.get(
                            "gutter_evidence_ratio"
                        )
                    )
                )

        if page.get(
            "ambiguities"
        ):
            lines.extend(
                [
                    "",
                    "### Ambiguity",
                    "",
                ]
            )

            for ambiguity in page[
                "ambiguities"
            ]:
                lines.append(
                    "- span="
                    + str(
                        ambiguity.get(
                            "span_block_id"
                        )
                    )
                    + " overlaps="
                    + ", ".join(
                        str(value)
                        for value
                        in ambiguity.get(
                            "overlapping_block_ids",
                            [],
                        )
                    )
                )

        if page.get(
            "invalid_blocks"
        ):
            lines.extend(
                [
                    "",
                    "### Invalid blocks",
                    "",
                ]
            )

            for invalid in page[
                "invalid_blocks"
            ]:
                lines.append(
                    "- "
                    + str(
                        invalid.get(
                            "block_id"
                        )
                    )
                    + ": "
                    + str(
                        invalid.get(
                            "reason"
                        )
                    )
                )

        lines.append("")

    return (
        "\n".join(lines)
        .rstrip()
        + "\n"
    )


def print_reading_order_summary(
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    print()
    print("=" * 88)
    print(
        "Stage 6.2 阅读顺序恢复"
        f" | {result.get('source_file')}"
        f" | 页数={result.get('page_count')}"
        f" | 多栏页={result.get('multi_column_pages')}"
        f" | 算法版本={STAGE62_VERSION}"
        f" | Pipeline={PIPELINE_VERSION}"
    )
    print("=" * 88)

    print(
        "状态"
        f" | resolved={result['status_counts'].get('resolved', 0)}"
        f" | partial={result['status_counts'].get('partial', 0)}"
        f" | reordered={result.get('reordered_pages', 0)}"
        f" | ambiguity={result.get('ambiguity_count', 0)}"
        f" | invalid={result.get('invalid_block_count', 0)}"
        f" | excluded_noise={result.get('excluded_noise_block_count', 0)}"
        f" | excluded_page_number={result.get('excluded_page_number_block_count', 0)}"
        f" | excluded_watermark={result.get('excluded_watermark_block_count', 0)}"
        f" | excluded_boundary_footer_table={result.get('excluded_boundary_footer_table_block_count', 0)}"
        f" | excluded_boundary_footer_text={result.get('excluded_boundary_footer_text_block_count', 0)}"
        f" | ancillary={result.get('ancillary_block_count', 0)}"
        f" | split={result.get('split_source_block_count', 0)}"
        f" | fragments={result.get('logical_fragment_count', 0)}"
        f" | ignored_watermark_regions={result.get('ignored_watermark_region_count', 0)}"
        f" | noise_inflated_left={result.get('noise_inflated_left_count', 0)}"
        f" | noise_inflated_right={result.get('noise_inflated_right_count', 0)}"
    )

    print(
        f"JSON：{output_dir / 'reading_order.json'}"
    )
    print(
        f"Markdown：{output_dir / 'reading_order.md'}"
    )
    print(
        "说明：多栏页使用“两级字号证据 + 连续 run + 对侧正文继续”识别 bottom ancillary；"
        "已确认 ancillary run 支持 bbox 重叠情况下的向下连续吸收；"
        "落在 image/vector 二维区域中的小字会被保护为图表内容。"
        "极底部跨栏小字号 footer text 才从 logical flow 排除。"
        "不匹配任何具体期刊/作者/DOI/字符串；Stage1 / Stage4 原证据始终保留。"
        "不修改 Stage4 原 block；Stage6.2 自身不做段落合并 / 跨页正文续接 / OCR / Quality Gate。"
    )
    print("=" * 88)



# =============================================================================
# Stage 6.3 Line → Paragraph Reconstruction
# =============================================================================


def stage63_bbox_area(
    bbox: dict[str, Any],
) -> float:
    return max(
        0.0,
        float(bbox["x1"])
        - float(bbox["x0"]),
    ) * max(
        0.0,
        float(bbox["bottom"])
        - float(bbox["top"]),
    )


def stage63_bbox_center(
    bbox: dict[str, Any],
) -> tuple[float, float]:
    return (
        (
            float(bbox["x0"])
            + float(bbox["x1"])
        ) / 2.0,
        (
            float(bbox["top"])
            + float(bbox["bottom"])
        ) / 2.0,
    )


def stage63_word_bbox(
    word: dict[str, Any],
) -> dict[str, float] | None:
    try:
        x0 = float(word["x0"])
        x1 = float(word["x1"])
        top = float(word["top"])
        bottom = float(word["bottom"])
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    if (
        x1 <= x0
        or bottom <= top
    ):
        return None

    return {
        "x0": x0,
        "top": top,
        "x1": x1,
        "bottom": bottom,
    }


def stage63_bbox_intersection_area(
    a: dict[str, Any],
    b: dict[str, Any],
) -> float:
    x0 = max(
        float(a["x0"]),
        float(b["x0"]),
    )
    x1 = min(
        float(a["x1"]),
        float(b["x1"]),
    )
    top = max(
        float(a["top"]),
        float(b["top"]),
    )
    bottom = min(
        float(a["bottom"]),
        float(b["bottom"]),
    )

    if (
        x1 <= x0
        or bottom <= top
    ):
        return 0.0

    return (
        (x1 - x0)
        * (bottom - top)
    )


def stage63_center_inside(
    inner_bbox: dict[str, Any],
    outer_bbox: dict[str, Any],
    tolerance: float = 0.0,
) -> bool:
    center_x, center_y = (
        stage63_bbox_center(
            inner_bbox
        )
    )

    return (
        float(outer_bbox["x0"])
        - tolerance
        <= center_x
        <= float(outer_bbox["x1"])
        + tolerance
        and float(outer_bbox["top"])
        - tolerance
        <= center_y
        <= float(outer_bbox["bottom"])
        + tolerance
    )


def stage63_bbox_union(
    bboxes: list[dict[str, Any]],
) -> dict[str, float] | None:
    if not bboxes:
        return None

    return {
        "x0": min(
            float(bbox["x0"])
            for bbox in bboxes
        ),
        "top": min(
            float(bbox["top"])
            for bbox in bboxes
        ),
        "x1": max(
            float(bbox["x1"])
            for bbox in bboxes
        ),
        "bottom": max(
            float(bbox["bottom"])
            for bbox in bboxes
        ),
    }


def stage63_is_cjk_char(
    char: str,
) -> bool:
    if not char:
        return False

    code = ord(char[0])

    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def stage63_join_words(
    words: list[dict[str, Any]],
) -> str:
    """
    只做最小的行内 word 拼接。

    - Stage1 word 已经是 parser 的原子词；
    - 英文/数字词之间默认保留空格；
    - 紧邻 CJK token 可不插空格；
    - 不在这里修复断词、连字符、错误缺空格。
    """
    if not words:
        return ""

    ordered = sorted(
        words,
        key=lambda item: (
            float(item["x0"]),
            float(item["top"]),
        ),
    )

    parts: list[str] = []
    previous: dict[str, Any] | None = None

    for word in ordered:
        value = clean_text(
            word.get(
                "text",
                "",
            )
        )

        if not value:
            continue

        if previous is None:
            parts.append(value)
            previous = word
            continue

        previous_text = clean_text(
            previous.get(
                "text",
                "",
            )
        )

        gap = (
            float(word["x0"])
            - float(previous["x1"])
        )

        previous_height = max(
            1.0,
            float(previous["bottom"])
            - float(previous["top"]),
        )

        current_height = max(
            1.0,
            float(word["bottom"])
            - float(word["top"]),
        )

        height_ref = (
            previous_height
            + current_height
        ) / 2.0

        no_space = (
            gap
            <= max(
                0.8,
                0.10 * height_ref,
            )
            or (
                previous_text
                and value
                and stage63_is_cjk_char(
                    previous_text[-1]
                )
                and stage63_is_cjk_char(
                    value[0]
                )
                and gap
                <= 0.75
                * height_ref
            )
        )

        if not no_space:
            parts.append(" ")

        parts.append(value)
        previous = word

    return "".join(parts)



def stage63_table_candidate_features(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    extracted = candidate.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        list,
    ):
        extracted = []

    rows = [
        row
        if isinstance(
            row,
            list,
        )
        else []
        for row in extracted
    ]

    row_count = len(rows)
    max_columns = max(
        (
            len(row)
            for row in rows
        ),
        default=0,
    )

    nonempty_texts: list[str] = []

    for row in rows:
        for cell in row:
            value = clean_text(
                cell
                if cell is not None
                else ""
            )

            if value:
                nonempty_texts.append(
                    value
                )

    lengths = [
        len(value)
        for value in nonempty_texts
    ]

    total_chars = sum(lengths)
    longest_cell_chars = max(
        lengths,
        default=0,
    )

    longest_share = (
        longest_cell_chars
        / total_chars
        if total_chars > 0
        else 0.0
    )

    return {
        "row_count": row_count,
        "max_columns": max_columns,
        "nonempty_cell_count":
            len(nonempty_texts),
        "total_chars": total_chars,
        "longest_cell_chars":
            longest_cell_chars,
        "longest_cell_share":
            round(
                longest_share,
                4,
            ),
        "cell_count":
            candidate.get(
                "cell_count"
            ),
        "source_table_index":
            candidate.get(
                "table_index"
            ),
    }


def stage63_bbox_iou(
    a: dict[str, Any],
    b: dict[str, Any],
) -> float:
    intersection = (
        stage63_bbox_intersection_area(
            a,
            b,
        )
    )

    if intersection <= 0:
        return 0.0

    union = (
        stage63_bbox_area(a)
        + stage63_bbox_area(b)
        - intersection
    )

    if union <= 0:
        return 0.0

    return intersection / union


def stage63_match_table_candidate(
    raw_page: dict[str, Any],
    reading_item: dict[str, Any],
) -> dict[str, Any] | None:
    item_bbox = reading_item.get(
        "bbox"
    )

    if not isinstance(
        item_bbox,
        dict,
    ):
        return None

    best: dict[str, Any] | None = None
    best_iou = 0.0

    candidates = raw_page.get(
        "table_candidates",
        [],
    )

    if not isinstance(
        candidates,
        list,
    ):
        return None

    for candidate in candidates:
        if not isinstance(
            candidate,
            dict,
        ):
            continue

        candidate_bbox = normalize_bbox(
            candidate.get(
                "bbox"
            )
        )

        if candidate_bbox is None:
            continue

        iou = stage63_bbox_iou(
            item_bbox,
            candidate_bbox,
        )

        if iou > best_iou:
            best_iou = iou
            best = candidate

    if (
        best is None
        or best_iou
        < LAYOUT_CONTAINER_TABLE_BBOX_IOU
    ):
        return None

    copied = dict(best)
    copied[
        "_stage63_bbox_iou"
    ] = best_iou

    return copied


def stage63_classify_table_unit(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
    reading_item: dict[str, Any],
) -> dict[str, Any]:
    candidate = (
        stage63_match_table_candidate(
            raw_page,
            reading_item,
        )
    )

    if candidate is None:
        return {
            "reading_order":
                reading_item.get(
                    "reading_order"
                ),
            "block_id":
                reading_item.get(
                    "block_id"
                ),
            "classification":
                "data_table",
            "confidence":
                "conservative_default",
            "reason":
                "no_matching_stage1_table_candidate",
            "source_table_index": None,
        }

    features = (
        stage63_table_candidate_features(
            candidate
        )
    )

    document_structure = (
        reading_page.get(
            "document_structure",
            {}
        )
    )

    if not isinstance(
        document_structure,
        dict,
    ):
        document_structure = {}

    zone_type = str(
        document_structure.get(
            "zone_type"
        )
        or ""
    )

    low_dimensional = (
        features["row_count"]
        <= LAYOUT_CONTAINER_MAX_ROWS
        and features["max_columns"]
        <= LAYOUT_CONTAINER_MAX_COLUMNS
        and features[
            "nonempty_cell_count"
        ]
        <= LAYOUT_CONTAINER_MAX_NONEMPTY_CELLS
    )

    prose_dominant = (
        features["total_chars"]
        >= LAYOUT_CONTAINER_MIN_TOTAL_CHARS
        and features[
            "longest_cell_chars"
        ]
        >= LAYOUT_CONTAINER_MIN_LONGEST_CELL_CHARS
        and features[
            "longest_cell_share"
        ]
        >= LAYOUT_CONTAINER_MIN_LONGEST_SHARE
    )

    one_dimensional = (
        features["max_columns"]
        <= 1
    )

    sem_free_support = (
        zone_type
        in LAYOUT_CONTAINER_SEMIFREE_ZONES
    )

    layout_container = (
        low_dimensional
        and prose_dominant
        and (
            one_dimensional
            or sem_free_support
        )
    )

    classification = (
        "layout_container"
        if layout_container
        else "data_table"
    )

    reason = (
        "low_dimensional_prose_dominant"
        if layout_container
        else "table_structure_retained"
    )

    return {
        "reading_order":
            reading_item.get(
                "reading_order"
            ),
        "block_id":
            reading_item.get(
                "block_id"
            ),
        "classification":
            classification,
        "confidence":
            (
                "high"
                if layout_container
                else "conservative"
            ),
        "reason": reason,
        "zone_type":
            zone_type
            if zone_type
            else None,
        "bbox_iou":
            round(
                float(
                    candidate.get(
                        "_stage63_bbox_iou",
                        0.0,
                    )
                ),
                4,
            ),
        **features,
    }


def stage63_classify_table_units(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> list[dict[str, Any]]:
    diagnostics: list[
        dict[str, Any]
    ] = []

    for item in reading_page.get(
        "reading_order",
        [],
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        if (
            item.get(
                "block_type"
            )
            != "table"
        ):
            continue

        diagnostics.append(
            stage63_classify_table_unit(
                raw_page,
                reading_page,
                item,
            )
        )

    return diagnostics



def stage63_table_candidate_text_blob(
    candidate: dict[str, Any],
) -> str:
    extracted = candidate.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        list,
    ):
        return ""

    parts: list[str] = []

    for row in extracted:
        if not isinstance(
            row,
            list,
        ):
            continue

        for cell in row:
            value = clean_text(
                cell
                if cell is not None
                else ""
            )

            if value:
                parts.append(
                    value
                )

    return "\n".join(
        parts
    )


def stage63_sequence_match_coverage(
    needle_text: str,
    haystack_text: str,
) -> float:
    """
    needle 中有多少字符能按顺序在 haystack 中匹配到。

    用 matching blocks 的覆盖率，而不是整体 ratio：
    container 文本通常远长于一个 native text block，
    整体 ratio 会被长度差稀释。
    """
    needle_norm = (
        stage63_layout_match_text(
            needle_text
        )
    )
    haystack_norm = (
        stage63_layout_match_text(
            haystack_text
        )
    )

    if not needle_norm or not haystack_norm:
        return 0.0

    matcher = SequenceMatcher(
        None,
        needle_norm,
        haystack_norm,
        autojunk=False,
    )

    matched = sum(
        block.size
        for block in matcher.get_matching_blocks()
    )

    return (
        matched
        / len(needle_norm)
    )


def stage63_layout_container_native_suppressions(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    layout_container 已成为正文权威来源后，
    抑制“同一区域内、而且文本已被 extracted_data 表示”的 native text。

    这解决的是 logical-flow 去重，不修改任何 Stage1/Stage4 证据。
    """
    reading_order = reading_page.get(
        "reading_order",
        [],
    )

    table_diagnostics = (
        stage63_classify_table_units(
            raw_page,
            reading_page,
        )
    )

    diagnostic_by_order = {
        int(item["reading_order"]):
            item
        for item in table_diagnostics
        if (
            item.get(
                "reading_order"
            )
            is not None
            and item.get(
                "classification"
            )
            == "layout_container"
        )
    }

    if not diagnostic_by_order:
        return []

    table_items_by_order = {
        int(item.get("reading_order", 0) or 0):
            item
        for item in reading_order
        if (
            isinstance(item, dict)
            and item.get(
                "block_type"
            )
            == "table"
        )
    }

    containers: list[
        dict[str, Any]
    ] = []

    for order, diagnostic in diagnostic_by_order.items():
        table_item = table_items_by_order.get(
            order
        )

        if table_item is None:
            continue

        candidate = (
            stage63_match_table_candidate(
                raw_page,
                table_item,
            )
        )

        if candidate is None:
            continue

        bbox = table_item.get(
            "bbox"
        )

        if not isinstance(
            bbox,
            dict,
        ):
            continue

        blob = (
            stage63_table_candidate_text_blob(
                candidate
            )
        )

        containers.append(
            {
                "reading_order": order,
                "block_id":
                    table_item.get(
                        "block_id"
                    ),
                "bbox": bbox,
                "text_blob": blob,
                "diagnostic": diagnostic,
            }
        )

    if not containers:
        return []

    exact_noise_texts = (
        stage63_exact_noise_texts(
            reading_page
        )
    )

    suppressions: list[
        dict[str, Any]
    ] = []

    for item in reading_order:
        if not isinstance(
            item,
            dict,
        ):
            continue

        if (
            item.get(
                "block_type"
            )
            != "text"
        ):
            continue

        item_bbox = item.get(
            "bbox"
        )

        if not isinstance(
            item_bbox,
            dict,
        ):
            continue

        item_area = (
            stage63_bbox_area(
                item_bbox
            )
        )

        if item_area <= 0:
            continue

        preview = clean_text(
            item.get(
                "text_preview",
                "",
            )
        )

        for container in containers:
            overlap_area = (
                stage63_bbox_intersection_area(
                    item_bbox,
                    container["bbox"],
                )
            )

            bbox_coverage = (
                overlap_area
                / item_area
            )

            if (
                bbox_coverage
                < LAYOUT_CONTAINER_NATIVE_TEXT_MIN_BBOX_COVERAGE
            ):
                continue

            # 已确认的独立水印 text unit：
            # 若它主要位于 layout_container 内，直接从 logical flow 去重。
            if (
                preview
                and preview
                in exact_noise_texts
            ):
                suppressions.append(
                    {
                        "reading_order":
                            int(
                                item.get(
                                    "reading_order",
                                    0,
                                )
                                or 0
                            ),
                        "block_id":
                            item.get(
                                "block_id"
                            ),
                        "container_reading_order":
                            container[
                                "reading_order"
                            ],
                        "container_block_id":
                            container[
                                "block_id"
                            ],
                        "reason":
                            "exact_confirmed_noise_inside_layout_container",
                        "bbox_coverage":
                            round(
                                bbox_coverage,
                                4,
                            ),
                        "preview":
                            preview,
                        "text_match_coverage":
                            None,
                    }
                )
                break

            if (
                len(
                    stage63_layout_match_text(
                        preview
                    )
                )
                < LAYOUT_CONTAINER_NATIVE_TEXT_MIN_PREVIEW_CHARS
            ):
                continue

            match_coverage = (
                stage63_sequence_match_coverage(
                    preview,
                    container[
                        "text_blob"
                    ],
                )
            )

            if (
                match_coverage
                < LAYOUT_CONTAINER_NATIVE_TEXT_MIN_MATCH_COVERAGE
            ):
                continue

            suppressions.append(
                {
                    "reading_order":
                        int(
                            item.get(
                                "reading_order",
                                0,
                            )
                            or 0
                        ),
                    "block_id":
                        item.get(
                            "block_id"
                        ),
                    "container_reading_order":
                        container[
                            "reading_order"
                        ],
                    "container_block_id":
                        container[
                            "block_id"
                        ],
                    "reason":
                        "text_already_represented_by_layout_container",
                    "bbox_coverage":
                        round(
                            bbox_coverage,
                            4,
                        ),
                    "preview":
                        preview,
                    "text_match_coverage":
                        round(
                            match_coverage,
                            4,
                        ),
                }
            )
            break

    return suppressions


def stage63_prepare_effective_text_units(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> list[dict[str, Any]]:
    table_diagnostics = (
        stage63_classify_table_units(
            raw_page,
            reading_page,
        )
    )

    table_class_by_order = {
        int(item["reading_order"]):
            item
        for item in table_diagnostics
        if item.get(
            "reading_order"
        ) is not None
    }

    # 不在 Stage4 / Stage6.2 reading-unit 粒度提前删除 native text。
    #
    # 原因：
    # 一个 reading unit 可能同时覆盖“应保留正文 + layout_container 已表示正文”，
    # 用 unit 的大 bbox / text_preview 做 suppression 过粗。
    #
    # 统一改为：
    # line -> paragraph 重建完成以后，
    # 再用实际 paragraph bbox + 实际 paragraph text 做 authority 去重。
    effective: list[
        dict[str, Any]
    ] = []

    for item in reading_page.get(
        "reading_order",
        [],
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue

        block_type = item.get(
            "block_type"
        )

        if block_type == "text":
            copied = dict(item)
            copied[
                "stage63_source_kind"
            ] = "native_text"
            effective.append(
                copied
            )
            continue

        if block_type != "table":
            continue

        order = int(
            item.get(
                "reading_order",
                0,
            )
            or 0
        )

        diagnostic = (
            table_class_by_order.get(
                order,
                {},
            )
        )

        if (
            diagnostic.get(
                "classification"
            )
            != "layout_container"
        ):
            continue

        copied = dict(item)
        copied[
            "block_type"
        ] = "text"
        copied[
            "stage63_source_kind"
        ] = "layout_container"
        copied[
            "table_classification"
        ] = diagnostic

        # 让 empty-unit 风险逻辑知道：这个容器本身确实承载了文本。
        copied[
            "text_preview"
        ] = (
            "layout_container_text"
        )

        effective.append(
            copied
        )

    effective.sort(
        key=lambda item: int(
            item.get(
                "reading_order",
                0,
            )
            or 0
        )
    )

    return effective



def stage63_normalize_preserved_line(
    value: Any,
) -> str:
    """
    NFKC + 单行空白归一化。

    与 clean_text 不同，这个函数只处理“单行”，
    不会把一个 cell 的多个原始换行压成一行。
    """
    if value is None:
        return ""

    normalized = unicodedata.normalize(
        "NFKC",
        str(value),
    )

    return re.sub(
        r"[ \t\f\v]+",
        " ",
        normalized,
    ).strip()


def stage63_exact_noise_texts(
    reading_page: dict[str, Any],
) -> set[str]:
    """
    只拿 Stage6.1 已经 auto_remove 的 watermark 文本。

    注意：
    - 这里只用于 layout_container 的“独立整行完全匹配”；
    - 不做 substring 删除；
    - 不删除混有正常正文的行。
    """
    values: set[str] = set()

    for region in reading_page.get(
        "ignored_noise_regions",
        [],
    ):
        if not isinstance(
            region,
            dict,
        ):
            continue

        value = clean_text(
            region.get(
                "text"
            )
        )

        if value:
            values.add(
                value
            )

    for excluded in reading_page.get(
        "excluded_noise_blocks",
        [],
    ):
        if not isinstance(
            excluded,
            dict,
        ):
            continue

        if (
            excluded.get(
                "reason"
            )
            not in {
                "standalone_auto_remove_watermark",
                "watermark",
            }
        ):
            continue

        value = clean_text(
            excluded.get(
                "text_preview"
            )
        )

        if value:
            values.add(
                value
            )

    return values


def stage63_is_exact_noise_line(
    line_text: str,
    noise_texts: set[str],
) -> bool:
    normalized = clean_text(
        line_text
    )

    if not normalized:
        return False

    return normalized in noise_texts



def stage63_layout_match_text(
    value: Any,
) -> str:
    normalized = unicodedata.normalize(
        "NFKC",
        str(
            value
            if value is not None
            else ""
        ),
    ).lower()

    # 只去空白。标点保留给 SequenceMatcher 自己容错，
    # 避免过度归一化导致短文本误匹配。
    return re.sub(
        r"\s+",
        "",
        normalized,
    )


def stage63_layout_is_enumeration_line(
    value: Any,
) -> bool:
    text = stage63_normalize_preserved_line(
        value
    )

    if not text:
        return False

    return bool(
        re.match(
            r"^(?:"
            r"[（(]\s*\d{1,3}\s*[）)]"
            r"|"
            r"(?:\d{1,3}|[一二三四五六七八九十百]+)\s*[.．、]"
            r")",
            text,
        )
    )


def stage63_layout_is_heading_like_line(
    value: Any,
) -> bool:
    text = stage63_normalize_preserved_line(
        value
    )

    if not text:
        return False

    if (
        len(text)
        > LAYOUT_PARAGRAPH_HEADING_MAX_CHARS
    ):
        return False

    # 枚举项即使内部带冒号，也优先按 list item 处理。
    if stage63_layout_is_enumeration_line(
        text
    ):
        return False

    return text.endswith(
        (
            ":",
            "：",
        )
    )


def stage63_layout_raw_visual_lines(
    raw_page: dict[str, Any],
    candidate_bbox: dict[str, Any],
    noise_texts: set[str],
) -> list[dict[str, Any]]:
    words = raw_page.get(
        "words",
        [],
    )

    if not isinstance(
        words,
        list,
    ):
        return []

    selected: list[
        dict[str, Any]
    ] = []

    for word in words:
        if not isinstance(
            word,
            dict,
        ):
            continue

        bbox = stage63_word_bbox(
            word
        )

        if bbox is None:
            continue

        if not stage63_center_inside(
            bbox,
            candidate_bbox,
            tolerance=1.5,
        ):
            continue

        copied = dict(word)
        selected.append(
            copied
        )

    visual_lines = (
        stage63_group_words_into_lines(
            selected
        )
    )

    result: list[
        dict[str, Any]
    ] = []

    for index, line in enumerate(
        visual_lines,
        start=1,
    ):
        line_text = stage63_normalize_preserved_line(
            line.get(
                "text",
                "",
            )
        )

        if not line_text:
            continue

        if stage63_is_exact_noise_line(
            line_text,
            noise_texts,
        ):
            continue

        copied = dict(line)
        copied[
            "visual_line_index"
        ] = index
        copied[
            "match_text"
        ] = stage63_layout_match_text(
            line_text
        )
        result.append(
            copied
        )

    return result


def stage63_attach_layout_visual_evidence(
    records: list[dict[str, Any]],
    raw_page: dict[str, Any],
    candidate_bbox: dict[str, Any],
    noise_texts: set[str],
) -> dict[str, Any]:
    """
    extracted_data 决定内容顺序；
    raw visual lines 只提供段落边界弱证据。

    因为某些 PDF 的原生 y 顺序本身会错，所以：
    - 不用 visual y 重新排序内容；
    - 只做文本相似匹配；
    - 若同一 cell 的 visual y 出现明显逆序，则禁用该 cell 的“行距断段”；
    - 首行缩进仍可作为弱证据。
    """
    visual_lines = (
        stage63_layout_raw_visual_lines(
            raw_page,
            candidate_bbox,
            noise_texts,
        )
    )

    used_visual_indices: set[int] = set()

    matched_count = 0
    scores: list[float] = []

    for record in records:
        target = stage63_layout_match_text(
            record.get(
                "text",
                "",
            )
        )

        best_index: int | None = None
        best_score = 0.0

        if target:
            for index, visual in enumerate(
                visual_lines
            ):
                if index in used_visual_indices:
                    continue

                source = visual.get(
                    "match_text",
                    "",
                )

                if not source:
                    continue

                score = SequenceMatcher(
                    None,
                    target,
                    source,
                    autojunk=False,
                ).ratio()

                if score > best_score:
                    best_score = score
                    best_index = index

        if (
            best_index is None
            or best_score
            < LAYOUT_PARAGRAPH_VISUAL_MATCH_MIN_SCORE
        ):
            record[
                "visual_match_score"
            ] = round(
                best_score,
                4,
            )
            record[
                "visual_match_found"
            ] = False
            continue

        used_visual_indices.add(
            best_index
        )

        visual = visual_lines[
            best_index
        ]

        bbox = visual.get(
            "bbox",
            {},
        )

        record[
            "visual_match_found"
        ] = True
        record[
            "visual_match_score"
        ] = round(
            best_score,
            4,
        )
        record[
            "visual_line_index"
        ] = visual.get(
            "visual_line_index"
        )
        record[
            "visual_x0"
        ] = bbox.get(
            "x0"
        )
        record[
            "visual_top"
        ] = bbox.get(
            "top"
        )
        record[
            "visual_bottom"
        ] = bbox.get(
            "bottom"
        )
        record[
            "visual_median_word_height"
        ] = visual.get(
            "median_word_height"
        )

        matched_count += 1
        scores.append(
            best_score
        )

    # 每个 cell 单独判断 visual y 是否可信。
    by_cell: dict[
        str,
        list[dict[str, Any]]
    ] = defaultdict(list)

    for record in records:
        key = str(
            record.get(
                "layout_container_cell_key",
                "",
            )
        )
        by_cell[
            key
        ].append(
            record
        )

    unreliable_cells: list[str] = []

    for cell_key, cell_records in by_cell.items():
        inversion_count = 0
        previous: dict[str, Any] | None = None

        for record in cell_records:
            if not record.get(
                "visual_match_found"
            ):
                continue

            if previous is None:
                previous = record
                continue

            previous_top = float(
                previous.get(
                    "visual_top",
                    0.0,
                )
            )
            current_top = float(
                record.get(
                    "visual_top",
                    0.0,
                )
            )

            height_ref = max(
                1.0,
                float(
                    previous.get(
                        "visual_median_word_height",
                        8.0,
                    )
                    or 8.0
                ),
                float(
                    record.get(
                        "visual_median_word_height",
                        8.0,
                    )
                    or 8.0
                ),
            )

            tolerance = (
                height_ref
                * LAYOUT_PARAGRAPH_ORDER_INVERSION_TOL_HEIGHT_RATIO
            )

            if (
                current_top
                + tolerance
                < previous_top
            ):
                inversion_count += 1

            previous = record

        reliable = (
            inversion_count == 0
        )

        if not reliable:
            unreliable_cells.append(
                cell_key
            )

        for record in cell_records:
            record[
                "visual_sequence_reliable"
            ] = reliable
            record[
                "visual_order_inversion_count"
            ] = inversion_count

    return {
        "visual_line_count":
            len(
                visual_lines
            ),
        "matched_visual_line_count":
            matched_count,
        "visual_match_rate":
            round(
                (
                    matched_count
                    / len(records)
                    if records
                    else 0.0
                ),
                4,
            ),
        "median_visual_match_score":
            round(
                median_number(
                    scores
                )
                or 0.0,
                4,
            ),
        "unreliable_visual_order_cell_count":
            len(
                unreliable_cells
            ),
        "unreliable_visual_order_cells":
            unreliable_cells,
    }


def stage63_layout_container_break_reason(
    paragraph: dict[str, Any],
    previous: dict[str, Any],
    current: dict[str, Any],
) -> tuple[
    bool,
    str,
]:
    current_text = current.get(
        "text",
        "",
    )

    previous_text = previous.get(
        "text",
        "",
    )

    # 结构性标题单独成段。
    if stage63_layout_is_heading_like_line(
        current_text
    ):
        return (
            True,
            "layout_heading_line",
        )

    if stage63_layout_is_heading_like_line(
        previous_text
    ):
        return (
            True,
            "after_layout_heading",
        )

    # 新的编号项作为新段开始。
    if stage63_layout_is_enumeration_line(
        current_text
    ):
        return (
            True,
            "layout_enumeration_item",
        )

    # 如果上一行本身是编号项标题，下一行优先视作该 item 的正文，
    # 不因为缩进或视觉行距把它拆开。
    if stage63_layout_is_enumeration_line(
        previous_text
    ):
        return (
            False,
            "after_layout_enumeration",
        )

    # 首行缩进：对 layout_container 长正文非常常见。
    if current.get(
        "visual_match_found"
    ):
        baseline_x0 = median_number(
            [
                float(
                    line[
                        "visual_x0"
                    ]
                )
                for line in paragraph.get(
                    "lines",
                    []
                )[-4:]
                if (
                    line.get(
                        "visual_match_found"
                    )
                    and line.get(
                        "visual_x0"
                    )
                    is not None
                )
            ]
        )

        current_x0 = current.get(
            "visual_x0"
        )

        height_ref = float(
            current.get(
                "visual_median_word_height",
                8.0,
            )
            or 8.0
        )

        if (
            baseline_x0 is not None
            and current_x0 is not None
            and (
                float(current_x0)
                - baseline_x0
            )
            > (
                height_ref
                * LAYOUT_PARAGRAPH_INDENT_HEIGHT_RATIO
            )
        ):
            return (
                True,
                "layout_first_line_indent",
            )

    # 视觉顺序可靠时，大行距可作为自然段边界。
    if (
        previous.get(
            "visual_match_found"
        )
        and current.get(
            "visual_match_found"
        )
        and previous.get(
            "visual_sequence_reliable"
        )
        and current.get(
            "visual_sequence_reliable"
        )
    ):
        previous_top = float(
            previous.get(
                "visual_top",
                0.0,
            )
        )
        current_top = float(
            current.get(
                "visual_top",
                0.0,
            )
        )

        # 只有 visual y 确实向下推进才使用 gap。
        if current_top >= previous_top:
            gap = (
                float(
                    current.get(
                        "visual_top",
                        0.0,
                    )
                )
                - float(
                    previous.get(
                        "visual_bottom",
                        0.0,
                    )
                )
            )

            height_ref = max(
                1.0,
                float(
                    previous.get(
                        "visual_median_word_height",
                        8.0,
                    )
                    or 8.0
                ),
                float(
                    current.get(
                        "visual_median_word_height",
                        8.0,
                    )
                    or 8.0
                ),
            )

            if (
                gap
                > (
                    height_ref
                    * LAYOUT_PARAGRAPH_LARGE_GAP_HEIGHT_RATIO
                )
            ):
                return (
                    True,
                    "layout_large_visual_gap",
                )

    return (
        False,
        "layout_container_cell_continuation",
    )



def stage63_cell_bbox_from_candidate(
    candidate: dict[str, Any],
    row_index_zero: int,
    cell_index_zero: int,
) -> dict[str, float] | None:
    rows = candidate.get("rows")
    if not isinstance(rows, list):
        return None
    if not (0 <= row_index_zero < len(rows)):
        return None

    row = rows[row_index_zero]
    if not isinstance(row, dict):
        return None

    cells = row.get("cells")
    if not isinstance(cells, list):
        return None
    if not (0 <= cell_index_zero < len(cells)):
        return None

    cell = cells[cell_index_zero]
    if not isinstance(cell, dict):
        return None

    return normalize_bbox(cell)


def stage63_confirmed_watermark_word_rewrites(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    找出被 Stage6.1 几何证据确认污染的 Stage1 raw word，
    记录“原 raw word -> 去水印后的 word”。

    重要：
    - 不按固定字符值匹配；
    - 先由 confirmed watermark occurrence + char geometry 精确确认；
    - 后续 layout_container 只替换这个完整 raw word，不做全局 substring 清洗。
    """
    regions = [
        item
        for item in reading_page.get(
            "ignored_noise_regions",
            [],
        )
        if isinstance(item, dict)
    ]

    if not regions:
        return []

    rewrites: list[dict[str, Any]] = []

    for raw_word in raw_page.get("words", []):
        if not isinstance(raw_word, dict):
            continue

        original = stage63_normalize_preserved_line(
            raw_word.get("text")
        )

        if not original:
            continue

        cleaned_word, removed, rewritten = (
            stage63_strip_confirmed_watermark_from_word(
                raw_word,
                raw_page,
                regions,
            )
        )

        if not rewritten or int(removed or 0) <= 0:
            continue

        cleaned = (
            stage63_normalize_preserved_line(
                cleaned_word.get("text")
            )
            if isinstance(cleaned_word, dict)
            else ""
        )

        if cleaned == original:
            continue

        word_bbox = stage63_word_bbox(raw_word)
        if word_bbox is None:
            continue

        rewrites.append(
            {
                "original": original,
                "cleaned": cleaned,
                "bbox": word_bbox,
                "removed_count": int(removed or 0),
            }
        )

    return rewrites


def stage63_apply_confirmed_watermark_rewrites_to_cell(
    value: Any,
    cell_bbox: dict[str, float] | None,
    rewrites: list[dict[str, Any]],
) -> tuple[str, int]:
    """
    对 layout_container 的单个 extracted_data cell 做保守清洗。

    只允许使用：
    1) 已经由 char geometry 确认污染的 raw word；
    2) 该 raw word 与当前 cell geometry 相交；
    3) extracted_data 中能找到完整 original raw word。

    因此不会把某个水印字符值在整段文本里全局 replace。
    """
    text_value = (
        ""
        if value is None
        else str(value)
    )

    if not text_value or cell_bbox is None or not rewrites:
        return text_value, 0

    removed = 0

    for item in rewrites:
        word_bbox = item.get("bbox")
        if not isinstance(word_bbox, dict):
            continue

        if (
            bbox_intersection_area(
                word_bbox,
                cell_bbox,
            )
            <= 0
        ):
            continue

        original = str(
            item.get("original") or ""
        )
        cleaned = str(
            item.get("cleaned") or ""
        )

        if not original:
            continue

        # extracted_data 的 cell 按行保留；逐行做完整 raw-word 替换，
        # 只替换一次，避免误伤同 cell 内其它同值字符。
        raw_lines = text_value.splitlines()
        changed = False
        new_lines: list[str] = []

        for raw_line in raw_lines:
            normalized_line = (
                stage63_normalize_preserved_line(
                    raw_line
                )
            )

            if (
                not changed
                and original
                in normalized_line
            ):
                normalized_line = (
                    normalized_line.replace(
                        original,
                        cleaned,
                        1,
                    )
                )
                changed = True

            new_lines.append(
                normalized_line
            )

        if changed:
            text_value = "\n".join(
                new_lines
            )
            removed += int(
                item.get(
                    "removed_count",
                    1,
                )
                or 1
            )

    return text_value, removed


def stage63_layout_container_ordered_lines(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
    unit: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    """
    对 layout_container 不再重新按 raw word y/x 猜内部顺序。

    优先复用 Stage1 table_candidates.extracted_data：
    - 它已经按 table cell / cell 内换行给出了稳定顺序；
    - Stage6.3 只把这些文本作为 logical text flow；
    - Stage1 / Stage4 原 table evidence 不修改。

    每个非空 cell 作为一个 paragraph boundary。
    cell 内原始换行保留，后续 6.5 再做断词/换行规范化。
    """
    candidate = (
        stage63_match_table_candidate(
            raw_page,
            unit,
        )
    )

    if candidate is None:
        return (
            [],
            {
                "status":
                    "no_matching_table_candidate",
                "line_count": 0,
                "cell_count": 0,
                "removed_exact_noise_line_count":
                    0,
                "removed_embedded_noise_count":
                    0,
            },
        )

    extracted = candidate.get(
        "extracted_data"
    )

    if not isinstance(
        extracted,
        list,
    ):
        return (
            [],
            {
                "status":
                    "no_extracted_data",
                "line_count": 0,
                "cell_count": 0,
                "removed_exact_noise_line_count":
                    0,
                "removed_embedded_noise_count":
                    0,
            },
        )

    noise_texts = (
        stage63_exact_noise_texts(
            reading_page
        )
    )

    embedded_noise_rewrites = (
        stage63_confirmed_watermark_word_rewrites(
            raw_page,
            reading_page,
        )
    )

    bbox = unit.get(
        "bbox"
    )

    if not isinstance(
        bbox,
        dict,
    ):
        return (
            [],
            {
                "status":
                    "invalid_unit_bbox",
                "line_count": 0,
                "cell_count": 0,
                "removed_exact_noise_line_count":
                    0,
                "removed_embedded_noise_count":
                    0,
            },
        )

    ordered_cells: list[
        tuple[
            int,
            int,
            list[str],
        ]
    ] = []

    removed_noise_lines: list[str] = []
    removed_embedded_noise_count = 0

    for row_index, row in enumerate(
        extracted,
        start=1,
    ):
        if not isinstance(
            row,
            list,
        ):
            continue

        for cell_index, cell in enumerate(
            row,
            start=1,
        ):
            if cell is None:
                continue

            cell_bbox = (
                stage63_cell_bbox_from_candidate(
                    candidate,
                    row_index - 1,
                    cell_index - 1,
                )
            )

            cleaned_cell, embedded_removed = (
                stage63_apply_confirmed_watermark_rewrites_to_cell(
                    cell,
                    cell_bbox,
                    embedded_noise_rewrites,
                )
            )

            removed_embedded_noise_count += int(
                embedded_removed
            )

            raw_lines = str(
                cleaned_cell
            ).splitlines()

            cleaned_lines: list[str] = []

            for raw_line in raw_lines:
                line = (
                    stage63_normalize_preserved_line(
                        raw_line
                    )
                )

                if not line:
                    continue

                if (
                    stage63_is_exact_noise_line(
                        line,
                        noise_texts,
                    )
                ):
                    removed_noise_lines.append(
                        line
                    )
                    continue

                cleaned_lines.append(
                    line
                )

            if cleaned_lines:
                ordered_cells.append(
                    (
                        row_index,
                        cell_index,
                        cleaned_lines,
                    )
                )

    total_line_count = sum(
        len(lines)
        for _, _, lines
        in ordered_cells
    )

    if total_line_count == 0:
        return (
            [],
            {
                "status":
                    "empty_after_filter",
                "line_count": 0,
                "cell_count":
                    len(
                        ordered_cells
                    ),
                "removed_exact_noise_line_count":
                    len(
                        removed_noise_lines
                    ),
                "removed_exact_noise_lines":
                    removed_noise_lines,
                "removed_embedded_noise_count":
                    removed_embedded_noise_count,
            },
        )

    top = float(
        bbox["top"]
    )
    bottom = float(
        bbox["bottom"]
    )
    x0 = float(
        bbox["x0"]
    )
    x1 = float(
        bbox["x1"]
    )

    usable_height = max(
        1.0,
        bottom - top,
    )

    synthetic_step = (
        usable_height
        / max(
            1,
            total_line_count,
        )
    )

    # 只用于保持 cell 内部顺序以及后续审计。
    # 不把 synthetic bbox 当作真实 PDF 几何。
    synthetic_height = max(
        1.0,
        min(
            synthetic_step * 0.8,
            10.0,
        ),
    )

    records: list[
        dict[str, Any]
    ] = []

    line_cursor = 0

    for (
        row_index,
        cell_index,
        cell_lines,
    ) in ordered_cells:
        cell_key = (
            f"r{row_index}c{cell_index}"
        )

        for line_in_cell, line_text in enumerate(
            cell_lines,
            start=1,
        ):
            line_top = (
                top
                + line_cursor
                * synthetic_step
            )

            line_bottom = min(
                bottom,
                line_top
                + synthetic_height,
            )

            if line_bottom <= line_top:
                line_bottom = (
                    line_top
                    + 1.0
                )

            records.append(
                {
                    "source_line_index":
                        line_in_cell,
                    "layout_container_row":
                        row_index,
                    "layout_container_cell":
                        cell_index,
                    "layout_container_cell_key":
                        cell_key,
                    "stage63_source_kind":
                        "layout_container_ordered_text",
                    "bbox": {
                        "x0": x0,
                        "top": line_top,
                        "x1": x1,
                        "bottom": line_bottom,
                    },
                    "word_count":
                        max(
                            1,
                            len(
                                re.findall(
                                    r"\S+",
                                    line_text,
                                )
                            ),
                        ),
                    "char_count":
                        len(
                            line_text
                        ),
                    "median_word_height":
                        synthetic_height,
                    "text":
                        line_text,
                    "source_word_indices":
                        [],
                    "synthetic_geometry":
                        True,
                }
            )

            line_cursor += 1

    visual_diagnostics = (
        stage63_attach_layout_visual_evidence(
            records,
            raw_page,
            bbox,
            noise_texts,
        )
    )

    return (
        records,
        {
            "status":
                "completed",
            "source_table_index":
                candidate.get(
                    "table_index"
                ),
            "cell_count":
                len(
                    ordered_cells
                ),
            "line_count":
                len(
                    records
                ),
            "removed_exact_noise_line_count":
                len(
                    removed_noise_lines
                ),
            "removed_exact_noise_lines":
                removed_noise_lines,
            "removed_embedded_noise_count":
                removed_embedded_noise_count,
            "noise_filter_mode":
                "confirmed_geometry_word_rewrite_plus_exact_whole_line",
            "uses_stage1_extracted_data":
                True,
            **visual_diagnostics,
        },
    )




def stage63_char_matches_confirmed_watermark(
    char: dict[str, Any],
    region: dict[str, Any],
) -> bool:
    """
    字符级确认 watermark occurrence。

    不使用任何固定字符表；只匹配 Stage6.1 已确认 occurrence 自带的：
    exact text + fontname + font size + rotation + bbox。
    """
    char_text = clean_text(char.get("text"))
    noise_text = clean_text(region.get("text"))

    if not char_text or not noise_text or char_text != noise_text:
        return False

    region_font = clean_text(region.get("fontname"))
    char_font = clean_text(char.get("fontname"))

    if region_font and char_font and region_font != char_font:
        return False

    region_size = region.get("font_size")
    char_size = char.get("size")

    if finite_number(region_size) and finite_number(char_size):
        if abs(float(region_size) - float(char_size)) > 1.0:
            return False

    char_rotation = char_rotation_strength(char)
    region_rotation = region.get("rotation_strength")

    if char_rotation < 0.20:
        return False

    if finite_number(region_rotation):
        if abs(char_rotation - float(region_rotation)) > 0.20:
            return False

    char_bbox_value = raw_char_bbox(char)
    region_bbox = region.get("bbox")

    if char_bbox_value is None or not isinstance(region_bbox, dict):
        return False

    max_delta = max(
        abs(char_bbox_value["x0"] - float(region_bbox["x0"])),
        abs(char_bbox_value["top"] - float(region_bbox["top"])),
        abs(char_bbox_value["x1"] - float(region_bbox["x1"])),
        abs(char_bbox_value["bottom"] - float(region_bbox["bottom"])),
    )

    return max_delta <= 1.5


def stage63_remove_one_substring(
    value: str,
    token: str,
) -> tuple[str, bool]:
    if not value or not token:
        return value, False

    index = value.find(token)
    if index < 0:
        return value, False

    return (
        value[:index]
        + value[index + len(token):],
        True,
    )


def stage63_select_cleaned_word_char_band(
    word_bbox: dict[str, float],
    cleaned_text: str,
    kept_chars: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    在“被旋转水印拉高/拉宽的 Stage1 word bbox”内部，找回真正属于该 word 的
    单一物理文本行 bbox。

    背景：pdfplumber 可能把一个旋转大字水印字符粘进普通正文 word，导致 raw word
    的 bbox 跨越后续多行。若仅把 watermark 字符从 text 删除、再对巨型 bbox 内所有
    非水印 chars 做 union，会把邻近正文行也吸进 cleaned word，继续污染 Stage6.3
    行聚合和 reading order。

    这里不使用页码/固定字符串，只使用：
    1) 已确认去除 watermark 后的 cleaned_text；
    2) char 真实几何；
    3) raw word 原始 top 作为“该 word 起始物理行”的弱锚点。

    做法：
    - 将非水印 chars 按垂直基线聚成若干 visual bands；
    - 对每个 band 按 x 排序后与 cleaned_text 做字符序列相似度；
    - 优先选择文本匹配高、且 top 最接近 raw word.top 的 band；
    - 返回该 band 的 bbox + 真实字符序列。bbox 只取该物理行，绝不把后续物理行一起 union；
    - v0.3.16 同时保留 band_text，用于解决“正文字符与水印字符同字形”时误删了错误 occurrence 的问题。
    """
    if not kept_chars or not cleaned_text:
        return None

    # 只在 Stage6.3 内部使用，避免依赖更宽松的全局 boundary-line 容差。
    y_tolerance = max(
        PARAGRAPH_LINE_Y_TOLERANCE,
        2.5,
    )

    ordered = sorted(
        kept_chars,
        key=lambda item: (
            float(item["bbox"]["top"]),
            float(item["bbox"]["x0"]),
        ),
    )

    bands: list[list[dict[str, Any]]] = []

    for item in ordered:
        bbox = item["bbox"]
        center_y = (
            float(bbox["top"])
            + float(bbox["bottom"])
        ) / 2.0

        best_index: int | None = None
        best_delta: float | None = None

        for index, band in enumerate(bands):
            centers = [
                (
                    float(member["bbox"]["top"])
                    + float(member["bbox"]["bottom"])
                ) / 2.0
                for member in band
            ]
            band_center = median_number(centers)
            if band_center is None:
                continue

            heights = [
                max(
                    1.0,
                    float(member["bbox"]["bottom"])
                    - float(member["bbox"]["top"]),
                )
                for member in band
            ]
            band_height = median_number(heights) or 1.0
            current_height = max(
                1.0,
                float(bbox["bottom"])
                - float(bbox["top"]),
            )
            tolerance = max(
                y_tolerance,
                min(band_height, current_height)
                * PARAGRAPH_LINE_Y_HEIGHT_RATIO,
            )
            delta = abs(center_y - band_center)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_index = index
                best_delta = delta

        if best_index is None:
            bands.append([item])
        else:
            bands[best_index].append(item)

    target_norm = stage63_layout_match_text(cleaned_text)
    if not target_norm:
        return None

    best_band: list[dict[str, Any]] | None = None
    best_score: tuple[float, float, int] | None = None

    for band in bands:
        spatial = sorted(
            band,
            key=lambda item: (
                float(item["bbox"]["x0"]),
                float(item["bbox"]["top"]),
            ),
        )
        band_text = "".join(
            str(item.get("text") or "")
            for item in spatial
        )
        band_norm = stage63_layout_match_text(band_text)
        if not band_norm:
            continue

        matcher = SequenceMatcher(
            None,
            target_norm,
            band_norm,
            autojunk=False,
        )
        ratio = matcher.ratio()

        band_bbox = stage63_bbox_union(
            [item["bbox"] for item in band]
        )
        if band_bbox is None:
            continue

        top_delta = abs(
            float(band_bbox["top"])
            - float(word_bbox["top"])
        )

        # ratio 为主；同分时选更接近 raw word 起始 top 的物理行；
        # 再同分时选字符更多的一行。
        score = (
            ratio,
            -top_delta,
            len(band_norm),
        )

        if best_score is None or score > best_score:
            best_score = score
            best_band = band

    if best_band is None or best_score is None:
        return None

    # 必须有较强文本支持；否则宁可不改 bbox，也不凭几何猜。
    if best_score[0] < 0.60:
        return None

    selected_bbox = stage63_bbox_union(
        [item["bbox"] for item in best_band]
    )
    if selected_bbox is None:
        return None

    selected_spatial = sorted(
        best_band,
        key=lambda item: (
            float(item["bbox"]["x0"]),
            float(item["bbox"]["top"]),
        ),
    )
    selected_text = clean_text(
        "".join(
            str(item.get("text") or "")
            for item in selected_spatial
        )
    ).strip()

    return {
        "bbox": selected_bbox,
        "text": selected_text,
        "match_ratio": float(best_score[0]),
    }


def stage63_strip_confirmed_watermark_from_word(
    word: dict[str, Any],
    raw_page: dict[str, Any],
    regions: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int, bool]:
    """
    从 Stage1 word 中移除已被 Stage6.1 occurrence 精确确认的水印字符。

    不按字符值全局 replace；Stage1 原 evidence 不修改。

    v0.3.15 额外修复：
    若旋转水印把 raw word bbox 拉成跨多行巨型 bbox，删除 watermark 字符后不能
    对 bbox 内“所有剩余 chars”做 union；否则邻近正文行会被误吸进 cleaned word。
    改为按 char baseline + cleaned_text 匹配选回真正单一物理行。
    """
    if not regions:
        return dict(word), 0, False

    word_bbox = stage63_word_bbox(word)

    if word_bbox is None:
        return dict(word), 0, False

    intersecting_regions = [
        region
        for region in regions
        if isinstance(region.get("bbox"), dict)
        and bbox_intersection_area(
            word_bbox,
            region["bbox"],
        ) > 0
    ]

    if not intersecting_regions:
        return dict(word), 0, False

    matched_regions: list[dict[str, Any]] = []
    kept_chars: list[dict[str, Any]] = []

    for char in raw_page.get("chars", []):
        if not isinstance(char, dict):
            continue

        char_bbox_value = raw_char_bbox(char)

        if char_bbox_value is None:
            continue

        center_x = (
            char_bbox_value["x0"]
            + char_bbox_value["x1"]
        ) / 2.0

        center_y = (
            char_bbox_value["top"]
            + char_bbox_value["bottom"]
        ) / 2.0

        if not point_inside_bbox(
            center_x,
            center_y,
            word_bbox,
            tolerance=1.0,
        ):
            continue

        matched_region = next(
            (
                region
                for region
                in intersecting_regions
                if stage63_char_matches_confirmed_watermark(
                    char,
                    region,
                )
            ),
            None,
        )

        if matched_region is not None:
            matched_regions.append(
                matched_region
            )
            continue

        kept_chars.append(
            {
                "text": char.get("text"),
                "bbox": char_bbox_value,
            }
        )

    if not matched_regions:
        return dict(word), 0, False

    cleaned_text = clean_text(
        word.get("text")
    )
    removed = 0

    # 同一个 watermark occurrence 可能因 bbox 搜索被重复遇到，
    # 这里按 occurrence 几何去重后再从 raw word text 中各删除一次。
    unique_regions: list[dict[str, Any]] = []
    seen_region_keys: set[tuple[Any, ...]] = set()
    for region in matched_regions:
        bbox = region.get("bbox") or {}
        key = (
            clean_text(region.get("text")),
            round(float(bbox.get("x0", 0.0)), 3),
            round(float(bbox.get("top", 0.0)), 3),
            round(float(bbox.get("x1", 0.0)), 3),
            round(float(bbox.get("bottom", 0.0)), 3),
        )
        if key in seen_region_keys:
            continue
        seen_region_keys.add(key)
        unique_regions.append(region)

    for region in unique_regions:
        token = clean_text(
            region.get("text")
        )

        cleaned_text, changed = (
            stage63_remove_one_substring(
                cleaned_text,
                token,
            )
        )

        if changed:
            removed += 1

    cleaned_text = cleaned_text.strip()

    # bbox 内存在 confirmed watermark char，并不等于当前 Stage1 word 的 text
    # 一定包含该 watermark token。若没有真正从 word text 删除任何字符，
    # 说明这个 word 只是几何上被水印 bbox 穿过；此时必须保持原 word/bbox 不变。
    if removed <= 0:
        return dict(word), 0, False

    if not cleaned_text:
        return None, removed, True

    copied = dict(word)
    copied["text"] = cleaned_text

    kept_band = stage63_select_cleaned_word_char_band(
        word_bbox=word_bbox,
        cleaned_text=cleaned_text,
        kept_chars=kept_chars,
    )

    if kept_band is not None:
        kept_bbox = kept_band.get("bbox")
        if isinstance(kept_bbox, dict):
            copied["x0"] = kept_bbox["x0"]
            copied["top"] = kept_bbox["top"]
            copied["x1"] = kept_bbox["x1"]
            copied["bottom"] = kept_bbox["bottom"]

        # 关键：若 char-band 与当前 cleaned_text 高匹配，优先信任
        # “排除已确认 watermark char 后的真实物理行字符序列”。
        # 这避免正文中存在同字形字符时，stage63_remove_one_substring
        # 误删第一个合法 occurrence，却把真正 watermark occurrence 留在后面。
        band_text = clean_text(kept_band.get("text")).strip()
        band_ratio = kept_band.get("match_ratio")
        if (
            band_text
            and finite_number(band_ratio)
            and float(band_ratio) >= 0.82
        ):
            copied["text"] = band_text

    return copied, removed, True


FORM_LABEL_MAX_CHARS = 24
FORM_LABEL_MIN_X_SHIFT = 18.0
FORM_LABEL_VALUE_X_TOLERANCE = 10.0
FORM_LABEL_MAX_VERTICAL_GAP_RATIO = 1.8
FORM_LABEL_INLINE_MAX_PREFIX_WORDS = 3


def stage63_split_inline_multiline_form_labels(
    lines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    把“左侧短 label 与右侧多行 value 的某一行处在同一视觉基线”拆开。

    典型几何不是按字段名判断，而是：
    - 当前视觉行左端存在一个很短、以 : / ：结尾的 label；
    - 同一视觉行右侧还有 value；
    - 前一行、后一行都从与该 value 近似相同的 x0 开始，说明右侧是多行 value run；
    - label 明显位于 value 列左侧。

    只做结构拆分，不改任何字符。拆开后继续交给
    stage63_reorder_multiline_form_labels 把 label 移到整段 value run 前面。
    """
    if len(lines) < 3:
        return lines, []

    output: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    def make_subline(
        source: dict[str, Any],
        words: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not words:
            return None

        bboxes = [
            item.get("bbox")
            for item in words
            if isinstance(item.get("bbox"), dict)
        ]
        bbox = stage63_bbox_union(bboxes)
        if bbox is None:
            return None

        word_texts = [
            clean_text(item.get("text"))
            for item in words
            if clean_text(item.get("text"))
        ]
        if not word_texts:
            return None

        copied = dict(source)
        copied["text"] = stage63_join_words(
            words
        )
        copied["bbox"] = bbox
        copied["word_count"] = len(words)
        copied["char_count"] = len(copied["text"])
        copied["source_word_indices"] = [
            int(item.get("source_word_index", -1))
            for item in words
        ]
        copied["median_word_height"] = round(
            median_number(
                [
                    float(item.get("height", 0.0) or 0.0)
                    for item in words
                    if float(item.get("height", 0.0) or 0.0) > 0
                ]
            )
            or float(source.get("median_word_height", 0.0) or 0.0),
            4,
        )
        copied["_stage63_words"] = [dict(item) for item in words]
        return copied

    for index, line in enumerate(lines):
        words = line.get("_stage63_words")

        if (
            index == 0
            or index >= len(lines) - 1
            or not isinstance(words, list)
            or len(words) < 2
        ):
            output.append(line)
            continue

        previous_bbox = lines[index - 1].get("bbox")
        following_bbox = lines[index + 1].get("bbox")

        if not isinstance(previous_bbox, dict) or not isinstance(following_bbox, dict):
            output.append(line)
            continue

        split_applied = False

        max_prefix = min(
            FORM_LABEL_INLINE_MAX_PREFIX_WORDS,
            len(words) - 1,
        )

        for split_at in range(1, max_prefix + 1):
            left_words = words[:split_at]
            right_words = words[split_at:]

            left_text = stage63_join_words(left_words)
            left_text = clean_text(left_text)

            if (
                not left_text
                or len(left_text) > FORM_LABEL_MAX_CHARS
                or not left_text.endswith((":", "："))
            ):
                continue

            left_bbox = stage63_bbox_union(
                [item.get("bbox") for item in left_words if isinstance(item.get("bbox"), dict)]
            )
            right_bbox = stage63_bbox_union(
                [item.get("bbox") for item in right_words if isinstance(item.get("bbox"), dict)]
            )

            if left_bbox is None or right_bbox is None:
                continue

            right_x = float(right_bbox["x0"])

            if right_x - float(left_bbox["x0"]) < FORM_LABEL_MIN_X_SHIFT:
                continue

            if float(left_bbox["x1"]) > right_x + FORM_LABEL_VALUE_X_TOLERANCE:
                continue

            # 必须由上下两行共同证明这里确实是同一个右侧多行 value run。
            if (
                abs(float(previous_bbox["x0"]) - right_x) > FORM_LABEL_VALUE_X_TOLERANCE
                or abs(float(following_bbox["x0"]) - right_x) > FORM_LABEL_VALUE_X_TOLERANCE
            ):
                continue

            label_height = max(
                1.0,
                float(left_bbox["bottom"]) - float(left_bbox["top"]),
            )
            max_gap = label_height * FORM_LABEL_MAX_VERTICAL_GAP_RATIO

            previous_gap = float(left_bbox["top"]) - float(previous_bbox["bottom"])
            following_gap = float(following_bbox["top"]) - float(left_bbox["bottom"])

            if previous_gap > max_gap or following_gap > max_gap:
                continue

            left_line = make_subline(line, left_words)
            right_line = make_subline(line, right_words)

            if left_line is None or right_line is None:
                continue

            output.extend([left_line, right_line])
            diagnostics.append(
                {
                    "text": left_text,
                    "source_line_index": index,
                    "value_x0": round(right_x, 4),
                    "reason": "inline_left_label_inside_multiline_value_run",
                }
            )
            split_applied = True
            break

        if not split_applied:
            output.append(line)

    return output, diagnostics


def stage63_reorder_multiline_form_labels(
    lines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    修复“左侧短 label 垂直居中、右侧 value 跨多行”造成的 y-sort 乱序。

    只用几何 + 标点：
    - label 短且以 : / ：结尾；
    - label 明显位于右侧 value 列左边；
    - label 前后都有 x0 对齐的 value line；
    - value run 纵向覆盖 label。

    不匹配具体字段名。
    """
    if len(lines) < 3:
        return lines, []

    working = [
        dict(line)
        for line in lines
    ]
    diagnostics: list[
        dict[str, Any]
    ] = []

    changed = True

    while changed:
        changed = False

        for index in range(
            1,
            len(working) - 1,
        ):
            label = working[index]
            label_text = clean_text(
                label.get("text")
            )
            label_bbox = label.get("bbox")

            if (
                not label_text
                or len(label_text)
                > FORM_LABEL_MAX_CHARS
                or not label_text.endswith(
                    (":", "：")
                )
                or not isinstance(
                    label_bbox,
                    dict,
                )
            ):
                continue

            previous = working[
                index - 1
            ]
            following = working[
                index + 1
            ]

            previous_bbox = previous.get(
                "bbox"
            )
            following_bbox = following.get(
                "bbox"
            )

            if (
                not isinstance(
                    previous_bbox,
                    dict,
                )
                or not isinstance(
                    following_bbox,
                    dict,
                )
            ):
                continue

            right_x = (
                float(
                    previous_bbox["x0"]
                )
                + float(
                    following_bbox["x0"]
                )
            ) / 2.0

            if (
                abs(
                    float(
                        previous_bbox["x0"]
                    )
                    - float(
                        following_bbox["x0"]
                    )
                )
                > FORM_LABEL_VALUE_X_TOLERANCE
            ):
                continue

            if (
                right_x
                - float(
                    label_bbox["x0"]
                )
                < FORM_LABEL_MIN_X_SHIFT
            ):
                continue

            if (
                float(
                    label_bbox["x1"]
                )
                > right_x
                + FORM_LABEL_VALUE_X_TOLERANCE
            ):
                continue

            label_height = max(
                1.0,
                float(
                    label_bbox["bottom"]
                )
                - float(
                    label_bbox["top"]
                ),
            )
            max_gap = (
                label_height
                * FORM_LABEL_MAX_VERTICAL_GAP_RATIO
            )

            previous_gap = (
                float(
                    label_bbox["top"]
                )
                - float(
                    previous_bbox["bottom"]
                )
            )
            following_gap = (
                float(
                    following_bbox["top"]
                )
                - float(
                    label_bbox["bottom"]
                )
            )

            if (
                previous_gap > max_gap
                or following_gap > max_gap
            ):
                continue

            # 向前扩展同一右侧 value run。
            run_start = index - 1

            while run_start > 0:
                candidate = working[
                    run_start - 1
                ]
                current = working[
                    run_start
                ]
                candidate_bbox = (
                    candidate.get("bbox")
                )
                current_bbox = (
                    current.get("bbox")
                )

                if (
                    not isinstance(
                        candidate_bbox,
                        dict,
                    )
                    or not isinstance(
                        current_bbox,
                        dict,
                    )
                ):
                    break

                if (
                    abs(
                        float(
                            candidate_bbox["x0"]
                        )
                        - right_x
                    )
                    > FORM_LABEL_VALUE_X_TOLERANCE
                ):
                    break

                gap = (
                    float(
                        current_bbox["top"]
                    )
                    - float(
                        candidate_bbox["bottom"]
                    )
                )

                if gap > max_gap:
                    break

                run_start -= 1

            moved = working.pop(
                index
            )
            working.insert(
                run_start,
                moved,
            )

            diagnostics.append(
                {
                    "text":
                        label_text,
                    "from_index":
                        index,
                    "to_index":
                        run_start,
                    "value_x0":
                        round(
                            right_x,
                            4,
                        ),
                    "reason":
                        "left_label_vertically_centered_across_multiline_value",
                }
            )

            changed = True
            break

    return (
        working,
        diagnostics,
    )


def stage63_assign_words_to_text_units(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> tuple[
    dict[int, list[dict[str, Any]]],
    dict[str, Any],
]:
    """
    把 Stage1 words 唯一分配给 Stage6.2 text reading units。

    为什么不能“每个 bbox 各自抓一次 words”：
    p43 已经证明 Stage4 text bbox 可能纵向重叠。
    如果每个 bbox 独立抓词，同一个 word 可能进入两个段落。

    因此：
    - 每个 word 找所有候选 text unit；
    - center inside 优先；
    - 再看 overlap coverage；
    - 多个候选时优先更小 bbox（更具体的 fragment）；
    - 一个 word 最终只能属于一个 reading unit。
    """
    text_units = [
        item
        for item in (
            stage63_prepare_effective_text_units(
                raw_page,
                reading_page,
            )
        )
        if isinstance(
            item.get(
                "bbox"
            ),
            dict,
        )
    ]

    assignments: dict[
        int,
        list[dict[str, Any]],
    ] = {
        int(item["reading_order"]): []
        for item in text_units
    }

    # v0.3.13：Stage4 v0.2.4+ 为 native text block 保存了 source_word_indices。
    # 当本页 native text units 都带这个字段时，使用 provenance 作为 raw word ownership。
    # 旧 Stage4 输入没有该字段时，继续兼容原来的 bbox assignment。
    native_text_units = [
        item
        for item in text_units
        if item.get("stage63_source_kind") == "native_text"
    ]

    provenance_mode = bool(native_text_units) and all(
        "source_word_indices" in item
        and isinstance(item.get("source_word_indices"), list)
        for item in native_text_units
    )

    provenance_orders_by_word: dict[int, set[int]] = defaultdict(set)

    if provenance_mode:
        for item in native_text_units:
            order = int(item["reading_order"])
            for value in item.get("source_word_indices", []):
                if isinstance(value, int) and value >= 0:
                    provenance_orders_by_word[value].add(order)

    provenance_claimed_word_count = 0
    provenance_unclaimed_word_count = 0

    raw_words = raw_page.get(
        "words",
        [],
    )

    if not isinstance(
        raw_words,
        list,
    ):
        raw_words = []

    valid_word_count = 0
    assigned_word_count = 0
    ambiguous_assignment_count = 0
    unassigned_word_count = 0
    watermark_removed_char_count = 0
    watermark_rewritten_word_count = 0
    watermark_dropped_word_count = 0

    ignored_noise_regions = [
        item
        for item in reading_page.get(
            "ignored_noise_regions",
            [],
        )
        if isinstance(
            item,
            dict,
        )
    ]

    candidate_word_count_by_order: dict[int, int] = {
        int(item["reading_order"]): 0
        for item in text_units
    }

    claimed_elsewhere_count_by_order: dict[int, int] = {
        int(item["reading_order"]): 0
        for item in text_units
    }

    winner_orders_by_loser: dict[
        int,
        set[int],
    ] = {
        int(item["reading_order"]): set()
        for item in text_units
    }

    for word_index, raw_word in enumerate(
        raw_words
    ):
        if not isinstance(
            raw_word,
            dict,
        ):
            continue

        (
            word,
            removed_chars,
            rewritten,
        ) = (
            stage63_strip_confirmed_watermark_from_word(
                raw_word,
                raw_page,
                ignored_noise_regions,
            )
        )

        watermark_removed_char_count += int(
            removed_chars
        )

        if rewritten:
            watermark_rewritten_word_count += 1

        if word is None:
            watermark_dropped_word_count += 1
            continue

        word_bbox = (
            stage63_word_bbox(
                word
            )
        )

        if word_bbox is None:
            continue

        value = clean_text(
            word.get(
                "text",
                "",
            )
        )

        if not value:
            continue

        valid_word_count += 1

        allowed_orders: set[int] | None = None

        if provenance_mode:
            allowed_orders = provenance_orders_by_word.get(
                word_index,
                set(),
            )

            # 未被任何 Stage4 native text block claim 的 raw word，
            # 不允许再因为 bbox 较大而被 Stage6.3 捞回正文。
            if not allowed_orders:
                provenance_unclaimed_word_count += 1
                unassigned_word_count += 1
                continue

            provenance_claimed_word_count += 1

        word_area = (
            stage63_bbox_area(
                word_bbox
            )
        )

        candidates: list[
            tuple[
                int,
                float,
                float,
                int,
                dict[str, Any],
            ]
        ] = []

        for unit in text_units:
            unit_order = int(
                unit.get("reading_order", 0)
                or 0
            )

            if (
                allowed_orders is not None
                and unit_order not in allowed_orders
            ):
                continue

            unit_bbox = unit[
                "bbox"
            ]

            center_inside = (
                stage63_center_inside(
                    word_bbox,
                    unit_bbox,
                    tolerance=PARAGRAPH_WORD_BBOX_TOLERANCE,
                )
            )

            overlap_area = (
                stage63_bbox_intersection_area(
                    word_bbox,
                    unit_bbox,
                )
            )

            coverage = (
                overlap_area
                / word_area
                if word_area > 0
                else 0.0
            )

            if (
                allowed_orders is None
                and not (
                    center_inside
                    or coverage
                    >= PARAGRAPH_WORD_MIN_OVERLAP_COVERAGE
                )
            ):
                continue

            unit_area = (
                stage63_bbox_area(
                    unit_bbox
                )
            )

            # 排序：
            # 1) center inside 优先；
            # 2) overlap coverage 高优先；
            # 3) bbox 小优先；
            # 4) reading order 早优先。
            candidates.append(
                (
                    0
                    if center_inside
                    else 1,
                    -coverage,
                    unit_area,
                    int(
                        unit[
                            "reading_order"
                        ]
                    ),
                    unit,
                )
            )

        if not candidates:
            unassigned_word_count += 1
            continue

        for candidate in candidates:
            candidate_order = int(
                candidate[4][
                    "reading_order"
                ]
            )
            candidate_word_count_by_order[
                candidate_order
            ] += 1

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
            )
        )

        if len(candidates) > 1:
            ambiguous_assignment_count += 1

        winner = candidates[0][4]
        order = int(
            winner[
                "reading_order"
            ]
        )

        for candidate in candidates[1:]:
            loser_order = int(
                candidate[4][
                    "reading_order"
                ]
            )

            if loser_order == order:
                continue

            claimed_elsewhere_count_by_order[
                loser_order
            ] += 1

            winner_orders_by_loser[
                loser_order
            ].add(
                order
            )

        copied = dict(word)
        copied[
            "_stage63_word_index"
        ] = word_index

        assignments[
            order
        ].append(
            copied
        )

        assigned_word_count += 1

    # layout_container 的文本来自 Stage1 extracted_data，后续走独立 ordered-lines
    # 路径，不依赖 raw-word assignments；因此 empty-unit 风险只检查 native_text。
    empty_text_units = [
        int(item["reading_order"])
        for item in text_units
        if item.get("stage63_source_kind") == "native_text"
        and not assignments.get(
            int(item["reading_order"])
        )
    ]

    unit_by_order = {
        int(item["reading_order"]):
            item
        for item in text_units
    }

    empty_text_unit_details: list[
        dict[str, Any]
    ] = []

    shadowed_empty_orders: list[int] = []
    unsupported_empty_orders: list[int] = []
    risky_unsupported_empty_orders: list[int] = []
    placeholder_empty_orders: list[int] = []

    for order in empty_text_units:
        unit = unit_by_order[
            order
        ]

        candidate_count = int(
            candidate_word_count_by_order.get(
                order,
                0,
            )
            or 0
        )

        claimed_elsewhere = int(
            claimed_elsewhere_count_by_order.get(
                order,
                0,
            )
            or 0
        )

        preview = clean_text(
            unit.get(
                "text_preview",
                "",
            )
        )

        preview_char_count = len(
            preview
        )

        flow_role = str(
            unit.get(
                "flow_role",
                "main",
            )
        )

        if candidate_count > 0:
            classification = (
                "shadowed_by_overlapping_unit"
            )
            shadowed_empty_orders.append(
                order
            )
            stage63_risk = False

        elif preview_char_count == 0:
            classification = (
                "empty_placeholder"
            )
            placeholder_empty_orders.append(
                order
            )
            stage63_risk = False

        else:
            classification = (
                "no_stage1_word_support"
            )
            unsupported_empty_orders.append(
                order
            )

            stage63_risk = (
                flow_role == "main"
                and preview_char_count
                >= PARAGRAPH_EMPTY_UNIT_RISK_MIN_CHARS
            )

            if stage63_risk:
                risky_unsupported_empty_orders.append(
                    order
                )

        empty_text_unit_details.append(
            {
                "reading_order":
                    order,
                "block_id":
                    unit.get(
                        "block_id"
                    ),
                "source_block_id":
                    unit.get(
                        "source_block_id"
                    ),
                "logical_fragment":
                    unit.get(
                        "logical_fragment"
                    ),
                "column_role":
                    unit.get(
                        "column_role"
                    ),
                "flow_role":
                    flow_role,
                "stage63_source_kind":
                    unit.get(
                        "stage63_source_kind",
                        "native_text",
                    ),
                "text_preview":
                    preview
                    if preview
                    else None,
                "preview_char_count":
                    preview_char_count,
                "candidate_word_count":
                    candidate_count,
                "claimed_elsewhere_word_count":
                    claimed_elsewhere,
                "winner_reading_orders":
                    sorted(
                        winner_orders_by_loser.get(
                            order,
                            set(),
                        )
                    ),
                "classification":
                    classification,
                "stage63_risk":
                    stage63_risk,
            }
        )

    return (
        assignments,
        {
            "valid_raw_word_count":
                valid_word_count,
            "confirmed_watermark_removed_char_count":
                watermark_removed_char_count,
            "confirmed_watermark_rewritten_word_count":
                watermark_rewritten_word_count,
            "confirmed_watermark_dropped_word_count":
                watermark_dropped_word_count,
            "assigned_word_count":
                assigned_word_count,
            "unassigned_raw_word_count":
                unassigned_word_count,
            "ambiguous_candidate_word_count":
                ambiguous_assignment_count,
            "word_assignment_mode":
                (
                    "source_word_provenance"
                    if provenance_mode
                    else "bbox_fallback"
                ),
            "provenance_claimed_word_count":
                provenance_claimed_word_count,
            "provenance_unclaimed_word_count":
                provenance_unclaimed_word_count,
            "text_unit_count":
                len(text_units),
            "empty_text_unit_count":
                len(empty_text_units),
            "empty_text_unit_orders":
                empty_text_units,

            "shadowed_empty_text_unit_count":
                len(
                    shadowed_empty_orders
                ),
            "shadowed_empty_text_unit_orders":
                shadowed_empty_orders,

            "unsupported_empty_text_unit_count":
                len(
                    unsupported_empty_orders
                ),
            "unsupported_empty_text_unit_orders":
                unsupported_empty_orders,

            "risky_unsupported_empty_text_unit_count":
                len(
                    risky_unsupported_empty_orders
                ),
            "risky_unsupported_empty_text_unit_orders":
                risky_unsupported_empty_orders,

            "placeholder_empty_text_unit_count":
                len(
                    placeholder_empty_orders
                ),
            "placeholder_empty_text_unit_orders":
                placeholder_empty_orders,

            "empty_text_unit_details":
                empty_text_unit_details,

            "word_reuse_count":
                0,
        },
    )


def stage63_group_words_into_lines(
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    把 Stage1 words 聚合成视觉行。

    v0.3.14 regression fix：
    旧实现只比较 word center_y 与 line center_y。若某个 raw word 的 bbox
    异常偏高/跨越多条物理行，它的 center_y 可能恰好落到另一条正文行附近，
    从而把不同物理行吸进同一个 line，最终改变正文顺序。

    新规则仍然不做语义判断，只增加几何一致性：
    - center_y 接近只是必要条件之一；
    - 同行还必须有足够 vertical overlap，或 top/bottom 边界同时接近；
    - 对高度显著异常的 word 使用更严格的边界一致性；
    - 不删除任何 word，不按具体页面/字符串写补丁。
    """
    if not words:
        return []

    prepared: list[dict[str, Any]] = []
    heights: list[float] = []

    for word in words:
        bbox = stage63_word_bbox(word)
        if bbox is None:
            continue

        center_x, center_y = stage63_bbox_center(bbox)
        height = max(1.0, bbox["bottom"] - bbox["top"])
        heights.append(height)
        prepared.append(
            {
                "word": word,
                "bbox": bbox,
                "center_x": center_x,
                "center_y": center_y,
                "height": height,
            }
        )

    if not prepared:
        return []

    median_height = median_number(heights) or 8.0
    y_tolerance = max(
        PARAGRAPH_LINE_Y_TOLERANCE,
        median_height * PARAGRAPH_LINE_Y_HEIGHT_RATIO,
    )

    prepared.sort(
        key=lambda item: (
            item["center_y"],
            item["bbox"]["top"],
            item["bbox"]["x0"],
        )
    )

    line_groups: list[list[dict[str, Any]]] = []

    def group_stats(group: list[dict[str, Any]]) -> dict[str, float]:
        normal = [
            item
            for item in group
            if item["height"] <= median_height * PARAGRAPH_LINE_TALL_WORD_RATIO
        ]
        basis = normal or group
        return {
            "center": median_number([item["center_y"] for item in basis]) or 0.0,
            "top": median_number([item["bbox"]["top"] for item in basis]) or 0.0,
            "bottom": median_number([item["bbox"]["bottom"] for item in basis]) or 0.0,
            "height": median_number([item["height"] for item in basis]) or median_height,
        }

    def compatible(item: dict[str, Any], group: list[dict[str, Any]]) -> tuple[bool, float]:
        stats = group_stats(group)
        center_delta = abs(item["center_y"] - stats["center"])
        if center_delta > y_tolerance:
            return False, center_delta

        item_bbox = item["bbox"]
        ref_bbox = {
            "x0": 0.0,
            "x1": 1.0,
            "top": stats["top"],
            "bottom": stats["bottom"],
        }
        overlap = max(
            0.0,
            min(item_bbox["bottom"], ref_bbox["bottom"])
            - max(item_bbox["top"], ref_bbox["top"]),
        )
        overlap_ref = max(1.0, min(item["height"], stats["height"]))
        overlap_ratio = overlap / overlap_ref

        top_delta = abs(item_bbox["top"] - stats["top"])
        bottom_delta = abs(item_bbox["bottom"] - stats["bottom"])
        normal_edge_tol = median_height * PARAGRAPH_LINE_EDGE_TOL_HEIGHT_RATIO
        edge_aligned = (
            top_delta <= normal_edge_tol
            and bottom_delta <= normal_edge_tol
        )

        is_tall = item["height"] > median_height * PARAGRAPH_LINE_TALL_WORD_RATIO
        if is_tall:
            # 异常高 bbox 不能仅凭中心接近吸附到正常正文行。
            tall_tol = median_height * PARAGRAPH_LINE_TALL_EDGE_TOL_HEIGHT_RATIO
            strong_edge_alignment = (
                top_delta <= tall_tol
                and bottom_delta <= tall_tol
            )
            return (
                overlap_ratio >= 0.90 and strong_edge_alignment,
                center_delta,
            )

        return (
            overlap_ratio >= PARAGRAPH_LINE_MIN_VERTICAL_OVERLAP_RATIO
            or edge_aligned,
            center_delta,
        )

    for item in prepared:
        best_index: int | None = None
        best_delta: float | None = None

        for index, group in enumerate(line_groups):
            ok, delta = compatible(item, group)
            if not ok:
                continue
            if best_delta is None or delta < best_delta:
                best_index = index
                best_delta = delta

        if best_index is None:
            line_groups.append([item])
        else:
            line_groups[best_index].append(item)

    lines: list[dict[str, Any]] = []

    for group in line_groups:
        group.sort(
            key=lambda item: (
                item["bbox"]["x0"],
                item["center_y"],
            )
        )

        group_words = [item["word"] for item in group]
        line_bbox = stage63_bbox_union([item["bbox"] for item in group])
        if line_bbox is None:
            continue

        line_text = stage63_join_words(group_words)
        if not line_text:
            continue

        line_heights = [item["height"] for item in group]
        lines.append(
            {
                "text": line_text,
                "bbox": line_bbox,
                "word_count": len(group_words),
                "char_count": len(line_text),
                "median_word_height": round(
                    median_number(line_heights) or median_height,
                    4,
                ),
                "source_word_indices": [
                    int(word.get("_stage63_word_index", -1))
                    for word in group_words
                ],
                "_stage63_words": [
                    {
                        "text": clean_text(item["word"].get("text")),
                        "bbox": dict(item["bbox"]),
                        "x0": float(item["bbox"]["x0"]),
                        "top": float(item["bbox"]["top"]),
                        "x1": float(item["bbox"]["x1"]),
                        "bottom": float(item["bbox"]["bottom"]),
                        "source_word_index": int(
                            item["word"].get("_stage63_word_index", -1)
                        ),
                        "height": float(item["height"]),
                    }
                    for item in group
                ],
            }
        )

    lines.sort(
        key=lambda item: (
            float(item["bbox"]["top"]),
            float(item["bbox"]["x0"]),
        )
    )

    return lines

def stage63_column_bounds(
    role: str,
    page_width: float,
) -> tuple[float, float]:
    mid = page_width / 2.0

    if role == "left":
        return (
            0.0,
            mid,
        )

    if role == "right":
        return (
            mid,
            page_width,
        )

    return (
        0.0,
        page_width,
    )


def stage63_page_font_reference(
    reading_page: dict[str, Any],
) -> float | None:
    values = [
        float(
            item[
                "median_font_size"
            ]
        )
        for item
        in reading_page.get(
            "reading_order",
            []
        )
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "block_type"
            )
            == "text"
            and item.get(
                "flow_role"
            )
            == "main"
            and item.get(
                "median_font_size"
            )
            is not None
            and float(
                item[
                    "median_font_size"
                ]
            )
            > 0
        )
    ]

    return (
        median_number(
            values
        )
    )


def stage63_is_geometric_heading_line(
    line: dict[str, Any],
    unit: dict[str, Any],
    page_width: float,
    page_font_reference: float | None,
    unit_line_count: int = 1,
) -> bool:
    text = clean_text(
        line.get(
            "text",
            "",
        )
    )

    if not text:
        return False

    if (
        len(text)
        > PARAGRAPH_HEADING_MAX_CHAR_COUNT
    ):
        return False

    bbox = line[
        "bbox"
    ]

    role = str(
        unit.get(
            "column_role"
        )
        or "span"
    )

    column_x0, column_x1 = (
        stage63_column_bounds(
            role,
            page_width,
        )
    )

    column_width = max(
        1.0,
        column_x1
        - column_x0,
    )

    line_width = max(
        1.0,
        float(
            bbox["x1"]
        )
        - float(
            bbox["x0"]
        ),
    )

    line_center = (
        float(
            bbox["x0"]
        )
        + float(
            bbox["x1"]
        )
    ) / 2.0

    column_center = (
        column_x0
        + column_x1
    ) / 2.0

    width_ratio = (
        line_width
        / column_width
    )

    center_delta_ratio = abs(
        line_center
        - column_center
    ) / column_width

    # v0.3.12：普通正文的某一视觉行也可能“居中且较短”。
    # 因此 centered_short 不再单独构成标题证据；必须再有字号证据。
    centered_short = (
        len(text)
        <= PARAGRAPH_CENTERED_HEADING_MAX_CHAR_COUNT
        and width_ratio
        <= PARAGRAPH_CENTERED_HEADING_MAX_WIDTH_RATIO
        and center_delta_ratio
        <= PARAGRAPH_HEADING_CENTER_TOL_RATIO
    )

    font_size = unit.get(
        "median_font_size"
    )

    large_font = False
    centered_font_support = False

    if (
        page_font_reference
        and page_font_reference > 0
        and font_size is not None
    ):
        font_ratio = (
            float(font_size)
            / page_font_reference
        )

        large_font = (
            font_ratio
            >= PARAGRAPH_HEADING_FONT_RATIO
        )

        # v0.3.14：不能让一个多行正文 text unit 的所有短行
        # 继承 unit 级字号后都变成 heading。居中型标题必须是
        # 独立单行 unit；large_font 也要求当前行本身较窄，
        # 作为保守的几何保护，避免普通正文被标题边界切碎。
        centered_font_support = (
            unit_line_count == 1
            and centered_short
            and font_ratio
            >= PARAGRAPH_CENTERED_HEADING_MIN_FONT_RATIO
        )

        large_font = (
            large_font
            and width_ratio <= PARAGRAPH_HEADING_MAX_WIDTH_RATIO
            and unit_line_count == 1
        )

    return bool(
        large_font
        or centered_font_support
    )


def stage63_make_line_records(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
]:
    assignments, assignment_diag = (
        stage63_assign_words_to_text_units(
            raw_page,
            reading_page,
        )
    )

    page_width = float(
        raw_page.get(
            "width",
            0.0,
        )
        or 0.0
    )

    if page_width <= 0:
        page_width = 1.0

    page_font_reference = (
        stage63_page_font_reference(
            reading_page
        )
    )

    line_records: list[
        dict[str, Any]
    ] = []

    line_order = 0

    layout_container_diagnostics: list[
        dict[str, Any]
    ] = []

    effective_text_units = (
        stage63_prepare_effective_text_units(
            raw_page,
            reading_page,
        )
    )

    for unit in effective_text_units:
        reading_order = int(
            unit.get(
                "reading_order",
                0,
            )
            or 0
        )

        if (
            unit.get(
                "stage63_source_kind"
            )
            == "layout_container"
        ):
            (
                unit_lines,
                layout_diag,
            ) = (
                stage63_layout_container_ordered_lines(
                    raw_page,
                    reading_page,
                    unit,
                )
            )

            layout_diag = dict(
                layout_diag
            )
            layout_diag[
                "reading_order"
            ] = reading_order
            layout_diag[
                "block_id"
            ] = unit.get(
                "block_id"
            )

            layout_container_diagnostics.append(
                layout_diag
            )
        else:
            unit_lines = (
                stage63_group_words_into_lines(
                    assignments.get(
                        reading_order,
                        [],
                    )
                )
            )

            (
                unit_lines,
                inline_form_splits,
            ) = (
                stage63_split_inline_multiline_form_labels(
                    unit_lines
                )
            )

            if inline_form_splits:
                assignment_diag.setdefault(
                    "inline_multiline_form_label_splits",
                    [],
                ).extend(
                    [
                        {
                            **item,
                            "reading_order":
                                reading_order,
                            "block_id":
                                unit.get(
                                    "block_id"
                                ),
                        }
                        for item
                        in inline_form_splits
                    ]
                )

            (
                unit_lines,
                form_reorders,
            ) = (
                stage63_reorder_multiline_form_labels(
                    unit_lines
                )
            )

            if form_reorders:
                assignment_diag.setdefault(
                    "multiline_form_label_reorders",
                    [],
                ).extend(
                    [
                        {
                            **item,
                            "reading_order":
                                reading_order,
                            "block_id":
                                unit.get(
                                    "block_id"
                                ),
                        }
                        for item
                        in form_reorders
                    ]
                )

        for local_index, line in enumerate(
            unit_lines,
            start=1,
        ):
            line_order += 1

            if (
                line.get(
                    "stage63_source_kind"
                )
                == "layout_container_ordered_text"
            ):
                is_heading = False
            else:
                is_heading = (
                    stage63_is_geometric_heading_line(
                        line,
                        unit,
                        page_width,
                        page_font_reference,
                        unit_line_count=len(unit_lines),
                    )
                )

            line_records.append(
                {
                    "line_order":
                        line_order,
                    "source_reading_order":
                        reading_order,
                    "source_line_index":
                        line.get(
                            "source_line_index",
                            local_index,
                        ),
                    "source_block_id":
                        unit.get(
                            "source_block_id"
                        ),
                    "block_id":
                        unit.get(
                            "block_id"
                        ),
                    "logical_fragment":
                        unit.get(
                            "logical_fragment"
                        ),
                    "column_role":
                        unit.get(
                            "column_role"
                        ),
                    "flow_role":
                        unit.get(
                            "flow_role",
                            "main",
                        ),
                    "stage63_source_kind":
                        line.get(
                            "stage63_source_kind",
                            unit.get(
                                "stage63_source_kind",
                                "native_text",
                            ),
                        ),
                    "layout_container_row":
                        line.get(
                            "layout_container_row"
                        ),
                    "layout_container_cell":
                        line.get(
                            "layout_container_cell"
                        ),
                    "layout_container_cell_key":
                        line.get(
                            "layout_container_cell_key"
                        ),
                    "synthetic_geometry":
                        bool(
                            line.get(
                                "synthetic_geometry",
                                False,
                            )
                        ),
                    "visual_match_found":
                        bool(
                            line.get(
                                "visual_match_found",
                                False,
                            )
                        ),
                    "visual_match_score":
                        line.get(
                            "visual_match_score"
                        ),
                    "visual_line_index":
                        line.get(
                            "visual_line_index"
                        ),
                    "visual_x0":
                        line.get(
                            "visual_x0"
                        ),
                    "visual_top":
                        line.get(
                            "visual_top"
                        ),
                    "visual_bottom":
                        line.get(
                            "visual_bottom"
                        ),
                    "visual_median_word_height":
                        line.get(
                            "visual_median_word_height"
                        ),
                    "visual_sequence_reliable":
                        line.get(
                            "visual_sequence_reliable"
                        ),
                    "visual_order_inversion_count":
                        line.get(
                            "visual_order_inversion_count"
                        ),
                    "median_font_size":
                        unit.get(
                            "median_font_size"
                        ),
                    "is_geometric_heading":
                        is_heading,
                    "bbox":
                        line["bbox"],
                    "word_count":
                        line["word_count"],
                    "char_count":
                        line["char_count"],
                    "median_word_height":
                        line[
                            "median_word_height"
                        ],
                    "text":
                        line["text"],
                    "source_word_indices":
                        line[
                            "source_word_indices"
                        ],
                }
            )

    (
        line_records,
        page_form_reorders,
    ) = (
        stage63_reorder_multiline_form_labels(
            line_records
        )
    )

    if page_form_reorders:
        for new_order, item in enumerate(
            line_records,
            start=1,
        ):
            item["line_order"] = new_order

        assignment_diag.setdefault(
            "multiline_form_label_reorders",
            [],
        ).extend(
            [
                {
                    **item,
                    "scope":
                        "page_cross_unit",
                }
                for item
                in page_form_reorders
            ]
        )

    assignment_diag[
        "page_cross_unit_form_label_reorder_count"
    ] = len(
        page_form_reorders
    )

    assignment_diag[
        "line_count"
    ] = len(
        line_records
    )

    assignment_diag[
        "multiline_form_label_reorder_count"
    ] = len(
        assignment_diag.get(
            "multiline_form_label_reorders",
            [],
        )
    )

    assignment_diag[
        "inline_multiline_form_label_split_count"
    ] = len(
        assignment_diag.get(
            "inline_multiline_form_label_splits",
            [],
        )
    )

    # native-text authority suppression 改到 paragraph 重建之后执行。
    assignment_diag[
        "layout_container_native_suppressions"
    ] = []

    assignment_diag[
        "layout_container_native_suppression_count"
    ] = 0

    assignment_diag[
        "layout_container_ordered_text_diagnostics"
    ] = (
        layout_container_diagnostics
    )

    assignment_diag[
        "layout_container_ordered_text_count"
    ] = sum(
        1
        for item
        in layout_container_diagnostics
        if item.get(
            "status"
        )
        == "completed"
    )

    assignment_diag[
        "layout_container_exact_noise_line_removed_count"
    ] = sum(
        int(
            item.get(
                "removed_exact_noise_line_count",
                0,
            )
            or 0
        )
        for item
        in layout_container_diagnostics
    )

    assignment_diag[
        "layout_container_embedded_noise_removed_count"
    ] = sum(
        int(
            item.get(
                "removed_embedded_noise_count",
                0,
            )
            or 0
        )
        for item
        in layout_container_diagnostics
    )

    return (
        line_records,
        assignment_diag,
    )


def stage63_line_gap(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> float:
    return (
        float(
            current["bbox"]["top"]
        )
        - float(
            previous[
                "bbox"
            ]["bottom"]
        )
    )


def stage63_should_break_paragraph(
    paragraph: dict[str, Any],
    line: dict[str, Any],
) -> tuple[
    bool,
    str,
]:
    previous = paragraph[
        "lines"
    ][-1]

    previous_kind = str(
        previous.get(
            "stage63_source_kind",
            "native_text",
        )
    )

    current_kind = str(
        line.get(
            "stage63_source_kind",
            "native_text",
        )
    )

    layout_kind = (
        "layout_container_ordered_text"
    )

    if (
        previous_kind == layout_kind
        or current_kind == layout_kind
    ):
        if (
            previous_kind
            != current_kind
        ):
            return (
                True,
                "source_kind_change",
            )

        if (
            int(
                previous.get(
                    "source_reading_order",
                    0,
                )
                or 0
            )
            != int(
                line.get(
                    "source_reading_order",
                    0,
                )
                or 0
            )
        ):
            return (
                True,
                "layout_container_change",
            )

        if (
            previous.get(
                "layout_container_cell_key"
            )
            != line.get(
                "layout_container_cell_key"
            )
        ):
            return (
                True,
                "layout_container_cell_change",
            )

        # 同一个 layout-container cell 内：
        # 内容顺序仍完全服从 extracted_data；
        # 只利用通用结构标记 + 首行缩进 + 可靠视觉行距恢复自然段。
        return stage63_layout_container_break_reason(
            paragraph,
            previous,
            line,
        )

    if (
        line.get(
            "flow_role"
        )
        != paragraph.get(
            "flow_role"
        )
    ):
        return (
            True,
            "flow_role_change",
        )

    if (
        line.get(
            "column_role"
        )
        != paragraph.get(
            "column_role"
        )
    ):
        return (
            True,
            "column_change",
        )

    if (
        previous.get(
            "is_geometric_heading"
        )
        or line.get(
            "is_geometric_heading"
        )
    ):
        return (
            True,
            "geometric_heading_boundary",
        )

    previous_top = float(
        previous["bbox"]["top"]
    )
    current_top = float(
        line["bbox"]["top"]
    )

    # reading order 已经跨栏/跨区域时，y 会明显回跳。
    # Stage6.3 不跨这种 reset 合段。
    if (
        current_top
        + 1.0
        < previous_top
    ):
        return (
            True,
            "vertical_reset",
        )

    previous_height = max(
        1.0,
        float(
            previous[
                "median_word_height"
            ]
        ),
    )

    current_height = max(
        1.0,
        float(
            line[
                "median_word_height"
            ]
        ),
    )

    height_ref = (
        previous_height
        + current_height
    ) / 2.0

    gap = stage63_line_gap(
        previous,
        line,
    )

    if (
        gap
        > height_ref
        * PARAGRAPH_BREAK_GAP_HEIGHT_RATIO
    ):
        return (
            True,
            "large_line_gap",
        )

    previous_unit = int(
        previous.get(
            "source_reading_order",
            0,
        )
        or 0
    )

    current_unit = int(
        line.get(
            "source_reading_order",
            0,
        )
        or 0
    )

    if (
        previous_unit
        != current_unit
    ):
        if (
            gap
            > height_ref
            * PARAGRAPH_CROSS_UNIT_MAX_GAP_HEIGHT_RATIO
        ):
            return (
                True,
                "cross_unit_gap",
            )

        baseline_x0 = median_number(
            [
                float(
                    item[
                        "bbox"
                    ]["x0"]
                )
                for item
                in paragraph[
                    "lines"
                ][-3:]
            ]
        )

        if baseline_x0 is None:
            baseline_x0 = float(
                previous[
                    "bbox"
                ]["x0"]
            )

        left_shift = abs(
            float(
                line[
                    "bbox"
                ]["x0"]
            )
            - baseline_x0
        )

        if (
            left_shift
            > height_ref
            * PARAGRAPH_CROSS_UNIT_MAX_LEFT_SHIFT_HEIGHT_RATIO
        ):
            return (
                True,
                "cross_unit_alignment_change",
            )

    # 行首明显向右缩进：
    # 只作为新段证据，不把“向左回到正常边界”强行切段。
    baseline_x0 = median_number(
        [
            float(
                item[
                    "bbox"
                ]["x0"]
            )
            for item
            in paragraph[
                "lines"
            ][-3:]
        ]
    )

    if baseline_x0 is not None:
        indent = (
            float(
                line[
                    "bbox"
                ]["x0"]
            )
            - baseline_x0
        )

        if (
            indent
            > height_ref
            * PARAGRAPH_INDENT_BREAK_HEIGHT_RATIO
        ):
            return (
                True,
                "new_line_indent",
            )

    return (
        False,
        "continuous",
    )


def stage63_finalize_paragraph(
    paragraph: dict[str, Any],
    paragraph_index: int,
    page_number: int,
) -> dict[str, Any]:
    lines = paragraph[
        "lines"
    ]

    bbox = stage63_bbox_union(
        [
            line["bbox"]
            for line in lines
        ]
    )

    source_reading_orders = list(
        dict.fromkeys(
            int(
                line[
                    "source_reading_order"
                ]
            )
            for line in lines
        )
    )

    source_block_ids = list(
        dict.fromkeys(
            str(
                line.get(
                    "source_block_id"
                )
                or line.get(
                    "block_id"
                )
                or ""
            )
            for line in lines
            if (
                line.get(
                    "source_block_id"
                )
                or line.get(
                    "block_id"
                )
            )
        )
    )

    source_word_indices = list(
        dict.fromkeys(
            int(value)
            for line in lines
            for value in line.get(
                "source_word_indices",
                [],
            )
            if isinstance(value, int) and value >= 0
        )
    )

    raw_lines = [
        line["text"]
        for line in lines
    ]

    source_kinds = list(
        dict.fromkeys(
            str(
                line.get(
                    "stage63_source_kind",
                    "native_text",
                )
            )
            for line in lines
        )
    )

    return {
        "paragraph_id":
            (
                f"p{page_number:04d}_para"
                f"{paragraph_index:03d}"
            ),
        "page_number":
            page_number,
        "flow_role":
            paragraph.get(
                "flow_role",
                "main",
            ),
        "column_role":
            paragraph.get(
                "column_role",
            ),
        "is_geometric_heading":
            bool(
                len(lines) == 1
                and lines[0].get(
                    "is_geometric_heading"
                )
            ),
        "line_count":
            len(lines),
        "word_count":
            sum(
                int(
                    line.get(
                        "word_count",
                        0,
                    )
                )
                for line in lines
            ),
        "source_reading_orders":
            source_reading_orders,
        "source_line_orders":
            [
                int(
                    line.get(
                        "line_order",
                        0,
                    )
                    or 0
                )
                for line in lines
                if int(
                    line.get(
                        "line_order",
                        0,
                    )
                    or 0
                ) > 0
            ],
        "source_kinds":
            source_kinds,
        "uses_synthetic_geometry":
            any(
                bool(
                    line.get(
                        "synthetic_geometry",
                        False,
                    )
                )
                for line in lines
            ),
        "source_block_ids":
            source_block_ids,
        "source_word_indices":
            source_word_indices,
        "bbox":
            bbox,
        "lines":
            raw_lines,

        # Stage6.3 故意保留真实行边界。
        # 6.5 才处理断词/连字符/异常空格。
        "text_with_linebreaks":
            "\n".join(
                raw_lines
            ),
        "break_reason":
            paragraph.get(
                "break_reason",
                "page_start",
            ),
    }


def stage63_build_paragraphs(
    line_records: list[dict[str, Any]],
    page_number: int,
) -> list[dict[str, Any]]:
    paragraphs: list[
        dict[str, Any]
    ] = []

    current: dict[str, Any] | None = None

    for line in line_records:
        if current is None:
            current = {
                "flow_role":
                    line.get(
                        "flow_role",
                        "main",
                    ),
                "column_role":
                    line.get(
                        "column_role",
                    ),
                "lines":
                    [line],
                "break_reason":
                    "page_start",
            }
            continue

        should_break, reason = (
            stage63_should_break_paragraph(
                current,
                line,
            )
        )

        if not should_break:
            current[
                "lines"
            ].append(
                line
            )
            continue

        paragraphs.append(
            stage63_finalize_paragraph(
                current,
                len(paragraphs)
                + 1,
                page_number,
            )
        )

        current = {
            "flow_role":
                line.get(
                    "flow_role",
                    "main",
                ),
            "column_role":
                line.get(
                    "column_role",
                ),
            "lines":
                [line],
            "break_reason":
                reason,
        }

    if current is not None:
        paragraphs.append(
            stage63_finalize_paragraph(
                current,
                len(paragraphs)
                + 1,
                page_number,
            )
        )

    return paragraphs



def stage63_layout_container_authorities(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    构造 layout_container 的 authoritative text regions。

    authority 只来自：
    - Stage6.3 已确认 classification == layout_container
    - 对应 Stage1 table candidate extracted_data

    不修改任何源证据。
    """
    diagnostics = (
        stage63_classify_table_units(
            raw_page,
            reading_page,
        )
    )

    layout_orders = {
        int(item["reading_order"]):
            item
        for item in diagnostics
        if (
            item.get("reading_order") is not None
            and item.get(
                "classification"
            )
            == "layout_container"
        )
    }

    if not layout_orders:
        return []

    authorities: list[
        dict[str, Any]
    ] = []

    for item in reading_page.get(
        "reading_order",
        [],
    ):
        if not isinstance(item, dict):
            continue

        if item.get("block_type") != "table":
            continue

        order = int(
            item.get(
                "reading_order",
                0,
            )
            or 0
        )

        if order not in layout_orders:
            continue

        bbox = item.get("bbox")

        if not isinstance(
            bbox,
            dict,
        ):
            continue

        candidate = (
            stage63_match_table_candidate(
                raw_page,
                item,
            )
        )

        if candidate is None:
            continue

        text_blob = (
            stage63_table_candidate_text_blob(
                candidate
            )
        )

        if not text_blob:
            continue

        authorities.append(
            {
                "reading_order": order,
                "block_id":
                    item.get(
                        "block_id"
                    ),
                "bbox": bbox,
                "text_blob": text_blob,
                "source_table_index":
                    candidate.get(
                        "table_index"
                    ),
            }
        )

    return authorities


def stage63_paragraph_bbox_coverage(
    paragraph_bbox: dict[str, Any],
    container_bbox: dict[str, Any],
) -> float:
    paragraph_area = (
        stage63_bbox_area(
            paragraph_bbox
        )
    )

    if paragraph_area <= 0:
        return 0.0

    overlap_area = (
        stage63_bbox_intersection_area(
            paragraph_bbox,
            container_bbox,
        )
    )

    return (
        overlap_area
        / paragraph_area
    )



def stage63_paragraph_intersects_container(
    paragraph_bbox: dict[str, Any],
    container_bbox: dict[str, Any],
) -> bool:
    return (
        stage63_bbox_intersection_area(
            paragraph_bbox,
            container_bbox,
        )
        > 0
    )


def stage63_paragraph_starts_in_container(
    paragraph_bbox: dict[str, Any],
    container_bbox: dict[str, Any],
) -> bool:
    """
    用 paragraph 顶边中点近似“正文起点”。

    这里只用于 strong-text authority 路径：
    - 文本必须 >= 0.97 高覆盖；
    - paragraph 与 container 还必须真实相交；
    - 因此这里不是单独的删除依据。
    """
    paragraph = normalize_bbox(
        paragraph_bbox
    )
    container = normalize_bbox(
        container_bbox
    )

    if (
        paragraph is None
        or container is None
    ):
        return False

    start_x = (
        paragraph["x0"]
        + paragraph["x1"]
    ) / 2.0

    start_y = paragraph["top"]

    tolerance = (
        LAYOUT_CONTAINER_NATIVE_TEXT_START_TOLERANCE
    )

    return (
        container["x0"] - tolerance
        <= start_x
        <= container["x1"] + tolerance
        and container["top"] - tolerance
        <= start_y
        <= container["bottom"] + tolerance
    )


def stage63_suppress_native_paragraphs_by_authority(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
    paragraphs: list[dict[str, Any]],
    page_number: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    set[int],
]:
    """
    Stage6.3 logical authority 去重。

    为什么放在 paragraph 之后：
    - Stage4 / Stage6.2 text unit 往往比真实正文段落大；
    - 用 unit bbox + text_preview 判断会把“局部重复”稀释掉，
      或者为了命中而不得不放宽阈值；
    - paragraph 已经拥有真实 text + 更精确 bbox，正适合做保守去重。

    删除规则：
    A. source == native_text 且整段文本完全等于 Stage6.1 已确认 watermark
       -> logical paragraph 删除。

    B1. 常规 authority 路径：
       - paragraph bbox coverage >= 0.60；
       - paragraph text coverage >= 0.80；
       -> logical duplicate 删除。

    B2. 强文本 authority 路径：
       - 不降低全局 bbox coverage 阈值；
       - paragraph text coverage >= 0.97；
       - paragraph 与 container 有真实几何交集；
       - paragraph 顶边中点（正文起点近似）位于 container 内；
       -> 即使粗 bbox 向 container 外延伸，也可判定 duplicate。

    layout_container_ordered_text 自己永远不在此处删除。
    """
    authorities = (
        stage63_layout_container_authorities(
            raw_page,
            reading_page,
        )
    )

    exact_noise_texts = (
        stage63_exact_noise_texts(
            reading_page
        )
    )

    kept: list[
        dict[str, Any]
    ] = []

    suppressions: list[
        dict[str, Any]
    ] = []

    suppressed_line_orders: set[int] = set()

    for paragraph in paragraphs:
        source_kinds = [
            str(value)
            for value in paragraph.get(
                "source_kinds",
                [],
            )
        ]

        # 只对纯 native paragraph 做 authority 去重。
        if source_kinds != ["native_text"]:
            kept.append(paragraph)
            continue

        paragraph_text = clean_text(
            paragraph.get(
                "text_with_linebreaks",
                "",
            )
        )

        paragraph_bbox = paragraph.get(
            "bbox"
        )

        suppression: dict[str, Any] | None = None

        # 规则 A：Stage6.1 已确认的独立 watermark 整段。
        if (
            paragraph_text
            and paragraph_text
            in exact_noise_texts
        ):
            suppression = {
                "paragraph_id":
                    paragraph.get(
                        "paragraph_id"
                    ),
                "reason":
                    "exact_confirmed_noise_paragraph",
                "text":
                    paragraph_text,
                "bbox_coverage":
                    None,
                "text_match_coverage":
                    None,
                "container_block_id":
                    None,
                "container_reading_order":
                    None,
            }

        # 规则 B：layout_container authority 覆盖。
        elif (
            paragraph_text
            and isinstance(
                paragraph_bbox,
                dict,
            )
            and len(
                stage63_layout_match_text(
                    paragraph_text
                )
            )
            >= LAYOUT_CONTAINER_NATIVE_TEXT_MIN_PREVIEW_CHARS
        ):
            for authority in authorities:
                bbox_coverage = (
                    stage63_paragraph_bbox_coverage(
                        paragraph_bbox,
                        authority["bbox"],
                    )
                )

                text_match_coverage = (
                    stage63_sequence_match_coverage(
                        paragraph_text,
                        authority[
                            "text_blob"
                        ],
                    )
                )

                intersects = (
                    stage63_paragraph_intersects_container(
                        paragraph_bbox,
                        authority["bbox"],
                    )
                )

                starts_inside = (
                    stage63_paragraph_starts_in_container(
                        paragraph_bbox,
                        authority["bbox"],
                    )
                )

                standard_match = (
                    bbox_coverage
                    >= LAYOUT_CONTAINER_NATIVE_TEXT_MIN_BBOX_COVERAGE
                    and text_match_coverage
                    >= LAYOUT_CONTAINER_NATIVE_TEXT_MIN_MATCH_COVERAGE
                )

                strong_text_match = (
                    text_match_coverage
                    >= LAYOUT_CONTAINER_NATIVE_TEXT_STRONG_MATCH_COVERAGE
                    and intersects
                    and starts_inside
                )

                if not (
                    standard_match
                    or strong_text_match
                ):
                    continue

                suppression = {
                    "paragraph_id":
                        paragraph.get(
                            "paragraph_id"
                        ),
                    "reason":
                        "paragraph_already_represented_by_layout_container",
                    "authority_mode":
                        (
                            "standard_geometry_text"
                            if standard_match
                            else "strong_text_start_inside"
                        ),
                    "text":
                        paragraph_text,
                    "bbox_coverage":
                        round(
                            bbox_coverage,
                            4,
                        ),
                    "text_match_coverage":
                        round(
                            text_match_coverage,
                            4,
                        ),
                    "intersects_container":
                        intersects,
                    "paragraph_starts_in_container":
                        starts_inside,
                    "container_block_id":
                        authority.get(
                            "block_id"
                        ),
                    "container_reading_order":
                        authority.get(
                            "reading_order"
                        ),
                }
                break

        if suppression is None:
            kept.append(paragraph)
            continue

        source_line_orders = [
            int(value)
            for value in paragraph.get(
                "source_line_orders",
                [],
            )
            if int(value) > 0
        ]

        suppression[
            "source_line_orders"
        ] = source_line_orders

        suppression[
            "source_reading_orders"
        ] = list(
            paragraph.get(
                "source_reading_orders",
                [],
            )
        )

        suppressions.append(
            suppression
        )

        suppressed_line_orders.update(
            source_line_orders
        )

    # logical paragraph IDs 重新连续编号，避免去重后出现 para005 -> para007。
    for index, paragraph in enumerate(
        kept,
        start=1,
    ):
        paragraph[
            "paragraph_id"
        ] = (
            f"p{page_number:04d}_para"
            f"{index:03d}"
        )

    return (
        kept,
        suppressions,
        suppressed_line_orders,
    )


def stage63_build_flow_units(
    reading_page: dict[str, Any],
    paragraphs: list[dict[str, Any]],
    table_unit_diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    为后续 6.4~6.6 保留页内 logical flow。

    关键约束：
    - paragraph 的先后顺序必须服从 Stage6.3 已经重建好的 logical paragraph 顺序；
    - source_reading_order 只保留 provenance，不能再次把跨 text-unit 的几何重排撤销；
    - image / data_table / vector 仍作为 flow barrier，不能被文本重排跨越；
    - layout_container 属于 textual slot，因为它已经被内部 paragraphs 替代。

    这解决一种通用场景：左侧短 label 垂直居中于右侧多行 value 时，
    Stage6.3 已经把 label 移到 value run 前面，但如果这里再按原始
    source_reading_order 排序，就会把正确顺序重新打乱。
    """
    layout_container_orders = {
        int(item["reading_order"])
        for item in table_unit_diagnostics
        if (
            item.get("classification") == "layout_container"
            and item.get("reading_order") is not None
        )
    }

    table_diagnostic_by_order = {
        int(item["reading_order"]): item
        for item in table_unit_diagnostics
        if item.get("reading_order") is not None
    }

    paragraph_rank: dict[str, int] = {}
    paragraph_by_id: dict[str, dict[str, Any]] = {}
    paragraphs_by_source_order: dict[int, set[str]] = defaultdict(set)
    covered_orders: set[int] = set()

    for rank, paragraph in enumerate(paragraphs):
        paragraph_id = str(paragraph["paragraph_id"])
        paragraph_rank[paragraph_id] = rank
        paragraph_by_id[paragraph_id] = paragraph

        for value in paragraph.get("source_reading_orders", []):
            order = int(value)
            paragraphs_by_source_order[order].add(paragraph_id)
            covered_orders.add(order)

    reading_items = [
        item
        for item in reading_page.get("reading_order", [])
        if isinstance(item, dict)
    ]

    def is_textual_slot(item: dict[str, Any]) -> bool:
        order = int(item.get("reading_order", 0) or 0)
        block_type = str(item.get("block_type") or "")

        if block_type == "text":
            return True

        return (
            block_type == "table"
            and order in layout_container_orders
            and order in covered_orders
        )

    def emit_paragraph(paragraph_id: str) -> None:
        if paragraph_id in emitted_paragraph_ids:
            return

        paragraph = paragraph_by_id.get(paragraph_id)
        if paragraph is None:
            return

        flow_units.append(
            {
                "unit_type": "paragraph",
                "paragraph_id": paragraph_id,
                "flow_role": paragraph.get("flow_role"),
                "column_role": paragraph.get("column_role"),
                "bbox": paragraph.get("bbox"),
                "source_reading_orders": paragraph.get("source_reading_orders"),
            }
        )
        emitted_paragraph_ids.add(paragraph_id)

    flow_units: list[dict[str, Any]] = []
    emitted_paragraph_ids: set[str] = set()

    index = 0
    while index < len(reading_items):
        item = reading_items[index]

        if is_textual_slot(item):
            # 收集由非文本对象分隔的连续 textual run。
            # run 内 paragraph 顺序服从 Stage6.3 logical paragraph rank，
            # 而不是原始 source_reading_order。
            run_orders: list[int] = []
            end = index

            while end < len(reading_items) and is_textual_slot(reading_items[end]):
                run_orders.append(
                    int(reading_items[end].get("reading_order", 0) or 0)
                )
                end += 1

            run_paragraph_ids: set[str] = set()
            for order in run_orders:
                run_paragraph_ids.update(
                    paragraphs_by_source_order.get(order, set())
                )

            for paragraph_id in sorted(
                run_paragraph_ids,
                key=lambda value: paragraph_rank.get(value, 10**9),
            ):
                emit_paragraph(paragraph_id)

            index = end
            continue

        order = int(item.get("reading_order", 0) or 0)

        table_diag = table_diagnostic_by_order.get(order, {})

        flow_units.append(
            {
                "unit_type": str(item.get("block_type") or "object"),
                "reading_order": order,
                "block_id": item.get("block_id"),
                "source_block_id": item.get("source_block_id"),
                "source_table_index": (
                    table_diag.get("source_table_index")
                    if str(item.get("block_type") or "") == "table"
                    else None
                ),
                "column_role": item.get("column_role"),
                "flow_role": item.get("flow_role", "main"),
                "bbox": item.get("bbox"),
            }
        )
        index += 1

    # 极端情况下若 provenance 缺失，仍按 Stage6.3 paragraph 顺序保底输出，
    # 避免静默丢正文。
    for paragraph in paragraphs:
        emit_paragraph(str(paragraph["paragraph_id"]))

    for flow_order, unit in enumerate(flow_units, start=1):
        unit["flow_order"] = flow_order

    return flow_units


def build_page_paragraph_result(
    raw_page: dict[str, Any],
    reading_page: dict[str, Any],
) -> dict[str, Any]:
    page_number = int(
        reading_page[
            "page_number"
        ]
    )

    line_records, assignment_diag = (
        stage63_make_line_records(
            raw_page,
            reading_page,
        )
    )

    raw_paragraphs = (
        stage63_build_paragraphs(
            line_records,
            page_number,
        )
    )

    (
        paragraphs,
        paragraph_suppressions,
        suppressed_line_orders,
    ) = (
        stage63_suppress_native_paragraphs_by_authority(
            raw_page,
            reading_page,
            raw_paragraphs,
            page_number,
        )
    )

    if suppressed_line_orders:
        line_records = [
            line
            for line in line_records
            if int(
                line.get(
                    "line_order",
                    0,
                )
                or 0
            )
            not in suppressed_line_orders
        ]

        # logical line_order 重新连续编号。
        for index, line in enumerate(
            line_records,
            start=1,
        ):
            line[
                "line_order"
            ] = index

    assignment_diag[
        "pre_authority_paragraph_count"
    ] = len(
        raw_paragraphs
    )

    assignment_diag[
        "layout_container_native_suppressions"
    ] = paragraph_suppressions

    assignment_diag[
        "layout_container_native_suppression_count"
    ] = len(
        paragraph_suppressions
    )

    # 拆分统计，避免把“水印清理”误读成“layout authority 去重”。
    assignment_diag[
        "confirmed_noise_paragraph_removed_count"
    ] = sum(
        1
        for item in paragraph_suppressions
        if item.get("reason")
        == "exact_confirmed_noise_paragraph"
    )

    assignment_diag[
        "layout_authority_duplicate_removed_count"
    ] = sum(
        1
        for item in paragraph_suppressions
        if item.get("reason")
        == "paragraph_already_represented_by_layout_container"
    )

    assignment_diag[
        "layout_authority_standard_removed_count"
    ] = sum(
        1
        for item in paragraph_suppressions
        if item.get("authority_mode")
        == "standard_geometry_text"
    )

    assignment_diag[
        "layout_authority_strong_text_removed_count"
    ] = sum(
        1
        for item in paragraph_suppressions
        if item.get("authority_mode")
        == "strong_text_start_inside"
    )

    assignment_diag[
        "logical_line_count_after_authority_suppression"
    ] = len(
        line_records
    )

    table_unit_diagnostics = (
        stage63_classify_table_units(
            raw_page,
            reading_page,
        )
    )

    flow_units = (
        stage63_build_flow_units(
            reading_page,
            paragraphs,
            table_unit_diagnostics,
        )
    )

    source_status = str(
        reading_page.get(
            "status",
            "unknown",
        )
    )

    empty_text_units = int(
        assignment_diag.get(
            "empty_text_unit_count",
            0,
        )
        or 0
    )

    risky_unsupported_empty_units = int(
        assignment_diag.get(
            "risky_unsupported_empty_text_unit_count",
            0,
        )
        or 0
    )

    if (
        source_status
        != "resolved"
    ):
        status = "partial"
        confidence = "low"
        inherited_risk = True

    elif (
        risky_unsupported_empty_units
        > 0
    ):
        status = "partial"
        confidence = "low"
        inherited_risk = False

    else:
        status = "completed"
        confidence = str(
            reading_page.get(
                "confidence",
                "medium",
            )
        )
        inherited_risk = False

    return {
        "page_number":
            page_number,
        "status":
            status,
        "confidence":
            confidence,
        "source_reading_status":
            source_status,
        "source_reading_confidence":
            reading_page.get(
                "confidence"
            ),
        "inherited_reading_risk":
            inherited_risk,
        "line_count":
            len(line_records),
        "paragraph_count":
            len(paragraphs),
        "flow_unit_count":
            len(flow_units),
        "assignment_diagnostics":
            assignment_diag,
        "layout_container_count":
            sum(
                1
                for item
                in table_unit_diagnostics
                if item.get(
                    "classification"
                )
                == "layout_container"
            ),
        "data_table_count":
            sum(
                1
                for item
                in table_unit_diagnostics
                if item.get(
                    "classification"
                )
                == "data_table"
            ),
        "table_unit_diagnostics":
            table_unit_diagnostics,
        "lines":
            line_records,
        "paragraphs":
            paragraphs,
        "flow_units":
            flow_units,

        # 6.3 只重建逻辑文本流，不修改 Stage1 / Stage4 原证据。
        "source_evidence_modified":
            False,
        "cross_page_merge_completed":
            False,
        "word_break_repair_completed":
            False,
        "quality_gate_completed":
            False,
    }


def build_paragraph_result(
    snapshot_pages: dict[int, dict[str, Any]],
    reading_result: dict[str, Any],
) -> dict[str, Any]:
    pages = [
        build_page_paragraph_result(
            snapshot_pages.get(
                int(
                    reading_page[
                        "page_number"
                    ]
                ),
                {},
            ),
            reading_page,
        )
        for reading_page
        in reading_result.get(
            "pages",
            []
        )
        if isinstance(
            reading_page,
            dict,
        )
    ]

    status_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    total_lines = 0
    total_paragraphs = 0
    total_flow_units = 0
    total_empty_text_units = 0
    total_shadowed_empty_text_units = 0
    total_unsupported_empty_text_units = 0
    total_risky_unsupported_empty_text_units = 0
    total_placeholder_empty_text_units = 0
    total_layout_containers = 0
    total_data_tables = 0
    total_layout_container_ordered_text = 0
    total_layout_container_exact_noise_removed = 0
    total_layout_container_embedded_noise_removed = 0
    total_page_cross_unit_form_label_reorders = 0
    total_layout_container_native_suppressions = 0
    total_confirmed_noise_paragraph_removed = 0
    total_layout_authority_duplicate_removed = 0
    total_layout_authority_standard_removed = 0
    total_layout_authority_strong_text_removed = 0

    total_assigned_words = 0
    total_unassigned_words = 0
    total_ambiguous_candidate_words = 0
    inherited_risk_pages = 0

    for page in pages:
        status_counts[
            str(page["status"])
        ] += 1

        total_lines += int(
            page.get(
                "line_count",
                0,
            )
        )

        total_paragraphs += int(
            page.get(
                "paragraph_count",
                0,
            )
        )

        total_flow_units += int(
            page.get(
                "flow_unit_count",
                0,
            )
        )

        diagnostics = page.get(
            "assignment_diagnostics",
            {},
        )

        total_empty_text_units += int(
            diagnostics.get(
                "empty_text_unit_count",
                0,
            )
            or 0
        )

        total_shadowed_empty_text_units += int(
            diagnostics.get(
                "shadowed_empty_text_unit_count",
                0,
            )
            or 0
        )

        total_unsupported_empty_text_units += int(
            diagnostics.get(
                "unsupported_empty_text_unit_count",
                0,
            )
            or 0
        )

        total_risky_unsupported_empty_text_units += int(
            diagnostics.get(
                "risky_unsupported_empty_text_unit_count",
                0,
            )
            or 0
        )

        total_placeholder_empty_text_units += int(
            diagnostics.get(
                "placeholder_empty_text_unit_count",
                0,
            )
            or 0
        )

        total_layout_containers += int(
            page.get(
                "layout_container_count",
                0,
            )
            or 0
        )

        total_data_tables += int(
            page.get(
                "data_table_count",
                0,
            )
            or 0
        )

        total_layout_container_ordered_text += int(
            diagnostics.get(
                "layout_container_ordered_text_count",
                0,
            )
            or 0
        )

        total_layout_container_exact_noise_removed += int(
            diagnostics.get(
                "layout_container_exact_noise_line_removed_count",
                0,
            )
            or 0
        )

        total_layout_container_embedded_noise_removed += int(
            diagnostics.get(
                "layout_container_embedded_noise_removed_count",
                0,
            )
            or 0
        )

        total_page_cross_unit_form_label_reorders += int(
            diagnostics.get(
                "page_cross_unit_form_label_reorder_count",
                0,
            )
            or 0
        )

        total_layout_container_native_suppressions += int(
            diagnostics.get(
                "layout_container_native_suppression_count",
                0,
            )
            or 0
        )

        total_confirmed_noise_paragraph_removed += int(
            diagnostics.get(
                "confirmed_noise_paragraph_removed_count",
                0,
            )
            or 0
        )

        total_layout_authority_duplicate_removed += int(
            diagnostics.get(
                "layout_authority_duplicate_removed_count",
                0,
            )
            or 0
        )

        total_layout_authority_standard_removed += int(
            diagnostics.get(
                "layout_authority_standard_removed_count",
                0,
            )
            or 0
        )

        total_layout_authority_strong_text_removed += int(
            diagnostics.get(
                "layout_authority_strong_text_removed_count",
                0,
            )
            or 0
        )

        total_assigned_words += int(
            diagnostics.get(
                "assigned_word_count",
                0,
            )
            or 0
        )

        total_unassigned_words += int(
            diagnostics.get(
                "unassigned_raw_word_count",
                0,
            )
            or 0
        )

        total_ambiguous_candidate_words += int(
            diagnostics.get(
                "ambiguous_candidate_word_count",
                0,
            )
            or 0
        )

        if page.get(
            "inherited_reading_risk"
        ):
            inherited_risk_pages += 1

    return {
        "stage": "6.3",
        "version": STAGE63_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "source_file":
            reading_result.get(
                "source_file"
            ),
        "page_count":
            len(pages),
        "status_counts":
            dict(status_counts),
        "line_count":
            total_lines,
        "paragraph_count":
            total_paragraphs,
        "flow_unit_count":
            total_flow_units,
        "empty_text_unit_count":
            total_empty_text_units,
        "shadowed_empty_text_unit_count":
            total_shadowed_empty_text_units,
        "unsupported_empty_text_unit_count":
            total_unsupported_empty_text_units,
        "risky_unsupported_empty_text_unit_count":
            total_risky_unsupported_empty_text_units,
        "placeholder_empty_text_unit_count":
            total_placeholder_empty_text_units,
        "layout_container_count":
            total_layout_containers,
        "data_table_count":
            total_data_tables,
        "layout_container_ordered_text_count":
            total_layout_container_ordered_text,
        "layout_container_exact_noise_line_removed_count":
            total_layout_container_exact_noise_removed,
        "layout_container_embedded_noise_removed_count":
            total_layout_container_embedded_noise_removed,
        "page_cross_unit_form_label_reorder_count":
            total_page_cross_unit_form_label_reorders,
        # 兼容旧字段：total suppression = noise + authority duplicate。
        "layout_container_native_suppression_count":
            total_layout_container_native_suppressions,

        "confirmed_noise_paragraph_removed_count":
            total_confirmed_noise_paragraph_removed,

        "layout_authority_duplicate_removed_count":
            total_layout_authority_duplicate_removed,

        "layout_authority_standard_removed_count":
            total_layout_authority_standard_removed,

        "layout_authority_strong_text_removed_count":
            total_layout_authority_strong_text_removed,

        "assigned_word_count":
            total_assigned_words,
        "unassigned_raw_word_count":
            total_unassigned_words,
        "ambiguous_candidate_word_count":
            total_ambiguous_candidate_words,
        "inherited_reading_risk_pages":
            inherited_risk_pages,
        "pages":
            pages,
        "cross_page_merge_completed":
            False,
        "word_break_repair_completed":
            False,
        "quality_gate_completed":
            False,
        "stage_status": {
            "algorithm_baseline":
                STAGE63_VERSION,
            "sealed":
                False,
            "scope":
                "line_to_paragraph_reconstruction",
            "source_authority_policy": {
                "native_text":
                    "stage1_words",
                "data_table":
                    "preserve_table_flow_unit",
                "layout_container":
                    "stage1_table_extracted_data",
            },
        },
    }


def render_paragraph_markdown(
    result: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Stage 6.3 Line → Paragraph Reconstruction",
        "",
        f"- 文件：{result.get('source_file')}",
        f"- 页数：{result.get('page_count')}",
        f"- 行：{result.get('line_count')}",
        f"- 段落：{result.get('paragraph_count')}",
        f"- flow units：{result.get('flow_unit_count')}",
        f"- 空 text reading unit：{result.get('empty_text_unit_count')}",
        f"- 其中 overlap shadow：{result.get('shadowed_empty_text_unit_count')}",
        f"- 无 Stage1 word 支持：{result.get('unsupported_empty_text_unit_count')}",
        f"- 其中新增风险：{result.get('risky_unsupported_empty_text_unit_count')}",
        f"- 空 placeholder：{result.get('placeholder_empty_text_unit_count')}",
        f"- layout container：{result.get('layout_container_count')}",
        f"- data table：{result.get('data_table_count')}",
        f"- layout container ordered text：{result.get('layout_container_ordered_text_count')}",
        f"- layout container 删除的独立已确认 watermark 行：{result.get('layout_container_exact_noise_line_removed_count')}",
        f"- layout container 删除的嵌入式已确认 watermark：{result.get('layout_container_embedded_noise_removed_count')}",
        f"- 跨 text-unit 表单 label 重排：{result.get('page_cross_unit_form_label_reorder_count')}",
        f"- 已确认噪声 paragraph 删除：{result.get('confirmed_noise_paragraph_removed_count')}",
        f"- layout authority 重复正文删除：{result.get('layout_authority_duplicate_removed_count')}",
        f"- 其中 standard geometry+text：{result.get('layout_authority_standard_removed_count')}",
        f"- 其中 strong text+start-inside：{result.get('layout_authority_strong_text_removed_count')}",
        f"- suppression 总数（兼容字段）：{result.get('layout_container_native_suppression_count')}",
        f"- 继承 Stage6.2 风险页：{result.get('inherited_reading_risk_pages')}",
        "",
        "> 说明：本文件保留真实行边界；不做断词修复、不做跨页段落续接、不做 Quality Gate。",
        "",
    ]

    for page in result.get(
        "pages",
        []
    ):
        lines.extend(
            [
                f"## PDF 第 {page.get('page_number')} 页",
                "",
                (
                    f"- status: `{page.get('status')}`"
                    f" | confidence: `{page.get('confidence')}`"
                    f" | source_reading_status: `{page.get('source_reading_status')}`"
                    f" | lines={page.get('line_count')}"
                    f" | paragraphs={page.get('paragraph_count')}"
                    f" | empty_text_units={page.get('assignment_diagnostics', {}).get('empty_text_unit_count', 0)}"
                    f" | shadowed={page.get('assignment_diagnostics', {}).get('shadowed_empty_text_unit_count', 0)}"
                    f" | risky_empty={page.get('assignment_diagnostics', {}).get('risky_unsupported_empty_text_unit_count', 0)}"
                ),
                "",
            ]
        )

        table_details = page.get(
            "table_unit_diagnostics",
            [],
        )

        if table_details:
            lines.append(
                "### Table logical-flow classification"
            )
            lines.append("")

            for detail in table_details:
                lines.append(
                    (
                        f"- order={detail.get('reading_order')}"
                        f" | block={detail.get('block_id')}"
                        f" | class={detail.get('classification')}"
                        f" | rows={detail.get('row_count')}"
                        f" | cols={detail.get('max_columns')}"
                        f" | nonempty={detail.get('nonempty_cell_count')}"
                        f" | total_chars={detail.get('total_chars')}"
                        f" | longest={detail.get('longest_cell_chars')}"
                        f" | share={detail.get('longest_cell_share')}"
                        f" | zone={detail.get('zone_type')}"
                    )
                )

            lines.append("")

        native_suppressions = page.get(
            "assignment_diagnostics",
            {},
        ).get(
            "layout_container_native_suppressions",
            [],
        )

        if native_suppressions:
            lines.append(
                "### Paragraph-level layout-container authority suppression"
            )
            lines.append("")

            for detail in native_suppressions:
                lines.append(
                    (
                        f"- paragraph={detail.get('paragraph_id')}"
                        f" | container={detail.get('container_block_id')}"
                        f" | reason={detail.get('reason')}"
                        f" | mode={detail.get('authority_mode')}"
                        f" | bbox_coverage={detail.get('bbox_coverage')}"
                        f" | text_match={detail.get('text_match_coverage')}"
                        f" | intersects={detail.get('intersects_container')}"
                        f" | starts_inside={detail.get('paragraph_starts_in_container')}"
                        f" | text={repr(detail.get('text'))}"
                    )
                )

            lines.append("")

        layout_order_details = page.get(
            "assignment_diagnostics",
            {},
        ).get(
            "layout_container_ordered_text_diagnostics",
            [],
        )

        if layout_order_details:
            lines.append(
                "### Layout container ordered-text recovery"
            )
            lines.append("")

            for detail in layout_order_details:
                lines.append(
                    (
                        f"- order={detail.get('reading_order')}"
                        f" | block={detail.get('block_id')}"
                        f" | status={detail.get('status')}"
                        f" | cells={detail.get('cell_count')}"
                        f" | lines={detail.get('line_count')}"
                        f" | removed_exact_noise={detail.get('removed_exact_noise_line_count')}"
                        f" | visual_match={detail.get('matched_visual_line_count')}/{detail.get('line_count')}"
                        f" | visual_match_rate={detail.get('visual_match_rate')}"
                        f" | unreliable_cells={detail.get('unreliable_visual_order_cell_count')}"
                        f" | mode={detail.get('noise_filter_mode')}"
                    )
                )

            lines.append("")

        empty_details = page.get(
            "assignment_diagnostics",
            {},
        ).get(
            "empty_text_unit_details",
            [],
        )

        if empty_details:
            lines.append(
                "### Empty text unit diagnostics"
            )
            lines.append("")

            for detail in empty_details:
                lines.append(
                    (
                        f"- order={detail.get('reading_order')}"
                        f" | block={detail.get('block_id')}"
                        f" | class={detail.get('classification')}"
                        f" | candidate_words={detail.get('candidate_word_count')}"
                        f" | claimed_elsewhere={detail.get('claimed_elsewhere_word_count')}"
                        f" | winners={detail.get('winner_reading_orders')}"
                        f" | risk={detail.get('stage63_risk')}"
                        f" | preview={repr(detail.get('text_preview'))}"
                    )
                )

            lines.append("")

        for paragraph in page.get(
            "paragraphs",
            []
        ):
            heading = (
                " heading"
                if paragraph.get(
                    "is_geometric_heading"
                )
                else ""
            )

            lines.append(
                (
                    f"### {paragraph.get('paragraph_id')}"
                    f" | {paragraph.get('flow_role')}"
                    f" | {paragraph.get('column_role')}"
                    f"{heading}"
                    f" | lines={paragraph.get('line_count')}"
                    f" | break={paragraph.get('break_reason')}"
                )
            )
            lines.append("")

            for raw_line in paragraph.get(
                "lines",
                []
            ):
                lines.append(
                    raw_line
                )

            lines.append("")

        non_text_units = [
            unit
            for unit in page.get(
                "flow_units",
                []
            )
            if unit.get(
                "unit_type"
            )
            != "paragraph"
        ]

        if non_text_units:
            lines.append(
                "### Non-text flow units"
            )
            lines.append("")

            for unit in non_text_units:
                lines.append(
                    (
                        f"- order={unit.get('flow_order')}"
                        f" | type={unit.get('unit_type')}"
                        f" | block={unit.get('block_id')}"
                        f" | role={unit.get('column_role')}"
                    )
                )

            lines.append("")

    return (
        "\n".join(lines)
        .rstrip()
        + "\n"
    )


def print_paragraph_summary(
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    print()
    print("=" * 88)
    print(
        "Stage 6.3 行→段落重建"
        f" | {result.get('source_file')}"
        f" | 页数={result.get('page_count')}"
        f" | 算法版本={STAGE63_VERSION}"
        f" | Pipeline={PIPELINE_VERSION}"
    )
    print("=" * 88)

    print(
        "状态"
        f" | completed={result['status_counts'].get('completed', 0)}"
        f" | partial={result['status_counts'].get('partial', 0)}"
        f" | lines={result.get('line_count', 0)}"
        f" | paragraphs={result.get('paragraph_count', 0)}"
        f" | empty_text_units={result.get('empty_text_unit_count', 0)}"
        f" | shadowed_empty={result.get('shadowed_empty_text_unit_count', 0)}"
        f" | unsupported_empty={result.get('unsupported_empty_text_unit_count', 0)}"
        f" | risky_empty={result.get('risky_unsupported_empty_text_unit_count', 0)}"
        f" | layout_container={result.get('layout_container_count', 0)}"
        f" | data_table={result.get('data_table_count', 0)}"
        f" | layout_ordered={result.get('layout_container_ordered_text_count', 0)}"
        f" | layout_noise_removed={result.get('layout_container_exact_noise_line_removed_count', 0)}"
        f" | layout_embedded_noise_removed={result.get('layout_container_embedded_noise_removed_count', 0)}"
        f" | form_label_reordered={result.get('multiline_form_label_reorder_count', 0)}"
        f" | form_label_inline_split={result.get('inline_multiline_form_label_split_count', 0)}"
        f" | noise_para_removed={result.get('confirmed_noise_paragraph_removed_count', 0)}"
        f" | authority_dup_removed={result.get('layout_authority_duplicate_removed_count', 0)}"
        f" | authority_standard={result.get('layout_authority_standard_removed_count', 0)}"
        f" | authority_strong={result.get('layout_authority_strong_text_removed_count', 0)}"
        f" | suppression_total={result.get('layout_container_native_suppression_count', 0)}"
        f" | inherited_reading_risk_pages={result.get('inherited_reading_risk_pages', 0)}"
        f" | assigned_words={result.get('assigned_word_count', 0)}"
        f" | unassigned_raw_words={result.get('unassigned_raw_word_count', 0)}"
    )

    print(
        f"JSON：{output_dir / 'paragraphs.json'}"
    )
    print(
        f"Markdown：{output_dir / 'paragraphs.md'}"
    )
    print(
        "说明：Stage6.3 只利用 Stage1 words + Stage6.2 reading order 做几何行/段重建；"
        "一个 raw word 最多进入一个 text unit，避免重叠 bbox 重复文本；"
        "empty text unit 会区分 overlap shadow 与真正无 Stage1 word 支持，只有后者的非平凡 main text 才新增 partial；"
        "低维、长正文占主导的 table geometry 会在 logical flow 中按 layout_container 恢复正文；"
        "layout_container 优先复用 Stage1 extracted_data 的 cell/行顺序；raw words 仅作为首行缩进/可靠行距的弱段落边界证据；"
        "paragraph 重建后，再用实际 paragraph bbox + text 对 layout_container authority 做去重；"
        "常规路径保持 bbox>=0.60 + text>=0.80；若 text>=0.97 且 paragraph 起点位于 container 内并真实相交，则允许 strong-text 路径，不降低全局 bbox 阈值；"
        "Stage6.1 已确认的 watermark 仅在 char geometry 精确匹配后从受污染 raw word 中排除；"
        "layout_container 只替换完整、已确认污染的 raw word，不按固定字符值做全局删除；Stage1/Stage4 table 证据不删除；"
        "不做跨页正文续接、不做断词/语义修复、不做 OCR / Quality Gate；"
        "Stage6.2 已标 partial 的复杂页继续保持 partial，不会被本阶段掩盖。"
    )
    print("=" * 88)



# =============================================================================
# Stage 6.4 Cross-page Ordinary Paragraph Continuation
# =============================================================================

# v0.1.0 采用“高精度优先”的保守策略：
# 宁可漏掉一部分真正跨页段落，也不把两个独立段落错误粘在一起。
STAGE64_ALLOWED_ZONE_TYPES = {
    "semi_free",
}

STAGE64_PREV_LAST_LINE_MIN_BOTTOM_RATIO = 0.68
STAGE64_NEXT_FIRST_LINE_MAX_TOP_RATIO = 0.30

# 上一页尾行需要基本铺满正文行宽，说明它更像是“被分页截断”的连续行，
# 而不是一个自然结束的短尾行。
STAGE64_PREV_LAST_LINE_MIN_FILL_RATIO = 0.72

# 下一页第一行如果相对正文左边界有明显首行缩进，更像新段落。
# 单位使用该页 median word height，避免绑定固定 pt。
STAGE64_NEXT_FIRST_LINE_MAX_INDENT_HEIGHT_RATIO = 1.25

# paragraph 长度不再作为 hard gate。
# 跨页时上一页/下一页 fragment 天然可能只有一行，
# “短”本身不能区分正文 continuation 与图注/标题。
# 长度仅保留为审计指标，真正的结构保护交给：
# structural boundary / terminal / page-edge geometry / indent / non-text boundary。
# 强句末标点：继续保守处理。
# 即使现实中同一自然段也可能恰好在分页前结束一句，
# 这里仍先拒绝，优先保证 precision。
STAGE64_STRONG_TERMINALS = set(
    "。！？!?；;：:."
)


def stage64_structure_value(
    reading_page: dict[str, Any],
    key: str,
) -> Any:
    structure = reading_page.get(
        "document_structure",
        {},
    )

    if not isinstance(
        structure,
        dict,
    ):
        return None

    return structure.get(
        key
    )


def stage64_paragraph_text(
    paragraph: dict[str, Any],
) -> str:
    return clean_text(
        paragraph.get(
            "text_with_linebreaks",
            "",
        )
    )


def stage64_is_plain_native_paragraph(
    paragraph: dict[str, Any],
) -> bool:
    """
    Stage6.4 只要求“来源与流属性可靠”。

    注意：
    Stage6.3 的 is_geometric_heading 是页内段落重建的弱几何标签，
    在页边界处会因为“只剩一两行 / bbox 特殊”而大量误报。
    因此 Stage6.4 不再把该标签作为硬拒绝条件。

    真正的跨页结构保护由后续独立规则完成：
    - 下一页标题 / 编号项识别；
    - 最小段落长度；
    - 页边界几何；
    - table / image / vector 边界保护；
    - partial / multi-column / layout_container 排除。
    """
    return (
        paragraph.get(
            "flow_role"
        )
        == "main"
        and paragraph.get(
            "column_role"
        )
        == "single"
        and paragraph.get(
            "source_kinds"
        )
        == ["native_text"]
        and not paragraph.get(
            "uses_synthetic_geometry"
        )
    )


def stage64_find_paragraph_by_id(
    page: dict[str, Any],
    paragraph_id: str,
) -> dict[str, Any] | None:
    for paragraph in page.get(
        "paragraphs",
        [],
    ):
        if (
            paragraph.get(
                "paragraph_id"
            )
            == paragraph_id
        ):
            return paragraph

    return None


def stage64_boundary_paragraph(
    page: dict[str, Any],
    *,
    side: str,
) -> dict[str, Any] | None:
    """
    只允许真正位于 page logical flow 边缘的 paragraph。

    prev page：最后一个 flow unit 必须就是 paragraph。
    next page：第一个 flow unit 必须就是 paragraph。

    如果边界存在 table/image/vector，则本阶段直接不跨过去。
    """
    units = [
        unit
        for unit in page.get(
            "flow_units",
            []
        )
        if isinstance(
            unit,
            dict,
        )
    ]

    if not units:
        return None

    unit = (
        units[-1]
        if side == "tail"
        else units[0]
    )

    if (
        unit.get(
            "unit_type"
        )
        != "paragraph"
    ):
        return None

    paragraph_id = str(
        unit.get(
            "paragraph_id"
        )
        or ""
    )

    if not paragraph_id:
        return None

    return stage64_find_paragraph_by_id(
        page,
        paragraph_id,
    )


def stage64_line_matches_paragraph_edge(
    line: dict[str, Any],
    paragraph: dict[str, Any],
    *,
    side: str,
) -> bool:
    paragraph_lines = paragraph.get(
        "lines",
        [],
    )

    if not paragraph_lines:
        return False

    target_text = clean_text(
        paragraph_lines[-1]
        if side == "tail"
        else paragraph_lines[0]
    )

    if not target_text:
        return False

    if clean_text(
        line.get(
            "text",
            "",
        )
    ) != target_text:
        return False

    paragraph_bbox = paragraph.get(
        "bbox"
    )
    line_bbox = line.get(
        "bbox"
    )

    if not isinstance(
        paragraph_bbox,
        dict,
    ) or not isinstance(
        line_bbox,
        dict,
    ):
        return False

    line_area = stage63_bbox_area(
        line_bbox
    )

    if line_area <= 0:
        return False

    overlap = stage63_bbox_intersection_area(
        line_bbox,
        paragraph_bbox,
    )

    return (
        overlap / line_area
        >= 0.80
    )


def stage64_find_boundary_line(
    page: dict[str, Any],
    paragraph: dict[str, Any],
    *,
    side: str,
) -> dict[str, Any] | None:
    candidates = [
        line
        for line in page.get(
            "lines",
            []
        )
        if (
            isinstance(
                line,
                dict,
            )
            and stage64_line_matches_paragraph_edge(
                line,
                paragraph,
                side=side,
            )
        )
    ]

    if not candidates:
        return None

    if side == "tail":
        return max(
            candidates,
            key=lambda line: float(
                line.get(
                    "bbox",
                    {},
                ).get(
                    "top",
                    0.0,
                )
            ),
        )

    return min(
        candidates,
        key=lambda line: float(
            line.get(
                "bbox",
                {},
            ).get(
                "top",
                0.0,
            )
        ),
    )


def stage64_quantile(
    values: list[float],
    q: float,
) -> float | None:
    if not values:
        return None

    ordered = sorted(
        values
    )

    if len(ordered) == 1:
        return ordered[0]

    position = (
        max(
            0.0,
            min(
                1.0,
                q,
            ),
        )
        * (
            len(ordered)
            - 1
        )
    )

    lo = int(
        math.floor(
            position
        )
    )
    hi = int(
        math.ceil(
            position
        )
    )

    if lo == hi:
        return ordered[lo]

    fraction = (
        position
        - lo
    )

    return (
        ordered[lo]
        * (
            1.0
            - fraction
        )
        + ordered[hi]
        * fraction
    )


def stage64_page_body_geometry(
    page: dict[str, Any],
) -> dict[str, float] | None:
    """
    只使用 main + single + native logical lines 估计该页正文行盒。

    body_right 用 x1 的 75% 分位而不是 max，
    避免一个异常长行把正文右边界拉偏。
    """
    lines = [
        line
        for line in page.get(
            "lines",
            []
        )
        if (
            isinstance(
                line,
                dict,
            )
            and line.get(
                "flow_role"
            )
            == "main"
            and line.get(
                "column_role"
            )
            == "single"
            and line.get(
                "stage63_source_kind"
            )
            == "native_text"
            and isinstance(
                line.get(
                    "bbox"
                ),
                dict,
            )
        )
    ]

    if not lines:
        return None

    x0s = [
        float(
            line["bbox"]["x0"]
        )
        for line in lines
    ]

    x1s = [
        float(
            line["bbox"]["x1"]
        )
        for line in lines
    ]

    heights = [
        max(
            1.0,
            float(
                line["bbox"]["bottom"]
            )
            - float(
                line["bbox"]["top"]
            ),
        )
        for line in lines
    ]

    body_left = median_number(
        x0s
    )
    body_right = stage64_quantile(
        x1s,
        0.75,
    )
    line_height = median_number(
        heights
    )

    if (
        body_left is None
        or body_right is None
        or line_height is None
        or body_right
        <= body_left
    ):
        return None

    return {
        "body_left":
            float(
                body_left
            ),
        "body_right":
            float(
                body_right
            ),
        "line_height":
            float(
                line_height
            ),
    }


def stage64_strip_closing_marks(
    text: str,
) -> str:
    value = text.rstrip()

    closing_marks = (
        "\"'”’》」』】）)]}"
    )

    while (
        value
        and value[-1]
        in closing_marks
    ):
        value = value[:-1].rstrip()

    return value


def stage64_ends_with_strong_terminal(
    paragraph: dict[str, Any],
) -> bool:
    text = stage64_strip_closing_marks(
        stage64_paragraph_text(
            paragraph
        )
    )

    return bool(
        text
        and text[-1]
        in STAGE64_STRONG_TERMINALS
    )


def stage64_starts_structural_boundary(
    paragraph: dict[str, Any],
) -> bool:
    text = stage64_paragraph_text(
        paragraph
    )

    if not text:
        return True

    first_line = (
        paragraph.get(
            "lines",
            [text],
        )[0]
        if paragraph.get(
            "lines"
        )
        else text
    )

    first_line = stage63_normalize_preserved_line(
        first_line
    )

    if not first_line:
        return True

    if stage63_layout_is_enumeration_line(
        first_line
    ):
        return True

    if stage63_layout_is_heading_like_line(
        first_line
    ):
        return True

    # 补充通用结构开头，不绑定具体模板标题。
    if re.match(
        r"^(?:"
        r"[（(][一二三四五六七八九十百]+[）)]"
        r"|"
        r"第[一二三四五六七八九十百\d]+[章节部分篇]"
        r"|"
        r"\d+(?:\.\d+){1,4}\s+"
        r"|"
        r"[•●▪■]\s*"
        r")",
        first_line,
    ):
        return True

    return False


def stage64_candidate_metrics(
    prev_page: dict[str, Any],
    next_page: dict[str, Any],
    prev_paragraph: dict[str, Any],
    next_paragraph: dict[str, Any],
    prev_raw_page: dict[str, Any],
    next_raw_page: dict[str, Any],
) -> dict[str, Any]:
    prev_line = stage64_find_boundary_line(
        prev_page,
        prev_paragraph,
        side="tail",
    )

    next_line = stage64_find_boundary_line(
        next_page,
        next_paragraph,
        side="head",
    )

    prev_geometry = (
        stage64_page_body_geometry(
            prev_page
        )
    )

    next_geometry = (
        stage64_page_body_geometry(
            next_page
        )
    )

    metrics: dict[str, Any] = {
        "prev_boundary_line_found":
            prev_line is not None,
        "next_boundary_line_found":
            next_line is not None,
        "prev_body_geometry_found":
            prev_geometry is not None,
        "next_body_geometry_found":
            next_geometry is not None,
    }

    if (
        prev_line is None
        or next_line is None
        or prev_geometry is None
        or next_geometry is None
    ):
        return metrics

    prev_height = float(
        prev_raw_page.get(
            "height",
            0.0,
        )
        or 0.0
    )
    next_height = float(
        next_raw_page.get(
            "height",
            0.0,
        )
        or 0.0
    )

    if (
        prev_height <= 0
        or next_height <= 0
    ):
        metrics[
            "page_size_valid"
        ] = False
        return metrics

    metrics[
        "page_size_valid"
    ] = True

    prev_bbox = prev_line[
        "bbox"
    ]
    next_bbox = next_line[
        "bbox"
    ]

    prev_bottom_ratio = (
        float(
            prev_bbox[
                "bottom"
            ]
        )
        / prev_height
    )

    next_top_ratio = (
        float(
            next_bbox[
                "top"
            ]
        )
        / next_height
    )

    prev_body_width = max(
        1.0,
        (
            prev_geometry[
                "body_right"
            ]
            - prev_geometry[
                "body_left"
            ]
        ),
    )

    prev_fill_ratio = (
        float(
            prev_bbox[
                "x1"
            ]
        )
        - prev_geometry[
            "body_left"
        ]
    ) / prev_body_width

    prev_fill_ratio = max(
        0.0,
        min(
            1.5,
            prev_fill_ratio,
        ),
    )

    next_indent = (
        float(
            next_bbox[
                "x0"
            ]
        )
        - next_geometry[
            "body_left"
        ]
    )

    next_indent_height_ratio = (
        next_indent
        / max(
            1.0,
            next_geometry[
                "line_height"
            ],
        )
    )

    metrics.update(
        {
            "prev_last_line_bottom_ratio":
                round(
                    prev_bottom_ratio,
                    4,
                ),
            "next_first_line_top_ratio":
                round(
                    next_top_ratio,
                    4,
                ),
            "prev_last_line_fill_ratio":
                round(
                    prev_fill_ratio,
                    4,
                ),
            "next_first_line_indent_height_ratio":
                round(
                    next_indent_height_ratio,
                    4,
                ),
            "prev_body_left":
                round(
                    prev_geometry[
                        "body_left"
                    ],
                    3,
                ),
            "prev_body_right":
                round(
                    prev_geometry[
                        "body_right"
                    ],
                    3,
                ),
            "next_body_left":
                round(
                    next_geometry[
                        "body_left"
                    ],
                    3,
                ),
            "next_body_right":
                round(
                    next_geometry[
                        "body_right"
                    ],
                    3,
                ),
        }
    )

    return metrics


def stage64_evaluate_boundary(
    prev_page: dict[str, Any],
    next_page: dict[str, Any],
    prev_reading_page: dict[str, Any],
    next_reading_page: dict[str, Any],
    prev_raw_page: dict[str, Any],
    next_raw_page: dict[str, Any],
) -> dict[str, Any]:
    prev_page_number = int(
        prev_page[
            "page_number"
        ]
    )
    next_page_number = int(
        next_page[
            "page_number"
        ]
    )

    result: dict[str, Any] = {
        "edge_id":
            (
                f"p{prev_page_number:04d}"
                f"_to_p{next_page_number:04d}"
            ),
        "from_page":
            prev_page_number,
        "to_page":
            next_page_number,
        "decision":
            "rejected",
        "confidence":
            "none",
        "reason":
            None,
        "metrics":
            {},
    }

    if (
        next_page_number
        != prev_page_number + 1
    ):
        result[
            "reason"
        ] = "not_adjacent_pages"
        return result

    if (
        prev_page.get(
            "status"
        )
        != "completed"
        or next_page.get(
            "status"
        )
        != "completed"
    ):
        result[
            "reason"
        ] = "page_not_completed"
        return result

    prev_section = stage64_structure_value(
        prev_reading_page,
        "section_id",
    )
    next_section = stage64_structure_value(
        next_reading_page,
        "section_id",
    )

    if (
        not prev_section
        or not next_section
        or prev_section
        != next_section
    ):
        result[
            "reason"
        ] = "section_mismatch_or_missing"
        return result

    prev_zone = stage64_structure_value(
        prev_reading_page,
        "zone_type",
    )
    next_zone = stage64_structure_value(
        next_reading_page,
        "zone_type",
    )

    if (
        prev_zone
        != next_zone
        or prev_zone
        not in STAGE64_ALLOWED_ZONE_TYPES
    ):
        result[
            "reason"
        ] = "zone_not_allowed"
        return result

    prev_paragraph = (
        stage64_boundary_paragraph(
            prev_page,
            side="tail",
        )
    )
    next_paragraph = (
        stage64_boundary_paragraph(
            next_page,
            side="head",
        )
    )

    if (
        prev_paragraph is None
        or next_paragraph is None
    ):
        result[
            "reason"
        ] = "non_text_boundary_or_missing_paragraph"
        return result

    result[
        "from_paragraph_id"
    ] = prev_paragraph.get(
        "paragraph_id"
    )
    result[
        "to_paragraph_id"
    ] = next_paragraph.get(
        "paragraph_id"
    )

    result[
        "from_preview"
    ] = stage64_paragraph_text(
        prev_paragraph
    )[-180:]

    result[
        "to_preview"
    ] = stage64_paragraph_text(
        next_paragraph
    )[:180]

    if (
        not stage64_is_plain_native_paragraph(
            prev_paragraph
        )
        or not stage64_is_plain_native_paragraph(
            next_paragraph
        )
    ):
        result[
            "reason"
        ] = "not_plain_native_paragraph"
        return result

    prev_text = stage64_paragraph_text(
        prev_paragraph
    )
    next_text = stage64_paragraph_text(
        next_paragraph
    )

    # 长度只用于诊断，不再作为跨页 continuation 的硬拒绝条件。
    # 页边界 fragment 只有一行是正常现象；直接按字符数过滤会误杀真实续接。
    result[
        "text_metrics"
    ] = {
        "prev_char_count":
            len(prev_text),
        "next_char_count":
            len(next_text),
    }

    if stage64_starts_structural_boundary(
        next_paragraph
    ):
        result[
            "reason"
        ] = "next_starts_structural_boundary"
        return result

    if stage64_ends_with_strong_terminal(
        prev_paragraph
    ):
        result[
            "reason"
        ] = "prev_ends_strong_terminal"
        return result

    metrics = stage64_candidate_metrics(
        prev_page,
        next_page,
        prev_paragraph,
        next_paragraph,
        prev_raw_page,
        next_raw_page,
    )

    result[
        "metrics"
    ] = metrics

    required_metric_flags = (
        "prev_boundary_line_found",
        "next_boundary_line_found",
        "prev_body_geometry_found",
        "next_body_geometry_found",
        "page_size_valid",
    )

    if not all(
        metrics.get(
            key
        )
        for key in required_metric_flags
    ):
        result[
            "reason"
        ] = "insufficient_geometry_evidence"
        return result

    if (
        float(
            metrics[
                "prev_last_line_bottom_ratio"
            ]
        )
        < STAGE64_PREV_LAST_LINE_MIN_BOTTOM_RATIO
    ):
        result[
            "reason"
        ] = "prev_text_not_near_page_bottom"
        return result

    if (
        float(
            metrics[
                "next_first_line_top_ratio"
            ]
        )
        > STAGE64_NEXT_FIRST_LINE_MAX_TOP_RATIO
    ):
        result[
            "reason"
        ] = "next_text_not_near_page_top"
        return result

    if (
        float(
            metrics[
                "prev_last_line_fill_ratio"
            ]
        )
        < STAGE64_PREV_LAST_LINE_MIN_FILL_RATIO
    ):
        result[
            "reason"
        ] = "prev_last_line_too_short"
        return result

    if (
        float(
            metrics[
                "next_first_line_indent_height_ratio"
            ]
        )
        > STAGE64_NEXT_FIRST_LINE_MAX_INDENT_HEIGHT_RATIO
    ):
        result[
            "reason"
        ] = "next_first_line_looks_indented"
        return result

    result[
        "decision"
    ] = "confirmed"
    result[
        "confidence"
    ] = "high"
    result[
        "reason"
    ] = "high_confidence_cross_page_continuation"

    return result


def stage64_build_logical_paragraphs(
    paragraph_result: dict[str, Any],
    confirmed_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    不修改 Stage6.3 physical paragraphs。

    这里只生成独立 logical paragraph view。
    多页 fragment 仍逐段保留，文本拼接只插入 '\\n'，
    不做跨页断词修复；6.5 再处理。
    """
    paragraphs: list[
        dict[str, Any]
    ] = []

    paragraph_by_id: dict[
        str,
        dict[str, Any]
    ] = {}

    for page in paragraph_result.get(
        "pages",
        [],
    ):
        for paragraph in page.get(
            "paragraphs",
            [],
        ):
            paragraph_id = str(
                paragraph[
                    "paragraph_id"
                ]
            )

            copied = dict(
                paragraph
            )

            paragraphs.append(
                copied
            )
            paragraph_by_id[
                paragraph_id
            ] = copied

    outgoing = {
        str(edge["from_paragraph_id"]):
            str(edge["to_paragraph_id"])
        for edge in confirmed_edges
    }

    incoming = {
        str(edge["to_paragraph_id"]):
            str(edge["from_paragraph_id"])
        for edge in confirmed_edges
    }

    edge_by_pair = {
        (
            str(edge["from_paragraph_id"]),
            str(edge["to_paragraph_id"]),
        ):
            edge
        for edge in confirmed_edges
    }

    logical: list[
        dict[str, Any]
    ] = []

    visited: set[str] = set()

    for paragraph in paragraphs:
        start_id = str(
            paragraph[
                "paragraph_id"
            ]
        )

        if (
            start_id in visited
            or start_id in incoming
        ):
            continue

        chain: list[
            dict[str, Any]
        ] = []

        edge_ids: list[str] = []

        current_id = start_id

        while (
            current_id
            and current_id
            not in visited
            and current_id
            in paragraph_by_id
        ):
            current = paragraph_by_id[
                current_id
            ]

            chain.append(
                current
            )
            visited.add(
                current_id
            )

            next_id = outgoing.get(
                current_id
            )

            if not next_id:
                break

            edge = edge_by_pair.get(
                (
                    current_id,
                    next_id,
                )
            )

            if edge is not None:
                edge_ids.append(
                    str(
                        edge[
                            "edge_id"
                        ]
                    )
                )

            current_id = next_id

        logical_id = (
            f"lp{len(logical) + 1:06d}"
        )

        fragments = [
            {
                "page_number":
                    int(
                        item[
                            "page_number"
                        ]
                    ),
                "paragraph_id":
                    item[
                        "paragraph_id"
                    ],
                "text_with_linebreaks":
                    item.get(
                        "text_with_linebreaks",
                        "",
                    ),
                "source_kinds":
                    item.get(
                        "source_kinds",
                        [],
                    ),
                # v0.6.6：把 physical paragraph 的几何继续带到 logical view。
                # Stage6.6 需要它把 image/vector/table 插回正文原始阅读位置。
                "bbox":
                    item.get(
                        "bbox"
                    ),
                "source_reading_orders":
                    item.get(
                        "source_reading_orders",
                        [],
                    ),
                "source_block_ids":
                    item.get(
                        "source_block_ids",
                        [],
                    ),
                "source_word_indices":
                    item.get(
                        "source_word_indices",
                        [],
                    ),
                "is_geometric_heading":
                    bool(
                        item.get(
                            "is_geometric_heading",
                            False,
                        )
                    ),
            }
            for item in chain
        ]

        logical.append(
            {
                "logical_paragraph_id":
                    logical_id,
                "status":
                    (
                        "cross_page_merged"
                        if len(chain) > 1
                        else "single"
                    ),
                "fragment_count":
                    len(chain),
                "source_pages":
                    [
                        item[
                            "page_number"
                        ]
                        for item in fragments
                    ],
                "source_paragraph_ids":
                    [
                        item[
                            "paragraph_id"
                        ]
                        for item in fragments
                    ],
                "edge_ids":
                    edge_ids,
                "flow_role":
                    chain[0].get(
                        "flow_role"
                    )
                    if chain
                    else None,
                "column_role":
                    chain[0].get(
                        "column_role"
                    )
                    if chain
                    else None,
                "fragments":
                    fragments,

                # 仅逻辑拼接；跨页边界保留为换行。
                # 6.5 才允许处理断词、连字符等。
                "text_with_page_boundaries":
                    "\n".join(
                        item[
                            "text_with_linebreaks"
                        ]
                        for item in fragments
                    ),
                "page_boundary_join_mode":
                    "preserve_newline",
                "word_break_repair_completed":
                    False,
            }
        )

    # 防御：理论上不会出现有 incoming 但起点没被遍历的 cycle；
    # 若出现，也不能静默丢 paragraph。
    for paragraph in paragraphs:
        paragraph_id = str(
            paragraph[
                "paragraph_id"
            ]
        )

        if paragraph_id in visited:
            continue

        logical.append(
            {
                "logical_paragraph_id":
                    f"lp{len(logical) + 1:06d}",
                "status":
                    "single",
                "fragment_count":
                    1,
                "source_pages":
                    [
                        paragraph[
                            "page_number"
                        ]
                    ],
                "source_paragraph_ids":
                    [
                        paragraph_id
                    ],
                "edge_ids":
                    [],
                "flow_role":
                    paragraph.get(
                        "flow_role"
                    ),
                "column_role":
                    paragraph.get(
                        "column_role"
                    ),
                "fragments":
                    [
                        {
                            "page_number":
                                paragraph[
                                    "page_number"
                                ],
                            "paragraph_id":
                                paragraph_id,
                            "text_with_linebreaks":
                                paragraph.get(
                                    "text_with_linebreaks",
                                    "",
                                ),
                            "source_kinds":
                                paragraph.get(
                                    "source_kinds",
                                    [],
                                ),
                            "bbox":
                                paragraph.get(
                                    "bbox"
                                ),
                            "source_reading_orders":
                                paragraph.get(
                                    "source_reading_orders",
                                    [],
                                ),
                            "source_block_ids":
                                paragraph.get(
                                    "source_block_ids",
                                    [],
                                ),
                            "source_word_indices":
                                paragraph.get(
                                    "source_word_indices",
                                    [],
                                ),
                            "is_geometric_heading":
                                bool(
                                    paragraph.get(
                                        "is_geometric_heading",
                                        False,
                                    )
                                ),
                        }
                    ],
                "text_with_page_boundaries":
                    paragraph.get(
                        "text_with_linebreaks",
                        "",
                    ),
                "page_boundary_join_mode":
                    "none",
                "word_break_repair_completed":
                    False,
            }
        )

        visited.add(
            paragraph_id
        )

    return logical


def build_cross_page_paragraph_result(
    snapshot_pages: dict[int, dict[str, Any]],
    reading_result: dict[str, Any],
    paragraph_result: dict[str, Any],
) -> dict[str, Any]:
    paragraph_pages = {
        int(page["page_number"]):
            page
        for page in paragraph_result.get(
            "pages",
            [],
        )
        if isinstance(
            page,
            dict,
        )
    }

    reading_pages = {
        int(page["page_number"]):
            page
        for page in reading_result.get(
            "pages",
            [],
        )
        if isinstance(
            page,
            dict,
        )
    }

    page_numbers = sorted(
        paragraph_pages
    )

    boundary_candidates: list[
        dict[str, Any]
    ] = []

    skip_reason_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    evaluated_boundary_count = 0

    for prev_page_number in page_numbers:
        next_page_number = (
            prev_page_number + 1
        )

        if (
            next_page_number
            not in paragraph_pages
        ):
            continue

        evaluated_boundary_count += 1

        prev_page = paragraph_pages[
            prev_page_number
        ]
        next_page = paragraph_pages[
            next_page_number
        ]

        prev_reading = reading_pages.get(
            prev_page_number,
            {},
        )
        next_reading = reading_pages.get(
            next_page_number,
            {},
        )

        prev_section = stage64_structure_value(
            prev_reading,
            "section_id",
        )
        next_section = stage64_structure_value(
            next_reading,
            "section_id",
        )

        prev_zone = stage64_structure_value(
            prev_reading,
            "zone_type",
        )
        next_zone = stage64_structure_value(
            next_reading,
            "zone_type",
        )

        # candidate generation 本身也保守：
        # 只有同 section + 同 allowed zone 才值得进入详细 boundary audit。
        if (
            not prev_section
            or prev_section
            != next_section
        ):
            skip_reason_counts[
                "section_mismatch_or_missing"
            ] += 1
            continue

        if (
            prev_zone
            != next_zone
            or prev_zone
            not in STAGE64_ALLOWED_ZONE_TYPES
        ):
            skip_reason_counts[
                "zone_not_allowed"
            ] += 1
            continue

        evaluation = (
            stage64_evaluate_boundary(
                prev_page,
                next_page,
                prev_reading,
                next_reading,
                snapshot_pages.get(
                    prev_page_number,
                    {},
                ),
                snapshot_pages.get(
                    next_page_number,
                    {},
                ),
            )
        )

        boundary_candidates.append(
            evaluation
        )

    confirmed_edges = [
        item
        for item in boundary_candidates
        if item.get(
            "decision"
        )
        == "confirmed"
    ]

    rejected_candidates = [
        item
        for item in boundary_candidates
        if item.get(
            "decision"
        )
        == "rejected"
    ]

    rejection_reason_counts: dict[
        str,
        int,
    ] = defaultdict(int)

    for item in rejected_candidates:
        rejection_reason_counts[
            str(
                item.get(
                    "reason"
                )
                or "unknown"
            )
        ] += 1

    logical_paragraphs = (
        stage64_build_logical_paragraphs(
            paragraph_result,
            confirmed_edges,
        )
    )

    merged_groups = [
        item
        for item in logical_paragraphs
        if item.get(
            "status"
        )
        == "cross_page_merged"
    ]

    physical_paragraph_count = int(
        paragraph_result.get(
            "paragraph_count",
            0,
        )
        or 0
    )

    return {
        "stage":
            "6.4",
        "version":
            STAGE64_VERSION,
        "pipeline_version":
            PIPELINE_VERSION,
        "source_file":
            paragraph_result.get(
                "source_file"
            ),
        "page_count":
            paragraph_result.get(
                "page_count"
            ),
        "evaluated_adjacent_boundary_count":
            evaluated_boundary_count,
        "candidate_boundary_count":
            len(
                boundary_candidates
            ),
        "confirmed_boundary_count":
            len(
                confirmed_edges
            ),
        "rejected_candidate_count":
            len(
                rejected_candidates
            ),
        "skip_reason_counts":
            dict(
                skip_reason_counts
            ),
        "rejection_reason_counts":
            dict(
                rejection_reason_counts
            ),
        "physical_paragraph_count":
            physical_paragraph_count,
        "logical_paragraph_count":
            len(
                logical_paragraphs
            ),
        "merged_logical_paragraph_count":
            len(
                merged_groups
            ),
        "merged_fragment_count":
            sum(
                int(
                    item.get(
                        "fragment_count",
                        0,
                    )
                )
                for item in merged_groups
            ),
        "boundary_candidates":
            boundary_candidates,
        "confirmed_edges":
            confirmed_edges,
        "logical_paragraphs":
            logical_paragraphs,

        # 关键审计语义：
        # 6.3 physical paragraphs 仍是不可变审计视图。
        "physical_paragraphs_modified":
            False,
        "cross_page_merge_completed":
            True,
        "word_break_repair_completed":
            False,
        "quality_gate_completed":
            False,
        "stage_status": {
            "algorithm_baseline":
                STAGE64_VERSION,
            "sealed":
                True,
            "scope":
                "high_confidence_ordinary_cross_page_paragraph_continuation",
            "precision_policy":
                "prefer_false_negative_over_false_positive",
            "geometric_heading_policy":
                "not_a_hard_gate_at_page_boundary",
            "paragraph_length_policy":
                "diagnostic_only_not_a_hard_gate",
            "allowed_zone_types":
                sorted(
                    STAGE64_ALLOWED_ZONE_TYPES
                ),
            "excluded_sources": [
                "layout_container_ordered_text",
                "data_table",
                "image",
                "vector",
                "multi_column",
                "partial_page",
            ],
        },
    }


def render_cross_page_paragraph_markdown(
    result: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Stage 6.4 Cross-page Ordinary Paragraph Continuation",
        "",
        f"- 文件：{result.get('source_file')}",
        f"- 页数：{result.get('page_count')}",
        f"- 相邻页边界：{result.get('evaluated_adjacent_boundary_count')}",
        f"- 进入候选审计：{result.get('candidate_boundary_count')}",
        f"- confirmed：{result.get('confirmed_boundary_count')}",
        f"- rejected：{result.get('rejected_candidate_count')}",
        f"- physical paragraphs：{result.get('physical_paragraph_count')}",
        f"- logical paragraphs：{result.get('logical_paragraph_count')}",
        f"- merged logical paragraphs：{result.get('merged_logical_paragraph_count')}",
        "",
        "> Stage6.4 不修改 paragraphs.json；只生成独立 logical paragraph view。"
        " 跨页 fragment 之间只保留换行，不做断词/字符修复。",
        "",
        "## Confirmed edges",
        "",
    ]

    confirmed = result.get(
        "confirmed_edges",
        [],
    )

    if not confirmed:
        lines.append(
            "_无 confirmed cross-page continuation。_"
        )
        lines.append("")
    else:
        for edge in confirmed:
            metrics = edge.get(
                "metrics",
                {},
            )

            lines.extend(
                [
                    (
                        f"### {edge.get('edge_id')}"
                        f" | {edge.get('from_paragraph_id')}"
                        f" → {edge.get('to_paragraph_id')}"
                    ),
                    "",
                    (
                        f"- pages: {edge.get('from_page')} → {edge.get('to_page')}"
                        f" | confidence={edge.get('confidence')}"
                    ),
                    (
                        f"- prev_chars={edge.get('text_metrics', {}).get('prev_char_count')}"
                        f" | next_chars={edge.get('text_metrics', {}).get('next_char_count')}"
                    ),
                    (
                        f"- prev_bottom={metrics.get('prev_last_line_bottom_ratio')}"
                        f" | next_top={metrics.get('next_first_line_top_ratio')}"
                        f" | prev_fill={metrics.get('prev_last_line_fill_ratio')}"
                        f" | next_indent={metrics.get('next_first_line_indent_height_ratio')}"
                    ),
                    f"- prev tail：`{edge.get('from_preview')}`",
                    f"- next head：`{edge.get('to_preview')}`",
                    "",
                ]
            )

    lines.extend(
        [
            "## Rejected candidate boundaries",
            "",
        ]
    )

    for edge in result.get(
        "boundary_candidates",
        [],
    ):
        if edge.get(
            "decision"
        ) != "rejected":
            continue

        lines.append(
            (
                f"- {edge.get('edge_id')}"
                f" | reason={edge.get('reason')}"
                f" | from={edge.get('from_paragraph_id')}"
                f" | to={edge.get('to_paragraph_id')}"
            )
        )

    lines.extend(
        [
            "",
            "## Merged logical paragraphs",
            "",
        ]
    )

    merged = [
        item
        for item in result.get(
            "logical_paragraphs",
            [],
        )
        if item.get(
            "status"
        )
        == "cross_page_merged"
    ]

    if not merged:
        lines.append(
            "_无跨页逻辑合并段。_"
        )
    else:
        for item in merged:
            lines.extend(
                [
                    (
                        f"### {item.get('logical_paragraph_id')}"
                        f" | pages={item.get('source_pages')}"
                        f" | fragments={item.get('fragment_count')}"
                    ),
                    "",
                ]
            )

            for fragment in item.get(
                "fragments",
                [],
            ):
                lines.append(
                    (
                        f"**PDF 第 {fragment.get('page_number')} 页"
                        f" / {fragment.get('paragraph_id')}**"
                    )
                )
                lines.append("")
                lines.append(
                    fragment.get(
                        "text_with_linebreaks",
                        "",
                    )
                )
                lines.append("")

    return (
        "\n".join(
            lines
        ).rstrip()
        + "\n"
    )


def print_cross_page_paragraph_summary(
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    print()
    print("=" * 96)
    print(
        "Stage 6.4 跨页普通正文续接"
        f" | {result.get('source_file')}"
        f" | 页数={result.get('page_count')}"
        f" | 算法版本={STAGE64_VERSION}"
        f" | Pipeline={PIPELINE_VERSION}"
    )
    print("=" * 96)

    print(
        "状态"
        f" | adjacent_boundaries={result.get('evaluated_adjacent_boundary_count', 0)}"
        f" | candidates={result.get('candidate_boundary_count', 0)}"
        f" | confirmed={result.get('confirmed_boundary_count', 0)}"
        f" | rejected={result.get('rejected_candidate_count', 0)}"
        f" | physical_paragraphs={result.get('physical_paragraph_count', 0)}"
        f" | logical_paragraphs={result.get('logical_paragraph_count', 0)}"
        f" | merged_groups={result.get('merged_logical_paragraph_count', 0)}"
        f" | merged_fragments={result.get('merged_fragment_count', 0)}"
    )

    print(
        f"JSON：{output_dir / 'cross_page_paragraphs.json'}"
    )
    print(
        f"Markdown：{output_dir / 'cross_page_paragraphs.md'}"
    )

    print(
        "说明：v0.1.2 只处理同 section 的 semi_free 普通单栏 native 正文；"
        "边界存在 table/image/vector、复杂/partial 页、layout_container、多栏时不合并；"
        "Stage6.3 geometric-heading 标签不再作为硬拒绝，下一页标题/编号项由独立文本结构规则拦截；"
        "paragraph 字符长度仅做诊断，不再硬拒绝，因为页边界 fragment 天然可能只有一行；"
        "上一页尾行需接近页底并基本铺满正文宽度，下一页首行需靠近页顶且没有明显首行缩进；"
        "上一页若已有强句末标点则保守拒绝。"
        "本阶段只生成 logical view，不修改 Stage6.3 physical paragraphs，"
        "跨页断词/连字符修复留给 Stage6.5。"
    )
    print("=" * 96)



# =============================================================================
# Stage 6.6 Normalized Text Flow Output
# =============================================================================

def stage66_text_sha256(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


def stage66_document_structure(
    reading_page: dict[str, Any],
) -> dict[str, Any]:
    value = reading_page.get(
        "document_structure",
        {},
    )

    if not isinstance(
        value,
        dict,
    ):
        return {}

    return value


def stage66_section_title(
    structure: dict[str, Any],
) -> str | None:
    # 兼容不同 Stage3/Stage4 schema 命名，不修改其内容。
    for key in (
        "section_title",
        "title",
        "canonical_title",
        "section_name",
    ):
        value = structure.get(
            key
        )

        if isinstance(
            value,
            str,
        ) and value.strip():
            return value.strip()

    return None


def stage66_section_key(
    structure: dict[str, Any],
    page_number: int,
) -> str:
    section_id = structure.get(
        "section_id"
    )

    if (
        isinstance(
            section_id,
            str,
        )
        and section_id.strip()
    ):
        return (
            "section:"
            + section_id.strip()
        )

    # 缺 section 时不静默丢页。
    return (
        f"unassigned:p{page_number:04d}"
    )


def stage66_logical_paragraph_maps(
    cross_page_result: dict[str, Any],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    logical_by_id: dict[
        str,
        dict[str, Any]
    ] = {}

    source_to_logical: dict[
        str,
        str
    ] = {}

    for logical in cross_page_result.get(
        "logical_paragraphs",
        [],
    ):
        if not isinstance(
            logical,
            dict,
        ):
            continue

        logical_id = str(
            logical.get(
                "logical_paragraph_id"
            )
            or ""
        )

        if not logical_id:
            continue

        logical_by_id[
            logical_id
        ] = logical

        for paragraph_id in logical.get(
            "source_paragraph_ids",
            [],
        ):
            paragraph_id = str(
                paragraph_id
            )

            if not paragraph_id:
                continue

            # duplicate mapping 留给 integrity audit 检出；
            # 这里不覆盖第一个映射。
            source_to_logical.setdefault(
                paragraph_id,
                logical_id,
            )

    return (
        logical_by_id,
        source_to_logical,
    )


def stage66_mapping_integrity(
    paragraph_result: dict[str, Any],
    cross_page_result: dict[str, Any],
) -> dict[str, Any]:
    physical_ids: list[str] = []

    for page in paragraph_result.get(
        "pages",
        [],
    ):
        for paragraph in page.get(
            "paragraphs",
            [],
        ):
            paragraph_id = str(
                paragraph.get(
                    "paragraph_id"
                )
                or ""
            )

            if paragraph_id:
                physical_ids.append(
                    paragraph_id
                )

    logical_source_ids: list[str] = []

    for logical in cross_page_result.get(
        "logical_paragraphs",
        [],
    ):
        for paragraph_id in logical.get(
            "source_paragraph_ids",
            [],
        ):
            paragraph_id = str(
                paragraph_id
            )

            if paragraph_id:
                logical_source_ids.append(
                    paragraph_id
                )

    physical_set = set(
        physical_ids
    )
    logical_set = set(
        logical_source_ids
    )

    duplicate_logical_sources = sorted(
        paragraph_id
        for paragraph_id in logical_set
        if logical_source_ids.count(
            paragraph_id
        )
        > 1
    )

    missing_from_logical = sorted(
        physical_set
        - logical_set
    )

    unknown_in_logical = sorted(
        logical_set
        - physical_set
    )

    return {
        "physical_paragraph_count":
            len(
                physical_ids
            ),
        "logical_source_fragment_count":
            len(
                logical_source_ids
            ),
        "unique_physical_paragraph_count":
            len(
                physical_set
            ),
        "unique_logical_source_paragraph_count":
            len(
                logical_set
            ),
        "missing_from_logical":
            missing_from_logical,
        "unknown_in_logical":
            unknown_in_logical,
        "duplicate_logical_sources":
            duplicate_logical_sources,
        "status":
            (
                "pass"
                if (
                    not missing_from_logical
                    and not unknown_in_logical
                    and not duplicate_logical_sources
                    and len(physical_ids)
                    == len(physical_set)
                )
                else "fail"
            ),
    }


def stage66_make_paragraph_record(
    record_id: str,
    logical: dict[str, Any],
    first_page_structure: dict[str, Any],
    first_page_status: str,
    first_page_confidence: str,
) -> dict[str, Any]:
    text = str(
        logical.get(
            "text_with_page_boundaries",
            ""
        )
    )

    fragments = [
        item
        for item in logical.get(
            "fragments",
            [],
        )
        if isinstance(item, dict)
    ]

    first_fragment = (
        fragments[0]
        if fragments
        else {}
    )

    fragment_geometry = [
        {
            "page_number": item.get("page_number"),
            "paragraph_id": item.get("paragraph_id"),
            "bbox": item.get("bbox"),
            "source_reading_orders": item.get("source_reading_orders", []),
            "source_block_ids": item.get("source_block_ids", []),
            "source_word_indices": item.get("source_word_indices", []),
        }
        for item in fragments
    ]

    first_reading_orders = [
        int(value)
        for value in first_fragment.get(
            "source_reading_orders",
            [],
        )
        if isinstance(value, int)
    ]

    return {
        "record_id":
            record_id,
        "record_type":
            "paragraph",
        "logical_paragraph_id":
            logical.get(
                "logical_paragraph_id"
            ),
        "logical_status":
            logical.get(
                "status"
            ),
        "source_pages":
            logical.get(
                "source_pages",
                [],
            ),
        "source_paragraph_ids":
            logical.get(
                "source_paragraph_ids",
                [],
            ),
        "source_fragment_count":
            logical.get(
                "fragment_count",
                0,
            ),
        "section_id":
            first_page_structure.get(
                "section_id"
            ),
        "section_title":
            stage66_section_title(
                first_page_structure
            ),
        "zone_type":
            first_page_structure.get(
                "zone_type"
            ),
        "flow_role":
            logical.get(
                "flow_role"
            ),
        "column_role":
            logical.get(
                "column_role"
            ),
        "source_page_status":
            first_page_status,
        "source_page_confidence":
            first_page_confidence,

        # v0.6.6：保留 logical paragraph 在各物理页上的几何来源。
        # 单页 paragraph 可直接使用 bbox 参与 text/image/table 的统一排序。
        "bbox":
            first_fragment.get(
                "bbox"
            ),
        "source_fragment_geometry":
            fragment_geometry,
        "source_word_indices":
            first_fragment.get(
                "source_word_indices",
                [],
            ),
        "reading_order":
            (
                min(first_reading_orders)
                if first_reading_orders
                else None
            ),
        "effective_visibility":
            "visible",

        # 字符级内容严格来自 Stage6.4 logical text。
        # Stage6.6 不 trim / replace / join / repair。
        "text":
            text,
        "text_sha256":
            stage66_text_sha256(
                text
            ),
        "text_preservation":
            "exact_from_stage64_logical_text",
        "page_boundary_join_mode":
            logical.get(
                "page_boundary_join_mode"
            ),
        "word_break_repair_completed":
            False,
    }


def stage66_make_non_text_record(
    record_id: str,
    page_number: int,
    unit: dict[str, Any],
    structure: dict[str, Any],
    page_status: str,
    page_confidence: str,
) -> dict[str, Any]:
    unit_type = str(
        unit.get(
            "unit_type"
        )
        or "object"
    )

    return {
        "record_id":
            record_id,
        "record_type":
            f"{unit_type}_ref",
        "source_page":
            page_number,
        "section_id":
            structure.get(
                "section_id"
            ),
        "section_title":
            stage66_section_title(
                structure
            ),
        "zone_type":
            structure.get(
                "zone_type"
            ),
        "source_page_status":
            page_status,
        "source_page_confidence":
            page_confidence,
        "block_id":
            unit.get(
                "block_id"
            ),
        "source_block_id":
            unit.get(
                "source_block_id"
            ),
        "source_table_index":
            unit.get(
                "source_table_index"
            ),
        "reading_order":
            unit.get(
                "reading_order"
            ),
        "flow_order":
            unit.get(
                "flow_order"
            ),
        "flow_role":
            unit.get(
                "flow_role"
            ),
        "column_role":
            unit.get(
                "column_role"
            ),
        "bbox":
            unit.get(
                "bbox"
            ),

        # Stage6.6 不尝试自己恢复 table/image/vector 内容。
        # table 的结构化恢复仍由 Stage5 负责。
        "content_status":
            "reference_only_no_text_synthesis",
    }


def build_normalized_text_flow_result(
    reading_result: dict[str, Any],
    paragraph_result: dict[str, Any],
    cross_page_result: dict[str, Any],
) -> dict[str, Any]:
    reading_pages = {
        int(page["page_number"]):
            page
        for page in reading_result.get(
            "pages",
            [],
        )
        if isinstance(
            page,
            dict,
        )
    }

    paragraph_pages = {
        int(page["page_number"]):
            page
        for page in paragraph_result.get(
            "pages",
            [],
        )
        if isinstance(
            page,
            dict,
        )
    }

    (
        logical_by_id,
        source_to_logical,
    ) = stage66_logical_paragraph_maps(
        cross_page_result
    )

    integrity = stage66_mapping_integrity(
        paragraph_result,
        cross_page_result,
    )

    records: list[
        dict[str, Any]
    ] = []

    emitted_logical_ids: set[
        str
    ] = set()

    page_index: list[
        dict[str, Any]
    ] = []

    section_order: list[str] = []
    sections_by_key: dict[
        str,
        dict[str, Any]
    ] = {}

    partial_source_pages: list[int] = []
    non_text_ref_count = 0

    for page_number in sorted(
        paragraph_pages
    ):
        page = paragraph_pages[
            page_number
        ]

        reading_page = reading_pages.get(
            page_number,
            {},
        )

        structure = stage66_document_structure(
            reading_page
        )

        section_key = stage66_section_key(
            structure,
            page_number,
        )

        if section_key not in sections_by_key:
            section_order.append(
                section_key
            )

            sections_by_key[
                section_key
            ] = {
                "section_key":
                    section_key,
                "section_id":
                    structure.get(
                        "section_id"
                    ),
                "section_title":
                    stage66_section_title(
                        structure
                    ),
                "zone_type":
                    structure.get(
                        "zone_type"
                    ),
                "page_numbers":
                    [],
                "record_ids":
                    [],
            }

        section_entry = sections_by_key[
            section_key
        ]

        section_entry[
            "page_numbers"
        ].append(
            page_number
        )

        page_status = str(
            page.get(
                "status",
                "unknown",
            )
        )

        page_confidence = str(
            page.get(
                "confidence",
                "unknown",
            )
        )

        if page_status != "completed":
            partial_source_pages.append(
                page_number
            )

        starts: list[str] = []
        continues: list[str] = []
        page_non_text_refs: list[str] = []

        # 哪些 logical paragraph 在本页有 fragment，但不是在本页开始。
        for logical_id, logical in logical_by_id.items():
            source_pages = [
                int(value)
                for value in logical.get(
                    "source_pages",
                    [],
                )
            ]

            if (
                page_number in source_pages
                and source_pages
                and source_pages[0]
                != page_number
            ):
                continues.append(
                    logical_id
                )

        for unit in page.get(
            "flow_units",
            [],
        ):
            if not isinstance(
                unit,
                dict,
            ):
                continue

            if (
                unit.get(
                    "unit_type"
                )
                == "paragraph"
            ):
                paragraph_id = str(
                    unit.get(
                        "paragraph_id"
                    )
                    or ""
                )

                logical_id = source_to_logical.get(
                    paragraph_id
                )

                if not logical_id:
                    # 不静默制造新文本；
                    # integrity 会把这种情况标 fail。
                    continue

                if logical_id in emitted_logical_ids:
                    continue

                logical = logical_by_id.get(
                    logical_id
                )

                if logical is None:
                    continue

                record_id = (
                    f"ntf{len(records) + 1:06d}"
                )

                record = stage66_make_paragraph_record(
                    record_id,
                    logical,
                    structure,
                    page_status,
                    page_confidence,
                )

                records.append(
                    record
                )

                emitted_logical_ids.add(
                    logical_id
                )

                starts.append(
                    logical_id
                )

                section_entry[
                    "record_ids"
                ].append(
                    record_id
                )

                continue

            record_id = (
                f"ntf{len(records) + 1:06d}"
            )

            record = stage66_make_non_text_record(
                record_id,
                page_number,
                unit,
                structure,
                page_status,
                page_confidence,
            )

            records.append(
                record
            )

            non_text_ref_count += 1

            page_non_text_refs.append(
                record_id
            )

            section_entry[
                "record_ids"
            ].append(
                record_id
            )

        page_index.append(
            {
                "page_number":
                    page_number,
                "status":
                    page_status,
                "confidence":
                    page_confidence,
                "section_id":
                    structure.get(
                        "section_id"
                    ),
                "section_title":
                    stage66_section_title(
                        structure
                    ),
                "zone_type":
                    structure.get(
                        "zone_type"
                    ),
                "logical_paragraphs_started":
                    starts,
                "logical_paragraphs_continued_from_previous_page":
                    sorted(
                        set(
                            continues
                        )
                    ),
                "non_text_record_ids":
                    page_non_text_refs,
            }
        )

    # logical paragraph 理论上都应通过 physical flow 被 emit。
    missing_logical_records = sorted(
        set(
            logical_by_id
        )
        - emitted_logical_ids
    )

    sections = [
        sections_by_key[
            key
        ]
        for key in section_order
    ]

    status = (
        "completed"
        if (
            integrity.get(
                "status"
            )
            == "pass"
            and not missing_logical_records
        )
        else "partial"
    )

    return {
        "stage":
            "6.6",
        "version":
            STAGE66_VERSION,
        "pipeline_version":
            PIPELINE_VERSION,
        "source_file":
            paragraph_result.get(
                "source_file"
            ),
        "page_count":
            paragraph_result.get(
                "page_count"
            ),
        "status":
            status,

        # Stage1~6 的最终 native 机器结果；后续仍需 Quality Gate，故不是最终 LLM Document。
        "artifact_role":
            "native_parser_final_flow",
        "final_llm_document":
            False,

        "source_stage_versions": {
            "stage_6_1":
                STAGE61_VERSION,
            "stage_6_2":
                STAGE62_VERSION,
            "stage_6_3":
                STAGE63_VERSION,
            "stage_6_4":
                STAGE64_VERSION,
            "stage_6_5":
                STAGE65_STATUS,
        },

        "text_policy": {
            "character_level_content_repair":
                False,
            "confirmed_noise_character_exclusion":
                True,
            "word_break_repair":
                False,
            "semantic_rewrite":
                False,
            "ocr":
                False,
            "quality_gate":
                False,
            "cross_page_newline":
                "preserved_from_stage_6_4",
        },

        "mapping_integrity":
            integrity,
        "missing_logical_records":
            missing_logical_records,

        "logical_paragraph_count":
            len(
                logical_by_id
            ),
        "emitted_logical_paragraph_count":
            len(
                emitted_logical_ids
            ),
        "record_count":
            len(
                records
            ),
        "non_text_reference_count":
            non_text_ref_count,
        "partial_source_pages":
            sorted(
                set(
                    partial_source_pages
                )
            ),

        "sections":
            sections,
        "page_index":
            page_index,
        "records":
            records,

        "stage_status": {
            "algorithm_baseline":
                STAGE66_VERSION,
            "sealed":
                False,
            "scope":
                "native_final_flow_before_quality_gate",
            "text_mutation":
                "confirmed_noise_exclusion_only",
            "non_text_policy":
                "table_materialized_image_vector_reference_only",
            "stage5_table_recovery":
                "materialized_in_stage_6_6",
            "readable_renderer_policy":
                "pure_view_no_repair",
            "next_stage":
                "stage_7_native_evidence_manifest",
        },
    }



# =============================================================================
# Stage 6.6 — Stage5 table materialization + final native flow
# =============================================================================
#
# 这一组函数把原 render_readable_md.py 中会改变“最终内容”的逻辑收回 Stage6.6：
# - Stage5 physical/logical table 物化；
# - 跨页 logical row 按 start_page 放置；
# - Stage6.1 已确认 auto_remove occurrence 在 source cell 上的表格噪声清理；
# - paragraph 已表达 table 的最终去重决策。
#
# readable_final.md 后面只读取 normalized_text_flow.json，不再读取 Stage5 / snapshot / noise。
# =============================================================================

STAGE66_TABLE_PARAGRAPH_MATCH_MIN_COVERAGE = 0.80


def stage66_stage5_page_map(
    stage5: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}

    for page in stage5.get("pages", []):
        if not isinstance(page, dict):
            continue

        try:
            page_number = int(page["page_number"])
        except (KeyError, TypeError, ValueError):
            continue

        result[page_number] = page

    return result


def stage66_stage5_tables(
    page: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        item
        for item in page.get("items", [])
        if isinstance(item, dict)
        and item.get("type") == "table"
    ]


def stage66_stage5_owned_word_indices(
    stage5: dict[str, Any],
) -> dict[int, set[int]]:
    """
    收集 Stage5 已明确吸收进 table cell 的 Stage1 word ownership。

    当前只使用 Stage5 v0.3.9+ 的 table bottom overflow recovery 证据。
    不做文本相似度、不按页码/字符串特判。
    """
    result: dict[int, set[int]] = defaultdict(set)

    for recovery in stage5.get(
        "table_boundary_overflow_recoveries",
        [],
    ):
        if not isinstance(recovery, dict):
            continue

        try:
            page_number = int(recovery.get("page_number"))
        except (TypeError, ValueError):
            continue

        for value in recovery.get("source_word_indices", []):
            if isinstance(value, int) and value >= 0:
                result[page_number].add(value)

    # Stage5 v0.4.0+：无线框表格 candidate 的 native words 也具有明确 ownership。
    for page in stage5.get("pages", []):
        if not isinstance(page, dict):
            continue
        try:
            page_number = int(page.get("page_number"))
        except (TypeError, ValueError):
            continue

        for item in page.get("items", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") != "table":
                continue
            if item.get("table_origin") != "stage4_gridless_table_candidate":
                continue
            for value in item.get("source_word_indices", []):
                if isinstance(value, int) and value >= 0:
                    result[page_number].add(value)

    return result




def stage66_materialized_table_owned_word_indices(
    normalized: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> dict[int, set[int]]:
    """
    为“最终确实可见且已经物化”的 native table 建立 raw-word ownership。

    这不是按 table bbox 把所有 word 粗暴吞掉：
    1. 只接受 effective_visibility=visible 且 materialized 的 table_ref；
    2. raw word 的几何中心必须落在对应 Stage1 table candidate 内；
    3. 若 raw word 与 Stage6.1 已确认 noise occurrence 重叠，先仅从该 word 的
       文本副本中移除这些已确认 noise token；
    4. 去噪后的有效文本必须已经由最终 table_text 表达，纯噪声 word 则允许
       由“table + confirmed noise”共同解释；
    5. 不修改 Stage1 word，不按 case/page/固定字符串判断。

    用途：解决 PDF 把“正文片段 + 斜向水印字符”合并进同一个 raw word 时，
    table 已正确物化正文，但 paragraph 仍残留一个去水印后的短片段的问题。
    """
    result: dict[int, set[int]] = defaultdict(set)

    records = normalized.get("records", [])
    if not isinstance(records, list):
        return {}

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "table_ref":
            continue
        if str(record.get("effective_visibility") or "") != "visible":
            continue

        materialization = str(record.get("materialization_status") or "")
        if materialization not in {"materialized", "materialized_empty"}:
            continue

        table_text = str(record.get("table_text") or "")
        table_norm = stage63_layout_match_text(table_text)

        try:
            page_number = int(record.get("source_page"))
            table_index = int(record.get("source_table_index"))
        except (TypeError, ValueError):
            continue

        raw_page = snapshot_pages.get(page_number)
        if not isinstance(raw_page, dict):
            continue

        table_bbox = stage66_raw_table_bbox(
            snapshot_pages,
            page_number,
            table_index,
        )
        if table_bbox is None:
            continue

        raw_words = raw_page.get("words", [])
        if not isinstance(raw_words, list):
            continue

        page_noise = noise_by_page.get(page_number, [])

        for word_index, word in enumerate(raw_words):
            if not isinstance(word, dict):
                continue

            word_bbox = normalize_bbox(word)
            if word_bbox is None:
                continue

            center_x, center_y = bbox_center(word_bbox)
            if not point_inside_bbox(
                center_x,
                center_y,
                table_bbox,
                tolerance=0.0,
            ):
                continue

            raw_text = str(word.get("text") or "")
            if not raw_text:
                continue

            cleaned_text = raw_text
            overlapped_confirmed_noise = False

            for occurrence in page_noise:
                if not isinstance(occurrence, dict):
                    continue

                occurrence_bbox = normalize_bbox(occurrence.get("bbox"))
                token = str(occurrence.get("text") or "")

                if occurrence_bbox is None or not token:
                    continue

                if stage66_bbox_intersection_area(
                    word_bbox,
                    occurrence_bbox,
                ) <= 0:
                    continue

                cleaned_text, removed = stage66_remove_one_token(
                    cleaned_text,
                    token,
                )

                if removed:
                    overlapped_confirmed_noise = True

            cleaned_norm = stage63_layout_match_text(cleaned_text)

            # 纯噪声 word：由 confirmed noise + table geometry 解释。
            if not cleaned_norm and overlapped_confirmed_noise:
                result[page_number].add(word_index)
                continue

            if not cleaned_norm or not table_norm:
                continue

            represented = cleaned_norm in table_norm

            # 较长片段允许极保守的顺序覆盖兜底，避免 cell 内机械换行差异。
            if not represented and len(cleaned_norm) >= 4:
                represented = (
                    stage63_sequence_match_coverage(
                        cleaned_text,
                        table_text,
                    )
                    >= 0.95
                )

            if represented:
                result[page_number].add(word_index)

    return dict(result)

def stage66_paragraph_fully_owned_by_stage5(
    record: dict[str, Any],
    owned_by_page: dict[int, set[int]],
) -> tuple[bool, dict[str, Any]]:
    """
    仅当 paragraph 的所有带 provenance 的 physical fragments 都被
    Stage5 table ownership 完整覆盖时才允许 suppression。

    partial overlap 一律不改文本，避免误删。
    """
    fragments = record.get("source_fragment_geometry", [])

    if not isinstance(fragments, list) or not fragments:
        return False, {}

    evidence: list[dict[str, Any]] = []
    saw_owned_words = False

    for fragment in fragments:
        if not isinstance(fragment, dict):
            return False, {}

        try:
            page_number = int(fragment.get("page_number"))
        except (TypeError, ValueError):
            return False, {}

        indices = [
            value
            for value in fragment.get("source_word_indices", [])
            if isinstance(value, int) and value >= 0
        ]

        if not indices:
            return False, {}

        owned = owned_by_page.get(page_number, set())
        covered = set(indices).issubset(owned)

        evidence.append(
            {
                "page_number": page_number,
                "source_word_indices": indices,
                "owned_word_count": sum(
                    1 for value in indices if value in owned
                ),
                "fully_covered": covered,
            }
        )

        if not covered:
            return False, {"fragments": evidence}

        saw_owned_words = True

    return saw_owned_words, {"fragments": evidence}



def stage66_suppress_confirmed_noise_table_residuals(
    normalized: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> int:
    """
    抑制一种非常窄、但通用的残余重复：

    PDF 可能把“真实表格正文片段 + 旋转水印字符”合并进同一个 Stage1 raw word。
    Stage6.3 能依据 confirmed watermark char geometry 把水印字符从 paragraph 文本中排除，
    但 raw-word bbox 仍可能被水印拉得很大，从而使常规 table word ownership 因几何中心偏移而漏命中。

    这里不按短文本、不按页码、不按固定字符删除。只有同时满足以下条件才 suppress：
    1. paragraph 是单页、仍 visible，且有明确 source_word_indices；
    2. 至少一个 source raw word 确实被 Stage6.1 confirmed noise occurrence 删除过 token；
    3. 所有 source raw words 去除 confirmed noise 后拼接出的文本，与 paragraph 文本精确一致（仅忽略空白）；
    4. 同页存在 visible + materialized 的 table，paragraph 文本已经完整存在于 table_text；
    5. source raw words 与该 table bbox 有实际几何交集。

    这样只消除“已被表格表达的去水印残片”，不会把 table extraction 未覆盖的 native 事实静默删除。
    """
    tables_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for record in normalized.get("records", []):
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "table_ref":
            continue
        if str(record.get("effective_visibility") or "") != "visible":
            continue
        if str(record.get("materialization_status") or "") not in {
            "materialized",
            "materialized_empty",
        }:
            continue
        if not str(record.get("table_text") or "").strip():
            continue
        try:
            page_number = int(record.get("source_page"))
        except (TypeError, ValueError):
            continue
        tables_by_page[page_number].append(record)

    suppressed = 0

    for record in normalized.get("records", []):
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "paragraph":
            continue
        if str(record.get("effective_visibility") or "visible") != "visible":
            continue

        source_pages = [
            int(value)
            for value in record.get("source_pages", [])
            if isinstance(value, int)
        ]
        if len(source_pages) != 1:
            continue

        page_number = source_pages[0]
        page_tables = tables_by_page.get(page_number, [])
        if not page_tables:
            continue

        paragraph_text = str(record.get("text") or "")
        paragraph_norm = stage63_layout_match_text(paragraph_text)
        if not paragraph_norm:
            continue

        fragments = record.get("source_fragment_geometry", [])
        if not isinstance(fragments, list) or not fragments:
            continue

        indices: list[int] = []
        for fragment in fragments:
            if not isinstance(fragment, dict):
                indices = []
                break
            try:
                fragment_page = int(fragment.get("page_number"))
            except (TypeError, ValueError):
                indices = []
                break
            if fragment_page != page_number:
                indices = []
                break
            values = [
                value
                for value in fragment.get("source_word_indices", [])
                if isinstance(value, int) and value >= 0
            ]
            if not values:
                indices = []
                break
            indices.extend(values)

        if not indices:
            # 兼容旧 record：单页 paragraph 顶层可能仍保留 provenance。
            indices = [
                value
                for value in record.get("source_word_indices", [])
                if isinstance(value, int) and value >= 0
            ]

        if not indices:
            continue

        # 去重但保留原 provenance 顺序。
        ordered_indices: list[int] = []
        seen_indices: set[int] = set()
        for value in indices:
            if value in seen_indices:
                continue
            seen_indices.add(value)
            ordered_indices.append(value)

        raw_page = snapshot_pages.get(page_number)
        if not isinstance(raw_page, dict):
            continue
        raw_words = raw_page.get("words", [])
        if not isinstance(raw_words, list):
            continue

        cleaned_parts: list[str] = []
        word_bboxes: list[dict[str, float]] = []
        removed_noise_evidence: list[dict[str, Any]] = []
        provenance_valid = True

        for word_index in ordered_indices:
            if not (0 <= word_index < len(raw_words)):
                provenance_valid = False
                break
            word = raw_words[word_index]
            if not isinstance(word, dict):
                provenance_valid = False
                break

            word_bbox = normalize_bbox(word)
            if word_bbox is None:
                provenance_valid = False
                break
            word_bboxes.append(word_bbox)

            cleaned_text = str(word.get("text") or "")
            removed_for_word: list[str] = []

            for occurrence in noise_by_page.get(page_number, []):
                if not isinstance(occurrence, dict):
                    continue
                occurrence_bbox = normalize_bbox(occurrence.get("bbox"))
                token = str(occurrence.get("text") or "")
                if occurrence_bbox is None or not token:
                    continue
                if stage66_bbox_intersection_area(word_bbox, occurrence_bbox) <= 0:
                    continue

                cleaned_text, removed = stage66_remove_one_token(
                    cleaned_text,
                    token,
                )
                if removed:
                    removed_for_word.append(token)

            if removed_for_word:
                removed_noise_evidence.append(
                    {
                        "source_word_index": word_index,
                        "removed_tokens": removed_for_word,
                    }
                )

            cleaned_parts.append(cleaned_text)

        if not provenance_valid or not removed_noise_evidence:
            continue

        cleaned_norm = stage63_layout_match_text("".join(cleaned_parts))
        if cleaned_norm != paragraph_norm:
            continue

        matched_table: dict[str, Any] | None = None

        for table in page_tables:
            table_text = str(table.get("table_text") or "")
            table_norm = stage63_layout_match_text(table_text)
            if paragraph_norm not in table_norm:
                continue

            table_bbox = normalize_bbox(table.get("bbox"))
            if table_bbox is None:
                try:
                    table_index = int(table.get("source_table_index"))
                except (TypeError, ValueError):
                    table_index = -1
                if table_index >= 0:
                    table_bbox = stage66_raw_table_bbox(
                        snapshot_pages,
                        page_number,
                        table_index,
                    )

            if table_bbox is None:
                continue

            if not all(
                stage66_bbox_intersection_area(word_bbox, table_bbox) > 0
                for word_bbox in word_bboxes
            ):
                continue

            matched_table = table
            break

        if matched_table is None:
            continue

        record["effective_visibility"] = (
            "suppressed_confirmed_noise_table_residual"
        )
        record["suppression_reason"] = (
            "confirmed_noise_stripped_source_words_exactly_match_paragraph_and_are_already_represented_by_materialized_table"
        )
        record["suppression_evidence"] = {
            "source_page": page_number,
            "source_word_indices": ordered_indices,
            "removed_confirmed_noise": removed_noise_evidence,
            "materialized_table_record_id": matched_table.get("record_id"),
            "source_table_index": matched_table.get("source_table_index"),
            "paragraph_text_match": "exact_after_whitespace_normalization",
            "table_text_contains_paragraph": True,
            "source_words_intersect_table": True,
        }
        suppressed += 1

    return suppressed

def stage66_raw_table(
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
    table_index: int,
) -> dict[str, Any] | None:
    page = snapshot_pages.get(page_number)

    if not isinstance(page, dict):
        return None

    for table in page.get("table_candidates", []):
        if not isinstance(table, dict):
            continue

        try:
            current_index = int(table.get("table_index", -1))
        except (TypeError, ValueError):
            continue

        if current_index == int(table_index):
            return table

    return None


def stage66_raw_table_bbox(
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
    table_index: int,
) -> dict[str, float] | None:
    table = stage66_raw_table(
        snapshot_pages,
        page_number,
        table_index,
    )

    if not isinstance(table, dict):
        return None

    direct = normalize_bbox(table.get("bbox"))
    if direct is not None:
        return direct

    cells: list[dict[str, float]] = []

    for row in table.get("rows", []):
        if not isinstance(row, dict):
            continue

        for cell in row.get("cells", []):
            bbox = normalize_bbox(cell) if isinstance(cell, dict) else None
            if bbox is not None:
                cells.append(bbox)

    return bbox_union(cells)


def stage66_bbox_overlap_over_smaller(
    a: dict[str, float],
    b: dict[str, float],
) -> float:
    x0 = max(a["x0"], b["x0"])
    top = max(a["top"], b["top"])
    x1 = min(a["x1"], b["x1"])
    bottom = min(a["bottom"], b["bottom"])

    if x1 <= x0 or bottom <= top:
        return 0.0

    intersection = (x1 - x0) * (bottom - top)
    area_a = max(0.0, (a["x1"] - a["x0"]) * (a["bottom"] - a["top"]))
    area_b = max(0.0, (b["x1"] - b["x0"]) * (b["bottom"] - b["top"]))
    denominator = min(area_a, area_b)

    return intersection / denominator if denominator > 0 else 0.0


def stage66_resolve_table_ref_index(
    record: dict[str, Any],
    physical_tables: list[dict[str, Any]],
    consumed: set[int],
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
) -> int | None:
    available: dict[int, dict[str, Any]] = {}

    for item in physical_tables:
        try:
            table_index = int(item.get("table_index"))
        except (TypeError, ValueError):
            continue

        if table_index in consumed:
            continue

        available[table_index] = item

    explicit = record.get("source_table_index")

    try:
        explicit_index = int(explicit)
    except (TypeError, ValueError):
        explicit_index = None

    if explicit_index is not None and explicit_index in available:
        return explicit_index

    ref_bbox = normalize_bbox(record.get("bbox"))

    if ref_bbox is not None:
        scored: list[tuple[float, int]] = []

        for table_index in available:
            table_bbox = stage66_raw_table_bbox(
                snapshot_pages,
                page_number,
                table_index,
            )

            if table_bbox is None:
                continue

            score = stage66_bbox_overlap_over_smaller(
                ref_bbox,
                table_bbox,
            )

            if score > 0:
                scored.append((score, table_index))

        if scored:
            scored.sort(reverse=True)
            if scored[0][0] >= 0.60:
                return scored[0][1]

    return next(iter(available), None)


def stage66_raw_row_cell_bboxes(
    snapshot_pages: dict[int, dict[str, Any]],
    page_number: int,
    table_index: int,
    row_index: int,
) -> list[dict[str, float] | None]:
    table = stage66_raw_table(
        snapshot_pages,
        page_number,
        table_index,
    )

    if not isinstance(table, dict):
        return []

    rows = table.get("rows", [])

    if not isinstance(rows, list) or not (0 <= row_index < len(rows)):
        return []

    row = rows[row_index]

    if not isinstance(row, dict):
        return []

    result: list[dict[str, float] | None] = []

    for cell in row.get("cells", []):
        result.append(
            normalize_bbox(cell)
            if isinstance(cell, dict)
            else None
        )

    return result


def stage66_locate_noise_occurrence_source_cell(
    occurrence_bbox: dict[str, float],
    cell_bboxes: list[dict[str, float] | None],
) -> int | None:
    center_x, center_y = bbox_center(occurrence_bbox)
    exact: list[int] = []

    for index, cell_bbox in enumerate(cell_bboxes):
        if cell_bbox is None:
            continue

        if point_inside_bbox(
            center_x,
            center_y,
            cell_bbox,
            tolerance=0.0,
        ):
            exact.append(index)

    if len(exact) == 1:
        return exact[0]

    candidates = exact

    if not candidates:
        candidates = []

        for index, cell_bbox in enumerate(cell_bboxes):
            if cell_bbox is None:
                continue

            if point_inside_bbox(
                center_x,
                center_y,
                cell_bbox,
                tolerance=0.25,
            ):
                candidates.append(index)

    if not candidates:
        return None

    def distance_to_cell_center(index: int) -> float:
        cell_bbox = cell_bboxes[index]
        assert cell_bbox is not None
        cx, cy = bbox_center(cell_bbox)
        return (cx - center_x) ** 2 + (cy - center_y) ** 2

    return min(candidates, key=distance_to_cell_center)


def stage66_removable_noise_occurrences(
    noise_result: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for candidate in noise_result.get("noise_candidates", []):
        if not isinstance(candidate, dict):
            continue

        if candidate.get("action") != "auto_remove":
            continue

        for occurrence in candidate.get("occurrences", []):
            if not isinstance(occurrence, dict):
                continue

            page_number = occurrence.get("page_number")
            bbox = normalize_bbox(occurrence.get("bbox"))
            token = clean_text(
                occurrence.get("text")
                or candidate.get("text")
            )

            if not isinstance(page_number, int) or bbox is None or not token:
                continue

            result[page_number].append(
                {
                    "text": token,
                    "bbox": bbox,
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_type": candidate.get("type"),
                }
            )

    return dict(result)


def stage66_removable_tokens_by_output_column(
    row_source: dict[str, Any] | None,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> dict[int, list[str]]:
    result: dict[int, list[str]] = defaultdict(list)

    if not isinstance(row_source, dict):
        return {}

    # Stage5 v0.4.0+ 无线框表格：直接使用每个 cell 的 native word ownership
    # 将 Stage6.1 已确认的 noise occurrence 映射回输出列。
    direct_cells = row_source.get("direct_cell_source_word_indices")
    if isinstance(direct_cells, list):
        try:
            direct_page = int(row_source.get("start_page"))
        except (TypeError, ValueError):
            direct_page = -1

        raw_page = snapshot_pages.get(direct_page, {})
        raw_words = raw_page.get("words", []) if isinstance(raw_page, dict) else []

        for col_index, raw_indices in enumerate(direct_cells):
            if not isinstance(raw_indices, list):
                continue

            word_bboxes: list[dict[str, float]] = []
            for value in raw_indices:
                if not isinstance(value, int) or not (0 <= value < len(raw_words)):
                    continue
                bbox = normalize_bbox(raw_words[value])
                if bbox is not None:
                    word_bboxes.append(bbox)

            if not word_bboxes:
                continue

            for occurrence in noise_by_page.get(direct_page, []):
                occurrence_bbox = normalize_bbox(occurrence.get("bbox"))
                if occurrence_bbox is None:
                    continue

                matched = False
                for word_bbox_value in word_bboxes:
                    x0 = max(occurrence_bbox["x0"], word_bbox_value["x0"])
                    y0 = max(occurrence_bbox["top"], word_bbox_value["top"])
                    x1 = min(occurrence_bbox["x1"], word_bbox_value["x1"])
                    y1 = min(occurrence_bbox["bottom"], word_bbox_value["bottom"])
                    if x1 > x0 and y1 > y0:
                        matched = True
                        break

                if matched:
                    token = str(occurrence.get("text") or "")
                    if token:
                        result[col_index].append(token)

        if result:
            return dict(result)

    source_map: dict[tuple[int, int, int, int], int] = {}

    for mapping in row_source.get("source_cell_mappings", []):
        if not isinstance(mapping, dict):
            continue

        try:
            key = (
                int(mapping["page_number"]),
                int(mapping["table_index"]),
                int(mapping["row_index"]),
                int(mapping["cell_index"]),
            )
            source_map[key] = int(mapping["logical_column_index"])
        except (KeyError, TypeError, ValueError):
            continue

    fragments = row_source.get("source_fragments", [])

    if not isinstance(fragments, list):
        return {}

    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue

        try:
            page_number = int(fragment["page_number"])
            table_index = int(fragment["table_index"])
            row_index = int(fragment["row_index"])
        except (KeyError, TypeError, ValueError):
            continue

        cell_bboxes = stage66_raw_row_cell_bboxes(
            snapshot_pages,
            page_number,
            table_index,
            row_index,
        )

        for occurrence in noise_by_page.get(page_number, []):
            source_col = stage66_locate_noise_occurrence_source_cell(
                occurrence["bbox"],
                cell_bboxes,
            )

            if source_col is None:
                continue

            if row_source.get("merged"):
                output_col = source_map.get(
                    (
                        page_number,
                        table_index,
                        row_index,
                        source_col,
                    )
                )

                if output_col is None:
                    # merged row 不猜测 logical column。
                    continue
            else:
                output_col = source_col

            result[output_col].append(occurrence["text"])

    return dict(result)


def stage66_remove_one_token(
    value: str,
    token: str,
) -> tuple[str, bool]:
    if not value or not token:
        return value, False

    index = value.find(token)

    if index < 0:
        return value, False

    return (
        value[:index] + value[index + len(token):],
        True,
    )


def stage66_clean_table_row_noise(
    row: list[Any],
    row_source: dict[str, Any] | None,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[list[str], int]:
    cells = [
        "" if cell is None else str(cell)
        for cell in row
    ]

    tokens_by_col = stage66_removable_tokens_by_output_column(
        row_source,
        snapshot_pages,
        noise_by_page,
    )

    removed_count = 0

    for col_index, tokens in tokens_by_col.items():
        if not (0 <= col_index < len(cells)):
            continue

        for token in tokens:
            cells[col_index], removed = stage66_remove_one_token(
                cells[col_index],
                token,
            )

            if removed:
                removed_count += 1

    return cells, removed_count


def stage66_normalize_cell_display(value: Any) -> str:
    """
    把 cell 内的物理折行恢复成单行展示。

    不改字、不猜词；只避免机械折行制造新的空格：
    - 中文↔中文、中文↔数字/字母：不加空格；
    - 数字↔数字：不加空格（手机号/日期/编号常见）；
    - 英文字母↔英文字母：保留一个空格，避免英文单词粘连；
    - 行尾连字符：直接续接。
    """
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = [
        part.strip()
        for part in text.split("\n")
        if part.strip()
    ]

    if not parts:
        return ""

    def is_cjk(char: str) -> bool:
        if not char:
            return False
        code = ord(char)
        return (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
        )

    current = parts[0]

    for part in parts[1:]:
        previous = current[-1] if current else ""
        next_char = part[0] if part else ""

        if previous in "-‐‑‒–—":
            separator = ""
        elif previous.isdigit() and next_char.isdigit():
            separator = ""
        elif is_cjk(previous) or is_cjk(next_char):
            separator = ""
        elif previous.isascii() and previous.isalpha() and next_char.isascii() and next_char.isalpha():
            separator = " "
        else:
            separator = ""

        current += separator + part

    return current


def stage66_materialize_rows(
    rows: list[list[Any]],
    row_sources: list[dict[str, Any] | None],
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[list[list[str]], str, int]:
    final_rows: list[list[str]] = []
    lines: list[str] = []
    removed_count = 0

    for index, row in enumerate(rows):
        source = row_sources[index] if index < len(row_sources) else None

        cleaned, current_removed = stage66_clean_table_row_noise(
            row,
            source,
            snapshot_pages,
            noise_by_page,
        )

        removed_count += current_removed

        cells = [
            stage66_normalize_cell_display(cell)
            for cell in cleaned
        ]

        # v0.3.0：不再删除行尾空 cell。
        # 尾部空 cell 可能对应真实列（例如“签名”列），删除会破坏后续矩阵表列对齐。
        if not any(cells):
            continue

        final_rows.append(cells)
        lines.append("\t".join(cells))

    return final_rows, "\n".join(lines), removed_count


def stage66_logical_table_by_fragment(
    stage5: dict[str, Any],
) -> dict[tuple[int, int], dict[str, Any]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}

    for table in stage5.get("cross_page_logical_tables", []):
        if not isinstance(table, dict):
            continue

        for fragment in table.get("source_fragments", []):
            if not isinstance(fragment, dict):
                continue

            try:
                key = (
                    int(fragment["page_number"]),
                    int(fragment["table_index"]),
                )
            except (KeyError, TypeError, ValueError):
                continue

            result[key] = table

    return result


def stage66_logical_rows_starting_on_page(
    logical_table: dict[str, Any],
    page_number: int,
) -> tuple[list[list[Any]], list[dict[str, Any] | None]]:
    rows = logical_table.get("rows", [])
    row_sources = logical_table.get("row_sources", [])

    if not isinstance(rows, list):
        return [], []

    selected_rows: list[list[Any]] = []
    selected_sources: list[dict[str, Any] | None] = []

    for index, row in enumerate(rows):
        source = (
            row_sources[index]
            if isinstance(row_sources, list)
            and index < len(row_sources)
            else None
        )

        if not isinstance(source, dict):
            continue

        try:
            start_page = int(source.get("start_page"))
        except (TypeError, ValueError):
            continue

        if start_page != page_number:
            continue

        selected_rows.append(
            row if isinstance(row, list) else [row]
        )
        selected_sources.append(source)

    return selected_rows, selected_sources


def stage66_physical_row_sources(
    page_number: int,
    table_index: int,
    row_count: int,
    physical_table: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    direct_cells = (
        physical_table.get("cell_source_word_indices", [])
        if isinstance(physical_table, dict)
        else []
    )

    result: list[dict[str, Any]] = []

    for row_index in range(row_count):
        source: dict[str, Any] = {
            "start_page": page_number,
            "source_fragments": [
                {
                    "page_number": page_number,
                    "table_index": table_index,
                    "row_index": row_index,
                }
            ],
            "merged": False,
        }

        if (
            isinstance(physical_table, dict)
            and physical_table.get("table_origin")
            == "stage4_gridless_table_candidate"
            and isinstance(direct_cells, list)
            and row_index < len(direct_cells)
            and isinstance(direct_cells[row_index], list)
        ):
            source["source_kind"] = "gridless_native_words"
            source["direct_cell_source_word_indices"] = direct_cells[row_index]

        result.append(source)

    return result


def stage66_table_rows_text_features(
    rows: list[Any],
) -> dict[str, Any]:
    row_count = len(rows)
    max_columns = 0
    nonempty: list[str] = []

    for row in rows:
        if not isinstance(row, list):
            continue

        max_columns = max(max_columns, len(row))

        for cell in row:
            value = clean_text(cell)
            if value:
                nonempty.append(value)

    total_chars = sum(
        len(stage63_layout_match_text(value))
        for value in nonempty
    )

    longest_cell_chars = max(
        [
            len(stage63_layout_match_text(value))
            for value in nonempty
        ],
        default=0,
    )

    longest_share = (
        longest_cell_chars / total_chars
        if total_chars > 0
        else 0.0
    )

    return {
        "row_count": row_count,
        "max_columns": max_columns,
        "nonempty_cell_count": len(nonempty),
        "total_chars": total_chars,
        "longest_cell_chars": longest_cell_chars,
        "longest_cell_share": longest_share,
        "text_blob": "\n".join(nonempty),
    }


def stage66_table_already_represented_by_paragraphs(
    rows: list[Any],
    paragraph_texts: list[str],
    zone_type: str,
) -> tuple[bool, dict[str, Any]]:
    features = stage66_table_rows_text_features(rows)

    low_dimensional = (
        features["row_count"] <= LAYOUT_CONTAINER_MAX_ROWS
        and features["max_columns"] <= LAYOUT_CONTAINER_MAX_COLUMNS
        and features["nonempty_cell_count"] <= LAYOUT_CONTAINER_MAX_NONEMPTY_CELLS
    )

    prose_dominant = (
        features["total_chars"] >= LAYOUT_CONTAINER_MIN_TOTAL_CHARS
        and features["longest_cell_chars"] >= LAYOUT_CONTAINER_MIN_LONGEST_CELL_CHARS
        and features["longest_cell_share"] >= LAYOUT_CONTAINER_MIN_LONGEST_SHARE
    )

    one_dimensional = features["max_columns"] <= 1
    zone_support = zone_type in LAYOUT_CONTAINER_SEMIFREE_ZONES
    paragraph_blob = "\n".join(paragraph_texts)

    coverage = stage63_sequence_match_coverage(
        str(features["text_blob"]),
        paragraph_blob,
    )

    long_prose_duplicate = (
        low_dimensional
        and prose_dominant
        and (one_dimensional or zone_support)
        and coverage >= STAGE66_TABLE_PARAGRAPH_MATCH_MIN_COVERAGE
    )

    short_overlap_duplicate = (
        features["row_count"] <= 3
        and features["max_columns"] <= 1
        and features["nonempty_cell_count"] <= 3
        and features["total_chars"] > 0
        and coverage >= 0.98
    )

    duplicate = bool(
        long_prose_duplicate
        or short_overlap_duplicate
    )

    return duplicate, {
        "coverage": round(coverage, 4),
        "long_prose_duplicate": long_prose_duplicate,
        "short_overlap_duplicate": short_overlap_duplicate,
        "features": {
            key: value
            for key, value in features.items()
            if key != "text_blob"
        },
    }



# =============================================================================
# Stage6.6 table display policy / paragraph-table dedupe / page flow order
# =============================================================================

STAGE66_TABLE_MATRIX_MIN_ROWS = 3
STAGE66_TABLE_MATRIX_MIN_DENSE_RATIO = 0.70
STAGE66_TABLE_MATRIX_DENSE_OCCUPANCY = 0.65
STAGE66_TABLE_MATRIX_MAX_COLUMNS = 16
STAGE66_TABLE_HEADER_MIN_OCCUPANCY = 0.65
STAGE66_TABLE_HEADER_MAX_DIGIT_RATIO = 0.16
STAGE66_TABLE_HEADER_MAX_AVG_CELL_CHARS = 18.0
STAGE66_TABLE_HIERARCHY_MIN_SPARSE_LEADING_RATIO = 0.30

STAGE66_TABLE_DUPLICATE_MIN_TEXT_COVERAGE = 0.80
STAGE66_TABLE_DUPLICATE_MIN_GEOMETRY_OVERLAP = 0.10
STAGE66_TABLE_DUPLICATE_MIN_CHARS = 6
STAGE66_TABLE_DUPLICATE_MAX_PARAGRAPH_RUN = 4


def stage66_pad_row(
    row: list[Any],
    width: int,
) -> list[str]:
    values = [
        stage66_normalize_cell_display(value)
        for value in row
    ]

    if len(values) < width:
        values.extend(
            [""] * (width - len(values))
        )

    return values[:width]


def stage66_nonempty_count(
    row: list[Any],
) -> int:
    return sum(
        1
        for value in row
        if stage66_normalize_cell_display(value)
    )


def stage66_digit_ratio(
    values: list[str],
) -> float:
    text = "".join(values)

    if not text:
        return 1.0

    digit_count = sum(
        1
        for char in text
        if char.isdigit()
    )

    return digit_count / len(text)


def stage66_header_like_score(
    row: list[Any],
    width: int,
) -> float:
    if width <= 1:
        return 0.0

    values = stage66_pad_row(
        row,
        width,
    )

    nonempty = [
        value
        for value in values
        if value
    ]

    if len(nonempty) < 2:
        return 0.0

    occupancy = len(nonempty) / width

    if occupancy < STAGE66_TABLE_HEADER_MIN_OCCUPANCY:
        return 0.0

    digit_ratio = stage66_digit_ratio(
        nonempty
    )

    avg_chars = sum(
        len(value)
        for value in nonempty
    ) / len(nonempty)

    if digit_ratio > STAGE66_TABLE_HEADER_MAX_DIGIT_RATIO:
        return 0.0

    if avg_chars > STAGE66_TABLE_HEADER_MAX_AVG_CELL_CHARS:
        return 0.0

    short_ratio = sum(
        1
        for value in nonempty
        if len(value) <= 24
    ) / len(nonempty)

    return (
        0.55 * occupancy
        + 0.25 * (1.0 - min(1.0, digit_ratio / max(STAGE66_TABLE_HEADER_MAX_DIGIT_RATIO, 1e-6)))
        + 0.20 * short_ratio
    )


def stage66_table_display_profile(
    rows: list[list[str]],
) -> dict[str, Any]:
    if not rows:
        return {
            "row_count": 0,
            "max_columns": 0,
            "structural_row_count": 0,
            "dense_row_count": 0,
            "dense_ratio": 0.0,
            "matrix_candidate": False,
            "hierarchy_candidate": False,
        }

    max_columns = max(
        len(row)
        for row in rows
    )

    if max_columns <= 0:
        max_columns = 1

    structural_rows = []
    dense_rows = []
    sparse_leading_rows = 0

    for row in rows:
        padded = stage66_pad_row(
            row,
            max_columns,
        )

        nonempty_indices = [
            index
            for index, value in enumerate(padded)
            if value
        ]

        nonempty_count = len(nonempty_indices)

        if nonempty_count >= 2:
            structural_rows.append(row)

            occupancy = (
                nonempty_count
                / max_columns
            )

            if occupancy >= STAGE66_TABLE_MATRIX_DENSE_OCCUPANCY:
                dense_rows.append(row)

        if (
            max_columns >= 3
            and nonempty_indices
            and nonempty_indices[0] >= 1
        ):
            sparse_leading_rows += 1

    dense_ratio = (
        len(dense_rows)
        / len(structural_rows)
        if structural_rows
        else 0.0
    )

    matrix_candidate = bool(
        2 <= max_columns <= STAGE66_TABLE_MATRIX_MAX_COLUMNS
        and len(dense_rows) >= STAGE66_TABLE_MATRIX_MIN_ROWS
        and dense_ratio >= STAGE66_TABLE_MATRIX_MIN_DENSE_RATIO
    )

    first_header_score = stage66_header_like_score(
        rows[0],
        max_columns,
    )

    hierarchy_candidate = bool(
        3 <= max_columns <= 6
        and len(rows) >= 4
        and first_header_score > 0.0
        and (
            sparse_leading_rows
            / max(1, len(rows) - 1)
        ) >= STAGE66_TABLE_HIERARCHY_MIN_SPARSE_LEADING_RATIO
    )

    return {
        "row_count": len(rows),
        "max_columns": max_columns,
        "structural_row_count": len(structural_rows),
        "dense_row_count": len(dense_rows),
        "dense_ratio": round(dense_ratio, 4),
        "matrix_candidate": matrix_candidate,
        "hierarchy_candidate": hierarchy_candidate,
        "first_header_score": round(first_header_score, 4),
    }


def stage66_find_local_header(
    rows: list[list[str]],
    width: int,
) -> tuple[int | None, list[str] | None, float]:
    # 只在前 4 行寻找表头；前面允许存在“主要研究人员”这类表内标题行。
    best_index: int | None = None
    best_row: list[str] | None = None
    best_score = 0.0

    for index, row in enumerate(rows[:4]):
        score = stage66_header_like_score(
            row,
            width,
        )

        if score > best_score:
            best_index = index
            best_row = stage66_pad_row(
                row,
                width,
            )
            best_score = score

    if best_score < 0.72:
        return None, None, best_score

    return best_index, best_row, best_score


def stage66_find_prior_logical_header(
    logical_table: dict[str, Any] | None,
    page_number: int,
    width: int,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[list[str] | None, float]:
    if not isinstance(logical_table, dict):
        return None, 0.0

    rows = logical_table.get("rows", [])
    row_sources = logical_table.get("row_sources", [])

    if not isinstance(rows, list):
        return None, 0.0

    best_row: list[str] | None = None
    best_score = 0.0
    best_start_page = -1

    for index, row in enumerate(rows):
        if not isinstance(row, list):
            continue

        source = (
            row_sources[index]
            if isinstance(row_sources, list)
            and index < len(row_sources)
            and isinstance(row_sources[index], dict)
            else None
        )

        if not isinstance(source, dict):
            continue

        try:
            start_page = int(source.get("start_page"))
        except (TypeError, ValueError):
            continue

        if start_page >= page_number:
            continue

        cleaned, _ = stage66_clean_table_row_noise(
            row,
            source,
            snapshot_pages,
            noise_by_page,
        )

        values = [
            stage66_normalize_cell_display(value)
            for value in cleaned
        ]

        if len(values) != width:
            continue

        score = stage66_header_like_score(
            values,
            width,
        )

        if score < 0.80:
            continue

        if (
            start_page > best_start_page
            or (
                start_page == best_start_page
                and score > best_score
            )
        ):
            best_start_page = start_page
            best_score = score
            best_row = values

    return best_row, best_score


def stage66_escape_markdown_cell(
    value: str,
) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .strip()
    )


def stage66_render_markdown_table(
    rows: list[list[str]],
    header: list[str],
    local_header_index: int | None,
) -> str:
    width = len(header)

    preamble_rows: list[list[str]] = []
    data_rows: list[list[str]] = []

    if local_header_index is None:
        data_rows = rows
    else:
        preamble_rows = rows[:local_header_index]
        data_rows = rows[local_header_index + 1:]

    lines: list[str] = []

    for row in preamble_rows:
        values = [
            value
            for value in stage66_pad_row(row, width)
            if value
        ]

        if values:
            lines.append(" / ".join(values))
            lines.append("")

    header_cells = [
        stage66_escape_markdown_cell(value or f"列{index + 1}")
        for index, value in enumerate(
            stage66_pad_row(header, width)
        )
    ]

    lines.append(
        "| " + " | ".join(header_cells) + " |"
    )
    lines.append(
        "| " + " | ".join(["---"] * width) + " |"
    )

    for row in data_rows:
        cells = [
            stage66_escape_markdown_cell(value)
            for value in stage66_pad_row(row, width)
        ]

        if not any(cells):
            continue

        lines.append(
            "| " + " | ".join(cells) + " |"
        )

    return "\n".join(lines).strip()


def stage66_render_hierarchical_table(
    rows: list[list[str]],
    initial_context: list[str] | None = None,
) -> str:
    width = max(
        len(row)
        for row in rows
    )

    padded_rows = [
        stage66_pad_row(row, width)
        for row in rows
    ]

    header_index, _, _ = stage66_find_local_header(
        padded_rows,
        width,
    )

    start_index = (
        header_index + 1
        if header_index is not None
        else 0
    )

    context = [""] * max(0, width - 1)

    if isinstance(initial_context, list):
        for index, value in enumerate(
            initial_context[: len(context)]
        ):
            context[index] = stage66_normalize_cell_display(value)

    lines: list[str] = []

    for row in padded_rows[start_index:]:
        if width == 1:
            if row[0]:
                lines.append(row[0])
            continue

        value = row[-1]

        changed_index: int | None = None

        for index in range(width - 1):
            cell = row[index]

            if not cell:
                continue

            context[index] = cell
            changed_index = index

            # 上级发生变化后，旧的下级上下文不应继续继承。
            for clear_index in range(index + 1, width - 1):
                if row[clear_index]:
                    continue
                context[clear_index] = ""

        path = [
            item
            for item in context
            if item
        ]

        if value and path:
            lines.append(
                " > ".join(path)
                + "："
                + value
            )
        elif path and changed_index is not None:
            lines.append(
                " > ".join(path)
            )
        elif value:
            lines.append(value)

    return "\n".join(lines).strip()


def stage66_render_structured_form(
    rows: list[list[str]],
) -> str:
    lines: list[str] = []

    for row in rows:
        values = [
            (index, stage66_normalize_cell_display(value))
            for index, value in enumerate(row)
            if stage66_normalize_cell_display(value)
        ]

        if not values:
            continue

        if len(values) == 1:
            lines.append(values[0][1])
            continue

        # 高占用行更像“子表的一行”，保留同一行关系，不强行猜 key/value。
        width = max(1, len(row))
        occupancy = len(values) / width

        if len(values) >= 3 and occupancy >= 0.60:
            lines.append(
                " | ".join(value for _, value in values)
            )
            continue

        # 稀疏表单通常呈 label/value, label/value ... 交替。
        # 仅在非空 cell 为偶数时配对；否则保守保留顺序。
        if len(values) % 2 == 0:
            pairs = []

            for offset in range(0, len(values), 2):
                left = values[offset][1]
                right = values[offset + 1][1]
                pairs.append(f"{left}：{right}")

            lines.append("；".join(pairs))
            continue

        lines.append(
            " | ".join(value for _, value in values)
        )

    return "\n".join(lines).strip()



def stage66_logical_hierarchy_context(
    logical_table: dict[str, Any] | None,
    page_number: int,
    width: int,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[bool, list[str]]:
    """判断跨页 logical table 是否整体属于层级表，并恢复本页开始前的层级上下文。"""
    if not isinstance(logical_table, dict) or width < 3:
        return False, []

    rows = logical_table.get("rows", [])
    row_sources = logical_table.get("row_sources", [])

    if not isinstance(rows, list):
        return False, []

    cleaned_rows: list[list[str]] = []
    cleaned_sources: list[dict[str, Any] | None] = []

    for index, row in enumerate(rows):
        if not isinstance(row, list):
            continue

        source = (
            row_sources[index]
            if isinstance(row_sources, list)
            and index < len(row_sources)
            and isinstance(row_sources[index], dict)
            else None
        )

        cleaned, _ = stage66_clean_table_row_noise(
            row,
            source,
            snapshot_pages,
            noise_by_page,
        )

        values = [
            stage66_normalize_cell_display(value)
            for value in cleaned
        ]

        # schema 发生明显变化时，不拿不同宽度的 row 判断当前层级表。
        if len(values) != width:
            continue

        cleaned_rows.append(values)
        cleaned_sources.append(source)

    if not cleaned_rows:
        return False, []

    logical_profile = stage66_table_display_profile(
        cleaned_rows
    )

    if not logical_profile.get("hierarchy_candidate"):
        return False, []

    header_index, _, _ = stage66_find_local_header(
        cleaned_rows,
        width,
    )

    if header_index is None:
        return False, []

    context = [""] * (width - 1)

    for index, row in enumerate(cleaned_rows):
        if index <= header_index:
            continue

        source = cleaned_sources[index]

        if not isinstance(source, dict):
            continue

        try:
            start_page = int(source.get("start_page"))
        except (TypeError, ValueError):
            continue

        if start_page >= page_number:
            continue

        for col in range(width - 1):
            value = row[col]

            if not value:
                continue

            context[col] = value

            for clear_col in range(col + 1, width - 1):
                if row[clear_col]:
                    continue
                context[clear_col] = ""

    return True, context



def stage66_logical_matrix_context(
    logical_table: dict[str, Any] | None,
    width: int,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[bool, list[str] | None, float, dict[str, Any]]:
    """
    用整张 cross-page logical table 判断“它整体是不是规则矩阵表”。

    这样续页即使只有 1~2 行、物理页没有重复表头，也可以继承逻辑表表头
    输出合法 Markdown，而不是退化成 `6 | 2018 | ...` 结构文本。
    """
    if not isinstance(logical_table, dict) or width < 2:
        return False, None, 0.0, {}

    rows = logical_table.get("rows", [])
    row_sources = logical_table.get("row_sources", [])
    if not isinstance(rows, list):
        return False, None, 0.0, {}

    cleaned_rows: list[list[str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        source = (
            row_sources[index]
            if isinstance(row_sources, list)
            and index < len(row_sources)
            and isinstance(row_sources[index], dict)
            else None
        )
        cleaned, _ = stage66_clean_table_row_noise(
            row,
            source,
            snapshot_pages,
            noise_by_page,
        )
        values = [stage66_normalize_cell_display(value) for value in cleaned]
        if len(values) != width:
            continue
        cleaned_rows.append(values)

    if not cleaned_rows:
        return False, None, 0.0, {}

    profile = stage66_table_display_profile(cleaned_rows)
    if not profile.get("matrix_candidate"):
        return False, None, 0.0, profile

    _, header, score = stage66_find_local_header(cleaned_rows, width)
    if header is None:
        return False, None, score, profile

    return True, header, score, profile


def stage66_build_uniform_table_display(
    rows: list[list[str]],
    logical_table: dict[str, Any] | None,
    page_number: int,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    profile = stage66_table_display_profile(
        rows
    )

    if not rows:
        return {
            "mode": "structured_text",
            "text": "",
            "diagnostics": profile,
        }

    width = int(
        profile.get("max_columns", 0)
        or 0
    )

    logical_hierarchy, hierarchy_context = (
        stage66_logical_hierarchy_context(
            logical_table,
            page_number,
            width,
            snapshot_pages,
            noise_by_page,
        )
    )

    if profile.get("hierarchy_candidate") or logical_hierarchy:
        diagnostics = dict(profile)
        diagnostics["logical_hierarchy"] = logical_hierarchy
        diagnostics["inherited_context"] = hierarchy_context

        return {
            "mode": "structured_hierarchy",
            "text": stage66_render_hierarchical_table(
                rows,
                hierarchy_context,
            ),
            "diagnostics": diagnostics,
        }

    logical_matrix, logical_header, logical_header_score, logical_matrix_profile = (
        stage66_logical_matrix_context(
            logical_table,
            width,
            snapshot_pages,
            noise_by_page,
        )
    )

    if (profile.get("matrix_candidate") or logical_matrix) and width >= 2:
        local_index, local_header, local_score = (
            stage66_find_local_header(
                rows,
                width,
            )
        )

        header = local_header
        propagated = False
        propagated_score = 0.0
        propagated_source = None

        if header is None:
            header, propagated_score = (
                stage66_find_prior_logical_header(
                    logical_table,
                    page_number,
                    width,
                    snapshot_pages,
                    noise_by_page,
                )
            )
            if header is not None:
                propagated = True
                propagated_source = "prior_logical_page"

        if header is None and logical_matrix and logical_header is not None:
            header = logical_header
            propagated = True
            propagated_score = logical_header_score
            propagated_source = "logical_table_canonical_header"

        if header is not None:
            diagnostics = dict(profile)
            diagnostics.update(
                {
                    "logical_matrix": logical_matrix,
                    "logical_matrix_profile": logical_matrix_profile,
                    "local_header_index": local_index,
                    "local_header_score": round(local_score, 4),
                    "propagated_header": propagated,
                    "propagated_header_source": propagated_source,
                    "propagated_header_score": round(propagated_score, 4),
                }
            )

            return {
                "mode": "markdown_table",
                "text": stage66_render_markdown_table(
                    rows,
                    header,
                    local_index,
                ),
                "diagnostics": diagnostics,
            }

    return {
        "mode": "structured_text",
        "text": stage66_render_structured_form(rows),
        "diagnostics": profile,
    }



def stage66_display_structural_width(
    row: list[str],
) -> int:
    """返回用于“显示层子表切分”的稳定列数；非结构行返回 0。"""
    if not isinstance(row, list) or len(row) < 2:
        return 0

    nonempty = sum(
        1
        for value in row
        if stage66_normalize_cell_display(value)
    )

    # 至少两个非空 cell 才把这一行当作二维表格结构证据。
    # 单 cell / 稀疏标题行只作为子表之间的文本分隔，不据此猜 schema。
    if nonempty < 2:
        return 0

    return len(row)


def stage66_split_mixed_schema_rows(
    rows: list[list[str]],
) -> list[dict[str, Any]]:
    """
    将同一物理 table block 中的多种 row schema 分成显示子段。

    典型来源：PDF 在一页中连续放置“科研项目表 + 论文表”，pdfplumber
    可能把它们包进同一个 table block。此时 Stage5 的 logical table 仍可用于
    跨页 row/cell recovery，但 readable 层不能强迫所有 row 共用同一个表头。

    本函数只依据 row 的二维列数和连续性切分，不读取字段语义。
    """
    structural_widths = {
        width
        for row in rows
        if (width := stage66_display_structural_width(row)) >= 2
    }

    # 只有一种二维 schema 时保持原逻辑，避免影响层级表、表单和普通矩阵表。
    if len(structural_widths) <= 1:
        return [
            {
                "kind": "uniform",
                "width": (
                    next(iter(structural_widths))
                    if structural_widths
                    else 0
                ),
                "rows": rows,
            }
        ]

    segments: list[dict[str, Any]] = []
    current_rows: list[list[str]] = []
    current_kind: str | None = None
    current_width = 0

    def flush() -> None:
        nonlocal current_rows, current_kind, current_width
        if not current_rows:
            return
        segments.append(
            {
                "kind": current_kind or "text",
                "width": current_width,
                "rows": current_rows,
            }
        )
        current_rows = []
        current_kind = None
        current_width = 0

    for row in rows:
        width = stage66_display_structural_width(row)
        kind = "table" if width >= 2 else "text"

        if not current_rows:
            current_rows = [row]
            current_kind = kind
            current_width = width
            continue

        same_segment = (
            kind == current_kind
            and (
                kind == "text"
                or width == current_width
            )
        )

        if same_segment:
            current_rows.append(row)
            continue

        flush()
        current_rows = [row]
        current_kind = kind
        current_width = width

    flush()
    return segments


def stage66_build_table_display(
    rows: list[list[str]],
    logical_table: dict[str, Any] | None,
    page_number: int,
    snapshot_pages: dict[int, dict[str, Any]],
    noise_by_page: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    v0.3.4：LLM-first 的保守表格序列化。

    目标不是尽量把所有表格都转成 Markdown，而是避免给下游模型制造
    “看起来很规整、实际列关系可能错误”的结构暗示。

    规则：
    - Stage5 已确认的跨页 logical table：一律结构化文本，不做表头继承，
      不做 mixed-schema 子表拼接；机器层 rows/cells/provenance 仍完整保留。
    - 层级表：输出 structured_hierarchy。
    - 单页、规则矩阵、当前页自身存在高置信表头：才输出 Markdown table。
    - 其它表单、稀疏表、结构不确定表：输出 structured_text。

    不按 case/page/string 特判。
    """
    profile = stage66_table_display_profile(rows)

    if not rows:
        return {
            "mode": "structured_text",
            "text": "",
            "diagnostics": {
                **profile,
                "llm_first_policy": True,
            },
        }

    width = int(profile.get("max_columns", 0) or 0)

    # 跨页表格：不再为了 readable Markdown 做表头继承或 schema 修复。
    # Stage5 的 logical table 仍保留在 normalized JSON 中，后续如果需要
    # 专门的表格视图，可以基于机器结构重新序列化，而无需重跑 PDF。
    if isinstance(logical_table, dict):
        logical_hierarchy, hierarchy_context = (
            stage66_logical_hierarchy_context(
                logical_table,
                page_number,
                width,
                snapshot_pages,
                noise_by_page,
            )
        )

        if profile.get("hierarchy_candidate") or logical_hierarchy:
            diagnostics = dict(profile)
            diagnostics.update(
                {
                    "llm_first_policy": True,
                    "cross_page_forced_structured": True,
                    "logical_hierarchy": logical_hierarchy,
                    "inherited_context": hierarchy_context,
                }
            )
            return {
                "mode": "structured_hierarchy",
                "text": stage66_render_hierarchical_table(
                    rows,
                    hierarchy_context,
                ),
                "diagnostics": diagnostics,
            }

        diagnostics = dict(profile)
        diagnostics.update(
            {
                "llm_first_policy": True,
                "cross_page_forced_structured": True,
                "header_inheritance_disabled": True,
                "mixed_schema_segmentation_disabled": True,
            }
        )
        return {
            "mode": "structured_text",
            "text": stage66_render_structured_form(rows),
            "diagnostics": diagnostics,
        }

    # 单页层级表继续保留“路径 > 指标：值”形式；这比 Markdown rowspan
    # 近似更稳定，也更适合下游 LLM。
    if profile.get("hierarchy_candidate"):
        diagnostics = dict(profile)
        diagnostics.update(
            {
                "llm_first_policy": True,
                "single_page_hierarchy": True,
            }
        )
        return {
            "mode": "structured_hierarchy",
            "text": stage66_render_hierarchical_table(rows),
            "diagnostics": diagnostics,
        }

    # 只有“本页自身就是规则矩阵 + 本页自身有可靠表头”才使用 Markdown。
    # 不从前页/全局 logical table 传播表头，因此不会把错误 schema 强加给当前页。
    if profile.get("matrix_candidate") and width >= 2:
        local_index, local_header, local_score = stage66_find_local_header(
            rows,
            width,
        )

        # 为降低误判，表头必须出现在前两行；后面的“像表头行”不用于
        # 把整块内容改写成 Markdown。
        if (
            local_header is not None
            and local_index is not None
            and local_index <= 1
            and local_score >= 0.80
        ):
            diagnostics = dict(profile)
            diagnostics.update(
                {
                    "llm_first_policy": True,
                    "single_page_markdown": True,
                    "local_header_index": local_index,
                    "local_header_score": round(local_score, 4),
                    "propagated_header": False,
                }
            )
            return {
                "mode": "markdown_table",
                "text": stage66_render_markdown_table(
                    rows,
                    local_header,
                    local_index,
                ),
                "diagnostics": diagnostics,
            }

    diagnostics = dict(profile)
    diagnostics.update(
        {
            "llm_first_policy": True,
            "fallback_reason": "not_safe_single_page_matrix",
        }
    )
    return {
        "mode": "structured_text",
        "text": stage66_render_structured_form(rows),
        "diagnostics": diagnostics,
    }


def stage66_record_start_page(
    record: dict[str, Any],
) -> int | None:
    if record.get("record_type") == "paragraph":
        pages = record.get("source_pages", [])

        if not pages:
            return None

        try:
            return int(pages[0])
        except (TypeError, ValueError):
            return None

    try:
        return int(record.get("source_page"))
    except (TypeError, ValueError):
        return None


def stage66_bbox_intersection_area(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    x0 = max(first["x0"], second["x0"])
    top = max(first["top"], second["top"])
    x1 = min(first["x1"], second["x1"])
    bottom = min(first["bottom"], second["bottom"])

    if x1 <= x0 or bottom <= top:
        return 0.0

    return (x1 - x0) * (bottom - top)


def stage66_bbox_area_value(
    bbox: dict[str, float],
) -> float:
    return max(
        0.0,
        (bbox["x1"] - bbox["x0"])
        * (bbox["bottom"] - bbox["top"]),
    )


def stage66_suppress_table_duplicate_paragraph_runs(
    page_records: list[dict[str, Any]],
) -> int:
    tables = [
        record
        for record in page_records
        if record.get("record_type") == "table_ref"
        and str(record.get("effective_visibility") or "") == "visible"
        and str(record.get("table_text") or "").strip()
        and normalize_bbox(record.get("bbox")) is not None
    ]

    paragraphs = [
        record
        for record in page_records
        if record.get("record_type") == "paragraph"
        and str(record.get("effective_visibility") or "visible") == "visible"
        and str(record.get("text") or "").strip()
        and normalize_bbox(record.get("bbox")) is not None
    ]

    paragraphs.sort(
        key=lambda record: (
            normalize_bbox(record.get("bbox"))["top"],
            normalize_bbox(record.get("bbox"))["x0"],
        )
    )

    candidates: list[dict[str, Any]] = []

    for table in tables:
        table_bbox = normalize_bbox(table.get("bbox"))
        assert table_bbox is not None
        table_text = str(table.get("table_text") or "")

        for start in range(len(paragraphs)):
            run_records: list[dict[str, Any]] = []

            for end in range(
                start,
                min(
                    len(paragraphs),
                    start + STAGE66_TABLE_DUPLICATE_MAX_PARAGRAPH_RUN,
                ),
            ):
                run_records.append(
                    paragraphs[end]
                )

                bboxes = [
                    normalize_bbox(item.get("bbox"))
                    for item in run_records
                ]
                bboxes = [
                    bbox
                    for bbox in bboxes
                    if bbox is not None
                ]

                run_bbox = bbox_union(bboxes)

                if run_bbox is None:
                    continue

                overlap = stage66_bbox_overlap_over_smaller(
                    run_bbox,
                    table_bbox,
                )

                if overlap < STAGE66_TABLE_DUPLICATE_MIN_GEOMETRY_OVERLAP:
                    continue

                run_text = "\n".join(
                    str(item.get("text") or "")
                    for item in run_records
                )

                normalized_chars = len(
                    stage63_layout_match_text(run_text)
                )

                if normalized_chars < STAGE66_TABLE_DUPLICATE_MIN_CHARS:
                    continue

                coverage = stage63_sequence_match_coverage(
                    run_text,
                    table_text,
                )

                if coverage < STAGE66_TABLE_DUPLICATE_MIN_TEXT_COVERAGE:
                    continue

                candidates.append(
                    {
                        "coverage": coverage,
                        "overlap": overlap,
                        "normalized_chars": normalized_chars,
                        "matched_chars": coverage * normalized_chars,
                        "records": list(run_records),
                        "table_record_id": table.get("record_id"),
                    }
                )

    # 优先覆盖更多重复字符，而不是只追求单段 coverage=1.0。
    # 这样可处理“同一 table 尾部被 Stage6.3 拆成两三段”的情况。
    candidates.sort(
        key=lambda item: (
            item["matched_chars"],
            len(item["records"]),
            item["coverage"],
            item["overlap"],
        ),
        reverse=True,
    )

    suppressed_ids: set[str] = set()
    suppressed_count = 0

    for candidate in candidates:
        ids = [
            str(record.get("record_id") or "")
            for record in candidate["records"]
        ]

        if not all(ids) or any(
            record_id in suppressed_ids
            for record_id in ids
        ):
            continue

        for record in candidate["records"]:
            record_id = str(record.get("record_id"))
            suppressed_ids.add(record_id)
            suppressed_count += 1
            record["effective_visibility"] = (
                "suppressed_table_overlap_duplicate"
            )
            record["suppression_reason"] = (
                "paragraph_text_already_materialized_by_overlapping_table"
            )
            record["suppression_evidence"] = {
                "table_record_id": candidate["table_record_id"],
                "text_coverage": round(candidate["coverage"], 4),
                "geometry_overlap": round(candidate["overlap"], 4),
            }

    return suppressed_count


def stage66_page_safe_for_non_text_insertion(
    records: list[dict[str, Any]],
) -> bool:
    """
    v0.3.1：正文顺序以 Stage6.3/6.4 的 semantic order 为 authority。

    本函数只判断“是否可以把 non-text 按几何插回正文骨架”，
    不再允许按 top/x 重新排序已有 paragraph。
    """
    paragraph_anchor_count = 0
    non_text_anchor_count = 0

    for record in records:
        if record.get("record_type") == "paragraph":
            pages = record.get("source_pages", [])

            # 跨页 logical paragraph 的几何横跨多个物理页，当前不在这里拆分。
            if isinstance(pages, list) and len(pages) > 1:
                return False

            column_role = str(record.get("column_role") or "")
            if column_role in {"left", "right"}:
                return False

            if normalize_bbox(record.get("bbox")) is not None:
                paragraph_anchor_count += 1
        else:
            column_role = str(record.get("column_role") or "")
            if column_role in {"left", "right"}:
                return False

            if normalize_bbox(record.get("bbox")) is not None:
                non_text_anchor_count += 1

    return (
        paragraph_anchor_count >= 1
        and non_text_anchor_count >= 1
    )


def stage66_non_text_insertion_slot(
    non_text_record: dict[str, Any],
    paragraph_entries: list[tuple[int, dict[str, Any]]],
) -> int | None:
    """
    在“不改变 paragraph 相对顺序”的前提下，为一个 non-text record
    选择插入槽位：0 表示第一个 paragraph 前，N 表示最后一个 paragraph 后。

    只使用几何关系；若 non-text 明显嵌在单个 paragraph bbox 内部，说明需要
    更细的 paragraph split 才能精确插入，此时返回 None，不做强猜。
    """
    bbox = normalize_bbox(non_text_record.get("bbox"))
    if bbox is None or not paragraph_entries:
        return None

    paragraph_bboxes: list[tuple[int, dict[str, float]]] = []

    for semantic_index, (_, record) in enumerate(paragraph_entries):
        paragraph_bbox = normalize_bbox(record.get("bbox"))
        if paragraph_bbox is not None:
            paragraph_bboxes.append((semantic_index, paragraph_bbox))

    if not paragraph_bboxes:
        return None

    # 如果 non-text 的纵向中心落在某个 paragraph 的内部，且上下都没有明显
    # paragraph gap，则当前粒度不足以安全地“切开 paragraph”。不猜。
    non_center_y = (bbox["top"] + bbox["bottom"]) / 2.0

    overlapping = [
        (index, paragraph_bbox)
        for index, paragraph_bbox in paragraph_bboxes
        if (
            paragraph_bbox["top"] < non_center_y < paragraph_bbox["bottom"]
            and stage66_bbox_intersection_area(bbox, paragraph_bbox) > 0
        )
    ]

    if overlapping:
        # 只有在 non-text 与 paragraph 真正有面积重叠时才视为不可安全插入；
        # 单纯 y 区间相交但 x 完全分离（例如左右字段）不阻止插入。
        return None

    before_candidates = [
        (index, paragraph_bbox)
        for index, paragraph_bbox in paragraph_bboxes
        if paragraph_bbox["bottom"] <= bbox["top"] + 1.0
    ]

    after_candidates = [
        (index, paragraph_bbox)
        for index, paragraph_bbox in paragraph_bboxes
        if paragraph_bbox["top"] >= bbox["bottom"] - 1.0
    ]

    nearest_before = (
        max(before_candidates, key=lambda item: item[1]["bottom"])
        if before_candidates
        else None
    )
    nearest_after = (
        min(after_candidates, key=lambda item: item[1]["top"])
        if after_candidates
        else None
    )

    if nearest_before is not None and nearest_after is not None:
        before_index, before_bbox = nearest_before
        after_index, after_bbox = nearest_after

        # 正常情况下两个几何邻居在 semantic skeleton 中也是前后关系。
        # 如果不是（例如表单 label/value 的 y 坐标交错），不重排正文，
        # 只选择距离更近的一侧作为插入锚点。
        if before_index < after_index:
            return before_index + 1

        gap_before = max(0.0, bbox["top"] - before_bbox["bottom"])
        gap_after = max(0.0, after_bbox["top"] - bbox["bottom"])

        if gap_before <= gap_after:
            return before_index + 1
        return after_index

    if nearest_before is not None:
        return nearest_before[0] + 1

    if nearest_after is not None:
        return nearest_after[0]

    return None


def stage66_apply_page_geometry_order(
    normalized: dict[str, Any],
) -> dict[str, Any]:
    """
    v0.3.1 final flow ordering：

    - paragraph 的相对顺序严格继承 Stage6.3/6.4 semantic order；
    - image/table/vector 只作为 non-text 插入 paragraph skeleton；
    - 不再把所有 records 用 (top, x0) 全量重排；
    - 证据不足时保留 Stage6.2/6.3 原顺序。

    这样既不会把 Page1 一类已修正的表单 label/value 顺序重新排坏，
    又能把 Page17 一类正文中间图片插回对应段落间隙。
    """
    records = [
        record
        for record in normalized.get("records", [])
        if isinstance(record, dict)
    ]

    grouped: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    unassigned: list[tuple[int, dict[str, Any]]] = []

    for original_index, record in enumerate(records):
        page_number = stage66_record_start_page(record)

        if page_number is None:
            unassigned.append((original_index, record))
            continue

        grouped[page_number].append((original_index, record))

    reordered: list[dict[str, Any]] = []
    page_order_modes: dict[int, str] = {}

    for page_number in sorted(grouped):
        entries = grouped[page_number]
        page_records = [record for _, record in entries]

        if not stage66_page_safe_for_non_text_insertion(page_records):
            ordered_entries = list(entries)
            page_order_modes[page_number] = "preserve_stage63_semantic_order"
        else:
            paragraph_entries = [
                pair
                for pair in entries
                if pair[1].get("record_type") == "paragraph"
            ]
            non_text_entries = [
                pair
                for pair in entries
                if pair[1].get("record_type") != "paragraph"
            ]

            slots: list[list[tuple[int, dict[str, Any]]]] = [
                [] for _ in range(len(paragraph_entries) + 1)
            ]
            unresolved_non_text: list[tuple[int, dict[str, Any]]] = []

            paragraph_original_indices = [
                original_index
                for original_index, _ in paragraph_entries
            ]

            for pair in non_text_entries:
                original_index, record = pair
                slot = stage66_non_text_insertion_slot(
                    record,
                    paragraph_entries,
                )

                if slot is None:
                    # 无几何锚点或几何与 paragraph 内部重叠时，按原 record
                    # 在 paragraph skeleton 中的大致位置回退，不改变正文顺序。
                    slot = sum(
                        1
                        for value in paragraph_original_indices
                        if value < original_index
                    )
                    slot = max(0, min(len(paragraph_entries), slot))
                    unresolved_non_text.append(pair)

                slots[slot].append(pair)

            for slot_items in slots:
                slot_items.sort(
                    key=lambda pair: (
                        (
                            normalize_bbox(pair[1].get("bbox"))["top"]
                            if normalize_bbox(pair[1].get("bbox")) is not None
                            else float("inf")
                        ),
                        (
                            normalize_bbox(pair[1].get("bbox"))["x0"]
                            if normalize_bbox(pair[1].get("bbox")) is not None
                            else float("inf")
                        ),
                        pair[0],
                    )
                )

            ordered_entries: list[tuple[int, dict[str, Any]]] = []

            for index, paragraph_pair in enumerate(paragraph_entries):
                ordered_entries.extend(slots[index])
                ordered_entries.append(paragraph_pair)

            ordered_entries.extend(slots[len(paragraph_entries)])

            page_order_modes[page_number] = (
                "preserve_semantic_text_insert_non_text"
                if not unresolved_non_text
                else "preserve_semantic_text_insert_non_text_with_fallback"
            )

        for page_flow_order, (_, record) in enumerate(
            ordered_entries,
            start=1,
        ):
            record["page_flow_order"] = page_flow_order
            reordered.append(record)

    reordered.extend(
        record
        for _, record in sorted(unassigned)
    )

    normalized["records"] = reordered

    rank = {
        str(record.get("record_id")): index
        for index, record in enumerate(reordered)
        if record.get("record_id")
    }

    for section in normalized.get("sections", []):
        if not isinstance(section, dict):
            continue
        values = section.get("record_ids", [])
        if isinstance(values, list):
            values.sort(
                key=lambda record_id: rank.get(
                    str(record_id),
                    10**12,
                )
            )

    for page in normalized.get("page_index", []):
        if not isinstance(page, dict):
            continue

        try:
            page_number = int(page.get("page_number"))
        except (TypeError, ValueError):
            continue

        page["final_record_order_mode"] = page_order_modes.get(
            page_number,
            "preserve_stage63_semantic_order",
        )

        non_text_ids = page.get("non_text_record_ids", [])
        if isinstance(non_text_ids, list):
            non_text_ids.sort(
                key=lambda record_id: rank.get(
                    str(record_id),
                    10**12,
                )
            )

    return normalized


def stage66_records_by_start_page(
    normalized: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for record in normalized.get("records", []):
        if not isinstance(record, dict):
            continue

        if record.get("record_type") == "paragraph":
            pages = record.get("source_pages", [])
            if not pages:
                continue

            try:
                page_number = int(pages[0])
            except (TypeError, ValueError):
                continue
        else:
            try:
                page_number = int(record.get("source_page"))
            except (TypeError, ValueError):
                continue

        result[page_number].append(record)

    return dict(result)


def stage66_append_record_to_section(
    normalized: dict[str, Any],
    page_number: int,
    record_id: str,
) -> None:
    for section in normalized.get("sections", []):
        if not isinstance(section, dict):
            continue

        pages = section.get("page_numbers", [])

        if page_number not in pages:
            continue

        record_ids = section.setdefault("record_ids", [])

        if record_id not in record_ids:
            record_ids.append(record_id)

        return


def stage66_append_non_text_to_page_index(
    normalized: dict[str, Any],
    page_number: int,
    record_id: str,
) -> None:
    for page in normalized.get("page_index", []):
        if not isinstance(page, dict):
            continue

        try:
            current_page = int(page.get("page_number"))
        except (TypeError, ValueError):
            continue

        if current_page != page_number:
            continue

        values = page.setdefault("non_text_record_ids", [])

        if record_id not in values:
            values.append(record_id)

        return


def stage66_validate_stage5_identity(
    normalized: dict[str, Any],
    stage5: dict[str, Any],
) -> None:
    normalized_source = clean_text(normalized.get("source_file"))
    stage5_source = clean_text(stage5.get("source_file"))

    if (
        normalized_source
        and stage5_source
        and normalized_source != stage5_source
    ):
        raise ValueError(
            "Stage5 与 Stage6 source_file 不一致: "
            f"{stage5_source} != {normalized_source}"
        )

    stage5_page_count = stage5.get("page_count")
    normalized_page_count = normalized.get("page_count")

    try:
        stage5_count = int(stage5_page_count)
        normalized_count = int(normalized_page_count)
    except (TypeError, ValueError):
        return

    if stage5_count != normalized_count:
        raise ValueError(
            "Stage5 与 Stage6 page_count 不一致: "
            f"{stage5_count} != {normalized_count}"
        )


def stage66_finalize_native_flow(
    normalized: dict[str, Any],
    stage5: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]],
    noise_result: dict[str, Any],
) -> dict[str, Any]:
    """
    把 Stage5 table recovery 正式收口进 Stage6.6。

    注意：
    - 这不是 readable renderer 的后处理；
    - readable_final.md 后面只消费本函数产出的 normalized result；
    - 不重新打开 PDF，不做 OCR，不做字符语义修复。
    """
    stage66_validate_stage5_identity(
        normalized,
        stage5,
    )

    stage5_pages = stage66_stage5_page_map(stage5)
    logical_map = stage66_logical_table_by_fragment(stage5)
    stage5_owned_words = stage66_stage5_owned_word_indices(stage5)
    noise_by_page = stage66_removable_noise_occurrences(noise_result)
    records_by_page = stage66_records_by_start_page(normalized)

    page_index_map = {
        int(page["page_number"]): page
        for page in normalized.get("page_index", [])
        if isinstance(page, dict)
        and page.get("page_number") is not None
    }

    materialized_count = 0
    suppressed_existing_count = 0
    appended_table_count = 0
    unresolved_table_count = 0
    logical_continuation_count = 0
    removed_noise_token_count = 0
    suppressed_paragraph_count = 0
    suppressed_stage5_owned_paragraph_count = 0
    suppressed_materialized_table_owned_paragraph_count = 0
    suppressed_confirmed_noise_table_residual_count = 0
    suppressed_physical_tables: list[dict[str, Any]] = []

    for page_number in sorted(
        set(page_index_map)
        | set(stage5_pages)
        | set(records_by_page)
    ):
        page_records = records_by_page.get(page_number, [])

        # Stage5 已通过 native geometry 明确把某些 raw words 吸收到 table cell 后，
        # 若一个 paragraph 的 provenance 被这些 ownership 100% 覆盖，则该 paragraph
        # 不应再次进入最终正文。partial overlap 不做任何字符级修改。
        for record in page_records:
            if (
                record.get("record_type") != "paragraph"
                or str(record.get("effective_visibility") or "visible") != "visible"
            ):
                continue

            fully_owned, ownership_evidence = (
                stage66_paragraph_fully_owned_by_stage5(
                    record,
                    stage5_owned_words,
                )
            )

            if not fully_owned:
                continue

            record["effective_visibility"] = (
                "suppressed_stage5_table_ownership"
            )
            record["suppression_reason"] = (
                "paragraph_source_words_fully_owned_by_stage5_table_recovery"
            )
            record["suppression_evidence"] = ownership_evidence
            suppressed_stage5_owned_paragraph_count += 1

        paragraph_texts = [
            str(record.get("text") or "")
            for record in page_records
            if record.get("record_type") == "paragraph"
            and str(record.get("effective_visibility") or "visible") == "visible"
            and str(record.get("text") or "").strip()
        ]

        idx = page_index_map.get(page_number, {})
        zone_type = str(idx.get("zone_type") or "")
        physical_tables = stage66_stage5_tables(
            stage5_pages.get(page_number, {})
        )

        physical_by_index: dict[int, dict[str, Any]] = {}

        for item in physical_tables:
            try:
                table_index = int(item.get("table_index"))
            except (TypeError, ValueError):
                continue

            physical_by_index[table_index] = item

        consumed: set[int] = set()

        # 先物化 Stage6 已经存在的 table_ref。
        for record in page_records:
            if record.get("record_type") != "table_ref":
                continue

            table_index = stage66_resolve_table_ref_index(
                record,
                physical_tables,
                consumed,
                snapshot_pages,
                page_number,
            )

            if table_index is None:
                record["materialization_status"] = "unresolved_stage5_table"
                record["effective_visibility"] = "visible_unresolved"
                unresolved_table_count += 1
                continue

            physical = physical_by_index.get(table_index)

            if not isinstance(physical, dict):
                record["materialization_status"] = "unresolved_stage5_table"
                record["effective_visibility"] = "visible_unresolved"
                unresolved_table_count += 1
                continue

            consumed.add(table_index)
            record["source_table_index"] = table_index
            logical = logical_map.get((page_number, table_index))

            if logical is not None:
                rows, row_sources = stage66_logical_rows_starting_on_page(
                    logical,
                    page_number,
                )
                table_source = "stage5_cross_page_logical_table"
            else:
                raw_rows = physical.get("rows", [])
                rows = raw_rows if isinstance(raw_rows, list) else []
                row_sources = stage66_physical_row_sources(
                    page_number,
                    table_index,
                    len(rows),
                    physical,
                )
                table_source = "stage5_physical_table"

            duplicate, duplicate_evidence = (
                stage66_table_already_represented_by_paragraphs(
                    rows,
                    paragraph_texts,
                    zone_type,
                )
            )

            if duplicate:
                record["materialization_status"] = "suppressed_duplicate"
                record["effective_visibility"] = "suppressed_duplicate"
                record["suppression_reason"] = (
                    "table_already_represented_by_final_paragraphs"
                )
                record["suppression_evidence"] = duplicate_evidence
                record["table_source"] = table_source
                suppressed_existing_count += 1
                continue

            final_rows, table_text, removed = stage66_materialize_rows(
                rows,
                row_sources,
                snapshot_pages,
                noise_by_page,
            )

            removed_noise_token_count += removed

            display = stage66_build_table_display(
                final_rows,
                logical,
                page_number,
                snapshot_pages,
                noise_by_page,
            )

            record["table_source"] = table_source
            record["table_origin"] = physical.get("table_origin")
            record["table_rows"] = final_rows
            record["table_text"] = table_text
            record["table_display_mode"] = display["mode"]
            record["table_display_text"] = display["text"]
            record["table_display_diagnostics"] = display["diagnostics"]
            record["table_row_sources"] = row_sources
            record["confirmed_noise_tokens_removed"] = removed
            record["effective_visibility"] = "visible"

            if final_rows:
                record["materialization_status"] = "materialized"
                materialized_count += 1
            elif logical is not None:
                record["materialization_status"] = (
                    "logical_continuation_merged_to_previous_start_page"
                )
                logical_continuation_count += 1
            else:
                record["materialization_status"] = "materialized_empty"
                materialized_count += 1

        # Stage5 仍有物理表但 Stage6 flow 没有 table_ref：
        # 在 Stage6.6 做最后归并，而不是由 readable renderer 再兜底。
        for physical in physical_tables:
            try:
                table_index = int(physical.get("table_index"))
            except (TypeError, ValueError):
                continue

            if table_index in consumed:
                continue

            logical = logical_map.get((page_number, table_index))

            if logical is not None:
                rows, row_sources = stage66_logical_rows_starting_on_page(
                    logical,
                    page_number,
                )
                table_source = "stage5_cross_page_logical_table"

                # 续页没有从本页开始的 logical row，不额外制造空 record。
                if not rows:
                    continue
            else:
                raw_rows = physical.get("rows", [])
                rows = raw_rows if isinstance(raw_rows, list) else []
                row_sources = stage66_physical_row_sources(
                    page_number,
                    table_index,
                    len(rows),
                    physical,
                )
                table_source = "stage5_physical_table"

            duplicate, duplicate_evidence = (
                stage66_table_already_represented_by_paragraphs(
                    rows,
                    paragraph_texts,
                    zone_type,
                )
            )

            if duplicate:
                suppressed_physical_tables.append(
                    {
                        "page_number": page_number,
                        "table_index": table_index,
                        "reason": "table_already_represented_by_final_paragraphs",
                        "evidence": duplicate_evidence,
                    }
                )
                continue

            final_rows, table_text, removed = stage66_materialize_rows(
                rows,
                row_sources,
                snapshot_pages,
                noise_by_page,
            )

            if not final_rows:
                continue

            removed_noise_token_count += removed
            record_id = f"ntf{len(normalized.get('records', [])) + 1:06d}"

            display = stage66_build_table_display(
                final_rows,
                logical,
                page_number,
                snapshot_pages,
                noise_by_page,
            )

            record = {
                "record_id": record_id,
                "record_type": "table_ref",
                "source_page": page_number,
                "section_id": idx.get("section_id"),
                "section_title": idx.get("section_title"),
                "zone_type": idx.get("zone_type"),
                "source_page_status": idx.get("status"),
                "source_page_confidence": idx.get("confidence"),
                "block_id": physical.get("block_id"),
                "source_block_id": physical.get("source_block_id"),
                "source_table_index": table_index,
                "reading_order": None,
                "flow_order": None,
                "flow_role": "main",
                "column_role": None,
                "bbox": (
                    physical.get("bbox")
                    or stage66_raw_table_bbox(
                        snapshot_pages,
                        page_number,
                        table_index,
                    )
                ),
                "content_status": "materialized_stage5_native",
                "record_origin": "stage6_6_stage5_unreferenced_table_recovery",
                "table_source": table_source,
                "table_origin": physical.get("table_origin"),
                "table_rows": final_rows,
                "table_text": table_text,
                "table_display_mode": display["mode"],
                "table_display_text": display["text"],
                "table_display_diagnostics": display["diagnostics"],
                "table_row_sources": row_sources,
                "confirmed_noise_tokens_removed": removed,
                "materialization_status": "materialized",
                "effective_visibility": "visible",
            }

            normalized.setdefault("records", []).append(record)
            records_by_page.setdefault(page_number, []).append(record)
            stage66_append_record_to_section(
                normalized,
                page_number,
                record_id,
            )
            stage66_append_non_text_to_page_index(
                normalized,
                page_number,
                record_id,
            )

            appended_table_count += 1
            materialized_count += 1

        # 反向去重：table 已成为最终 authority 后，抑制同一区域内已经被 table
        # 表达的 native paragraph。允许最多 4 个相邻 paragraph 组成一个重复 run，
        # 避免表格底部被拆成两三段后漏删。
        suppressed_paragraph_count += (
            stage66_suppress_table_duplicate_paragraph_runs(
                records_by_page.get(page_number, [])
            )
        )

    # v0.3.5：只有最终真正物化、可见的 native table 才成为新的 word authority。
    # ownership 还必须满足“去除 confirmed noise 后的 raw word 文本已经被 table_text 表达”。
    # 这样既能抑制“正文片段 + 水印字符”混合 raw word 产生的残余 paragraph，
    # 又不会仅凭几何把 table extraction 没有表达出来的 native word 静默删除。
    materialized_table_owned_words = (
        stage66_materialized_table_owned_word_indices(
            normalized,
            snapshot_pages,
            noise_by_page,
        )
    )

    final_table_owned_words: dict[int, set[int]] = defaultdict(set)

    for page_number, indices in stage5_owned_words.items():
        final_table_owned_words[page_number].update(indices)

    for page_number, indices in materialized_table_owned_words.items():
        final_table_owned_words[page_number].update(indices)

    for record in normalized.get("records", []):
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "paragraph":
            continue
        if str(record.get("effective_visibility") or "visible") != "visible":
            continue

        fully_owned, ownership_evidence = (
            stage66_paragraph_fully_owned_by_stage5(
                record,
                final_table_owned_words,
            )
        )

        if not fully_owned:
            continue

        # 如果该 paragraph 只依赖旧的 Stage5 explicit ownership，前面的 pass
        # 理论上已经处理；这里主要记录 materialized table authority 新增的覆盖。
        source_pages = [
            int(fragment.get("page_number"))
            for fragment in record.get("source_fragment_geometry", [])
            if isinstance(fragment, dict)
            and fragment.get("page_number") is not None
        ]

        uses_materialized_authority = any(
            materialized_table_owned_words.get(page_number)
            for page_number in source_pages
        )

        if not uses_materialized_authority:
            continue

        record["effective_visibility"] = (
            "suppressed_materialized_table_word_ownership"
        )
        record["suppression_reason"] = (
            "paragraph_source_words_already_represented_by_materialized_table_after_confirmed_noise_exclusion"
        )
        record["suppression_evidence"] = ownership_evidence
        suppressed_materialized_table_owned_paragraph_count += 1

    # v0.3.6：处理 raw-word bbox 被 confirmed watermark 拉伸后导致的极窄 ownership 漏判。
    # 只有 provenance、实际去噪、paragraph 精确文本、materialized table 文本、几何交集五者同时成立才 suppress。
    suppressed_confirmed_noise_table_residual_count += (
        stage66_suppress_confirmed_noise_table_residuals(
            normalized,
            snapshot_pages,
            noise_by_page,
        )
    )

    # v0.3.0：paragraph 已携带 bbox 后，对普通单栏页统一按几何重建最终 record 顺序。
    # 多栏页保留 Stage6.2 reading order，不做简单 y/x 重排。
    normalized = stage66_apply_page_geometry_order(
        normalized
    )

    normalized["record_count"] = len(normalized.get("records", []))
    normalized["non_text_reference_count"] = sum(
        1
        for record in normalized.get("records", [])
        if isinstance(record, dict)
        and record.get("record_type") != "paragraph"
    )

    normalized["artifact_role"] = "native_parser_final_flow"
    normalized["stage66_table_finalization"] = {
        "status": "completed",
        "stage5_table_materialization": True,
        "readable_renderer_requires_upstream_repair": False,
        "materialized_table_record_count": materialized_count,
        "appended_unreferenced_stage5_table_count": appended_table_count,
        "suppressed_existing_table_ref_count": suppressed_existing_count,
        "suppressed_unreferenced_stage5_table_count": len(
            suppressed_physical_tables
        ),
        "unresolved_table_ref_count": unresolved_table_count,
        "logical_continuation_only_record_count": logical_continuation_count,
        "confirmed_noise_token_removal_count": removed_noise_token_count,
        "suppressed_table_overlap_paragraph_count": suppressed_paragraph_count,
        "suppressed_stage5_owned_paragraph_count":
            suppressed_stage5_owned_paragraph_count,
        "suppressed_materialized_table_owned_paragraph_count":
            suppressed_materialized_table_owned_paragraph_count,
        "suppressed_confirmed_noise_table_residual_count":
            suppressed_confirmed_noise_table_residual_count,
        "materialized_table_owned_word_count": sum(
            len(indices)
            for indices in materialized_table_owned_words.values()
        ),
        "suppressed_physical_tables": suppressed_physical_tables,
        "table_display_policy": (
            "single_page_local_header_matrix_markdown_else_structured_text_cross_page_always_structured"
        ),
    }

    normalized.setdefault("text_policy", {})[
        "table_noise_cleanup"
    ] = "stage6_1_confirmed_occurrence_plus_source_cell_geometry"
    normalized["text_policy"][
        "stage5_table_materialization"
    ] = True
    normalized["text_policy"][
        "table_display_serialization"
    ] = "llm_first_single_page_safe_markdown_else_structured_text"
    normalized["text_policy"][
        "paragraph_table_overlap_dedupe"
    ] = (
        "stage5_explicit_ownership_then_materialized_table_verified_word_ownership_then_confirmed_noise_residual_exact_match_then_geometry_plus_text_coverage"
    )
    normalized["text_policy"][
        "non_text_inline_order"
    ] = "preserve_semantic_text_insert_non_text_when_safe"
    normalized["text_policy"][
        "readable_renderer_mutates_content"
    ] = False

    normalized.setdefault("stage_status", {})[
        "scope"
    ] = "native_final_flow_before_quality_gate"
    normalized["stage_status"][
        "stage5_table_recovery"
    ] = "materialized_in_stage_6_6"
    normalized["stage_status"][
        "readable_renderer_policy"
    ] = "pure_view_no_repair"
    normalized["stage_status"][
        "next_stage"
    ] = "stage_7_native_evidence_manifest"

    return normalized


# =============================================================================
# readable_final.md — pure view of Stage6 final machine result
# =============================================================================


def stage66_join_display_lines(text: str) -> str:
    """只去机械视觉换行；不补字、不删字、不重新解析。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")
    paragraphs: list[str] = []
    current = ""

    def is_ascii_alnum(char: str) -> bool:
        return bool(char) and char.isascii() and char.isalnum()

    def is_cjk(char: str) -> bool:
        if not char:
            return False
        code = ord(char)
        return (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF
        )

    for raw in raw_lines:
        line = raw.strip()

        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue

        if not current:
            current = line
            continue

        previous = current[-1] if current else ""
        next_char = line[0] if line else ""

        if is_cjk(previous) and is_cjk(next_char):
            separator = ""
        elif is_ascii_alnum(previous) and is_ascii_alnum(next_char):
            separator = " "
        elif previous in "-‐‑‒–—":
            separator = ""
        else:
            separator = ""

        current += separator + line

    if current:
        paragraphs.append(current)

    return "\n\n".join(paragraphs)


def stage66_looks_like_heading(text: str) -> bool:
    compact = " ".join(text.split())

    if not compact or len(compact) > 60:
        return False

    patterns = [
        r"^[一二三四五六七八九十]+、",
        r"^第[一二三四五六七八九十0-9]+[章节部分]",
        r"^\d+[.、]\s*\S+",
        r"^（\d+）\s*\S+",
    ]

    return any(
        re.search(pattern, compact)
        for pattern in patterns
    )


def stage66_same_heading(a: str, b: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value or "").strip("#：:、. ")

    left = normalize(a)
    right = normalize(b)

    return bool(
        left
        and right
        and (
            left == right
            or left in right
            or right in left
        )
    )


def render_readable_final_markdown(
    normalized: dict[str, Any],
) -> str:
    """
    纯展示层：只消费 Stage6 final normalized result。

    禁止：
    - 读取 Stage5 / snapshot / noise；
    - 再次删除 watermark/page number；
    - 再次恢复 logical table；
    - 再次决定 table/paragraph 去重。
    """
    page_index = {
        int(page["page_number"]): page
        for page in normalized.get("page_index", [])
        if isinstance(page, dict)
        and page.get("page_number") is not None
    }

    records_by_page = stage66_records_by_start_page(normalized)
    all_pages = sorted(
        set(page_index)
        | set(records_by_page)
    )

    lines: list[str] = []
    previous_section: str | None = None

    for page_number in all_pages:
        idx = page_index.get(page_number, {})
        section_title = str(
            idx.get("section_title")
            or idx.get("section_id")
            or ""
        ).strip()
        records = records_by_page.get(page_number, [])

        lines.append(f"<!-- page: {page_number} -->")
        lines.append("")

        first_paragraph_text = ""

        for record in records:
            if record.get("record_type") != "paragraph":
                continue

            if str(
                record.get("effective_visibility")
                or "visible"
            ) != "visible":
                continue

            first_paragraph_text = stage66_join_display_lines(
                str(record.get("text") or "")
            ).strip()

            if first_paragraph_text:
                break

        if (
            section_title
            and section_title != "封面"
            and section_title != previous_section
            and not stage66_same_heading(
                section_title,
                first_paragraph_text,
            )
        ):
            lines.append(section_title)
            lines.append("")

        previous_section = section_title or previous_section
        emitted_any = False
        logical_continuation_only = False

        for record in records:
            record_type = str(record.get("record_type") or "")

            if record_type == "paragraph":
                visibility = str(
                    record.get("effective_visibility")
                    or "visible"
                )

                if visibility != "visible":
                    continue

                paragraph_text = stage66_join_display_lines(
                    str(record.get("text") or "")
                ).strip()

                if not paragraph_text:
                    continue

                # readable_final 不再制造 Markdown heading。
                # 标题/章节结构由 normalized_text_flow.json 的 section 元数据承担；
                # 这里仅忠实输出文字，避免 1.xxx / （1）xxx 被误变成 ##。
                lines.append(paragraph_text)

                lines.append("")
                emitted_any = True
                continue

            if record_type == "table_ref":
                visibility = str(
                    record.get("effective_visibility")
                    or "visible"
                )

                if visibility == "suppressed_duplicate":
                    continue

                materialization = str(
                    record.get("materialization_status")
                    or ""
                )

                if materialization == "logical_continuation_merged_to_previous_start_page":
                    logical_continuation_only = True
                    continue

                table_text = str(
                    record.get("table_display_text")
                    or record.get("table_text")
                    or ""
                ).strip()

                if table_text:
                    lines.append(table_text)
                    lines.append("")
                    emitted_any = True
                else:
                    lines.append("> [表格区域：Stage6 final flow 未物化出可读表格内容]")
                    lines.append("")
                    emitted_any = True

                continue

            if record_type == "image_ref":
                lines.append("> [图片区域：当前主解析未识别图片内文字]")
                lines.append("")
                emitted_any = True
                continue

            if record_type == "vector_ref":
                lines.append("> [图形/向量区域]")
                lines.append("")
                emitted_any = True
                continue

        if not emitted_any and logical_continuation_only:
            lines.append("> [跨页表格续接：本页内容已合并到上一页开始的逻辑行]")
            lines.append("")
            emitted_any = True

        if not emitted_any:
            lines.append("> [当前 Stage6 最终结果没有可读文本]")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"

def render_normalized_text_flow_markdown(
    result: dict[str, Any],
) -> str:
    records_by_id = {
        str(record["record_id"]):
            record
        for record in result.get(
            "records",
            [],
        )
        if isinstance(
            record,
            dict,
        )
        and record.get(
            "record_id"
        )
    }

    lines: list[str] = [
        "# Stage 6.6 Final Native Text Flow",
        "",
        f"- 文件：{result.get('source_file')}",
        f"- 页数：{result.get('page_count')}",
        f"- 状态：{result.get('status')}",
        f"- logical paragraphs：{result.get('logical_paragraph_count')}",
        f"- records：{result.get('record_count')}",
        f"- non-text refs：{result.get('non_text_reference_count')}",
        f"- partial source pages：{result.get('partial_source_pages')}",
        "",
        "> 这是 Stage1~6 的最终 native 机器结果，但不是最终 LLM-ready Document。"
        " Stage6.6 已正式物化 Stage5 table recovery，并落实已确认的表格噪声清理；"
        "不做断词修复、不做语义补写、不做 OCR / Quality Gate。"
        " image/vector 继续保留引用。",
        "",
    ]

    for section in result.get(
        "sections",
        [],
    ):
        title = (
            section.get(
                "section_title"
            )
            or section.get(
                "section_id"
            )
            or section.get(
                "section_key"
            )
        )

        lines.extend(
            [
                f"## {title}",
                "",
                (
                    f"_pages={section.get('page_numbers')}"
                    f" | zone={section.get('zone_type')}_"
                ),
                "",
            ]
        )

        for record_id in section.get(
            "record_ids",
            [],
        ):
            record = records_by_id.get(
                str(
                    record_id
                )
            )

            if record is None:
                continue

            if (
                record.get(
                    "record_type"
                )
                == "paragraph"
            ):
                source_pages = record.get(
                    "source_pages",
                    [],
                )

                lines.append(
                    (
                        f"<!-- {record.get('record_id')}"
                        f" | logical={record.get('logical_paragraph_id')}"
                        f" | pages={source_pages}"
                        f" | paragraphs={record.get('source_paragraph_ids')} -->"
                    )
                )

                lines.append(
                    record.get(
                        "text",
                        "",
                    )
                )
                lines.append("")
                continue

            lines.append(
                (
                    f"> [{str(record.get('record_type')).upper()}"
                    f" | PDF page {record.get('source_page')}"
                    f" | block={record.get('block_id')}]"
                )
            )
            lines.append("")

    return (
        "\n".join(
            lines
        ).rstrip()
        + "\n"
    )


def print_normalized_text_flow_summary(
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    integrity = result.get(
        "mapping_integrity",
        {},
    )

    print()
    print("=" * 104)
    print(
        "Stage 6.6 规范化文本流输出"
        f" | {result.get('source_file')}"
        f" | 页数={result.get('page_count')}"
        f" | 算法版本={STAGE66_VERSION}"
        f" | Pipeline={PIPELINE_VERSION}"
    )
    print("=" * 104)

    print(
        "状态"
        f" | status={result.get('status')}"
        f" | logical_paragraphs={result.get('logical_paragraph_count', 0)}"
        f" | emitted={result.get('emitted_logical_paragraph_count', 0)}"
        f" | records={result.get('record_count', 0)}"
        f" | non_text_refs={result.get('non_text_reference_count', 0)}"
        f" | partial_source_pages={len(result.get('partial_source_pages', []))}"
        f" | mapping_integrity={integrity.get('status')}"
        f" | missing_logical_records={len(result.get('missing_logical_records', []))}"
    )

    print(
        f"JSON：{output_dir / 'normalized_text_flow.json'}"
    )
    print(
        f"Markdown：{output_dir / 'normalized_text_flow.md'}"
    )

    print(
        "说明：Stage6.5 按设计跳过。Stage6.6 形成 Stage1~6 最终 native flow："
        "正文来自 Stage6.4 logical paragraphs，table 正式物化 Stage5 recovery，"
        "表格噪声仅落实 Stage6.1 已确认 occurrence + source-cell 几何证据；"
        "readable_final.md 只做展示，不再修复内容；"
        "下一步进入 Stage7 Native Evidence Manifest。"
    )
    print("=" * 104)


# =============================================================================
# Markdown diagnostic
# =============================================================================


def page_range_text(
    pages: list[int],
) -> str:
    if not pages:
        return "-"

    if len(pages) <= 12:
        return ", ".join(
            str(page)
            for page in pages
        )

    return (
        ", ".join(
            str(page)
            for page in pages[:10]
        )
        + f", ... 共{len(pages)}页"
    )


def render_markdown(
    result: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# Stage 6.1 Noise Candidates",
        "",
        f"- 文件：{result['source_file']}",
        f"- 页数：{result['page_count']}",
        f"- 候选组：{result['candidate_count']}",
        "- 当前只识别并给出建议动作，不删除任何正文。",
        "",
        "## 汇总",
        "",
        "| 类型 | 候选组 | occurrence |",
        "|---|---:|---:|",
    ]

    all_types = (
        "page_number",
        "repeated_header",
        "repeated_footer",
        "watermark",
    )

    for candidate_type in all_types:
        lines.append(
            "| "
            + candidate_type
            + " | "
            + str(
                result[
                    "candidate_type_counts"
                ].get(
                    candidate_type,
                    0,
                )
            )
            + " | "
            + str(
                result[
                    "occurrence_type_counts"
                ].get(
                    candidate_type,
                    0,
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 动作汇总",
            "",
            "| action | 候选组 |",
            "|---|---:|",
            f"| auto_remove | {result['action_counts'].get('auto_remove', 0)} |",
            f"| keep_first | {result['action_counts'].get('keep_first', 0)} |",
            f"| review | {result['action_counts'].get('review', 0)} |",
            "",
            "## 候选详情",
            "",
        ]
    )

    for candidate in result[
        "noise_candidates"
    ]:
        lines.extend(
            [
                "### "
                + candidate[
                    "candidate_id"
                ],
                "",
                f"- 类型：{candidate['type']}",
                f"- 子类型：{candidate.get('subtype', '-')}",
                f"- 文本：`{candidate.get('text', '')}`",
                f"- 页：{page_range_text(candidate.get('pages', []))}",
                f"- 原因：{candidate.get('reason', '')}",
                f"- 建议动作：`{candidate.get('action', 'review')}`",
                f"- 动作原因：{candidate.get('action_reason', '')}",
                (
                    f"- 分组模式：`{candidate.get('grouping_mode')}`"
                    if candidate.get("grouping_mode")
                    else ""
                ),
                (
                    f"- 最大页距：{candidate.get('max_page_gap')}"
                    if candidate.get("max_page_gap") is not None
                    else ""
                ),
                (
                    f"- 原始文本种类：{candidate.get('distinct_text_count')}"
                    if candidate.get("distinct_text_count") is not None
                    else ""
                ),
                "",
                "| PDF页 | x_ratio | y_ratio | section | zone |",
                "|---:|---:|---:|---|---|",
            ]
        )

        for occurrence in candidate.get(
            "occurrences",
            [],
        ):
            lines.append(
                "| "
                + str(
                    occurrence[
                        "page_number"
                    ]
                )
                + " | "
                + f"{float(occurrence.get('x_ratio', 0.0)):.3f}"
                + " | "
                + f"{float(occurrence.get('y_ratio', 0.0)):.3f}"
                + " | "
                + str(
                    occurrence.get(
                        "section_id"
                    )
                    or "-"
                )
                + " | "
                + str(
                    occurrence.get(
                        "zone_type"
                    )
                    or "-"
                )
                + " |"
            )

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def print_summary(
    result: dict[str, Any],
    output_dir: Path,
) -> None:
    print()
    print("=" * 72)
    print(
        "Stage 6.1 噪声候选识别"
        f" | {result['source_file']}"
        f" | 页数={result['page_count']}"
        f" | 候选组={result['candidate_count']}"
        f" | 算法版本={STAGE61_VERSION}"
        f" | Pipeline={PIPELINE_VERSION}"
    )
    print("=" * 72)

    for candidate_type in (
        "page_number",
        "repeated_header",
        "repeated_footer",
        "watermark",
    ):
        print(
            f"{candidate_type:>18}"
            f" | 组={result['candidate_type_counts'].get(candidate_type, 0)}"
            f" | occurrence={result['occurrence_type_counts'].get(candidate_type, 0)}"
        )

    print(
        "动作"
        f" | auto_remove={result['action_counts'].get('auto_remove', 0)}"
        f" | keep_first={result['action_counts'].get('keep_first', 0)}"
        f" | review={result['action_counts'].get('review', 0)}"
    )

    print(
        f"JSON：{output_dir / 'noise_candidates.json'}"
    )
    print(
        f"Markdown：{output_dir / 'noise_candidates.md'}"
    )
    print(
        "说明：本版修复 repeated header/footer 错误聚类："
        "原始文本完全一致才可能 keep_first；"
        "仅数字归一化后格式相似一律 review；"
        "连续 '- N -' 单独识别为 inner page number。"
        "当前仍不删除文字，不做 OCR / 阅读顺序 / 段落合并 / Quality Gate。"
    )
    print("=" * 72)


def create_text_flow_result(
    *,
    snapshot_path: Path,
    structure_path: Path,
    table_result_path: Path,
    table_result: dict[str, Any] | None = None,
    snapshot_meta: dict[str, Any] | None = None,
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
    page_structure: dict[str, Any] | None = None,
) -> TextFlowResult:
    """Compute the existing Stage 6 results before artifact serialization."""
    if (snapshot_meta is None) != (snapshot_pages is None):
        raise ValueError("snapshot_meta and snapshot_pages must be provided together")
    if snapshot_meta is None:
        snapshot_meta, snapshot_pages = load_snapshot(Path(snapshot_path))
    structure = page_structure if page_structure is not None else load_json(Path(structure_path))
    stage5_result = table_result if table_result is not None else load_json(Path(table_result_path))

    result = build_result(
        snapshot_meta,
        snapshot_pages,
        structure,
    )
    reading_result = build_reading_order_result(
        structure,
        snapshot_pages,
        result,
    )
    paragraph_result = build_paragraph_result(
        snapshot_pages,
        reading_result,
    )
    cross_page_result = build_cross_page_paragraph_result(
        snapshot_pages,
        reading_result,
        paragraph_result,
    )
    normalized_result = build_normalized_text_flow_result(
        reading_result,
        paragraph_result,
        cross_page_result,
    )
    normalized_result = stage66_finalize_native_flow(
        normalized_result,
        stage5_result,
        snapshot_pages,
        result,
    )

    return TextFlowResult(
        noise=result,
        reading_order=reading_result,
        paragraphs=paragraph_result,
        cross_page_paragraphs=cross_page_result,
        normalized_flow=normalized_result,
    )


def write_text_flow_result(flow: TextFlowResult, output_dir: Path) -> None:
    """Write the historical Stage 6 JSON and Markdown artifacts."""
    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    json_artifacts = {
        "noise_candidates.json": flow.noise,
        "reading_order.json": flow.reading_order,
        "paragraphs.json": flow.paragraphs,
        "cross_page_paragraphs.json": flow.cross_page_paragraphs,
        "normalized_text_flow.json": flow.normalized_flow,
    }
    for name, value in json_artifacts.items():
        with (output_dir / name).open("w", encoding="utf-8") as file:
            json.dump(
                value,
                file,
                ensure_ascii=False,
                indent=2,
            )

    (output_dir / "noise_candidates.md").write_text(
        render_markdown(flow.noise),
        encoding="utf-8",
    )
    (output_dir / "reading_order.md").write_text(
        render_reading_order_markdown(flow.reading_order),
        encoding="utf-8",
    )
    (output_dir / "paragraphs.md").write_text(
        render_paragraph_markdown(flow.paragraphs),
        encoding="utf-8",
    )
    (output_dir / "cross_page_paragraphs.md").write_text(
        render_cross_page_paragraph_markdown(flow.cross_page_paragraphs),
        encoding="utf-8",
    )
    (output_dir / "normalized_text_flow.md").write_text(
        render_normalized_text_flow_markdown(flow.normalized_flow),
        encoding="utf-8",
    )
    (output_dir / "readable_final.md").write_text(
        render_readable_final_markdown(flow.normalized_flow),
        encoding="utf-8",
    )


def run_text_flow(
    *,
    snapshot_path: Path,
    structure_path: Path,
    table_result_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Compatibility API preserving Stage 6 artifacts and return value."""
    flow = create_text_flow_result(
        snapshot_path=snapshot_path,
        structure_path=structure_path,
        table_result_path=table_result_path,
    )
    write_text_flow_result(flow, output_dir)
    return flow.normalized_flow
