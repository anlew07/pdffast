from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


# =============================================================================
# Section Aligner v0.2.5
# =============================================================================
#
# 目标：
#
# Template Analyzer
#       ↓
# ┌───────────────────────────────┐
# │ matched                       │
# │ → template_aware              │
# ├───────────────────────────────┤
# │ unknown，但存在可靠章节锚点   │
# │ → template_assisted           │
# ├───────────────────────────────┤
# │ unknown，章节证据也不足       │
# │ → generic                     │
# └───────────────────────────────┘
#
# 原则：
#
# 1. 模板是增强能力，不是解析前置条件。
# 2. 未知模板也允许利用真实观察到的相似章节。
# 3. template_assisted 不允许强行补完整 A/B 模板。
# 4. generic 不使用任何模板章节推断。
# 5. 不解析 PDF，不做 OCR。
#
# =============================================================================


# -----------------------------------------------------------------------------
# template_assisted 最低证据要求
# -----------------------------------------------------------------------------
#
# unknown PDF 至少满足：
#
#   - 真实识别到 3 个章节
#   - 其中至少 2 个具有模板区分能力
#   - 至少分布在 3 个不同 PDF 页面
#
# 才启用 template_assisted。
#
# 只有“附件清单 + 诚信承诺书 + 审核意见”这种
# shared anchors，不足以启用模板辅助模式。
# -----------------------------------------------------------------------------

ASSISTED_MIN_SECTION_HITS = 3

ASSISTED_MIN_DISTINCTIVE_HITS = 2

ASSISTED_MIN_DISTINCT_PAGES = 3

# =============================================================================
# Anchor Sequence Validation
# =============================================================================

# 如果同一 PDF 页面同时命中了 3 个及以上不同章节，
# 该页高度疑似：
#
#   - 目录
#   - 章节索引
#   - 附件中的目录页
#
# 这种页面不参与“真正章节入口”的选择。
#
# 注意：
# 这里只影响 Section Alignment，
# 不影响 Template Analyzer 的模板身份判断。
ANCHOR_CROWDING_HARD_THRESHOLD = 3

