"""Application service for one PDFFast parse request."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
import json
from pathlib import Path

from pdffast.application.input_fingerprint import fingerprint_input as _fingerprint
from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.profiles import ProviderProfileError, apply_production_profile, load_provider_profile
from pdffast.providers.runtime_normalization import normalize_runtime_result
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.pipeline.runner import run_core_pipeline
from pdffast.result import ParseResult
from pdffast.runtime import observe_parse


@dataclass
class ParseService:
    config: ParserConfig

    def parse(self, pdf_path: Path, *, run_id: str = "parse", case_id: str | None = None) -> ParseResult:
        paths = ArtifactPaths.for_run(Path(self.config.output_root).resolve() / run_id)
        with observe_parse(
            run_id,
            log_path=paths.diagnostics.pipeline_log if self.config.capture_output else None,
        ):
            metadata = _fingerprint(Path(pdf_path))
            paths.result.manifest_json.parent.mkdir(parents=True, exist_ok=True)
            paths.result.manifest_json.write_text(
                json.dumps({"run_id": run_id, "input": metadata}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return self._parse(pdf_path, run_id=run_id, case_id=case_id, input_metadata=metadata)

    def _parse(self, pdf_path: Path, *, run_id: str, case_id: str | None, input_metadata: dict) -> ParseResult:
        config = self.config
        project_root = Path(config.project_root or Path(__file__).resolve().parents[2])
        bundled_configs = None
        if config.project_root is None:
            from importlib.resources import files

            bundled_configs = files("pdffast.resources.configs")
        provider_configs = config.provider_configs
        registry = config.registry
        normalizer = config.normalizer
        provider_chain_overrides = config.provider_chain_overrides
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
                if provider_configs is None:
                    provider_configs = payload["providers"]
                if registry is None:
                    plugins = config.provider_plugins if config.provider_plugins is not None else payload.get("plugins", {})
                    registry = ProviderRegistry(base_dir=project_root, plugins=plugins)
                if normalizer is None:
                    paths = registry.plugin_normalizers if isinstance(registry, ProviderRegistry) else {}
                    normalizer = partial(normalize_runtime_result, plugin_normalizer_paths=paths)
                if provider_chain_overrides is None:
                    provider_chain_overrides = payload.get("provider_chain_overrides")
            except (OSError, KeyError, TypeError, ValueError) as exc:
                location = str(config_path) if config.project_root is not None else "PDFFast 内置资源 providers.json"
                raise ConfigurationError(f"无法加载 Provider 配置：{location}: {exc}") from exc
        if config.provider_profile is not None:
            if provider_chain_overrides is not None:
                raise ConfigurationError(
                    "provider_profile cannot be combined with provider_chain_overrides"
                )
            try:
                profile = load_provider_profile(Path(config.provider_profile))
                provider_configs, provider_chain_overrides = apply_production_profile(
                    provider_configs, profile
                )
            except ProviderProfileError as exc:
                raise ConfigurationError(f"Provider profile 无效：{exc}") from exc
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
        context = replace(context, input_metadata=input_metadata)
        return run_core_pipeline(
            context,
            provider_configs=provider_configs,
            registry=registry,
            normalizer=normalizer,
            provider_chain_overrides=provider_chain_overrides,
            execute_providers=True,
        )
