"""PDFFast 对外稳定异常。"""

from __future__ import annotations

from pathlib import Path


class PDFFastError(Exception):
    """所有公共解析错误的基类。"""


class ConfigurationError(PDFFastError, ValueError):
    """解析配置无效。"""


class ParseExecutionError(PDFFastError, RuntimeError):
    """流水线执行失败，并保留本次运行的定位信息。"""

    def __init__(
        self,
        message: str,
        *,
        run_dir: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.log_path = Path(log_path) if log_path is not None else None


class ProviderUnavailableError(ParseExecutionError):
    """生产 Provider 不可用。"""
