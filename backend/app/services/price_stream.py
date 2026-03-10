"""
Real-time price stream for dashboard WebSocket.

Maintains an in-memory cache of symbol -> price from Crypto.com get-tickers,
and broadcasts updates to all connected WebSocket clients at a configurable interval.
Uses the existing portfolio_cache.get_crypto_prices() so egress and logic stay centralized.
"""

import asyncio
import logging
import os
import time
from typing import Dict, Set, Any

logger = logging.getLogger(__name__)

# Default interval (seconds) between price fetches and broadcasts
PRICE_STREAM_INTERVAL_S = int(os.getenv("PRICE_STREAM_INTERVAL_S", "10"))
# Set to "false" to disable the price stream (no background task, WS still accepts connections but may have stale/empty snapshot)
ENABLE_PRICE_STREAM = os.getenv("ENABLE_WS_PRICES", "true").lower() in ("true", "1", "yes")


# In-memory cache: symbol -> price (e.g. {"BTC": 45000.0, "ETH": 2400.0})
_cache: Dict[str, float] = {}
_cache_ts: float = 0
_subscribers: Set[Any] = set()
_lock = asyncio.Lock()
_task: asyncio.Task | None = None


def get_snapshot() -> Dict[str, Any]:
    """Return current cache as a JSON-serializable snapshot for new WS clients."""
    return {
        "prices": dict(_cache),
        "ts": _cache_ts,
        "source": "crypto_com",
    }


async def _fetch_prices() -> Dict[str, float]:
    """Fetch prices from Crypto.com (run in thread to avoid blocking)."""
    from app.services.portfolio_cache import get_crypto_prices
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_crypto_prices)


async def _broadcast(payload: Dict[str, Any]) -> None:
    """Send payload to all connected WebSocket clients; remove dead connections."""
    global _subscribers
    dead = set()
    async with _lock:
        for ws in _subscribers:
            try:
                await ws.send_json(payload)
            except Exception as e:
                logger.debug("Price stream: client send failed, dropping: %s", e)
                dead.add(ws)
        for ws in dead:
            _subscribers.discard(ws)


async def _run_loop() -> None:
    """Background task: fetch prices periodically and broadcast to subscribers."""
    global _cache, _cache_ts
    while True:
        try:
            prices = await _fetch_prices()
            if prices:
                _cache.clear()
                _cache.update(prices)
                _cache_ts = time.time()
                snapshot = get_snapshot()
                await _broadcast(snapshot)
                logger.debug("Price stream: updated %d symbols", len(prices))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Price stream fetch failed: %s", e)
        await asyncio.sleep(PRICE_STREAM_INTERVAL_S)


def start_price_stream() -> None:
    """Start the background price-fetch loop if enabled and not already running."""
    global _task
    if not ENABLE_PRICE_STREAM:
        logger.info("Price stream disabled (ENABLE_WS_PRICES=false)")
        return
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_run_loop())
    logger.info("Price stream started (interval=%ss)", PRICE_STREAM_INTERVAL_S)


def stop_price_stream() -> None:
    """Cancel the background task."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
        logger.info("Price stream stopped")


async def subscribe(ws: Any) -> None:
    """Register a WebSocket for price updates and send current snapshot."""
    async with _lock:
        _subscribers.add(ws)
    snapshot = get_snapshot()
    try:
        await ws.send_json(snapshot)
    except Exception as e:
        logger.debug("Price stream: initial send failed: %s", e)
        async with _lock:
            _subscribers.discard(ws)


async def unsubscribe(ws: Any) -> None:
    """Remove a WebSocket from subscribers."""
    async with _lock:
        _subscribers.discard(ws)
