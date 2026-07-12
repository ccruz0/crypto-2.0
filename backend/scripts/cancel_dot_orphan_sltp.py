#!/usr/bin/env python3
"""
Cancel orphan DOT_USD SL/TP orders, preserving last-order protection.

When to use:
  After dot_orphan_inventory.py confirms orphan candidates (filled parent BUYs
  with stale SL/TP still on exchange). Default is dry-run; pass --live to cancel.

Usage:
  cd backend && python scripts/dot_orphan_inventory.py
  cd backend && python scripts/cancel_dot_orphan_sltp.py          # dry-run
  cd backend && python scripts/cancel_dot_orphan_sltp.py --live     # execute
"""
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.unified_open_orders_fetch import fetch_unified_open_orders

# Import cancel helper from existing duplicate-cleanup script
from scripts.cancel_duplicate_sl_tp import cancel_order_on_exchange

PRESERVE_IDS = frozenset({"73817490101968821", "73817490101971168"})
PRESERVE_PARENT = "5755600491599560690"
SYMBOLS = {"DOT_USD", "DOT_USDT"}
SL_TP_TYPES = [
    "STOP_LIMIT",
    "STOP_LOSS_LIMIT",
    "STOP_LOSS",
    "TAKE_PROFIT_LIMIT",
    "TAKE_PROFIT",
]
ORPHAN_PARENT_IDS = frozenset(
    {
        "5755600491393550286",
        "5755600491455791519",
        "5755600491468413585",
        "5755600491541407094",
        "5755600491297552675",
        "5755600491267092692",
    }
)


def is_sl_tp_raw(raw: dict) -> bool:
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    return "STOP" in ot or "TAKE_PROFIT" in ot


def collect_exchange_dot_sl_tp() -> list[dict]:
    result = fetch_unified_open_orders(trade_client)
    all_raw: list[dict] = []
    for bucket in ("advanced_raw", "trigger_raw", "regular_raw"):
        for r in result.get(bucket, []):
            sym = (r.get("instrument_name") or "").upper()
            if sym in SYMBOLS and is_sl_tp_raw(r):
                all_raw.append(r)
    seen: set[str] = set()
    uniq: list[dict] = []
    for o in all_raw:
        oid = str(o.get("order_id") or o.get("exchange_order_id"))
        if oid not in seen:
            seen.add(oid)
            uniq.append(o)
    return uniq


def is_confirmed_orphan(db, db_order: ExchangeOrder | None) -> bool:
    if db_order is None:
        return False
    if db_order.parent_order_id == PRESERVE_PARENT:
        return False
    if db_order.parent_order_id in ORPHAN_PARENT_IDS:
        parent = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == db_order.parent_order_id)
            .first()
        )
        return parent is not None and parent.status == OrderStatusEnum.FILLED
    return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cancel orphan DOT SL/TP orders")
    parser.add_argument("--live", action="store_true", help="Execute cancellations")
    args = parser.parse_args()

    db = create_db_session()
    try:
        exchange_orders = collect_exchange_dot_sl_tp()
        before_count = len(exchange_orders)
        before_qty = sum(float(o.get("quantity") or 0) for o in exchange_orders)

        to_cancel: list[tuple[str, ExchangeOrder | None, dict]] = []
        preserved: list[str] = []

        for raw in exchange_orders:
            oid = str(raw.get("order_id") or raw.get("exchange_order_id"))
            if oid in PRESERVE_IDS:
                preserved.append(oid)
                continue
            db_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == oid)
                .first()
            )
            if is_confirmed_orphan(db, db_order):
                to_cancel.append((oid, db_order, raw))
            else:
                print(f"SKIP (uncertain): {oid} parent={getattr(db_order, 'parent_order_id', None)}")

        print("=== BEFORE ===")
        print(f"exchange_sl_tp_count={before_count} total_qty={before_qty}")
        print(f"preserve={sorted(preserved)}")
        print(f"to_cancel={len(to_cancel)} qty={sum(float(r.get('quantity') or 0) for _, _, r in to_cancel)}")

        cancelled = 0
        failed = 0
        cancelled_qty = 0.0

        for oid, db_order, raw in to_cancel:
            qty = float(raw.get("quantity") or 0)
            if not args.live:
                print(f"[DRY RUN] would cancel {oid} qty={qty}")
                continue
            print(f"Cancelling {oid} qty={qty}...", end=" ")
            try:
                result = cancel_order_on_exchange(
                    oid, order_type=raw.get("order_type") or raw.get("type")
                )
                if "error" not in result:
                    if db_order:
                        db_order.status = OrderStatusEnum.CANCELLED
                        db_order.exchange_update_time = datetime.now(timezone.utc)
                        db.commit()
                    print("OK")
                    cancelled += 1
                    cancelled_qty += qty
                else:
                    print(f"FAIL: {result.get('error')}")
                    failed += 1
                    db.rollback()
            except Exception as exc:
                print(f"ERROR: {exc}")
                failed += 1
                db.rollback()

        if args.live:
            after = collect_exchange_dot_sl_tp()
            after_qty = sum(float(o.get("quantity") or 0) for o in after)
            print("\n=== AFTER ===")
            print(f"exchange_sl_tp_count={len(after)} total_qty={after_qty}")
            for o in after:
                oid = o.get("order_id") or o.get("exchange_order_id")
                print(f"  kept: {oid} {o.get('order_type')} qty={o.get('quantity')}")
            print("\n=== SUMMARY ===")
            print(f"cancelled={cancelled} failed={failed} cancelled_qty={cancelled_qty}")
            print(f"preserved={sorted(preserved)}")
        else:
            print("\nRun with --live to execute")
    finally:
        db.close()


if __name__ == "__main__":
    main()
