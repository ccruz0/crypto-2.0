"""In-memory cache for unified open orders."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional, Tuple

from app.services.open_orders import UnifiedOpenOrder

_lock = Lock()
_orders: List[UnifiedOpenOrder] = []
_last_updated: Optional[datetime] = None


def store_unified_open_orders(orders: List[UnifiedOpenOrder]) -> None:
    """Persist the latest unified open orders snapshot in memory."""
    global _orders, _last_updated
    with _lock:
        _orders = list(orders or [])
        _last_updated = datetime.now(timezone.utc)


def get_unified_open_orders() -> Tuple[List[UnifiedOpenOrder], Optional[datetime]]:
    """Return the cached unified orders and their timestamp."""
    with _lock:
        return list(_orders), _last_updated


def get_open_orders_cache() -> Dict[str, Optional[object]]:
    """Return a raw cache dict for consumers that expect the legacy shape."""
    orders, last_updated = get_unified_open_orders()
    return {
        "orders": orders,
        "last_updated": last_updated,
    }


def get_unified_open_orders_summary() -> dict:
    """Return a serializable snapshot used by API responses."""
    orders, last_updated = get_unified_open_orders()
    return {
        "orders": [order.to_public_dict() for order in orders],
        "last_updated": last_updated.isoformat() if last_updated else None,
    }


def update_open_orders_cache(orders: List[UnifiedOpenOrder]) -> None:
    """Legacy helper used by exchange sync to store orders."""
    store_unified_open_orders(orders)


def clear_open_orders_cache() -> None:
    """Reset the cache (primarily used in tests)."""
    store_unified_open_orders([])


__all__ = [
    "get_open_orders_cache",
    "get_unified_open_orders",
    "get_unified_open_orders_summary",
    "update_open_orders_cache",
    "clear_open_orders_cache",
    "store_unified_open_orders",
]

