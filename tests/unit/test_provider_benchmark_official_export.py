import hashlib
import json

import pytest

from tools.provider_benchmark.export_omnidocbench_official import (
    expected_fingerprint, export_official_evaluation,
)


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8"
    )


def fixture(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    data = [
        {
            "layout_dets": [
                {"anno_id": i, "category_type": "table", "html": "<table><tr><td>钱</td></tr></table>",
                 "ignore": False, "order": 0},
                {"anno_id": i + 100, "category_type": "equation_isolated", "latex": "$x=2$", "order": 1},
            ],
            "page_info": {"image_path": f"my-page-{i}.png",
                          "page_attribute": {"language": "simplified_chinese"}},
            "extra": {"relation": [{"source_anno_id": i, "target_anno_id": i + 100,
                                   "relation_type": "parent_son"}]},
        }
        for i in range(2)
    ]
    raw = json.dumps(data, ensure_ascii=False).encode()
    annotations = root / "OmniDocBench.json"
    annotations.write_bytes(raw)
    rows = [
        {"page_id": f"omnidocbench_{i:05d}", "source_annotation_index": i,
         "source_image_name": f"my-page-{i}.png", "image": f"/no/need/{i}.png",
         "pdf": f"assets/{i}.pdf", "benchmark_stratum": "table_hard"}
        for i in range(2)
    ]
    manifest = root / "selected/manifest.jsonl"
    jsonl(manifest, rows)
    selection = {"official_annotations_sha256": hashlib.sha256(raw).hexdigest()}
    (manifest.parent / "selection.json").write_text(json.dumps(selection), encoding="utf-8")
    preds = root / "run/predictions.jsonl"
    jsonl(preds, [
        {"page_id": "omnidocbench_00000", "provider": "rapidocr_ch_light",
         "status": "SUCCESS", "text": "研究金额：100万元"},
        {"page_id": "omnidocbench_00001", "provider": "rapidocr_ch_light",
         "status": "FAILED", "text": None},
    ])
    (preds.parent / "run_manifest.json").write_text(
        json.dumps({"dataset_fingerprint_sha256": expected_fingerprint(rows)}), encoding="utf-8"
    )
    return annotations, manifest, preds, data


def test_preserve_official_gt_and_export_md(tmp_path):
    annotations, manifest, predictions, original = fixture(tmp_path)
    output = tmp_path / "official"
    meta = export_official_evaluation(
        annotations=annotations, manifest=manifest,
        prediction_files=[predictions], output_dir=output,
    )
    assert meta["selected_pages"] == 2
    assert meta["scoring"] == "NOT_RUN_OFFICIAL_EVALUATOR_REQUIRED"
    assert json.loads((output / "OmniDocBench.selected.json").read_text()) == original
    page0 = output / "predictions/rapidocr_ch_light/my-page-0.md"
    page1 = output / "predictions/rapidocr_ch_light/my-page-1.md"
    assert page0.read_text() == "研究金额：100万元"
    assert page1.is_file() and page1.read_text() == ""
    config = (output / "configs/rapidocr_ch_light.yaml").read_text()
    assert "match_method: quick_match" in config
    assert "CDM" not in config
    assert "TEDS" in config
    assert "OmniDocBench.selected.json" in config


def test_gt_only_does_not_write_false_scores(tmp_path):
    annotations, manifest, _, original = fixture(tmp_path)
    meta = export_official_evaluation(
        annotations=annotations, manifest=manifest, output_dir=tmp_path / "gt_only"
    )
    assert meta["providers"] == []
    assert meta["scoring"] == "NOT_RUN_OFFICIAL_EVALUATOR_REQUIRED"
    assert len(json.loads((tmp_path / "gt_only/OmniDocBench.selected.json").read_text())) == 2


def test_mismatched_fingerprint_rejected(tmp_path):
    annotations, manifest, pred, _ = fixture(tmp_path)
    (pred.parent / "run_manifest.json").write_text(
        json.dumps({"dataset_fingerprint_sha256": "invalid"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        export_official_evaluation(
            annotations=annotations, manifest=manifest,
            prediction_files=[pred], output_dir=tmp_path / "bad",
        )


def test_wrong_source_image_rejected(tmp_path):
    annotations, manifest, _, _ = fixture(tmp_path)
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    rows[0]["source_image_name"] = "wrong.png"
    jsonl(manifest, rows)
    with pytest.raises(ValueError, match="image name mismatch"):
        export_official_evaluation(
            annotations=annotations, manifest=manifest, output_dir=tmp_path / "bad",
        )
