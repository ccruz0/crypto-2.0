"""Domain events for event_bus (OrderFilled, ProtectionRequested, AlertEmitted)."""
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class OrderFilled:
    """Emitted when an order is filled (triggers protection flow)."""
    symbol: str
    side: str
    exchange_order_id: str
    filled_price: float
    quantity: float
    source: str
    correlation_id: Optional[str] = None


@dataclass
class ProtectionRequested:
    """Emitted when protection is requested (unconfirmed fill)."""
    symbol: str
    exchange_order_id: str
    source: str
    correlation_id: Optional[str] = None


@dataclass
class AlertEmitted:
    """Emitted when an alert is sent (observability)."""
    symbol: str
    decision_type: str
    reason_code: Optional[str] = None
    source: str = "alert_emitter"
    correlation_id: Optional[str] = None


@dataclass
class InvariantViolation:
    """Emitted when a guard blocks an action (e.g. risk_guard)."""
    decision_type: str  # "FAILED"
    reason_code: str    # "RISK_GUARD_BLOCKED"
    message: str
    symbol: Optional[str] = None
    source: str = "risk_guard"
    correlation_id: Optional[str] = None


__all__ = [
    "AlertEmitted",
    "InvariantViolation",
    "OrderFilled",
    "ProtectionRequested",
]
