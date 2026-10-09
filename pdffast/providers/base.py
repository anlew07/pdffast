from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from .supplemental import SupplementalEvidence


@dataclass(frozen=True)
class ProviderPreflight:
    provider: str
    available: bool
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderTask:
    task_id: str
    capability_route: str
    input_image: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawProviderResult:
    provider: str
    task_id: str
    status: str
    payload: Any
    markdown: str | None = None
    elapsed_seconds: float | None = None
    warnings: tuple[str, ...] = ()
    supplemental_evidence: SupplementalEvidence | None = None


class Provider(Protocol):
    name: str

    def preflight(self) -> ProviderPreflight: ...

    def initialize(self) -> None: ...

    def execute(self, task: ProviderTask) -> RawProviderResult: ...

    def close(self) -> None: ...
