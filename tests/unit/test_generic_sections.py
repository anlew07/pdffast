"""Sections must come from observed PDF text, never a configured template."""

from pdffast.native.sections import diagnose_page_ownership, diagnose_section_candidates, discover_sections


def _page(number: int, text: str) -> dict:
    return {"record_type": "page", "page_number": number, "native_text": text}


def _divider(number: int, title: str) -> dict:
    page = _page(number, f"{title}\n- {number} -")
    page.update({
        "width": 600, "height": 840,
        "words": [{"text": title, "x0": 130, "x1": 470, "top": 300}],
        "chars": [{"text": char, "top": 300, "size": 30} for char in title],
    })
    return page


def _visual_page(number: int, title: str, footer: int) -> dict:
    body = "这一页有连续的原生正文和足够的文字证据，可以比较相邻页面的版式与页码。"
    page = _page(number, f"{title}\n{body}\n- {footer} -")
    page.update({
        "width": 600, "height": 840,
        "words": [{"text": title, "x0": 190, "x1": 410, "top": 55}],
        "chars": [{"text": char, "top": 55, "size": 22} for char in title]
        + [{"text": char, "top": 120, "size": 12} for char in body],
    })
    return page


def _body_page(number: int, footer: int | None = None) -> dict:
    body = "这一页继续呈现同一份文档的正文，文字长度足以供原生版式与页码判断。"
    page = _page(number, body + (f"\n- {footer} -" if footer is not None else ""))
    page.update({"width": 600, "height": 840, "chars": [{"text": char, "top": 120, "size": 12} for char in body]})
    return page


def test_numbered_observed_headings_keep_pdf_titles_and_cover_pages() -> None:
    pages = {
        1: _page(1, "项目申请书\n编号 42"),
        2: _page(2, "一、基本信息\n申请人信息"),
        3: _page(3, "正文延续"),
        4: _page(4, "二、技术路线\n详细研究方案"),
    }
    result = discover_sections(source_file="sample.pdf", page_count=4, snapshot_pages=pages)
    assert [(s["title"], s["start_page"], s["end_page"]) for s in result["sections"]] == [
        ("一、基本信息", 2, 3),
        ("二、技术路线", 4, 4),
    ]
    assert result["unresolved_regions"] == [{
        "region_type": "generic_region", "start_page": 1, "end_page": 1,
        "reason": "首个已观察章节标题之前的页面没有可靠章节边界。",
    }]
    assert all(s["canonical_title"] is None for s in result["sections"])
    assert result["pages"][0]["section_id"] is None


def test_no_heading_is_explicitly_unresolved() -> None:
    result = discover_sections(source_file="sample.pdf", page_count=2, snapshot_pages={1: _page(1, "正文")})
    assert result["sections"] == []
    assert result["unresolved_regions"][0]["end_page"] == 2
    assert all(page["section_id"] is None for page in result["pages"])


def test_centered_large_observed_title_is_retained_without_numbering() -> None:
    page = _page(1, "科研诚信承诺书\n本人承诺遵守相关规定并据实填写材料")
    page.update({
        "width": 600, "height": 840,
        "words": [{"text": "科研诚信承诺书", "x0": 200, "x1": 400, "top": 55}],
        "chars": [
            {"text": char, "top": 55, "size": 22} for char in "科研诚信承诺书"
        ] + [{"text": char, "top": 120, "size": 12} for char in "本人承诺遵守相关规定并据实填写材料"],
    })
    result = discover_sections(source_file="sample.pdf", page_count=1, snapshot_pages={1: page})
    assert result["sections"][0]["title"] == "科研诚信承诺书"
    assert result["sections"][0]["match_mode"] == "generic_visual_heading"


