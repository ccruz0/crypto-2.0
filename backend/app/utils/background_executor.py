"""Dedicated thread pool for heavy background work.

Starlette/FastAPI run sync route handlers (``/__ping``, ``/api/health``) on the
default ``anyio`` thread pool. Background jobs that also used that pool
(``asyncio.to_thread`` / ``run_in_executor(None, ...)``) could starve health
probes under load. Heavy sync/rebuild/candle work goes here instead.

Async health handlers (``async def``) avoid the default pool entirely.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_WORKERS = int(os.getenv("BACKGROUND_EXECUTOR_MAX_WORKERS", "4"))
_executor: Optional[ThreadPoolExecutor] = None
_last_loop_lag_sec: float = 0.0
_lag_monitor_task: Optional[asyncio.Task] = None
_last_lag_warning_at: float = 0.0

LOOP_LAG_THRESHOLD_SEC = float(os.getenv("EVENT_LOOP_LAG_THRESHOLD_SEC", "1.5"))
_LAG_PROBE_INTERVAL_SEC = float(os.getenv("EVENT_LOOP_LAG_PROBE_INTERVAL_SEC", "0.5"))
_LAG_WARNING_INTERVAL_SEC = 10.0

# Named non-reentrant guards for overlapping background jobs.
_overlap_busy: Dict[str, bool] = {}
_overlap_meta_lock: Optional[asyncio.Lock] = None


def _get_overlap_meta_lock() -> asyncio.Lock:
    global _overlap_meta_lock
    if _overlap_meta_lock is None:
        _overlap_meta_lock = asyncio.Lock()
    return _overlap_meta_lock


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


def heavy_sync_mode() -> str:
    """``full`` (default) | ``throttle`` | ``off`` — controls candle/order-history."""
    return (os.getenv("ATP_HEAVY_SYNC_MODE") or "full").strip().lower()


def heavy_sync_candle_allowed(*, guard_busy: bool = False) -> bool:
    """Whether candle sweep may run under the current heavy-sync mode."""
    mode = heavy_sync_mode()
    if mode == "off":
        return False
    if guard_busy:
        return False
    if mode == "throttle":
        if event_loop_lag_seconds() > LOOP_LAG_THRESHOLD_SEC * 0.5:
            return False
    return heavy_background_work_allowed()


def heavy_sync_order_history_allowed(*, guard_busy: bool = False) -> bool:
    """Whether order-history sync may run under the current heavy-sync mode."""
    mode = heavy_sync_mode()
    if mode == "off":
        return False
    if guard_busy:
        return False
    if mode == "throttle":
        if event_loop_lag_seconds() > LOOP_LAG_THRESHOLD_SEC * 0.5:
            return False
    return heavy_background_work_allowed()


def background_executor_stats() -> str:
    """Approximate atp-bg queue depth for observability."""
    ex = _executor
    if ex is None:
        return "executor=not_started"
    qsize = "?"
    work_queue = getattr(ex, "_work_queue", None)
    if work_queue is not None and hasattr(work_queue, "qsize"):
        try:
            qsize = str(work_queue.qsize())
        except Exception:
            qsize = "?"
    active = "?"
    threads = getattr(ex, "_threads", None)
    if threads is not None:
        active = str(len(threads))
    return f"queue={qsize} active_threads={active} max_workers={_MAX_WORKERS}"


@asynccontextmanager
async def overlap_guard(name: str) -> AsyncIterator[bool]:
    """Non-reentrant guard — yields True if acquired, False if already busy."""
    async with _get_overlap_meta_lock():
        if _overlap_busy.get(name):
            logger.warning(
                "OverlapGuard skip — %s already running (%s)",
                name,
                background_executor_stats(),
            )
            yield False
            return
        _overlap_busy[name] = True
    try:
        yield True
    finally:
        async with _get_overlap_meta_lock():
            _overlap_busy[name] = False


def reset_overlap_guards_for_tests() -> None:
    """Clear overlap state between tests."""
    _overlap_busy.clear()


async def start_event_loop_lag_monitor() -> None:
    """Probe loop responsiveness; used by circuit breakers for heavy sync."""
    global _lag_monitor_task, _last_loop_lag_sec, _last_lag_warning_at

    if _lag_monitor_task is not None and not _lag_monitor_task.done():
        return

    async def _probe() -> None:
        global _last_loop_lag_sec, _last_lag_warning_at
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(_LAG_PROBE_INTERVAL_SEC)
            _last_loop_lag_sec = max(
                0.0,
                time.perf_counter() - t0 - _LAG_PROBE_INTERVAL_SEC,
            )
            if _last_loop_lag_sec >= LOOP_LAG_THRESHOLD_SEC:
                now = time.monotonic()
                if now - _last_lag_warning_at >= _LAG_WARNING_INTERVAL_SEC:
                    _last_lag_warning_at = now
                    logger.warning(
                        "Event loop lag elevated: %.2fs (threshold %.2fs) %s",
                        _last_loop_lag_sec,
                        LOOP_LAG_THRESHOLD_SEC,
                        background_executor_stats(),
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
