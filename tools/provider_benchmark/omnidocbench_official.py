"""Lossless 60-page OmniDocBench GT subset and official Markdown prediction export.

Official annotations are preserved, not converted into guessed page text.
Use the OmniDocBench official evaluator for text, table, formula and order scores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

SUCCESS = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
PROVIDER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            rows.append(item)
    return rows


def prepare_gt(*, manifest: Path, annotations: Path, out: Path) -> dict:
    manifest, annotations, out = manifest.resolve(), annotations.resolve(), out.resolve()
    rows = read_jsonl(manifest)
    if not rows:
        raise ValueError("empty benchmark manifest")
    raw = annotations.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    selection_file = manifest.parent / "selection.json"
    if not selection_file.is_file():
        raise ValueError(f"missing selection.json: {selection_file}")
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    if selection.get("official_annotations_sha256") != digest:
        raise ValueError("official annotation SHA256 mismatch")
    source = json.loads(raw)
    if not isinstance(source, list):
        raise ValueError("expected official GT JSON array")
    seen_indices, seen_ids, seen_filenames = set(), set(), set()
    subset, mapping = [], []
    for row in rows:
        pid, index, image = row.get("page_id"), row.get("source_annotation_index"), row.get("source_image_name")
        if not isinstance(pid, str) or not pid or pid in seen_ids:
            raise ValueError(f"invalid/duplicate page_id: {pid!r}")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(source) or index in seen_indices:
            raise ValueError(f"invalid/duplicate official annotation index: {index!r}")
        info = source[index].get("page_info") or {}
        official_image = Path(info.get("image_path") or "").name
        if not isinstance(image, str) or image != official_image or Path(image).name != image:
            raise ValueError(f"source image mismatch at index {index}: {image!r} / {official_image!r}")
        if Path(image).suffix.lower() not in {".png", ".jpg"}:
            raise ValueError(f"unsupported official image filename: {image}")
        filename = image[:-4] + ".md"
        if filename in seen_filenames:
            raise ValueError(f"duplicate official Markdown filename: {filename}")
        seen_ids.add(pid)
        seen_indices.add(index)
        seen_filenames.add(filename)
        subset.append(source[index])  # keep layout_dets, ignore, order, extra, latex, html unchanged
        mapping.append({
            "page_id": pid, "source_annotation_index": index,
            "source_image_name": image, "markdown_filename": filename,
            "benchmark_stratum": row.get("benchmark_stratum"),
        })
    out.mkdir(parents=True, exist_ok=True)
    (out / "official_gt_subset.json").write_text(
        json.dumps(subset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "mapping.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in mapping),
        encoding="utf-8",
    )
    result = {
        "pages": len(mapping),
        "by_stratum": dict(Counter(row["benchmark_stratum"] for row in mapping)),
        "annotation_sha256": digest,
        "quality": "NOT_SCORED_USE_OFFICIAL_EVALUATOR",
        "gt_path": str(out / "official_gt_subset.json"),
        "mapping_path": str(out / "mapping.jsonl"),
    }
    (out / "export_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def export_predictions(*, mapping_path: Path, prediction_files: list[Path], out: Path) -> dict:
    mapping = read_jsonl(mapping_path.resolve())
    if not mapping:
        raise ValueError("empty official mapping")
    page_map = {}
    names = set()
    for item in mapping:
        pid, name = item.get("page_id"), item.get("markdown_filename")
        if not isinstance(pid, str) or not pid or pid in page_map:
            raise ValueError("duplicate/invalid page_id in mapping")
        if not isinstance(name, str) or not name.endswith(".md") or Path(name).name != name or name in names:
            raise ValueError("duplicate/invalid markdown filename in mapping")
        page_map[pid] = name
        names.add(name)
    pairs = {}
    providers = set()
    for path in prediction_files:
        for row in read_jsonl(path.resolve()):
            pid = row.get("page_id")
            if pid == "__teardown__":
                continue
            if pid not in page_map:
                raise ValueError(f"unrecognized prediction page_id: {pid!r}")
            provider = row.get("provider")
            if not isinstance(provider, str) or not PROVIDER.fullmatch(provider):
                raise ValueError(f"invalid provider: {provider!r}")
            key = pid, provider
            if key in pairs:
                raise ValueError(f"duplicate prediction: {key}")
            pairs[key] = row
            providers.add(provider)
    if not providers:
        raise ValueError("no Provider predictions")
    out = out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"prediction output is not empty: {out}; choose a new directory")
    out.mkdir(parents=True, exist_ok=True)
    details = {}
    for provider in sorted(providers):
        provider_dir = out / provider
        provider_dir.mkdir()
        counts = Counter()
        created = 0
        for pid, md_filename in page_map.items():
            item = pairs.get((pid, provider))
            status = item.get("status", "MISSING") if item else "MISSING"
            counts[status] += 1
            if status in SUCCESS and isinstance(item.get("text"), str) and item["text"].strip():
                (provider_dir / md_filename).write_text(item["text"], encoding="utf-8")
                created += 1
        details[provider] = {
            "markdown_files": created, "statuses": dict(counts),
            "path": str(provider_dir),
        }
    result = {
        "expected_pages": len(page_map), "providers": details,
        "note": "Missing/failed outputs are absent Markdown; official evaluator counts them as empty predictions.",
    }
    (out / "prediction_export_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniDocBench official evaluation data bridge")
    sub = parser.add_subparsers(dest="command", required=True)
    pgt = sub.add_parser("prepare-gt")
    pgt.add_argument("--manifest", required=True, type=Path)
    pgt.add_argument("--annotations", required=True, type=Path)
    pgt.add_argument("--out", required=True, type=Path)
    pp = sub.add_parser("export-predictions")
    pp.add_argument("--mapping", required=True, type=Path)
    pp.add_argument("--predictions", required=True, nargs="+", type=Path)
    pp.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    value = (
        prepare_gt(manifest=args.manifest, annotations=args.annotations, out=args.out)
        if args.command == "prepare-gt" else
        export_predictions(mapping_path=args.mapping, prediction_files=args.predictions, out=args.out)
    )
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
