"""Regression: pdfplumber can rasterize a valid subpixel PDF region to 0x0.

Exercise the real PDF->pdfplumber->PIL render path, without OCR models.
This is the Stage 9.1 failure observed in JudgeAI project 0030.
"""
from __future__ import annotations

from pathlib import Path

import pdfplumber
import pytest
from PIL import Image

from pdffast.fallback.planner import (
    TASK_INLINE_CONTEXT_FALLBACK,
    TASK_PAGE_FALLBACK,
    TASK_REGION_FALLBACK,
    raster_safe_region_bbox,
    render_task_inputs,
)


def blank_pdf(path: Path) -> Path:
    """Construct a single blank 100pt page without extra test dependencies."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(offsets)} >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(data)
    return path


def task(kind: str, id: str, box: dict | None = None) -> dict:
    return {
        "task_id": id,
        "task_type": kind,
        "page_number": 1,
        "source_id": id,
        "source_bbox": box,
    }


def test_real_pdf_tiny_region_and_inline_context_render_nonempty_pngs(tmp_path):
    pdf = blank_pdf(tmp_path / "tiny.pdf")
    center = {"x0": 15, "top": 18, "x1": 15.015, "bottom": 18.015}
    edge = {"x0": 0, "top": 0, "x1": 0.001, "bottom": 0.001}

    # Confirm the historical bug is actually reproducible at 300 DPI.
    with pdfplumber.open(pdf) as source:
        original = source.pages[0].crop((15, 18, 15.015, 18.015), strict=False)
        assert original.to_image(resolution=300).original.size == (0, 0)

    tasks = [
        task(TASK_REGION_FALLBACK, "region-mini", center.copy()),
        task(TASK_INLINE_CONTEXT_FALLBACK, "inline-edge", edge.copy()),
    ]
    render_task_inputs(pdf, tasks, tmp_path / "outputs", page_dpi=300, region_dpi=300)

    assert tasks[0]["source_bbox"] == center
    assert tasks[1]["source_bbox"] == edge
    for current in tasks:
        with Image.open(current["input_image"]) as img:
            assert img.width >= 1 and img.height >= 1
            img.verify()
        assert current["render"]["raster_bbox_adjusted"] is True
        raster = current["render"]["raster_bbox"]
        assert 0 <= raster["x0"] < raster["x1"] <= 100
        assert 0 <= raster["top"] < raster["bottom"] <= 100


def test_normal_region_bbox_remains_unchanged_and_page_path_unmodified(tmp_path):
    pdf = blank_pdf(tmp_path / "normal.pdf")
    box = {"x0": 20, "top": 30, "x1": 40, "bottom": 55}
    tasks = [
        task(TASK_REGION_FALLBACK, "regular", box.copy()),
        task(TASK_PAGE_FALLBACK, "page"),
    ]
    render_task_inputs(pdf, tasks, tmp_path / "outputs", page_dpi=144, region_dpi=300)
    assert tasks[0]["render"]["raster_bbox_adjusted"] is False
    assert tasks[0]["render"]["raster_bbox"] == box
    with Image.open(tasks[0]["input_image"]) as img:
        assert img.width > 20 and img.height > 20
    with Image.open(tasks[1]["input_image"]) as img:
        assert img.width > 0 and img.height > 0
    assert tasks[1]["render"] == {"renderer": "pdfplumber", "dpi": 144}


@pytest.mark.parametrize("bbox", [
    {"x0": 150, "top": 20, "x1": 151, "bottom": 25},
    {"x0": 20, "top": 20, "x1": 10, "bottom": 25},
    {"x0": 20, "top": 20, "x1": float("nan"), "bottom": 25},
    {"x0": 20, "top": 20, "x1": 25},
])
def test_invalid_bbox_never_emits_a_fake_ocr_image(tmp_path, bbox):
    pdf = blank_pdf(tmp_path / "invalid.pdf")
    tasks = [task(TASK_REGION_FALLBACK, "invalid-region", bbox)]
    with pytest.raises(ValueError, match="invalid-region"):
        render_task_inputs(pdf, tasks, tmp_path / "outputs", 300, 300)
    assert tasks[0].get("input_image") is None
    assert not list((tmp_path / "outputs").rglob("*.png"))


def test_minimum_pixel_expansion_remains_clipped_to_page_boundary():
    original = {"x0": 99.999, "top": 99.999, "x1": 100, "bottom": 100}
    x0, top, x1, bottom = raster_safe_region_bbox(
        original, (0, 0, 100, 100), 300, task_id="edge"
    )
    assert x1 == 100 and bottom == 100
    assert (x1 - x0) >= 2 * 72 / 300 - 1e-8
    assert (bottom - top) >= 2 * 72 / 300 - 1e-8
