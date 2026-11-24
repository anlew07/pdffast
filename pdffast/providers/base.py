from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .supplemental import SupplementalEvidence


class ProviderAssetIntegrityError(RuntimeError):
    """A locked Provider model asset changed after production preflight."""


def asset_stat_identity(path: Path | str) -> dict[str, int]:
    value = Path(path).stat()
    return {
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
        "inode": value.st_ino,
        "device": value.st_dev,
        "mode": stat.S_IMODE(value.st_mode),
        "uid": value.st_uid,
        "gid": value.st_gid,
    }


def validate_asset_stat_snapshot(config: dict[str, Any]) -> None:
    snapshot = config.get("_pdffast_asset_stat_snapshot")
    if snapshot is None:
        return
    if not isinstance(snapshot, dict) or not snapshot:
        raise ProviderAssetIntegrityError("locked Provider asset stat snapshot is invalid")
    for raw_path, expected in snapshot.items():
        try:
            actual = asset_stat_identity(raw_path)
        except OSError as exc:
            raise ProviderAssetIntegrityError(
                f"locked Provider asset is unavailable: {raw_path}"
            ) from exc
        if actual != expected:
            raise ProviderAssetIntegrityError(
                f"locked Provider asset changed after preflight: {raw_path}"
            )


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
