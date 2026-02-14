"""
Order intent reconciliation: mark stale PENDING intents (no exchange order) as ORDER_FAILED.
Used by nightly audit. Strict semantics: callers must FAIL the audit if DB is unreachable
or if any stale intents remain after reconciliation.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.models.order_intent import OrderIntent
from app.models.exchange_order import ExchangeOrder

logger = logging.getLogger(__name__)

# Status value we set on intents that have no matching exchange order after grace window
ORDER_FAILED = "ORDER_FAILED"
MISSING_EXCHANGE_ORDER = "MISSING_EXCHANGE_ORDER"


def run_reconciliation(db: Session, grace_minutes: int = 10) -> tuple[int, int]:
    """
    Find PENDING order intents older than grace_minutes with no matching exchange order,
    mark them as ORDER_FAILED with error_message=MISSING_EXCHANGE_ORDER, commit, then
    count how many remain stale (still PENDING with no order).

    Returns:
        (marked_count, unresolved_count)
        - marked_count: intents updated to ORDER_FAILED
        - unresolved_count: intents still PENDING with no exchange order after this run
    """
    if db is None:
        raise ValueError("db session is required")
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
        has_order = _has_matching_exchange_order(db, intent)
        if not has_order:
            intent.status = ORDER_FAILED
            intent.error_message = MISSING_EXCHANGE_ORDER
            marked += 1
            logger.info(
                "Reconciled stale intent id=%s signal_id=%s -> ORDER_FAILED (MISSING_EXCHANGE_ORDER)",
                intent.id,
                intent.signal_id,
            )
    if marked:
        db.commit()
    # Count still-stale: PENDING/ORDER_PLACED, old, no matching order (re-query after possible commit)
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
        if not _has_matching_exchange_order(db, intent):
            unresolved += 1
    return marked, unresolved


def _has_matching_exchange_order(db: Session, intent: OrderIntent) -> bool:
    """True if there is an exchange order for this intent (by order_id or by signal/trade_signal_id)."""
    if intent.order_id:
        if db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == intent.order_id).first():
            return True
    if intent.signal_id is not None:
        if (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.trade_signal_id == intent.signal_id)
            .first()
        ):
            return True
    return False
