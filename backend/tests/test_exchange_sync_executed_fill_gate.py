"""Unit tests for should_notify_executed_fill gating (stops Telegram spam from historical order sync)."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.exchange_sync import (
    RECENT_FILL_WINDOW_SECONDS,
    should_notify_executed_fill,
)


def _order(
    trade_signal_id=None,
    parent_order_id=None,
    exchange_update_time=None,
    exchange_create_time=None,
    execution_notified_at=None,
):
    o = MagicMock()
    o.trade_signal_id = trade_signal_id
    o.parent_order_id = parent_order_id
    o.exchange_update_time = exchange_update_time
    o.exchange_create_time = exchange_create_time
    o.execution_notified_at = execution_notified_at
    return o


def test_historical_fill_not_system_not_admin_no_notify():
    """Historical fill (older than 1h), not system order, not admin -> no notify."""
    now = datetime.now(timezone.utc)
    filled_at = now - timedelta(seconds=RECENT_FILL_WINDOW_SECONDS + 60)
    order = _order(
        trade_signal_id=None,
        parent_order_id=None,
        exchange_update_time=filled_at,
        exchange_create_time=filled_at,
        execution_notified_at=None,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed is False
    assert "historical fill" in reason.lower() or "outside window" in reason.lower()


def test_recent_fill_not_system_notify_once_then_block():
    """Recent fill (within 1h), not system order -> allow first time, block on second (already notified)."""
    now = datetime.now(timezone.utc)
    filled_at = now - timedelta(seconds=300)
    order = _order(
        trade_signal_id=None,
        parent_order_id=None,
        exchange_update_time=filled_at,
        exchange_create_time=filled_at,
        execution_notified_at=None,
    )
    allowed1, reason1 = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed1 is True
    assert "recent" in reason1.lower()

    order.execution_notified_at = now
    allowed2, reason2 = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed2 is False
    assert "already notified" in reason2.lower()


def test_system_order_trade_signal_id_allows_even_old():
    """System order (trade_signal_id set) -> allow even if fill is old."""
    now = datetime.now(timezone.utc)
    filled_at = now - timedelta(seconds=RECENT_FILL_WINDOW_SECONDS + 3600)
    order = _order(
        trade_signal_id=123,
        parent_order_id=None,
        exchange_update_time=filled_at,
        exchange_create_time=filled_at,
        execution_notified_at=None,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed is True
    assert "system order" in reason.lower()


def test_system_order_parent_order_id_allows():
    """System order (parent_order_id set, SL/TP) -> allow."""
    now = datetime.now(timezone.utc)
    filled_at = now - timedelta(seconds=RECENT_FILL_WINDOW_SECONDS + 100)
    order = _order(
        trade_signal_id=None,
        parent_order_id="parent-123",
        exchange_update_time=filled_at,
        exchange_create_time=filled_at,
        execution_notified_at=None,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed is True
    assert "system order" in reason.lower()


def test_admin_resync_allows_regardless_of_age():
    """Admin resync -> allow regardless of age (first time)."""
    now = datetime.now(timezone.utc)
    filled_at = now - timedelta(days=7)
    order = _order(
        trade_signal_id=None,
        parent_order_id=None,
        exchange_update_time=filled_at,
        exchange_create_time=filled_at,
        execution_notified_at=None,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=True,
    )
    assert allowed is True
    assert "admin" in reason.lower()


def test_admin_resync_still_dedup_if_already_notified():
    """Admin resync but already notified -> block (dedup)."""
    now = datetime.now(timezone.utc)
    order = _order(
        trade_signal_id=None,
        parent_order_id=None,
        exchange_update_time=now,
        exchange_create_time=now,
        execution_notified_at=now,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=now,
        source="sync_order_history",
        requested_by_admin=True,
    )
    assert allowed is False
    assert "already notified" in reason.lower()


def test_no_timestamp_blocks():
    """Order with no fill timestamp -> block."""
    order = _order(
        trade_signal_id=None,
        parent_order_id=None,
        exchange_update_time=None,
        exchange_create_time=None,
        execution_notified_at=None,
    )
    allowed, reason = should_notify_executed_fill(
        db=MagicMock(),
        order=order,
        now_utc=datetime.now(timezone.utc),
        source="sync_order_history",
        requested_by_admin=False,
    )
    assert allowed is False
    assert "historical" in reason.lower() or "timestamp" in reason.lower()
