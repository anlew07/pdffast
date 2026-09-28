"""Public, transport-agnostic PDFFast parser facade."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_core_pipeline


@dataclass
class PDFFastParser:
    """Parse PDFs through Core without importing a web framework or task queue."""

    config: ParserConfig | None = None
    project_root: Path | None = None
    output_root: Path = Path("outputs")
    output_mode: str = "minimal"
    capture_output: bool = True
    provider_configs: dict[str, dict[str, Any]] | None = None
    registry: Any | None = None
    normalizer: Any | None = None

    def parse(self, pdf_path: Path, *, run_id: str = "parse", case_id: str | None = None) -> Any:
        config = self.config
        if config is None:
            config = ParserConfig(
                project_root=self.project_root,
                output_root=self.output_root,
                output_mode=self.output_mode,
                capture_output=self.capture_output,
                provider_configs=self.provider_configs,
                registry=self.registry,
                normalizer=self.normalizer,
            )
        project_root = Path(config.project_root or Path(__file__).resolve().parents[1])
        bundled_configs = None
        if config.project_root is None:
            from importlib.resources import files

            bundled_configs = files("pdffast.resources.configs")
        provider_configs = config.provider_configs
        registry = config.registry
        normalizer = config.normalizer
        if provider_configs is None or registry is None or normalizer is None:
            try:
                if config.project_root is not None:
                    config_path = project_root / "configs/providers.json"
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                else:
                    payload = json.loads(
                        bundled_configs
                        .joinpath("providers.json")
                        .read_text(encoding="utf-8")
                    )
                provider_configs = payload["providers"]
                registry = ProviderRegistry(base_dir=project_root)
                normalizer = normalize_runtime_result
            except (OSError, KeyError, TypeError, ValueError) as exc:
                location = str(config_path) if config.project_root is not None else "PDFFast 内置资源 providers.json"
                raise ConfigurationError(f"无法加载 Provider 配置：{location}: {exc}") from exc
        context = PipelineContext.create(
            project_root=config.project_root or project_root,
            pdf=Path(pdf_path),
            output_root=config.output_root,
            run_id=run_id,
            case_id=case_id,
            page_dpi=config.page_dpi,
            region_dpi=config.region_dpi,
            rapidocr_workers=config.rapidocr_workers,
            table_mode=config.table_mode,
            output_mode=config.output_mode,
            capture_output=config.capture_output,
            templates_path=(
                None
                if bundled_configs is None
                else Path(str(bundled_configs.joinpath("templates.json")))
            ),
            providers_path=(
                None
                if bundled_configs is None
                else Path(str(bundled_configs.joinpath("providers.json")))
            ),
            route_candidates_path=(
                None
                if bundled_configs is None
                else Path(
                    str(
                        bundled_configs.joinpath(
                            "frozen/stage9_route_candidates_prod_v001.json"
                        )
                    )
                )
            ),
        )
        return run_core_pipeline(
            context,
            provider_configs=provider_configs,
            registry=registry,
            normalizer=normalizer,
            execute_providers=True,
        )
