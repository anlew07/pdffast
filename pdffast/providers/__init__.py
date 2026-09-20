"""Provider runtime contracts and lazy adapter registry."""

from .base import Provider, ProviderPreflight, ProviderTask, RawProviderResult
from .registry import ProviderRegistry

__all__ = [
    "Provider",
    "ProviderPreflight",
    "ProviderRegistry",
    "ProviderTask",
    "RawProviderResult",
]
