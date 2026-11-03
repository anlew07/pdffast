"""Input-file fingerprint metadata shared by PDFFast parse entry points.

This reads the input before parsing; it is not an immutable source snapshot.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint_input(pdf: Path) -> dict:
    """Record bytes observed before parsing, without retaining the PDF itself.

    Direct callers must keep their source unchanged throughout parsing. This
    digest is not a snapshot guarantee for a concurrently modified file.
    """
    metadata = {
        "algorithm": "sha256", "sha256": None, "byte_size": None,
        "filename": pdf.name, "status": "FAILED",
    }
    try:
        digest = hashlib.sha256()
        byte_size = 0
        with pdf.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_size += len(chunk)
        metadata.update(sha256=digest.hexdigest(), byte_size=byte_size, status="COMPLETE")
    except OSError as exc:
        # Preserve existing parser failure semantics; unknown is never zero.
        metadata["error"] = f"{type(exc).__name__}: {exc}"
    return metadata

