"""Recovered headings are evidence for a later reconciliation, never sections."""

from copy import deepcopy

from pdffast.structure_reconciliation.heading_candidates import (
    extract_recovered_heading_candidates,
)


def _native(*owners: str | None) -> dict:
    return {
        "page_count": len(owners),
        "page_index": [
            {"page_number": page, "section_id": owner}
            for page, owner in enumerate(owners, 1)
        ],
        "sections": [{"section_id": owner} for owner in owners if owner],
    }


def _prediction(page: int, *, task_type: str = "PAGE_FALLBACK", **channels: dict) -> dict:
    return {
        "task_id": f"task-{page}-{task_type}",
        "task_type": task_type,
        "page_number": page,
        "selected_provider": "fixture_provider",
        "terminal_fallback_applied": False,
        "selected_canonical": {
            "text": {"availability": "AVAILABLE", "content": "some text", "source_format": "plain_text"},
            "reading_blocks": {"availability": "NOT_EMITTED", "items": []},
            "spatial_text": {"availability": "NOT_EMITTED", "items": []},
            "source_artifacts": {"task_result": "/fixture/raw.json"},
            **channels,
        },
    }


def _spatial(text: str, top: float, height: float, x0: float, x1: float, confidence: float = .99) -> dict:
    return {
        "text": text,
        "confidence": confidence,
        "bbox": {"x0": x0, "top": top, "x1": x1, "bottom": top + height},
    }


def test_explicit_provider_heading_becomes_candidate_not_section() -> None:
    native = _native(None)
    before = deepcopy(native)
    result = extract_recovered_heading_candidates(native, [_prediction(
        1, reading_blocks={"availability": "AVAILABLE", "items": [
            {"kind": "heading", "level": 1, "text": "原文标题", "block_id": "block_001", "order": 0},
        ]},
    )])
    assert [(c.text, c.evidence_kind, c.status) for c in result.candidates] == [
        ("原文标题", "EXPLICIT_HEADING_BLOCK", "CANDIDATE")
    ]
    assert result.candidates[0].block_index == 0
    assert result.candidates[0].source_reference == "/fixture/raw.json"
    assert native == before


def test_markdown_heading_records_derived_evidence() -> None:
    prediction = _prediction(1, reading_blocks={"availability": "AVAILABLE", "items": [
        {"kind": "heading", "level": 2, "text": "# 已由 Markdown 标记", "order": 0},
    ]})
    prediction["selected_canonical"]["text"]["source_format"] = "markdown"
    result = extract_recovered_heading_candidates(_native(None), [prediction])
    assert result.candidates[0].evidence_kind == "MARKDOWN_HEADING"
    assert result.candidates[0].text == "# 已由 Markdown 标记"
    assert result.candidates[0].signals["origin"] == "provider_markdown_via_normalizer"


def test_ocr_prominent_line_can_become_candidate() -> None:
    lines = [
        _spatial("陕西省教育厅服务地方专项计划项目", 10, 42, 180, 820),
        _spatial("合同书", 75, 46, 400, 600),
        _spatial("项目名称和项目编号等普通表单字段", 290, 24, 120, 880),
        _spatial("项目负责人以及相应单位信息", 325, 26, 120, 880),
        _spatial("申请人和相关单位签署的说明", 360, 25, 120, 880),
    ]
    result = extract_recovered_heading_candidates(_native(None), [_prediction(
        1, spatial_text={"availability": "AVAILABLE", "coordinate_system": "provider_image_pixels",
                         "relative_coordinate_basis": "ocr_item_union_bbox", "items": lines},
    )])
    assert [c.text for c in result.candidates] == ["陕西省教育厅服务地方专项计划项目", "合同书"]
    assert all(c.evidence_kind == "OCR_VISUAL_LINE" for c in result.candidates)
    assert result.candidates[0].bbox_coordinate_space == "PROVIDER_INPUT_IMAGE"
    assert result.candidates[0].raw_bbox == lines[0]["bbox"]
    assert result.candidates[0].signals["relative_line_height"] > 1
    assert result.candidates[0].provider_confidence == .99


