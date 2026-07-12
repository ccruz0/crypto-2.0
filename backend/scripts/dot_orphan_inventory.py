#!/usr/bin/env python3
"""
Read-only inventory of DOT SL/TP on exchange + DB for orphan cleanup.

When to use:
  After Expected TP shows orphaned protection for DOT (balance <= 0 but SL/TP
  remain), run this script to compare DB vs exchange open orders and list orphan
  candidates before cancellation.

Usage:
  cd backend && python scripts/dot_orphan_inventory.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.unified_open_orders_fetch import fetch_unified_open_orders

PRESERVE_PARENT = "5755600491599560690"
PRESERVE_SL = "73817490101968821"
PRESERVE_TP = "73817490101971168"
SYMBOLS = {"DOT_USD", "DOT_USDT"}
SL_TP_TYPES = [
    "STOP_LIMIT",
    "STOP_LOSS_LIMIT",
    "STOP_LOSS",
    "TAKE_PROFIT_LIMIT",
    "TAKE_PROFIT",
]


def is_sl_tp_order(raw: dict) -> bool:
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    return "STOP" in ot or "TAKE_PROFIT" in ot


def main() -> None:
    db = create_db_session()
    try:
        active = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.symbol.in_(SYMBOLS),
                ExchangeOrder.order_type.in_(SL_TP_TYPES),
                ExchangeOrder.status.in_(
                    [
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED,
                    ]
                ),
            )
            .all()
        )
        print("=== DB ACTIVE SL/TP ===")
        print(f"count={len(active)}")
        total_db_qty = 0.0
        for o in sorted(
            active,
            key=lambda x: (x.symbol, x.order_type or "", str(x.exchange_order_id)),
        ):
            q = float(o.quantity or 0)
            total_db_qty += q
            print(
                f"  {o.exchange_order_id} | {o.symbol} | {o.order_type} | "
                f"role={o.order_role} | side={o.side} | qty={o.quantity} | "
                f"price={o.price} | parent={o.parent_order_id} | status={o.status}"
            )
        print(f"total_db_qty={total_db_qty}")

        parent = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == PRESERVE_PARENT)
            .first()
        )
        if parent:
            print(f"\n=== PRESERVE PARENT {PRESERVE_PARENT} ===")
            print(
                f"  symbol={parent.symbol} status={parent.status} side={parent.side} "
                f"qty={parent.quantity}"
            )
            children = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.parent_order_id == PRESERVE_PARENT)
                .all()
            )
            for c in children:
                print(
                    f"  child: {c.exchange_order_id} {c.order_type} role={c.order_role} "
                    f"status={c.status} qty={c.quantity} price={c.price}"
                )

        print("\n=== EXCHANGE (unified fetch) ===")
        result = fetch_unified_open_orders(trade_client)
        print(
            f"sync={result.get('sync_status')} "
            f"adv_status={result.get('advanced_orders_status')} "
            f"trigger_status={result.get('trigger_orders_status')}"
        )
        print(
            f"regular_raw={len(result.get('regular_raw', []))} "
            f"trigger_raw={len(result.get('trigger_raw', []))} "
            f"advanced_raw={len(result.get('advanced_raw', []))}"
        )

        all_raw = []
        for bucket in ("advanced_raw", "trigger_raw", "regular_raw"):
            for r in result.get(bucket, []):
                sym = (r.get("instrument_name") or "").upper()
                if sym in SYMBOLS and is_sl_tp_order(r):
                    all_raw.append(r)

        seen: set[str] = set()
        uniq: list[dict] = []
        for o in all_raw:
            oid = str(o.get("order_id") or o.get("exchange_order_id"))
            if oid not in seen:
                seen.add(oid)
                uniq.append(o)

        print(f"DOT SL/TP on exchange={len(uniq)}")
        total_ex_qty = 0.0
        for o in sorted(
            uniq,
            key=lambda x: (
                x.get("instrument_name", ""),
                x.get("order_type", ""),
                str(x.get("order_id", "")),
            ),
        ):
            oid = o.get("order_id") or o.get("exchange_order_id")
            ot = o.get("order_type") or o.get("type")
            q = float(o.get("quantity") or 0)
            total_ex_qty += q
            preserve = (
                " *** PRESERVE ***"
                if str(oid) in (PRESERVE_SL, PRESERVE_TP)
                else ""
            )
            print(
                f"  {oid} | {o.get('instrument_name')} | {ot} | side={o.get('side')} | "
                f"qty={o.get('quantity')} | limit={o.get('limit_price') or o.get('price')} | "
                f"ref={o.get('ref_price') or o.get('trigger_price')} | "
                f"status={o.get('status')}{preserve}"
            )
        print(f"total_exchange_sl_tp_qty={total_ex_qty}")

        preserve_ids = {PRESERVE_SL, PRESERVE_TP}
        orphan_candidates = [
            o
            for o in uniq
            if str(o.get("order_id") or o.get("exchange_order_id")) not in preserve_ids
        ]
        print(f"\n=== ORPHAN CANDIDATES (excl preserve SL/TP) ===")
        print(f"count={len(orphan_candidates)}")
        orphan_qty = sum(float(o.get("quantity") or 0) for o in orphan_candidates)
        print(f"orphan_qty={orphan_qty}")
        for o in orphan_candidates:
            oid = o.get("order_id") or o.get("exchange_order_id")
            print(
                f"  CANCEL? {oid} | {o.get('order_type')} | qty={o.get('quantity')} | "
                f"limit={o.get('limit_price') or o.get('price')}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
