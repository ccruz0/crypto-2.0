"""
Cross-process Telegram event deduplication.

Uses the existing dedup_events table (Week-5) so all backend workers share state.
Callers claim an event key; only the first claim within TTL may send Telegram.

This is for operational idempotency (same incident must not re-notify), not for
muting intentional alerts.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# In-process fallback when DB is unavailable (tests / transient DB errors).
_memory_claims: Dict[str, float] = {}


def _stable_key(event_key: str) -> str:
    """Fit event keys into dedup_events.key (String(128))."""
    raw = (event_key or "").strip()
    if len(raw) <= 120:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"tg:{digest}:{raw[:80]}"


def claim_telegram_event(
    db: Optional[Session],
    event_key: str,
    *,
    symbol: Optional[str] = None,
    ttl_minutes: int = 360,
    action: str = "telegram",
) -> bool:
    """
    Claim the right to emit a Telegram notification for event_key.

    Returns True if the caller should send (first claim within TTL).
    Returns False if a prior claim is still inside the TTL window.
    """
    key = _stable_key(event_key)
    if not key:
        return True

    if db is not None:
        try:
            from app.services.dedup_events_week5 import check_and_record_dedup

            decision, _is_new = check_and_record_dedup(
                db,
                key=key,
                symbol=symbol,
                action=action[:32] if action else "telegram",
                ttl_minutes=ttl_minutes,
            )
            allowed = decision == "ALLOWED"
            if not allowed:
                logger.info(
                    "telegram_event_dedup: suppressed key=%s symbol=%s ttl_minutes=%s",
                    key[:64],
                    symbol,
                    ttl_minutes,
                )
            return allowed
        except Exception as exc:
            logger.warning(
                "telegram_event_dedup: DB claim failed key=%s error=%s; using memory fallback",
                key[:64],
                exc,
            )

    now = time.time()
    ttl_seconds = max(60, int(ttl_minutes) * 60)
    last = _memory_claims.get(key)
    if last is not None and (now - last) < ttl_seconds:
        logger.info(
            "telegram_event_dedup: memory suppressed key=%s elapsed=%.0fs",
            key[:64],
            now - last,
        )
        return False
    _memory_claims[key] = now
    return True


def is_telegram_event_claimed(
    db: Optional[Session],
    event_key: str,
    *,
    ttl_minutes: int = 360,
) -> bool:
    """
    Read-only check: True when an active claim exists (do not create a claim).
    Used to skip unrecoverable retry loops (e.g. TP already past market).
    """
    key = _stable_key(event_key)
    if not key:
        return False

    if db is not None:
        try:
            from datetime import datetime, timedelta, timezone
            from app.models.dedup_events_week5 import DedupEventWeek5

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
            existing = db.query(DedupEventWeek5).filter(DedupEventWeek5.key == key).first()
            if existing is None:
                return False
            created = existing.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return bool(created and created >= cutoff)
        except Exception as exc:
            logger.debug("telegram_event_dedup: is_claimed DB check failed: %s", exc)

    last = _memory_claims.get(key)
    if last is None:
        return False
    return (time.time() - last) < max(60, int(ttl_minutes) * 60)


def clear_memory_claims_for_tests() -> None:
    """Test helper — clears in-process fallback claims."""
    _memory_claims.clear()
