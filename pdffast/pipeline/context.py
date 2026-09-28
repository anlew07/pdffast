"""Immutable configuration for one PDFFast pipeline run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.config import OutputMode


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
    output_mode: OutputMode = "minimal"
    capture_output: bool = True

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
        output_mode: OutputMode = "minimal",
        capture_output: bool = True,
        templates_path: Path | None = None,
        providers_path: Path | None = None,
        route_candidates_path: Path | None = None,
    ) -> "PipelineContext":
        if page_dpi <= 0:
            raise ValueError("page_dpi must be greater than zero")
        if region_dpi <= 0:
            raise ValueError("region_dpi must be greater than zero")
        if rapidocr_workers < 1:
            raise ValueError("rapidocr_workers must be at least one")
        if table_mode not in {"off", "auto", "all"}:
            raise ValueError("table_mode must be one of: off, auto, all")
        if output_mode not in {"minimal", "diagnostic", "full"}:
            raise ValueError("output_mode must be one of: minimal, diagnostic, full")

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
            templates=Path(templates_path).resolve() if templates_path else root / "configs/templates.json",
            providers=Path(providers_path).resolve() if providers_path else root / "configs/providers.json",
            route_candidates=(Path(route_candidates_path).resolve() if route_candidates_path else root / "configs/frozen/stage9_route_candidates_prod_v001.json"),
            page_dpi=page_dpi,
            region_dpi=region_dpi,
            rapidocr_workers=rapidocr_workers,
            table_mode=table_mode,
            artifacts=ArtifactPaths.for_run(run_dir),
            output_mode=output_mode,
            capture_output=capture_output,
        )
