from __future__ import annotations

import json
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any



# =============================================================================
# Template Analyzer 参数
# =============================================================================

# cover 和 attachments 是逻辑结构区域，
# PDF 中不一定真的存在“封面”“附件内容”这些标题，
# 因此不参与模板类型识别。
IGNORED_SECTION_IDS = {
    "cover",
    "attachments",
}

# 只存在于一个模板中的章节锚点具有较强区分能力。
UNIQUE_ANCHOR_WEIGHT = 1.0

# 多个模板共有的章节标题只提供弱证据。
SHARED_ANCHOR_WEIGHT = 0.25

# 至少命中两个具有模板区分能力的章节，
# 才允许正式判定模板。
MIN_UNIQUE_ANCHOR_HITS = 2

# 区分性章节覆盖率过低时不强行判断模板。
MIN_DISTINCTIVE_COVERAGE = 0.25

# 第一候选与第二候选差距过小时，
# 返回 unknown。
MIN_TEMPLATE_MARGIN = 0.15

# semantic anchor 只允许搜索页面顶部前若干个非空文本行。
#
# 当前主要用于 Template B 的“可行性研究报告”标题页，
# 防止正文中偶然出现这些词导致误命中。
SEMANTIC_PAGE_TOP_LINES = 6


def round_number(
    value: float,
    digits: int = 4,
) -> float:
    return round(
        float(value),
        digits,
    )


def normalize_anchor_text(
    text: str,
) -> str:
    """
    对章节标题和页面文本做轻量标准化。

    例如：

        一、基本信息
        一 基本信息

    标准化后都成为：

        一基本信息

    当前只保留：
    - 中文字符
    - 字母
    - 数字

    不做语义纠错。
    """
    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    return "".join(
        char
        for char in text
        if (
            char.isalnum()
            or "\u4e00"
            <= char
            <= "\u9fff"
        )
    )


def get_section_anchors(
    section: dict[str, Any],
) -> list[dict[str, str]]:
    """
    获取普通章节标题锚点。

    优先读取 anchors。

    如果旧模板配置不存在 anchors，
    自动退回 title。

    对标准化后相同的 aliases 自动去重。
    """
    raw_anchors = section.get(
        "anchors"
    )

    if (
        isinstance(
            raw_anchors,
            list,
        )
        and raw_anchors
    ):
        source_anchors = raw_anchors

    else:
        source_anchors = [
            section.get(
                "title",
                "",
            )
        ]

    normalized_map: dict[
        str,
        str,
    ] = {}

    for anchor in source_anchors:
        anchor_text = str(
            anchor
        ).strip()

        normalized_anchor = (
            normalize_anchor_text(
                anchor_text
            )
        )

        if (
            normalized_anchor
            and normalized_anchor
            not in normalized_map
        ):
            normalized_map[
                normalized_anchor
            ] = anchor_text

    return [
        {
            "text":
                original_text,

            "normalized":
                normalized_text,
        }
        for (
            normalized_text,
            original_text,
        ) in normalized_map.items()
    ]


def get_section_semantic_anchors(
    section: dict[str, Any],
) -> list[dict[str, str]]:
    """
    获取章节的语义锚点。

    semantic anchor 与普通 explicit anchor 不同。

    当前主要用于 Template B：

        第七章 可行性分析报告

    真实 PDF 中可能没有：

        七、可行性分析报告

    而只出现：

        项目可行性研究报告

    这种情况下允许使用 semantic anchor。
    """
    raw_anchors = section.get(
        "semantic_anchors"
    )

    if not isinstance(
        raw_anchors,
        list,
    ):
        return []

    normalized_map: dict[
        str,
        str,
    ] = {}

    for anchor in raw_anchors:
        anchor_text = str(
            anchor
        ).strip()

        normalized_anchor = (
            normalize_anchor_text(
                anchor_text
            )
        )

        if (
            normalized_anchor
            and normalized_anchor
            not in normalized_map
        ):
            normalized_map[
                normalized_anchor
            ] = anchor_text

    result = [
        {
            "text":
                original_text,

            "normalized":
                normalized_text,
        }
        for (
            normalized_text,
            original_text,
        ) in normalized_map.items()
    ]

    # 优先匹配更长、更具体的 semantic anchor。
    #
    # 例如页面写的是：
    #
    #   项目可行性研究报告
    #
    # 它同时包含：
    #
    #   可行性研究报告
    #
    # 我们应该优先记录更具体的完整标题。
    result.sort(
        key=lambda item: len(
            item[
                "normalized"
            ]
        ),
        reverse=True,
    )

    return result


