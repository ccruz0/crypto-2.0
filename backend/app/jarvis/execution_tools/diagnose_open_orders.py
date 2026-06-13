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
        detail = f"Raw in-memory cache contains {count} open orders; last_updated={last_updated}"
        return count, _evidence(
            source="api",
            reference="open_orders_cache_raw",
            detail=detail,
            confidence="high",
        )
    except Exception as exc:
        return 0, _evidence(
            source="api",
            reference="open_orders_cache_raw",
            detail=f"Failed to read cache: {exc}",
            confidence="low",
        )


def _inspect_dashboard_effective() -> tuple[int, str, str, EvidenceItem]:
    """What GET /api/orders/open returns via resolve_open_orders (includes DB fallback)."""
    try:
        from app.database import create_db_session
        from app.services.open_orders_resolver import resolve_open_orders

        db = create_db_session()
        try:
            resolved = resolve_open_orders(db)
        finally:
            db.close()

        count = len(resolved.orders)
        source = resolved.source or "unknown"
        sync_status = resolved.sync_status or "unknown"
        trigger_note = ""
        if resolved.trigger_orders_error:
            trigger_note = (
                f"; trigger_orders_error={resolved.trigger_orders_error}"
                f" (code={resolved.trigger_orders_error_code})"
            )
        detail = (
            f"Dashboard API effective count={count} via source={source}, "
            f"sync_status={sync_status}, data_verified={resolved.data_verified}{trigger_note}"
        )
        return count, source, sync_status, _evidence(
            source="dashboard",
            reference="resolve_open_orders",
            detail=detail,
            confidence="high",
        )
    except Exception as exc:
        return 0, "error", "error", _evidence(
            source="dashboard",
            reference="resolve_open_orders",
            detail=f"Failed to resolve dashboard open orders: {exc}",
            confidence="low",
        )


def _inspect_live_exchange() -> tuple[dict[str, Any], EvidenceItem]:
    """Live Crypto.com regular + trigger orders (same path as reconciliation)."""
    meta: dict[str, Any] = {
        "regular_count": 0,
        "trigger_count": 0,
        "total_count": 0,
        "data_verified": False,
        "sync_status": None,
        "error": None,
        "trigger_orders_error": None,
        "trigger_orders_error_code": None,
        "skipped": False,
    }
    try:
        from app.core.crypto_com_guardrail import require_aws_or_skip
        from app.services.brokers.crypto_com_trade import trade_client
        from app.services.unified_open_orders_fetch import fetch_unified_open_orders
        from app.utils.credential_resolver import ensure_trade_client_crypto_credentials

        skip = require_aws_or_skip("diagnose_open_orders")
        if skip:
            meta["skipped"] = True
            meta["error"] = skip.get("reason")
            return meta, _evidence(
                source="exchange",
                reference="live_open_orders",
                detail=f"Live exchange fetch skipped: {skip.get('reason')}",
                confidence="low",
            )

        cred = ensure_trade_client_crypto_credentials()
        if not trade_client.api_key or not trade_client.api_secret:
            meta["error"] = "API credentials not configured"
            meta["sync_status"] = "missing_credentials"
            return meta, _evidence(
                source="exchange",
                reference="live_open_orders",
                detail="Live exchange fetch unavailable: credentials not configured",
                confidence="high",
            )

        fetch_result = fetch_unified_open_orders(trade_client)
        meta.update(
            {
                "regular_count": fetch_result.get("regular_count") or 0,
                "trigger_count": fetch_result.get("trigger_count") or 0,
                "total_count": len(fetch_result.get("orders") or []),
                "data_verified": bool(fetch_result.get("data_verified")),
                "sync_status": fetch_result.get("sync_status"),
                "error": fetch_result.get("error_message"),
                "trigger_orders_error": fetch_result.get("trigger_orders_error"),
                "trigger_orders_error_code": fetch_result.get("trigger_orders_error_code"),
            }
        )
        trigger_status = fetch_result.get("trigger_orders_status")
        detail = (
            f"Live exchange: regular={meta['regular_count']}, trigger={meta['trigger_count']}, "
            f"total={meta['total_count']}, data_verified={meta['data_verified']}"
        )
        if meta["trigger_orders_error"]:
            detail += (
                f"; trigger API issue: {meta['trigger_orders_error']} "
                f"(code={meta['trigger_orders_error_code']}, status={trigger_status})"
            )
        return meta, _evidence(
            source="exchange",
            reference="live_open_orders",
            detail=detail,
            confidence="high" if meta["data_verified"] else "medium",
        )
    except Exception as exc:
        meta["error"] = str(exc)
        return meta, _evidence(
            source="exchange",
            reference="live_open_orders",
            detail=f"Live exchange fetch failed: {exc}",
            confidence="low",
        )


