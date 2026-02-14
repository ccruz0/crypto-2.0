"""
Order intent reconciliation: mark stale intents (no matching exchange order) as FAILED.
Used by scripts/aws/reconcile_order_intents.sh and tests.
"""
from datetime import datetime, timezone, timedelta
from typing import Tuple

from sqlalchemy.orm import Session

from app.models.order_intent import OrderIntent
from app.models.exchange_order import ExchangeOrder


def run_reconciliation(db: Session, grace_minutes: int = 5) -> Tuple[int, int]:
    """
    Find stale order intents (PENDING/ORDER_PLACED, older than grace_minutes),
    mark those without a matching ExchangeOrder as ORDER_FAILED (MISSING_EXCHANGE_ORDER).
    Returns (marked_count, unresolved_count). Unresolved = still stale without match after run.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=grace_minutes)
    stale = (
        db.query(OrderIntent)
        .filter(
            OrderIntent.status.in_(["PENDING", "ORDER_PLACED"]),
            OrderIntent.created_at < cutoff,
        )
        .all()
    )
    marked = 0
    for intent in stale:
        has_order = False
        if intent.order_id:
            has_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == intent.order_id)
                .first()
            ) is not None
        if not has_order and intent.signal_id is not None:
            has_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.trade_signal_id == intent.signal_id)
                .first()
            ) is not None
        if has_order:
            continue
        intent.status = "ORDER_FAILED"
        intent.error_message = "MISSING_EXCHANGE_ORDER"
        db.commit()
        marked += 1

    still_stale = (
        db.query(OrderIntent)
        .filter(
            OrderIntent.status.in_(["PENDING", "ORDER_PLACED"]),
            OrderIntent.created_at < cutoff,
        )
        .all()
    )
    unresolved = 0
    for intent in still_stale:
        has_order = False
        if intent.order_id:
            has_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == intent.order_id)
                .first()
            ) is not None
        if not has_order and intent.signal_id is not None:
            has_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.trade_signal_id == intent.signal_id)
                .first()
            ) is not None
        if not has_order:
            unresolved += 1
    return marked, unresolved
