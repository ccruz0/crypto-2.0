"""Shared Crypto.com open-orders fetch used by sync, APIs, and reconciliation."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.services.crypto_com_sync_errors import extract_sync_failure, is_sync_failure_response
from app.services.open_orders import UnifiedOpenOrder

logger = logging.getLogger(__name__)

PAGE_SIZE = 200
ADVANCED_SOURCE_ENDPOINT = "private/advanced/get-open-orders"


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


def _order_dedup_key(raw: dict[str, Any]) -> Optional[str]:
    for field in ("exchange_order_id", "order_id", "client_oid"):
        value = raw.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return None


def classify_advanced_open_order(raw: dict[str, Any]) -> tuple[bool, bool]:
    """
    Classify an advanced open order.

    Returns ``(include_in_unified, is_trigger)``.
    """
    order_type = (raw.get("order_type") or raw.get("type") or "").upper()
    status = (raw.get("status") or raw.get("order_status") or "ACTIVE").upper()

    is_trigger_type = "TAKE_PROFIT" in order_type or "STOP" in order_type
    active_statuses = {"ACTIVE", "PENDING", "NEW", "PARTIALLY_FILLED"}

    if is_trigger_type:
        return status in active_statuses, True

    if order_type in ("LIMIT", "MARKET") and status in active_statuses:
        if "TAKE_PROFIT" not in order_type and "STOP" not in order_type:
            return True, False

    return False, False


def _prepare_advanced_raw(raw: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(raw)
    prepared["source_endpoint"] = ADVANCED_SOURCE_ENDPOINT

    exec_inst = prepared.get("exec_inst") or []
    if isinstance(exec_inst, str):
        exec_inst = [exec_inst]
    prepared["is_margin_order"] = "MARGIN_ORDER" in exec_inst

    contingency = prepared.get("contingency_type") or prepared.get("contingencyType")
    prepared["contingency_type"] = contingency
    prepared["is_spot_attach"] = bool(prepared.get("is_spot_attach")) or contingency == "SPOT_ATTACH"
    return prepared


def _merge_raw_orders(
    regular_raw: list[dict[str, Any]],
    trigger_raw: list[dict[str, Any]],
    advanced_raw: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], bool]]:
    """Merge raw orders from all sources; dedupe and prefer trigger metadata."""
    merged: dict[str, tuple[dict[str, Any], bool]] = {}

    def upsert(raw: dict[str, Any], is_trigger: bool) -> None:
        key = _order_dedup_key(raw)
        if not key:
            return
        existing = merged.get(key)
        if existing is None:
            merged[key] = (raw, is_trigger)
            return
        existing_raw, existing_trigger = existing
        if is_trigger and not existing_trigger:
            merged[key] = (raw, True)
            return
        if is_trigger == existing_trigger:
            return
        merged[key] = (existing_raw, existing_trigger or is_trigger)

    for raw in regular_raw:
        upsert(raw, False)
    for raw in trigger_raw:
        upsert(raw, True)
    for raw in advanced_raw:
        prepared = _prepare_advanced_raw(raw)
        include, is_trigger = classify_advanced_open_order(prepared)
        if include:
            upsert(prepared, is_trigger)

    return list(merged.values())


def fetch_unified_open_orders(trade_client: Any | None = None) -> dict[str, Any]:
    """
    Fetch live open orders from Crypto.com (regular + trigger + advanced).

    Rules:
    - Regular open orders success => sync_status=ok, data_verified=True
    - Trigger orders failure (e.g. 50001) is non-fatal; exposed separately
    - Advanced orders supplement margin SPOT_ATTACH and trigger orders
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
        "advanced_raw": [],
        "all_raw_orders": [],
        "sync_status": "api_error",
        "data_verified": False,
        "error_code": None,
        "error_message": None,
        "trigger_orders_status": None,
        "trigger_orders_error": None,
        "trigger_orders_error_code": None,
        "advanced_orders_status": None,
        "advanced_orders_error": None,
        "advanced_orders_error_code": None,
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
                    "Trigger orders fetch failed (%s): %s — continuing with regular/advanced open orders",
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
            "Trigger orders fetch raised %s — continuing with regular/advanced open orders only",
            exc,
        )

    advanced_raw: list[dict[str, Any]] = []
    advanced_status: str | None = "ok"
    advanced_error: str | None = None
    advanced_error_code: int | None = None

    try:
        response = trade_client.get_advanced_open_orders()
        if is_sync_failure_response(response):
            failure = extract_sync_failure(response)
            advanced_status = failure.get("sync_status") or "api_error"
            advanced_error = failure.get("error_message")
            advanced_error_code = failure.get("error_code")
            logger.warning(
                "Advanced open orders fetch failed (%s): %s — continuing with regular/trigger orders",
                advanced_status,
                advanced_error,
            )
        else:
            advanced_raw = _extract_orders(response)
    except Exception as exc:
        advanced_status = "api_error"
        advanced_error = str(exc)
        logger.warning("Advanced open orders fetch raised %s", exc)

    merged_pairs = _merge_raw_orders(regular_raw, trigger_raw, advanced_raw)
    all_raw_orders = [raw for raw, _ in merged_pairs]

    combined: List[UnifiedOpenOrder] = []
    for raw, is_trigger in merged_pairs:
        try:
            mapped = trade_client._map_incoming_order(raw, is_trigger=is_trigger)
        except Exception as exc:
            logger.warning("Failed to normalize order payload: %s", exc)
            continue
        combined.append(mapped)

    regular_count = sum(1 for order in combined if not order.is_trigger)
    trigger_count = sum(1 for order in combined if order.is_trigger)

    data_verified = True
    if advanced_status not in (None, "ok") and not advanced_raw:
        logger.info(
            "Regular fetch succeeded but advanced fetch failed; data_verified remains true for regular orders"
        )

    result.update(
        {
            "orders": combined,
            "regular_raw": regular_raw,
            "trigger_raw": trigger_raw,
            "advanced_raw": advanced_raw,
            "all_raw_orders": all_raw_orders,
            "sync_status": "ok",
            "data_verified": data_verified,
            "error_code": None,
            "error_message": None,
            "trigger_orders_status": trigger_status,
            "trigger_orders_error": trigger_error,
            "trigger_orders_error_code": trigger_error_code,
            "advanced_orders_status": advanced_status,
            "advanced_orders_error": advanced_error,
            "advanced_orders_error_code": advanced_error_code,
            "regular_count": regular_count,
            "trigger_count": trigger_count,
        }
    )
    logger.info(
        "Unified open orders fetched: regular=%s, trigger=%s, advanced_raw=%s, total=%s, trigger_status=%s, advanced_status=%s",
        regular_count,
        trigger_count,
        len(advanced_raw),
        len(combined),
        trigger_status,
        advanced_status,
    )
    return result


__all__ = [
    "ADVANCED_SOURCE_ENDPOINT",
    "classify_advanced_open_order",
    "fetch_unified_open_orders",
]
