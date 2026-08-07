#!/usr/bin/env python3
"""Cancel known DOT_USD ghost STOP_LIMIT legs (qty ≫ wallet).

Audit 2026-08-07:
  wallet DOT ≈ 0.00086
  open STOP_LIMIT BUY:
    73817490102053590 qty=1.29
    73817490102053328 qty=48.67

Default is dry-run. Pass --live to cancel on Crypto.com.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.unified_open_orders_fetch import fetch_unified_open_orders
from app.services.brokers.crypto_com_trade import trade_client
from scripts.cancel_duplicate_sl_tp import cancel_order_on_exchange

TARGETS: Dict[str, Dict[str, Any]] = {
    "73817490102053590": {
        "symbol": "DOT_USD",
        "side": "BUY",
        "order_type_substr": "STOP",
        "expected_qty": 1.29,
    },
    "73817490102053328": {
        "symbol": "DOT_USD",
        "side": "BUY",
        "order_type_substr": "STOP",
        "expected_qty": 48.67,
    },
}


def _collect_raw_orders() -> List[dict]:
    result = fetch_unified_open_orders(trade_client)
    out: List[dict] = []
    for bucket in ("advanced_raw", "trigger_raw", "regular_raw"):
        out.extend(result.get(bucket) or [])
    return out


def _find_on_exchange(order_id: str, raws: List[dict]) -> Optional[dict]:
    for raw in raws:
        oid = str(raw.get("order_id") or raw.get("exchange_order_id") or "")
        if oid == order_id:
            return raw
    return None


def _matches_target(order_id: str, raw: dict) -> tuple[bool, str]:
    spec = TARGETS[order_id]
    sym = (raw.get("instrument_name") or raw.get("symbol") or "").upper()
    side = (raw.get("side") or "").upper()
    ot = (raw.get("order_type") or raw.get("type") or "").upper()
    try:
        qty = float(raw.get("quantity") or raw.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    if sym != spec["symbol"]:
        return False, f"symbol={sym} expected={spec['symbol']}"
    if side and side != spec["side"]:
        return False, f"side={side} expected={spec['side']}"
    if spec["order_type_substr"] not in ot:
        return False, f"order_type={ot} expected contains {spec['order_type_substr']}"
    expected = float(spec["expected_qty"])
    if abs(qty - expected) > max(0.01, expected * 0.02):
        return False, f"qty={qty} expected≈{expected}"
    return True, f"{sym} {side} {ot} qty={qty}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cancel DOT ghost STOP_LIMIT legs")
    parser.add_argument("--live", action="store_true", help="Execute cancels on exchange")
    args = parser.parse_args()

    print(f"mode={'LIVE' if args.live else 'DRY-RUN'} targets={list(TARGETS)}")
    raws = _collect_raw_orders()
    print(f"unified_open_raw_count={len(raws)}")

    db = create_db_session()
    cancelled = 0
    failed = 0
    skipped = 0
    try:
        for oid, spec in TARGETS.items():
            raw = _find_on_exchange(oid, raws)
            if not raw:
                print(f"SKIP {oid}: not found on exchange (already gone?)")
                skipped += 1
                continue
            ok, detail = _matches_target(oid, raw)
            if not ok:
                print(f"ABORT {oid}: safety mismatch ({detail})")
                failed += 1
                continue
            print(f"{'CANCEL' if args.live else 'DRY'} {oid}: {detail}")
            if not args.live:
                continue
            try:
                result = cancel_order_on_exchange(
                    oid, order_type=raw.get("order_type") or raw.get("type")
                )
                if isinstance(result, dict) and result.get("error"):
                    print(f"  FAIL: {result.get('error')}")
                    failed += 1
                    continue
                db_order = (
                    db.query(ExchangeOrder)
                    .filter(ExchangeOrder.exchange_order_id == oid)
                    .first()
                )
                if db_order is not None:
                    db_order.status = OrderStatusEnum.CANCELLED
                    db_order.exchange_update_time = datetime.now(timezone.utc)
                    db.commit()
                print("  OK")
                cancelled += 1
            except Exception as exc:
                print(f"  ERROR: {exc}")
                failed += 1
                db.rollback()

        print(
            f"summary cancelled={cancelled} failed={failed} skipped={skipped} "
            f"dry_run={not args.live}"
        )
        if failed:
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
