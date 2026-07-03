"""Tests for the cap-race dedup at the orchestrator entry choke point.

Real-money incident 2026-07-03: two near-simultaneous DOT_USD SELL signals (~3s apart, inside
``ORDER_CREATION_LOCK_SECONDS``) BOTH placed real orders. PR #114 added the atomic per-(symbol,
side) dedup slot but only inside the ``_create_buy_order`` / ``_create_sell_order`` wrappers. The
LIVE entry path is the orchestrator, which calls ``_place_order_from_signal`` directly (NOT the
wrappers), so the guard was bypassed (prod logs showed dedup_suppressed=0).

The fix moves the SAME atomic slot into ``_place_order_from_signal`` — the single choke point every
orchestrator entry passes through. These tests assert the wrapper's dedup semantics by patching
``_place_order_from_signal_impl`` (the real placement body) so the wrapper's claim/retain/release
logic is exercised in isolation. They mirror the patterns in
``test_signal_monitor_real_path_sltp.py``.
"""
import asyncio
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.services.signal_monitor import SignalMonitorService


def _make_watchlist_item(symbol="DOT_USD", margin=True):
    w = Mock()
    w.symbol = symbol
    w.trade_enabled = True
    w.trade_amount_usd = 100.0
    w.trade_on_margin = margin
    return w


def _make_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.query.return_value.filter.return_value.count.return_value = 0
    return db


def _place(svc, side="SELL", symbol="DOT_USD"):
    return svc._place_order_from_signal(
        db=_make_db(),
        symbol=symbol,
        side=side,
        watchlist_item=_make_watchlist_item(symbol=symbol),
        current_price=6.0,
        source="orchestrator",
    )


class TestOrchestratorEntryDedup:
    def test_two_near_simultaneous_entries_only_one_placed(self):
        # The incident scenario: two orchestrator SELL entries race in together. Exactly one must
        # reach the exchange; the other is suppressed BEFORE placement.
        svc = SignalMonitorService()
        started = {"count": 0}

        async def _slow_impl(*a, **k):
            started["count"] += 1
            await asyncio.sleep(0.05)  # hold the slot while the sibling call races in
            return {"order_id": "first"}

        async def _race():
            with patch.object(svc, "_place_order_from_signal_impl", side_effect=_slow_impl):
                return await asyncio.gather(_place(svc), _place(svc))

        r1, r2 = asyncio.run(_race())
        outcomes = {str(r.get("order_id") or r.get("error")) for r in (r1, r2)}
        assert outcomes == {"first", "DUPLICATE_ORDER_SUPPRESSED"}
        assert started["count"] == 1  # impl body (real placement) ran exactly once

    def test_sequential_within_ttl_is_suppressed(self):
        # The REAL race: two entries 2-4s apart. After a SUCCESSFUL order the slot is retained so
        # its TTL suppresses the 2nd; once the TTL expires a later entry is allowed again.
        svc = SignalMonitorService()

        async def _impl(*a, **k):
            return {"order_id": "ok"}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_impl) as impl:
            r1 = asyncio.run(_place(svc))
            r2 = asyncio.run(_place(svc))  # within TTL -> suppressed before impl runs
            svc.order_creation_locks["DOT_USD:SELL"] -= (svc.ORDER_CREATION_LOCK_SECONDS + 1)
            r3 = asyncio.run(_place(svc))  # slot aged past TTL -> allowed

        assert r1 == {"order_id": "ok"}
        assert r2["error"] == "DUPLICATE_ORDER_SUPPRESSED"
        assert r3 == {"order_id": "ok"}
        assert impl.call_count == 2  # r1 and r3 placed; r2 suppressed before impl

    def test_buy_and_sell_slots_are_independent_on_orchestrator_path(self):
        svc = SignalMonitorService()

        async def _impl(*a, **k):
            return {"order_id": "ok"}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_impl):
            r_sell = asyncio.run(_place(svc, side="SELL"))
            r_buy = asyncio.run(_place(svc, side="BUY"))  # different side -> different slot

        assert r_sell == {"order_id": "ok"}
        assert r_buy == {"order_id": "ok"}

    def test_block_result_releases_slot_and_allows_retry(self):
        # A guard/block (cap, live-trading, invalid qty) returns an "error" dict WITHOUT placing a
        # real order -> the slot must be released so a legitimate later entry is not blocked.
        svc = SignalMonitorService()

        async def _blocked(*a, **k):
            return {"error": "system_core_max_open_trades", "blocked": True}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_blocked):
            r1 = asyncio.run(_place(svc))
            r2 = asyncio.run(_place(svc))  # slot was released -> this is NOT a duplicate-suppress

        assert r1["error"] == "system_core_max_open_trades"
        assert r2["error"] == "system_core_max_open_trades"
        assert "DOT_USD:SELL" not in svc.order_creation_locks  # released, not retained

    def test_exchange_rejection_releases_slot(self):
        # place_market_order rejection surfaces as an error dict (no order id) -> release.
        svc = SignalMonitorService()

        async def _rejected(*a, **k):
            return {"error": "insufficient_balance", "error_type": "exchange_rejected"}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_rejected):
            asyncio.run(_place(svc))

        assert "DOT_USD:SELL" not in svc.order_creation_locks

    def test_exception_releases_slot_and_propagates(self):
        # A raised exception is a non-placement outcome: release the slot and let it propagate.
        svc = SignalMonitorService()
        calls = {"n": 0}

        async def _impl(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {"order_id": "ok"}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_impl):
            with pytest.raises(RuntimeError):
                asyncio.run(_place(svc))
            # Slot released on error -> the retry proceeds immediately (no TTL wait).
            r2 = asyncio.run(_place(svc))

        assert r2 == {"order_id": "ok"}
        assert calls["n"] == 2

    def test_suppressed_result_is_consistent_shape(self):
        svc = SignalMonitorService()
        assert svc._try_claim_order_slot("DOT_USD", "SELL") is True  # first entry in flight

        async def _impl(*a, **k):
            return {"order_id": "should-not-run"}

        with patch.object(svc, "_place_order_from_signal_impl", side_effect=_impl) as impl:
            result = asyncio.run(_place(svc))

        impl.assert_not_called()
        assert result["error"] == "DUPLICATE_ORDER_SUPPRESSED"
        assert result["error_type"] == "duplicate_order_suppressed"
