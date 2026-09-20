"""Plan reproducible reference and candidate pipeline commands safely."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def _runtime_arguments(
    *,
    output_root: Path,
    run_id: str,
    page_dpi: int,
    region_dpi: int,
    rapidocr_workers: int,
    table_mode: str,
    route_candidates: Path,
    provider_config: Path,
    templates: Path,
) -> list[str]:
    return [
        "--output-root",
        str(output_root),
        "--run-id",
        run_id,
        "--page-dpi",
        str(page_dpi),
        "--region-dpi",
        str(region_dpi),
        "--rapidocr-workers",
        str(rapidocr_workers),
        "--table-mode",
        table_mode,
        "--route-candidates",
        str(route_candidates),
        "--provider-config",
        str(provider_config),
        "--templates",
        str(templates),
    ]


def build_reference_command(
    *,
    python: Path,
    reference_root: Path,
    pdf: Path,
    output_root: Path,
    run_id: str,
    page_dpi: int,
    region_dpi: int,
    rapidocr_workers: int,
    table_mode: str,
) -> list[str]:
    return [
        str(python),
        str(reference_root / "scripts/pipeline_observed_runner.py"),
        str(pdf),
        *_runtime_arguments(
            output_root=output_root,
            run_id=run_id,
            page_dpi=page_dpi,
            region_dpi=region_dpi,
            rapidocr_workers=rapidocr_workers,
            table_mode=table_mode,
            route_candidates=(
                reference_root
                / "configs/frozen/stage9_route_candidates_prod_v001.json"
            ),
            provider_config=reference_root / "configs/stage9_providers_v011.json",
            templates=reference_root / "configs/templates.json",
        ),
    ]


def build_candidate_command(
    *,
    python: Path,
    candidate_root: Path,
    pdf: Path,
    output_root: Path,
    run_id: str,
    page_dpi: int,
    region_dpi: int,
    rapidocr_workers: int,
    table_mode: str,
) -> list[str]:
    return [
        str(python),
        str(candidate_root / "scripts/run_pipeline.py"),
        str(pdf),
        *_runtime_arguments(
            output_root=output_root,
            run_id=run_id,
            page_dpi=page_dpi,
            region_dpi=region_dpi,
            rapidocr_workers=rapidocr_workers,
            table_mode=table_mode,
            route_candidates=(
                candidate_root
                / "configs/frozen/stage9_route_candidates_prod_v001.json"
            ),
            provider_config=candidate_root / "configs/providers.json",
            templates=candidate_root / "configs/templates.json",
        ),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--reference-output-root", required=True, type=Path)
    parser.add_argument("--candidate-output-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reference-python", type=Path)
    parser.add_argument("--candidate-python", type=Path)
    parser.add_argument("--page-dpi", type=int, default=150)
    parser.add_argument("--region-dpi", type=int, default=150)
    parser.add_argument("--rapidocr-workers", type=int, default=1)
    parser.add_argument("--table-mode", choices=("off", "auto", "all"), default="auto")
    parser.add_argument("--execute", choices=("reference",))
    args = parser.parse_args(argv)

    reference_python = args.reference_python or args.reference_root / ".venv/bin/python"
    candidate_python = args.candidate_python or args.candidate_root / ".venv/bin/python"
    common = {
        "pdf": args.pdf,
        "run_id": args.run_id,
        "page_dpi": args.page_dpi,
        "region_dpi": args.region_dpi,
        "rapidocr_workers": args.rapidocr_workers,
        "table_mode": args.table_mode,
    }
    reference_command = build_reference_command(
        python=reference_python,
        reference_root=args.reference_root,
        output_root=args.reference_output_root,
        **common,
    )
    candidate_command = build_candidate_command(
        python=candidate_python,
        candidate_root=args.candidate_root,
        output_root=args.candidate_output_root,
        **common,
    )

    if args.execute is None:
        print(
            json.dumps(
                {
                    "reference_command": reference_command,
                    "candidate_command": candidate_command,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.pdf.is_file():
        print(f"PDF does not exist: {args.pdf}", file=sys.stderr)
        return 2
    target_run = args.reference_output_root / args.run_id
    if target_run.exists():
        print(f"run directory already exists: {target_run}", file=sys.stderr)
        return 2

    completed = subprocess.run(reference_command, cwd=args.reference_root)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
