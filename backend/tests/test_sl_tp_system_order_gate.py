"""Tests for SL/TP auto-creation gate and system-order detection in exchange_sync."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.exchange_order import OrderStatusEnum
from app.services.exchange_sync import (
    ensure_system_order_attribution,
    has_complete_sl_tp_protection,
    is_system_created_order,
    link_system_trade_signal_to_order,
    should_auto_create_sl_tp_on_sync,
    sl_tp_creation_result_ok,
)


def _order(exchange_order_id="123", trade_signal_id=None, parent_order_id=None, symbol="DOGE_USD"):
    o = MagicMock()
    o.exchange_order_id = exchange_order_id
    o.trade_signal_id = trade_signal_id
    o.parent_order_id = parent_order_id
    o.symbol = symbol
    return o


def test_is_system_created_order_via_trade_signal_id():
    db = MagicMock()
    order = _order(trade_signal_id=42)
    assert is_system_created_order(db, order) is True


def test_ensure_attribution_links_trade_signal_row():
    db = MagicMock()
    order = _order(trade_signal_id=None)
    signal = MagicMock()
    signal.id = 99
    db.query.return_value.filter.return_value.first.return_value = signal
    ts_id, is_system, source = ensure_system_order_attribution(db, order)
    assert is_system is True
    assert ts_id == 99
    assert order.trade_signal_id == 99
    assert source in ("trade_signal_id", "trade_signal_relink")


def test_ensure_attribution_via_order_intent_without_trade_signal():
    """Bot OrderIntent must attribute even when TradeSignal link raced."""
    db = MagicMock()
    order = _order(trade_signal_id=None, exchange_order_id="5755600492526823562", symbol="APT_USD")
    intent = MagicMock()
    intent.id = 7
    # link TradeSignal → None; relink TradeSignal → None; OrderIntent → intent
    db.query.return_value.filter.return_value.first.side_effect = [None, None]
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = intent
    ts_id, is_system, source = ensure_system_order_attribution(db, order)
    assert is_system is True
    assert ts_id is None
    assert source == "order_intent"


def test_is_system_created_order_via_order_intent():
    db = MagicMock()
    order = _order(trade_signal_id=None)
    intent = MagicMock()
    intent.id = 42
    db.query.return_value.filter.return_value.first.side_effect = [None, None]
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = intent
    assert is_system_created_order(db, order) is True


def test_two_doge_orders_both_detected_as_system():
    """Each DOGE order id must resolve independently (not symbol-overwritten)."""
    db = MagicMock()
    order_a = _order(exchange_order_id="5755600491448633454", symbol="DOGE_USD")
    order_b = _order(exchange_order_id="5755600491449038884", symbol="DOGE_USD")

    sig_a = MagicMock(); sig_a.id = 11
    sig_b = MagicMock(); sig_b.id = 12
    db.query.return_value.filter.return_value.first.return_value = sig_a
    assert is_system_created_order(db, order_a) is True

    order_b.trade_signal_id = None
    db.query.return_value.filter.return_value.first.return_value = sig_b
    assert is_system_created_order(db, order_b) is True


def test_should_create_for_system_order_without_timestamp():
    db = MagicMock()
    order = _order(trade_signal_id=7)
    with patch(
        "app.services.sl_tp_protection.is_sltp_healing_enabled",
        return_value=True,
    ), patch(
        "app.services.exchange_sync.has_complete_sl_tp_protection",
        return_value=False,
    ), patch(
        "app.services.exchange_sync.should_skip_rejected_tp_backfill",
        return_value=False,
    ):
        allowed, reason = should_auto_create_sl_tp_on_sync(
            db, order, order_filled_time=None, now_utc=datetime.now(timezone.utc)
        )
    assert allowed is True
    assert reason == "system_order_needs_protection"


def test_should_skip_wallet_side_mismatch_for_system_order():
    db = MagicMock()
    order = _order(trade_signal_id=7)
    order.side = "SELL"
    with patch(
        "app.services.sl_tp_protection.is_sltp_healing_enabled",
        return_value=True,
    ), patch(
        "app.services.exchange_sync.has_complete_sl_tp_protection",
        return_value=False,
    ), patch(
        "app.services.exchange_sync.should_skip_rejected_tp_backfill",
        return_value=False,
    ):
        allowed, reason = should_auto_create_sl_tp_on_sync(
            db,
            order,
            order_filled_time=None,
            now_utc=datetime.now(timezone.utc),
            wallet_balance=1.89,
            entry_side="SELL",
        )
    assert allowed is False
    assert reason.startswith("wallet_side_mismatch")


def test_should_skip_rejected_tp_terminal():
    db = MagicMock()
    order = _order(trade_signal_id=7)
    with patch(
        "app.services.sl_tp_protection.is_sltp_healing_enabled",
        return_value=True,
    ), patch(
        "app.services.exchange_sync.has_complete_sl_tp_protection",
        return_value=False,
    ), patch(
        "app.services.exchange_sync.should_skip_rejected_tp_backfill",
        return_value=True,
    ):
        allowed, reason = should_auto_create_sl_tp_on_sync(
            db, order, order_filled_time=None, now_utc=datetime.now(timezone.utc)
        )
    assert allowed is False
    assert reason == "tp_rejected_terminal"


def test_should_skip_external_old_fill():
    db = MagicMock()
    order = _order()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    now = datetime.now(timezone.utc)
    filled = now - timedelta(hours=5)
    with patch(
        "app.services.sl_tp_protection.is_sltp_healing_enabled",
        return_value=True,
    ), patch(
        "app.services.exchange_sync.has_complete_sl_tp_protection",
        return_value=False,
    ), patch(
        "app.services.exchange_sync.should_skip_rejected_tp_backfill",
        return_value=False,
    ):
        allowed, reason = should_auto_create_sl_tp_on_sync(db, order, filled, now)
    assert allowed is False
    assert reason.startswith("external_order_old_fill")


def test_link_system_trade_signal_sets_id():
    db = MagicMock()
    order = _order()
    signal = MagicMock()
    signal.id = 55
    db.query.return_value.filter.return_value.first.return_value = signal
    assert link_system_trade_signal_to_order(db, order) is True
    assert order.trade_signal_id == 55


def test_sl_tp_creation_result_ok_both_legs():
    result = {
        "sl_result": {"order_id": "sl1"},
        "tp_result": {"order_id": "tp1"},
    }
    assert sl_tp_creation_result_ok(result) is True


def test_sl_tp_creation_result_ok_missing_sl():
    result = {
        "sl_result": {"error": "failed"},
        "tp_result": {"order_id": "tp1"},
    }
    assert sl_tp_creation_result_ok(result) is False


def test_has_complete_sl_tp_protection_both_roles():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        ("STOP_LOSS",),
        ("TAKE_PROFIT",),
    ]
    assert has_complete_sl_tp_protection(db, "parent123") is True