def load_template_config(
    template_path: Path,
) -> dict[str, Any]:
    """
    读取模板配置文件。
    """
    if not template_path.exists():
        raise FileNotFoundError(
            f"模板配置不存在: "
            f"{template_path}"
        )

    data = json.loads(
        template_path.read_text(
            encoding="utf-8"
        )
    )

    templates = data.get(
        "templates"
    )

    if not isinstance(
        templates,
        list,
    ) or not templates:
        raise ValueError(
            "templates.json 中没有有效 templates。"
        )

    return data



def load_profile_page_texts(
    profile_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
]:
    """
    从 Stage 1 Page Profile JSON 读取每页 native_text。

    Stage 2 不再打开 PDF。

    这样整条 fast path 中：
        PDF I/O 只发生在 Stage 1。
    """
    if not profile_path.exists():
        raise FileNotFoundError(
            f"Page Profile 不存在: "
            f"{profile_path}"
        )

    data = json.loads(
        profile_path.read_text(
            encoding="utf-8"
        )
    )

    raw_pages = data.get(
        "pages"
    )

    if not isinstance(
        raw_pages,
        list,
    ):
        raise ValueError(
            "Page Profile JSON 中没有有效 pages。"
        )

    pages: list[
        dict[str, Any]
    ] = []

    for raw_page in raw_pages:
        page_number = raw_page.get(
            "page_number"
        )

        if not isinstance(
            page_number,
            int,
        ):
            continue

        if "native_text" not in raw_page:
            raise ValueError(
                "当前 Page Profile 缺少 native_text。"
                "请使用新版 1_page_profiler.py "
                "重新生成单次扫描结果。"
            )

        text = str(
            raw_page.get(
                "native_text",
                "",
            )
            or ""
        )

        non_empty_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        top_text = "\n".join(
            non_empty_lines[
                :SEMANTIC_PAGE_TOP_LINES
            ]
        )

        pages.append(
            {
                "page_number":
                    page_number,

                "text":
                    text,

                "normalized_text":
                    normalize_anchor_text(
                        text
                    ),

                "top_text":
                    top_text,

                "normalized_top_text":
                    normalize_anchor_text(
                        top_text
                    ),
            }
        )

    pages.sort(
        key=lambda item: int(
            item[
                "page_number"
            ]
        )
    )

    return (
        data,
        pages,
    )


def build_anchor_frequency(
    templates: list[dict[str, Any]],
) -> Counter[str]:
    """
    统计普通 explicit anchor
    出现在多少个模板中。

    用于区分：

        unique anchor
        shared anchor

    semantic anchor 不参与模板间唯一性计算。

    原因是：

    semantic anchor 是某个已知特殊章节的 fallback，
    而不是通用模板识别标题。
    """
    frequency: Counter[str] = (
        Counter()
    )

    for template in templates:
        seen_in_template: set[
            str
        ] = set()

        for section in template.get(
            "sections",
            [],
        ):
            section_id = str(
                section.get(
                    "section_id",
                    "",
                )
            )

            if (
                section_id
                in IGNORED_SECTION_IDS
            ):
                continue

            anchors = (
                get_section_anchors(
                    section
                )
            )

            for anchor in anchors:
                seen_in_template.add(
                    anchor[
                        "normalized"
                    ]
                )

        for normalized_anchor in (
            seen_in_template
        ):
            frequency[
                normalized_anchor
            ] += 1

    return frequency


def find_anchor_pages(
    normalized_anchor: str,
    pages: list[dict[str, Any]],
) -> list[int]:
    """
    查找普通章节标题出现在哪些 PDF 物理页。

    当前采用：

        标准化后的完整标题
        in
        标准化后的整页 native text
    """
    if not normalized_anchor:
        return []

    return [
        int(
            page[
                "page_number"
            ]
        )
        for page in pages
        if (
            normalized_anchor
            in page[
                "normalized_text"
            ]
        )
    ]


def find_semantic_anchor_pages(
    normalized_anchor: str,
    pages: list[dict[str, Any]],
    match_scope: str,
) -> list[int]:
    """
    查找 semantic anchor。

    当前只支持：

        page_top

    即：

        只检查页面顶部前若干个非空文本行。

    这样可以避免正文中偶然提到：

        可行性研究报告

    时被错误认为章节入口。
    """
    if not normalized_anchor:
        return []

    if match_scope != "page_top":
        return []

    return [
        int(
            page[
                "page_number"
            ]
        )
        for page in pages
        if (
            normalized_anchor
            in page[
                "normalized_top_text"
            ]
        )
    ]


