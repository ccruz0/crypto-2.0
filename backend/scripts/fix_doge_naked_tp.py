#!/usr/bin/env python3
"""Fix DOGE_USD naked short: recreate full-wallet SL + TP.

Prod audit 2026-08-07 / follow-up:
  wallet short, covered_qty=0, only STOP_LIMIT SLs on exchange (no TP).

run=1 (PR #392): cancelled SLs then wallet_empty_short (available=0 on loans).
run=2 (PR #394): wallet gate fixed; TP 0.0692 string-formatted to "0.07"
  via price_decimals default=2 → INVALID_TRIGGER_PRICE (above market ~0.0699).
run=3: keep true decimals + force market-relative short TP/SL before place.

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


def _force_market_relative_short_levels(plan) -> None:
    """Overwrite plan TP/SL from live mark so stale abs / coarse round cannot go above market."""
    from app.utils.sl_trigger_guard import (
        compute_market_relative_sl,
        compute_market_relative_tp,
        ensure_tp_clear_of_market_after_tick,
        ensure_valid_sl_trigger,
        ensure_valid_tp_trigger,
        fetch_ticker_prices,
        reference_price_for_trigger,
    )

    ticker = fetch_ticker_prices(SYMBOL)
    if not ticker:
        raise RuntimeError("REFUSING: no live ticker for DOGE_USD — cannot size short TP/SL")

    wl = getattr(plan, "watchlist", None)
    tp_pct = abs(float(wl.tp_percentage)) if wl and wl.tp_percentage else 1.0
    sl_pct = abs(float(wl.sl_percentage)) if wl and wl.sl_percentage else 10.0
    # Keep a usable buffer below mark even when watchlist TP% is very tight (1%).
    tp_pct = max(tp_pct, 1.0)

    ref_tp = reference_price_for_trigger("SELL", is_tp=True, ticker=ticker)
    ref_sl = reference_price_for_trigger("SELL", is_tp=False, ticker=ticker)
    if not ref_tp or ref_tp <= 0:
        raise RuntimeError(f"REFUSING: invalid TP reference price {ref_tp!r}")

    tp_price = compute_market_relative_tp("SELL", float(ref_tp), tp_pct)
    sl_price = compute_market_relative_sl("SELL", float(ref_sl or ref_tp), sl_pct)
    entry_px = None
    if getattr(plan, "entry", None) is not None and plan.entry.price:
        entry_px = float(plan.entry.price)
    tp_price, _ = ensure_valid_tp_trigger(
        entry_side="SELL",
        tp_price=float(tp_price),
        last_price=float(ref_tp),
        tp_percentage=tp_pct,
        entry_price=entry_px,
        ticker=ticker,
    )
    sl_price, _ = ensure_valid_sl_trigger(
        entry_side="SELL",
        sl_price=float(sl_price),
        last_price=float(ref_sl or ref_tp),
        sl_percentage=sl_pct,
        entry_price=entry_px,
        ticker=ticker,
    )
    try:
        tick_raw = (trade_client._get_instrument_metadata(SYMBOL) or {}).get("price_tick_size")
        tick_f = float(tick_raw) if tick_raw not in (None, "") else None
    except (TypeError, ValueError):
        tick_f = None
    tp_price = ensure_tp_clear_of_market_after_tick(
        entry_side="SELL",
        tp_price=float(tp_price),
        market_price=float(ref_tp),
        tick_size=tick_f,
    )
    # DOGE tick is 1e-6; keep 6 dp so place path cannot coerce via coarse formats.
    plan.tp_price = round(float(tp_price), 6)
    plan.sl_price = round(float(sl_price), 6)
    print(
        f"Market-relative short levels: ref_tp={ref_tp} ref_sl={ref_sl} "
        f"tp_pct={tp_pct} sl_pct={sl_pct} -> tp={plan.tp_price} sl={plan.sl_price}"
    )
    if float(plan.tp_price) >= float(ref_tp):
        raise RuntimeError(
            f"REFUSING: short TP {plan.tp_price} not below market ref {ref_tp}"
        )


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
            if args.live:
                tp, sl = verify_after()
                print(f"After verify: tp={tp} sl={sl}")
                return 0 if tp > 0 and sl > 0 else 1
            return 0

        try:
            _force_market_relative_short_levels(plan)
        except Exception as exc:
            print(f"REFUSING market-relative levels: {exc}")
            return 4
        print_plan(plan)

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
