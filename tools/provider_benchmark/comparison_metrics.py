"""Label-free output agreement metrics for pairs of Provider predictions.

These are symmetric text-overlap diagnostics, never OCR accuracy scores.
"""
from __future__ import annotations

from collections import Counter


def clean(text: str) -> str:
    """Use the same whitespace-free character comparison policy as CER."""
    return "".join(text.split())


def _overlap(a: Counter[str], b: Counter[str]) -> float | None:
    total = sum(a.values()) + sum(b.values())
    if total == 0:
        return None
    common = sum(min(n, b.get(token, 0)) for token, n in a.items())
    return round(200.0 * common / total, 2)


def directional_gram_recall(reference: str, candidate: str) -> float | None:
    """Percent of reference character n-grams appearing in candidate.

    No longer than 3 characters per gram. This is a rough lexical
    coverage diagnostic only; it does not prove actual content completeness.
    """
    left, right = clean(reference), clean(candidate)
    if not left:
        return None
    if not right:
        return 0.0
    width = min(3, len(left), len(right))
    ref_counts = Counter(left[i:i+width] for i in range(len(left)-width+1))
    pred_counts = Counter(right[i:i+width] for i in range(len(right)-width+1))
    found = sum(min(n, pred_counts.get(fragment, 0)) for fragment, n in ref_counts.items())
    return round(100.0 * found / sum(ref_counts.values()), 2)


def compare_texts(a: str, b: str) -> dict[str, float | int | None]:
    """Character bag Dice and ordered 3-gram bag Dice percentages.

    Both metrics are symmetric, 0-100. Character overlap ignores order;
    3-grams consider local order, but not page-level reading order.
    Both-empty outputs are non-scorable (None); one-empty is 0%.
    No correctness/coverage claim is made without reviewed ground truth.
    """
    left, right = clean(a), clean(b)
    if not left and not right:
        return {
            "char_overlap_pct": None,
            "trigram_overlap_pct": None,
            "char_delta": 0,
            "normalized_chars_a": 0,
            "normalized_chars_b": 0,
            "a_fragments_covered_by_b_pct": None,
            "b_fragments_covered_by_a_pct": None,
        }
    char_pct = _overlap(Counter(left), Counter(right))
    def grams(s: str) -> Counter[str]:
        # Short texts use the largest possible n to avoid a zero denominator.
        n = min(3, len(s))
        return Counter(s[i:i+n] for i in range(len(s) - n + 1)) if n else Counter()

    if not left or not right:
        gram_pct = 0.0
    elif min(len(left), len(right)) < 3:
        # Keep the same n on both sides.
        n = min(len(left), len(right))
        gram_pct = _overlap(
            Counter(left[i:i+n] for i in range(len(left)-n+1)),
            Counter(right[i:i+n] for i in range(len(right)-n+1)),
        )
    else:
        gram_pct = _overlap(grams(left), grams(right))
    return {
        "char_overlap_pct": char_pct,
        "trigram_overlap_pct": gram_pct,
        "char_delta": len(left) - len(right),
        "normalized_chars_a": len(left),
        "normalized_chars_b": len(right),
        "a_fragments_covered_by_b_pct": directional_gram_recall(a, b),
        "b_fragments_covered_by_a_pct": directional_gram_recall(b, a),
    }
