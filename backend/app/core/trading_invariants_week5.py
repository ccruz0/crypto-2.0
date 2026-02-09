"""
Week 5: Trading safety invariants (fail-fast).

Enforces before placing orders or sending alerts:
- Valid symbol and side
- Quantity > 0
- Price formatting constraints for the exchange
- If TP/SL requested: main order must be confirmed filled (filled_price, filled_qty)
- If SELL: confirm position exists (caller provides position_exists)

Each failure produces a single structured log and returns a typed error.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Side must be BUY or SELL
VALID_SIDES = frozenset({"BUY", "SELL"})

# Reason codes for structured logging (decision=BLOCKED)
REASON_INVALID_SYMBOL = "INVALID_SYMBOL"
REASON_INVALID_SIDE = "INVALID_SIDE"
REASON_INVALID_QUANTITY = "INVALID_QUANTITY"
REASON_INVALID_PRICE = "INVALID_PRICE"
REASON_TP_SL_REQUIRES_FILL = "TP_SL_REQUIRES_FILL"
REASON_SELL_REQUIRES_POSITION = "SELL_REQUIRES_POSITION"


@dataclass
class InvariantFailure:
    """Typed result when an invariant check fails."""
    reason_code: str
    message: str
    details: Optional[dict] = None


def _log_blocked(
    correlation_id: str,
    symbol: str,
    decision: str,
    reason_code: str,
    details: Optional[dict] = None,
) -> None:
    """Emit a single structured log entry for a blocked decision."""
    detail_str = ""
    if details:
        parts = [f"{k}={v}" for k, v in details.items()]
        detail_str = " " + " ".join(parts)
    logger.warning(
        "correlation_id=%s symbol=%s decision=%s reason_code=%s%s",
        correlation_id,
        symbol,
        decision,
        reason_code,
        detail_str,
    )


def validate_symbol_and_side(
    symbol: str,
    side: str,
    correlation_id: str,
) -> Optional[InvariantFailure]:
    """
    Validate symbol is non-empty and side is BUY or SELL.
    Returns InvariantFailure if invalid; None if valid.
    """
    if not symbol or not str(symbol).strip():
        _log_blocked(correlation_id, symbol or "(empty)", "BLOCKED", REASON_INVALID_SYMBOL, {"symbol": symbol})
        return InvariantFailure(REASON_INVALID_SYMBOL, "Symbol must be non-empty", {"symbol": symbol})
    side_upper = (side or "").strip().upper()
    if side_upper not in VALID_SIDES:
        _log_blocked(correlation_id, symbol, "BLOCKED", REASON_INVALID_SIDE, {"side": side})
        return InvariantFailure(REASON_INVALID_SIDE, f"Side must be BUY or SELL, got {side!r}", {"side": side})
    return None


def validate_quantity(
    quantity: float,
    symbol: str,
    correlation_id: str,
) -> Optional[InvariantFailure]:
    """Validate quantity > 0. Returns InvariantFailure if invalid."""
    if quantity is None or (isinstance(quantity, (int, float)) and quantity <= 0):
        _log_blocked(
            correlation_id,
            symbol,
            "BLOCKED",
            REASON_INVALID_QUANTITY,
            {"quantity": quantity},
        )
        return InvariantFailure(
            REASON_INVALID_QUANTITY,
            "Quantity must be greater than 0",
            {"quantity": quantity},
        )
    return None


def validate_price_format(
    price: Optional[float],
    symbol: str,
    correlation_id: str,
    *,
    allow_none: bool = False,
) -> Optional[InvariantFailure]:
    """
    Validate price for exchange: finite, non-negative.
    If allow_none=True, None is valid (e.g. market order).
    """
    if price is None:
        if allow_none:
            return None
        _log_blocked(correlation_id, symbol, "BLOCKED", REASON_INVALID_PRICE, {"price": None})
        return InvariantFailure(REASON_INVALID_PRICE, "Price is required", {"price": None})
    try:
        p = float(price)
    except (TypeError, ValueError):
        _log_blocked(correlation_id, symbol, "BLOCKED", REASON_INVALID_PRICE, {"price": price})
        return InvariantFailure(REASON_INVALID_PRICE, "Price must be a number", {"price": price})
    if not (0 <= p < 1e12):
        _log_blocked(correlation_id, symbol, "BLOCKED", REASON_INVALID_PRICE, {"price": p})
        return InvariantFailure(
            REASON_INVALID_PRICE,
            "Price must be non-negative and finite",
            {"price": p},
        )
    return None


def validate_tp_sl_requires_fill(
    tp_sl_requested: bool,
    filled_price: Optional[float],
    filled_qty: Optional[float],
    symbol: str,
    correlation_id: str,
) -> Optional[InvariantFailure]:
    """
    If TP/SL is requested, main order must be confirmed filled (filled_price and filled_qty).
    """
    if not tp_sl_requested:
        return None
    if filled_price is None or filled_qty is None:
        _log_blocked(
            correlation_id,
            symbol,
            "BLOCKED",
            REASON_TP_SL_REQUIRES_FILL,
            {"filled_price": filled_price, "filled_qty": filled_qty},
        )
        return InvariantFailure(
            REASON_TP_SL_REQUIRES_FILL,
            "TP/SL requested but main order not confirmed filled (filled_price and filled_qty required)",
            {"filled_price": filled_price, "filled_qty": filled_qty},
        )
    try:
        fp, fq = float(filled_price), float(filled_qty)
    except (TypeError, ValueError):
        _log_blocked(
            correlation_id,
            symbol,
            "BLOCKED",
            REASON_TP_SL_REQUIRES_FILL,
            {"filled_price": filled_price, "filled_qty": filled_qty},
        )
        return InvariantFailure(
            REASON_TP_SL_REQUIRES_FILL,
            "filled_price and filled_qty must be numbers",
            {"filled_price": filled_price, "filled_qty": filled_qty},
        )
    if fp <= 0 or fq <= 0:
        _log_blocked(
            correlation_id,
            symbol,
            "BLOCKED",
            REASON_TP_SL_REQUIRES_FILL,
            {"filled_price": fp, "filled_qty": fq},
        )
        return InvariantFailure(
            REASON_TP_SL_REQUIRES_FILL,
            "filled_price and filled_qty must be positive",
            {"filled_price": fp, "filled_qty": fq},
        )
    return None


def validate_sell_position_exists(
    side: str,
    position_exists: bool,
    symbol: str,
    correlation_id: str,
) -> Optional[InvariantFailure]:
    """If SELL, confirm position exists (from caller's position source)."""
    if (side or "").strip().upper() != "SELL":
        return None
    if not position_exists:
        _log_blocked(
            correlation_id,
            symbol,
            "BLOCKED",
            REASON_SELL_REQUIRES_POSITION,
            {"position_exists": False},
        )
        return InvariantFailure(
            REASON_SELL_REQUIRES_POSITION,
            "SELL requires an existing position for the symbol",
            {"position_exists": False},
        )
    return None


def validate_trading_decision(
    symbol: str,
    side: str,
    quantity: float,
    correlation_id: str,
    *,
    price: Optional[float] = None,
    tp_sl_requested: bool = False,
    filled_price: Optional[float] = None,
    filled_qty: Optional[float] = None,
    position_exists: Optional[bool] = None,
    price_required: bool = False,
) -> Optional[InvariantFailure]:
    """
    Run all applicable invariant checks for a trading decision.
    Returns first InvariantFailure if any check fails; None if all pass.
    """
    fail = validate_symbol_and_side(symbol, side, correlation_id)
    if fail:
        return fail
    fail = validate_quantity(quantity, symbol, correlation_id)
    if fail:
        return fail
    if price_required or price is not None:
        fail = validate_price_format(price, symbol, correlation_id, allow_none=not price_required)
        if fail:
            return fail
    fail = validate_tp_sl_requires_fill(
        tp_sl_requested, filled_price, filled_qty, symbol, correlation_id
    )
    if fail:
        return fail
    if position_exists is not None:
        fail = validate_sell_position_exists(side, position_exists, symbol, correlation_id)
        if fail:
            return fail
    return None
