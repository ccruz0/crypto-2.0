"""Helpers for identifying filled entry orders in executed-order views."""

from __future__ import annotations

from typing import Optional, Union

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

PROTECTION_ROLES = frozenset({"STOP_LOSS", "TAKE_PROFIT"})
TRIGGER_ORDER_TYPES = frozenset({
    "STOP_LIMIT",
    "STOP_LOSS",
    "STOP_LOSS_LIMIT",
    "TAKE_PROFIT",
    "TAKE_PROFIT_LIMIT",
})


def _normalize_side(side: Union[str, object]) -> str:
    if hasattr(side, "value"):
        return str(side.value).upper()
    return str(side or "").upper()


def _normalize_status(status: Union[str, object]) -> str:
    if hasattr(status, "value"):
        return str(status.value).upper()
    return str(status or "").upper()


def is_filled_entry_order(
    *,
    status: Union[str, OrderStatusEnum],
    side: Union[str, object],
    order_role: Optional[str] = None,
    order_type: Optional[str] = None,
) -> bool:
    """Return True for filled long (BUY) or short (SELL) entry orders.

    Excludes protection legs (SL/TP roles or trigger order types).
    """
    if _normalize_status(status) != OrderStatusEnum.FILLED.value:
        return False

    role = (order_role or "").upper()
    if role in PROTECTION_ROLES:
        return False

    order_type_upper = (order_type or "").upper()
    if order_type_upper in TRIGGER_ORDER_TYPES:
        return False

    side_val = _normalize_side(side)
    return side_val in {"BUY", "SELL"}


def is_filled_entry_exchange_order(order: ExchangeOrder) -> bool:
    """Convenience wrapper for ExchangeOrder rows."""
    return is_filled_entry_order(
        status=order.status,
        side=order.side,
        order_role=order.order_role,
        order_type=order.order_type,
    )
