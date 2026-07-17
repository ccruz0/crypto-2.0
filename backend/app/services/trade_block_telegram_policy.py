"""Policy for when TRADE BLOCKED should page Telegram live vs daily summary only."""

from __future__ import annotations

from typing import Optional


def suppress_live_trade_block_telegram(*reasons: Optional[str]) -> bool:
    """
    Return True when a TRADE BLOCKED reason must not send live Telegram.

    Chronic host-wide open-order cap is rolled into the daily summary instead.
    Lifecycle / monitoring rows are still written by the caller.
    """
    haystack = " ".join(r for r in reasons if r).upper()
    return "MAX_OPEN_ORDERS_TOTAL" in haystack
