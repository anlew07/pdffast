"""Public, transport-agnostic PDFFast parser facade."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from pdffast.application.execution_contract import validate_execution_request
from pdffast.application.parse_service import ParseService
from pdffast.config import ParserConfig
from pdffast.errors import ConfigurationError
from pdffast.result import ParseResult


@dataclass
class PDFFastParser:
    """Public entry point for parsing PDFs."""

    config: ParserConfig | None = None
    project_root: Path | None = None
    output_root: Path = Path("outputs")
    output_mode: str = "minimal"
    capture_output: bool = True
    provider_configs: dict[str, dict[str, Any]] | None = None
    registry: Any | None = None
    normalizer: Any | None = None
    provider_plugins: dict[str, dict[str, str]] | None = None
    provider_chain_overrides: dict[str, list[str]] | None = None
    provider_profile: Path | None = None

    def _resolved_config(self) -> ParserConfig:
        config = self.config
        if config is not None and (
            self.provider_profile is not None
            or config.provider_profile is not None and any(
                value is not None for value in (
                    self.project_root, self.provider_configs, self.registry, self.normalizer,
                    self.provider_plugins, self.provider_chain_overrides,
                )
            )
        ):
            raise ConfigurationError("provider_profile cannot be split between config and facade options")
        if config is not None:
            return config
        return ParserConfig(
            project_root=self.project_root,
            output_root=self.output_root,
            output_mode=self.output_mode,
            capture_output=self.capture_output,
            provider_configs=self.provider_configs,
            registry=self.registry,
            normalizer=self.normalizer,
            provider_plugins=self.provider_plugins,
            provider_chain_overrides=self.provider_chain_overrides,
            provider_profile=self.provider_profile,
        )

    def parse(
        self,
        pdf_path: Path,
        *,
        run_id: str = "parse",
        case_id: str | None = None,
        expected_input_sha256: str | None = None,
    ) -> ParseResult:
        """Backward-compatible parse API with optional caller digest verification."""
        return ParseService(config=self._resolved_config()).parse(
            pdf_path,
            run_id=run_id,
            case_id=case_id,
            expected_input_sha256=expected_input_sha256,
        )

    def parse_request(
        self,
        pdf_path: Path,
        request: Mapping[str, Any],
        *,
        case_id: str | None = None,
    ) -> ParseResult:
        """Execute one strict, versioned request using a deployment-locked profile.

        The request may tune only generic parser parameters. Provider choice,
        route candidates, fallback policy and runtime configuration remain
        owned by the trusted PDFFast deployment.
        """
        normalized = validate_execution_request(request)
        config = self._resolved_config()
        if config.provider_profile is None:
            raise ConfigurationError(
                "versioned execution requests require a locked Production Profile"
            )

        effective_options = {
            "page_dpi": config.page_dpi,
            "region_dpi": config.region_dpi,
            "rapidocr_workers": config.rapidocr_workers,
            "table_mode": config.table_mode,
        }
        effective_options.update(normalized["options"])
        effective_config = replace(config, **normalized["options"])
        execution_request = {
            "schema_version": normalized["schema_version"],
            "input_sha256": normalized["input"]["sha256"],
            "options": effective_options,
        }
        return ParseService(config=effective_config).parse(
            pdf_path,
            run_id=normalized["run_id"],
            case_id=case_id,
            expected_input_sha256=normalized["input"]["sha256"],
            execution_request=execution_request,
        )