def score_template(
    template: dict[str, Any],
    pages: list[dict[str, Any]],
    anchor_frequency: Counter[str],
) -> dict[str, Any]:
    """
    对单个模板进行章节锚点匹配和评分。

    一个 section 可以拥有多个 aliases。

    但无论命中多少 aliases：

        一个 section 只能计算一次得分。

    普通 explicit anchor 优先。

    只有 explicit anchor 完全没有命中时，
    才允许使用 semantic anchor fallback。
    """
    matched_score = 0.0
    maximum_score = 0.0

    distinctive_score = 0.0
    distinctive_maximum = 0.0

    unique_anchor_hits = 0
    shared_anchor_hits = 0

    matched_sections: list[
        dict[str, Any]
    ] = []

    missed_sections: list[
        dict[str, Any]
    ] = []

    sections = template.get(
        "sections",
        [],
    )

    for section in sections:
        section_id = str(
            section.get(
                "section_id",
                "",
            )
        )

        if (
            section_id
            in IGNORED_SECTION_IDS
        ):
            continue

        title = str(
            section.get(
                "title",
                "",
            )
        )

        anchors = (
            get_section_anchors(
                section
            )
        )

        semantic_anchors = (
            get_section_semantic_anchors(
                section
            )
        )

        semantic_match_scope = str(
            section.get(
                "semantic_match_scope",
                "",
            )
        )

        if not anchors:
            continue

        # -------------------------------------------------------------
        # 判断该 section 是否具有模板区分能力
        # -------------------------------------------------------------

        is_unique = any(
            anchor_frequency[
                anchor[
                    "normalized"
                ]
            ]
            == 1
            for anchor in anchors
        )

        weight = (
            UNIQUE_ANCHOR_WEIGHT
            if is_unique
            else SHARED_ANCHOR_WEIGHT
        )

        maximum_score += (
            weight
        )

        if is_unique:
            distinctive_maximum += (
                weight
            )

        # -------------------------------------------------------------
        # 第一阶段：普通 explicit anchor
        # -------------------------------------------------------------

        matched_page_set: set[
            int
        ] = set()

        matched_anchors: list[
            dict[str, Any]
        ] = []

        for anchor in anchors:
            matched_pages = (
                find_anchor_pages(
                    normalized_anchor=
                        anchor[
                            "normalized"
                        ],
                    pages=pages,
                )
            )

            if not matched_pages:
                continue

            matched_page_set.update(
                matched_pages
            )

            matched_anchors.append(
                {
                    "anchor":
                        anchor[
                            "text"
                        ],

                    "normalized_anchor":
                        anchor[
                            "normalized"
                        ],

                    "pages":
                        matched_pages,

                    "anchor_type":
                        (
                            "unique"
                            if anchor_frequency[
                                anchor[
                                    "normalized"
                                ]
                            ]
                            == 1
                            else "shared"
                        ),

                    "match_mode":
                        "explicit_anchor",
                }
            )

        # -------------------------------------------------------------
        # 第二阶段：semantic anchor fallback
        # -------------------------------------------------------------
        #
        # 只有普通章节标题完全没有命中时，
        # 才启用语义标题。
        # -------------------------------------------------------------

        if (
            not matched_page_set
            and semantic_anchors
        ):
            for anchor in semantic_anchors:
                semantic_pages = (
                    find_semantic_anchor_pages(
                        normalized_anchor=
                            anchor[
                                "normalized"
                            ],
                        pages=pages,
                        match_scope=
                            semantic_match_scope,
                    )
                )

                if not semantic_pages:
                    continue

                matched_page_set.update(
                    semantic_pages
                )

                matched_anchors.append(
                    {
                        "anchor":
                            anchor[
                                "text"
                            ],

                        "normalized_anchor":
                            anchor[
                                "normalized"
                            ],

                        "pages":
                            semantic_pages,

                        "anchor_type":
                            "semantic",

                        "match_mode":
                            "semantic_anchor",

                        "match_scope":
                            semantic_match_scope,
                    }
                )

                # semantic anchors 已按长度从长到短排序。
                #
                # 找到第一个最具体的标题以后立即停止，
                # 防止：
                #
                #   项目可行性研究报告
                #
                # 同时又被：
                #
                #   可行性研究报告
                #
                # 重复记录。
                break

        matched_pages = sorted(
            matched_page_set
        )

        # -------------------------------------------------------------
        # section 命中
        # -------------------------------------------------------------

        if matched_pages:
            matched_score += (
                weight
            )

            if is_unique:
                distinctive_score += (
                    weight
                )

                unique_anchor_hits += 1

            else:
                shared_anchor_hits += 1

            match_mode = (
                "semantic_anchor"
                if any(
                    item.get(
                        "match_mode"
                    )
                    == "semantic_anchor"
                    for item in matched_anchors
                )
                else "explicit_anchor"
            )

            matched_sections.append(
                {
                    "section_id":
                        section_id,

                    "title":
                        title,

                    "zone_type":
                        section.get(
                            "zone_type"
                        ),

                    "order":
                        section.get(
                            "order"
                        ),

                    # 当前只是标题首次匹配位置。
                    #
                    # v0.1.2 还不能直接把它解释为
                    # 最终章节 start_page。
                    "first_match_page":
                        matched_pages[0],

                    "all_match_pages":
                        matched_pages,

                    "anchor_type":
                        (
                            "unique"
                            if is_unique
                            else "shared"
                        ),

                    "match_mode":
                        match_mode,

                    "weight":
                        weight,

                    "matched_anchors":
                        matched_anchors,
                }
            )

        # -------------------------------------------------------------
        # section 未命中
        # -------------------------------------------------------------

        else:
            missed_sections.append(
                {
                    "section_id":
                        section_id,

                    "title":
                        title,

                    "zone_type":
                        section.get(
                            "zone_type"
                        ),

                    "order":
                        section.get(
                            "order"
                        ),

                    "anchor_type":
                        (
                            "unique"
                            if is_unique
                            else "shared"
                        ),

                    "weight":
                        weight,

                    "anchors": [
                        anchor[
                            "text"
                        ]
                        for anchor in anchors
                    ],

                    "semantic_anchors": [
                        anchor[
                            "text"
                        ]
                        for anchor in semantic_anchors
                    ],

                    "semantic_match_scope":
                        semantic_match_scope,
                }
            )

    coverage = (
        matched_score
        / maximum_score
        if maximum_score > 0
        else 0.0
    )

    distinctive_coverage = (
        distinctive_score
        / distinctive_maximum
        if distinctive_maximum > 0
        else 0.0
    )

    return {
        "template_id":
            template.get(
                "template_id"
            ),

        "template_name":
            template.get(
                "template_name"
            ),

        "score":
            round_number(
                matched_score
            ),

        "max_score":
            round_number(
                maximum_score
            ),

        "coverage":
            round_number(
                coverage
            ),

        "distinctive_coverage":
            round_number(
                distinctive_coverage
            ),

        "unique_anchor_hits":
            unique_anchor_hits,

        "shared_anchor_hits":
            shared_anchor_hits,

        "matched_section_count":
            len(
                matched_sections
            ),

        "matched_sections":
            matched_sections,

        "missed_sections":
            missed_sections,
    }


