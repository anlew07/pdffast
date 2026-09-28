"""稳定的解析结果边界。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .pipeline.context import PipelineContext


@dataclass(frozen=True)
class ParseResult:
    """对业务调用方稳定的解析结果，同时兼容旧 mapping 访问。"""

    canonical: dict[str, Any]
    markdown: str
    audit: dict[str, Any]
    artifacts: dict[str, Path]
    production_manifest: dict[str, Any] | None = None

    @classmethod
    def from_pipeline(cls, context: PipelineContext, payload: dict[str, Any]) -> "ParseResult":
        a = context.artifacts
        artifacts: dict[str, Path] = {
            "result_dir": a.result_dir,
            "result_document": a.result_document,
            "result_markdown": a.result_markdown,
            "result_audit": a.result_audit,
            "result_manifest": a.result_manifest,
        }
        if context.output_mode in {"diagnostic", "full"}:
            artifacts["pipeline_log"] = a.pipeline_log
        if context.output_mode == "full":
            artifacts.update(a.as_dict())
        return cls(
            canonical=payload["canonical"],
            markdown=str(payload["markdown"]),
            audit=payload["structure_audit"],
            artifacts=artifacts,
            production_manifest=payload.get("production_manifest"),
        )

    def __getitem__(self, key: str) -> Any:
        values = {
            "canonical": self.canonical,
            "markdown": self.markdown,
            "structure_audit": self.audit,
            "production_manifest": self.production_manifest,
            **self.artifacts,
        }
        return values[key]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __iter__(self) -> Iterator[str]:
        return iter(("canonical", "markdown", "structure_audit", "production_manifest", *self.artifacts))
