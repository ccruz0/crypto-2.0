"""Fill-time SL/TP completeness (healing OFF): both legs, retries, no false already_protected."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.signal_monitor import SignalMonitorService


def _make_db(existing_protection=None):
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = list(existing_protection or [])
    return db


def _filled_placement(order_id="entry-1"):
    return {
        "order_id": order_id,
        "status": "FILLED",
        "cumulative_quantity": "0.05",
        "avg_price": "2000.0",
    }


def _sltp_ok():
    return {
        "sl_result": {"order_id": "sl-1", "error": None},
        "tp_result": {"order_id": "tp-1", "error": None},
    }


def _sltp_sl_only():
    return {
        "sl_result": {"order_id": "sl-1", "error": None},
        "tp_result": {"order_id": None, "error": "INSUFFICIENT_ACC_BALANCE"},
    }


def _prot(role, oid):
    o = MagicMock()
    o.order_role = role
    o.exchange_order_id = oid
    return o


class TestProtectionCompletePredicates:
    def test_complete_requires_both_legs(self):
        assert SignalMonitorService._protection_confirms_complete(_sltp_ok()) is True
        assert SignalMonitorService._protection_confirms_complete(_sltp_sl_only()) is False
        assert SignalMonitorService._protection_confirms_take_profit(_sltp_sl_only()) is False
        assert SignalMonitorService._protection_confirms_stop_loss(_sltp_sl_only()) is True

    def test_already_protected_without_legs_still_confirms_sl_legacy(self):
        assert SignalMonitorService._protection_confirms_stop_loss(
            {"status": "already_protected", "order_id": "x"}
        ) is True


class TestPartialIdempotencyDoesNotSkip:
    def test_sl_only_existing_continues_create(self):
        svc = SignalMonitorService()
        db = _make_db(existing_protection=[_prot("STOP_LOSS", "sl-existing")])
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync, \
             patch.object(svc, "_flatten_unprotected_entry") as mock_flat, \
             patch("app.services.signal_monitor.time.sleep"):
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_sync._create_sl_tp_for_filled_order.return_value = _sltp_ok()
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="ETH_USDT",
                entry_side="BUY",
                order_id="entry-partial",
                placement_result=_filled_placement("entry-partial"),
                estimated_price=2000.0,
                source="test",
            )
        mock_sync._create_sl_tp_for_filled_order.assert_called()
        mock_flat.assert_not_called()
        assert result["tp_result"]["order_id"] == "tp-1"

    def test_both_existing_skips_create(self):
        svc = SignalMonitorService()
        db = _make_db(
            existing_protection=[
                _prot("STOP_LOSS", "sl-existing"),
                _prot("TAKE_PROFIT", "tp-existing"),
            ]
        )
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync:
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="ETH_USDT",
                entry_side="BUY",
                order_id="entry-full",
                placement_result=_filled_placement("entry-full"),
                estimated_price=2000.0,
                source="test",
            )
        mock_sync._create_sl_tp_for_filled_order.assert_not_called()
        assert result["status"] == "already_protected"


class TestCreateRetriesAndTpGap:
    def test_transient_failure_then_success_retries(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync, \
             patch.object(svc, "_flatten_unprotected_entry") as mock_flat, \
             patch("app.services.signal_monitor.time.sleep"), \
             patch("app.services.signal_monitor.SLTP_CREATE_MAX_ATTEMPTS", 3), \
             patch("app.services.signal_monitor.SLTP_CREATE_RETRY_DELAY_SECONDS", 0):
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_sync._create_sl_tp_for_filled_order.side_effect = [
                RuntimeError("transient"),
                _sltp_ok(),
            ]
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="BTC_USD",
                entry_side="BUY",
                order_id="entry-retry",
                placement_result=_filled_placement("entry-retry"),
                estimated_price=2000.0,
                source="test",
            )
        assert mock_sync._create_sl_tp_for_filled_order.call_count == 2
        mock_flat.assert_not_called()
        assert result["sl_result"]["order_id"] == "sl-1"

    def test_sl_only_retries_then_does_not_flatten(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync, \
             patch.object(svc, "_flatten_unprotected_entry") as mock_flat, \
             patch("app.services.signal_monitor.time.sleep"), \
             patch("app.services.signal_monitor.SLTP_CREATE_MAX_ATTEMPTS", 3), \
             patch("app.services.signal_monitor.SLTP_CREATE_RETRY_DELAY_SECONDS", 0), \
             patch.object(svc, "_telegram_send_enabled", return_value=False):
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_sync._create_sl_tp_for_filled_order.return_value = _sltp_sl_only()
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="DOT_USD",
                entry_side="BUY",
                order_id="entry-tp-miss",
                placement_result=_filled_placement("entry-tp-miss"),
                estimated_price=2000.0,
                source="test",
            )
        assert mock_sync._create_sl_tp_for_filled_order.call_count == 3
        mock_flat.assert_not_called()
        assert result["sl_result"]["order_id"] == "sl-1"
        assert not result["tp_result"].get("order_id")


class TestExtendedFillPoll:
    def test_extended_poll_after_initial_miss(self):
        svc = SignalMonitorService()
        db = _make_db()
        filled = {
            "status": "FILLED",
            "cumulative_quantity": Decimal("0.05"),
            "avg_price": 2000.0,
            "filled_price": 2000.0,
        }
        with patch.object(
            svc, "_poll_order_fill_confirmation", side_effect=[None, filled]
        ) as mock_poll, patch(
            "app.services.signal_monitor.trade_client"
        ) as mock_tc, patch(
            "app.services.exchange_sync.exchange_sync_service"
        ) as mock_sync, patch.object(
            svc, "_flatten_unprotected_entry"
        ), patch(
            "app.services.signal_monitor.ORDER_FILL_POLL_EXTENDED_ATTEMPTS", 5
        ):
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_sync._create_sl_tp_for_filled_order.return_value = _sltp_ok()
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="APT_USD",
                entry_side="BUY",
                order_id="entry-slow-fill",
                placement_result={"status": "NEW", "order_id": "entry-slow-fill"},
                estimated_price=2000.0,
                source="test",
            )
        assert mock_poll.call_count == 2
        mock_sync._create_sl_tp_for_filled_order.assert_called_once()
        assert result["sl_result"]["order_id"] == "sl-1"

    def test_fill_unconfirmed_does_not_claim_sync_backup(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch.object(svc, "_poll_order_fill_confirmation", return_value=None), \
             patch("app.services.signal_monitor.ORDER_FILL_POLL_EXTENDED_ATTEMPTS", 2), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync:
            result = svc._create_protection_after_entry_fill(
                db=db,
                symbol="SUI_USD",
                entry_side="BUY",
                order_id="entry-never-fill",
                placement_result={"status": "NEW"},
                estimated_price=1.0,
                source="test",
            )
        mock_sync._create_sl_tp_for_filled_order.assert_not_called()
        assert result["status"] == "fill_unconfirmed"


class TestFillPollUsesOrderDetail:
    def test_poll_prefers_get_order_detail(self):
        svc = SignalMonitorService()
        with patch("app.services.signal_monitor.trade_client") as mock_tc:
            mock_tc.get_order_detail.return_value = {
                "result": {
                    "order_id": "oid-1",
                    "status": "FILLED",
                    "cumulative_quantity": "1.25",
                    "avg_price": "10.5",
                }
            }
            mock_tc.get_open_orders.return_value = {"data": []}
            out = svc._poll_order_fill_confirmation(
                symbol="ALGO_USD",
                order_id="oid-1",
                max_attempts=1,
                poll_interval=0,
            )
        assert out is not None
        assert out["status"] == "FILLED"
        assert out["cumulative_quantity"] == Decimal("1.25")
        mock_tc.get_open_orders.assert_not_called()
