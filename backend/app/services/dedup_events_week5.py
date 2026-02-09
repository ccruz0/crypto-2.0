"""
Week 5: Dedup for actionable events (order placement, alert) with TTL window.

Key = hash(symbol, side, strategy_name, timeframe, trigger_price_bucket, time_bucket).
If key already exists within TTL (default 15 minutes), block order and block alert; log decision=DEDUPED.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Any
from sqlalchemy.orm import Session

from app.models.dedup_events_week5 import DedupEventWeek5
from app.utils.symbols import normalize_symbol_for_exchange

logger = logging.getLogger(__name__)

# Default TTL for dedup window (minutes)
DEDUP_TTL_MINUTES = 15


def compute_dedup_key(
    symbol: str,
    side: str,
    strategy_name: str,
    timeframe: str,
    trigger_price_bucket: str,
    time_bucket: str,
) -> str:
    """
    Deterministic dedup key for an actionable event.
    strategy_name and timeframe can be from strategy_key or "UNKNOWN".
    """
    normalized_symbol = normalize_symbol_for_exchange(symbol)
    side_upper = (side or "BUY").strip().upper()
    raw = "|".join([
        normalized_symbol,
        side_upper,
        (strategy_name or "UNKNOWN").strip(),
        (str(timeframe) or "UNKNOWN").strip(),
        (str(trigger_price_bucket) or "").strip(),
        (str(time_bucket) or "").strip(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_dedup_key_from_context(
    symbol: str,
    side: str,
    strategy_key: Optional[str] = None,
    trigger_price: Optional[float] = None,
    now: Optional[datetime] = None,
) -> str:
    """
    Build dedup key from context used in signal monitor.
    Uses 5-minute time bucket and 2-decimal price bucket.
    """
    now = now or datetime.now(timezone.utc)
    bucket_minute = now.minute - (now.minute % 5)
    bucketed = now.replace(minute=bucket_minute, second=0, microsecond=0)
    time_bucket = bucketed.strftime("%Y%m%d%H%M")
    strategy_name = (strategy_key or "UNKNOWN").strip()
    timeframe = "UNKNOWN"
    price_bucket = f"{float(trigger_price):.2f}" if trigger_price is not None else ""
    return compute_dedup_key(
        symbol=symbol,
        side=side,
        strategy_name=strategy_name,
        timeframe=timeframe,
        trigger_price_bucket=price_bucket,
        time_bucket=time_bucket,
    )


def check_and_record_dedup(
    db: Session,
    key: str,
    correlation_id: Optional[str] = None,
    symbol: Optional[str] = None,
    action: str = "order",
    payload_json: Optional[str] = None,
    ttl_minutes: int = DEDUP_TTL_MINUTES,
) -> Tuple[str, bool]:
    """
    Check if key exists within TTL; if not, record it and allow.
    Returns (decision, is_new): ("DEDUPED", False) if within TTL and block; ("ALLOWED", True/False) if allowed.
    When allowed, we insert or update the row so the key is in the window for next time.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=ttl_minutes)
    existing = db.query(DedupEventWeek5).filter(DedupEventWeek5.key == key).first()
    if existing:
        if existing.created_at >= cutoff:
            logger.warning(
                "correlation_id=%s symbol=%s decision=DEDUPED reason_code=DEDUP_KEY_IN_TTL key=%s",
                correlation_id,
                symbol,
                key[:32],
            )
            return "DEDUPED", False
        existing.created_at = now
        existing.correlation_id = correlation_id
        existing.symbol = symbol
        existing.action = action
        existing.payload_json = payload_json
        db.commit()
        return "ALLOWED", False
    try:
        row = DedupEventWeek5(
            key=key,
            correlation_id=correlation_id,
            symbol=symbol,
            action=action,
            payload_json=payload_json,
        )
        db.add(row)
        db.commit()
        return "ALLOWED", True
    except Exception as e:
        db.rollback()
        existing = db.query(DedupEventWeek5).filter(DedupEventWeek5.key == key).first()
        if existing and existing.created_at >= cutoff:
            logger.warning(
                "correlation_id=%s symbol=%s decision=DEDUPED reason_code=DEDUP_KEY_IN_TTL key=%s",
                correlation_id,
                symbol,
                key[:32],
            )
            return "DEDUPED", False
        if existing:
            existing.created_at = now
            db.commit()
            return "ALLOWED", False
        raise


def count_dedup_events_recent(db: Session, minutes: int = 60) -> int:
    """Count dedup_events rows in the last N minutes (for health snapshot). Returns 0 if table missing."""
    try:
        from sqlalchemy import func as sql_func
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return db.query(sql_func.count(DedupEventWeek5.id)).filter(
            DedupEventWeek5.created_at >= cutoff
        ).scalar() or 0
    except Exception:
        return 0
