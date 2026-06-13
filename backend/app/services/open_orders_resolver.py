"""Resolve open orders from in-memory cache with database fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.open_orders import UnifiedOpenOrder, _format_timestamp, _normalize_symbol
from app.services.open_orders_cache import get_open_orders_cache
from app.services.open_orders_sync_status import sync_status_public_dict

_OPEN_STATUSES = (
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
)


def _is_trigger_order_type(order_type: str | None, order_role: str | None) -> bool:
    order_type_u = (order_type or "").upper()
    order_role_u = (order_role or "").upper()
    trigger_tokens = ("STOP_LOSS", "STOP_LIMIT", "TAKE_PROFIT", "TRIGGER")
    return any(token in order_type_u for token in trigger_tokens) or any(
        token in order_role_u for token in trigger_tokens
    )


def _is_exchange_synced_row(row: ExchangeOrder) -> bool:
    return row.exchange_create_time is not None or row.exchange_update_time is not None


def exchange_order_to_unified(row: ExchangeOrder) -> UnifiedOpenOrder:
    """Convert a database ExchangeOrder row into UnifiedOpenOrder."""
    is_trigger = _is_trigger_order_type(row.order_type, row.order_role)
    trigger_price = None
    price = row.price
    if is_trigger and row.trigger_condition is not None:
        trigger_price = row.trigger_condition
        if price is None:
            price = row.trigger_condition

    metadata: dict[str, Any] = {
        "order_id": row.exchange_order_id,
        "instrument_name": row.symbol,
        "side": row.side.value if row.side else None,
        "order_type": row.order_type,
        "status": row.status.value if row.status else None,
        "quantity": str(row.quantity) if row.quantity is not None else None,
        "limit_price": str(price) if price is not None else None,
        "order_role": row.order_role,
        "client_oid": row.client_oid,
        "create_time": row.exchange_create_time,
        "update_time": row.exchange_update_time,
        "source": "database",
    }

    return UnifiedOpenOrder(
        order_id=str(row.exchange_order_id),
        symbol=_normalize_symbol(row.symbol),
        side=row.side.value if row.side else "BUY",
        order_type=(row.order_type or "LIMIT").upper(),
        status=row.status.value if row.status else "NEW",
        price=price,
        trigger_price=trigger_price,
        quantity=row.quantity or Decimal("0"),
        is_trigger=is_trigger,
        client_oid=row.client_oid,
        created_at=_format_timestamp(row.exchange_create_time or row.created_at),
        updated_at=_format_timestamp(row.exchange_update_time or row.updated_at),
        source="database",
        metadata=metadata,
    )


def fetch_db_open_orders_unified(db: Session) -> tuple[list[UnifiedOpenOrder], bool]:
    rows = (
        db.query(ExchangeOrder)
        .filter(ExchangeOrder.status.in_(_OPEN_STATUSES))
        .order_by(ExchangeOrder.created_at.desc())
        .limit(500)
        .all()
    )
    orders = [exchange_order_to_unified(row) for row in rows]
    data_verified = bool(rows) and all(_is_exchange_synced_row(row) for row in rows)
    return orders, data_verified


def unified_order_to_frontend_dict(unified_order: UnifiedOpenOrder) -> dict[str, Any]:
    """Convert UnifiedOpenOrder to the /api/orders/open response shape."""
    create_time = None
    create_timestamp_ms = None
    create_datetime_str = "N/A"

    if unified_order.created_at:
        try:
            if isinstance(unified_order.created_at, str):
                create_time = datetime.fromisoformat(unified_order.created_at.replace("Z", "+00:00"))
            else:
                create_time = unified_order.created_at
            if create_time.tzinfo is None:
                create_time = create_time.replace(tzinfo=timezone.utc)
            create_timestamp_ms = int(create_time.timestamp() * 1000)
            create_datetime_str = create_time.isoformat()
        except Exception:
            pass

    update_timestamp_ms = None
    if unified_order.updated_at:
        try:
            if isinstance(unified_order.updated_at, str):
                update_time = datetime.fromisoformat(unified_order.updated_at.replace("Z", "+00:00"))
            else:
                update_time = unified_order.updated_at
            if update_time.tzinfo is None:
                update_time = update_time.replace(tzinfo=timezone.utc)
            update_timestamp_ms = int(update_time.timestamp() * 1000)
        except Exception:
            update_timestamp_ms = create_timestamp_ms

    return {
        "order_id": unified_order.order_id,
        "client_oid": unified_order.client_oid,
        "instrument_name": unified_order.symbol,
        "order_type": unified_order.order_type or "LIMIT",
        "order_role": unified_order.metadata.get("order_role") if unified_order.metadata else None,
        "side": unified_order.side,
        "status": unified_order.status,
        "quantity": float(unified_order.quantity) if unified_order.quantity else 0.0,
        "price": float(unified_order.price) if unified_order.price else None,
        "trigger_price": float(unified_order.trigger_price) if unified_order.trigger_price is not None else None,
        "is_trigger": getattr(unified_order, "is_trigger", False),
        "avg_price": None,
        "cumulative_quantity": 0.0,
        "cumulative_value": 0.0,
        "create_time": create_timestamp_ms,
        "create_datetime": create_datetime_str,
        "update_time": update_timestamp_ms or create_timestamp_ms,
    }


@dataclass
class ResolvedOpenOrders:
    orders: list[UnifiedOpenOrder]
    source: str
    sync_status: str
    data_verified: bool
    last_updated: Optional[str]
    error_code: Optional[int]
    error_message: Optional[str]
    trigger_orders_status: Optional[str]
    trigger_orders_error: Optional[str]
    trigger_orders_error_code: Optional[int]

    def to_sync_meta(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "last_updated": self.last_updated,
            "sync_status": self.sync_status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "data_verified": self.data_verified,
            "trigger_orders_status": self.trigger_orders_status,
            "trigger_orders_error": self.trigger_orders_error,
            "trigger_orders_error_code": self.trigger_orders_error_code,
        }


def _cache_orders_list(cache: dict[str, Any]) -> list[UnifiedOpenOrder]:
    raw = cache.get("orders") or []
    if not isinstance(raw, list):
        return []
    return list(raw)


def resolve_open_orders(db: Optional[Session] = None) -> ResolvedOpenOrders:
    """
    Return open orders preferring a healthy in-memory cache; fall back to DB rows
    when the cache is empty or sync metadata is not ok.
    """
    cache = get_open_orders_cache() or {}
    cache_orders = _cache_orders_list(cache)
    sync_meta = sync_status_public_dict()
    cache_sync_status = sync_meta.get("sync_status") or "stale"
    cache_data_verified = bool(sync_meta.get("data_verified"))

    cache_usable = bool(cache_orders) and cache_sync_status == "ok" and cache_data_verified
    if cache_usable:
        return ResolvedOpenOrders(
            orders=cache_orders,
            source="crypto_com_api",
            sync_status="ok",
            data_verified=True,
            last_updated=sync_meta.get("last_updated"),
            error_code=sync_meta.get("error_code"),
            error_message=sync_meta.get("error_message"),
            trigger_orders_status=sync_meta.get("trigger_orders_status"),
            trigger_orders_error=sync_meta.get("trigger_orders_error"),
            trigger_orders_error_code=sync_meta.get("trigger_orders_error_code"),
        )

    db_orders: list[UnifiedOpenOrder] = []
    data_verified = False
    if db is not None:
        try:
            db_orders, data_verified = fetch_db_open_orders_unified(db)
        except Exception:
            db_orders = []
            data_verified = False

    if db_orders:
        fallback_status = "ok_db_fallback" if cache_sync_status == "ok" else "stale_cache_db_fallback"
        last_updated = sync_meta.get("last_updated")
        if not last_updated:
            for order in db_orders:
                if order.updated_at:
                    last_updated = order.updated_at
                    break

        return ResolvedOpenOrders(
            orders=db_orders,
            source="database_fallback",
            sync_status=fallback_status,
            data_verified=data_verified,
            last_updated=last_updated,
            error_code=sync_meta.get("error_code"),
            error_message=sync_meta.get("error_message"),
            trigger_orders_status=sync_meta.get("trigger_orders_status"),
            trigger_orders_error=sync_meta.get("trigger_orders_error"),
            trigger_orders_error_code=sync_meta.get("trigger_orders_error_code"),
        )

    return ResolvedOpenOrders(
        orders=[],
        source=sync_meta.get("source") or "crypto.com",
        sync_status=cache_sync_status,
        data_verified=False,
        last_updated=sync_meta.get("last_updated"),
        error_code=sync_meta.get("error_code"),
        error_message=sync_meta.get("error_message"),
        trigger_orders_status=sync_meta.get("trigger_orders_status"),
        trigger_orders_error=sync_meta.get("trigger_orders_error"),
        trigger_orders_error_code=sync_meta.get("trigger_orders_error_code"),
    )


__all__ = [
    "ResolvedOpenOrders",
    "exchange_order_to_unified",
    "fetch_db_open_orders_unified",
    "resolve_open_orders",
    "unified_order_to_frontend_dict",
]
