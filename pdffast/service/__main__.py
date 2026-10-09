"""Run v3 with an explicit, finite Uvicorn graceful shutdown window."""
from __future__ import annotations

import math
import os

import uvicorn


def build_config() -> uvicorn.Config:
    grace = float(os.environ.get('PDFFAST_SHUTDOWN_GRACE_SECONDS', '30'))
    if not math.isfinite(grace) or grace <= 0:
        raise ValueError('PDFFAST_SHUTDOWN_GRACE_SECONDS must be finite and positive')
    return uvicorn.Config(
        'pdffast.service.app:app',
        host=os.environ.get('PDFFAST_HOST', '127.0.0.1'),
        port=int(os.environ.get('PDFFAST_PORT', '8020')),
        timeout_graceful_shutdown=grace,
    )


if __name__ == '__main__':
    uvicorn.Server(build_config()).run()
