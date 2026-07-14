#!/usr/bin/env python3
"""
One-shot DOT_USD short TP/SL repair (user-approved production cleanup).

Cancels wrong-side SELL TPs wrongly FIFO-matched to short lots, then creates
BUY TPs (and missing BUY SLs) for open short entry parents.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.sl_tp_protection import has_complete_sl_tp_protection
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
from scripts.cancel_duplicate_sl_tp import cancel_order_on_exchange

CANCEL_IDS = frozenset(
    {
        "73817490101971350",
        "73817490101971349",
        "73817490101971198",
    }
)
KEEP_TP_ID = "73817490101971624"
SYMBOL = "DOT_USD"

# Open short parents needing BUY protection (parent_id -> (tp_price, use_lot_qty))
SHORT_REPAIRS: dict[str, tuple[float, bool]] = {
    "5755600491352963495": (0.8600, False),  # entry 0.8984
    "5755600491393550286": (0.8600, False),  # entry 0.8825
    "5755600491330755974": (0.8700, True),   # entry 0.8742 — use FIFO open lot qty
}


def _round_price(price: float) -> float:
    return round(price, 2) if price >= 100 else round(price, 4)


def _sl_price_for_short(entry: float, sl_pct: float = 10.0) -> float:
    return _round_price(entry * (1 + sl_pct / 100))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fix DOT_USD short TP/SL protection")
    parser.add_argument("--live", action="store_true", help="Execute on exchange")
    args = parser.parse_args()

    db = create_db_session()
    cancelled: list[str] = []
    created_tp: list[tuple[str, float, str]] = []
    created_sl: list[tuple[str, float, str]] = []

    try:
        from app.services.expected_take_profit import rebuild_open_lots

        lot_qty_by_parent = {
            lot.buy_order_id: float(lot.lot_qty)
            for lot in rebuild_open_lots(db, SYMBOL)
            if lot.buy_order_id
        }

        print("=== CANCEL wrong-side SELL TPs ===")
        for oid in sorted(CANCEL_IDS):
            order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == oid)
                .first()
            )
            if not order:
                print(f"SKIP missing DB row: {oid}")
                continue
            print(
                f"{'CANCEL' if args.live else 'DRY'} {oid} side={order.side} "
                f"price={order.price} parent={order.parent_order_id}"
            )
            if not args.live:
                continue
            result = cancel_order_on_exchange(oid, order_type=order.order_type)
            if "error" in result:
                print(f"  FAIL: {result['error']}")
                continue
            order.status = OrderStatusEnum.CANCELLED
            order.exchange_update_time = datetime.now(timezone.utc)
            db.commit()
            cancelled.append(oid)
            print("  OK")

        print(f"\n=== KEEP TP {KEEP_TP_ID} (unchanged) ===")

        print("\n=== CREATE BUY TPs + missing BUY SLs ===")
        for parent_id, (tp_price, use_lot_qty) in SHORT_REPAIRS.items():
            parent = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == parent_id)
                .first()
            )
            if not parent:
                print(f"SKIP missing parent {parent_id}")
                continue

            entry = float(parent.avg_price or parent.price or 0)
            qty = lot_qty_by_parent.get(parent_id) if use_lot_qty else float(
                parent.cumulative_quantity or parent.quantity or 0
            )
            if entry <= 0 or qty <= 0:
                print(f"SKIP invalid entry/qty parent={parent_id}")
                continue

            sl_price = _sl_price_for_short(entry)
            print(
                f"parent={parent_id} entry={entry} qty={qty} "
                f"tp={tp_price} sl={sl_price} complete_before="
                f"{has_complete_sl_tp_protection(db, parent_id)}"
            )

            if not args.live:
                continue

            if not has_complete_sl_tp_protection(db, parent_id):
                sl_result = create_stop_loss_order(
                    db=db,
                    symbol=SYMBOL,
                    side="SELL",
                    sl_price=sl_price,
                    quantity=qty,
                    entry_price=entry,
                    parent_order_id=parent_id,
                    dry_run=False,
                    source="auto",
                )
                sl_oid = sl_result.get("order_id")
                if sl_oid:
                    created_sl.append((parent_id, sl_price, sl_oid))
                    print(f"  SL created {sl_oid} @ {sl_price}")
                elif sl_result.get("error"):
                    print(f"  SL FAIL: {sl_result['error']}")

            tp_result = create_take_profit_order(
                db=db,
                symbol=SYMBOL,
                side="SELL",
                tp_price=tp_price,
                quantity=qty,
                entry_price=entry,
                parent_order_id=parent_id,
                dry_run=False,
                source="auto",
            )
            tp_oid = tp_result.get("order_id")
            if tp_oid:
                created_tp.append((parent_id, tp_price, tp_oid))
                print(f"  TP created {tp_oid} @ {tp_price}")
            elif tp_result.get("error"):
                print(f"  TP FAIL: {tp_result['error']}")

            complete = has_complete_sl_tp_protection(db, parent_id)
            print(f"  protection_complete={complete}")

        print("\n=== SUMMARY ===")
        print(f"cancelled={cancelled}")
        print(f"created_tp={created_tp}")
        print(f"created_sl={created_sl}")
        if not args.live:
            print("Run with --live to execute")
    finally:
        db.close()


if __name__ == "__main__":
    main()
