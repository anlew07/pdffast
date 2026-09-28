"""PDFFast v2 package."""

__version__ = "0.1.0"
from .parser import PDFFastParser
from .config import ParserConfig
from .errors import ConfigurationError, ParseExecutionError, PDFFastError, ProviderUnavailableError
from .result import ParseResult

__all__ = [
    "ConfigurationError",
    "ParseExecutionError",
    "ParserConfig",
    "PDFFastError",
    "PDFFastParser",
    "ParseResult",
    "ProviderUnavailableError",
]
