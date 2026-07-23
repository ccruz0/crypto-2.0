"""Throttle repeated order-failure Telegram / Control feed notifications.

Signal monitor retries every ~30s. Identical failures (same symbol + reason)
must page once per TTL, not every cycle. First alert is always allowed.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Default: 6h — matches config-failure telegram claim window.
_ORDER_FAIL_TTL_MINUTES = int(os.getenv("ORDER_FAILURE_TELEGRAM_TTL_MINUTES", str(6 * 60)))
# Monitoring/Control feed for TRADE_BLOCKED: align with live cooldown (~30m).
_TRADE_BLOCK_UI_TTL_MINUTES = int(os.getenv("TRADE_BLOCK_UI_TELEGRAM_TTL_MINUTES", "30"))
_CHRONIC_TRADE_BLOCK_UI_TTL_MINUTES = int(
    os.getenv("CHRONIC_TRADE_BLOCK_UI_TELEGRAM_TTL_MINUTES", str(6 * 60))
)


def normalize_failure_kind(failure_kind: Optional[str]) -> str:
    """Stable failure bucket for dedup keys (strip counters / noise)."""
    raw = (failure_kind or "EXCHANGE_ERROR_UNKNOWN").strip().upper()
    raw = re.sub(r"\(\d+/\d+\)", "", raw)
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"[^A-Z0-9_]+", "", raw)
    return (raw or "EXCHANGE_ERROR_UNKNOWN")[:80]


def claim_order_failure_telegram(
    db: Optional[Session],
    symbol: str,
    failure_kind: str,
    *,
    side: str = "BUY",
    ttl_minutes: Optional[int] = None,
) -> bool:
    """
    Claim once-per-incident Telegram for exchange/order placement failures.

    Returns True when the caller may send Telegram and persist a Control feed row.
    """
    kind = normalize_failure_kind(failure_kind)
    sym = (symbol or "").upper() or "UNKNOWN"
    side_u = (side or "BUY").upper()
    ttl = int(ttl_minutes) if ttl_minutes is not None else _ORDER_FAIL_TTL_MINUTES
    ttl = max(5, ttl)
    try:
        from app.services.telegram_event_dedup import claim_telegram_event

        return claim_telegram_event(
            db,
            f"order_fail:{kind}:{sym}:{side_u}",
            symbol=sym,
            ttl_minutes=ttl,
            action="order_fail",
        )
    except Exception as exc:
        logger.warning(
            "order_fail telegram claim failed symbol=%s kind=%s error=%s",
            sym,
            kind,
            exc,
        )
        return True


def claim_trade_block_monitoring_row(
    db: Optional[Session],
    symbol: str,
    side: str,
    reason: Optional[str],
    *,
    chronic: bool = False,
    ttl_minutes: Optional[int] = None,
) -> bool:
    """
    Claim once-per-incident Control/monitoring row for TRADE_BLOCKED.

    Chronic caps (e.g. MAX_OPEN_ORDERS_TOTAL) use a longer TTL so the feed
    is not refilled every monitor cycle while the host stays over the limit.
    """
    from app.utils.trading_guardrails import normalize_trade_block_reason_for_dedup

    sym = (symbol or "").upper() or "UNKNOWN"
    side_u = (side or "BUY").upper()
    normalized = normalize_trade_block_reason_for_dedup(reason or "")
    if ttl_minutes is not None:
        ttl = max(5, int(ttl_minutes))
    else:
        ttl = (
            max(5, _CHRONIC_TRADE_BLOCK_UI_TTL_MINUTES)
            if chronic
            else max(5, _TRADE_BLOCK_UI_TTL_MINUTES)
        )
    try:
        from app.services.telegram_event_dedup import claim_telegram_event

        return claim_telegram_event(
            db,
            f"trade_block_ui:{sym}:{side_u}:{normalized}",
            symbol=sym,
            ttl_minutes=ttl,
            action="trade_block_ui",
        )
    except Exception as exc:
        logger.warning(
            "trade_block_ui claim failed symbol=%s side=%s error=%s",
            sym,
            side_u,
            exc,
        )
        return True
