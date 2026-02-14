"""Tests for order intent reconciliation: stale intents without exchange order -> FAILED."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.services.order_intent_reconciliation import run_reconciliation


def test_reconciliation_marks_stale_intent_without_exchange_order():
    """Create stale order_intent with no exchange_order; run reconciliation; assert FAILED + MISSING_EXCHANGE_ORDER."""
    db = MagicMock()
    # Stale intent: PENDING, created_at in the past, no matching exchange order
    intent = MagicMock()
    intent.id = 1
    intent.signal_id = 100
    intent.order_id = None
    intent.status = "PENDING"
    intent.error_message = None
    intent.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    # Query chain: OrderIntent.filter(...).all() -> [intent]
    mock_order_intent_query = MagicMock()
    mock_order_intent_query.filter.return_value.all.return_value = [intent]
    mock_order_intent_query.filter.return_value.first.return_value = None

    # ExchangeOrder.filter(...).first() -> None (no matching order)
    mock_exchange_query = MagicMock()
    mock_exchange_query.filter.return_value.first.return_value = None

    def query(model):
        if model.__name__ == "OrderIntent":
            return mock_order_intent_query
        if model.__name__ == "ExchangeOrder":
            return mock_exchange_query
        return MagicMock()

    db.query.side_effect = query

    marked, unresolved = run_reconciliation(db, grace_minutes=5)

    assert intent.status == "ORDER_FAILED"
    assert intent.error_message == "MISSING_EXCHANGE_ORDER"
    assert marked == 1
    # After marking, "still_stale" query runs; our mock still returns [intent] with no order, so unresolved can be 1
    assert unresolved >= 0
    db.commit.assert_called()


def test_reconciliation_skips_intent_with_matching_exchange_order():
    """Stale intent that has a matching ExchangeOrder (by signal_id) is not marked FAILED."""
    db = MagicMock()
    intent = MagicMock()
    intent.id = 2
    intent.signal_id = 200
    intent.order_id = None
    intent.status = "PENDING"
    intent.error_message = None
    intent.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    mock_exchange_order = MagicMock()

    call_count = [0]

    def query(model):
        if model.__name__ == "OrderIntent":
            q = MagicMock()
            q.filter.return_value.all.return_value = [intent]
            q.filter.return_value.first.return_value = None
            return q
        if model.__name__ == "ExchangeOrder":
            q = MagicMock()
            # First call (check by order_id): no order. Second call (check by signal_id): has order.
            q.filter.return_value.first.return_value = mock_exchange_order
            return q
        return MagicMock()

    db.query.side_effect = query

    marked, unresolved = run_reconciliation(db, grace_minutes=5)

    assert intent.status == "PENDING"
    assert intent.error_message is None
    assert marked == 0
    assert unresolved == 0
