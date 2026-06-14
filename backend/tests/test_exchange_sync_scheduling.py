"""Tests for independent open-orders vs order-history scheduling in exchange sync."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.exchange_sync import ExchangeSyncService
from app.services.open_orders import UnifiedOpenOrder
from app.services.open_orders_cache import clear_open_orders_cache, get_unified_open_orders
from app.services.open_orders_sync_status import reset_open_orders_sync_status_for_tests, sync_status_public_dict


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_open_orders_cache()
    reset_open_orders_sync_status_for_tests()
    yield
    clear_open_orders_cache()
    reset_open_orders_sync_status_for_tests()


def _make_unified_order(order_id: str, *, is_trigger: bool = False) -> UnifiedOpenOrder:
    return UnifiedOpenOrder(
        order_id=order_id,
        symbol="BTC_USDT",
        side="BUY",
        order_type="STOP_LIMIT" if is_trigger else "LIMIT",
        status="ACTIVE",
        quantity=Decimal("0.01"),
        price=Decimal("50000"),
        is_trigger=is_trigger,
    )


def test_run_open_orders_sync_sync_does_not_call_order_history():
    service = ExchangeSyncService()
    db = MagicMock()
    with patch.object(service, "sync_open_orders") as mock_open, patch.object(
        service, "sync_order_history"
    ) as mock_history:
        service._run_open_orders_sync_sync(db)
    mock_open.assert_called_once_with(db)
    mock_history.assert_not_called()


def test_run_background_sync_sync_does_not_call_open_orders():
    service = ExchangeSyncService()
    db = MagicMock()
    with patch.object(service, "sync_balances") as mock_balances, patch.object(
        service, "sync_order_history", return_value=0
    ) as mock_history, patch.object(service, "sync_open_orders") as mock_open:
        service._run_background_sync_sync(db)
    mock_balances.assert_called_once_with(db)
    mock_history.assert_called_once()
    mock_open.assert_not_called()


def test_startup_open_orders_runs_before_background_sync(monkeypatch):
    """Open-orders loop should fire before the delayed background (order-history) loop."""
    service = ExchangeSyncService()
    service.startup_open_orders_delay = 0
    service.background_sync_startup_delay = 2
    service.open_orders_sync_interval = 60
    service.sync_interval = 60
    service.is_running = True

    events: list[tuple[str, float]] = []

    async def mock_open():
        events.append(("open", time.monotonic()))

    async def mock_background():
        events.append(("background", time.monotonic()))

    monkeypatch.setattr(service, "run_open_orders_sync", mock_open)
    monkeypatch.setattr(service, "run_background_sync", mock_background)

    async def run_loops():
        open_task = asyncio.create_task(service._open_orders_loop())
        bg_task = asyncio.create_task(service._background_sync_loop())
        await asyncio.sleep(0.4)
        service.is_running = False
        open_task.cancel()
        bg_task.cancel()
        for task in (open_task, bg_task):
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_loops())

    open_events = [e for e in events if e[0] == "open"]
    bg_events = [e for e in events if e[0] == "background"]
    assert len(open_events) >= 1
    assert len(bg_events) == 0


def test_long_order_history_does_not_block_open_orders_refresh(monkeypatch):
    """A slow order-history scan must not prevent open-orders refresh from completing."""
    service = ExchangeSyncService()
    service.order_history_timeout = 30

    def slow_history(db, page_size=200, max_pages=5, instrument_name=None, prefetched_orders=None):
        time.sleep(1.5)
        return 0

    open_timestamps: list[float] = []

    def fast_open(db):
        open_timestamps.append(time.monotonic())

    monkeypatch.setattr(service, "sync_balances", lambda db: None)
    monkeypatch.setattr(service, "sync_order_history", slow_history)
    monkeypatch.setattr(service, "sync_open_orders", fast_open)

    async def run_concurrent():
        bg_task = asyncio.create_task(service.run_background_sync())
        await asyncio.sleep(0.05)
        await service.run_open_orders_sync()
        await bg_task

    started = time.monotonic()
    asyncio.run(run_concurrent())

    assert len(open_timestamps) == 1
    assert open_timestamps[0] - started < 0.5


def test_sync_open_orders_failure_does_not_stop_order_history(monkeypatch):
    """Open-orders failure is isolated; background order-history sync still runs."""
    service = ExchangeSyncService()
    history_calls: list[str] = []

    def failing_open(db):
        raise RuntimeError("open orders API down")

    def record_history(db, page_size=200, max_pages=5, instrument_name=None, prefetched_orders=None):
        history_calls.append("ran")
        return 0

    monkeypatch.setattr(service, "sync_balances", lambda db: None)
    monkeypatch.setattr(service, "sync_order_history", record_history)

    with patch.object(service, "sync_open_orders", side_effect=failing_open):
        with pytest.raises(RuntimeError):
            service._run_open_orders_sync_sync(MagicMock())

    asyncio.run(service.run_background_sync())
    assert history_calls == ["ran"]


def test_open_orders_cache_updates_with_5_unified_orders():
    """Unified fetch with 5 orders (regular + trigger + advanced) updates cache."""
    clear_open_orders_cache()
    unified = [
        _make_unified_order("reg-1", is_trigger=False),
        _make_unified_order("reg-2", is_trigger=False),
        _make_unified_order("trig-1", is_trigger=True),
        _make_unified_order("trig-2", is_trigger=True),
        _make_unified_order("trig-3", is_trigger=True),
    ]
    fetch_payload = {
        "orders": unified,
        "regular_raw": [{"order_id": "reg-1"}, {"order_id": "reg-2"}],
        "trigger_raw": [{"order_id": "trig-1"}, {"order_id": "trig-2"}, {"order_id": "trig-3"}],
        "advanced_raw": [{"order_id": "adv-1"}],
        "all_raw_orders": [{"order_id": f"raw-{i}"} for i in range(5)],
        "sync_status": "ok",
        "data_verified": True,
        "error_code": None,
        "error_message": None,
        "trigger_orders_status": "ok",
        "trigger_orders_error": None,
        "trigger_orders_error_code": None,
        "regular_count": 2,
        "trigger_count": 3,
    }

    svc = ExchangeSyncService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    db.commit = MagicMock()

    with patch("app.services.unified_open_orders_fetch.fetch_unified_open_orders", return_value=fetch_payload):
        svc.sync_open_orders(db)

    orders, _ = get_unified_open_orders()
    assert len(orders) == 5
    meta = sync_status_public_dict()
    assert meta["data_verified"] is True
    assert meta["sync_status"] == "ok"
