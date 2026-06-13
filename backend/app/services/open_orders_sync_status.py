"""Track Crypto.com open-orders sync health separately from cached order data."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal, Optional

SyncStatus = Literal["ok", "failed_auth", "missing_credentials", "api_error", "stale", "skipped"]

_lock = Lock()
_state: dict[str, Any] = {
    "source": "crypto.com",
    "last_updated": None,
    "sync_status": "stale",
    "error_code": None,
    "error_message": None,
    "data_verified": False,
    "trigger_orders_status": None,
    "trigger_orders_error": None,
    "trigger_orders_error_code": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_open_orders_sync_success(
    *,
    order_count: int = 0,
    trigger_orders_status: str | None = None,
    trigger_orders_error: str | None = None,
    trigger_orders_error_code: int | None = None,
) -> None:
    """Record a verified successful sync from the exchange."""
    with _lock:
        _state.update(
            {
                "source": "crypto.com",
                "last_updated": _now_iso(),
                "sync_status": "ok",
                "error_code": None,
                "error_message": None,
                "data_verified": True,
                "order_count": order_count,
                "trigger_orders_status": trigger_orders_status,
                "trigger_orders_error": trigger_orders_error,
                "trigger_orders_error_code": trigger_orders_error_code,
            }
        )


def record_open_orders_sync_failure(
    *,
    sync_status: SyncStatus,
    error_code: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Record sync failure; does not clear cached orders."""
    with _lock:
        _state.update(
            {
                "source": "crypto.com",
                "last_updated": _now_iso(),
                "sync_status": sync_status,
                "error_code": error_code,
                "error_message": error_message,
                "data_verified": False,
            }
        )


def get_open_orders_sync_status() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def sync_status_public_dict() -> dict[str, Any]:
    """JSON-serializable sync metadata for API responses."""
    status = get_open_orders_sync_status()
    return {
        "source": status.get("source") or "crypto.com",
        "last_updated": status.get("last_updated"),
        "sync_status": status.get("sync_status") or "stale",
        "error_code": status.get("error_code"),
        "error_message": status.get("error_message"),
        "data_verified": bool(status.get("data_verified")),
        "trigger_orders_status": status.get("trigger_orders_status"),
        "trigger_orders_error": status.get("trigger_orders_error"),
        "trigger_orders_error_code": status.get("trigger_orders_error_code"),
    }


def reset_open_orders_sync_status_for_tests() -> None:
    with _lock:
        _state.clear()
        _state.update(
            {
                "source": "crypto.com",
                "last_updated": None,
                "sync_status": "stale",
                "error_code": None,
                "error_message": None,
                "data_verified": False,
                "trigger_orders_status": None,
                "trigger_orders_error": None,
                "trigger_orders_error_code": None,
            }
        )


__all__ = [
    "SyncStatus",
    "get_open_orders_sync_status",
    "record_open_orders_sync_failure",
    "record_open_orders_sync_success",
    "reset_open_orders_sync_status_for_tests",
    "sync_status_public_dict",
]
