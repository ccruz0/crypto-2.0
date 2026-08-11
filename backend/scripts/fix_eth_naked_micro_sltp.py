#!/usr/bin/env python3
"""
One-shot: recreate SL+TP for ETH_USDT naked micro short parent.

Prod: order 5755600492671134850 — ALERT SELL 0.0052 @ 1914.8 (2026-08-05).
Fill-time never placed children; later wallet-gap recreate used ~2x qty and REJECTED.

Sizes strictly to the parent fill (0.0052). Refuses when ETH wallet is flat/long
(BUY covers would be wrong-side on a net-long book).
"""
from __future__ import annotations

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder
from app.models.watchlist import WatchlistItem
from app.services.sl_tp_price_adjust import (
    compute_strategy_sl_tp_prices,
    resolve_watchlist_percentages,
)
from app.services.sl_tp_protection import (
    get_active_protection_order,
    has_complete_sl_tp_protection,
)
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order

PARENT_ID = "5755600492671134850"
SYMBOL = "ETH_USDT"
EXPECTED_QTY = 0.0052
QTY_TOLERANCE = 1e-6


def _wallet_eth_balance(db) -> Optional[float]:
    """Signed ETH base balance from exchange account summary, else None."""
    try:
        from app.services.brokers.crypto_com_trade import trade_client

        summary = trade_client.get_account_summary() or {}
        for account in summary.get("accounts") or []:
            currency = (account.get("currency") or account.get("instrument_name") or "").upper()
            if not currency:
                continue
            base = currency.split("_")[0]
            if base != "ETH":
                continue
            if currency in ("USDT", "USD", "USDC") or base in ("USDT", "USD", "USDC"):
                continue
            raw = account.get("quantity", account.get("balance", "0"))
            try:
                return float(raw or 0)
            except (TypeError, ValueError):
                return None
    except Exception as exc:
        print(f"WARN wallet lookup failed: {exc}")
    return None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Recreate 0.0052 BUY SL/TP for ETH naked micro short parent"
    )
    parser.add_argument("--live", action="store_true", help="Place orders on exchange")
    parser.add_argument(
        "--parent-id",
        default=PARENT_ID,
        help=f"Parent exchange order id (default {PARENT_ID})",
    )
    parser.add_argument(
        "--quantity",
        type=float,
        default=EXPECTED_QTY,
        help=f"Protection qty (default {EXPECTED_QTY})",
    )
    args = parser.parse_args()

    db = create_db_session()
    created_sl = created_tp = None
    try:
        parent = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == args.parent_id)
            .first()
        )
        if not parent:
            print(f"FAIL missing parent {args.parent_id}")
            sys.exit(1)

        symbol = (parent.symbol or SYMBOL).upper()
        side_val = parent.side.value if hasattr(parent.side, "value") else str(parent.side)
        entry_side = (side_val or "SELL").upper()
        entry = float(parent.avg_price or parent.price or 0)
        fill_qty = float(parent.cumulative_quantity or parent.quantity or 0)
        qty = float(args.quantity)
        if abs(fill_qty - qty) > QTY_TOLERANCE and fill_qty > 0:
            print(
                f"WARN parent fill qty={fill_qty} != requested={qty}; "
                f"using parent fill qty"
            )
            qty = fill_qty

        if entry_side != "SELL":
            print(f"FAIL parent side={entry_side} (expected SELL short entry)")
            sys.exit(1)
        if entry <= 0 or qty <= 0:
            print(f"FAIL invalid entry/qty entry={entry} qty={qty}")
            sys.exit(1)

        wallet = _wallet_eth_balance(db)
        print(
            f"parent={args.parent_id} symbol={symbol} side={entry_side} "
            f"entry={entry} qty={qty} wallet_eth={wallet}"
        )
        if wallet is not None and wallet >= 0:
            print(
                "FAIL ETH wallet is flat/long — refusing BUY SL/TP "
                "(wrong-side covers on a net-long book)"
            )
            sys.exit(1)

        complete_before = has_complete_sl_tp_protection(db, args.parent_id)
        existing_sl = get_active_protection_order(db, args.parent_id, "STOP_LOSS")
        existing_tp = get_active_protection_order(db, args.parent_id, "TAKE_PROFIT")
        print(
            f"complete_before={complete_before} "
            f"active_sl={getattr(existing_sl, 'exchange_order_id', None)} "
            f"active_tp={getattr(existing_tp, 'exchange_order_id', None)}"
        )
        if complete_before:
            print("OK already has ACTIVE SL+TP — nothing to do")
            return

        wl = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        if wl is None and symbol.endswith("_USDT"):
            wl = (
                db.query(WatchlistItem)
                .filter(WatchlistItem.symbol == symbol.replace("_USDT", "_USD"))
                .first()
            )
        sl_pct, tp_pct, mode = resolve_watchlist_percentages(wl)
        sl_price, tp_price, meta = compute_strategy_sl_tp_prices(
            entry_side=entry_side,
            entry_price=entry,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
        )
        print(
            f"mode={mode} sl_pct={sl_pct} tp_pct={tp_pct} "
            f"sl={sl_price} tp={tp_price} meta={meta}"
        )

        if not args.live:
            print("DRY-RUN only — pass --live to place BUY SL/TP")
            return

        if existing_sl is None:
            sl_result = create_stop_loss_order(
                db=db,
                symbol=symbol,
                side=entry_side,
                sl_price=sl_price,
                quantity=qty,
                entry_price=entry,
                parent_order_id=args.parent_id,
                dry_run=False,
                source="manual",
                sl_percentage=sl_pct,
            )
            created_sl = sl_result.get("order_id")
            if created_sl:
                print(f"SL created {created_sl} @ {sl_price} qty={qty}")
            else:
                print(f"SL FAIL: {sl_result.get('error') or sl_result}")
        else:
            print(f"SL already active {existing_sl.exchange_order_id}")

        if existing_tp is None:
            tp_result = create_take_profit_order(
                db=db,
                symbol=symbol,
                side=entry_side,
                tp_price=tp_price,
                quantity=qty,
                entry_price=entry,
                parent_order_id=args.parent_id,
                dry_run=False,
                source="manual",
            )
            created_tp = tp_result.get("order_id")
            if created_tp:
                print(f"TP created {created_tp} @ {tp_price} qty={qty}")
            else:
                print(f"TP FAIL: {tp_result.get('error') or tp_result}")
        else:
            print(f"TP already active {existing_tp.exchange_order_id}")

        complete_after = has_complete_sl_tp_protection(db, args.parent_id)
        print(
            f"=== SUMMARY created_sl={created_sl} created_tp={created_tp} "
            f"protection_complete={complete_after} ==="
        )
        if not complete_after:
            sys.exit(2)
    finally:
        db.close()


if __name__ == "__main__":
    main()
