import json

import pytest

from tools.provider_benchmark.prepare_omnidocbench_stratified import (
    get_stratum,
    prepare_stratified,
    select_stratified,
)


def sample(kind, i):
    subset = kind if kind in {"table_hard", "equation_hard", "layout_hard"} else "v1.5"
    return {
        "page_info": {
            "image_path": f"{i}.png",
            "page_attribute": {
                "language": "simplified_chinese",
                "subset": subset,
                "data_source": "research_report" if kind == "research_report" else "book",
                "layout": "single_column",
            },
        },
        "layout_dets": [{"category_type": "text_block", "text": "科研项目内容" * 25, "ignore": False}],
    }


def test_classification_is_conservative():
    base = sample("text_baseline", 0)
    assert get_stratum(base) == "text_baseline"
    base["layout_dets"].append({"category_type": "table", "text": "a"})
    assert get_stratum(base) is None
    base["layout_dets"].pop()
    base["layout_dets"][0]["text"] = "短"
    assert get_stratum(base) is None
    assert get_stratum(sample("research_report", 1)) == "research_report"


def test_fixed_nonoverlapping_strata(tmp_path):
    kinds = ["table_hard", "equation_hard", "layout_hard", "research_report", "text_baseline"]
    rows = [sample(kind, f"{kind}_{i}") for kind in kinds for i in range(3)]
    for item in rows:
        (tmp_path / item["page_info"]["image_path"]).write_bytes(b"dummy")
    quotas = {kind: 2 for kind in kinds}
    a = select_stratified(rows, images_root=tmp_path, seed=42, quotas=quotas)
    b = select_stratified(rows, images_root=tmp_path, seed=42, quotas=quotas)
    assert a == b
    assert len(a) == len({index for index, _, _ in a}) == 10
    with pytest.raises(ValueError, match="insufficient"):
        select_stratified(rows, images_root=tmp_path, quotas={kind: 4 for kind in kinds})


def test_build_manifest_with_real_image(tmp_path):
    fitz = pytest.importorskip("fitz")
    annotations = tmp_path / "OmniDocBench.json"
    images = tmp_path / "images"
    images.mkdir()
    kinds = ["table_hard", "equation_hard", "layout_hard", "research_report", "text_baseline"]
    samples = [sample(kind, kind) for kind in kinds]
    for kind in kinds:
        pix = fitz.Pixmap(fitz.csRGB, (0, 0, 80, 120), 0)
        pix.clear_with(255)
        pix.save(images / f"{kind}.png")
    annotations.write_text(json.dumps(samples, ensure_ascii=False), encoding="utf-8")
    result = prepare_stratified(
        annotations_path=annotations, images_root=images,
        output_dir=tmp_path / "output", quotas={kind: 1 for kind in kinds}
    )
    rows = [json.loads(x) for x in (tmp_path / "output/manifest.jsonl").read_text().splitlines()]
    assert len(rows) == 5
    assert set(result["actual"]) == set(kinds)
    assert len(set(row["page_id"] for row in rows)) == 5
    for row in rows:
        assert (tmp_path / "output" / row["pdf"]).is_file()
        assert row["ground_truth_status"] == "OFFICIAL_ANNOTATION_NOT_CONVERTED"
        with fitz.open(tmp_path / "output" / row["pdf"]) as doc:
            assert len(doc) == 1
            assert not doc[0].get_text().strip()