def load_json(
    path: Path,
) -> dict[str, Any]:
    """
    读取 JSON 文件。
    """
    if not path.exists():
        raise FileNotFoundError(
            f"文件不存在: {path}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def load_snapshot_pages(
    path: Path | None,
) -> dict[int, dict[str, Any]]:
    """读取 Stage1 page_snapshot.jsonl；未提供时返回空映射。"""
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    pages: dict[int, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or item.get("record_type") != "page":
            continue
        try:
            page_number = int(item["page_number"])
        except (KeyError, TypeError, ValueError):
            continue
        pages[page_number] = item
    return pages


def normalize_heading_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(
        ch for ch in text
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"
    )


_CN_NUM = "一二三四五六七八九十百零〇"
_TOP_LEVEL_PATTERNS = [
    re.compile(rf"^\s*([{_CN_NUM}]+)\s*[、．.]\s*(\S.*?)\s*$"),
    re.compile(rf"^\s*第([{_CN_NUM}]+)章\s*(\S.*?)\s*$"),
]
_PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


def _parse_cn_ordinal(token: str) -> int | None:
    """解析常见中文章节序号（1~999）；无法可靠解析时返回 None。"""
    token = unicodedata.normalize("NFKC", str(token or "")).strip().replace("〇", "零")
    if not token:
        return None
    digit = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    unit = {"十": 10, "百": 100}
    total = 0
    current = 0
    saw = False
    for ch in token:
        if ch in digit:
            current = digit[ch]
            saw = True
        elif ch in unit:
            saw = True
            value = current if current > 0 else 1
            total += value * unit[ch]
            current = 0
        else:
            return None
    if not saw:
        return None
    total += current
    return total if total > 0 else None


def heading_ordinal(text: str) -> int | None:
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    for pattern in _TOP_LEVEL_PATTERNS:
        match = pattern.match(value)
        if match:
            return _parse_cn_ordinal(match.group(1))
    return None


def _select_coherent_heading_sequence(
    observed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    从 native 一级标题候选中选择一个页序与章节序号都严格递增的最长链。

    目的不是猜模板，而是避免表格中的 "一、直接费用"、"二、间接费用"
    之类内部编号被误提升为文档级章节。候选本身仍来自 PDF 原生文本。
    """
    if len(observed) <= 1:
        return observed

    enriched: list[dict[str, Any]] = []
    for item in observed:
        ordinal = heading_ordinal(str(item.get("heading") or ""))
        if ordinal is None:
            continue
        copy = dict(item)
        copy["ordinal"] = ordinal
        enriched.append(copy)

    if len(enriched) <= 1:
        return enriched or observed

    # DP: 最大化候选数量；长度相同时优先模板精确命中更多、结束序号更大。
    best_len = [1] * len(enriched)
    best_match = [1 if isinstance(x.get("matched"), dict) else 0 for x in enriched]
    prev = [-1] * len(enriched)

    for i in range(len(enriched)):
        for j in range(i):
            if int(enriched[j]["page_number"]) >= int(enriched[i]["page_number"]):
                continue
            if int(enriched[j]["ordinal"]) >= int(enriched[i]["ordinal"]):
                continue
            cand_len = best_len[j] + 1
            cand_match = best_match[j] + (1 if isinstance(enriched[i].get("matched"), dict) else 0)
            if (cand_len, cand_match) > (best_len[i], best_match[i]):
                best_len[i] = cand_len
                best_match[i] = cand_match
                prev[i] = j

    end = max(
        range(len(enriched)),
        key=lambda i: (best_len[i], best_match[i], int(enriched[i]["ordinal"]), -int(enriched[i]["page_number"])),
    )
    chain: list[dict[str, Any]] = []
    while end >= 0:
        chain.append(enriched[end])
        end = prev[end]
    chain.reverse()
    return chain


def normalize_heading_display(text: str) -> str:
    """只清理章节前缀附近的排版空白，不改标题正文语义。"""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    value = re.sub(rf"^([{_CN_NUM}]+)\s*[、．.]\s*", r"\1、", value)
    value = re.sub(rf"^(第[{_CN_NUM}]+章)\s*", r"\1 ", value)
    return value.strip()


def strip_heading_prefix(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    value = re.sub(rf"^第[{_CN_NUM}]+章\s*", "", value)
    value = re.sub(rf"^[{_CN_NUM}]+\s*[、．.]\s*", "", value)
    return normalize_heading_text(value)


def observed_top_level_heading(raw_page: dict[str, Any]) -> str | None:
    """
    从 Stage1 原生文本中只识别明确的中文一级标题。
    不识别 1./1.1 等正文内部编号，避免把段落标题升级为章节。
    """
    native_text = str(raw_page.get("native_text") or "")
    candidates: list[str] = []
    for line in native_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _PAGE_NUMBER_RE.match(line):
            continue
        candidates.append(line)
        if len(candidates) >= 8:
            break

    for line in candidates:
        if len(line) > 60:
            continue
        if any(pattern.match(line) for pattern in _TOP_LEVEL_PATTERNS):
            return normalize_heading_display(line)
    return None


def match_observed_heading_to_template(
    heading: str,
    template_config: dict[str, Any],
) -> dict[str, Any] | None:
    """
    用“去掉章节序号后的标题正文”与已注册 title/anchors 做严格匹配。
    只做文本等价，不做模糊语义猜测。
    """
    target = strip_heading_prefix(heading)
    if not target:
        return None

    matches: list[dict[str, Any]] = []
    for template in template_config.get("templates", []):
        template_id = str(template.get("template_id") or "")
        for section in template.get("sections", []):
            aliases = []
            title = str(section.get("title") or "").strip()
            if title:
                aliases.append(title)
            raw_anchors = section.get("anchors")
            if isinstance(raw_anchors, list):
                aliases.extend(str(v).strip() for v in raw_anchors if str(v).strip())

            if any(strip_heading_prefix(alias) == target for alias in aliases):
                matches.append({
                    "template_id": template_id,
                    "section_id": section.get("section_id"),
                    "canonical_title": section.get("title"),
                    "zone_type": section.get("zone_type"),
                })

    unique = {
        (str(item.get("section_id")), str(item.get("canonical_title"))): item
        for item in matches
    }
    if len(unique) == 1:
        return next(iter(unique.values()))
    return None


def build_observed_generic_sections(
    page_count: int,
    snapshot_pages: dict[int, dict[str, Any]],
    template_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    unknown 模板下，从真实 native heading 构建章节。
    已注册标题优先获得 canonical section_id；未匹配标题保留原文。
    不从模板补写不存在的章节。
    """
    observed: list[dict[str, Any]] = []
    for page_number in range(1, page_count + 1):
        page = snapshot_pages.get(page_number)
        if not isinstance(page, dict):
            continue
        heading = observed_top_level_heading(page)
        if not heading:
            continue
        matched = match_observed_heading_to_template(heading, template_config)
        observed.append({
            "page_number": page_number,
            "heading": heading,
            "matched": matched,
        })

    # Generic 模式只保留一个文档级、序号严格递增的一级章节链。
    # 这样表格内部的 "一、直接费用" 等编号不会切断真实章节。
    observed = _select_coherent_heading_sequence(observed)

    if not observed:
        return [], [{
            "region_type": "generic_region",
            "start_page": 1,
            "end_page": page_count,
            "reason": "没有足够可靠的模板或原生一级标题证据。",
        }]

    sections: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    first_page = int(observed[0]["page_number"])
    if first_page > 1:
        sections.append({
            "section_id": "generic_front_matter",
            "title": "封面",
            "canonical_title": None,
            "zone_type": None,
            "order": None,
            "start_page": 1,
            "end_page": first_page - 1,
            "anchor_page": 1,
            "boundary_source": "before_first_observed_heading",
            "boundary_confidence": "medium",
            "match_mode": "generic_front_matter",
            "structure_evidence": "position_before_first_observed_heading",
            "candidate_sources": [],
            "is_distinctive": False,
        })

    for index, item in enumerate(observed):
        start_page = int(item["page_number"])
        end_page = (
            int(observed[index + 1]["page_number"]) - 1
            if index + 1 < len(observed)
            else page_count
        )
        matched = item.get("matched") if isinstance(item.get("matched"), dict) else None
        section_id = (
            matched.get("section_id")
            if matched and matched.get("section_id")
            else f"generic_section_{index + 1:03d}"
        )
        sections.append({
            "section_id": section_id,
            "title": item["heading"],
            "canonical_title": matched.get("canonical_title") if matched else None,
            "zone_type": matched.get("zone_type") if matched else None,
            "order": None,
            "start_page": start_page,
            "end_page": max(start_page, end_page),
            "anchor_page": start_page,
            "boundary_source": "next_observed_native_heading_minus_one" if index + 1 < len(observed) else "document_end",
            "boundary_confidence": "high",
            "match_mode": "registered_heading_exact" if matched else "generic_native_heading",
            "structure_evidence": "observed_native_top_level_heading",
            "candidate_sources": [matched.get("template_id")] if matched else [],
            "is_distinctive": bool(matched),
        })

    return sections, unresolved


def load_template_config(
    path: Path,
) -> dict[str, Any]:
    """
    读取 templates.json。
    """
    config = load_json(
        path
    )

    templates = config.get(
        "templates"
    )

    if not isinstance(
        templates,
        list,
    ) or not templates:
        raise ValueError(
            "templates.json 中没有有效 templates。"
        )

    return config


def find_template_definition(
    config: dict[str, Any],
    template_id: str,
) -> dict[str, Any]:
    """
    根据 template_id 找到模板定义。
    """
    for template in config.get(
        "templates",
        [],
    ):
        if (
            template.get(
                "template_id"
            )
            == template_id
        ):
            return template

    raise ValueError(
        f"未找到模板定义: "
        f"{template_id}"
    )


def get_candidate_by_id(
    analyzer_result: dict[str, Any],
    template_id: str,
) -> dict[str, Any] | None:
    """
    从 Template Analyzer candidates 中
    找到指定 template_id。
    """
    for candidate in analyzer_result.get(
        "candidates",
        [],
    ):
        if (
            candidate.get(
                "template_id"
            )
            == template_id
        ):
            return candidate

    return None


def get_best_candidate(
    analyzer_result: dict[str, Any],
) -> dict[str, Any] | None:
    """
    获取 Template Analyzer 的最佳候选。
    """
    best_candidate_id = (
        analyzer_result.get(
            "best_candidate"
        )
    )

    if best_candidate_id:
        candidate = (
            get_candidate_by_id(
                analyzer_result,
                str(
                    best_candidate_id
                ),
            )
        )

        if candidate is not None:
            return candidate

    candidates = (
        analyzer_result.get(
            "candidates",
            [],
        )
    )

    if candidates:
        return candidates[0]

    return None


def build_template_section_map(
    template: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    """
    根据 order 建立模板章节映射。
    """
    result: dict[
        int,
        dict[str, Any],
    ] = {}

    for section in template.get(
        "sections",
        [],
    ):
        order = section.get(
            "order"
        )

        if not isinstance(
            order,
            int,
        ):
            continue

        result[
            order
        ] = section

    return result


def get_section_candidate_pages(
    section: dict[str, Any],
) -> list[int]:
    """
    获取章节所有可能的标题页。

    优先使用 Template Analyzer 输出的：

        all_match_pages

    如果旧结果没有该字段，
    自动退回：

        first_match_page

    这样兼容之前已经生成的 JSON。
    """
    raw_pages = section.get(
        "all_match_pages"
    )

    pages: list[int] = []

    if isinstance(
        raw_pages,
        list,
    ):
        for value in raw_pages:
            if (
                isinstance(
                    value,
                    int,
                )
                and value > 0
            ):
                pages.append(
                    value
                )

    if not pages:
        first_page = section.get(
            "first_match_page"
        )

        if (
            isinstance(
                first_page,
                int,
            )
            and first_page > 0
        ):
            pages.append(
                first_page
            )

    return sorted(
        set(
            pages
        )
    )


def build_anchor_page_density(
    sections: list[dict[str, Any]],
) -> dict[int, int]:
    """
    统计每个 PDF 页面同时命中了多少个不同章节。

    例如目录页可能同时出现：

        一、基本信息
        二、项目负责人基本情况
        三、拟开展研究内容
        四、研究条件

    那么这个页面的 anchor density 会非常高。

    正常正文的章节入口通常只有一个章节标题。
    """
    page_sections: defaultdict[
        int,
        set[str],
    ] = defaultdict(
        set
    )

    for section in sections:
        section_id = str(
            section.get(
                "section_id",
                "",
            )
        )

        order = section.get(
            "order"
        )

        section_key = (
            f"{order}:"
            f"{section_id}"
        )

        for page in (
            get_section_candidate_pages(
                section
            )
        ):
            page_sections[
                page
            ].add(
                section_key
            )

    return {
        page:
            len(
                section_keys
            )

        for (
            page,
            section_keys,
        ) in page_sections.items()
    }


def anchor_chain_rank(
    state: dict[str, Any],
) -> tuple[
    int,
    int,
    int,
    int,
    int,
]:
    """
    对一条章节锚点链评分。

    优先级：

    1. 命中的章节数量越多越好
    2. 页面锚点拥挤程度越低越好
    3. 更靠前的完整章节链优先
    4. 更早结束的链优先
    5. 总页码更小的链优先

    第 3 条能够避免：

        正文有一套完整章节
        +
        后面附件又嵌入了一份完整申请书

    时错误选择附件中的第二套章节。
    """
    pages = state[
        "pages"
    ]

    if not pages:
        return (
            0,
            0,
            0,
            0,
            0,
        )

    return (
        len(
            pages
        ),

        -int(
            state[
                "crowding_penalty"
            ]
        ),

        -int(
            pages[0]
        ),

        -int(
            pages[-1]
        ),

        -sum(
            int(
                page
            )
            for page in pages
        ),
    )


def resolve_anchor_sequence(
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    从 all_match_pages 中选择真正的主章节锚点链。

    目标是解决：

        目录重复章节标题
        附件嵌入另一份申请书
        页眉/重复标题

    核心约束：

        section order 必须递增
        PDF page 必须严格递增

    例如：

        第一章：[1, 2, 65]
        第二章：[1, 3, 66]
        第三章：[1, 8, 70]
        第四章：[1, 9, 71]

    PDF第1页同时出现大量章节，
    会被识别为 crowded page。

    最终优先选择：

        2 → 3 → 8 → 9

    而不是：

        1 → 1 → 1 → 1

    也不会优先选择：

        65 → 66 → 70 → 71
    """
    raw_sections: list[
        dict[str, Any]
    ] = []

    for section in candidate.get(
        "matched_sections",
        [],
    ):
        order = section.get(
            "order"
        )

        if not isinstance(
            order,
            int,
        ):
            continue

        candidate_pages = (
            get_section_candidate_pages(
                section
            )
        )

        if not candidate_pages:
            continue

        raw_sections.append(
            {
                **section,

                "_candidate_pages":
                    candidate_pages,
            }
        )

    raw_sections.sort(
        key=lambda item: int(
            item[
                "order"
            ]
        )
    )

    if not raw_sections:
        return []

    page_density = (
        build_anchor_page_density(
            raw_sections
        )
    )

    # -------------------------------------------------------------------------
    # DAG / 动态规划
    # -------------------------------------------------------------------------
    #
    # 每一个：
    #
    #   section + candidate_page
    #
    # 都视为一个节点。
    #
    # 只有：
    #
    #   前一个 section order 更小
    #   前一个 page 更小
    #
    # 才能连接。
    # -------------------------------------------------------------------------

    states: list[
        dict[str, Any]
    ] = []

    for section_index, section in enumerate(
        raw_sections
    ):
        candidate_pages = section[
            "_candidate_pages"
        ]

        # 目录等高度拥挤页面不参与主章节链。
        usable_pages = [
            page
            for page in candidate_pages
            if page_density.get(
                page,
                0,
            )
            < ANCHOR_CROWDING_HARD_THRESHOLD
        ]

        # 如果这一章节只有 crowded page，
        # 当前结构阶段宁可暂时放弃该章节，
        # 也不把目录页当成正文入口。
        if not usable_pages:
            continue

        for page in usable_pages:
            current_penalty = max(
                0,
                page_density.get(
                    page,
                    1,
                )
                - 1,
            )

            best_state: dict[
                str,
                Any,
            ] = {
                "section_indices":
                    [
                        section_index
                    ],

                "pages":
                    [
                        page
                    ],

                "crowding_penalty":
                    current_penalty,

                "last_page":
                    page,

                "section_index":
                    section_index,
            }

            # 尝试从之前的章节链延伸到当前节点。
            for previous in states:
                previous_section_index = int(
                    previous[
                        "section_index"
                    ]
                )

                previous_page = int(
                    previous[
                        "last_page"
                    ]
                )

                if (
                    previous_section_index
                    >= section_index
                ):
                    continue

                if (
                    previous_page
                    >= page
                ):
                    continue

                new_state = {
                    "section_indices":
                        (
                            previous[
                                "section_indices"
                            ]
                            +
                            [
                                section_index
                            ]
                        ),

                    "pages":
                        (
                            previous[
                                "pages"
                            ]
                            +
                            [
                                page
                            ]
                        ),

                    "crowding_penalty":
                        (
                            int(
                                previous[
                                    "crowding_penalty"
                                ]
                            )
                            +
                            current_penalty
                        ),

                    "last_page":
                        page,

                    "section_index":
                        section_index,
                }

                if (
                    anchor_chain_rank(
                        new_state
                    )
                    >
                    anchor_chain_rank(
                        best_state
                    )
                ):
                    best_state = (
                        new_state
                    )

            states.append(
                best_state
            )

    if not states:
        return []

    best_chain = max(
        states,
        key=anchor_chain_rank,
    )

    selected_pages = {
        section_index:
            page

        for (
            section_index,
            page,
        ) in zip(
            best_chain[
                "section_indices"
            ],
            best_chain[
                "pages"
            ],
        )
    }

    resolved_sections: list[
        dict[str, Any]
    ] = []

    for section_index, page in (
        selected_pages.items()
    ):
        section = (
            raw_sections[
                section_index
            ]
        )

        candidate_pages = section[
            "_candidate_pages"
        ]

        crowded_pages = [
            candidate_page
            for candidate_page
            in candidate_pages
            if page_density.get(
                candidate_page,
                0,
            )
            >= ANCHOR_CROWDING_HARD_THRESHOLD
        ]

        resolved_section = {
            key:
                value

            for (
                key,
                value,
            ) in section.items()

            if key
            != "_candidate_pages"
        }

        resolved_section.update(
            {
                # 真正供 Section Alignment 使用的锚点页。
                "anchor_page":
                    page,

                # 保留所有原始候选，方便后续审计。
                "anchor_candidates":
                    candidate_pages,

                "crowding_filtered_pages":
                    crowded_pages,

                "anchor_selection_source":
                    "ordered_sequence_validation",
            }
        )

        resolved_sections.append(
            resolved_section
        )

    resolved_sections.sort(
        key=lambda item: (
            int(
                item[
                    "order"
                ]
            ),
            int(
                item[
                    "anchor_page"
                ]
            ),
        )
    )

    return resolved_sections


def normalize_matched_sections(
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Section Aligner 不再直接使用：

        first_match_page

    而是统一经过：

        Anchor Sequence Validation

    从 all_match_pages 中选择有序正文锚点。
    """
    return resolve_anchor_sequence(
        candidate
    )

# =============================================================================
# template_aware
# =============================================================================


def build_template_aware_ranges(
    page_count: int,
    template: dict[str, Any],
    matched_sections: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    已确定模板时，根据：

        模板 order
        +
        实际章节 anchor

    建立完整章节范围。

    可以使用模板先验：

        - 推断封面
        - 连续章节 next_anchor - 1
        - 检测中间缺失章节
        - 推断尾部 attachments/free
    """
    section_ranges: list[
        dict[str, Any]
    ] = []

    unresolved_regions: list[
        dict[str, Any]
    ] = []

    template_section_map = (
        build_template_section_map(
            template
        )
    )

    if not matched_sections:
        unresolved_regions.append(
            {
                "region_type":
                    "template_unresolved_region",

                "start_page":
                    1,

                "end_page":
                    page_count,

                "reason":
                    (
                        "模板已识别，"
                        "但没有可用于章节对齐的标题锚点。"
                    ),
            }
        )

        return (
            section_ranges,
            unresolved_regions,
        )

    # -------------------------------------------------------------------------
    # 封面 / 前置区域
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # 封面 / 前置材料
    # -------------------------------------------------------------------------
    #
    # 只把 PDF 第1页作为模板推断封面。
    #
    # 如果第一个可靠章节锚点不是第2页，
    # 那么第2页到第一章节之前的页面不再强行叫“封面”，
    # 而是保守标记为 front_matter_region。
    #
    # 可能包括：
    #
    #   - 目录
    #   - 填报说明
    #   - 前言
    #   - 使用说明
    #   - 其他前置材料
    # -------------------------------------------------------------------------

    first_anchor_page = int(
        matched_sections[
            0
        ][
            "anchor_page"
        ]
    )

    if first_anchor_page > 1:
        cover_definition = (
            template_section_map.get(
                0
            )
        )

        # -------------------------------------------------------------
        # PDF 第1页：封面
        # -------------------------------------------------------------

        section_ranges.append(
            {
                "section_id":
                    (
                        cover_definition.get(
                            "section_id"
                        )
                        if cover_definition
                        else "cover"
                    ),

                "title":
                    (
                        cover_definition.get(
                            "title"
                        )
                        if cover_definition
                        else "封面"
                    ),

                "zone_type":
                    (
                        cover_definition.get(
                            "zone_type"
                        )
                        if cover_definition
                        else "strong_template"
                    ),

                "order":
                    0,

                "start_page":
                    1,

                "end_page":
                    1,

                "boundary_source":
                    "first_page_cover_inference",

                "boundary_confidence":
                    "medium",

                "match_mode":
                    "inferred",
            }
        )

        # -------------------------------------------------------------
        # PDF 第2页 ～ 第一章节前一页：
        # front matter
        # -------------------------------------------------------------

        front_matter_start = 2

        front_matter_end = (
                first_anchor_page
                - 1
        )

        if (
                front_matter_start
                <= front_matter_end
        ):
            unresolved_regions.append(
                {
                    "region_type":
                        "front_matter_region",

                    "start_page":
                        front_matter_start,

                    "end_page":
                        front_matter_end,

                    "reason":
                        (
                            "位于封面之后、"
                            "第一个可靠章节锚点之前；"
                            "可能为目录、填报说明"
                            "或其他前置材料，"
                            "当前版本不强行分类。"
                        ),
                }
            )

    # -------------------------------------------------------------------------
    # 已匹配章节
    # -------------------------------------------------------------------------

    for index, current in enumerate(
        matched_sections
    ):
        current_page = int(
            current[
                "anchor_page"
            ]
        )

        current_order = int(
            current[
                "order"
            ]
        )

        # ---------------------------------------------------------------------
        # 不是最后一个标题
        # ---------------------------------------------------------------------

        if (
            index
            < len(
                matched_sections
            )
            - 1
        ):
            next_section = (
                matched_sections[
                    index + 1
                ]
            )

            next_page = int(
                next_section[
                    "anchor_page"
                ]
            )

            next_order = int(
                next_section[
                    "order"
                ]
            )

            order_gap = (
                next_order
                - current_order
            )

            # -----------------------------------------------------------------
            # 模板章节连续
            # -----------------------------------------------------------------

            if (
                order_gap == 1
                and next_page
                > current_page
            ):
                section_ranges.append(
                    {
                        "section_id":
                            current.get(
                                "section_id"
                            ),

                        "title":
                            current.get(
                                "title"
                            ),

                        "zone_type":
                            current.get(
                                "zone_type"
                            ),

                        "order":
                            current_order,

                        "start_page":
                            current_page,

                        "end_page":
                            next_page
                            - 1,

                        "boundary_source":
                            "next_anchor_minus_one",

                        "boundary_confidence":
                            "high",

                        "match_mode":
                            current.get(
                                "match_mode"
                            ),

                        "anchor_page":
                            current_page,
                    }
                )

            # -----------------------------------------------------------------
            # 模板顺序中间缺章节
            # -----------------------------------------------------------------

            elif (
                order_gap > 1
                and next_page
                > current_page
            ):
                # 当前章节只确认 anchor 页。
                section_ranges.append(
                    {
                        "section_id":
                            current.get(
                                "section_id"
                            ),

                        "title":
                            current.get(
                                "title"
                            ),

                        "zone_type":
                            current.get(
                                "zone_type"
                            ),

                        "order":
                            current_order,

                        "start_page":
                            current_page,

                        "end_page":
                            current_page,

                        "boundary_source":
                            (
                                "anchor_only_due_to_"
                                "missing_section"
                            ),

                        "boundary_confidence":
                            "low",

                        "match_mode":
                            current.get(
                                "match_mode"
                            ),

                        "anchor_page":
                            current_page,
                    }
                )

                unresolved_start = (
                    current_page
                    + 1
                )

                unresolved_end = (
                    next_page
                    - 1
                )

                if (
                    unresolved_start
                    <= unresolved_end
                ):
                    missing_sections: list[
                        dict[str, Any]
                    ] = []

                    for order in range(
                        current_order + 1,
                        next_order,
                    ):
                        definition = (
                            template_section_map.get(
                                order
                            )
                        )

                        if definition:
                            missing_sections.append(
                                {
                                    "order":
                                        order,

                                    "section_id":
                                        definition.get(
                                            "section_id"
                                        ),

                                    "title":
                                        definition.get(
                                            "title"
                                        ),

                                    "zone_type":
                                        definition.get(
                                            "zone_type"
                                        ),
                                }
                            )

                    unresolved_regions.append(
                        {
                            "region_type":
                                (
                                    "between_missing_"
                                    "sections"
                                ),

                            "start_page":
                                unresolved_start,

                            "end_page":
                                unresolved_end,

                            "previous_section_id":
                                current.get(
                                    "section_id"
                                ),

                            "next_section_id":
                                next_section.get(
                                    "section_id"
                                ),

                            "missing_sections":
                                missing_sections,

                            "reason":
                                (
                                    "模板顺序中存在"
                                    "未命中的章节锚点。"
                                ),
                        }
                    )

            # -----------------------------------------------------------------
            # 顺序异常
            # -----------------------------------------------------------------

            else:
                section_ranges.append(
                    {
                        "section_id":
                            current.get(
                                "section_id"
                            ),

                        "title":
                            current.get(
                                "title"
                            ),

                        "zone_type":
                            current.get(
                                "zone_type"
                            ),

                        "order":
                            current_order,

                        "start_page":
                            current_page,

                        "end_page":
                            current_page,

                        "boundary_source":
                            "unexpected_order",

                        "boundary_confidence":
                            "low",

                        "match_mode":
                            current.get(
                                "match_mode"
                            ),

                        "anchor_page":
                            current_page,
                    }
                )

        # ---------------------------------------------------------------------
        # 最后一个已匹配章节
        # ---------------------------------------------------------------------

        else:
            section_ranges.append(
                {
                    "section_id":
                        current.get(
                            "section_id"
                        ),

                    "title":
                        current.get(
                            "title"
                        ),

                    "zone_type":
                        current.get(
                            "zone_type"
                        ),

                    "order":
                        current_order,

                    "start_page":
                        current_page,

                    "end_page":
                        current_page,

                    "boundary_source":
                        "last_anchor_only",

                    "boundary_confidence":
                        "medium",

                    "match_mode":
                        current.get(
                            "match_mode"
                        ),

                    "anchor_page":
                        current_page,
                }
            )

            post_start = (
                current_page
                + 1
            )

            if post_start > page_count:
                continue

            # -----------------------------------------------------------------
            # 检查模板尾部是否只剩 attachments/free
            # -----------------------------------------------------------------

            trailing_sections = [
                definition
                for (
                    order,
                    definition,
                ) in template_section_map.items()
                if order > current_order
            ]

            trailing_sections.sort(
                key=lambda item: int(
                    item.get(
                        "order",
                        9999,
                    )
                )
            )

            can_infer_attachments = (
                len(
                    trailing_sections
                )
                == 1

                and trailing_sections[
                    0
                ].get(
                    "section_id"
                )
                == "attachments"

                and trailing_sections[
                    0
                ].get(
                    "zone_type"
                )
                == "free"
            )

            if can_infer_attachments:
                attachments = (
                    trailing_sections[
                        0
                    ]
                )

                section_ranges.append(
                    {
                        "section_id":
                            attachments.get(
                                "section_id"
                            ),

                        "title":
                            attachments.get(
                                "title"
                            ),

                        "zone_type":
                            attachments.get(
                                "zone_type"
                            ),

                        "order":
                            attachments.get(
                                "order"
                            ),

                        "start_page":
                            post_start,

                        "end_page":
                            page_count,

                        "boundary_source":
                            "template_tail_inference",

                        "boundary_confidence":
                            "medium",

                        "match_mode":
                            "inferred",

                        "inferred_from_section_id":
                            current.get(
                                "section_id"
                            ),
                    }
                )

            else:
                unresolved_regions.append(
                    {
                        "region_type":
                            "post_template_region",

                        "start_page":
                            post_start,

                        "end_page":
                            page_count,

                        "reason":
                            (
                                "最后一个已识别模板章节之后"
                                "仍存在无法安全确认的页面。"
                            ),
                    }
                )

    return (
        section_ranges,
        unresolved_regions,
    )


# =============================================================================
# template_assisted
# =============================================================================


def collect_assisted_sections(
    analyzer_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    unknown 模板时：

    汇总所有候选模板中已经真实观察到的章节。

    但每个候选模板都必须先经过：

        Anchor Sequence Validation

    避免目录页、附件中的重复申请书污染
    template_assisted。
    """
    merged: dict[
        tuple[str, int],
        dict[str, Any],
    ] = {}

    candidates = (
        analyzer_result.get(
            "candidates",
            [],
        )
    )

    for candidate_rank, candidate in enumerate(
        candidates
    ):
        candidate_id = str(
            candidate.get(
                "template_id",
                "",
            )
        )

        # 关键变化：
        #
        # 不再直接读取 matched_sections，
        # 而是先做章节链解析。
        resolved_sections = (
            normalize_matched_sections(
                candidate
            )
        )

        for section in resolved_sections:
            section_id = str(
                section.get(
                    "section_id",
                    "",
                )
            )

            anchor_page = (
                section.get(
                    "anchor_page"
                )
            )

            if not section_id:
                continue

            if not isinstance(
                anchor_page,
                int,
            ):
                continue

            key = (
                section_id,
                anchor_page,
            )

            is_distinctive = (
                section.get(
                    "anchor_type"
                )
                == "unique"
            )

            if key not in merged:
                merged[
                    key
                ] = {
                    "section_id":
                        section_id,

                    "title":
                        section.get(
                            "title"
                        ),

                    "zone_type":
                        section.get(
                            "zone_type"
                        ),

                    "anchor_page":
                        anchor_page,

                    "match_mode":
                        section.get(
                            "match_mode"
                        ),

                    "is_distinctive":
                        is_distinctive,

                    "candidate_sources":
                        [
                            candidate_id
                        ],

                    "best_candidate_rank":
                        candidate_rank,

                    "matched_anchors":
                        section.get(
                            "matched_anchors",
                            [],
                        ),

                    "anchor_candidates":
                        section.get(
                            "anchor_candidates",
                            [],
                        ),

                    "crowding_filtered_pages":
                        section.get(
                            "crowding_filtered_pages",
                            [],
                        ),

                    "anchor_selection_source":
                        section.get(
                            "anchor_selection_source"
                        ),
                }

            else:
                item = merged[
                    key
                ]

                if (
                    candidate_id
                    not in item[
                        "candidate_sources"
                    ]
                ):
                    item[
                        "candidate_sources"
                    ].append(
                        candidate_id
                    )

                if is_distinctive:
                    item[
                        "is_distinctive"
                    ] = True

                if (
                    candidate_rank
                    < item[
                        "best_candidate_rank"
                    ]
                ):
                    item[
                        "best_candidate_rank"
                    ] = (
                        candidate_rank
                    )

    sections = list(
        merged.values()
    )

    sections.sort(
        key=lambda item: (
            item[
                "anchor_page"
            ],
            item[
                "best_candidate_rank"
            ],
            item[
                "section_id"
            ],
        )
    )

    return sections

def has_conflicting_assisted_pages(
    sections: list[dict[str, Any]],
) -> bool:
    """
    如果同一页同时被识别成两个不同 section_id，
    当前版本不贸然启用 template_assisted。
    """
    page_sections: defaultdict[
        int,
        set[str],
    ] = defaultdict(
        set
    )

    for section in sections:
        page_sections[
            int(
                section[
                    "anchor_page"
                ]
            )
        ].add(
            str(
                section[
                    "section_id"
                ]
            )
        )

    return any(
        len(section_ids) > 1
        for section_ids
        in page_sections.values()
    )


def can_use_template_assisted(
    sections: list[dict[str, Any]],
) -> tuple[
    bool,
    dict[str, Any],
]:
    """
    判断 unknown PDF 是否有足够可靠的章节证据，
    可以进入 template_assisted。
    """
    section_ids = {
        str(
            section[
                "section_id"
            ]
        )
        for section in sections
    }

    distinctive_section_ids = {
        str(
            section[
                "section_id"
            ]
        )
        for section in sections
        if section.get(
            "is_distinctive"
        )
    }

    distinct_pages = {
        int(
            section[
                "anchor_page"
            ]
        )
        for section in sections
    }

    has_conflict = (
        has_conflicting_assisted_pages(
            sections
        )
    )

    metrics = {
        "recognized_section_count":
            len(
                section_ids
            ),

        "distinctive_section_count":
            len(
                distinctive_section_ids
            ),

        "distinct_anchor_page_count":
            len(
                distinct_pages
            ),

        "has_conflicting_anchor_pages":
            has_conflict,
    }

    allowed = (
        len(
            section_ids
        )
        >= ASSISTED_MIN_SECTION_HITS

        and len(
            distinctive_section_ids
        )
        >= ASSISTED_MIN_DISTINCTIVE_HITS

        and len(
            distinct_pages
        )
        >= ASSISTED_MIN_DISTINCT_PAGES

        and not has_conflict
    )

    return (
        allowed,
        metrics,
    )


def build_template_assisted_ranges(
    page_count: int,
    sections: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    unknown 模板但存在可靠章节锚点时：

    只使用真实观察到的章节。

    不使用完整 A/B 模板先验。

    允许：

        当前实际锚点
        →
        下一个实际锚点 - 1

    但置信度降为 medium。

    不允许：

        - 推断封面
        - 推断缺失章节
        - 推断附件区
        - 强制套 A/B order

    注意：

    front_matter_region 只用于 template_aware。
    template_assisted 因为模板身份未确认，
    第一可靠锚点之前统一保留为 pre_assisted_region。
    """
    section_ranges: list[
        dict[str, Any]
    ] = []

    unresolved_regions: list[
        dict[str, Any]
    ] = []

    if not sections:
        unresolved_regions.append(
            {
                "region_type":
                    "generic_region",

                "start_page":
                    1,

                "end_page":
                    page_count,

                "reason":
                    "没有可靠章节锚点。",
            }
        )

        return (
            section_ranges,
            unresolved_regions,
        )

    sections = sorted(
        sections,
        key=lambda item: (
            item[
                "anchor_page"
            ],
            item[
                "section_id"
            ],
        )
    )

    first_anchor_page = int(
        sections[
            0
        ][
            "anchor_page"
        ]
    )

    # -------------------------------------------------------------------------
    # 第一可靠章节之前：
    #
    # unknown 模板下不推断 cover，
    # 也不把前置页面进一步分类。
    # -------------------------------------------------------------------------

    if first_anchor_page > 1:
        unresolved_regions.append(
            {
                "region_type":
                    "pre_assisted_region",

                "start_page":
                    1,

                "end_page":
                    first_anchor_page
                    - 1,

                "reason":
                    (
                        "模板身份未确认，"
                        "第一可靠章节锚点之前的页面"
                        "不使用已注册模板先验进行分类。"
                    ),
            }
        )

    # -------------------------------------------------------------------------
    # 实际观察到的章节
    # -------------------------------------------------------------------------

    for index, current in enumerate(
        sections
    ):
        current_page = int(
            current[
                "anchor_page"
            ]
        )

        # ---------------------------------------------------------------------
        # 还有下一个真实章节锚点
        # ---------------------------------------------------------------------

        if (
            index
            < len(
                sections
            )
            - 1
        ):
            next_page = int(
                sections[
                    index + 1
                ][
                    "anchor_page"
                ]
            )

            if next_page > current_page:
                end_page = (
                    next_page
                    - 1
                )
            else:
                end_page = (
                    current_page
                )

            section_ranges.append(
                {
                    "section_id":
                        current.get(
                            "section_id"
                        ),

                    "title":
                        current.get(
                            "title"
                        ),

                    "zone_type":
                        current.get(
                            "zone_type"
                        ),

                    "order":
                        None,

                    "start_page":
                        current_page,

                    "end_page":
                        end_page,

                    "anchor_page":
                        current_page,

                    "boundary_source":
                        (
                            "next_observed_"
                            "anchor_minus_one"
                        ),

                    "boundary_confidence":
                        "medium",

                    "match_mode":
                        current.get(
                            "match_mode"
                        ),

                    "structure_evidence":
                        "observed_registered_anchor",

                    "candidate_sources":
                        current.get(
                            "candidate_sources",
                            [],
                        ),

                    "is_distinctive":
                        current.get(
                            "is_distinctive",
                            False,
                        ),
                }
            )

        # ---------------------------------------------------------------------
        # 最后一个真实章节锚点
        # ---------------------------------------------------------------------

        else:
            section_ranges.append(
                {
                    "section_id":
                        current.get(
                            "section_id"
                        ),

                    "title":
                        current.get(
                            "title"
                        ),

                    "zone_type":
                        current.get(
                            "zone_type"
                        ),

                    "order":
                        None,

                    "start_page":
                        current_page,

                    "end_page":
                        current_page,

                    "anchor_page":
                        current_page,

                    "boundary_source":
                        "last_observed_anchor_only",

                    "boundary_confidence":
                        "medium",

                    "match_mode":
                        current.get(
                            "match_mode"
                        ),

                    "structure_evidence":
                        "observed_registered_anchor",

                    "candidate_sources":
                        current.get(
                            "candidate_sources",
                            [],
                        ),

                    "is_distinctive":
                        current.get(
                            "is_distinctive",
                            False,
                        ),
                }
            )

            post_start = (
                current_page
                + 1
            )

            if post_start <= page_count:
                unresolved_regions.append(
                    {
                        "region_type":
                            "post_assisted_region",

                        "start_page":
                            post_start,

                        "end_page":
                            page_count,

                        "reason":
                            (
                                "未知模板下不根据已注册模板"
                                "强行推断尾部附件区域。"
                            ),
                    }
                )

    return (
        section_ranges,
        unresolved_regions,
    )


# =============================================================================
# generic
# =============================================================================


def build_generic_regions(
    page_count: int,
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
    template_config: dict[str, Any] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    既没有可靠模板身份，也没有足够已注册章节锚点时：

    1. 若提供 Stage1 snapshot，则优先使用真实观察到的一级标题构建章节；
    2. 能与已注册模板标题严格匹配的，复用 canonical section_id；
    3. 匹配不了的保留原文标题；
    4. 完全没有可靠标题时才退回整篇 generic_region。
    """
    if snapshot_pages and template_config:
        return build_observed_generic_sections(
            page_count=page_count,
            snapshot_pages=snapshot_pages,
            template_config=template_config,
        )

    return (
        [],
        [
            {
                "region_type": "generic_region",
                "start_page": 1,
                "end_page": page_count,
                "reason": (
                    "没有足够可靠的模板或章节证据，且未提供原生页面快照，"
                    "不使用模板结构进行推断。"
                ),
            }
        ],
    )


# =============================================================================
# page map
# =============================================================================


def build_page_map(
    page_count: int,
    section_ranges: list[dict[str, Any]],
    unresolved_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    给每一 PDF 物理页建立结构映射。
    """
    page_map = [
        {
            "page_number":
                page_number,

            "structure_type":
                "unassigned",

            "section_id":
                None,

            "title":
                None,

            "zone_type":
                None,
        }
        for page_number in range(
            1,
            page_count + 1,
        )
    ]

    # -------------------------------------------------------------------------
    # section
    # -------------------------------------------------------------------------

    for section in section_ranges:
        start_page = int(
            section[
                "start_page"
            ]
        )

        end_page = int(
            section[
                "end_page"
            ]
        )

        for page_number in range(
            start_page,
            end_page + 1,
        ):
            page_map[
                page_number - 1
            ] = {
                "page_number":
                    page_number,

                "structure_type":
                    "section",

                "section_id":
                    section.get(
                        "section_id"
                    ),

                "title":
                    section.get(
                        "title"
                    ),

                "zone_type":
                    section.get(
                        "zone_type"
                    ),

                "boundary_confidence":
                    section.get(
                        "boundary_confidence"
                    ),

                "match_mode":
                    section.get(
                        "match_mode"
                    ),
            }

    # -------------------------------------------------------------------------
    # unresolved
    # -------------------------------------------------------------------------

    for region in unresolved_regions:
        start_page = int(
            region[
                "start_page"
            ]
        )

        end_page = int(
            region[
                "end_page"
            ]
        )

        for page_number in range(
            start_page,
            end_page + 1,
        ):
            page_map[
                page_number - 1
            ] = {
                "page_number":
                    page_number,

                "structure_type":
                    region.get(
                        "region_type"
                    ),

                "section_id":
                    None,

                "title":
                    None,

                "zone_type":
                    None,
            }

    return page_map


# =============================================================================
# main alignment decision
# =============================================================================


def align_sections(
    analyzer_result: dict[str, Any],
    template_config: dict[str, Any],
    snapshot_pages: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Section Aligner 总入口。

    三种结构模式：

        template_aware
        template_assisted
        generic
    """
    page_count = int(
        analyzer_result[
            "page_count"
        ]
    )

    decision = str(
        analyzer_result.get(
            "decision",
            "unknown",
        )
    )

    # =========================================================================
    # 1. 明确识别到已注册模板
    # =========================================================================

    if decision == "matched":
        template_id = str(
            analyzer_result[
                "template_id"
            ]
        )

        template = (
            find_template_definition(
                config=
                    template_config,

                template_id=
                    template_id,
            )
        )

        candidate = (
            get_candidate_by_id(
                analyzer_result,
                template_id,
            )
        )

        if candidate is None:
            raise ValueError(
                "Template Analyzer 已判定模板，"
                "但 candidates 中找不到对应结果。"
            )

        matched_sections = (
            normalize_matched_sections(
                candidate
            )
        )

        (
            section_ranges,
            unresolved_regions,
        ) = (
            build_template_aware_ranges(
                page_count=
                    page_count,

                template=
                    template,

                matched_sections=
                    matched_sections,
            )
        )

        structure_mode = (
            "template_aware"
        )

        assisted_metrics = None

        assisted_candidates: list[
            str
        ] = []

    # =========================================================================
    # 2. 未确认模板
    # =========================================================================

    else:
        template_id = (
            "unknown"
        )

        assisted_sections = (
            collect_assisted_sections(
                analyzer_result
            )
        )

        (
            assisted_allowed,
            assisted_metrics,
        ) = (
            can_use_template_assisted(
                assisted_sections
            )
        )

        # ---------------------------------------------------------------------
        # 2A. unknown + 可靠相似章节
        # ---------------------------------------------------------------------

        if assisted_allowed:
            structure_mode = (
                "template_assisted"
            )

            (
                section_ranges,
                unresolved_regions,
            ) = (
                build_template_assisted_ranges(
                    page_count=
                        page_count,

                    sections=
                        assisted_sections,
                )
            )

            assisted_candidates = sorted(
                {
                    candidate_id
                    for section
                    in assisted_sections
                    for candidate_id
                    in section.get(
                        "candidate_sources",
                        [],
                    )
                }
            )

        # ---------------------------------------------------------------------
        # 2B. unknown + 章节证据不足
        # ---------------------------------------------------------------------

        else:
            structure_mode = (
                "generic"
            )

            (
                section_ranges,
                unresolved_regions,
            ) = (
                build_generic_regions(
                    page_count=page_count,
                    snapshot_pages=snapshot_pages,
                    template_config=template_config,
                )
            )

            assisted_candidates = []

    page_map = (
        build_page_map(
            page_count=
                page_count,

            section_ranges=
                section_ranges,

            unresolved_regions=
                unresolved_regions,
        )
    )

    return {
        "aligner_version":
            "0.2.5",

        "source_file":
            analyzer_result.get(
                "source_file"
            ),

        # ---------------------------------------------------------------------
        # 上游版本追踪
        # ---------------------------------------------------------------------

        "source_analyzer_version":
            analyzer_result.get(
                "analyzer_version"
            ),

        "source_profiler_version":
            analyzer_result.get(
                "source_profiler_version"
            ),

        "source_page_scan_version":
            analyzer_result.get(
                "source_page_scan_version"
            ),

        "page_count":
            page_count,

        # ---------------------------------------------------------------------
        # 模板身份
        # ---------------------------------------------------------------------

        "template_decision":
            decision,

        "template_id":
            template_id,

        "template_name":
            (
                analyzer_result.get(
                    "template_name"
                )
                if decision
                == "matched"
                else "未确定模板"
            ),

        "template_confidence":
            analyzer_result.get(
                "template_confidence"
            ),

        "best_candidate":
            analyzer_result.get(
                "best_candidate"
            ),

        "best_candidate_name":
            analyzer_result.get(
                "best_candidate_name"
            ),

        # ---------------------------------------------------------------------
        # 结构处理模式
        # ---------------------------------------------------------------------

        "structure_mode":
            structure_mode,

        "assisted_candidates":
            assisted_candidates,

        "assisted_metrics":
            assisted_metrics,

        # ---------------------------------------------------------------------
        # 结构输出
        # ---------------------------------------------------------------------

        "section_count":
            len(
                section_ranges
            ),

        "sections":
            section_ranges,

        "unresolved_regions":
            unresolved_regions,

        "pages":
            page_map,
    }


# =============================================================================
# terminal summary
# =============================================================================


def print_summary(
    result: dict[str, Any],
) -> None:
    """
    中文终端摘要。
    """
    print()

    print(
        "=" * 112
    )

    print(
        f"章节对齐器 | "
        f"{result['source_file']} "
        f"| 页数="
        f"{result['page_count']} "
        f"| 版本="
        f"{result['aligner_version']}"
    )

    print(
        "=" * 112
    )

    print(
        f"模板判定："
        f"{result['template_id']}"
    )

    print(
        f"结构模式："
        f"{result['structure_mode']}"
    )

    if (
        result[
            "structure_mode"
        ]
        == "template_aware"
    ):
        print(
            f"模板名称："
            f"{result['template_name']}"
        )

        print(
            f"模板置信度："
            f"{result['template_confidence']}"
        )

    elif (
        result[
            "structure_mode"
        ]
        == "template_assisted"
    ):
        print(
            "模板身份未确认，"
            "但检测到足够可靠的已注册章节锚点。"
        )

        print(
            f"相关候选："
            f"{', '.join(result['assisted_candidates'])}"
        )

        metrics = (
            result.get(
                "assisted_metrics"
            )
            or {}
        )

        print(
            f"章节证据："
            f"识别章节="
            f"{metrics.get('recognized_section_count', 0)} "
            f"区分章节="
            f"{metrics.get('distinctive_section_count', 0)} "
            f"锚点页="
            f"{metrics.get('distinct_anchor_page_count', 0)}"
        )

    else:
        if result.get("sections"):
            print(
                "模板身份未确认；已从 Stage1 原生一级标题恢复通用章节，"
                "已注册标题仅用于 section_id 对齐，不补写模板内容。"
            )
        else:
            print(
                "模板和原生一级标题证据均不足，"
                "进入未决通用区域模式。"
            )

    print()

    print(
        "章节范围："
    )

    print()

    if not result[
        "sections"
    ]:
        print(
            "  无可靠章节范围。"
        )

    else:
        for section in result[
            "sections"
        ]:
            start_page = int(
                section[
                    "start_page"
                ]
            )

            end_page = int(
                section[
                    "end_page"
                ]
            )

            confidence = str(
                section.get(
                    "boundary_confidence",
                    "",
                )
            )

            match_mode = str(
                section.get(
                    "match_mode",
                    "",
                )
            )

            print(
                f"  PDF第"
                f"{start_page:>3}"
                f"～"
                f"{end_page:<3}页"
                f" | "
                f"{str(section.get('section_id', '')):<22}"
                f" | "
                f"{str(section.get('zone_type', '')):<15}"
                f" | "
                f"{confidence:<6}"
                f" | "
                f"{match_mode:<15}"
                f" | "
                f"{section.get('title', '')}"
            )

    if result[
        "unresolved_regions"
    ]:
        print()

        print(
            "未决区域："
        )

        print()

        for region in result[
            "unresolved_regions"
        ]:
            print(
                f"  PDF第"
                f"{region['start_page']:>3}"
                f"～"
                f"{region['end_page']:<3}页"
                f" | "
                f"{region['region_type']}"
            )

    print(
        "=" * 112
    )


def run_section_alignment(
    *,
    analysis_path: Path,
    template_path: Path,
    snapshot_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    """Run Stage 3 through the package API while preserving its artifact format."""
    analyzer_result = load_json(Path(analysis_path))
    template_config = load_template_config(Path(template_path))
    snapshot_pages = load_snapshot_pages(
        Path(snapshot_path) if snapshot_path is not None else None
    )
    result = align_sections(
        analyzer_result=analyzer_result,
        template_config=template_config,
        snapshot_pages=snapshot_pages,
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

