"""Health liveness stays responsive while heavy background sync runs."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.utils.background_executor import (
    heavy_background_work_allowed,
    run_in_background,
    start_event_loop_lag_monitor,
)


def _block_seconds(seconds: float) -> None:
    time.sleep(seconds)


@pytest.mark.asyncio
async def test_ping_fast_while_background_pool_busy():
    """/__ping must answer in <2s even when the background executor is saturated."""
    await start_event_loop_lag_monitor()
    app = create_app()
    client = TestClient(app)

    # Fill the dedicated background pool (default max_workers=4).
    jobs = [run_in_background(_block_seconds, 2.5) for _ in range(4)]
    await asyncio.sleep(0.05)

    started = time.perf_counter()
    response = client.get("/__ping")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert elapsed < 2.0, f"/__ping took {elapsed:.2f}s with saturated background pool"

    await asyncio.gather(*jobs, return_exceptions=True)


@pytest.mark.asyncio
async def test_api_health_while_background_pool_busy():
    await start_event_loop_lag_monitor()
    app = create_app()
    client = TestClient(app)

    jobs = [run_in_background(_block_seconds, 2.5) for _ in range(4)]
    await asyncio.sleep(0.05)

    started = time.perf_counter()
    response = client.get("/api/health")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert response.json().get("status") == "ok"
    assert elapsed < 2.0

    await asyncio.gather(*jobs, return_exceptions=True)


@pytest.mark.asyncio
async def test_heavy_background_work_blocked_when_loop_lags():
    await start_event_loop_lag_monitor()

    with patch(
        "app.utils.background_executor._last_loop_lag_sec",
        2.0,
    ):
        assert heavy_background_work_allowed() is False