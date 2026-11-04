from __future__ import annotations

import json

import pytest

from tools.provider_benchmark.evaluate import evaluate
from tools.provider_benchmark.prepare import prepare_pages


def test_scoring_does_not_invent_quality_without_ground_truth():
    labels = [{"page_id": "p1", "label_status": "unlabeled", "text_gt": None}]
    predicted = [{"page_id": "p1", "provider": "a", "status": "SUCCESS", "text": "你好", "elapsed_seconds": 2}]
    row = evaluate(labels, predicted)[0]
    assert row["micro_cer_no_whitespace"] is None
    assert row["successful_pages"] == 1
    assert row["median_execute_seconds"] == 2


def test_scoring_counts_missing_and_failed_pages():
    labels = [
        {"page_id": "p1", "label_status": "approved", "text_gt": "你好", "critical_fields_gt": [{"name": "x", "value": "你"}]},
        {"page_id": "p2", "label_status": "approved", "text_gt": "金额500"},
        {"page_id": "p3", "label_status": "approved", "text_gt": "日期"},
    ]
    predictions = [
        {"page_id": "p1", "provider": "a", "status": "SUCCESS", "text": "你好", "elapsed_seconds": 1},
        {"page_id": "p2", "provider": "a", "status": "FAILED", "text": None, "elapsed_seconds": 2},
    ]
    result = evaluate(labels, predictions)[0]
    assert result["status_counts"]["MISSING"] == 1
    assert result["success_rate_all_expected"] == pytest.approx(1/3, abs=1e-4)
    assert result["micro_cer_no_whitespace"] == 0
    assert result["text_gt_pages_scored"] == 1
    assert result["field_literal_presence_recall"] == 1


def test_prepare_raster_only_pair_from_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    src = tmp_path / "data"
    src.mkdir()
    original = src / "case.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=300)
        page.insert_text((20,40), "hello")
        doc.save(original)
    items = prepare_pages(
        [{"page_id": "doc:p001", "pdf_filename": "case.pdf", "page_number": 1}],
        pdf_dir=src, output_dir=tmp_path / "prepared", dpi=100,
    )
    assert len(items) == 1
    assert (tmp_path / "prepared/manifest.jsonl").is_file()
    with fitz.open(tmp_path / "prepared" / items[0]["pdf"]) as raster:
        assert len(raster) == 1
        assert raster[0].get_text().strip() == ""
        assert raster[0].get_images()
