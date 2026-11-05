"""Prepare a reproducible, non-overlapping 60-page Chinese OmniDocBench subset.

This tool samples official labels without converting them into text Ground Truth.
It creates single-image PDFs solely to make PDF-only Provider inputs comparable.
Source annotations and images must have been obtained lawfully and stay local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

QUOTAS = {
    "table_hard": 15,
    "equation_hard": 10,
    "layout_hard": 10,
    "research_report": 10,
    "text_baseline": 15,
}
TEXT_CATEGORIES = {
    "title", "text_block", "list_group", "reference", "header", "footer",
    "page_number", "page_footnote", "page_header", "page_footer", "figure_caption",
    "figure_footnote", "table_caption", "table_footnote", "equation_caption",
}
EXCLUDED_TEXT_BASELINE = {
    "table", "figure", "equation_isolated", "equation_semantic",
    "equation_explanation", "chart", "image", "algorithm", "code",
}


def get_stratum(sample: dict[str, Any]) -> str | None:
    info = sample.get("page_info") or {}
    attr = info.get("page_attribute") or {}
    if attr.get("language") != "simplified_chinese":
        return None
    subset = attr.get("subset")
    if subset in {"table_hard", "equation_hard", "layout_hard"}:
        return str(subset)
    if subset != "v1.5":
        return None
    if attr.get("data_source") == "research_report":
        return "research_report"
    if attr.get("layout") != "single_column":
        return None
    # A single-column page is not necessarily plain text. Exclude pages
    # containing structural objects and require substantial body content.
    boxes = [box for box in sample.get("layout_dets") or []
             if isinstance(box, dict) and box.get("ignore") is not True]
    labels = {str(box.get("category_type") or "") for box in boxes}
    if labels & EXCLUDED_TEXT_BASELINE:
        return None
    if labels - TEXT_CATEGORIES:
        return None  # avoid asserting that an unknown annotation type is plain text
    body_text = "".join(str(box.get("text") or "") for box in boxes
                        if box.get("category_type") == "text_block")
    if len("".join(body_text.split())) < 80:
        return None
    return "text_baseline"


def source_image(images_root: Path, sample: dict[str, Any]) -> Path | None:
    info = sample.get("page_info") or {}
    raw = info.get("image_path")
    if not isinstance(raw, str) or not raw:
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = images_root.resolve()
    for candidate in (root / relative.name, root / relative):
        candidate = candidate.resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return None


def select_stratified(
    annotations: list[dict[str, Any]], *, images_root: Path, seed: int = 42,
    quotas: dict[str, int] | None = None,
) -> list[tuple[int, str, Path]]:
    """Return stable (source index, stratum, image) triples with no duplicates."""
    desired = dict(quotas or QUOTAS)
    if not desired or any(k not in QUOTAS or not isinstance(v, int) or v < 1
                          for k, v in desired.items()):
        raise ValueError("quotas must be positive values for supported strata")
    pools: dict[str, list[tuple[int, str, Path]]] = {key: [] for key in desired}
    for index, sample in enumerate(annotations):
        if not isinstance(sample, dict):
            continue
        kind = get_stratum(sample)
        if kind not in pools:
            continue
        path = source_image(images_root, sample)
        if path is not None:
            pools[kind].append((index, kind, path))
    rng = random.Random(seed)
    chosen = []
    shortages = {}
    for kind, count in desired.items():
        pool = pools[kind].copy()
        rng.shuffle(pool)
        if len(pool) < count:
            shortages[kind] = {"requested": count, "available": len(pool)}
        else:
            chosen.extend(pool[:count])
    if shortages:
        raise ValueError(f"insufficient OmniDocBench category/image coverage: {shortages}")
    assert len(chosen) == len(set(index for index, _, _ in chosen))
    return chosen


def prepare_stratified(
    *, annotations_path: Path, images_root: Path, output_dir: Path,
    seed: int = 42, dpi: int = 200, quotas: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not 72 <= dpi <= 400:
        raise ValueError("dpi must be between 72 and 400")
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required; use uv run --with pymupdf") from exc
    annotations_path = annotations_path.resolve()
    raw_annotations = annotations_path.read_bytes()
    data = json.loads(raw_annotations)
    if not isinstance(data, list):
        raise ValueError("OmniDocBench.json must contain a JSON array")
    desired = dict(quotas or QUOTAS)
    selected = select_stratified(data, images_root=images_root, seed=seed, quotas=desired)
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    annotation_sha256 = hashlib.sha256(raw_annotations).hexdigest()
    manifest = []
    for index, category, image in selected:
        page_id = f"omnidocbench_{index:05d}"
        image_bytes = image.read_bytes()
        with fitz.open(stream=image_bytes, filetype=image.suffix.lstrip(".")) as im:
            pix = im[0].get_pixmap()
            width, height = pix.width, pix.height
        pdf_path = assets_dir / f"{page_id}.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page(width=width * 72 / dpi, height=height * 72 / dpi)
            page.insert_image(page.rect, stream=image_bytes)
            pdf.save(pdf_path, garbage=4, deflate=True)
        info = data[index]["page_info"]
        manifest.append({
            "page_id": page_id,
            "page_number": 1,
            "benchmark_stratum": category,
            "capability_route": "PAGE_DOCUMENT_LAYOUT_PARSE",
            "image": str(image),
            "pdf": str(pdf_path.relative_to(output_dir)),
            "source_dataset": "opendatalab/OmniDocBench",
            "source_annotation_index": index,
            "source_image_name": image.name,
            "source_page_attribute": info.get("page_attribute", {}),
            "input_image_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "raster_pdf_assumed_dpi": dpi,
            "ground_truth_status": "OFFICIAL_ANNOTATION_NOT_CONVERTED",
        })
    (output_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in manifest),
        encoding="utf-8",
    )
    selection = {
        "dataset": "OmniDocBench",
        "strategy": "chinese_stratified_60_v1",
        "language": "simplified_chinese",
        "seed": seed,
        "dpi": dpi,
        "quotas": desired,
        "actual": dict(Counter(row["benchmark_stratum"] for row in manifest)),
        "selected_indices": [row["source_annotation_index"] for row in manifest],
        "official_annotations_sha256": annotation_sha256,
        "official_annotation_path": str(annotations_path),
        "ground_truth_conversion": "NOT_IMPLEMENTED",
        "license_note": "Official OmniDocBench is research-only/noncommercial; confirm rights before company use",
    }
    (output_dir / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return selection


def main() -> int:
    parser = argparse.ArgumentParser(description="Select 60 unique Chinese OmniDocBench pages by category")
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--images-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    selection = prepare_stratified(
        annotations_path=args.annotations,
        images_root=args.images_root,
        output_dir=args.out,
        seed=args.seed,
        dpi=args.dpi,
    )
    print(json.dumps({
        "selected": len(selection["selected_indices"]),
        "quotas": selection["actual"],
        "annotation_sha256": selection["official_annotations_sha256"],
        "output_dir": str(args.out),
        "ground_truth": selection["ground_truth_conversion"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
