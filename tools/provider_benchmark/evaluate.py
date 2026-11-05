"""Basic Provider Benchmark metrics: never infer quality without approved GT.

For table structure/formula/layout metrics use dataset-specific evaluators
(e.g. OmniDocBench official evaluator) instead of inventing a proxy score.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SUCCESS = frozenset({"SUCCESS", "SUCCESS_WITH_WARNINGS"})
APPROVED = frozenset({"reviewed", "approved"})


def _plain(value: str) -> str:
    return "".join(value.split())


def _distance(a: str, b: str) -> int:
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(a, b)
    except ImportError:
        pass
    if len(a) < len(b):
        a, b = b, a
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = new
    return row[-1]


def _p95(data: list[float]) -> float | None:
    if not data:
        return None
    ordered = sorted(data)
    pos = (len(ordered) - 1) * .95
    lo, hi = math.floor(pos), math.ceil(pos)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 5)


def evaluate(
    truth: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pages = {}
    for entry in truth:
        key = entry["page_id"]
        if key in pages:
            raise ValueError(f"duplicate ground-truth page_id: {key}")
        pages[key] = entry
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for pred in predictions:
        provider, page_id = pred["provider"], pred["page_id"]
        if page_id == "__teardown__":
            continue
        if page_id in grouped[provider]:
            raise ValueError(f"duplicate Provider prediction: {provider}/{page_id}")
        grouped[provider][page_id] = pred
    summaries: list[dict[str, Any]] = []
    for provider, rows in sorted(grouped.items()):
        statuses = Counter()
        successful = 0
        times = []
        char_total = edits = scored = 0
        field_total = field_found = 0
        for pid, entry in pages.items():
            pred = rows.get(pid)
            status = str(pred.get("status", "MISSING")) if pred else "MISSING"
            statuses[status] += 1
            if pred is None:
                continue
            ok = status in SUCCESS
            if ok:
                successful += 1
            elapsed = pred.get("elapsed_seconds")
            if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and math.isfinite(elapsed) and elapsed >= 0:
                times.append(float(elapsed))
            if not ok or entry.get("label_status") not in APPROVED:
                continue
            gt = entry.get("text_gt")
            prediction_text = pred.get("text")
            if isinstance(gt, str) and isinstance(prediction_text, str):
                normalized_gt, normalized_pred = _plain(gt), _plain(prediction_text)
                if normalized_gt:
                    char_total += len(normalized_gt)
                    edits += _distance(normalized_gt, normalized_pred)
                    scored += 1
            # Literal presence is a recall-oriented proxy; it does not prove
            # correct key-value association (that needs manual/structural GT).
            for item in entry.get("critical_fields_gt") or []:
                val = item.get("value")
                if isinstance(val, str) and val.strip() and isinstance(prediction_text, str):
                    field_total += 1
                    field_found += _plain(val) in _plain(prediction_text)
        summaries.append({
            "provider": provider,
            "expected_pages": len(pages),
            "observed_predictions": sum(pid in pages for pid in rows),
            "successful_pages": successful,
            "success_rate_all_expected": round(successful / len(pages), 5) if pages else None,
            "status_counts": dict(sorted(statuses.items())),
            "elapsed_sample_count": len(times),
            "median_execute_seconds": round(statistics.median(times), 5) if times else None,
            "p95_execute_seconds": _p95(times),
            "approved_gt_pages": sum(e.get("label_status") in APPROVED for e in pages.values()),
            "text_gt_pages_scored": scored,
            "text_gt_characters_scored": char_total,
            "micro_cer_no_whitespace": round(edits / char_total, 6) if char_total else None,
            "field_values_scored": field_total,
            "field_literal_presence_recall": round(field_found / field_total, 6) if field_total else None,
            "warning": "CER covers successful approved GT pages only; review missing/failure coverage. Literal field presence is not extraction accuracy.",
        })
    return summaries


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score independent Provider results against approved manual GT")
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    scores = evaluate(_read(args.truth), [row for path in args.predictions for row in _read(path)])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"results": scores}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(scores, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
