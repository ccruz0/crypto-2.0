"""In-memory event bus for OrderFilled, ProtectionRequested, AlertEmitted (observability)."""
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_BUS: Any = None


def is_event_bus_enabled() -> bool:
    """Return True if event bus publishing is enabled (e.g. via env)."""
    return os.getenv("EVENT_BUS_ENABLED", "false").lower() == "true"


def get_event_bus() -> "EventBus":
    """Return the singleton event bus."""
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS


class EventBus:
    """Simple in-memory bus; publish is a no-op unless handlers are registered."""

    def publish(self, event: Any) -> None:
        """Publish an event (no-op by default; extend to add subscribers)."""
        logger.debug("[EVENT_BUS] publish %s", type(event).__name__)


__all__ = [
    "EventBus",
    "get_event_bus",
    "is_event_bus_enabled",
]
