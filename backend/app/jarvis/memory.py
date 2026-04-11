"""Pluggable memory for Jarvis (in-process default; swap for Redis/DB later)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

_MAX_TURNS = 20


class JarvisMemory(ABC):
    """Interface for conversation memory (orchestrator depends only on this)."""

    @abstractmethod
    def save_interaction(self, user_input: str, result: Any) -> None:
        ...

    @abstractmethod
    def get_recent_context(self, max_items: int = 5) -> str:
        ...

    def clear(self) -> None:
        """Override to reset storage (tests)."""
        pass


class InMemoryJarvisMemory(JarvisMemory):
    """FIFO-capped in-process store (last 20 turns)."""

    def __init__(self) -> None:
        self._interactions: list[dict[str, Any]] = []

    def save_interaction(self, user_input: str, result: Any) -> None:
        self._interactions.append(
            {
                "input": (user_input or "")[:4000],
                "result": result,
            }
        )
        while len(self._interactions) > _MAX_TURNS:
            self._interactions.pop(0)

    def get_recent_context(self, max_items: int = 5) -> str:
        if max_items < 1:
            return ""
        tail = self._interactions[-max_items:]
        lines: list[str] = []
        for i, row in enumerate(tail, start=1):
            lines.append(f"{i}. User: {row.get('input', '')}")
            lines.append(f"   Result: {row.get('result', '')!r}")
        return "\n".join(lines).strip()

    def clear(self) -> None:
        self._interactions.clear()


_default_memory: JarvisMemory = InMemoryJarvisMemory()


def get_default_memory() -> JarvisMemory:
    return _default_memory


def reset_default_memory_for_tests() -> None:
    """Clear the process-global default store (tests only)."""
    if isinstance(_default_memory, InMemoryJarvisMemory):
        _default_memory.clear()


# Legacy module-level API (delegates to default) — preserved for callers that imported these.
def save_interaction(user_input: str, result: Any) -> None:
    get_default_memory().save_interaction(user_input, result)


def get_recent_context(max_items: int = 5) -> str:
    return get_default_memory().get_recent_context(max_items=max_items)


def clear_memory() -> None:
    get_default_memory().clear()
