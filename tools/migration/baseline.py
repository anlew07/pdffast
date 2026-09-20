"""Capture the immutable source baseline for the reference production path."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Sequence


REFERENCE_FILES = (
    "configs/frozen/stage9_route_candidates_prod_v001.json",
    "configs/stage9_providers_v011.json",
    "configs/templates.json",
    "scripts/10_1_canonical_document_builder.py",
    "scripts/10_2_1_structure_boundary_audit.py",
    "scripts/10_2_llm_ready_renderer.py",
    "scripts/1_page_profiler.py",
    "scripts/2_template_analyzer.py",
    "scripts/3_section_aligner.py",
    "scripts/4_page_structure_builder.py",
    "scripts/5_table_recovery.py",
    "scripts/6_text_flow_normalizer.py",
    "scripts/7_native_evidence_manifest.py",
    "scripts/8_quality_gate.py",
    "scripts/9_1_fallback_unit_builder.py",
    "scripts/9_2_provider_router.py",
    "scripts/9_3_provider_benchmark.py",
    "scripts/9_5_1_prediction_normalizer.py",
    "scripts/9_6_3_runtime_escalation_policy.py",
    "scripts/9_8_full_production_fallback_executor.py",
    "scripts/pipeline_observed_runner.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture_manifest(reference_root: Path) -> dict[str, object]:
    """Return a path-independent manifest for the audited production files."""

    root = Path(reference_root).resolve()
    files: list[dict[str, object]] = []
    for relative in sorted(REFERENCE_FILES):
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"reference production file is missing: {path}")
        files.append(
            {
                "path": relative,
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return {
        "schema_version": "1.0",
        "role": "pdffast_reference_production_sources",
        "files": files,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with an existing manifest without modifying it",
    )
    args = parser.parse_args(argv)

    manifest = capture_manifest(args.reference_root)
    output = args.output
    if args.check:
        if not output.is_file():
            print(f"manifest does not exist: {output}", file=sys.stderr)
            return 1
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing != manifest:
            print(f"manifest differs: {output}", file=sys.stderr)
            return 1
        return 0

    if output.exists():
        print(f"manifest already exists: {output}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
