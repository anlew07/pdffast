"""Immutable configuration for one PDFFast pipeline run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pdffast.pipeline.artifacts import ArtifactPaths


@dataclass(frozen=True)
class PipelineContext:
    project_root: Path
    pdf: Path
    output_root: Path
    run_id: str
    case_id: str
    run_dir: Path
    templates: Path
    providers: Path
    route_candidates: Path
    page_dpi: int
    region_dpi: int
    rapidocr_workers: int
    table_mode: str
    artifacts: ArtifactPaths

    @classmethod
    def create(
        cls,
        *,
        project_root: Path,
        pdf: Path,
        output_root: Path,
        run_id: str,
        case_id: str | None,
        page_dpi: int,
        region_dpi: int,
        rapidocr_workers: int,
        table_mode: str,
    ) -> "PipelineContext":
        if page_dpi <= 0:
            raise ValueError("page_dpi must be greater than zero")
        if region_dpi <= 0:
            raise ValueError("region_dpi must be greater than zero")
        if rapidocr_workers < 1:
            raise ValueError("rapidocr_workers must be at least one")
        if table_mode not in {"off", "auto", "all"}:
            raise ValueError("table_mode must be one of: off, auto, all")

        root = Path(project_root).resolve()
        source_pdf = Path(pdf).resolve()
        resolved_output = Path(output_root).resolve()
        raw_case_id = case_id if case_id is not None else source_pdf.stem
        safe_case_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_case_id)
        run_dir = resolved_output / run_id

        return cls(
            project_root=root,
            pdf=source_pdf,
            output_root=resolved_output,
            run_id=run_id,
            case_id=safe_case_id,
            run_dir=run_dir,
            templates=root / "configs/templates.json",
            providers=root / "configs/providers.json",
            route_candidates=(
                root / "configs/frozen/stage9_route_candidates_prod_v001.json"
            ),
            page_dpi=page_dpi,
            region_dpi=region_dpi,
            rapidocr_workers=rapidocr_workers,
            table_mode=table_mode,
            artifacts=ArtifactPaths.for_run(run_dir),
        )
