#!/usr/bin/env python3
"""
Diagnose Open vs Trigger orders from Crypto.com API.

Run on EC2 (backend container) to confirm what the API returns:
  - Open orders: count from private/get-open-orders
  - Trigger orders: count from private/get-trigger-orders

Also prints sample order keys (e.g. product_type, spot_margin) to detect
Cross/margin vs spot filtering.

Usage (on EC2):
  cd /home/ubuntu/automated-trading-platform
  sudo docker compose --profile aws exec backend-aws python /app/scripts/diagnose_open_vs_trigger_orders.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.core.crypto_com_guardrail import is_local_execution_context, LOCAL_SKIP_PRIVATE_MESSAGE
except ImportError:
    def is_local_execution_context() -> bool:
        return (os.getenv("EXECUTION_CONTEXT", "LOCAL") or "LOCAL").strip().upper() == "LOCAL"
    LOCAL_SKIP_PRIVATE_MESSAGE = "LOCAL mode: private Crypto.com endpoints are AWS-only"


def main() -> int:
    print("=" * 60)
    print("OPEN ORDERS vs TRIGGER ORDERS DIAGNOSTIC")
    print("=" * 60)

    if is_local_execution_context():
        print("\n" + LOCAL_SKIP_PRIVATE_MESSAGE)
        print("Run this script on EC2 (inside backend-aws container) to see real API counts.")
        print("=" * 60)
        return 0

    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    if not client.api_key or not client.api_secret:
        print("\n❌ API credentials not configured (EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET)")
        return 1

    open_count = 0
    trigger_count = 0
    open_sample = None
    trigger_sample = None
    open_error = None
    trigger_error = None

    # 1) Open orders (regular limit/market open orders)
    print("\n1. private/get-open-orders")
    try:
        resp = client.get_open_orders(page=0, page_size=200)
        if resp.get("error"):
            open_error = resp.get("error")
            print(f"   Error: {open_error}")
        else:
            data = resp.get("data") or []
            open_count = len(data) if isinstance(data, list) else 0
            if data and isinstance(data, list):
                open_sample = data[0] if isinstance(data[0], dict) else None
            print(f"   Open orders: {open_count}")
    except Exception as e:
        open_error = str(e)
        print(f"   Exception: {e}")

    # 2) Trigger orders (TP/SL conditional orders)
    print("\n2. private/get-trigger-orders")
    try:
        resp = client.get_trigger_orders(page=0, page_size=200)
        if resp.get("error"):
            trigger_error = resp.get("error")
            print(f"   Error: {trigger_error}")
        else:
            data = resp.get("data") or []
            trigger_count = len(data) if isinstance(data, list) else 0
            if data and isinstance(data, list):
                trigger_sample = data[0] if isinstance(data[0], dict) else None
            print(f"   Trigger orders: {trigger_count}")
    except Exception as e:
        trigger_error = str(e)
        print(f"   Exception: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY (what the API returned)")
    print("=" * 60)
    print(f"   Open orders:   {open_count}")
    print(f"   Trigger orders: {trigger_count}")
    print(f"   Total (both):  {open_count + trigger_count}")

    # Sample keys to detect Cross/Spot
    if open_sample:
        print("\n--- Sample OPEN order (first) keys ---")
        for k in sorted(open_sample.keys()):
            v = open_sample[k]
            if k.lower() in ("api_key", "sig", "secret"):
                v = "<redacted>"
            print(f"   {k}: {v}")
    if trigger_sample:
        print("\n--- Sample TRIGGER order (first) keys ---")
        for k in sorted(trigger_sample.keys()):
            v = trigger_sample[k]
            if k.lower() in ("api_key", "sig", "secret"):
                v = "<redacted>"
            print(f"   {k}: {v}")

    if open_error or trigger_error:
        print("\n⚠️  One or both API calls failed; fix auth/IP then re-run.")
        return 1
    print("\n✅ Diagnostic complete. Use these counts to confirm dashboard vs exchange.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
