import hashlib
import json

import pytest

from tools.provider_benchmark.omnidocbench_official import prepare_gt, export_predictions


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def sample(tmp_path):
    source = [
        {"page_info": {"image_path": "alpha.png"}, "layout_dets": [{"text": "你好", "order": 0}], "extra": {"relation": []}},
        {"page_info": {"image_path": "unused.png"}, "layout_dets": []},
        {"page_info": {"image_path": "beta.png"}, "layout_dets": [{"html": "<table></table>"}], "extra": {"relation": []}},
    ]
    annotations = tmp_path / "OmniDocBench.json"
    annotations.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    manifest = tmp_path / "subset/manifest.jsonl"
    write_jsonl(manifest, [
        {"page_id": "omnidocbench_00000", "source_annotation_index": 0,
         "source_image_name": "alpha.png", "benchmark_stratum": "text_baseline"},
        {"page_id": "omnidocbench_00002", "source_annotation_index": 2,
         "source_image_name": "beta.png", "benchmark_stratum": "table_hard"},
    ])
    (manifest.parent / "selection.json").write_text(json.dumps({
        "official_annotations_sha256": hashlib.sha256(annotations.read_bytes()).hexdigest()
    }))
    return manifest, annotations, source


def test_original_gt_and_names_are_preserved(tmp_path):
    manifest, annotations, source = sample(tmp_path)
    info = prepare_gt(manifest=manifest, annotations=annotations, out=tmp_path / "gt")
    assert info["pages"] == 2
    assert info["by_stratum"] == {"text_baseline": 1, "table_hard": 1}
    assert json.loads((tmp_path / "gt/official_gt_subset.json").read_text()) == [source[0], source[2]]
    mapping = [json.loads(line) for line in (tmp_path / "gt/mapping.jsonl").read_text().splitlines()]
    assert [x["markdown_filename"] for x in mapping] == ["alpha.md", "beta.md"]


def test_dataset_fingerprint_guard(tmp_path):
    manifest, annotations, _ = sample(tmp_path)
    annotations.write_text("[]")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        prepare_gt(manifest=manifest, annotations=annotations, out=tmp_path / "gt")


def test_prediction_export_and_missing_pages(tmp_path):
    manifest, annotations, _ = sample(tmp_path)
    prepare_gt(manifest=manifest, annotations=annotations, out=tmp_path / "gt")
    predictions = tmp_path / "predictions.jsonl"
    write_jsonl(predictions, [
        {"page_id": "omnidocbench_00000", "provider": "rapidocr", "status": "SUCCESS", "text": "你好"},
        {"page_id": "omnidocbench_00002", "provider": "rapidocr", "status": "FAILED"},
        {"page_id": "omnidocbench_00000", "provider": "docling", "status": "SUCCESS", "text": "# 你好"},
    ])
    info = export_predictions(mapping_path=tmp_path / "gt/mapping.jsonl",
                              prediction_files=[predictions], out=tmp_path / "preds")
    assert info["providers"]["rapidocr"]["markdown_files"] == 1
    assert (tmp_path / "preds/rapidocr/alpha.md").read_text() == "你好"
    assert not (tmp_path / "preds/rapidocr/beta.md").exists()
    assert info["providers"]["docling"]["statuses"]["MISSING"] == 1
    with pytest.raises(ValueError, match="not empty"):
        export_predictions(mapping_path=tmp_path / "gt/mapping.jsonl",
                           prediction_files=[predictions], out=tmp_path / "preds")


def test_image_name_mismatch_is_rejected(tmp_path):
    manifest, annotations, _ = sample(tmp_path)
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    rows[0]["source_image_name"] = "wrong.png"
    write_jsonl(manifest, rows)
    with pytest.raises(ValueError, match="source image mismatch"):
        prepare_gt(manifest=manifest, annotations=annotations, out=tmp_path / "gt")
