"""Compare reference and candidate artifacts without hiding semantic drift."""

from __future__ import annotations

import argparse
import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


IGNORED_KEYS = frozenset(
    {
        "timestamp",
        "generated_at",
        "generated_at_utc",
        "run_id",
        "wall_seconds",
        "total_wall_seconds",
        "elapsed_seconds",
        "pid",
        "process_id",
        "temp_dir",
    }
)

PATH_KEYS = frozenset(
    {
        "canonical_path",
        "input_image",
        "log_path",
        "output_path",
        "path",
        "pdf",
        "provider_raw_ref",
        "result_path",
        "source_file",
        "source_path",
        "source_pdf",
    }
)


@dataclass(frozen=True)
class RootMapping:
    reference_project: Path
    candidate_project: Path
    reference_run: Path
    candidate_run: Path


@dataclass(frozen=True)
class ComparisonResult:
    equal: bool
    summary: str
    diff: str


def _normalized_path(value: str, roots: RootMapping) -> str:
    replacements = (
        (str(roots.reference_run), "<RUN_ROOT>"),
        (str(roots.candidate_run), "<RUN_ROOT>"),
        (str(roots.reference_project), "<PROJECT_ROOT>"),
        (str(roots.candidate_project), "<PROJECT_ROOT>"),
    )
    for prefix, token in replacements:
        if value == prefix:
            return token
        if value.startswith(prefix + "/"):
            return token + value[len(prefix) :]
    return value


def normalize_json(value: object, roots: RootMapping) -> object:
    """Normalize only explicitly approved runtime metadata and path fields."""

    def visit(item: object, field_name: str | None = None) -> object:
        if isinstance(item, dict):
            return {
                key: visit(child, key)
                for key, child in item.items()
                if key not in IGNORED_KEYS
            }
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, str) and field_name in PATH_KEYS:
            return _normalized_path(item, roots)
        return item

    return visit(value)


def _pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _first_difference(reference: object, candidate: object, pointer: str = "") -> str:
    if type(reference) is not type(candidate):
        return pointer or "/"
    if isinstance(reference, dict):
        reference_keys = set(reference)
        candidate_keys = set(candidate)
        if reference_keys != candidate_keys:
            key = sorted(reference_keys ^ candidate_keys)[0]
            return f"{pointer}/{_pointer_token(key)}"
        for key in sorted(reference_keys):
            found = _first_difference(
                reference[key], candidate[key], f"{pointer}/{_pointer_token(key)}"
            )
            if found:
                return found
        return ""
    if isinstance(reference, list):
        if len(reference) != len(candidate):
            return f"{pointer}/length"
        for index, (left, right) in enumerate(zip(reference, candidate)):
            found = _first_difference(left, right, f"{pointer}/{index}")
            if found:
                return found
        return ""
    return "" if reference == candidate else (pointer or "/")


def _text_diff(reference: str, candidate: str, left: str, right: str) -> str:
    return "".join(
        difflib.unified_diff(
            reference.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=left,
            tofile=right,
        )
    )


def compare_json(
    reference: Path,
    candidate: Path,
    roots: RootMapping,
) -> ComparisonResult:
    left = normalize_json(
        json.loads(Path(reference).read_text(encoding="utf-8")), roots
    )
    right = normalize_json(
        json.loads(Path(candidate).read_text(encoding="utf-8")), roots
    )
    if left == right:
        return ComparisonResult(True, "JSON artifacts are equal", "")

    pointer = _first_difference(left, right)
    left_text = json.dumps(left, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    right_text = json.dumps(right, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return ComparisonResult(
        False,
        f"JSON artifacts differ first at {pointer}",
        _text_diff(left_text, right_text, str(reference), str(candidate)),
    )


def compare_bytes(reference: Path, candidate: Path) -> ComparisonResult:
    left_bytes = Path(reference).read_bytes()
    right_bytes = Path(candidate).read_bytes()
    if left_bytes == right_bytes:
        return ComparisonResult(True, "Artifacts are byte-for-byte equal", "")

    left_text = left_bytes.decode("utf-8", errors="replace")
    right_text = right_bytes.decode("utf-8", errors="replace")
    return ComparisonResult(
        False,
        f"Byte artifacts differ: {len(left_bytes)} != {len(right_bytes)} bytes",
        _text_diff(left_text, right_text, str(reference), str(candidate)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("json", "bytes"), required=True)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--reference-run-root", type=Path)
    parser.add_argument("--candidate-run-root", type=Path)
    args = parser.parse_args(argv)

    if args.kind == "json":
        required = (
            args.reference_root,
            args.candidate_root,
            args.reference_run_root,
            args.candidate_run_root,
        )
        if any(value is None for value in required):
            parser.error("JSON comparison requires all project and run roots")
        roots = RootMapping(
            reference_project=args.reference_root,
            candidate_project=args.candidate_root,
            reference_run=args.reference_run_root,
            candidate_run=args.candidate_run_root,
        )
        result = compare_json(args.reference, args.candidate, roots)
    else:
        result = compare_bytes(args.reference, args.candidate)

    print(result.summary)
    if result.diff:
        print(result.diff, end="" if result.diff.endswith("\n") else "\n")
    return 0 if result.equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
