"""Signal → order business rules (alert-gated placement, no duplicate paths)."""
from __future__ import annotations

import os
from typing import Optional, Tuple


def signal_order_requires_alert() -> bool:
    """When true (default), orders are placed only after a Telegram alert is sent.

    The orchestrator handles placement on alert send; legacy ``_create_buy_order`` /
    ``_create_sell_order`` must not run in parallel.

    Set ``SIGNAL_ORDER_REQUIRES_ALERT=false`` to restore alert-independent trading.
    """
    return os.getenv("SIGNAL_ORDER_REQUIRES_ALERT", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def resolve_legacy_buy_order_gate(
    *,
    blocked_by_limits: bool,
    buy_alert_sent_successfully: bool,
) -> Tuple[bool, Optional[str]]:
    """Decide whether the legacy BUY order block should run this cycle."""
    if blocked_by_limits:
        return False, "blocked_by_limits"
    if buy_alert_sent_successfully:
        return False, "orchestrator_handled"
    if signal_order_requires_alert():
        return False, "alert_required_not_sent"
    return True, None
