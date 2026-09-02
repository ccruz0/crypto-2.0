"""Dedicated thread pool for exchange/DB-heavy background work.

Sync HTTP handlers (__ping, /api/health) and ``asyncio.to_thread`` share the
default executor. Long-running exchange_sync / candle_recorder / margin_recorder
work must use this pool instead so liveness endpoints stay responsive.

Operator evidence: ``guard_stats()`` exposes skip/run counters for 24–48h audits.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_WORKERS = int(os.getenv("BACKGROUND_EXECUTOR_MAX_WORKERS", "2"))
_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
_executor_lock = threading.Lock()

# Per-guard counters for post-deploy evidence (logged on skip / optional scrape).
_guard_stats: Dict[str, Dict[str, int]] = {}
_guard_stats_lock = threading.Lock()


def get_background_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Return the shared background thread pool (lazy singleton)."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_MAX_WORKERS,
                    thread_name_prefix="atp-bg",
                )
                logger.info(
                    "background_executor: started max_workers=%d",
                    _MAX_WORKERS,
                )
    return _executor


def reset_background_executor_for_tests() -> None:
    """Shut down and clear the pool — test isolation only."""
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
    with _guard_stats_lock:
        _guard_stats.clear()


def guard_stats() -> Dict[str, Dict[str, int]]:
    """Snapshot overlap-guard counters for ops evidence."""
    with _guard_stats_lock:
        return {name: dict(counters) for name, counters in _guard_stats.items()}


def _record_guard(name: str, field: str) -> None:
    with _guard_stats_lock:
        counters = _guard_stats.setdefault(name, {"runs": 0, "skipped": 0, "timeouts": 0})
        counters[field] = counters.get(field, 0) + 1


async def run_background_blocking(
    fn: Callable[..., T],
    /,
    *args: Any,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> T:
    """Run blocking callable on the dedicated background executor."""
    loop = asyncio.get_running_loop()
    bound = lambda: fn(*args, **kwargs)  # noqa: E731
    coro = loop.run_in_executor(get_background_executor(), bound)
    if timeout is not None:
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "background_executor: timeout after %.1fs fn=%s",
                timeout,
                getattr(fn, "__name__", repr(fn)),
            )
            raise
    return await coro


class OverlapGuard:
    """Circuit-style skip when a previous cycle of the same task is still running."""

    __slots__ = ("name", "_running", "_async_lock")

    def __init__(self, name: str) -> None:
        self.name = name
        self._running = False
        self._async_lock = asyncio.Lock()

    @property
    def is_busy(self) -> bool:
        return self._running

    async def run_if_idle(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """Run blocking ``fn`` off-loop when idle; return False when skipped."""
        async with self._async_lock:
            if self._running:
                _record_guard(self.name, "skipped")
                logger.warning(
                    "background_executor: skip %s (previous cycle still active, stats=%s)",
                    self.name,
                    guard_stats().get(self.name),
                )
                return False
            self._running = True

        _record_guard(self.name, "runs")
        started = time.monotonic()
        try:
            await run_background_blocking(fn, *args, timeout=timeout, **kwargs)
            return True
        except asyncio.TimeoutError:
            _record_guard(self.name, "timeouts")
            logger.warning(
                "background_executor: %s timed out after %.1fs",
                self.name,
                time.monotonic() - started,
            )
            raise
        finally:
            async with self._async_lock:
                self._running = False

    async def run_if_idle_coro(
        self,
        coro_factory: Callable[[], Any],
        /,
    ) -> bool:
        """Run async cycle when idle; return False when skipped."""
        async with self._async_lock:
            if self._running:
                _record_guard(self.name, "skipped")
                logger.warning(
                    "background_executor: skip %s (previous cycle still active, stats=%s)",
                    self.name,
                    guard_stats().get(self.name),
                )
                return False
            self._running = True

        _record_guard(self.name, "runs")
        try:
            await coro_factory()
            return True
        finally:
            async with self._async_lock:
                self._running = False
