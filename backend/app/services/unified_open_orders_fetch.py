"""Shared Crypto.com open-orders fetch used by sync, APIs, and reconciliation."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.services.crypto_com_sync_errors import extract_sync_failure, is_sync_failure_response
from app.services.open_orders import UnifiedOpenOrder

logger = logging.getLogger(__name__)

PAGE_SIZE = 200


def _extract_orders(response: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not response:
        return []
    data = response.get("data")
    if isinstance(data, list):
        return data
    orders = response.get("orders")
    if isinstance(orders, list):
        return orders
    return []


def fetch_unified_open_orders(trade_client: Any | None = None) -> dict[str, Any]:
    """
    Fetch live open orders from Crypto.com (regular + trigger).

    Rules:
    - Regular open orders success => sync_status=ok, data_verified=True
    - Trigger orders failure (e.g. 50001) is non-fatal; exposed separately
    - instrument_name preserved exactly as returned (aside from .upper())
    - failed_auth / missing_credentials only when regular fetch fails
    """
    if trade_client is None:
        from app.services.brokers.crypto_com_trade import trade_client as default_client

        trade_client = default_client

    result: dict[str, Any] = {
        "orders": [],
        "regular_raw": [],
        "trigger_raw": [],
        "sync_status": "api_error",
        "data_verified": False,
        "error_code": None,
        "error_message": None,
        "trigger_orders_status": None,
        "trigger_orders_error": None,
        "trigger_orders_error_code": None,
        "regular_count": 0,
        "trigger_count": 0,
    }

    regular_raw: list[dict[str, Any]] = []
    page = 0
    while True:
        response = trade_client.get_open_orders(page=page, page_size=PAGE_SIZE)
        if is_sync_failure_response(response):
            failure = extract_sync_failure(response)
            result["sync_status"] = failure.get("sync_status") or "api_error"
            result["error_code"] = failure.get("error_code")
            result["error_message"] = failure.get("error_message")
            result["data_verified"] = False
            return result

        batch = _extract_orders(response)
        if not batch:
            break
        regular_raw.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    trigger_raw: list[dict[str, Any]] = []
    trigger_status: str | None = "ok"
    trigger_error: str | None = None
    trigger_error_code: int | None = None

    page = 0
    try:
        while True:
            response = trade_client.get_trigger_orders(page=page, page_size=PAGE_SIZE)
            if is_sync_failure_response(response):
                failure = extract_sync_failure(response)
                trigger_status = failure.get("sync_status") or "api_error"
                trigger_error = failure.get("error_message")
                trigger_error_code = failure.get("error_code")
                logger.warning(
                    "Trigger orders fetch failed (%s): %s — continuing with regular open orders",
                    trigger_status,
                    trigger_error,
                )
                break

            batch = _extract_orders(response)
            if not batch:
                break
            trigger_raw.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
    except Exception as exc:
        trigger_status = "api_error"
        trigger_error = str(exc)
        logger.warning(
            "Trigger orders fetch raised %s — continuing with regular open orders only",
            exc,
        )

    combined: List[UnifiedOpenOrder] = []
    seen_ids: set[str] = set()

    def _append(raw_orders: list[dict[str, Any]], *, is_trigger: bool) -> None:
        for raw in raw_orders:
            try:
                mapped = trade_client._map_incoming_order(raw, is_trigger=is_trigger)
            except Exception as exc:
                logger.warning("Failed to normalize order payload: %s", exc)
                continue
            if mapped.order_id in seen_ids:
                continue
            seen_ids.add(mapped.order_id)
            combined.append(mapped)

    _append(regular_raw, is_trigger=False)
    _append(trigger_raw, is_trigger=True)

    regular_count = sum(1 for order in combined if not order.is_trigger)
    trigger_count = sum(1 for order in combined if order.is_trigger)

    result.update(
        {
            "orders": combined,
            "regular_raw": regular_raw,
            "trigger_raw": trigger_raw,
            "sync_status": "ok",
            "data_verified": True,
            "error_code": None,
            "error_message": None,
            "trigger_orders_status": trigger_status,
            "trigger_orders_error": trigger_error,
            "trigger_orders_error_code": trigger_error_code,
            "regular_count": regular_count,
            "trigger_count": trigger_count,
        }
    )
    logger.info(
        "Unified open orders fetched: regular=%s, trigger=%s, total=%s, trigger_status=%s",
        regular_count,
        trigger_count,
        len(combined),
        trigger_status,
    )
    return result


__all__ = ["fetch_unified_open_orders"]
