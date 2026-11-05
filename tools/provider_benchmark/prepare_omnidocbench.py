"""Select a small, reproducible subset of locally obtained OmniDocBench images.

Research-only dataset: this script never downloads or republishes source data.
Keep official OmniDocBench annotations unchanged and use its official evaluator
for table/formula/layout/read-order scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any


def select_and_prepare(
    annotations: list[dict[str, Any]],
    *,
    images_root: Path,
    output_dir: Path,
    limit: int = 30,
    seed: int = 42,
    language: str | None = None,
    data_source: str | None = None,
    dpi: int = 200,
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if not 72 <= dpi <= 400:
        raise ValueError("dpi must be between 72 and 400")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to create raster PDF inputs") from exc
    images_root, output_dir = Path(images_root), Path(output_dir)
    candidates = []
    for i, sample in enumerate(annotations):
        info = sample.get("page_info") or {}
        attr = info.get("page_attribute") or {}
        if language and str(attr.get("language", "")).lower() != language.lower():
            continue
        if data_source and str(attr.get("data_source", "")).lower() != data_source.lower():
            continue
        ref = info.get("image_path")
        if not isinstance(ref, str) or not ref:
            continue
        path = images_root / Path(ref).name
        if not path.is_file():
            path = images_root / ref
        if not path.is_file():
            continue
        candidates.append((i, info, path))
    if not candidates:
        raise ValueError("no matching available images; check filters and images_root")
    random.Random(seed).shuffle(candidates)
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    selected = []
    for index, info, image in candidates[:limit]:
        page_id = f"omnidocbench_{index:05d}"
        input_bytes = image.read_bytes()
        with fitz.open(image) as input_image:
            page = input_image[0]
            pix = page.get_pixmap()
            width, height = pix.width, pix.height
        pdf_path = assets / f"{page_id}.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page(width=width * 72 / dpi, height=height * 72 / dpi)
            page.insert_image(page.rect, stream=input_bytes)
            pdf.save(pdf_path, garbage=4, deflate=True)
        selected.append({
            "page_id": page_id,
            "page_number": 1,
            "capability_route": "PAGE_DOCUMENT_LAYOUT_PARSE",
            "image": str(image.resolve()),
            "pdf": str(pdf_path.relative_to(output_dir)),
            "source_dataset": "opendatalab/OmniDocBench",
            "source_annotation_index": index,
            "source_image_name": image.name,
            "input_image_sha256": hashlib.sha256(input_bytes).hexdigest(),
            "raster_pdf_assumed_dpi": dpi,
            "ground_truth_status": "OFFICIAL_ANNOTATION_NOT_CONVERTED",
        })
    (output_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected),
        encoding="utf-8",
    )
    (output_dir / "selection.json").write_text(
        json.dumps({
            "dataset": "OmniDocBench", "annotation_indices": [x["source_annotation_index"] for x in selected],
            "seed": seed, "limit": limit,
            "filters": {"language": language, "data_source": data_source},
            "license_note": "OmniDocBench dataset is research-only/noncommercial per official repository",
            "official_ground_truth_conversion": "NOT_IMPLEMENTED",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return selected


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare a local research-only OmniDocBench subset")
    ap.add_argument("--annotations", type=Path, required=True, help="OmniDocBench.json")
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--language")
    ap.add_argument("--data-source")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    annotations = json.loads(a.annotations.read_text(encoding="utf-8"))
    if not isinstance(annotations, list):
        raise ValueError("OmniDocBench annotations root must be a JSON array")
    selected = select_and_prepare(
        annotations, images_root=a.images_root, output_dir=a.out,
        limit=a.limit, seed=a.seed, language=a.language,
        data_source=a.data_source, dpi=a.dpi,
    )
    print(f"Prepared {len(selected)} OmniDocBench pages (official GT unchanged): {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
