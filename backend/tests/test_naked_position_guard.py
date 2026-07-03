"""Tests for the naked-position guard added after the 2026-07-03 DOT_USD incident.

Incident: the bot opened short entries but SL/TP creation failed with Crypto.com error
140001 (EXCHANGE_API_DISABLED — conditional/trigger orders disabled at the account level),
leaving NAKED (unprotected) positions. Crucially, 140001 is RETURNED as an error in the
SL/TP result (not raised), so the pre-existing exception-only auto-close never fired on the
orchestrator path.

Two guarantees are verified here:

1. HARD INVARIANT (backstop) — ``_create_protection_after_entry_fill`` is the single choke
   point every entry path funnels through. If the stop-loss was not actually created
   (returned error OR raised exception), the just-opened position is immediately flattened
   with a market order (SELL to close a long, BUY to cover a short). On a 140001 the broker
   conditional-orders circuit breaker is tripped.

2. PRE-BLOCK — once conditional orders are known-disabled, ``_place_order_from_signal``
   refuses NEW entries that would need protection, up front, before any order is placed.
"""
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.signal_monitor import SignalMonitorService


def _make_db():
    """DB double whose ExchangeOrder idempotency queries look empty (no existing SL/TP)."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


def _filled_placement(order_id="entry-1"):
    """Immediately-filled MARKET result so protection creation skips fill polling."""
    return {
        "order_id": order_id,
        "status": "FILLED",
        "cumulative_quantity": "0.05",
        "avg_price": "2000.0",
    }


def _sltp_140001():
    """SL/TP creation result as returned (NOT raised) on Crypto.com 140001."""
    api_disabled = {
        "order_id": None,
        "error_code": 140001,
        "error": "API_DISABLED: Check API key permissions, account settings, or environment mismatch",
    }
    return {"sl_result": dict(api_disabled), "tp_result": dict(api_disabled)}


def _sltp_ok():
    return {
        "sl_result": {"order_id": "sl-1", "error": None},
        "tp_result": {"order_id": "tp-1", "error": None},
    }


# ---------------------------------------------------------------------------
# Pure predicates
# ---------------------------------------------------------------------------


class TestProtectionPredicates:
    def test_stop_loss_confirmed_on_success(self):
        assert SignalMonitorService._protection_confirms_stop_loss(_sltp_ok()) is True

    def test_stop_loss_not_confirmed_on_140001(self):
        assert SignalMonitorService._protection_confirms_stop_loss(_sltp_140001()) is False

    def test_stop_loss_not_confirmed_on_none(self):
        assert SignalMonitorService._protection_confirms_stop_loss(None) is False

    def test_already_protected_counts_as_confirmed(self):
        assert SignalMonitorService._protection_confirms_stop_loss(
            {"status": "already_protected", "order_id": "x"}
        ) is True

    def test_missing_sl_order_id_is_not_confirmed(self):
        # TP created but SL missing -> still unprotected on the downside.
        result = {"sl_result": {"order_id": None, "error": None}, "tp_result": {"order_id": "tp-1"}}
        assert SignalMonitorService._protection_confirms_stop_loss(result) is False

    def test_conditional_disabled_detection(self):
        assert SignalMonitorService._protection_leg_conditional_disabled(
            {"error_code": 140001}
        ) is True
        assert SignalMonitorService._protection_leg_conditional_disabled(
            {"error": "Error 140001: API_DISABLED"}
        ) is True
        assert SignalMonitorService._protection_leg_conditional_disabled(
            {"error": "API_DISABLED"}
        ) is True
        assert SignalMonitorService._protection_leg_conditional_disabled(
            {"order_id": "sl-1", "error": None}
        ) is False
        assert SignalMonitorService._protection_leg_conditional_disabled(None) is False


# ---------------------------------------------------------------------------
# Choke-point auto-close (the hard invariant)
# ---------------------------------------------------------------------------


class TestFlattenOnProtectionFailure:
    def _run_protection(self, entry_side, creation_result=None, side_effect=None, order_id="entry-1"):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync:
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_tc.place_market_order.return_value = {"order_id": "close-1", "error": None}
            if side_effect is not None:
                mock_sync._create_sl_tp_for_filled_order.side_effect = side_effect
            else:
                mock_sync._create_sl_tp_for_filled_order.return_value = creation_result
            svc._create_protection_after_entry_fill(
                db=db,
                symbol="ETH_USDT",
                entry_side=entry_side,
                order_id=order_id,
                placement_result=_filled_placement(order_id),
                estimated_price=2000.0,
                source="orchestrator",
            )
            return mock_tc

    def test_long_flattened_with_market_sell_on_140001(self):
        mock_tc = self._run_protection("BUY", creation_result=_sltp_140001())
        mock_tc.place_market_order.assert_called_once()
        kwargs = mock_tc.place_market_order.call_args.kwargs
        assert kwargs["side"] == "SELL"
        assert kwargs["dry_run"] is False
        assert float(kwargs["qty"]) == pytest.approx(0.05)
        # 140001 -> breaker tripped so future entries are pre-blocked.
        mock_tc._mark_conditional_orders_unavailable.assert_called_once()

    def test_short_covered_with_market_buy_on_140001(self):
        mock_tc = self._run_protection("SELL", creation_result=_sltp_140001())
        mock_tc.place_market_order.assert_called_once()
        kwargs = mock_tc.place_market_order.call_args.kwargs
        assert kwargs["side"] == "BUY"
        assert kwargs["is_margin"] is True
        assert kwargs["dry_run"] is False
        # BUY market takes notional (quote) ~= qty * price = 0.05 * 2000 = 100.
        assert float(kwargs["notional"]) == pytest.approx(100.0)
        mock_tc._mark_conditional_orders_unavailable.assert_called_once()

    def test_no_flatten_when_stop_loss_created(self):
        mock_tc = self._run_protection("BUY", creation_result=_sltp_ok())
        mock_tc.place_market_order.assert_not_called()
        mock_tc._mark_conditional_orders_unavailable.assert_not_called()

    def test_flatten_when_protection_raises(self):
        # A raised exception (not a 140001 error dict) must ALSO flatten — the choke point
        # catches it so the orchestrator path cannot leak a naked position.
        mock_tc = self._run_protection("BUY", side_effect=RuntimeError("boom"))
        mock_tc.place_market_order.assert_called_once()
        assert mock_tc.place_market_order.call_args.kwargs["side"] == "SELL"
        # Not a 140001 -> breaker is left alone.
        mock_tc._mark_conditional_orders_unavailable.assert_not_called()

    def test_dry_run_entry_is_not_flattened(self):
        mock_tc = self._run_protection("BUY", creation_result=_sltp_140001(), order_id="dry_market_123")
        mock_tc.place_market_order.assert_not_called()

    def test_flatten_failure_does_not_raise(self):
        # If the flatten order itself fails, we alert and return — never raise.
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.services.exchange_sync.exchange_sync_service") as mock_sync:
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            mock_tc.place_market_order.return_value = {"error": "306 INSUFFICIENT_BALANCE"}
            mock_sync._create_sl_tp_for_filled_order.return_value = _sltp_140001()
            # Must not raise despite the close failing.
            svc._create_protection_after_entry_fill(
                db=db,
                symbol="ETH_USDT",
                entry_side="BUY",
                order_id="entry-1",
                placement_result=_filled_placement(),
                estimated_price=2000.0,
                source="orchestrator",
            )
            mock_tc.place_market_order.assert_called_once()


# ---------------------------------------------------------------------------
# Pre-block (refuse new entries when conditional orders are known-disabled)
# ---------------------------------------------------------------------------


def _watchlist_item(symbol="ETH_USDT", margin=False):
    w = Mock()
    w.symbol = symbol
    w.trade_enabled = True
    w.trade_amount_usd = 100.0
    w.trade_on_margin = margin
    return w


class TestPreBlockOnConditionalDisabled:
    def test_buy_entry_blocked_when_breaker_tripped(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.core.trading_invariants_week5.validate_trading_decision", return_value=None), \
             patch("app.services.system_core_trade_guards.check_system_core_buy_allowed", return_value=(True, None)):
            mock_tc._check_conditional_orders_circuit_breaker.return_value = False
            result = asyncio.run(
                svc._place_order_from_signal(db, "ETH_USDT", "BUY", _watchlist_item(), 2000.0)
            )
        assert result["error"] == "CONDITIONAL_ORDERS_DISABLED"
        assert result["blocked"] is True
        mock_tc.place_market_order.assert_not_called()

    def test_short_entry_blocked_when_breaker_tripped(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.core.trading_invariants_week5.validate_trading_decision", return_value=None), \
             patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=0), \
             patch("app.services.risk_guard.shorting_enabled", return_value=True):
            mock_tc._check_conditional_orders_circuit_breaker.return_value = False
            result = asyncio.run(
                svc._place_order_from_signal(db, "ETH_USDT", "SELL", _watchlist_item(margin=True), 2000.0)
            )
        assert result["error"] == "CONDITIONAL_ORDERS_DISABLED"
        mock_tc.place_market_order.assert_not_called()

    def test_entry_proceeds_when_breaker_ok(self):
        svc = SignalMonitorService()
        db = _make_db()
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor.telegram_notifier"), \
             patch("app.core.trading_invariants_week5.validate_trading_decision", return_value=None), \
             patch("app.services.system_core_trade_guards.check_system_core_buy_allowed", return_value=(True, None)), \
             patch("app.utils.live_trading.get_live_trading_status", return_value=False), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch.object(svc, "_create_protection_after_entry_fill", return_value=_sltp_ok()):
            mock_tc._check_conditional_orders_circuit_breaker.return_value = True
            mock_tc.place_market_order.return_value = _filled_placement("entry-1")
            result = asyncio.run(
                svc._place_order_from_signal(db, "ETH_USDT", "BUY", _watchlist_item(), 2000.0)
            )
        mock_tc.place_market_order.assert_called_once()
        assert result.get("order_id") == "entry-1"