def test_terminal_visual_heading_does_not_claim_unobserved_tail() -> None:
    title_page = _page(2, "科研成果论文名单\n此页列出本人已发表的论文和相关证明材料")
    title_page.update({
        "width": 600, "height": 840,
        "words": [{"text": "科研成果论文名单", "x0": 190, "x1": 410, "top": 55}],
        "chars": [{"text": "科", "top": 55, "size": 22}, {"text": "本", "top": 120, "size": 12}],
    })
    result = discover_sections(
        source_file="sample.pdf", page_count=4,
        snapshot_pages={1: _page(1, "一、正文\n内容"), 2: title_page, 3: _page(3, "附件扫描页")},
    )
    assert result["sections"][-1]["end_page"] == 2
    assert result["unresolved_regions"] == [{
        "region_type": "generic_region", "start_page": 3, "end_page": 4,
        "reason": "最后一个已观察标题之后缺少可靠的章节延续证据。",
    }]


def test_visual_heading_does_not_claim_unobserved_pages_before_next_title() -> None:
    visual = _page(1, "科研成果论文名单\n此页列出本人已发表的论文和相关证明材料")
    visual.update({
        "width": 600, "height": 840,
        "words": [{"text": "科研成果论文名单", "x0": 190, "x1": 410, "top": 55}],
        "chars": [{"text": "科", "top": 55, "size": 22}, {"text": "本", "top": 120, "size": 12}],
    })
    result = discover_sections(
        source_file="sample.pdf", page_count=4,
        snapshot_pages={1: visual, 4: _page(4, "一、其他资料\n正文")},
    )
    assert result["sections"][0]["end_page"] == 1
    assert result["unresolved_regions"][0]["start_page"] == 2
    assert result["unresolved_regions"][0]["end_page"] == 3


def test_terminal_numbered_heading_does_not_claim_unobserved_appendices() -> None:
    result = discover_sections(
        source_file="sample.pdf", page_count=4,
        snapshot_pages={1: _page(1, "一、审核意见\n正文"), 4: _page(4, "扫描附件")},
    )
    assert result["sections"][0]["end_page"] == 1
    assert result["unresolved_regions"][0]["start_page"] == 2
    assert result["unresolved_regions"][0]["end_page"] == 4


def test_numbering_chain_can_restart_after_document_boundary() -> None:
    pages = {
        1: _page(1, "一、正文第一章"),
        2: _page(2, "二、正文第二章"),
        3: _page(3, "三、正文第三章"),
        4: _page(4, "新文档封面"),
        5: _divider(5, "一、附件第一章"),
        7: _divider(7, "二、附件第二章"),
    }
    result = discover_sections(source_file="sample.pdf", page_count=8, snapshot_pages=pages)
    assert [(section["anchor_page"], section["title"]) for section in result["sections"]] == [
        (1, "一、正文第一章"),
        (2, "二、正文第二章"),
        (3, "三、正文第三章"),
        (5, "一、附件第一章"),
        (7, "二、附件第二章"),
    ]
    assert any(region["start_page"] == 4 and region["end_page"] == 4 for region in result["unresolved_regions"])
    diagnostics = diagnose_section_candidates(page_count=8, snapshot_pages=pages)
    assert next(item for item in diagnostics if item["page"] == 5)["reason"] == "numbering_restart_at_standalone_divider"


def test_numbering_restart_without_boundary_is_not_automatic() -> None:
    pages = {
        1: _page(1, "一、正文第一章"),
        2: _page(2, "二、正文第二章"),
        3: _page(3, "三、正文第三章"),
        4: _page(4, "材料目录\n一、目录条目\n下面还有很多列表内容"),
    }
    result = discover_sections(source_file="sample.pdf", page_count=4, snapshot_pages=pages)
    assert [section["title"] for section in result["sections"]] == [
        "一、正文第一章", "二、正文第二章", "三、正文第三章",
    ]
    diagnostics = diagnose_section_candidates(page_count=4, snapshot_pages=pages)
    assert next(item for item in diagnostics if item["page"] == 4)["reason"] == "numbering_reset_without_document_boundary"


