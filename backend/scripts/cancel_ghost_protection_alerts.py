#!/usr/bin/env python3
"""
Cancel ghost/orphan protection legs flagged by dashboard Expected TP banner.

Uses the same rules as ``compute_protection_leg_stats``:
  - wrong_side_cover_on_long  (BUY SL/TP while wallet > 0)
  - wrong_side_cover_on_short (SELL SL/TP while wallet < 0)
  - qty_exceeds_wallet / no_wallet

Default bases match the 2026-08-11 banner: ALGO×5, SUI×5, APT×4, AAVE×2.

  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py
  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py --live
  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py --live --bases ALGO,SUI
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.dashboard_position_counts import compute_protection_leg_stats
from app.services.open_orders_resolver import resolve_open_orders
from scripts.cancel_duplicate_sl_tp import cancel_order_on_exchange

DEFAULT_BASES = ("ALGO", "SUI", "APT", "AAVE")


def _balances_from_account_summary() -> List[dict]:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cancel ghost/orphan SL/TP legs vs wallet (dashboard banner)"
    )
    parser.add_argument("--live", action="store_true", help="Cancel on exchange")
    parser.add_argument(
        "--bases",
        default=",".join(DEFAULT_BASES),
        help=f"Comma-separated base currencies (default {','.join(DEFAULT_BASES)})",
    )
    parser.add_argument(
        "--all-bases",
        action="store_true",
        help="Cancel ghosts for every base (ignore --bases)",
    )
    args = parser.parse_args()

    bases: Optional[Set[str]] = None
    if not args.all_bases:
        bases = {b.strip().upper() for b in args.bases.split(",") if b.strip()}

    db = create_db_session()
    cancelled = 0
    failed = 0
    skipped = 0
    try:
        balances = _balances_from_account_summary()
        resolved = resolve_open_orders(db)
        orders = list(resolved.orders or [])
        _tp, _prot, alerts = compute_protection_leg_stats(orders, balances)

        if bases is not None:
            alerts = [a for a in alerts if (a.get("base") or "").upper() in bases]

        print(
            f"mode={'LIVE' if args.live else 'DRY-RUN'} "
            f"open_orders={len(orders)} ghost_alerts={len(alerts)} "
            f"bases={sorted(bases) if bases else 'ALL'}"
        )
        if not alerts:
            print("OK no matching ghost/orphan protection legs")
            return 0

        by_base: Dict[str, int] = {}
        for a in alerts:
            b = (a.get("base") or "?").upper()
            by_base[b] = by_base.get(b, 0) + 1
        print("by_base=" + ",".join(f"{k}x{v}" for k, v in sorted(by_base.items())))

        for alert in alerts:
            oid = (alert.get("order_id") or "").strip()
            sym = alert.get("symbol")
            reason = alert.get("reason")
            side = alert.get("side")
            qty = alert.get("quantity")
            wallet = alert.get("wallet_qty")
            ot = alert.get("order_type")
            print(
                f"{'CANCEL' if args.live else 'DRY'} {oid} {sym} {side} {ot} "
                f"qty={qty} wallet={wallet} reason={reason}"
            )
            if not oid:
                print("  SKIP missing order_id")
                skipped += 1
                continue
            if not args.live:
                continue
            try:
                result = cancel_order_on_exchange(oid, order_type=ot)
                if isinstance(result, dict) and result.get("error"):
                    print(f"  FAIL: {result.get('error')}")
                    failed += 1
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
                cancelled += 1
                print("  OK")
            except Exception as exc:
                print(f"  FAIL: {exc}")
                failed += 1
                db.rollback()

        print(
            f"=== SUMMARY cancelled={cancelled} failed={failed} "
            f"skipped={skipped} dry={not args.live} ==="
        )
        if args.live and failed:
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
