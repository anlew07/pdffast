"""PDFFast V3 public Python package API."""

__version__ = "0.1.0"
from .application.production_preflight import preflight_production_profile
from .config import ParserConfig
from .errors import (
    ConfigurationError,
    OutputValidationError,
    ParseExecutionError,
    PDFFastError,
    ProductionPreflightError,
    ProviderUnavailableError,
)
from .parser import PDFFastParser
from .result import ParseResult

__all__ = [
    "ConfigurationError",
    "OutputValidationError",
    "PDFFastError",
    "PDFFastParser",
    "ParseExecutionError",
    "ParseResult",
    "ParserConfig",
    "ProductionPreflightError",
    "ProviderUnavailableError",
    "preflight_production_profile",
]
