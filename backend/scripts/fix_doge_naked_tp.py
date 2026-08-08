#!/usr/bin/env python3
"""Fix DOGE_USD naked short: recreate full-wallet SL + TP.

Prod audit 2026-08-07 / follow-up:
  wallet short, covered_qty=0, only STOP_LIMIT SLs on exchange (no TP).

Cancels open DOGE_USD SL/TP on the exchange, then places fresh protection for
the full |wallet| via recover_missing_tps helpers.

  python3 /repo/backend/scripts/fix_doge_naked_tp.py
  python3 /repo/backend/scripts/fix_doge_naked_tp.py --live
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.services.brokers.crypto_com_trade import trade_client
from app.services.unified_open_orders_fetch import fetch_unified_open_orders
from app.utils.live_trading import get_live_trading_status
from scripts.recover_missing_tps import build_plan, cancel_orders, place_protection, print_plan

SYMBOL = "DOGE_USD"


def _is_sl_tp_raw(raw: dict) -> bool:
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    return "STOP" in ot or "TAKE_PROFIT" in ot


def collect_open_sl_tp(symbol: str) -> tuple[list[str], dict[str, str], list[str]]:
    symbol_u = symbol.upper()
    result = fetch_unified_open_orders(trade_client)
    ids: list[str] = []
    types: dict[str, str] = {}
    details: list[str] = []
    seen: set[str] = set()
    for bucket in ("advanced_raw", "trigger_raw", "regular_raw"):
        for raw in result.get(bucket, []):
            sym = (raw.get("instrument_name") or "").upper()
            if sym != symbol_u or not _is_sl_tp_raw(raw):
                continue
            oid = str(raw.get("order_id") or raw.get("exchange_order_id") or "")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            ids.append(oid)
            ot = str(raw.get("order_type") or raw.get("type") or "STOP_LIMIT")
            types[oid] = ot
            qty = raw.get("quantity") or raw.get("qty")
            side = raw.get("side")
            details.append(f"{oid} {side} {ot} qty={qty}")
    return ids, types, details


def verify_after() -> tuple[int, int]:
    """Return (tp_count, sl_count) currently open on DOGE_USD."""
    ids, types, _ = collect_open_sl_tp(SYMBOL)
    tp = sum(1 for oid in ids if "TAKE_PROFIT" in (types.get(oid) or "").upper())
    sl = sum(1 for oid in ids if "TAKE_PROFIT" not in (types.get(oid) or "").upper())
    return tp, sl


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix DOGE_USD naked short (create TP+SL)")
    parser.add_argument("--live", action="store_true", help="Cancel and recreate on exchange")
    args = parser.parse_args()

    db = create_db_session()
    try:
        live_trading = get_live_trading_status(db)
        print(f"Mode: {'LIVE' if args.live else 'DRY-RUN'} | LIVE_TRADING={live_trading}")
        if args.live and not live_trading:
            print("REFUSING --live because LIVE_TRADING is false.")
            return 2

        print(f"\n{'=' * 72}\n{SYMBOL}\n{'=' * 72}")
        ids, types, details = collect_open_sl_tp(SYMBOL)
        print(f"Open SL/TP before ({len(ids)}):")
        for line in details:
            print(f"  {line}")

        if ids:
            cancelled = cancel_orders(ids, dry_run=not args.live, order_types=types, db=db)
            print(f"Cancelled: {cancelled}")
        else:
            print("No open SL/TP to cancel")

        plan = build_plan(db, SYMBOL)
        print_plan(plan)

        if plan.position_qty is None or float(plan.position_qty) >= 0:
            print(
                f"REFUSING: expected short wallet (negative), got position_qty={plan.position_qty}"
            )
            return 3

        if not plan.action.startswith("create"):
            print(f"No placement planned (action={plan.action})")
            # Still verify — maybe already protected after cancel edge case
            if args.live:
                tp, sl = verify_after()
                print(f"After verify: tp={tp} sl={sl}")
                return 0 if tp > 0 and sl > 0 else 1
            return 0

        if not args.live:
            print("[DRY RUN] would place protection (SL+TP for full |wallet|)")
            return 0

        res = place_protection(
            db,
            plan,
            live=True,
            tp_only=False,
            cancel_sl_first=False,  # already cancelled exchange legs above
        )
        print(f"Place result: placed={res.get('placed')} errors={res.get('errors')}")
        if res.get("errors"):
            return 1

        tp, sl = verify_after()
        print(f"After verify: tp={tp} sl={sl}")
        if tp < 1:
            print("FAIL: no TAKE_PROFIT leg visible on exchange after placement")
            return 1
        if sl < 1:
            print("WARN: TP placed but no STOP leg visible")
            return 1
        print("SUCCESS: DOGE_USD has TP + SL on exchange")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
