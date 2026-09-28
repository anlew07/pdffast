"""运行时输出捕获工具。"""

from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path
from typing import Iterator


@contextlib.contextmanager
def capture_runtime_output(log_path: Path, *, enabled: bool = True) -> Iterator[None]:
    """将 Stage/Provider 的终端输出写入运行日志。"""
    if not enabled:
        yield
        return

    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        old_handlers = list(root.handlers)
        root.handlers = [handler]
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = stream
            sys.stderr = stream
            yield
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            root.handlers = old_handlers
            handler.close()
