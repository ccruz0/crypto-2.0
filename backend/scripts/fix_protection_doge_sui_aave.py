#!/usr/bin/env python3
"""
Recreate full-wallet SL+TP for DOGE_USD, SUI_USD, AAVE_USD.

Cancels all open SL/TP on each symbol, then places fresh protection for the
full account balance via recover_missing_tps helpers.

  python3 /repo/backend/scripts/fix_protection_doge_sui_aave.py
  python3 /repo/backend/scripts/fix_protection_doge_sui_aave.py --live
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

SYMBOLS: tuple[str, ...] = ("DOGE_USD", "SUI_USD", "AAVE_USD")


def _is_sl_tp_raw(raw: dict) -> bool:
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    return "STOP" in ot or "TAKE_PROFIT" in ot


def collect_open_sl_tp(symbol: str) -> tuple[list[str], dict[str, str]]:
    symbol_u = symbol.upper()
    result = fetch_unified_open_orders(trade_client)
    ids: list[str] = []
    types: dict[str, str] = {}
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
            types[oid] = str(raw.get("order_type") or raw.get("type") or "STOP_LIMIT")
    return ids, types


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix DOGE/SUI/AAVE full SL+TP coverage")
    parser.add_argument("--live", action="store_true", help="Cancel and recreate on exchange")
    args = parser.parse_args()

    db = create_db_session()
    failures = 0
    try:
        live_trading = get_live_trading_status(db)
        print(f"Mode: {'LIVE' if args.live else 'DRY-RUN'} | LIVE_TRADING={live_trading}")
        if args.live and not live_trading:
            print("REFUSING --live because LIVE_TRADING is false.")
            return 2

        for symbol in SYMBOLS:
            print(f"\n{'=' * 72}\n{symbol}\n{'=' * 72}")
            ids, types = collect_open_sl_tp(symbol)
            print(f"Open SL/TP to cancel: {len(ids)} {ids}")
            if ids:
                cancelled = cancel_orders(ids, dry_run=not args.live, order_types=types, db=db)
                print(f"Cancelled: {cancelled}")

            plan = build_plan(db, symbol)
            print_plan(plan)

            if not plan.action.startswith("create"):
                print(f"No placement needed (action={plan.action})")
                continue

            if not args.live:
                print("[DRY RUN] would place protection")
                continue

            res = place_protection(
                db,
                plan,
                live=True,
                tp_only=False,
                cancel_sl_first=False,
            )
            print(f"Place result: placed={res.get('placed')} errors={res.get('errors')}")
            if res.get("errors"):
                failures += 1

        print(f"\nDone failures={failures}")
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
