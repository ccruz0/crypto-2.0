#!/usr/bin/env python3
"""
Cancel targeted open orders — Tier 1 (wrong direction) + Tier 2 (duplicate stacks).

Excludes Tier 2b (BTC_USD duplicate TPs). Run on prod backend container:

  python3 /repo/backend/scripts/cancel_targeted_tier12_orders.py
  python3 /repo/backend/scripts/cancel_targeted_tier12_orders.py --live
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

# Tier 1 — wrong direction vs current position (8)
TIER1_ORDER_IDS: tuple[str, ...] = (
    "73817490102046274",  # AAVE BUY (long)
    "73817490102046276",  # AAVE BUY (long)
    "73817490102052353",  # ALGO SELL (short)
    "73817490102052354",  # ALGO SELL (short)
    "73817490101967197",  # BTC BUY (long)
    "73817490101971167",  # BTC BUY (long)
    "73817490102052346",  # DOGE SELL (short)
    "73817490102052347",  # DOGE SELL (short)
)

# Tier 2 — duplicate stacks; one pair kept per symbol (49)
TIER2_ORDER_IDS: tuple[str, ...] = (
    "73817490102037080",  # AAVE
    "73817490102037081",
    "73817490102038330",
    "73817490102048268",
    "73817490102048269",
    "73817490102051140",  # ALGO
    "73817490102051571",
    "73817490102051572",
    "73817490102051609",
    "73817490102051610",
    "73817490102030618",  # BTC_USDT
    "73817490102030619",
    "73817490102030620",
    "73817490102030621",
    "73817490102049979",  # DOGE
    "73817490102049981",
    "73817490102049983",
    "73817490102049985",
    "73817490102049987",
    "73817490102049989",
    "73817490102049991",
    "73817490102030384",  # DOT
    "73817490102030634",
    "73817490102045327",
    "73817490102049845",
    "73817490102049846",
    "73817490102033404",  # ETH_USD
    "73817490102034218",
    "73817490102036270",
    "73817490101967202",  # ETH_USDT
    "73817490101967204",
    "73817490101967206",
    "73817490101972208",
    "73817490102025321",
    "73817490102025323",
    "73817490102025324",
    "73817490102032781",
    "73817490102033784",
    "73817490102037020",
    "73817490102037021",
    "73817490102037874",
    "73817490102037875",
    "73817490102038683",
    "73817490102038684",
    "73817490102038759",
    "73817490102038844",
    "73817490102038967",
    "73817490102045668",
    "73817490102049707",
)

CANCEL_ORDER_IDS: tuple[str, ...] = TIER1_ORDER_IDS + TIER2_ORDER_IDS


def main() -> None:
    parser = argparse.ArgumentParser(description="Cancel Tier 1+2 targeted orders")
    parser.add_argument("--live", action="store_true", help="Execute cancellations")
    args = parser.parse_args()

    db = create_db_session()
    cancelled = 0
    failed = 0
    skipped = 0

    try:
        for order_id in CANCEL_ORDER_IDS:
            tier = "T1" if order_id in TIER1_ORDER_IDS else "T2"
            db_order = (
                db.query(ExchangeOrder)
                .filter(ExchangeOrder.exchange_order_id == order_id)
                .first()
            )
            symbol = getattr(db_order, "symbol", None) or "?"
            order_type = getattr(db_order, "order_type", None)

            if not args.live:
                print(f"[DRY RUN] [{tier}] would cancel {order_id} {symbol} {order_type}")
                continue

            print(f"[{tier}] Cancelling {order_id} ({symbol})...", end=" ", flush=True)
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
            f"tier1={len(TIER1_ORDER_IDS)} tier2={len(TIER2_ORDER_IDS)} live={args.live}"
        )
        if not args.live:
            print("Re-run with --live to execute.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
