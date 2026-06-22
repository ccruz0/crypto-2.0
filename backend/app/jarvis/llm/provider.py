"""Abstract LLM provider interface (the vendor-neutral seam).

This module intentionally has no provider/SDK imports so that anything
depending only on the interface stays decoupled from a specific vendor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider call fails.

    Concrete providers must wrap their vendor-specific exceptions in this type
    so callers can handle a single, stable error without importing SDK errors.
    """


@dataclass(frozen=True)
class LLMResponse:
    """Normalized response from any provider."""

    text: str
    model_id: str
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Minimal completion seam. Keep this interface intentionally thin."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Return a completion for ``prompt``. Must raise ``LLMProviderError`` on failure."""
        raise NotImplementedError
