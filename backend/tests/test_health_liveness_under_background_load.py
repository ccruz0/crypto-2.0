"""Regression: __ping and /api/health stay fast while background executor is saturated."""

from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core.background_executor import (
    OverlapGuard,
    get_background_executor,
    guard_stats,
    reset_background_executor_for_tests,
    run_background_blocking,
)


@pytest.fixture(autouse=True)
def _reset_executor():
    reset_background_executor_for_tests()
    yield
    reset_background_executor_for_tests()


def _hold_executor_workers(duration_sec: float = 30.0) -> tuple[list, threading.Event]:
    """Fill the background executor; return futures and a release event."""
    executor = get_background_executor()
    max_workers = int(os.getenv("BACKGROUND_EXECUTOR_MAX_WORKERS", "2"))
    release = threading.Event()
    started = threading.Event()
    started_count = {"n": 0}
    lock = threading.Lock()

    def slow_job():
        with lock:
            started_count["n"] += 1
            if started_count["n"] >= max_workers:
                started.set()
        release.wait(timeout=duration_sec)

    futures = [executor.submit(slow_job) for _ in range(max_workers)]
    assert started.wait(timeout=5.0), "background executor workers did not start in time"
    return futures, release


def test_liveness_endpoints_while_background_executor_busy(monkeypatch):
    monkeypatch.setenv("DEBUG_DISABLE_STARTUP_EVENT", "true")
    monkeypatch.setattr("app.factory.DEBUG_DISABLE_STARTUP_EVENT", True)

    from app.factory import create_app

    app = create_app(role="legacy")
    client = TestClient(app)

    futures, release = _hold_executor_workers()
    try:
        t0 = time.monotonic()
        ping = client.get("/__ping")
        health = client.get("/api/health")
        elapsed = time.monotonic() - t0

        assert ping.status_code == 200
        assert ping.json().get("ok") is True
        assert health.status_code == 200
        assert health.json().get("status") == "ok"
        assert elapsed < 1.0, f"liveness took {elapsed:.2f}s with saturated background pool"
    finally:
        release.set()
        for fut in futures:
            fut.result(timeout=5.0)


@pytest.mark.asyncio
async def test_overlap_guard_skips_when_busy():
    guard = OverlapGuard("test.guard")
    entered = threading.Event()
    release = threading.Event()

    def slow():
        entered.set()
        release.wait(timeout=10)

    first = asyncio.create_task(guard.run_if_idle(slow, timeout=15))
    for _ in range(100):
        await asyncio.sleep(0.05)
        if entered.is_set():
            break
    else:
        pytest.fail("slow job did not start on background executor")

    skipped = await guard.run_if_idle(slow, timeout=15)
    assert skipped is False
    release.set()
    assert (await first) is True
    stats = guard_stats().get("test.guard", {})
    assert stats.get("skipped", 0) >= 1
    assert stats.get("runs", 0) >= 1


def test_exchange_sync_skips_overlapping_open_orders_cycle(monkeypatch):
    service = __import__(
        "app.services.exchange_sync", fromlist=["ExchangeSyncService"]
    ).ExchangeSyncService()

    def slow_open(db):
        import time

        time.sleep(0.4)

    monkeypatch.setattr(service, "_run_open_orders_sync_sync", slow_open)

    async def run():
        first = asyncio.create_task(service.run_open_orders_sync())
        await asyncio.sleep(0.05)
        skipped = await service.run_open_orders_sync()
        await first
        return skipped

    assert asyncio.run(run()) is False
