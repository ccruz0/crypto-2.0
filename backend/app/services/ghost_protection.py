"""List and cancel ghost/orphan protection legs (Expected TP red-banner rules).

Same rules as ``compute_protection_leg_stats``:
  - wrong_side_cover_on_long  (BUY SL/TP while wallet > 0)
  - wrong_side_cover_on_short (SELL SL/TP while wallet < 0)
  - qty_exceeds_wallet / no_wallet
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import (
    ADVANCED_CANCEL_ORDER_ENDPOINT,
    trade_client,
)
from app.services.dashboard_position_counts import compute_protection_leg_stats
from app.services.open_orders_resolver import resolve_open_orders
from app.utils.http_client import http_post

log = logging.getLogger("app.ghost_protection")


def balances_from_account_summary() -> List[dict]:
    """Normalize Crypto.com account summary into dashboard-style balance rows."""
    summary = trade_client.get_account_summary() or {}
    out: List[dict] = []
    for account in summary.get("accounts") or []:
        currency = (account.get("currency") or account.get("instrument_name") or "").upper()
        if not currency:
            continue
        raw = account.get("quantity", account.get("balance", "0"))
        try:
            bal = float(raw or 0)
        except (TypeError, ValueError):
            bal = 0.0
        out.append({"currency": currency, "balance": bal, "asset": currency})
    return out


def cancel_protection_order_on_exchange(
    order_id: str, *, order_type: Optional[str] = None
) -> dict:
    """Cancel a protection/trigger order via the exchange API (bypasses LIVE_TRADING DB gate)."""
    trade_client._refresh_runtime_flags()
    detail = trade_client._get_order_detail_summary(order_id)
    detail_type = (detail or {}).get("type") if isinstance(detail, dict) else None
    from app.services.brokers.crypto_com_trade import _is_conditional_order_type

    if _is_conditional_order_type(order_type) or _is_conditional_order_type(detail_type):
        method = ADVANCED_CANCEL_ORDER_ENDPOINT
    else:
        method = "private/cancel-order"
    payload = trade_client.sign_request(method, {"order_id": order_id})
    url = f"{trade_client.base_url}/{method}"
    response = http_post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
        calling_module="ghost_protection",
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") not in (0, None):
        return {"error": body.get("message") or str(body)}
    return body.get("result") or body


def _filter_alerts(
    alerts: List[dict],
    *,
    bases: Optional[Set[str]] = None,
    order_ids: Optional[Set[str]] = None,
) -> List[dict]:
    out = alerts
    if bases is not None:
        out = [a for a in out if (a.get("base") or "").upper() in bases]
    if order_ids is not None:
        wanted = {oid.strip() for oid in order_ids if oid and str(oid).strip()}
        out = [a for a in out if (a.get("order_id") or "").strip() in wanted]
    return out


def list_ghost_protection_alerts(
    db: Session,
    *,
    bases: Optional[Iterable[str]] = None,
    balances: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Return ghost/orphan protection alerts from live open orders + wallet."""
    bal = balances if balances is not None else balances_from_account_summary()
    resolved = resolve_open_orders(db)
    orders = list(resolved.orders or [])
    _tp, _prot, alerts = compute_protection_leg_stats(orders, bal)

    base_set: Optional[Set[str]] = None
    if bases is not None:
        base_set = {b.strip().upper() for b in bases if b and str(b).strip()}
    alerts = _filter_alerts(alerts, bases=base_set)

    by_base: Dict[str, int] = {}
    for a in alerts:
        b = (a.get("base") or "?").upper()
        by_base[b] = by_base.get(b, 0) + 1

    return {
        "ok": True,
        "count": len(alerts),
        "by_base": by_base,
        "alerts": alerts,
        "open_orders_count": len(orders),
        "sync_status": getattr(resolved, "sync_status", None),
    }


def clean_ghost_protection_alerts(
    db: Session,
    *,
    dry_run: bool = True,
    order_ids: Optional[Iterable[str]] = None,
    bases: Optional[Iterable[str]] = None,
    balances: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """Cancel ghost protection legs (or dry-run). Only cancels currently flagged ghosts."""
    listed = list_ghost_protection_alerts(db, bases=bases, balances=balances)
    alerts: List[dict] = list(listed.get("alerts") or [])

    id_set: Optional[Set[str]] = None
    if order_ids is not None:
        id_set = {str(oid).strip() for oid in order_ids if oid and str(oid).strip()}
        alerts = _filter_alerts(alerts, order_ids=id_set)

    results: List[dict] = []
    cancelled = 0
    failed = 0
    skipped = 0

    for alert in alerts:
        oid = (alert.get("order_id") or "").strip()
        entry = {
            "order_id": oid or None,
            "symbol": alert.get("symbol"),
            "base": alert.get("base"),
            "side": alert.get("side"),
            "order_type": alert.get("order_type"),
            "quantity": alert.get("quantity"),
            "wallet_qty": alert.get("wallet_qty"),
            "reason": alert.get("reason"),
            "status": "pending",
            "error": None,
        }
        if not oid:
            entry["status"] = "skipped"
            entry["error"] = "missing_order_id"
            skipped += 1
            results.append(entry)
            continue

        if dry_run:
            entry["status"] = "would_cancel"
            results.append(entry)
            continue

        try:
            result = cancel_protection_order_on_exchange(
                oid, order_type=alert.get("order_type")
            )
            if isinstance(result, dict) and result.get("error"):
                entry["status"] = "failed"
                entry["error"] = str(result.get("error"))
                failed += 1
                results.append(entry)
                continue

            row = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == oid)
                .first()
            )
            if row is not None:
                row.status = OrderStatusEnum.CANCELLED
                row.exchange_update_time = datetime.now(timezone.utc)
                db.commit()

            entry["status"] = "cancelled"
            cancelled += 1
            results.append(entry)
            log.info(
                "Ghost protection cancelled order_id=%s symbol=%s reason=%s",
                oid,
                alert.get("symbol"),
                alert.get("reason"),
            )
        except Exception as exc:
            db.rollback()
            entry["status"] = "failed"
            entry["error"] = str(exc)
            failed += 1
            results.append(entry)
            log.exception("Ghost protection cancel failed order_id=%s", oid)

    return {
        "ok": failed == 0,
        "dry_run": dry_run,
        "count": len(alerts),
        "cancelled": cancelled,
        "failed": failed,
        "skipped": skipped,
        "by_base": listed.get("by_base") if order_ids is None else None,
        "results": results,
    }
