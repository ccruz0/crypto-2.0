#!/usr/bin/env python3
"""
Idempotent backfill / correction of BTC historical BUY fills into ``exchange_orders``.

WHY
---
The ~2.4949 BTC spot position was accumulated by LIMIT BUYs placed directly on
Crypto.com. Because no FILLED BUY rows existed, the cost-basis engine
(``app.services.expected_take_profit``) reported ``cost_basis_unknown=True`` and
the Portfolio P&L / Expected-TP showed "—".

SOURCE OF TRUTH (corrected 2026-07-08)
--------------------------------------
An earlier version of this script reconstructed the fills by NETTING the
``private/get-transactions`` TRADING ledger. That netting produced INCORRECT
quantities / prices / dates (e.g. the 2026-06-29 fill came out as 1.27463 BTC
instead of the real 1.30000 BTC, and the 0.30 @ 60,500 fill was dated to its
later modification time 2026-06-24 instead of its real 2026-06-05 fill).

``private/get-order-history`` returns 0 rows for this account (spot, margin,
get-trades and empty-param fallbacks all return empty), so the AUTHORITATIVE
per-order source is ``private/get-order-detail`` queried by the real exchange
``order_id``. Those order_ids are the OTOCO parents of the still-active
take-profit orders and match the operator's Crypto.com app "Order history".
Each row below was verified field-by-field against ``get-order-detail``:

  order_id             qty      avg_fill   limit    create_time (UTC)
  5755600488945374736  0.30000  75100.00   75100    2026-05-20 15:52:10  (BTC_USDT)
  5755600489289088548  0.30000  71100.00   71100    2026-05-28 05:03:14
  5755600489717738162  0.30000  63244.37   63300    2026-06-04 17:17:21
  5755600489811716124  0.30000  60500.00   60500    2026-06-05 16:22:08
  5755600491091887888  1.30000  59100.00   59100    2026-06-29 14:53:44

Sum = 2.50000 BTC vs 2.49490132 held; the ~0.0051 BTC residual is BTC-denominated
trading fees deducted from the fills (small, expected, NOT fabricated).
Weighted-average entry (executed avg-fill basis) = 63,125.32 USD.

NOTE on the 2026-06-04 order: it was a LIMIT @ 63,300 that FILLED at an average
of 63,244.37 (better than limit). Cost basis uses the executed average
(63,244.37), which is the real USD spent -- NOT an error.

``exchange_create_time`` is set to the order-placement time (``create_time``),
which is what the Crypto.com app "Order history" Time column shows (verified:
the 2026-06-05 order shows 06-05 in the app even though its update_time is
06-24). ``exchange_update_time`` keeps the exchange ``update_time``.

SAFETY
------
- Rows are written as FILLED BUY with ``trade_signal_id=NULL``,
  ``parent_order_id=NULL``, ``order_role=NULL`` => classified as EXTERNAL
  (reconciled) orders. Combined with their fill age (weeks old), the
  exchange-sync gate returns ``external_order_old_fill`` and will NOT
  auto-create SL/TP or place any exchange order.
- ``execution_notified_at`` is set so no "ORDER EXECUTED" Telegram is sent.
- Upsert dedupes on ``exchange_order_id`` (unique) and only reconciles rows that
  are EXTERNAL (``trade_signal_id`` and ``parent_order_id`` both NULL) => safe to
  re-run and will never clobber a genuine bot order.
- THIS SCRIPT ONLY WRITES TO THE DB. It never touches the exchange for writes.
  With ``--verify-live`` it performs READ-ONLY ``get-order-detail`` calls to
  re-confirm the embedded snapshot before writing.

USAGE
-----
  # from backend/ inside the backend container
  PYTHONPATH=. python scripts/backfill_btc_trade_history.py                 # dry-run
  PYTHONPATH=. python scripts/backfill_btc_trade_history.py --verify-live    # dry-run + live re-verify
  PYTHONPATH=. python scripts/backfill_btc_trade_history.py --write          # apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Authoritative filled BTC BUY orders, verified via private/get-order-detail
# (order_id -> exact qty / executed avg_price / limit price / cumulative_value /
# create_time / update_time). See module docstring for provenance.
BTC_BUY_ORDERS = [
    {"exchange_order_id": "5755600488945374736", "symbol": "BTC_USDT", "quantity": "0.30000000", "avg_price": "75100.00000000", "limit_price": "75100.00000000", "cumulative_value": "22530.00000000", "exchange_create_time": "2026-05-20T15:52:10.174000+00:00", "exchange_update_time": "2026-05-23T07:46:29.076000+00:00"},
    {"exchange_order_id": "5755600489289088548", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "71100.00000000", "limit_price": "71100.00000000", "cumulative_value": "21330.00000000", "exchange_create_time": "2026-05-28T05:03:14.328000+00:00", "exchange_update_time": "2026-06-01T15:23:44.064000+00:00"},
    {"exchange_order_id": "5755600489717738162", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "63244.37000000", "limit_price": "63300.00000000", "cumulative_value": "18973.31100000", "exchange_create_time": "2026-06-04T17:17:21.461000+00:00", "exchange_update_time": "2026-06-04T17:17:21.461000+00:00"},
    {"exchange_order_id": "5755600489811716124", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "60500.00000000", "limit_price": "60500.00000000", "cumulative_value": "18150.00000000", "exchange_create_time": "2026-06-05T16:22:08.944000+00:00", "exchange_update_time": "2026-06-24T15:44:30.206000+00:00"},
    {"exchange_order_id": "5755600491091887888", "symbol": "BTC_USD",  "quantity": "1.30000000", "avg_price": "59100.00000000", "limit_price": "59100.00000000", "cumulative_value": "76830.00000000", "exchange_create_time": "2026-06-29T14:53:44.208000+00:00", "exchange_update_time": "2026-06-29T15:05:15.156000+00:00"},
]


def _verify_live() -> None:
    """READ-ONLY: re-confirm each embedded row against private/get-order-detail."""
    from app.services.brokers.crypto_com_trade import trade_client

    print("Live re-verification via get-order-detail (read-only):")
    all_ok = True
    for o in BTC_BUY_ORDERS:
        oid = o["exchange_order_id"]
        raw = trade_client.get_order_detail(oid)
        res = raw.get("result") if isinstance(raw, dict) else None
        if isinstance(res, dict) and "order_info" in res:
            res = res["order_info"]
        if not isinstance(res, dict):
            print(f"  ! {oid}: could not fetch order detail (skipping compare)")
            continue
        qty_ok = Decimal(str(res.get("cumulative_quantity") or res.get("quantity") or 0)) == Decimal(o["quantity"])
        avg_ok = Decimal(str(res.get("avg_price") or 0)) == Decimal(o["avg_price"])
        status_ok = str(res.get("status")).upper() == "FILLED"
        side_ok = str(res.get("side")).upper() == "BUY"
        ok = qty_ok and avg_ok and status_ok and side_ok
        all_ok = all_ok and ok
        print(f"  {'OK ' if ok else '!! '}{oid} qty={res.get('cumulative_quantity')} avg={res.get('avg_price')} status={res.get('status')} side={res.get('side')}")
    print("Live verification:", "ALL MATCH" if all_ok else "MISMATCH - review before writing", "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill/correct BTC historical BUY fills into exchange_orders")
    parser.add_argument("--write", action="store_true", help="Actually write rows (default: dry-run)")
    parser.add_argument("--verify-live", action="store_true", help="Read-only re-verify embedded rows against get-order-detail first")
    args = parser.parse_args()
    dry_run = not args.write

    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

    if args.verify_live:
        _verify_live()

    now = datetime.now(timezone.utc)
    total_qty = sum(Decimal(o["quantity"]) for o in BTC_BUY_ORDERS)
    total_val = sum(Decimal(o["cumulative_value"]) for o in BTC_BUY_ORDERS)
    wavg = (total_val / total_qty) if total_qty > 0 else Decimal("0")
    print(f"BTC backfill: {len(BTC_BUY_ORDERS)} BUY orders, total_qty={total_qty}, weighted_avg={wavg:.2f}")
    print(f"Mode: {'DRY-RUN (no writes)' if dry_run else 'WRITE'}\n")

    db = SessionLocal()
    inserted = updated = unchanged = 0
    try:
        for o in BTC_BUY_ORDERS:
            oid = o["exchange_order_id"]
            qty = Decimal(o["quantity"])
            avg_price = Decimal(o["avg_price"])
            limit_price = Decimal(o.get("limit_price") or o["avg_price"])
            cum_val = Decimal(o["cumulative_value"])
            ct = datetime.fromisoformat(o["exchange_create_time"])
            ut = datetime.fromisoformat(o["exchange_update_time"])
            # Cost basis must reflect the executed average. The engine reads
            # ``price or avg_price`` (FIFO lots) and ``avg_price or price``
            # (summary); keep both equal to the executed avg so cost basis is
            # consistent everywhere. (The limit price is kept in the docstring.)
            stored_price = avg_price

            existing = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == oid).first()
            if existing is None:
                print(f"  + INSERT {oid} {o['symbol']} BUY FILLED qty={qty} @ {avg_price} (limit {limit_price}) ct={ct.date()}")
                inserted += 1
                if not dry_run:
                    db.add(ExchangeOrder(
                        exchange_order_id=oid,
                        client_oid=None,
                        symbol=o["symbol"],
                        side=OrderSideEnum.BUY,
                        order_type="LIMIT",
                        status=OrderStatusEnum.FILLED,
                        price=stored_price,
                        quantity=qty,
                        cumulative_quantity=qty,
                        cumulative_value=cum_val,
                        avg_price=avg_price,
                        exchange_create_time=ct,
                        exchange_update_time=ut,
                        imported_at=now,
                        # External/reconciled: no bot linkage => no SL/TP auto-creation.
                        trade_signal_id=None,
                        parent_order_id=None,
                        oco_group_id=None,
                        order_role=None,
                        # Suppress any "ORDER EXECUTED" Telegram for this historical fill.
                        execution_notified_at=now,
                    ))
            else:
                # Only reconcile EXTERNAL rows (no bot linkage). Never clobber a
                # genuine bot order (trade_signal_id / parent_order_id set).
                is_external = existing.trade_signal_id is None and existing.parent_order_id is None
                current = (
                    existing.side, existing.status,
                    Decimal(str(existing.quantity or 0)), Decimal(str(existing.cumulative_quantity or 0)),
                    Decimal(str(existing.cumulative_value or 0)), Decimal(str(existing.avg_price or 0)),
                    Decimal(str(existing.price or 0)),
                    existing.exchange_create_time, existing.exchange_update_time,
                )
                target = (
                    OrderSideEnum.BUY, OrderStatusEnum.FILLED,
                    qty, qty, cum_val, avg_price, stored_price, ct, ut,
                )
                if is_external and current != target:
                    print(f"  ~ UPDATE {oid} -> FILLED BUY qty={qty} @ {avg_price} (limit {limit_price}) ct={ct.date()}")
                    updated += 1
                    if not dry_run:
                        existing.side = OrderSideEnum.BUY
                        existing.status = OrderStatusEnum.FILLED
                        existing.order_type = existing.order_type or "LIMIT"
                        existing.quantity = qty
                        existing.cumulative_quantity = qty
                        existing.cumulative_value = cum_val
                        existing.avg_price = avg_price
                        existing.price = stored_price
                        existing.exchange_create_time = ct
                        existing.exchange_update_time = ut
                        if existing.imported_at is None:
                            existing.imported_at = now
                        if existing.execution_notified_at is None:
                            existing.execution_notified_at = now
                else:
                    print(f"  = UNCHANGED {oid} ({'already correct' if is_external else 'bot order, not touched'})")
                    unchanged += 1

        if not dry_run:
            db.commit()
            print("\nCommitted.")
        else:
            db.rollback()
            print("\nDry-run only. Re-run with --write to apply.")
        print(f"Summary: inserted={inserted} updated={updated} unchanged={unchanged}")
    except Exception as e:  # pragma: no cover
        db.rollback()
        print(f"ERROR: {e}")
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
