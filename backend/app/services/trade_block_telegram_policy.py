"""Policy for when expected trading noise must not page Telegram live.

Expected capacity / open-order limits and dust small-position SL/TP cases stay
visible in Monitoring (caller persists rows) and may roll into the daily summary.
Real failures (auth, exchange reject, InstanceDown, unprotected flatten, etc.)
still page Telegram.
"""

from __future__ import annotations

from typing import Optional

# Substrings matched case-insensitively against reason / error text.
# Keep this allowlist tight: only chronic / expected capacity limits.
SUPPRESS_LIVE_TELEGRAM_REASON_SUBSTRINGS: tuple[str, ...] = (
    "MAX_OPEN_ORDERS_TOTAL",
    "SYSTEM_CORE_MAX_OPEN_TRADES",
    "SYSTEM_CORE_ONE_ACTIVE_TRADE_PER_COIN",
    "MAX_OPEN_ORDERS_PER_SYMBOL",
    "MAX_OPEN_ORDERS_REACHED",
    "MAXIMUM OPEN ORDERS",
    "OPEN_ORDERS_LIMIT",
    "MAX_ORDERS_PER_SYMBOL_PER_DAY",
    "ONE_ACTIVE_TRADE_PER_COIN",
)

# Canonical reason codes (DecisionReason / classify_exchange_error).
SUPPRESS_LIVE_TELEGRAM_REASON_CODES: frozenset[str] = frozenset(
    {
        "SYSTEM_CORE_MAX_OPEN_TRADES",
        "ONE_ACTIVE_TRADE_PER_COIN",
        "MAX_OPEN_TRADES_REACHED",
        "ALREADY_HAS_OPEN_ORDER",
    }
)

# Small-position / cannot-protect-with-SL-TP (dust) — Monitoring only.
SUPPRESS_SMALL_POSITION_TELEGRAM_SUBSTRINGS: tuple[str, ...] = (
    "SMALL POSITION UNPROTECTED",
    "QUANTITY_BELOW_MIN",
    "BELOW MIN_QUANTITY",
    "POSITION CANNOT BE PROTECTED WITH SL/TP",
)


def _haystack(*parts: Optional[str]) -> str:
    return " ".join(p for p in parts if p).upper()


def is_expected_capacity_limit_reason(*reasons: Optional[str], reason_code: Optional[str] = None) -> bool:
    """True when the block/failure is an expected open-order / max-trades cap."""
    code = (reason_code or "").strip().upper()
    if code and code in SUPPRESS_LIVE_TELEGRAM_REASON_CODES:
        return True
    haystack = _haystack(*reasons, reason_code)
    if not haystack:
        return False
    return any(s in haystack for s in SUPPRESS_LIVE_TELEGRAM_REASON_SUBSTRINGS)


def suppress_live_trade_block_telegram(*reasons: Optional[str], reason_code: Optional[str] = None) -> bool:
    """
    Return True when a TRADE BLOCKED reason must not send live Telegram.

    Chronic host-wide / per-coin open-order caps are Monitoring + daily summary only.
    Lifecycle / monitoring rows are still written by the caller.
    """
    return is_expected_capacity_limit_reason(*reasons, reason_code=reason_code)


def suppress_order_failure_telegram(
    *reasons: Optional[str],
    reason_code: Optional[str] = None,
) -> bool:
    """
    Return True when an ORDER FAILED / automatic-order-failure alert must not
    page Telegram (expected capacity limit, not a real exchange outage).
    """
    return is_expected_capacity_limit_reason(*reasons, reason_code=reason_code)


def suppress_small_position_unprotected_telegram(*texts: Optional[str]) -> bool:
    """
    Return True for dust / below-min-qty positions that cannot take SL/TP.

    These remain in Monitoring; live Telegram is suppressed. Real unprotected
    flatten / rules-missing / critical SL-TP failures are NOT matched here.
    """
    haystack = _haystack(*texts)
    if not haystack:
        return False
    return any(s in haystack for s in SUPPRESS_SMALL_POSITION_TELEGRAM_SUBSTRINGS)
