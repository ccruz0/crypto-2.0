"""Unit tests for dedicated background executor helpers."""

from __future__ import annotations

import asyncio

import pytest

from app.core.background_executor import (
    OverlapGuard,
    guard_stats,
    reset_background_executor_for_tests,
    run_background_blocking,
)


@pytest.fixture(autouse=True)
def _reset_executor():
    reset_background_executor_for_tests()
    yield
    reset_background_executor_for_tests()


@pytest.mark.asyncio
async def test_run_background_blocking_returns_value():
    def add(a: int, b: int) -> int:
        return a + b

    assert await run_background_blocking(add, 2, 3) == 5


@pytest.mark.asyncio
async def test_run_background_blocking_timeout():
    def slow():
        import time

        time.sleep(2)

    with pytest.raises(asyncio.TimeoutError):
        await run_background_blocking(slow, timeout=0.2)


@pytest.mark.asyncio
async def test_overlap_guard_records_stats():
    guard = OverlapGuard("unit.guard")

    def noop():
        return None

    assert await guard.run_if_idle(noop) is True
    assert await guard.run_if_idle(noop) is True
    stats = guard_stats()["unit.guard"]
    assert stats["runs"] == 2
    assert stats["skipped"] == 0
