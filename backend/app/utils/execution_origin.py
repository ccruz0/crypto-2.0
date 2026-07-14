"""Resolve execution origin for filled orders (alert vs manual vs SL/TP)."""

from __future__ import annotations

from typing import Optional, Union

from app.utils.filled_entry_order import PROTECTION_ROLES, TRIGGER_ORDER_TYPES

EXECUTION_ORIGIN_STOP_LOSS = "STOP_LOSS"
EXECUTION_ORIGIN_TAKE_PROFIT = "TAKE_PROFIT"
EXECUTION_ORIGIN_ALERT = "ALERT"
EXECUTION_ORIGIN_MANUAL = "MANUAL"
EXECUTION_ORIGIN_EXCHANGE = "EXCHANGE"

_STOP_LOSS_TYPES = frozenset({"STOP_LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"})
_TAKE_PROFIT_TYPES = frozenset({"TAKE_PROFIT", "TAKE_PROFIT_LIMIT"})


def _normalize(value: Optional[str]) -> str:
    return (value or "").upper().strip()


def resolve_execution_origin(
    *,
    order_role: Optional[str] = None,
    order_type: Optional[str] = None,
    parent_order_id: Optional[str] = None,
    trade_signal_id: Optional[int] = None,
    has_order_intent: bool = False,
    has_trade_signal_link: bool = False,
) -> str:
    """Classify how an executed order was created.

    Priority: SL/TP role or trigger type > parent protection child > alert/intent > manual.
    """
    role = _normalize(order_role)
    if role == "STOP_LOSS":
        return EXECUTION_ORIGIN_STOP_LOSS
    if role == "TAKE_PROFIT":
        return EXECUTION_ORIGIN_TAKE_PROFIT

    order_type_upper = _normalize(order_type)
    if order_type_upper in _STOP_LOSS_TYPES:
        return EXECUTION_ORIGIN_STOP_LOSS
    if order_type_upper in _TAKE_PROFIT_TYPES:
        return EXECUTION_ORIGIN_TAKE_PROFIT

    if parent_order_id:
        if order_type_upper in _STOP_LOSS_TYPES:
            return EXECUTION_ORIGIN_STOP_LOSS
        if order_type_upper in _TAKE_PROFIT_TYPES:
            return EXECUTION_ORIGIN_TAKE_PROFIT
        return EXECUTION_ORIGIN_EXCHANGE

    if trade_signal_id or has_order_intent or has_trade_signal_link:
        return EXECUTION_ORIGIN_ALERT

    return EXECUTION_ORIGIN_MANUAL


def execution_origin_label(origin: str) -> str:
    """Spanish label for dashboard badges."""
    labels = {
        EXECUTION_ORIGIN_STOP_LOSS: "SL ejecutado",
        EXECUTION_ORIGIN_TAKE_PROFIT: "TP ejecutado",
        EXECUTION_ORIGIN_ALERT: "Alerta",
        EXECUTION_ORIGIN_MANUAL: "Manual",
        EXECUTION_ORIGIN_EXCHANGE: "Exchange",
    }
    return labels.get(origin, origin)


def format_type_display(
    *,
    order_type: Optional[str],
    execution_origin: str,
) -> str:
    """Human-readable Type column: e.g. MARKET (Alerta), SL ejecutado."""
    base = (order_type or "LIMIT").upper()
    origin = execution_origin

    if origin == EXECUTION_ORIGIN_STOP_LOSS:
        return "SL ejecutado"
    if origin == EXECUTION_ORIGIN_TAKE_PROFIT:
        return "TP ejecutado"

    label = execution_origin_label(origin)
    if origin == EXECUTION_ORIGIN_ALERT:
        return f"{base} (Alerta)"
    if origin == EXECUTION_ORIGIN_MANUAL:
        return f"{base} (Manual)"
    return base


def is_protection_execution(
    *,
    order_role: Optional[str] = None,
    order_type: Optional[str] = None,
    execution_origin: Optional[str] = None,
) -> bool:
    """True when the fill is from SL/TP protection, not an entry."""
    if execution_origin in {EXECUTION_ORIGIN_STOP_LOSS, EXECUTION_ORIGIN_TAKE_PROFIT}:
        return True
    role = _normalize(order_role)
    if role in PROTECTION_ROLES:
        return True
    return _normalize(order_type) in TRIGGER_ORDER_TYPES