def test_longer_later_numbering_run_does_not_replace_document_without_boundary() -> None:
    pages = {
        1: _page(1, "一、原文第一章"),
        2: _page(2, "二、原文第二章"),
        3: _page(3, "三、原文第三章"),
        4: _page(4, "一、页内重新编号\n普通正文"),
        5: _page(5, "二、页内编号"),
        6: _page(6, "三、页内编号"),
        7: _page(7, "四、页内编号"),
        8: _page(8, "五、页内编号"),
        9: _page(9, "六、页内编号"),
    }
    result = discover_sections(source_file="sample.pdf", page_count=9, snapshot_pages=pages)
    assert [(section["anchor_page"], section["title"]) for section in result["sections"][:3]] == [
        (1, "一、原文第一章"), (2, "二、原文第二章"), (3, "三、原文第三章"),
    ]
    assert all(section["anchor_page"] != 4 for section in result["sections"])


def test_repeated_visual_titles_are_not_globally_deduplicated() -> None:
    pages = {}
    for number in (2, 4, 6):
        page = _page(number, "批准通知书\n正文证明内容")
        page.update({
            "width": 600, "height": 840,
            "words": [{"text": "批准通知书", "x0": 205, "x1": 395, "top": 60}],
            "chars": [{"text": "批", "top": 60, "size": 22}, {"text": "正", "top": 120, "size": 12}],
        })
        pages[number] = page
    result = discover_sections(source_file="sample.pdf", page_count=6, snapshot_pages=pages)
    assert [(section["anchor_page"], section["title"]) for section in result["sections"]] == [
        (2, "批准通知书"), (4, "批准通知书"), (6, "批准通知书"),
    ]


def test_unresolved_pages_preserve_observed_candidates() -> None:
    result = discover_sections(
        source_file="sample.pdf", page_count=8,
        snapshot_pages={1: _page(1, "一、正文"), 2: _page(2, "二、正文"), 5: _divider(5, "一、附件")},
    )
    assert result["sections"][-1]["title"] == "一、附件"
    assert result["sections"][-1]["anchor_page"] == 5
    assert any(region["start_page"] == 3 and region["end_page"] == 4 for region in result["unresolved_regions"])


def test_section_discovery_has_no_template_input() -> None:
    result = discover_sections(source_file="sample.pdf", page_count=1, snapshot_pages={1: _page(1, "一、实际标题")})
    assert [section["title"] for section in result["sections"]] == ["一、实际标题"]


def test_visual_heading_can_continue_with_strong_evidence() -> None:
    pages = {1: _visual_page(1, "实际观察到的标题", 1), 2: _body_page(2, 2), 3: _body_page(3, 3)}
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert [(section["title"], section["start_page"], section["end_page"]) for section in result["sections"]] == [
        ("实际观察到的标题", 1, 3),
    ]
    decisions = diagnose_page_ownership(page_count=3, snapshot_pages=pages)
    assert [(item["page"], item["decision"]) for item in decisions] == [(1, "NEW_SECTION"), (2, "CONTINUE"), (3, "CONTINUE")]
    assert "internal_page_number_consecutive" in decisions[1]["continuity_signals"]


def test_visual_heading_does_not_absorb_unrelated_page() -> None:
    cover = _page(2, "另一份文档的封面\n独立说明\n申请人信息")
    cover.update({
        "width": 600, "height": 840,
        "words": [{"text": "另一份文档的封面", "x0": 180, "x1": 420, "top": 210}],
        "chars": [{"text": "封", "top": 210, "size": 26}, {"text": "说", "top": 280, "size": 12}],
    })
    pages = {1: _visual_page(1, "实际观察到的标题", 1), 2: cover, 3: _body_page(3, 3)}
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert result["sections"][0]["end_page"] == 1
    assert [(r["start_page"], r["end_page"]) for r in result["unresolved_regions"]] == [(2, 3)]
    decisions = diagnose_page_ownership(page_count=3, snapshot_pages=pages)
    assert decisions[1]["decision"] == "UNRESOLVED"
    assert "cover_like_page" in decisions[1]["boundary_signals"]


