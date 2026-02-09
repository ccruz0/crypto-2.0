"""
Week 5: Tests for dedup_events (idempotency key, TTL, block duplicate order/alert).
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.services.dedup_events_week5 import (
    compute_dedup_key,
    compute_dedup_key_from_context,
    check_and_record_dedup,
    count_dedup_events_recent,
    DEDUP_TTL_MINUTES,
)


def test_compute_dedup_key_deterministic():
    k1 = compute_dedup_key(
        "BTC_USDT", "BUY", "swing", "1h", "50000.00", "202602091200"
    )
    k2 = compute_dedup_key(
        "BTC_USDT", "BUY", "swing", "1h", "50000.00", "202602091200"
    )
    assert k1 == k2
    assert len(k1) == 64  # sha256 hex


def test_compute_dedup_key_different_inputs_different_keys():
    k1 = compute_dedup_key("BTC_USDT", "BUY", "s", "t", "1", "1")
    k2 = compute_dedup_key("BTC_USDT", "SELL", "s", "t", "1", "1")
    assert k1 != k2


def test_compute_dedup_key_from_context_same_inputs_same_key():
    now = datetime(2026, 2, 9, 12, 3, 0, tzinfo=timezone.utc)
    k1 = compute_dedup_key_from_context(
        "BTC_USDT", "BUY", strategy_key="swing", trigger_price=50000.0, now=now
    )
    k2 = compute_dedup_key_from_context(
        "BTC_USDT", "BUY", strategy_key="swing", trigger_price=50000.0, now=now
    )
    assert k1 == k2


def test_check_and_record_dedup_allowed_when_empty():
    """First call with a key should return ALLOWED and record."""
    db = MagicMock()
    # Simulate no existing row
    db.query.return_value.filter.return_value.first.return_value = None
    db.commit = MagicMock()
    with patch("app.services.dedup_events_week5.DedupEventWeek5") as MockModel:
        MockModel.return_value = MagicMock()
        decision, is_new = check_and_record_dedup(
            db, "abc123", correlation_id="c1", symbol="BTC_USDT", action="alert"
        )
    assert decision == "ALLOWED"
    assert is_new is True
    db.add.assert_called_once()
    db.commit.assert_called()


def test_check_and_record_dedup_deduped_when_recent():
    """If key exists and created_at within TTL, return DEDUPED."""
    db = MagicMock()
    existing = MagicMock()
    existing.key = "abc123"
    existing.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.query.return_value.filter.return_value.first.return_value = existing
    decision, is_new = check_and_record_dedup(
        db, "abc123", correlation_id="c1", symbol="BTC_USDT", action="alert", ttl_minutes=15
    )
    assert decision == "DEDUPED"
    assert is_new is False


def test_check_and_record_dedup_allowed_when_old():
    """If key exists but created_at older than TTL, refresh and allow."""
    db = MagicMock()
    existing = MagicMock()
    existing.key = "abc123"
    existing.created_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    db.query.return_value.filter.return_value.first.return_value = existing
    decision, is_new = check_and_record_dedup(
        db, "abc123", correlation_id="c1", symbol="BTC_USDT", action="alert", ttl_minutes=15
    )
    assert decision == "ALLOWED"
    assert is_new is False
    db.commit.assert_called()


def test_same_signal_twice_second_deduped():
    """Same key: first call ALLOWED (no row), second call DEDUPED (recent row)."""
    from app.services.dedup_events_week5 import compute_dedup_key_from_context
    now = datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc)
    key = compute_dedup_key_from_context(
        "BTC_USDT", "BUY", strategy_key="swing", trigger_price=50000.0, now=now
    )
    db = MagicMock()
    existing = MagicMock()
    existing.key = key
    existing.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)  # within TTL
    db.query.return_value.filter.return_value.first.side_effect = [None, existing]
    db.add = MagicMock()
    db.commit = MagicMock()
    with patch("app.services.dedup_events_week5.DedupEventWeek5") as MockModel:
        MockModel.return_value = MagicMock()
        d1, _ = check_and_record_dedup(db, key, symbol="BTC_USDT", action="order")
    assert d1 == "ALLOWED"
    d2, _ = check_and_record_dedup(db, key, symbol="BTC_USDT", action="order", ttl_minutes=15)
    assert d2 == "DEDUPED"


def test_same_signal_twice_only_one_order_placement_called():
    """Run the same signal (same dedup key) twice; only one order placement should be allowed."""
    from app.services.dedup_events_week5 import compute_dedup_key_from_context
    now = datetime(2026, 2, 9, 12, 0, 0, tzinfo=timezone.utc)
    key = compute_dedup_key_from_context(
        "ETH_USDT", "BUY", strategy_key="swing", trigger_price=3000.0, now=now
    )
    db = MagicMock()
    existing_recent = MagicMock()
    existing_recent.key = key
    existing_recent.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    db.query.return_value.filter.return_value.first.side_effect = [None, existing_recent]
    db.add = MagicMock()
    db.commit = MagicMock()
    place_order_mock = MagicMock(return_value={"order_id": "ord_1"})
    with patch("app.services.dedup_events_week5.DedupEventWeek5") as MockModel:
        MockModel.return_value = MagicMock()
        for _ in range(2):
            decision, _ = check_and_record_dedup(db, key, symbol="ETH_USDT", action="order", ttl_minutes=15)
            if decision == "ALLOWED":
                place_order_mock()
    assert place_order_mock.call_count == 1
