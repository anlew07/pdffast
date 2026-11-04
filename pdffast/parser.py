"""Public, transport-agnostic PDFFast parser facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdffast.application.parse_service import ParseService
from pdffast.config import ParserConfig
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

    def parse(self, pdf_path: Path, *, run_id: str = "parse", case_id: str | None = None) -> ParseResult:
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
                provider_plugins=self.provider_plugins,
                provider_chain_overrides=self.provider_chain_overrides,
                provider_profile=self.provider_profile,
            )
        return ParseService(config=config).parse(pdf_path, run_id=run_id, case_id=case_id)
