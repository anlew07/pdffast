"""Prepare selected OmniDocBench official GT and per-Provider Markdown for official end2end evaluation.

No OCR inference and no hand-crafted CER/accuracy. Keeps official annotation objects
unchanged, preserving ignore/order/relation/table HTML/formula LaTeX metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SUCCESS = frozenset({"SUCCESS", "SUCCESS_WITH_WARNINGS"})
SAFE_PROVIDER = re.compile(r"^[A-Za-z0-9_.-]+$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path}:{number}: expected JSON object")
        result.append(item)
    return result


def expected_fingerprint(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def render_eval_config(*, gt: Path, predictions: Path) -> str:
    """Return config for official end2end evaluator, excluding CDM/TeX dependency."""
    gt_value, pred_value = json.dumps(str(gt)), json.dumps(str(predictions))
    return (
        "end2end_eval:\n"
        "  metrics:\n"
        "    text_block:\n"
        "      metric: [Edit_dist]\n"
        "    display_formula:\n"
        "      metric: [Edit_dist]\n"
        "    table:\n"
        "      metric: [TEDS, Edit_dist]\n"
        "      teds_workers: 2\n"
        "    reading_order:\n"
        "      metric: [Edit_dist]\n"
        "  dataset:\n"
        "    dataset_name: end2end_dataset\n"
        "    ground_truth:\n"
        f"      data_path: {gt_value}\n"
        "    prediction:\n"
        f"      data_path: {pred_value}\n"
        "    match_method: quick_match\n"
        "    match_workers: 2\n"
    )


def export_official_evaluation(
    *, annotations: Path, manifest: Path, output_dir: Path,
    prediction_files: list[Path] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    annotations = annotations.resolve()
    manifest = manifest.resolve()
    output_dir = output_dir.resolve()
    raw_gt = annotations.read_bytes()
    annotated_pages = json.loads(raw_gt)
    if not isinstance(annotated_pages, list):
        raise ValueError("official annotations must be a JSON list")
    rows = read_jsonl(manifest)
    if not rows:
        raise ValueError("empty benchmark manifest")
    ids = [row.get("page_id") for row in rows]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) for i in ids):
        raise ValueError("duplicate or invalid page_id")
    fingerprint = expected_fingerprint(rows)

    selection_file = manifest.parent / "selection.json"
    selection = json.loads(selection_file.read_text(encoding="utf-8")) if selection_file.exists() else {}
    annotations_sha = hashlib.sha256(raw_gt).hexdigest()
    if selection.get("official_annotations_sha256") and selection["official_annotations_sha256"] != annotations_sha:
        raise ValueError("official annotation fingerprint differs from selection.json")

    subset, image_to_page = [], {}
    for row in rows:
        index = row.get("source_annotation_index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(annotated_pages):
            raise ValueError(f"invalid source_annotation_index for {row.get('page_id')}")
        page_id = f"omnidocbench_{index:05d}"
        if row["page_id"] != page_id:
            raise ValueError(f"manifest page_id/index mismatch: {row['page_id']} != {page_id}")
        page = annotated_pages[index]
        if not isinstance(page, dict):
            raise ValueError(f"official annotation {index} is not a JSON object")
        info = page.get("page_info") or {}
        image_name = Path(str(info.get("image_path") or "")).name
        if not image_name or row.get("source_image_name") != image_name:
            raise ValueError(f"official image name mismatch for {page_id}")
        if Path(image_name).suffix.lower() not in (".png", ".jpg"):
            raise ValueError(f"unsupported official image extension: {image_name}")
        md_filename = Path(image_name).stem + ".md"
        if md_filename in image_to_page:
            raise ValueError(f"duplicate official MD filename {md_filename}")
        if index in [i.get("source_annotation_index") for i in rows if i is not row]:
            raise ValueError(f"duplicate source_annotation_index {index}")
        image_to_page[md_filename] = row["page_id"]
        subset.append(page)  # full original official GT object, never concatenated text

    gt_file = output_dir / "OmniDocBench.selected.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    gt_file.write_text(json.dumps(subset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results = []
    excluded = set(exclude or [])
    records: dict[tuple[str, str], dict[str, Any]] = {}
    providers: list[str] = []
    for filename in prediction_files or []:
        path = Path(filename).resolve()
        run_path = path.parent / "run_manifest.json"
        if run_path.is_file():
            run_meta = json.loads(run_path.read_text(encoding="utf-8"))
            run_fp = run_meta.get("dataset_fingerprint_sha256")
            if run_fp and run_fp != fingerprint:
                raise ValueError(f"prediction dataset fingerprint mismatch: {path}")
        for rec in read_jsonl(path):
            pid, provider = rec.get("page_id"), rec.get("provider")
            if pid == "__teardown__":
                continue
            if not isinstance(provider, str) or not SAFE_PROVIDER.fullmatch(provider):
                raise ValueError(f"invalid provider label in {path}")
            if provider in excluded:
                continue
            if pid not in ids:
                raise ValueError(f"prediction has page not selected by manifest: {pid}")
            key = (pid, provider)
            if key in records:
                raise ValueError(f"duplicate Provider prediction: {key}")
            records[key] = rec
            if provider not in providers:
                providers.append(provider)
    for provider in providers:
        directory = output_dir / "predictions" / provider
        directory.mkdir(parents=True, exist_ok=True)
        statuses = Counter()
        for md_filename, page_id in image_to_page.items():
            rec = records.get((page_id, provider))
            status = str(rec.get("status") or "MISSING") if rec else "MISSING"
            statuses[status] += 1
            raw = rec.get("text") if rec and status in SUCCESS else ""
            value = raw if isinstance(raw, str) else ""
            # An empty .md explicitly represents a missing, failed, or empty
            # prediction, so the official evaluator does not silently skip it.
            (directory / md_filename).write_text(value, encoding="utf-8")
        config_path = output_dir / "configs" / f"{provider}.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            render_eval_config(gt=gt_file, predictions=directory), encoding="utf-8"
        )
        results.append({
            "provider": provider, "status_counts": dict(statuses),
            "prediction_dir": str(directory), "config": str(config_path),
            "empty_or_failed_predictions": sum(statuses[k] for k in statuses if k not in SUCCESS)
            + sum(not isinstance(records.get((pid, provider), {}).get("text"), str)
                  or not records.get((pid, provider), {}).get("text", "").strip()
                  for pid in ids if records.get((pid, provider), {}).get("status") in SUCCESS),
        })
    output = {
        "source_annotations": str(annotations),
        "source_sha256": annotations_sha,
        "manifest": str(manifest),
        "dataset_fingerprint_sha256": fingerprint,
        "selected_pages": len(rows),
        "official_gt": str(gt_file),
        "providers": results,
        "excluded_providers": sorted(excluded),
        "scoring": "NOT_RUN_OFFICIAL_EVALUATOR_REQUIRED",
        "warning": "Raster-only PDF inputs are not native-layer PDF classification tests. "
                   "Predictions contain plain canonical text; unsupported structured capabilities "
                   "must be marked N/A instead of interpreted as valid table/layout scores.",
    }
    (output_dir / "export_manifest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Export subset official GT and Provider predictions")
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--predictions", nargs="*", type=Path, default=[])
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = export_official_evaluation(
        annotations=args.annotations, manifest=args.manifest,
        prediction_files=args.predictions, output_dir=args.out, exclude=args.exclude
    )
    print(json.dumps({
        "selected_pages": out["selected_pages"],
        "gt_file": out["official_gt"],
        "providers_exported": [p["provider"] for p in out["providers"]],
        "scoring": out["scoring"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
