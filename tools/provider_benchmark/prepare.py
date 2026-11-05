"""Prepare fixed-DPI image/PDF pairs from a private page selection JSONL.

Each PDF output is raster-only to prevent PDF Workers from benefiting from an
embedded native text layer while text OCR receives a screenshot. Not a claim
that all engines use identical internal preprocessing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_pages(
    selections: list[dict[str, Any]],
    *,
    pdf_dir: Path,
    output_dir: Path,
    dpi: int = 200,
) -> list[dict[str, Any]]:
    if not 72 <= dpi <= 400:
        raise ValueError("dpi must be between 72 and 400")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("install PyMuPDF to prepare benchmark images") from exc
    pdf_dir = Path(pdf_dir)
    output_dir = Path(output_dir)
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    pdf_hashes: dict[str, str] = {}
    seen: set[str] = set()
    for row in selections:
        page_id = row.get("page_id")
        if not isinstance(page_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", page_id):
            raise ValueError(f"unsafe page_id: {page_id!r}")
        if page_id in seen:
            raise ValueError(f"duplicate page_id: {page_id}")
        seen.add(page_id)
        pdf_name = str(row.get("pdf_filename") or "")
        if Path(pdf_name).name != pdf_name or not pdf_name.lower().endswith(".pdf"):
            raise ValueError(f"{page_id}: pdf_filename must be a PDF basename")
        path = pdf_dir / pdf_name
        if not path.is_file():
            raise FileNotFoundError(f"{page_id}: source PDF not found: {path}")
        if pdf_name not in pdf_hashes:
            pdf_hashes[pdf_name] = _sha256(path)
        expected = row.get("pdf_sha256")
        if expected and expected != pdf_hashes[pdf_name]:
            raise ValueError(f"{page_id}: PDF SHA-256 mismatch")
        page_number = row.get("page_number")
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
            raise ValueError(f"{page_id}: page_number must be 1-based positive integer")
        with fitz.open(path) as original:
            if page_number > len(original):
                raise ValueError(f"{page_id}: page_number exceeds PDF page_count")
            page = original[page_number - 1]
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            png = pix.tobytes("png")
        stem = re.sub(r"[^A-Za-z0-9_.-]", "_", page_id) + "_" + hashlib.sha256(page_id.encode()).hexdigest()[:8]
        image = assets / (stem + ".png")
        raster_pdf = assets / (stem + ".pdf")
        image.write_bytes(png)
        with fitz.open() as out_pdf:
            width_pt, height_pt = pix.width * 72 / dpi, pix.height * 72 / dpi
            out_page = out_pdf.new_page(width=width_pt, height=height_pt)
            out_page.insert_image(out_page.rect, stream=png)
            out_pdf.save(raster_pdf, garbage=4, deflate=True)
        records.append({
            "page_id": page_id,
            "document_id": row.get("document_id"),
            "page_number": page_number,
            "capability_route": row.get("capability_route", "PAGE_DOCUMENT_OCR"),
            "image": str(image.relative_to(output_dir)),
            "pdf": str(raster_pdf.relative_to(output_dir)),
            "source_pdf_sha256": pdf_hashes[pdf_name],
            "render_dpi": dpi,
            "input_type": "raster_only_pdf_and_png",
            "selection_reason": row.get("selection_reason", "external"),
        })
    (output_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    (output_dir / "dataset_info.json").write_text(
        json.dumps({
            "page_count": len(records), "dpi": dpi,
            "source_document_count": len(pdf_hashes),
            "ground_truth": "NOT_INCLUDED",
            "comparison": "visual_only_raster_assets",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare private fixed-DPI Provider Benchmark assets")
    ap.add_argument("--pages", type=Path, required=True, help="pilot_pages.jsonl or compatible")
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    from tools.provider_benchmark.run import read_jsonl
    items = prepare_pages(read_jsonl(a.pages), pdf_dir=a.pdf_dir, output_dir=a.out, dpi=a.dpi)
    print(f"Prepared {len(items)} raster-only page pairs: {a.out / 'manifest.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