def test_numbered_section_continuation_remains_stable() -> None:
    pages = {1: _page(1, "一、正文\n一些内容\n1/3"), 2: _body_page(2), 3: _page(3, "二、下节\n正文\n3/3")}
    pages[1]["width"] = pages[2]["width"] = pages[3]["width"] = 600
    pages[1]["height"] = pages[2]["height"] = pages[3]["height"] = 840
    pages[2]["native_text"] += "\n2/3"
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert [(s["start_page"], s["end_page"]) for s in result["sections"]] == [(1, 2), (3, 3)]


def test_numbered_section_can_continue_across_scanned_pages_with_internal_numbering() -> None:
    pages = {1: _divider(1, "五、真实章节"), 2: _page(2, "5.1 这一页的条目说明有足够的原生文字\n- 2 -"), 3: _page(3, "5.2 下一页的条目说明也有足够的原生文字\n- 3 -")}
    pages[1]["native_text"] = "五、真实章节\n- 1 -"
    for page in (pages[2], pages[3]):
        page.update({"width": 600, "height": 840, "images": [{"x0": 50, "x1": 550, "top": 100, "bottom": 700}]})
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert result["sections"][0]["end_page"] == 3
    assert all(page["section_id"] == "observed_section_001" for page in result["pages"])


def test_consecutive_footer_alone_does_not_assign_other_numbered_document() -> None:
    pages = {1: _divider(1, "五、真实章节"), 2: _page(2, "2.1 另一组文档的条目有足够原生文字\n- 2 -")}
    pages[1]["native_text"] = "五、真实章节\n- 1 -"
    pages[2].update({"width": 600, "height": 840})
    result = discover_sections(source_file="sample.pdf", page_count=2, snapshot_pages=pages)
    assert result["sections"][0]["end_page"] == 1
    assert result["pages"][1]["section_id"] is None


def test_new_heading_stops_previous_section() -> None:
    pages = {1: _visual_page(1, "第一份标题", 1), 2: _body_page(2, 2), 3: _visual_page(3, "第二份标题", 1)}
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert [(s["anchor_page"], s["end_page"]) for s in result["sections"]] == [(1, 2), (3, 3)]


def test_unresolved_when_continuity_is_ambiguous() -> None:
    pages = {1: _visual_page(1, "已观察标题", 1), 2: _body_page(2), 3: _body_page(3)}
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert result["sections"][0]["end_page"] == 1
    assert [(r["start_page"], r["end_page"]) for r in result["unresolved_regions"]] == [(2, 3)]


def test_repeated_titles_keep_independent_ranges() -> None:
    pages = {1: _visual_page(1, "同一个实际标题", 1), 2: _body_page(2, 2), 3: _visual_page(3, "同一个实际标题", 1), 4: _body_page(4, 2)}
    result = discover_sections(source_file="sample.pdf", page_count=4, snapshot_pages=pages)
    assert [(s["section_id"], s["title"], s["start_page"], s["end_page"]) for s in result["sections"]] == [
        ("observed_section_001", "同一个实际标题", 1, 2),
        ("observed_section_002", "同一个实际标题", 3, 4),
    ]


def test_no_invented_heading_or_page_ownership() -> None:
    pages = {1: _visual_page(1, "真实标题", 1), 2: _page(2, "版\n式\n正\n2/4"), 3: _body_page(3, 3)}
    pages[2].update({"width": 520, "height": 750, "images": [{"x0": 0, "x1": 520, "top": 0, "bottom": 750}]})
    result = discover_sections(source_file="sample.pdf", page_count=3, snapshot_pages=pages)
    assert [s["title"] for s in result["sections"]] == ["真实标题"]
    assert result["pages"][1]["section_id"] is None
    assert result["pages"][2]["section_id"] is None
