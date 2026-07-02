"""Regression tests for executed-fill Telegram spam (fill dedup + throttle source length)."""
from unittest.mock import MagicMock

from app.services.signal_throttle import record_signal_event


def test_record_signal_event_truncates_long_last_source():
    db = MagicMock()
    existing = MagicMock()
    db.query.return_value.filter.return_value.one_or_none.return_value = existing

    record_signal_event(
        db=db,
        symbol="ETH_USDT",
        strategy_key="swing:conservative",
        side="BUY",
        price=1695.0,
        source="lifecycle_order_executed",
        emit_reason="ORDER_EXECUTED: test",
    )

    assert existing.last_source == "lifecycle_order_exec"
    assert len(existing.last_source) == 20
    db.commit.assert_called_once()


def test_fill_tracker_dedupes_repeat_fill(tmp_path):
    from app.services.fill_tracker import FillTracker

    tracker = FillTracker(db_path=str(tmp_path / "fill_tracker.db"))
    ok1, _ = tracker.should_notify_fill("order-1", 0.5, "FILLED")
    tracker.record_fill("order-1", 0.5, "FILLED", notification_sent=True)
    ok2, reason2 = tracker.should_notify_fill("order-1", 0.5, "FILLED")

    assert ok1 is True
    assert ok2 is False
    assert "already sent" in reason2.lower()