def detect_template(
    templates: list[dict[str, Any]],
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    对所有模板评分，然后选择最佳候选。

    template_confidence 是启发式分数，
    不是统计意义上的概率。
    """
    anchor_frequency = (
        build_anchor_frequency(
            templates
        )
    )

    candidates = [
        score_template(
            template=template,
            pages=pages,
            anchor_frequency=
                anchor_frequency,
        )
        for template in templates
    ]

    candidates.sort(
        key=lambda item: (
            item[
                "distinctive_coverage"
            ],
            item[
                "coverage"
            ],
            item[
                "unique_anchor_hits"
            ],
        ),
        reverse=True,
    )

    best = candidates[0]

    if len(
        candidates
    ) >= 2:
        second = candidates[1]

        margin = (
            float(
                best[
                    "distinctive_coverage"
                ]
            )
            -
            float(
                second[
                    "distinctive_coverage"
                ]
            )
        )

    else:
        margin = float(
            best[
                "distinctive_coverage"
            ]
        )

    margin = max(
        0.0,
        margin,
    )

    confidence = (
        0.70
        * float(
            best[
                "distinctive_coverage"
            ]
        )
        +
        0.30
        * float(
            best[
                "coverage"
            ]
        )
    )

    is_confident_match = (
        best[
            "unique_anchor_hits"
        ]
        >= MIN_UNIQUE_ANCHOR_HITS

        and float(
            best[
                "distinctive_coverage"
            ]
        )
        >= MIN_DISTINCTIVE_COVERAGE

        and margin
        >= MIN_TEMPLATE_MARGIN
    )

    if is_confident_match:
        template_id = (
            best[
                "template_id"
            ]
        )

        template_name = (
            best[
                "template_name"
            ]
        )

        decision = (
            "matched"
        )

    else:
        template_id = (
            "unknown"
        )

        template_name = (
            "未确定模板"
        )

        decision = (
            "unknown"
        )

    return {
        "decision":
            decision,

        "template_id":
            template_id,

        "template_name":
            template_name,

        "template_confidence":
            round_number(
                confidence
            ),

        "template_margin":
            round_number(
                margin
            ),

        "best_candidate":
            best[
                "template_id"
            ],

        "best_candidate_name":
            best[
                "template_name"
            ],

        "candidates":
            candidates,
    }



def analyze_profile(
    profile_path: Path,
    template_path: Path,
) -> dict[str, Any]:
    """
    执行 Template Analyzer v0.2.0。

    与 v0.1.2 相比：
        模板评分逻辑不变；
        输入从 PDF 改为 Stage 1 Page Profile JSON。
    """
    config = (
        load_template_config(
            template_path
        )
    )

    templates = config[
        "templates"
    ]

    (
        profile_data,
        pages,
    ) = (
        load_profile_page_texts(
            profile_path
        )
    )

    detection = (
        detect_template(
            templates=templates,
            pages=pages,
        )
    )

    return {
        "analyzer_version":
            "0.2.0",

        "template_schema_version":
            config.get(
                "schema_version"
            ),

        "source_file":
            profile_data.get(
                "source_file",
                profile_path.name,
            ),

        "source_profiler_version":
            profile_data.get(
                "profiler_version"
            ),

        "source_page_scan_version":
            profile_data.get(
                "page_scan_version"
            ),

        "page_count":
            len(
                pages
            ),

        **detection,
    }


def print_summary(
    result: dict[str, Any],
) -> None:
    """
    中文终端摘要。
    """
    print()

    print(
        "=" * 110
    )

    print(
        f"模板结构分析器 | "
        f"{result['source_file']} "
        f"| 页数="
        f"{result['page_count']} "
        f"| 版本="
        f"{result['analyzer_version']}"
    )

    print(
        "=" * 110
    )

    if (
        result[
            "decision"
        ]
        == "matched"
    ):
        print(
            f"模板判定："
            f"{result['template_id']} "
            f"({result['template_name']})"
        )

    else:
        print(
            "模板判定：unknown"
        )

        print(
            f"最佳候选："
            f"{result['best_candidate']} "
            f"({result['best_candidate_name']})"
        )

    print(
        f"启发式置信度："
        f"{result['template_confidence']:.3f}"
    )

    print(
        f"候选差距："
        f"{result['template_margin']:.3f}"
    )

    print()

    print(
        "候选模板评分："
    )

    for candidate in result[
        "candidates"
    ]:
        print(
            f"  "
            f"{candidate['template_id']:<12} "
            f"覆盖率="
            f"{candidate['coverage']:.3f} "
            f"区分锚点覆盖="
            f"{candidate['distinctive_coverage']:.3f} "
            f"唯一锚点命中="
            f"{candidate['unique_anchor_hits']} "
            f"公共锚点命中="
            f"{candidate['shared_anchor_hits']}"
        )

    print()

    best = result[
        "candidates"
    ][0]

    print(
        f"最佳候选 "
        f"{best['template_id']} "
        f"命中的章节锚点："
    )

    if not best[
        "matched_sections"
    ]:
        print(
            "  未找到章节标题锚点。"
        )

    else:
        for section in best[
            "matched_sections"
        ]:
            matched_anchor_texts = (
                " / ".join(
                    item[
                        "anchor"
                    ]
                    for item in section.get(
                        "matched_anchors",
                        [],
                    )
                )
            )

            match_mode_display = {
                "explicit_anchor":
                    "显式标题",

                "semantic_anchor":
                    "语义标题",
            }.get(
                section.get(
                    "match_mode"
                ),
                "未知",
            )

            print(
                f"  PDF第"
                f"{section['first_match_page']:>3}页 | "
                f"{section['anchor_type']:<6} | "
                f"{section['title']} "
                f"| 方式="
                f"{match_mode_display} "
                f"| 实际命中="
                f"{matched_anchor_texts}"
            )

    print(
        "=" * 110
    )


def run_template_analysis(
    *,
    profile_path: Path,
    template_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Run Stage 2 through the package API while preserving its artifact format."""
    result = analyze_profile(
        profile_path=Path(profile_path),
        template_path=Path(template_path),
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


