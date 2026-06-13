"""Read-only reconciliation of Crypto.com open orders vs DB vs dashboard cache."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.models.exchange_order import OrderStatusEnum

_OPEN_STATUSES = frozenset(
    {
        OrderStatusEnum.NEW.value,
        OrderStatusEnum.ACTIVE.value,
        OrderStatusEnum.PARTIALLY_FILLED.value,
    }
)

_TERMINAL_STATUSES = frozenset(
    {
        OrderStatusEnum.FILLED.value,
        OrderStatusEnum.CANCELLED.value,
        OrderStatusEnum.REJECTED.value,
        OrderStatusEnum.EXPIRED.value,
    }
)


def _normalize_symbol(symbol: str | None) -> str:
    if not symbol:
        return ""
    return symbol.replace("-", "_").replace("/", "_").upper()


def _normalize_status(status: str | None) -> str:
    if not status:
        return "UNKNOWN"
    return str(status).strip().upper()


def _decimal_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _order_snapshot(
    *,
    order_id: str,
    symbol: str,
    status: str,
    side: str | None = None,
    order_type: str | None = None,
    is_trigger: bool = False,
    source: str,
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "symbol": _normalize_symbol(symbol),
        "status": _normalize_status(status),
        "side": (side or "").upper() or None,
        "order_type": (order_type or "").upper() or None,
        "is_trigger": is_trigger,
        "source": source,
    }


def _fetch_exchange_orders() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.core.crypto_com_guardrail import get_execution_context, require_aws_or_skip
    from app.services.brokers.crypto_com_trade import trade_client
    from app.utils.credential_resolver import ensure_trade_client_crypto_credentials

    credential_meta = ensure_trade_client_crypto_credentials()
    meta: dict[str, Any] = {
        "execution_context": get_execution_context(),
        "skipped": False,
        "error": None,
        "regular_count": 0,
        "trigger_count": 0,
        "credentials_loaded": credential_meta.get("credentials_loaded"),
        "credential_pair": credential_meta.get("used_pair_name"),
        "credential_diagnostics": credential_meta.get("credential_diagnostics"),
        "runtime_env_path": credential_meta.get("runtime_env_path"),
    }

    skip = require_aws_or_skip("reconcile_crypto_com_open_orders")
    if skip:
        meta["skipped"] = True
        meta["skip_reason"] = skip.get("reason")
        return [], meta

    if not trade_client.api_key or not trade_client.api_secret:
        meta["error"] = "API credentials not configured"
        meta["sync_status"] = "missing_credentials"
        meta["data_verified"] = False
        return [], meta

    from app.services.unified_open_orders_fetch import fetch_unified_open_orders

    try:
        fetch_result = fetch_unified_open_orders(trade_client)
    except Exception as exc:
        meta["error"] = str(exc)
        meta["sync_status"] = "api_error"
        meta["data_verified"] = False
        return [], meta

    if not fetch_result.get("data_verified"):
        meta["error"] = fetch_result.get("error_message")
        meta["sync_status"] = fetch_result.get("sync_status")
        meta["error_code"] = fetch_result.get("error_code")
        meta["data_verified"] = False
        return [], meta

    meta["sync_status"] = "ok"
    meta["data_verified"] = True
    meta["trigger_orders_status"] = fetch_result.get("trigger_orders_status")
    meta["trigger_orders_error"] = fetch_result.get("trigger_orders_error")
    meta["trigger_orders_error_code"] = fetch_result.get("trigger_orders_error_code")

    orders: list[dict[str, Any]] = []
    for item in fetch_result.get("orders") or []:
        orders.append(
            _order_snapshot(
                order_id=item.order_id,
                symbol=item.symbol,
                status=item.status,
                side=item.side,
                order_type=item.order_type,
                is_trigger=item.is_trigger,
                source="exchange_live",
            )
        )
        if item.is_trigger:
            meta["trigger_count"] += 1
        else:
            meta["regular_count"] += 1

    meta["total_count"] = len(orders)
    return orders, meta


def _fetch_db_open_orders() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.database import create_db_session
    from app.models.exchange_order import ExchangeOrder

    meta: dict[str, Any] = {"error": None, "total_count": 0}
    orders: list[dict[str, Any]] = []

    try:
        db = create_db_session()
    except Exception as exc:
        meta["error"] = str(exc)
        return [], meta

    try:
        rows = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.status.in_(
                    [
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED,
                    ]
                )
            )
            .all()
        )
        for row in rows:
            orders.append(
                _order_snapshot(
                    order_id=row.exchange_order_id,
                    symbol=row.symbol,
                    status=row.status.value,
                    side=row.side.value if row.side else None,
                    order_type=row.order_type,
                    is_trigger=_is_trigger_order_type(row.order_type, row.order_role),
                    source="database",
                )
            )
        meta["total_count"] = len(orders)
        return orders, meta
    except Exception as exc:
        meta["error"] = str(exc)
        return [], meta
    finally:
        db.close()


def _is_trigger_order_type(order_type: str | None, order_role: str | None) -> bool:
    order_type_u = (order_type or "").upper()
    order_role_u = (order_role or "").upper()
    trigger_tokens = ("STOP_LOSS", "STOP_LIMIT", "TAKE_PROFIT", "TRIGGER")
    return any(token in order_type_u for token in trigger_tokens) or any(
        token in order_role_u for token in trigger_tokens
    )


def _fetch_dashboard_orders() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.services.open_orders_cache import get_open_orders_cache

    meta: dict[str, Any] = {"error": None, "last_updated": None, "total_count": 0}
    cache = get_open_orders_cache() or {}
    last_updated = cache.get("last_updated")
    meta["last_updated"] = last_updated.isoformat() if last_updated else None

    orders: list[dict[str, Any]] = []
    for item in cache.get("orders") or []:
        orders.append(
            _order_snapshot(
                order_id=item.order_id,
                symbol=item.symbol,
                status=item.status,
                side=item.side,
                order_type=item.order_type,
                is_trigger=item.is_trigger,
                source="dashboard_cache",
            )
        )
    meta["total_count"] = len(orders)
    return orders, meta


def _index_by_id(orders: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for order in orders:
        order_id = order.get("order_id")
        if order_id:
            indexed[str(order_id)] = order
    return indexed


def _reconcile_pair(
    *,
    left_name: str,
    left_orders: list[dict[str, Any]],
    right_name: str,
    right_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    left_by_id = _index_by_id(left_orders)
    right_by_id = _index_by_id(right_orders)
    left_ids = set(left_by_id)
    right_ids = set(right_by_id)

    missing_in_right = sorted(left_ids - right_ids)
    missing_in_left = sorted(right_ids - left_ids)

    status_mismatches: list[dict[str, Any]] = []
    symbol_mismatches: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []

    for order_id in sorted(left_ids & right_ids):
        left = left_by_id[order_id]
        right = right_by_id[order_id]
        left_status = _normalize_status(left.get("status"))
        right_status = _normalize_status(right.get("status"))
        left_symbol = _normalize_symbol(left.get("symbol"))
        right_symbol = _normalize_symbol(right.get("symbol"))

        entry = {
            "order_id": order_id,
            left_name: left,
            right_name: right,
        }
        matched.append(entry)

        if left_status != right_status:
            status_mismatches.append(
                {
                    "order_id": order_id,
                    f"{left_name}_status": left_status,
                    f"{right_name}_status": right_status,
                    "symbol": left_symbol or right_symbol,
                }
            )
        if left_symbol and right_symbol and left_symbol != right_symbol:
            symbol_mismatches.append(
                {
                    "order_id": order_id,
                    f"{left_name}_symbol": left_symbol,
                    f"{right_name}_symbol": right_symbol,
                    "status": left_status,
                }
            )

    return {
        "comparison": f"{left_name}_vs_{right_name}",
        "left_count": len(left_orders),
        "right_count": len(right_orders),
        "matched_count": len(matched),
        f"missing_in_{right_name}": [
            left_by_id[order_id] for order_id in missing_in_right
        ],
        f"missing_in_{left_name}": [
            right_by_id[order_id] for order_id in missing_in_left
        ],
        "status_mismatches": status_mismatches,
        "symbol_mismatches": symbol_mismatches,
    }


def _summarize_verdict(
    *,
    exchange_count: int,
    db_count: int,
    dashboard_count: int,
    exchange_meta: dict[str, Any],
    db_meta: dict[str, Any],
    dashboard_meta: dict[str, Any],
    reconciliations: list[dict[str, Any]],
) -> tuple[str, str, str]:
    if exchange_meta.get("skipped"):
        return (
            "Exchange fetch skipped (not in AWS execution context)",
            "Cannot compare live Crypto.com open orders from this environment. "
            "Run on EC2/backend-aws container with EXECUTION_CONTEXT=AWS.",
            "Re-run reconcile_crypto_com_open_orders inside backend-aws container.",
        )

    if exchange_meta.get("error") or exchange_meta.get("data_verified") is False:
        sync_status = exchange_meta.get("sync_status") or "api_error"
        return (
            f"Exchange fetch failed ({sync_status}): {exchange_meta.get('error') or 'not verified'}",
            "Live Crypto.com open orders could not be verified; reconciliation is incomplete. "
            "Dashboard zero must not be treated as confirmed empty.",
            "Verify EXCHANGE_CUSTOM_API_KEY/SECRET and API key IP allowlist, then re-run.",
        )

    if db_meta.get("error"):
        return (
            f"Database query failed: {db_meta['error']}",
            "Could not read exchange_orders open-status rows; reconciliation is incomplete.",
            "Verify DATABASE_URL connectivity, then re-run.",
        )

    issues = 0
    for rec in reconciliations:
        for key, value in rec.items():
            if key.endswith("_mismatches") and value:
                issues += len(value)
            elif key.startswith("missing_in_") and value:
                issues += len(value)

    if (
        exchange_count == 0
        and db_count == 0
        and dashboard_count == 0
        and exchange_meta.get("data_verified") is True
    ):
        return (
            "All sources agree: zero open orders",
            "Crypto.com live API, exchange_orders (open statuses), and dashboard cache all report "
            "zero open orders. The dashboard showing zero is consistent with the exchange.",
            "No action required unless open orders are expected on Crypto.com.",
        )

    if issues == 0:
        return (
            "All sources aligned",
            f"Exchange={exchange_count}, DB={db_count}, dashboard cache={dashboard_count}. "
            "No missing orders or status/symbol mismatches detected.",
            "No sync repair needed based on this read-only check.",
        )

    return (
        f"Reconciliation found {issues} discrepancy(ies)",
        f"Exchange={exchange_count}, DB={db_count}, dashboard cache={dashboard_count}. "
        "See reconciliation sections for orders present on one source but not another, "
        "or with status/symbol mismatches.",
        "Inspect exchange_sync logs and compare missing order IDs; do not run write cleanup "
        "unless explicitly approved.",
    )


def reconcile_crypto_com_open_orders(
    *,
    objective: str | None = None,
    action: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """
    Read-only three-way reconciliation:
    - Crypto.com live open orders (regular + trigger)
    - exchange_orders rows with open statuses
    - dashboard open orders cache (GET /api/orders/open source)
    """
    exchange_orders, exchange_meta = _fetch_exchange_orders()
    db_orders, db_meta = _fetch_db_open_orders()
    dashboard_orders, dashboard_meta = _fetch_dashboard_orders()

    reconciliations = [
        _reconcile_pair(
            left_name="exchange",
            left_orders=exchange_orders,
            right_name="database",
            right_orders=db_orders,
        ),
        _reconcile_pair(
            left_name="exchange",
            left_orders=exchange_orders,
            right_name="dashboard",
            right_orders=dashboard_orders,
        ),
        _reconcile_pair(
            left_name="database",
            left_orders=db_orders,
            right_name="dashboard",
            right_orders=dashboard_orders,
        ),
    ]

    root_cause, conclusion, next_action = _summarize_verdict(
        exchange_count=len(exchange_orders),
        db_count=len(db_orders),
        dashboard_count=len(dashboard_orders),
        exchange_meta=exchange_meta,
        db_meta=db_meta,
        dashboard_meta=dashboard_meta,
        reconciliations=reconciliations,
    )

    return {
        "tool": "reconcile_crypto_com_open_orders",
        "ok": True,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "exchange_live": len(exchange_orders),
            "database_open": len(db_orders),
            "dashboard_cache": len(dashboard_orders),
        },
        "sources": {
            "exchange": exchange_meta,
            "database": db_meta,
            "dashboard": dashboard_meta,
        },
        "exchange_orders": exchange_orders,
        "database_orders": db_orders,
        "dashboard_orders": dashboard_orders,
        "reconciliations": reconciliations,
        "root_cause": root_cause,
        "conclusion": conclusion,
        "next_action": next_action,
        "open_statuses": sorted(_OPEN_STATUSES),
    }
