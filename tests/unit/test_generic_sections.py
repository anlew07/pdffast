"""Sections must come from observed PDF text, never a configured template."""

from pdffast.native.sections import discover_sections


def _page(number: int, text: str) -> dict:
    return {"record_type": "page", "page_number": number, "native_text": text}


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
