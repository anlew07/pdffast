"""PDFFast 对外稳定异常。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_RUN_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


def is_execution_run_id(value: object) -> bool:
    return isinstance(value, str) and _RUN_ID.fullmatch(value) is not None


class _ExecutionFailure:
    """Serialize stable public fields while retaining native exceptions for local callers."""

    error_code = "PARSE_EXECUTION_FAILED"
    response_status = "FAILED"
    stage = "parse_preparation"
    contract_message = "PDF execution failed."
    risk_flags: tuple[str, ...] = ()
    run_id: str | None = None
    run_dir: Path | None = None
    log_path: Path | None = None

    def to_contract(self, *, run_id: str | None = None) -> dict[str, Any]:
        identifier = run_id if run_id is not None else self.run_id
        if identifier is None and self.run_dir is not None:
            identifier = self.run_dir.name
        diagnostics = {}
        if self.log_path is not None and self.run_dir is not None:
            try:
                relative = self.log_path.resolve(strict=True).relative_to(
                    self.run_dir.resolve(strict=True),
                )
                if relative.parts and chr(92) not in relative.as_posix():
                    diagnostics["log_path"] = relative.as_posix()
            except (OSError, RuntimeError, ValueError):
                pass
        return {
            "schema_version": "pdffast.execution.error.v1",
            "run_id": identifier if is_execution_run_id(identifier) else None,
            "status": self.response_status,
            "error": {
                "code": self.error_code,
                "type": type(self).__name__,
                "message": self.contract_message,
                "stage": self.stage,
                "retryable": False,
                "details": getattr(self, "details", {}),
            },
            "warnings": [],
            "risk_flags": list(self.risk_flags),
            "diagnostics": diagnostics,
        }


class PDFFastError(_ExecutionFailure, Exception):
    """所有公共解析错误的基类。"""


class ParseCancelledError(_ExecutionFailure, BaseException):
    """Explicitly aborted work, never a recoverable Provider result."""

    error_code = "PARSE_CANCELLED"
    response_status = "CANCELLED"
    stage = "runtime_cancellation"
    contract_message = "PDF execution was cancelled."


class ConfigurationError(PDFFastError, ValueError):
    """解析配置无效。"""

    status = "CONFIGURATION_FAILED"
    error_code = "INVALID_CONFIGURATION_OR_REQUEST"
    response_status = "BLOCKED"
    stage = "request_validation"
    contract_message = "PDFFast rejected the execution request or deployment configuration."


class RunReservationError(ConfigurationError):
    """The output directory could not be reserved for this execution."""

    error_code = "RUN_RESERVATION_FAILED"
    stage = "run_reservation"
    contract_message = "PDFFast could not reserve a directory for this run."


class InputUnavailableError(ConfigurationError):
    """The requested PDF cannot be read or has no content."""

    error_code = "INPUT_UNAVAILABLE"
    stage = "input_validation"
    contract_message = "The input PDF is unavailable or empty."

    def __init__(self, details: dict) -> None:
        self.details = details
        super().__init__("input PDF is unavailable or empty")


class InputIdentityMismatchError(ConfigurationError):
    """The PDF does not match the caller's expected SHA-256."""

    error_code = "INPUT_SHA256_MISMATCH"
    stage = "input_validation"
    contract_message = "The input PDF does not match the expected SHA-256."
    risk_flags = ("INPUT_SHA256_MISMATCH",)

    def __init__(self, expected_sha256: str, actual_sha256: str) -> None:
        self.details = {
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
        }
        super().__init__("input PDF SHA-256 does not match the execution request")


class ProductionPreflightError(PDFFastError, RuntimeError):
    """Production readiness could not be established before parsing."""

    status = "PREFLIGHT_FAILED"
    error_code = "PRODUCTION_PREFLIGHT_FAILED"
    response_status = "BLOCKED"
    stage = "production_preflight"
    contract_message = "Production preflight failed."
    risk_flags = ("PRODUCTION_PREFLIGHT_FAILED",)

    def __init__(self, report: dict) -> None:
        self.report = report
        providers = report.get("provider_runtime", {})
        failed = ", ".join(
            f"{name}={value['status']}" for name, value in providers.items()
            if value["status"] != "READY"
        )
        super().__init__(f"Production preflight failed: {failed or report.get('error', 'unknown')}")
        known_statuses = {"READY", "NOT_READY", "NOT_INSTALLED", "IDENTITY_UNVERIFIED",
                          "MISCONFIGURED", "CHECK_ERROR"}
        self.details = {
            "provider_status": {name: value["status"] for name, value in providers.items()
                                if is_execution_run_id(name) and value["status"] in known_statuses}
        }
        cause_type = report.get("error")
        if cause_type in ("OSError", "TypeError", "ValueError", "TimeoutExpired", "CalledProcessError"):
            self.details["cause_type"] = cause_type


class ParseExecutionError(PDFFastError, RuntimeError):
    """流水线执行失败，并保留本次运行的定位信息。"""

    status = "EXECUTION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        run_dir: Path | None = None,
        log_path: Path | None = None,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.log_path = Path(log_path) if log_path is not None else None
        self.stage = stage or type(self).stage
        self.details = details if details is not None else {}


class OutputValidationError(ParseExecutionError):
    """Locked artifact audit did not pass."""

    status = "OUTPUT_VALIDATION_FAILED"
    error_code = "OUTPUT_VALIDATION_FAILED"
    stage = "output_validation"
    contract_message = "PDF output validation failed."
    risk_flags = ("OUTPUT_VALIDATION_FAILED",)


class NoUsableResultError(OutputValidationError):
    """Only placeholders or empty output survived rendering."""

    error_code = "NO_USABLE_RESULT"
    contract_message = "PDF execution produced no usable result."


class ProviderExecutionError(ParseExecutionError):
    """Provider execution failed to deliver the required result."""

    error_code = "PROVIDER_EXECUTION_FAILED"
    stage = "provider_execution"
    contract_message = "Provider execution failed."
    risk_flags = ("PIPELINE_FAILURES_PRESENT",)


class ProviderUnavailableError(ParseExecutionError):
    """生产 Provider 不可用。"""

    error_code = "PROVIDER_INITIALIZATION_FAILED"
    stage = "provider_initialization"
    contract_message = "Provider initialization failed."
    risk_flags = ("PROVIDER_STARTUP_FAILED",)
