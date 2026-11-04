from __future__ import annotations

import json

import pytest

from tools.provider_benchmark.prepare_omnidocbench import select_and_prepare


def test_public_subset_is_deterministic_and_preserves_gt(tmp_path):
    fitz = pytest.importorskip("fitz")
    images = tmp_path / "images"
    images.mkdir()
    ann = []
    for i in range(3):
        image_path = images / f"p{i}.png"
        with fitz.open() as pdf:
            page = pdf.new_page(width=100, height=100)
            pix = page.get_pixmap()
            pix.save(image_path)
        ann.append({"page_info": {
            "image_path": f"images/p{i}.png",
            "page_attribute": {"language": "chinese", "data_source": "research_report"},
        }, "layout_dets": [{"category_type": "text_block", "text": "GT-do-not-erase"}]})
    first = select_and_prepare(ann, images_root=images, output_dir=tmp_path / "one", limit=2, seed=11, language="chinese")
    second = select_and_prepare(ann, images_root=images, output_dir=tmp_path / "two", limit=2, seed=11, language="chinese")
    assert [x["source_annotation_index"] for x in first] == [x["source_annotation_index"] for x in second]
    assert all(x["ground_truth_status"] == "OFFICIAL_ANNOTATION_NOT_CONVERTED" for x in first)
    assert all((tmp_path / "one" / x["pdf"]).is_file() for x in first)
    assert all(item["layout_dets"][0]["text"] == "GT-do-not-erase" for item in ann)
