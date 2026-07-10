"""Shared SL/TP protection idempotency helpers (cross-process safe)."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

logger = logging.getLogger(__name__)

ACTIVE_PROTECTION_STATUSES = [
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
]

_SL_TP_LOCK_NAMESPACE = 876543210


def get_active_protection_order(
    db: Session,
    parent_order_id: str,
    role: str,
) -> Optional[ExchangeOrder]:
    """Return the oldest active protection order for a parent entry and role."""
    return (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.parent_order_id == str(parent_order_id),
            ExchangeOrder.order_role == role,
            ExchangeOrder.status.in_(ACTIVE_PROTECTION_STATUSES),
        )
        .order_by(ExchangeOrder.id.asc())
        .first()
    )


def has_complete_sl_tp_protection(db: Session, parent_order_id: str) -> bool:
    """True when both an active SL and TP exist for the parent entry order."""
    sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS")
    tp = get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
    return sl is not None and tp is not None


def _sl_tp_lock_key(parent_order_id: str) -> int:
    return (_SL_TP_LOCK_NAMESPACE ^ hash(str(parent_order_id))) & 0x7FFFFFFF


def try_acquire_sl_tp_creation_lock(db: Session, parent_order_id: str) -> bool:
    """Try to acquire a Postgres advisory lock for SL/TP creation on one parent order."""
    key = _sl_tp_lock_key(parent_order_id)
    acquired = bool(
        db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
    )
    if not acquired:
        logger.info(
            "[SLTP_LOCK] Could not acquire advisory lock for parent=%s (another worker is creating SL/TP)",
            parent_order_id,
        )
    return acquired


def release_sl_tp_creation_lock(db: Session, parent_order_id: str) -> None:
    """Release the Postgres advisory lock for SL/TP creation on one parent order."""
    key = _sl_tp_lock_key(parent_order_id)
    try:
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    except Exception as exc:
        logger.warning(
            "[SLTP_LOCK] Failed to release advisory lock for parent=%s: %s",
            parent_order_id,
            exc,
        )
