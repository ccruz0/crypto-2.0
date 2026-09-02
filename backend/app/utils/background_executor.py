"""Dedicated thread pool for heavy background work.

Starlette/FastAPI run sync route handlers (``/__ping``, ``/api/health``) on the
default ``anyio`` thread pool. Background jobs that also used that pool
(``asyncio.to_thread`` / ``run_in_executor(None, ...)``) could starve health
probes under load. Heavy sync/rebuild/candle work goes here instead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_WORKERS = int(os.getenv("BACKGROUND_EXECUTOR_MAX_WORKERS", "4"))
_executor: Optional[ThreadPoolExecutor] = None
_last_loop_lag_sec: float = 0.0
_lag_monitor_task: Optional[asyncio.Task] = None

LOOP_LAG_THRESHOLD_SEC = float(os.getenv("EVENT_LOOP_LAG_THRESHOLD_SEC", "1.5"))
_LAG_PROBE_INTERVAL_SEC = float(os.getenv("EVENT_LOOP_LAG_PROBE_INTERVAL_SEC", "0.5"))


def get_background_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=_MAX_WORKERS,
            thread_name_prefix="atp-bg",
        )
        logger.info(
            "Background executor started (max_workers=%s)",
            _MAX_WORKERS,
        )
    return _executor


async def run_in_background(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run blocking work on the dedicated background pool."""
    loop = asyncio.get_running_loop()
    if kwargs:
        return await loop.run_in_executor(
            get_background_executor(),
            lambda: func(*args, **kwargs),
        )
    return await loop.run_in_executor(get_background_executor(), func, *args)


def event_loop_lag_seconds() -> float:
    """Estimated event-loop scheduling lag from the lag monitor."""
    return _last_loop_lag_sec


def heavy_background_work_allowed() -> bool:
    """False when the asyncio loop is falling behind — defer heavy sync."""
    return _last_loop_lag_sec < LOOP_LAG_THRESHOLD_SEC


async def start_event_loop_lag_monitor() -> None:
    """Probe loop responsiveness; used by circuit breakers for heavy sync."""
    global _lag_monitor_task, _last_loop_lag_sec

    if _lag_monitor_task is not None and not _lag_monitor_task.done():
        return

    async def _probe() -> None:
        global _last_loop_lag_sec
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(_LAG_PROBE_INTERVAL_SEC)
            _last_loop_lag_sec = max(
                0.0,
                time.perf_counter() - t0 - _LAG_PROBE_INTERVAL_SEC,
            )

    _lag_monitor_task = asyncio.create_task(_probe())
    logger.info(
        "Event loop lag monitor started (interval=%.2fs threshold=%.2fs)",
        _LAG_PROBE_INTERVAL_SEC,
        LOOP_LAG_THRESHOLD_SEC,
    )


def shutdown_background_executor() -> None:
    """Release background threads on process shutdown (best-effort)."""
    global _executor, _lag_monitor_task
    if _lag_monitor_task is not None and not _lag_monitor_task.done():
        _lag_monitor_task.cancel()
    _lag_monitor_task = None
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
