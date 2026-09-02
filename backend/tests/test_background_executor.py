"""Tests for dedicated background executor and event-loop lag monitor."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.utils.background_executor import (
    heavy_background_work_allowed,
    run_in_background,
    start_event_loop_lag_monitor,
)


def _add(a: int, b: int) -> int:
    return a + b


@pytest.mark.asyncio
async def test_run_in_background_executes_sync_function():
    result = await run_in_background(_add, 2, 3)
    assert result == 5


@pytest.mark.asyncio
async def test_lag_monitor_allows_work_when_healthy():
    await start_event_loop_lag_monitor()
    await asyncio.sleep(0.05)
    assert heavy_background_work_allowed() is True


@pytest.mark.asyncio
async def test_lag_monitor_detects_degraded_loop():
    await start_event_loop_lag_monitor()
    with patch("app.utils.background_executor._last_loop_lag_sec", 3.0):
        assert heavy_background_work_allowed() is False
