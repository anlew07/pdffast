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
