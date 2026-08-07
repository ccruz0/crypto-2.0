#!/usr/bin/env python3
"""
Cancel known orphan SL/TP triggers from the 2026-08-03 test session.

These orders were left open after positions were closed or were dust test legs.
Run on production backend container (has exchange credentials):

  docker exec <backend-aws> python3 /repo/backend/scripts/cancel_session_orphan_triggers.py
  docker exec <backend-aws> python3 /repo/backend/scripts/cancel_session_orphan_triggers.py --live
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from scripts.cancel_duplicate_sl_tp import cancel_order_on_exchange

# Session orphans — positions closed or dust tests; do NOT add DOGE/ALGO verified pairs.
ORPHAN_ORDER_IDS: tuple[str, ...] = (
    "73817490102052401",  # APT TP (BUY)
    "73817490102052402",  # APT SL (BUY)
    "73817490102052405",  # AAVE TP (BUY)
    "73817490102052406",  # AAVE SL (BUY)
    "73817490102052380",  # BTC TP dust (SELL)
    "73817490102052381",  # BTC SL dust (SELL)
    "73817490102052388",  # ETH TP test (SELL 0.0005)
    "73817490102052389",  # ETH SL test (SELL 0.0005)
    "73817490102052382",  # ETH TP orphan (SELL 0.0788)
    "73817490102052383",  # ETH SL orphan (SELL 0.0788)
    "73817490102051028",  # SUI orphan STOP (BUY 72.3)
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cancel session orphan SL/TP triggers")
    parser.add_argument("--live", action="store_true", help="Execute cancellations")
    args = parser.parse_args()

    db = create_db_session()
    cancelled = 0
    failed = 0
    skipped = 0

    try:
        for order_id in ORPHAN_ORDER_IDS:
            db_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == order_id)
                .first()
            )
            symbol = getattr(db_order, "symbol", None) or "?"
            order_type = getattr(db_order, "order_type", None)

            if not args.live:
                print(f"[DRY RUN] would cancel {order_id} {symbol} {order_type}")
                continue

            print(f"Cancelling {order_id} ({symbol})...", end=" ", flush=True)
            try:
                result = cancel_order_on_exchange(order_id, order_type=order_type)
                if "error" in result:
                    err = str(result.get("error", ""))
                    if any(x in err.lower() for x in ("not found", "does not exist", "unknown order")):
                        print("already gone")
                        if db_order:
                            db_order.status = OrderStatusEnum.CANCELLED
                            db_order.exchange_update_time = datetime.now(timezone.utc)
                            db.commit()
                        skipped += 1
                    else:
                        print(f"FAIL: {err}")
                        failed += 1
                        db.rollback()
                else:
                    print("OK")
                    if db_order:
                        db_order.status = OrderStatusEnum.CANCELLED
                        db_order.exchange_update_time = datetime.now(timezone.utc)
                        db.commit()
                    cancelled += 1
            except Exception as exc:
                print(f"ERROR: {exc}")
                failed += 1
                db.rollback()

        print(
            f"\nSummary: cancelled={cancelled} failed={failed} already_gone={skipped} "
            f"total_targets={len(ORPHAN_ORDER_IDS)} live={args.live}"
        )
        if not args.live:
            print("Re-run with --live to execute.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
