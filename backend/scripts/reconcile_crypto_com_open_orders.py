#!/usr/bin/env python3
"""
Read-only three-way reconciliation: Crypto.com live open orders vs DB vs dashboard cache.

No orders placed. No DB writes. No write gates enabled.

Usage (on EC2 / backend-aws container):
  python /app/scripts/reconcile_crypto_com_open_orders.py
  python /app/scripts/reconcile_crypto_com_open_orders.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.jarvis.execution_tools.reconcile_crypto_com_open_orders import (
    reconcile_crypto_com_open_orders,
)


def _print_section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _print_orders(label: str, orders: list[dict]) -> None:
    print(f"\n{label}: {len(orders)}")
    if not orders:
        print("  (none)")
        return
    for order in orders:
        trigger = " [trigger]" if order.get("is_trigger") else ""
        print(
            f"  - {order.get('order_id')} | {order.get('symbol')} | "
            f"{order.get('side')} | {order.get('status')} | "
            f"{order.get('order_type')}{trigger}"
        )


def _print_reconciliation(rec: dict) -> None:
    print(f"\n--- {rec.get('comparison')} ---")
    print(
        f"  left={rec.get('left_count')} right={rec.get('right_count')} "
        f"matched={rec.get('matched_count')}"
    )
    for key, value in rec.items():
        if not key.startswith("missing_in_"):
            continue
        if not value:
            continue
        print(f"\n  {key} ({len(value)}):")
        for order in value:
            print(
                f"    - {order.get('order_id')} | {order.get('symbol')} | "
                f"{order.get('status')} | source={order.get('source')}"
            )
    if rec.get("status_mismatches"):
        print(f"\n  status_mismatches ({len(rec['status_mismatches'])}):")
        for item in rec["status_mismatches"]:
            print(f"    - {item}")
    if rec.get("symbol_mismatches"):
        print(f"\n  symbol_mismatches ({len(rec['symbol_mismatches'])}):")
        for item in rec["symbol_mismatches"]:
            print(f"    - {item}")
    if not any(
        rec.get(k)
        for k in rec
        if k.startswith("missing_in_") or k.endswith("_mismatches")
    ):
        print("  No discrepancies.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Crypto.com open orders reconciliation"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit full JSON result instead of human-readable report",
    )
    args = parser.parse_args()

    result = reconcile_crypto_com_open_orders()

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1

    _print_section("CRYPTO.COM OPEN ORDERS RECONCILIATION (READ-ONLY)")
    print(f"Checked at: {result.get('checked_at')}")
    print(f"Conclusion: {result.get('conclusion')}")
    print(f"Root cause: {result.get('root_cause')}")
    print(f"Next action: {result.get('next_action')}")

    counts = result.get("counts") or {}
    _print_section("COUNTS")
    print(f"  Exchange live:     {counts.get('exchange_live', 0)}")
    print(f"  Database (open):   {counts.get('database_open', 0)}")
    print(f"  Dashboard cache:   {counts.get('dashboard_cache', 0)}")

    sources = result.get("sources") or {}
    _print_section("SOURCE METADATA")
    for name, meta in sources.items():
        print(f"  {name}: {meta}")

    _print_section("ORDERS BY SOURCE")
    _print_orders("Exchange live", result.get("exchange_orders") or [])
    _print_orders("Database open-status", result.get("database_orders") or [])
    _print_orders("Dashboard cache", result.get("dashboard_orders") or [])

    _print_section("RECONCILIATION")
    for rec in result.get("reconciliations") or []:
        _print_reconciliation(rec)

    print("\n" + "=" * 72)
    print("Done (read-only; no writes performed).")
    print("=" * 72)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