def test_ordinary_ocr_body_line_is_rejected_with_reason() -> None:
    lines = [
        _spatial("页面普通正文第一行，介绍具体事实", 10, 20, 0, 800),
        _spatial("页面普通正文第二行，继续介绍事实", 35, 20, 0, 800),
        _spatial("页面普通正文第三行，没有标题信号", 60, 20, 0, 800),
    ]
    result = extract_recovered_heading_candidates(_native(None), [_prediction(
        1, spatial_text={"availability": "AVAILABLE", "coordinate_system": "provider_image_pixels", "items": lines},
    )])
    assert result.candidates == ()
    assert any(d.status == "REJECTED" and d.reason == "not_visually_prominent" for d in result.diagnostics)


def test_pure_text_without_structure_does_not_create_heading() -> None:
    result = extract_recovered_heading_candidates(_native(None), [_prediction(1)])
    assert result.candidates == ()
    assert result.diagnostics[0].reason == "no_structural_heading_evidence"


def test_paragraph_blocks_without_heading_are_diagnosed() -> None:
    result = extract_recovered_heading_candidates(_native(None), [_prediction(
        1, reading_blocks={"availability": "AVAILABLE", "items": [
            {"kind": "paragraph", "text": "普通正文", "order": 0},
        ]},
    )])
    assert result.candidates == ()
    assert result.diagnostics[0].reason == "no_heading_block"


def test_only_native_unresolved_pages_are_considered() -> None:
    result = extract_recovered_heading_candidates(_native("native-section", None), [
        _prediction(1, reading_blocks={"availability": "AVAILABLE", "items": [{"kind": "heading", "text": "不能覆盖"}]}),
        _prediction(2, reading_blocks={"availability": "AVAILABLE", "items": [{"kind": "heading", "text": "可以候选"}]}),
    ])
    assert [c.page_number for c in result.candidates] == [2]
    assert any(d.reason == "native_section_already_owned" for d in result.diagnostics)


def test_region_inline_and_terminal_tasks_are_excluded() -> None:
    tasks = [_prediction(1, task_type=kind, reading_blocks={"availability": "AVAILABLE", "items": [{"kind": "heading", "text": kind}]})
             for kind in ("REGION_FALLBACK", "INLINE_CONTEXT_FALLBACK")]
    terminal = _prediction(1)
    terminal["terminal_fallback_applied"] = True
    tasks.append(terminal)
    result = extract_recovered_heading_candidates(_native(None), tasks)
    assert result.candidates == ()
    assert [d.reason for d in result.diagnostics] == ["not_whole_page_fallback", "not_whole_page_fallback", "terminal_fallback"]


def test_unknown_bbox_coordinate_space_is_not_interpreted_as_pdf() -> None:
    result = extract_recovered_heading_candidates(_native(None), [_prediction(
        1, spatial_text={"availability": "AVAILABLE", "coordinate_system": "unknown", "items": [
            _spatial("显著标题", 10, 40, 100, 400),
        ]},
    )])
    assert result.candidates == ()
    assert result.diagnostics[0].reason == "unsupported_coordinate_space"


def test_repeated_recovered_titles_are_not_deduplicated_by_text() -> None:
    native = _native(None, None)
    predictions = [_prediction(page, reading_blocks={"availability": "AVAILABLE", "items": [
        {"kind": "heading", "text": "重复的原文标题", "order": 0},
    ]}) for page in (1, 2)]
    result = extract_recovered_heading_candidates(native, predictions)
    assert [(c.page_number, c.text) for c in result.candidates] == [
        (1, "重复的原文标题"), (2, "重复的原文标题"),
    ]


def test_candidate_extraction_does_not_modify_selected_prediction() -> None:
    selected = _prediction(1, reading_blocks={"availability": "AVAILABLE", "items": [
        {"kind": "heading", "text": "PDF 原始标题", "order": 0},
    ]})
    before = deepcopy(selected)
    extract_recovered_heading_candidates(_native(None), [selected])
    assert selected == before
