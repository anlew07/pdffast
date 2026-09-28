"""面向调用方的 PDFFast 运行配置。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .errors import ConfigurationError

OutputMode = Literal["minimal", "diagnostic", "full"]


@dataclass(frozen=True)
class ParserConfig:
    """解析器配置；默认适合普通业务调用。"""

    project_root: Path | None = None
    output_root: Path = Path("outputs")
    output_mode: OutputMode = "minimal"
    capture_output: bool = True
    page_dpi: int = 200
    region_dpi: int = 300
    rapidocr_workers: int = 1
    table_mode: str = "auto"
    provider_configs: dict[str, dict[str, Any]] | None = field(default=None)
    registry: Any | None = None
    normalizer: Any | None = None

    def __post_init__(self) -> None:
        if self.output_mode not in {"minimal", "diagnostic", "full"}:
            raise ConfigurationError(
                f"output_mode 必须是 minimal、diagnostic 或 full，实际为 {self.output_mode!r}"
            )
        if self.page_dpi <= 0 or self.region_dpi <= 0:
            raise ConfigurationError("page_dpi 和 region_dpi 必须大于 0")
        if self.rapidocr_workers < 1:
            raise ConfigurationError("rapidocr_workers 必须至少为 1")
        if self.table_mode not in {"off", "auto", "all"}:
            raise ConfigurationError("table_mode 必须是 off、auto 或 all")