def _inspect_api_route() -> EvidenceItem:
    repo = search_repository(topic="api_routes", max_results=5)
    hits = [
        m
        for m in repo.get("matches", [])
        if "get_open_orders" in m.get("text", "") or "/orders/open" in m.get("text", "")
    ]
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
        detail="Backend route GET /orders/open uses resolve_open_orders (cache with DB fallback)",
        confidence="medium",
    )


def _inspect_frontend() -> EvidenceItem:
    repo = search_repository(topic="open_orders", max_results=8)
    frontend_hits = [
        m
        for m in repo.get("matches", [])
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
    cache_raw_count: int,
    dashboard_effective_count: int,
    dashboard_source: str,
    exchange_regular_count: int,
    exchange_trigger_count: int,
    exchange_total_count: int,
    exchange_data_verified: bool,
    exchange_skipped: bool,
    trigger_orders_error: str | None,
    trigger_orders_error_code: int | None,
    total_orders: int,
    status_counts: dict[str, int],
) -> tuple[str | None, str, str]:
    """Return root_cause, conclusion, next_action using live exchange + resolver paths."""

    if exchange_skipped:
        return (
            "Live exchange fetch skipped in this environment",
            "Cannot verify Crypto.com open orders from this runtime. "
            f"DB open-status={db_open_count}, raw cache={cache_raw_count}, "
            f"dashboard effective={dashboard_effective_count} (source={dashboard_source}).",
            "Re-run diagnose_open_orders inside backend-aws with EXECUTION_CONTEXT=AWS.",
        )

    if exchange_data_verified and exchange_total_count == 0 and db_open_count == 0 and cache_raw_count == 0:
        return (
            "All sources agree: zero open orders on exchange",
            "Crypto.com live API, exchange_orders (open statuses), and raw cache all report zero. "
            "Dashboard effective count also zero.",
            "No action required unless open orders are expected on Crypto.com.",
        )

    if exchange_data_verified and exchange_total_count > 0:
        if trigger_orders_error and exchange_trigger_count == 0 and exchange_regular_count > 0:
            if cache_raw_count == 0 and dashboard_effective_count == 0:
                return (
                    "Trigger order API failure may block cache updates; regular orders exist on exchange",
                    f"Live exchange has {exchange_regular_count} regular order(s) but trigger fetch failed "
                    f"({trigger_orders_error_code}: {trigger_orders_error}). "
                    f"Raw cache={cache_raw_count}; dashboard effective={dashboard_effective_count} "
                    f"(source={dashboard_source}).",
                    "Verify trigger-order API access; ensure sync uses cache-independent regular fetch.",
                )
            if dashboard_source == "database_fallback" and dashboard_effective_count > 0:
                return (
                    "Open orders cache stale; dashboard serving DB fallback while exchange has live orders",
                    f"Exchange live total={exchange_total_count} (regular={exchange_regular_count}, "
                    f"trigger={exchange_trigger_count}); raw cache={cache_raw_count}; "
                    f"dashboard effective={dashboard_effective_count} via {dashboard_source}.",
                    "Run exchange sync to refresh open_orders_cache; investigate trigger API if trigger count mismatches UI.",
                )

        if cache_raw_count == 0 and dashboard_effective_count > 0 and dashboard_source == "database_fallback":
            return (
                "Open orders cache empty but dashboard API serves database fallback",
                f"Exchange live total={exchange_total_count} (regular={exchange_regular_count}, "
                f"trigger={exchange_trigger_count}); DB open-status={db_open_count}; "
                f"raw cache=0; dashboard effective={dashboard_effective_count} via database_fallback. "
                "Users may still see orders — do not conclude dashboard is empty.",
                "Refresh open_orders_cache via exchange sync; compare live order IDs with exchange_orders.",
            )

        if cache_raw_count == 0 and dashboard_effective_count == 0 and exchange_total_count > 0:
            return (
                "Exchange has open orders but neither cache nor DB fallback populated dashboard API",
                f"Live exchange reports {exchange_total_count} order(s) "
                f"(regular={exchange_regular_count}, trigger={exchange_trigger_count}) but "
                f"dashboard effective count is 0 and raw cache is empty (DB open-status={db_open_count}).",
                "Inspect resolve_open_orders fallback conditions and exchange sync credential logs.",
            )

        if exchange_total_count != dashboard_effective_count or exchange_total_count != db_open_count:
            return (
                "Open order counts differ across exchange, database, and dashboard",
                f"Exchange live={exchange_total_count} (regular={exchange_regular_count}, "
                f"trigger={exchange_trigger_count}), DB={db_open_count}, "
                f"raw cache={cache_raw_count}, dashboard effective={dashboard_effective_count} "
                f"(source={dashboard_source}).",
                "Run reconcile_crypto_com_open_orders and inspect exchange_sync logs for missing order IDs.",
            )

    if db_open_count > 0 and cache_raw_count == 0 and not exchange_data_verified:
        return (
            "Database has open-status rows but cache is empty; live exchange not verified",
            f"exchange_orders has {db_open_count} open-status row(s), raw cache=0. "
            f"Dashboard effective={dashboard_effective_count} (source={dashboard_source}). "
            "Live exchange could not be verified in this run.",
            "Verify exchange credentials and re-run with live exchange access.",
        )

    if db_open_count == 0 and cache_raw_count > 0:
        return (
            "Open orders cache has entries but exchange_orders has no open-status rows",
            f"Raw cache shows {cache_raw_count} orders while DB open-status count is 0. "
            "Possible stale cache or status mapping mismatch.",
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

    if db_open_count > 0 and cache_raw_count > 0:
        return (
            "Open orders exist in database and cache",
            f"Pipeline healthy: DB={db_open_count} open-status rows, raw cache={cache_raw_count}, "
            f"dashboard effective={dashboard_effective_count}.",
            "If dashboard still shows empty, inspect frontend filter and API response mapping.",
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

    Compares live exchange, DB, raw cache, and dashboard-effective counts (resolve_open_orders).
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

    cache_raw_count, cache_evidence = _inspect_open_orders_cache()
    evidence.append(cache_evidence)

    dashboard_effective_count, dashboard_source, _dashboard_sync, dashboard_evidence = (
        _inspect_dashboard_effective()
    )
    evidence.append(dashboard_evidence)

    exchange_meta, exchange_evidence = _inspect_live_exchange()
    evidence.append(exchange_evidence)

    evidence.append(_inspect_api_route())
    evidence.append(_inspect_frontend())

    total_orders = sum(status_counts.values()) if status_counts else db_open_count
    root_cause, conclusion, next_action = _determine_root_cause(
        db_open_count=db_open_count,
        cache_raw_count=cache_raw_count,
        dashboard_effective_count=dashboard_effective_count,
        dashboard_source=dashboard_source,
        exchange_regular_count=int(exchange_meta.get("regular_count") or 0),
        exchange_trigger_count=int(exchange_meta.get("trigger_count") or 0),
        exchange_total_count=int(exchange_meta.get("total_count") or 0),
        exchange_data_verified=bool(exchange_meta.get("data_verified")),
        exchange_skipped=bool(exchange_meta.get("skipped")),
        trigger_orders_error=exchange_meta.get("trigger_orders_error"),
        trigger_orders_error_code=exchange_meta.get("trigger_orders_error_code"),
        total_orders=total_orders,
        status_counts=status_counts,
    )

    return {
        "tool": "diagnose_open_orders",
        "ok": True,
        "read_only": True,
        "table": "exchange_orders",
        "db_open_count": db_open_count,
        "cache_open_count": cache_raw_count,
        "cache_raw_count": cache_raw_count,
        "dashboard_effective_count": dashboard_effective_count,
        "dashboard_source": dashboard_source,
        "exchange_regular_count": exchange_meta.get("regular_count"),
        "exchange_trigger_count": exchange_meta.get("trigger_count"),
        "exchange_total_count": exchange_meta.get("total_count"),
        "exchange_data_verified": exchange_meta.get("data_verified"),
        "trigger_orders_error": exchange_meta.get("trigger_orders_error"),
        "trigger_orders_error_code": exchange_meta.get("trigger_orders_error_code"),
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
