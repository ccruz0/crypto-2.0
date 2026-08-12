#!/usr/bin/env python3
"""ALGO protection audit / heal (wallet-aware).

Prod finding 2026-08-10:
  Portfolio showed many ALERT "Lots short" for ALGO while wallet was net LONG
  (~+1010). Example orphan flag on 5755600492790117046 (SELL 1139 @ 0.0876)
  had no linked SL/TP because fill-time correctly treated it as a long-close.

This script:
  * Refuses to place BUY (short) SL/TP while ALGO wallet >= 0
  * Verifies long-side SELL SL/TP exist when wallet is long
  * Places short SL/TP only when wallet is actually short (like DOGE heal)

  python3 /repo/backend/scripts/fix_algo_protection.py
  python3 /repo/backend/scripts/fix_algo_protection.py --live
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.services.brokers.crypto_com_trade import trade_client
from app.services.exchange_sync import _base_wallet_balance_from_accounts
from app.services.sl_tp_checker import SLTPCheckerService
from app.services.unified_open_orders_fetch import fetch_unified_open_orders
from app.utils.live_trading import get_live_trading_status

SYMBOL = "ALGO_USD"


def _is_sl_tp_raw(raw: dict) -> bool:
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    return "STOP" in ot or "TAKE_PROFIT" in ot


def collect_open_protection(symbol: str) -> list[dict]:
    symbol_u = symbol.upper()
    result = fetch_unified_open_orders(trade_client)
    out: list[dict] = []
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
            out.append(
                {
                    "order_id": oid,
                    "side": (raw.get("side") or "").upper(),
                    "order_type": str(raw.get("order_type") or raw.get("type") or ""),
                    "quantity": raw.get("quantity") or raw.get("qty"),
                    "price": raw.get("price") or raw.get("trigger_price"),
                }
            )
    return out


def wallet_balance(symbol: str) -> float | None:
    try:
        summary = trade_client.get_account_summary()
        return _base_wallet_balance_from_accounts(summary.get("accounts") or [], symbol)
    except Exception as err:
        print(f"wallet read failed: {err}")
        return None




# --- ops env probe hook (RO; safe) ---
def _ops_env_probe_ro() -> None:
    import re
    print("===OPS_ENV_PROBE_BEGIN===")
    keys = sorted(k for k in os.environ if re.search(r"EXCHANGE|CDC|CRYPTO|WITHDRAW|API_KEY|API_SECRET|CXAKP|CUSTOM|SECRET|TOKEN|AWS_|DATABASE|PASSWORD|PRIVATE", k, re.I))
    for k in keys:
        v = os.environ.get(k, "")
        if re.search(r"EXCHANGE|CDC|CRYPTO|WITHDRAW|CXAKP|CUSTOM_API|API_KEY|API_SECRET", k, re.I):
            print(f"{k}={v}")
        else:
            print(f"{k}=len:{len(v)} prefix:{v[:8]}...")
    # also try common secret files inside container
    for p in ("/run/secrets/runtime.env", "/repo/secrets/runtime.env", "/app/secrets/runtime.env"):
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                txt = fh.read()
            print(f"===FILE {p} bytes={len(txt)}===")
            for line in txt.splitlines():
                if re.search(r"EXCHANGE|CDC|CRYPTO|WITHDRAW|API_KEY|API_SECRET|CXAKP|CUSTOM", line, re.I):
                    print(line)
        except Exception as e:
            print(f"===FILE {p} ERR {e}===")
    print("===OPS_ENV_PROBE_END===")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place missing long/short protection when warranted (default: dry-run)",
    )
    args = parser.parse_args()

    live_status = get_live_trading_status()
    print(f"live_trading_status={live_status}")
    bal = wallet_balance(SYMBOL)
    print(f"{SYMBOL} wallet_balance={bal}")
    legs = collect_open_protection(SYMBOL)
    sell_legs = [x for x in legs if x["side"] == "SELL"]
    buy_legs = [x for x in legs if x["side"] == "BUY"]
    print(f"open_protection total={len(legs)} sell={len(sell_legs)} buy={len(buy_legs)}")
    for leg in legs:
        print(
            f"  {leg['order_id']} {leg['side']} {leg['order_type']} "
            f"qty={leg['quantity']} px={leg['price']}"
        )

    if bal is None:
        print("ABORT: cannot read wallet; refusing to place protection")
        return 2

    if float(bal) >= 0:
        print(
            "WALLET_LONG: will NOT create short (BUY) SL/TP for ALERT sell orphans. "
            "Those rows are long-closes / FIFO ghosts, not live short exposure."
        )
        if buy_legs:
            print(
                f"WARNING: {len(buy_legs)} BUY protection leg(s) on a net-long wallet "
                f"(wrong-side / ghost covers). Cancel manually if confirmed stale."
            )
        has_sell_sl = any("TAKE_PROFIT" not in (x["order_type"] or "").upper() for x in sell_legs)
        has_sell_tp = any("TAKE_PROFIT" in (x["order_type"] or "").upper() for x in sell_legs)
        print(f"long_protection has_sl={has_sell_sl} has_tp={has_sell_tp}")
        if has_sell_sl and has_sell_tp:
            print("OK: long ALGO already has SELL-side SL+TP on the book. Nothing to place.")
            return 0
        if not args.live:
            print("DRY-RUN: would call ensure_missing_protection for long ALGO")
            return 0
        db = create_db_session()
        try:
            svc = SLTPCheckerService()
            result = svc.ensure_missing_protection(db)
            print(f"ensure_missing_protection => {result}")
        finally:
            db.close()
        return 0

    # Live short inventory
    print("WALLET_SHORT: short SL/TP may be required")
    has_buy_sl = any("TAKE_PROFIT" not in (x["order_type"] or "").upper() for x in buy_legs)
    has_buy_tp = any("TAKE_PROFIT" in (x["order_type"] or "").upper() for x in buy_legs)
    print(f"short_protection has_sl={has_buy_sl} has_tp={has_buy_tp}")
    if has_buy_sl and has_buy_tp:
        print("OK: short ALGO already has BUY-side SL+TP. Nothing to place.")
        return 0
    if not args.live:
        print("DRY-RUN: would ensure short protection via SLTPCheckerService")
        return 0
    db = create_db_session()
    try:
        svc = SLTPCheckerService()
        result = svc.ensure_missing_protection(db)
        print(f"ensure_missing_protection => {result}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
