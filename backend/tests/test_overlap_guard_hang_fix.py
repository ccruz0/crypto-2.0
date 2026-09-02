"""Tests for OverlapGuard, async liveness, rebuild cache, and heavy-sync mode."""
from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.expected_take_profit import (
    clear_rebuild_open_lots_cache_for_tests,
    rebuild_open_lots,
)
from app.utils.background_executor import (
    heavy_sync_candle_allowed,
    heavy_sync_mode,
    heavy_sync_order_history_allowed,
    overlap_guard,
    reset_overlap_guards_for_tests,
)


LIVENESS_PATHS = (
    "/__ping",
    "/health",
    "/api/health",
    "/ping_fast",
    "/api/ping_fast",
    "/test",
    "/",
)


def test_liveness_routes_are_async_handlers():
    app = create_app()
    routes_by_path = {
        getattr(route, "path", None): route
        for route in app.routes
        if getattr(route, "path", None) in LIVENESS_PATHS
    }
    for path in LIVENESS_PATHS:
        route = routes_by_path[path]
        assert route is not None, f"missing route {path}"
        assert inspect.iscoroutinefunction(route.endpoint), f"{path} must be async def"


@pytest.mark.parametrize("path,expected_key", [
    ("/__ping", "ok"),
    ("/health", "status"),
    ("/api/health", "status"),
    ("/ping_fast", "status"),
    ("/api/ping_fast", "status"),
])
def test_async_liveness_endpoints_return_200(path, expected_key):
    app = create_app()
    client = TestClient(app)
    response = client.get(path)
    assert response.status_code == 200
    assert expected_key in response.json()


@pytest.mark.asyncio
async def test_overlap_guard_skips_when_busy():
    reset_overlap_guards_for_tests()
    entered: list[str] = []

    async def hold_first():
        async with overlap_guard("exchange_sync_background") as acquired:
            assert acquired is True
            entered.append("first")
            await asyncio.sleep(0.25)

    async def try_second():
        await asyncio.sleep(0.05)
        async with overlap_guard("exchange_sync_background") as acquired:
            if acquired:
                entered.append("second")

    await asyncio.gather(hold_first(), try_second())
    assert entered == ["first"]


@pytest.mark.asyncio
async def test_overlap_guard_allows_after_release():
    reset_overlap_guards_for_tests()
    async with overlap_guard("candle_sweep") as acquired:
        assert acquired is True
    async with overlap_guard("candle_sweep") as acquired:
        assert acquired is True


def test_rebuild_open_lots_cache_collapses_repeated_calls(monkeypatch):
    monkeypatch.setenv("REBUILD_OPEN_LOTS_CACHE_TTL_SEC", "2.0")
    clear_rebuild_open_lots_cache_for_tests()
    db = MagicMock()
    calls = {"count": 0}

    def _fake_uncached(_db, symbol):
        calls["count"] += 1
        return []

    with patch(
        "app.services.expected_take_profit._rebuild_open_lots_uncached",
        side_effect=_fake_uncached,
    ):
        rebuild_open_lots(db, "BTC_USD")
        rebuild_open_lots(db, "BTC_USD")
        rebuild_open_lots(db, "ETH_USD")

    assert calls["count"] == 2


def test_rebuild_open_lots_cache_expires(monkeypatch):
    monkeypatch.setenv("REBUILD_OPEN_LOTS_CACHE_TTL_SEC", "0.05")
    clear_rebuild_open_lots_cache_for_tests()
    db = MagicMock()
    calls = {"count": 0}

    def _fake_uncached(_db, symbol):
        calls["count"] += 1
        return []

    with patch(
        "app.services.expected_take_profit._rebuild_open_lots_uncached",
        side_effect=_fake_uncached,
    ):
        rebuild_open_lots(db, "BTC_USD")
        time.sleep(0.06)
        rebuild_open_lots(db, "BTC_USD")

    assert calls["count"] == 2


def test_heavy_sync_mode_off_skips_candle_and_order_history(monkeypatch):
    monkeypatch.setenv("ATP_HEAVY_SYNC_MODE", "off")
    assert heavy_sync_mode() == "off"
    assert heavy_sync_candle_allowed() is False
    assert heavy_sync_order_history_allowed() is False


def test_heavy_sync_mode_throttle_blocks_at_half_threshold(monkeypatch):
    monkeypatch.setenv("ATP_HEAVY_SYNC_MODE", "throttle")
    with patch("app.utils.background_executor._last_loop_lag_sec", 1.0):
        assert heavy_sync_candle_allowed() is False
        assert heavy_sync_order_history_allowed() is False


@pytest.mark.asyncio
async def test_run_background_sync_skips_order_history_when_mode_off(monkeypatch):
    from app.services.exchange_sync import ExchangeSyncService

    monkeypatch.setenv("ATP_HEAVY_SYNC_MODE", "off")
    service = ExchangeSyncService()
    db = MagicMock()

    with patch.object(service, "sync_balances") as mock_balances, patch.object(
        service, "sync_order_history"
    ) as mock_history, patch(
        "app.services.exchange_sync.SessionLocal", return_value=db
    ):
        await service.run_background_sync()

    mock_balances.assert_called_once()
    mock_history.assert_not_called()
