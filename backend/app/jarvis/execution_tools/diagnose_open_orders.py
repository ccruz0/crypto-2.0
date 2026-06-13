"""End-to-end open orders diagnostic for Jarvis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.jarvis.execution_tools.query_database import query_database
from app.jarvis.execution_tools.search_repository import search_repository

EvidenceItem = dict[str, str]

_OPEN_STATUSES = ("NEW", "ACTIVE", "PARTIALLY_FILLED")


def _evidence(
    *,
    source: str,
    reference: str,
    detail: str,
    confidence: str = "medium",
) -> EvidenceItem:
    return {
        "source": source,
        "reference": reference,
        "detail": detail[:800],
        "confidence": confidence,
    }


def _inspect_open_orders_cache() -> tuple[int, EvidenceItem]:
    try:
        from app.services.open_orders_cache import get_open_orders_cache

        cache = get_open_orders_cache() or {}
        orders = cache.get("orders") or []
        count = len(orders) if isinstance(orders, list) else 0
        last_updated = cache.get("last_updated")
        detail = f"Cache contains {count} open orders; last_updated={last_updated}"
        return count, _evidence(
            source="api",
            reference="open_orders_cache",
            detail=detail,
            confidence="high",
        )
    except Exception as exc:
        return 0, _evidence(
            source="api",
            reference="open_orders_cache",
            detail=f"Failed to read cache: {exc}",
            confidence="low",
        )


def _inspect_api_route() -> EvidenceItem:
    repo = search_repository(topic="api_routes", max_results=5)
    hits = [m for m in repo.get("matches", []) if "get_open_orders" in m.get("text", "") or "/orders/open" in m.get("text", "")]
    if hits:
        hit = hits[0]
        return _evidence(
            source="repository",
            reference=hit.get("path", "routes_orders.py"),
            detail=f"Open orders API route at line {hit.get('line')}: {hit.get('text', '')[:200]}",
            confidence="high",
        )
    return _evidence(
        source="repository",
        reference="GET /orders/open",
        detail="Backend route GET /orders/open reads from Crypto.com open orders cache (routes_orders.py)",
        confidence="medium",
    )


def _inspect_frontend() -> EvidenceItem:
    repo = search_repository(topic="open_orders", max_results=8)
    frontend_hits = [
        m for m in repo.get("matches", [])
        if "frontend" in m.get("path", "") or "getOpenOrders" in m.get("text", "")
    ]
    if frontend_hits:
        hit = frontend_hits[0]
        return _evidence(
            source="repository",
            reference=hit.get("path", "frontend/src/app/api.ts"),
            detail=f"Frontend open orders hook at line {hit.get('line')}: {hit.get('text', '')[:200]}",
            confidence="high",
        )
    return _evidence(
        source="repository",
        reference="frontend/src/app/api.ts",
        detail="Frontend calls getOpenOrders() -> GET /orders/open",
        confidence="medium",
    )


def _determine_root_cause(
    *,
    db_open_count: int,
    cache_count: int,
    total_orders: int,
    status_counts: dict[str, int],
) -> tuple[str | None, str, str]:
    """Return root_cause, conclusion, next_action."""
    if db_open_count == 0 and cache_count == 0 and total_orders == 0:
        return (
            "No orders exist in exchange_orders table and open orders cache is empty",
            "The database has no order records and the Crypto.com cache is empty. "
            "The dashboard correctly shows zero open orders because there is no data to display.",
            "If open orders are expected, verify Crypto.com API credentials and exchange sync "
            "(ExchangeSyncService.sync_open_orders).",
        )

    if db_open_count > 0 and cache_count == 0:
        return (
            "Database has pending orders but Crypto.com open orders cache is empty",
            f"exchange_orders has {db_open_count} open-status rows but the API cache returned 0. "
            "The frontend reads from cache via GET /orders/open, not directly from the DB table.",
            "Run exchange sync to populate open_orders_cache, or inspect exchange credential/auth logs.",
        )

    if db_open_count == 0 and cache_count > 0:
        return (
            "Open orders cache has entries but exchange_orders has no open-status rows",
            f"Cache shows {cache_count} orders while DB open-status count is 0. "
            "Possible stale cache or status mapping mismatch between sync and DB import.",
            "Compare cache order IDs with exchange_orders.exchange_order_id and review sync filters.",
        )

    if total_orders > 0 and db_open_count == 0:
        top_status = max(status_counts, key=status_counts.get) if status_counts else "unknown"
        return (
            f"Orders exist ({total_orders} total) but none have open statuses ({', '.join(_OPEN_STATUSES)})",
            f"All {total_orders} orders are in terminal statuses (most common: {top_status}). "
            "Open orders UI filters to NEW/ACTIVE/PARTIALLY_FILLED only.",
            "Confirm whether pending orders exist on Crypto.com exchange; if yes, check status mapping in exchange sync.",
        )

    if db_open_count > 0 and cache_count > 0:
        return (
            "Open orders exist in database and cache; empty UI likely caused by frontend filter or mapping",
            f"Open orders pipeline healthy: DB={db_open_count} open-status rows, cache={cache_count} orders.",
            "If dashboard still shows empty, inspect frontend filter in page.tsx and getOpenOrders response mapping.",
        )

    return (
        None,
        "Insufficient data to determine why open orders appear empty.",
        "Collect exchange sync logs and verify Crypto.com API returns open orders.",
    )


def diagnose_open_orders(
    *,
    objective: str | None = None,
    action: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """
    Diagnose the open orders pipeline end-to-end.

    Checks DB table, cache, API route, frontend hook, and determines root cause.
    """
    evidence: list[EvidenceItem] = []

    db_count_result = query_database(preset="count_open_orders")
    db_open_count = int(db_count_result.get("count") or db_count_result.get("numeric_result") or 0)
    evidence.append(
        _evidence(
            source="database",
            reference="exchange_orders",
            detail=f"Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): {db_open_count}; "
            f"query={db_count_result.get('query_executed', '')[:120]}",
            confidence="high" if db_count_result.get("ok") else "low",
        )
    )

    status_result = query_database(preset="count_orders_by_status", limit=20)
    status_counts: dict[str, int] = status_result.get("status_counts") or {}
    if status_counts:
        evidence.append(
            _evidence(
                source="database",
                reference="exchange_orders.status",
                detail=f"Orders by status: {status_counts}",
                confidence="high",
            )
        )

    recent_result = query_database(preset="recent_orders", limit=5)
    recent_rows = recent_result.get("rows") or []
    if recent_rows:
        evidence.append(
            _evidence(
                source="database",
                reference="exchange_orders (recent)",
                detail=f"Latest orders sample: {recent_rows[:3]}",
                confidence="medium",
            )
        )

    positions_result = query_database(preset="open_positions", limit=10)
    pos_rows = positions_result.get("rows") or []
    evidence.append(
        _evidence(
            source="database",
            reference="exchange_orders (positions)",
            detail=f"Open position symbols: {pos_rows[:5] if pos_rows else 'none'}",
            confidence="medium",
        )
    )

    cache_count, cache_evidence = _inspect_open_orders_cache()
    evidence.append(cache_evidence)
    evidence.append(_inspect_api_route())
    evidence.append(_inspect_frontend())

    total_orders = sum(status_counts.values()) if status_counts else db_open_count
    root_cause, conclusion, next_action = _determine_root_cause(
        db_open_count=db_open_count,
        cache_count=cache_count,
        total_orders=total_orders,
        status_counts=status_counts,
    )

    return {
        "tool": "diagnose_open_orders",
        "ok": True,
        "read_only": True,
        "table": "exchange_orders",
        "db_open_count": db_open_count,
        "cache_open_count": cache_count,
        "count": db_open_count,
        "numeric_result": db_open_count,
        "available_statuses": list(status_counts.keys()) or list(_OPEN_STATUSES),
        "status_counts": status_counts,
        "latest_orders": recent_rows[:5],
        "api_route": "GET /orders/open",
        "frontend_hook": "getOpenOrders() in frontend/src/app/api.ts",
        "root_cause": root_cause,
        "evidence": evidence,
        "conclusion": conclusion,
        "next_action": next_action,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
