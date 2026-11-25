"""Stable public errors and machine-readable failure responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe diagnostic value without exposing arbitrary objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


class PDFFastError(Exception):
    """All public PDFFast failures share one machine-readable error envelope."""

    error_code = "PDFFAST_ERROR"
    response_status = "FAILED"
    default_stage = "unknown"
    retryable = False
    risk_flags: tuple[str, ...] = ()

    def to_contract(self, *, run_id: str | None = None) -> dict[str, Any]:
        """Serialize a failure without inventing a successful result Manifest."""
        run_dir = getattr(self, "run_dir", None)
        resolved_run_id = run_id or getattr(self, "run_id", None)
        if resolved_run_id is None and run_dir is not None:
            resolved_run_id = Path(run_dir).name

        details = getattr(self, "details", None)
        if details is None and getattr(self, "report", None) is not None:
            details = {"preflight_report": self.report}
        if not isinstance(details, dict):
            details = {}

        diagnostics: dict[str, str] = {}
        log_path = getattr(self, "log_path", None)
        if log_path is not None and run_dir is not None:
            try:
                relative = Path(log_path).resolve(strict=False).relative_to(
                    Path(run_dir).resolve(strict=True)
                )
                diagnostics["log_path"] = relative.as_posix()
            except (OSError, ValueError):
                pass

        response: dict[str, Any] = {
            "schema_version": "pdffast.execution.error.v1",
            "run_id": resolved_run_id,
            "status": self.response_status,
            "error": {
                "code": getattr(self, "error_code", self.error_code),
                "type": type(self).__name__,
                "message": str(self) or type(self).__name__,
                "stage": getattr(self, "stage", self.default_stage),
                "retryable": bool(getattr(self, "retryable", self.retryable)),
                "details": _json_safe(details),
            },
            "warnings": [],
            "risk_flags": sorted(set(self.risk_flags)),
        }
        if diagnostics:
            response["diagnostics"] = diagnostics
        return response


class ConfigurationError(PDFFastError, ValueError):
    """解析配置或调用请求无效，执行尚未进入业务解析。"""

    status = "CONFIGURATION_FAILED"
    error_code = "INVALID_CONFIGURATION_OR_REQUEST"
    response_status = "BLOCKED"
    default_stage = "request_validation"
    risk_flags = ("REQUEST_REJECTED",)


class InputIdentityMismatchError(ConfigurationError):
    """The supplied PDF does not match the caller's expected SHA-256."""

    error_code = "INPUT_SHA256_MISMATCH"
    default_stage = "input_validation"
    risk_flags = ("INPUT_SHA256_MISMATCH",)


class ProductionPreflightError(PDFFastError, RuntimeError):
    """Production readiness could not be established before parsing."""

    status = "PREFLIGHT_FAILED"
    error_code = "PRODUCTION_PREFLIGHT_FAILED"
    response_status = "BLOCKED"
    default_stage = "production_preflight"
    risk_flags = ("PRODUCTION_PREFLIGHT_FAILED",)

    def __init__(self, report: dict) -> None:
        self.report = report
        providers = report.get("provider_runtime", {})
        failed = ", ".join(
            f"{name}={value['status']}" for name, value in providers.items()
            if value["status"] != "READY"
        )
        super().__init__(f"Production preflight failed: {failed or report.get('error', 'unknown')}")


class ParseExecutionError(PDFFastError, RuntimeError):
    """流水线执行失败，并保留本次运行的定位信息。"""

    status = "EXECUTION_FAILED"
    error_code = "PARSE_EXECUTION_FAILED"
    response_status = "FAILED"
    default_stage = "pipeline"

    def __init__(
        self,
        message: str,
        *,
        run_dir: Path | None = None,
        log_path: Path | None = None,
        stage: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
        risk_flags: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.log_path = Path(log_path) if log_path is not None else None
        self.stage = stage or self.default_stage
        self.retryable = retryable
        self.details = details or {}
        if error_code is not None:
            self.error_code = error_code
        elif self.stage == "provider_initialization":
            self.error_code = "PROVIDER_INITIALIZATION_FAILED"
        self.risk_flags = tuple(risk_flags) or (
            ("PROVIDER_STARTUP_FAILED",)
            if self.stage == "provider_initialization" else ()
        )


class OutputValidationError(ParseExecutionError):
    """Locked artifact audit did not pass."""

    status = "OUTPUT_VALIDATION_FAILED"
    error_code = "OUTPUT_VALIDATION_FAILED"
    default_stage = "output_validation"
    risk_flags = ("OUTPUT_VALIDATION_FAILED",)


class ProviderUnavailableError(ParseExecutionError):
    """生产 Provider 不可用。"""

    error_code = "PROVIDER_UNAVAILABLE"
    default_stage = "provider_initialization"
    risk_flags = ("PROVIDER_STARTUP_FAILED",)
