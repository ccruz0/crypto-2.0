#!/usr/bin/env python3
"""
Idempotent backfill of BTC historical BUY fills into ``exchange_orders``.

WHY
---
The ~2.4949 BTC spot position was accumulated by BUYs placed directly on
Crypto.com (some as MARGIN fills). Those fills are NOT returned by
``private/get-order-history`` (returns 0 for BTC) and are only partially
returned by ``private/get-trades`` (which silently omits the recent
margin fills for this account). Because no FILLED BUY rows existed, the
cost-basis engine (``app.services.expected_take_profit``) reported
``cost_basis_unknown=True`` and the Portfolio P&L / Expected-TP showed "—".

SOURCE OF TRUTH
---------------
The authoritative source is the trading ledger ``private/get-transactions``
(journal_type=TRADING). Walking that ledger backward from today until the
running BTC balance (starting from the held 2.49490132 BTC) reaches ~0
identifies the exact set of BUY orders that comprise the current position.

Result of that reconstruction (see docs / chat investigation 2026-07-07):
  5 BUY orders 2026-05-23 -> 2026-06-29 totalling 2.47463 BTC (99.19% of the
  held 2.49490132 BTC); weighted-average entry price = 63,166.59 USD. The
  residual ~0.0203 BTC (0.8%) is a pre-existing opening lot whose cost basis
  predates the cleanly-retrievable ledger window and is intentionally left out
  (it shows as a small uncovered qty, not a fabricated price).

SAFETY
------
- Rows are written as FILLED BUY with ``trade_signal_id=NULL``,
  ``parent_order_id=NULL``, ``order_role=NULL`` => classified as EXTERNAL
  (reconciled) orders. Combined with their fill age (weeks old), the
  exchange-sync gate returns ``external_order_old_fill`` and will NOT
  auto-create SL/TP or place any exchange order.
- ``execution_notified_at`` is set so no "ORDER EXECUTED" Telegram is sent.
- Upsert dedupes on ``exchange_order_id`` (unique) => safe to re-run.
- THIS SCRIPT ONLY WRITES TO THE DB. It never touches the exchange.

USAGE
-----
  # from backend/ inside the backend container
  PYTHONPATH=. python scripts/backfill_btc_trade_history.py            # dry-run
  PYTHONPATH=. python scripts/backfill_btc_trade_history.py --write     # apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Reconstructed from the Crypto.com TRADING ledger (get-transactions).
# Each entry aggregates all fills of one exchange order_id.
BTC_BUY_ORDERS = [
    {"exchange_order_id": "5755600488945374736", "symbol": "BTC_USDT", "quantity": "0.30000000", "avg_price": "75100.00000000", "cumulative_value": "22530.00000000", "exchange_create_time": "2026-05-23T07:46:28+00:00"},
    {"exchange_order_id": "5755600489289088548", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "71100.00000000", "cumulative_value": "21330.00000000", "exchange_create_time": "2026-06-01T15:23:43+00:00"},
    {"exchange_order_id": "5755600489717738162", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "63244.37000000", "cumulative_value": "18973.31100000", "exchange_create_time": "2026-06-04T17:17:21+00:00"},
    {"exchange_order_id": "5755600489811716124", "symbol": "BTC_USD",  "quantity": "0.30000000", "avg_price": "60500.00000000", "cumulative_value": "18150.00000000", "exchange_create_time": "2026-06-24T15:44:30+00:00"},
    {"exchange_order_id": "5755600491091887888", "symbol": "BTC_USD",  "quantity": "1.27463000", "avg_price": "59100.00000000", "cumulative_value": "75330.63300000", "exchange_create_time": "2026-06-29T15:05:15+00:00"},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill BTC historical BUY fills into exchange_orders")
    parser.add_argument("--write", action="store_true", help="Actually write rows (default: dry-run)")
    args = parser.parse_args()
    dry_run = not args.write

    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

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
            cum_val = Decimal(o["cumulative_value"])
            ct = datetime.fromisoformat(o["exchange_create_time"])

            existing = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == oid).first()
            if existing is None:
                print(f"  + INSERT {oid} {o['symbol']} BUY FILLED qty={qty} @ {avg_price}")
                inserted += 1
                if not dry_run:
                    db.add(ExchangeOrder(
                        exchange_order_id=oid,
                        client_oid=None,
                        symbol=o["symbol"],
                        side=OrderSideEnum.BUY,
                        order_type="MARKET",
                        status=OrderStatusEnum.FILLED,
                        price=avg_price,
                        quantity=qty,
                        cumulative_quantity=qty,
                        cumulative_value=cum_val,
                        avg_price=avg_price,
                        exchange_create_time=ct,
                        exchange_update_time=ct,
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
                # Only fix rows that are missing the cost-basis fields; never clobber
                # a genuine bot order (trade_signal_id/parent set).
                needs = (
                    existing.status != OrderStatusEnum.FILLED
                    or existing.side != OrderSideEnum.BUY
                    or not existing.avg_price
                    or Decimal(str(existing.avg_price)) <= 0
                )
                if needs and existing.trade_signal_id is None and existing.parent_order_id is None:
                    print(f"  ~ UPDATE {oid} -> FILLED BUY qty={qty} @ {avg_price}")
                    updated += 1
                    if not dry_run:
                        existing.side = OrderSideEnum.BUY
                        existing.status = OrderStatusEnum.FILLED
                        existing.quantity = qty
                        existing.cumulative_quantity = qty
                        existing.cumulative_value = cum_val
                        existing.avg_price = avg_price
                        existing.price = avg_price
                        existing.exchange_create_time = ct
                        existing.exchange_update_time = ct
                        if existing.imported_at is None:
                            existing.imported_at = now
                else:
                    print(f"  = UNCHANGED {oid} (already present)")
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
