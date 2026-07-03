"""Tests for the REAL SL/TP wiring and the in-memory cap-race dedup in signal_monitor.

Covers the fix in ``fix/real-path-sltp-and-cap-race``:

PART A — the automatic order paths (``_create_buy_order`` / ``_create_sell_order``) now call
``_create_protection_after_entry_fill(...)`` directly (the working, side-aware mechanism) instead
of publishing an ``OrderFilled`` event that is a no-op in prod. A SELL only creates protection when
it is a SHORT ENTRY (margin, no existing position, shorting enabled); a SELL that closes a long does
NOT create SL/TP.

PART B — a near-simultaneous second order for the same (symbol, side) is suppressed by an atomic
in-memory dedup slot claimed before any cap check.

NOTE: these unit tests assert the wiring/decision only. Real confidence that SL and TP actually
appear on Crypto.com with the correct side requires the manual integration test documented in the PR.
"""
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.signal_monitor import SignalMonitorService


def _make_watchlist_item(symbol="ETH_USDT", margin=True):
    w = Mock()
    w.symbol = symbol
    w.trade_enabled = True
    w.trade_amount_usd = 100.0
    w.trade_on_margin = margin
    return w


def _make_db():
    """DB double whose ExchangeOrder idempotency/recent-order queries look empty."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


def _filled_market_result(order_id):
    return {
        "order_id": order_id,
        "status": "FILLED",
        "cumulative_quantity": "0.05",
        "avg_price": "2000.0",
    }


# ---------------------------------------------------------------------------
# PART A — real SL/TP wiring
# ---------------------------------------------------------------------------


class TestBuyRealPathProtection:
    def test_buy_filled_calls_protection_with_buy_side(self):
        svc = SignalMonitorService()
        db = _make_db()
        w = _make_watchlist_item()

        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor._emit_lifecycle_event"), \
             patch("app.utils.live_trading.get_live_trading_status", return_value=False), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch("app.utils.trading_guardrails.can_place_real_order", return_value=(True, None)), \
             patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=0), \
             patch.object(svc, "_count_total_open_buy_orders", return_value=0), \
             patch.object(svc, "_should_block_open_orders", return_value=False), \
             patch.object(svc, "_create_protection_after_entry_fill", return_value={"status": "ok"}) as mock_protect:
            mock_tc.place_market_order.return_value = _filled_market_result("buy-1")
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})

            asyncio.run(svc._create_buy_order(db, w, 2000.0, 0.0, 0.0))

        mock_protect.assert_called_once()
        assert mock_protect.call_args.kwargs["entry_side"] == "BUY"
        assert mock_protect.call_args.kwargs["order_id"] == "buy-1"


class TestSellRealPathProtection:
    def _run_sell(self, svc, db, w, *, positions, shorting):
        with patch("app.services.signal_monitor.trade_client") as mock_tc, \
             patch("app.services.signal_monitor._emit_lifecycle_event"), \
             patch("app.utils.live_trading.get_live_trading_status", return_value=False), \
             patch("app.services.live_trading_gate.assert_exchange_mutation_allowed"), \
             patch("app.services.order_position_service.count_open_positions_for_symbol", return_value=positions), \
             patch("app.services.risk_guard.shorting_enabled", return_value=shorting), \
             patch.object(svc, "_create_protection_after_entry_fill", return_value={"status": "ok"}) as mock_protect:
            mock_tc.place_market_order.return_value = _filled_market_result("sell-1")
            mock_tc.normalize_quantity_safe_with_fallback.return_value = ("0.05", {})
            asyncio.run(svc._create_sell_order(db, w, 2000.0, 0.0, 0.0))
        return mock_protect

    def test_sell_short_entry_calls_protection_with_sell_side(self):
        svc = SignalMonitorService()
        mock_protect = self._run_sell(
            svc, _make_db(), _make_watchlist_item(margin=True), positions=0, shorting=True
        )
        mock_protect.assert_called_once()
        assert mock_protect.call_args.kwargs["entry_side"] == "SELL"
        assert mock_protect.call_args.kwargs["order_id"] == "sell-1"

    def test_sell_long_close_does_not_create_protection(self):
        # Position already exists -> this SELL closes a long -> NO SL/TP.
        svc = SignalMonitorService()
        mock_protect = self._run_sell(
            svc, _make_db(), _make_watchlist_item(margin=True), positions=1, shorting=True
        )
        mock_protect.assert_not_called()

    def test_sell_margin_but_shorting_disabled_does_not_create_protection(self):
        # No position, margin on, but shorting is globally disabled -> not a short entry.
        svc = SignalMonitorService()
        mock_protect = self._run_sell(
            svc, _make_db(), _make_watchlist_item(margin=True), positions=0, shorting=False
        )
        mock_protect.assert_not_called()


# ---------------------------------------------------------------------------
# PART B — in-memory (symbol, side) cap-race dedup
# ---------------------------------------------------------------------------


class TestOrderDedupSlot:
    def test_second_order_suppressed_when_slot_held(self):
        svc = SignalMonitorService()
        # Simulate a first BUY already in flight for this (symbol, side).
        assert svc._try_claim_order_slot("ETH_USDT", "BUY") is True

        with patch.object(svc, "_create_buy_order_impl") as impl:
            result = asyncio.run(svc._create_buy_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0))

        impl.assert_not_called()
        assert result["error"] == "DUPLICATE_ORDER_SUPPRESSED"

    def test_slot_released_allows_next_order(self):
        svc = SignalMonitorService()

        async def _impl(*a, **k):
            return {"order_id": "ok"}

        with patch.object(svc, "_create_buy_order_impl", side_effect=_impl):
            r1 = asyncio.run(svc._create_buy_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0))
            # Slot released in finally -> a later order proceeds.
            r2 = asyncio.run(svc._create_buy_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0))

        assert r1 == {"order_id": "ok"}
        assert r2 == {"order_id": "ok"}

    def test_two_near_simultaneous_orders_only_one_runs(self):
        svc = SignalMonitorService()
        started = {"count": 0}

        async def _slow_impl(*a, **k):
            started["count"] += 1
            await asyncio.sleep(0.05)  # hold the slot while the sibling call races in
            return {"order_id": "first"}

        async def _race():
            with patch.object(svc, "_create_buy_order_impl", side_effect=_slow_impl):
                return await asyncio.gather(
                    svc._create_buy_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0),
                    svc._create_buy_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0),
                )

        r1, r2 = asyncio.run(_race())
        outcomes = {str(r.get("order_id") or r.get("error")) for r in (r1, r2)}
        assert outcomes == {"first", "DUPLICATE_ORDER_SUPPRESSED"}
        assert started["count"] == 1  # impl body ran exactly once

    def test_buy_and_sell_slots_are_independent(self):
        svc = SignalMonitorService()
        assert svc._try_claim_order_slot("ETH_USDT", "BUY") is True
        # Different side -> different key -> not blocked.
        assert svc._try_claim_order_slot("ETH_USDT", "SELL") is True
        # Same (symbol, side) -> blocked.
        assert svc._try_claim_order_slot("ETH_USDT", "BUY") is False

    def test_stale_slot_is_reclaimed_after_ttl(self):
        svc = SignalMonitorService()
        assert svc._try_claim_order_slot("ETH_USDT", "BUY") is True
        # Age the claim beyond the TTL.
        svc.order_creation_locks["ETH_USDT:BUY"] -= (svc.ORDER_CREATION_LOCK_SECONDS + 1)
        assert svc._try_claim_order_slot("ETH_USDT", "BUY") is True

    def test_sell_wrapper_suppresses_duplicate(self):
        svc = SignalMonitorService()
        assert svc._try_claim_order_slot("ETH_USDT", "SELL") is True
        with patch.object(svc, "_create_sell_order_impl") as impl:
            result = asyncio.run(svc._create_sell_order(_make_db(), _make_watchlist_item(), 2000.0, 0.0, 0.0))
        impl.assert_not_called()
        assert result["error"] == "DUPLICATE_ORDER_SUPPRESSED"
