import csv
import hashlib
import json

import pytest

from tools.provider_benchmark.report import build_report


def lines(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")


def sample(tmp_path):
    manifest = tmp_path / "inputs/manifest.jsonl"
    pages = [{"page_id": "case_001:p003", "image": "assets/one.png"},
             {"page_id": "case_001:p015", "image": "assets/two.png"}]
    lines(manifest, pages)
    (manifest.parent / "assets").mkdir()
    (manifest.parent / "assets/one.png").write_bytes(b"x")
    fingerprint = hashlib.sha256(
        json.dumps(pages, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    root = tmp_path / "runs"
    a = root / "ocr/predictions.jsonl"
    can = root / "ocr/canonical.json"
    can.parent.mkdir(parents=True)
    can.write_text(json.dumps({"tables": {"availability": "UNSUPPORTED"},
                               "warnings": ["needs_review"]}), encoding="utf-8")
    lines(a, [
        {"page_id": "case_001:p003", "provider": "a", "status": "SUCCESS",
         "text": "<b>你好</b>", "elapsed_seconds": 1.5, "canonical_path": str(can)},
        {"page_id": "case_001:p015", "provider": "a", "status": "SUCCESS",
         "text": "", "elapsed_seconds": 2.5},
    ])
    b = root / "layout/predictions.jsonl"
    lines(b, [
        {"page_id": "case_001:p015", "provider": "b", "status": "SUCCESS", "text": "文本", "elapsed_seconds": 4.0},
        {"page_id": "case_001:p003", "provider": "b", "status": "FAILED", "reason": "err"},
    ])
    for path in [a, b]:
        (path.parent / "run_manifest.json").write_text(
            json.dumps({"dataset_fingerprint_sha256": fingerprint}), encoding="utf-8"
        )
    return manifest, [a, b]


def test_same_page_matrix_and_escaped_full_text(tmp_path):
    manifest, runs = sample(tmp_path)
    out = tmp_path / "report"
    report = build_report(manifest=manifest, prediction_files=runs, out=out)
    assert report["page_count"] == 2 and report["provider_count"] == 2
    assert report["observed_predictions"] == 4
    assert report["quality"] == "NOT_SCORED_NEEDS_APPROVED_GROUND_TRUTH"
    with (out / "page_matrix.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["page_id"] == "case_001:p003"
    assert rows[0]["a__chars"] == "9"
    assert rows[0]["b__status"] == "FAILED"
    assert "EMPTY_TEXT" in rows[1]["a__flags"]
    page = (out / "page_compare.html").read_text(encoding="utf-8")
    assert "&lt;b&gt;你好&lt;/b&gt;" in page
    assert "<b>你好</b>" not in page
    assert "assets/one.png" in page
    with (out / "page_provider_details.csv").open(encoding="utf-8-sig", newline="") as f:
        details = list(csv.DictReader(f))
    assert len(details) == 4
    assert details[0]["tables"] == "UNSUPPORTED"
    assert "needs_review" in details[0]["flags"]


def test_mismatched_run_is_rejected(tmp_path):
    manifest, runs = sample(tmp_path)
    (runs[0].parent / "run_manifest.json").write_text(
        json.dumps({"dataset_fingerprint_sha256": "wrong"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        build_report(manifest=manifest, prediction_files=runs, out=tmp_path / "out")


def test_duplicate_predictions_are_rejected(tmp_path):
    manifest, runs = sample(tmp_path)
    with pytest.raises(ValueError, match="duplicate prediction"):
        build_report(manifest=manifest, prediction_files=[runs[0], runs[0]], out=tmp_path / "out")


def test_missing_prediction_remains_missing(tmp_path):
    manifest, runs = sample(tmp_path)
    rows = [json.loads(x) for x in runs[1].read_text().splitlines()]
    lines(runs[1], rows[:1])
    out = tmp_path / "report"
    report = build_report(manifest=manifest, prediction_files=runs, out=out)
    assert report["observed_predictions"] == 3
    with (out / "page_matrix.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["b__status"] == "MISSING"


def test_pairwise_csv_and_html_ab_diff(tmp_path):
    manifest, runs = sample(tmp_path)
    out = tmp_path / "report"
    result = build_report(manifest=manifest, prediction_files=runs, out=out)
    assert result["provider_count"] == 2
    with (out / "pairwise_pages.csv").open(encoding="utf-8-sig", newline="") as f:
        data = list(csv.DictReader(f))
    assert len(data) == 2
    assert data[0]["char_overlap_pct"] == ""  # non-success should not be scored
    assert data[1]["char_overlap_pct"] == "0.0"
    assert data[1]["a_fragments_covered_by_b_pct"] == ""
    assert data[1]["b_fragments_covered_by_a_pct"] == "0.0"
    with (out / "pairwise_summary.csv").open(encoding="utf-8-sig", newline="") as f:
        summaries = list(csv.DictReader(f))
    assert len(summaries) == 1
    assert summaries[0]["comparable_pages"] == "1"
    page = (out / "page_compare.html").read_text(encoding="utf-8")
    assert 'id="provider-a"' in page and 'id="provider-b"' in page
    assert "同页 A/B 差异高亮" in page
    assert "fragmentCoverage" in page
    assert "flushChanged" in page


def test_exclude_provider_drops_it_from_report_only(tmp_path):
    manifest, runs = sample(tmp_path)
    out = tmp_path / "report"
    result = build_report(manifest=manifest, prediction_files=runs, out=out, exclude=["b"])
    assert result["provider_count"] == 1
    assert result["observed_predictions"] == 2
    assert result["providers"] == ["a"]
    assert result["excluded_providers"] == ["b"]
    with (out / "pairwise_pages.csv").open(encoding="utf-8-sig", newline="") as f:
        assert len(list(csv.DictReader(f))) == 0


def test_approved_gt_scores_only_approved_pages(tmp_path):
    manifest, runs = sample(tmp_path)
    gt = tmp_path / "gt.jsonl"
    lines(gt, [
        {"page_id": "case_001:p003", "label_status": "approved", "text_gt": "<b>你好</b>",
         "critical_fields_gt": [{"name": "project", "value": "你好"}]},
        {"page_id": "case_001:p015", "label_status": "unlabeled", "text_gt": "未经审核"},
    ])
    out = tmp_path / "scored"
    result = build_report(manifest=manifest, prediction_files=runs, out=out, truth=gt)
    assert result["quality"] == "GT_SCORED_APPROVED_PAGES_ONLY"
    row = next(r for r in result["summaries"] if r["provider"] == "a")
    assert row["scored_gt_pages"] == 1
    assert row["micro_cer_pct"] == 0
    assert row["field_literal_recall_pct"] == 100
    assert row["mean_gt_fragment_recall_pct"] == 100
    with (out / "page_provider_details.csv").open(encoding="utf-8-sig", newline="") as f:
        details = list(csv.DictReader(f))
    assert [r["cer_pct"] for r in details if r["provider"] == "a"] == ["0.0", ""]
