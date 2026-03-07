#!/usr/bin/env python3
"""
Verification script for per-instrument time-windowed order history fetch.
Calls the broker for one instrument with a narrow time window.
Run inside backend container:
  python scripts/test_order_history_windowed.py [INSTRUMENT]
  python scripts/test_order_history_windowed.py --order-id ORDER_ID

Examples:
  python scripts/test_order_history_windowed.py ATOM_USDT
  python scripts/test_order_history_windowed.py --order-id 12345678

With INSTRUMENT: uses 6h window around now.
With --order-id: uses get-order-detail to get instrument_name and create_time, then 6h window around create_time.
No secrets in output.
"""
import argparse
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Test windowed order history fetch (instrument or order_id)")
    parser.add_argument("instrument", nargs="?", default=None, help="Instrument name (e.g. ATOM_USDT)")
    parser.add_argument("--order-id", dest="order_id", default=None, help="Order ID; derive instrument and window from get-order-detail")
    args = parser.parse_args()

    instrument = (args.instrument or "ATOM_USDT").strip() if not args.order_id else None
    start_ms = None
    end_ms = None

    try:
        from app.services.brokers.crypto_com_trade import trade_client
    except ImportError as e:
        print(f"Import error: {e}")
        sys.exit(1)

    if args.order_id:
        # Derive instrument and window from get-order-detail
        detail = trade_client.get_order_detail(args.order_id)
        if not detail or not detail.get("result"):
            print(f"order_id={args.order_id} not found or no result")
            sys.exit(1)
        result = detail["result"]
        instrument = result.get("instrument_name") or result.get("instrument")
        if not instrument:
            print("order detail missing instrument_name")
            sys.exit(1)
        if "/" in instrument:
            instrument = instrument.replace("/", "_")
        create_time_ms = result.get("create_time")
        if create_time_ms is None:
            create_time_ms = result.get("createTime")
        if create_time_ms is None:
            print("order detail missing create_time; using now")
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - 6 * 60 * 60 * 1000
            end_ms = now_ms
        else:
            six_h_ms = 6 * 60 * 60 * 1000
            start_ms = int(create_time_ms) - six_h_ms
            end_ms = int(create_time_ms) + six_h_ms
        print(f"order_id={args.order_id} instrument={instrument} create_time_ms={create_time_ms} window=±6h")
    else:
        now_ms = int(time.time() * 1000)
        six_h_ms = 6 * 60 * 60 * 1000
        start_ms = now_ms - six_h_ms
        end_ms = now_ms
        print(f"instrument={instrument} start_ms={start_ms} end_ms={end_ms} (6h window)")

    response = trade_client.get_order_history(
        start_time=start_ms,
        end_time=end_ms,
        page=0,
        page_size=100,
        instrument_name=instrument,
    )
    data = response.get("data", []) if response else []
    count = len(data)
    print(f"fetched={count}")
    if data:
        first = data[0]
        keys = list(first.keys())[:10] if isinstance(first, dict) else []
        print(f"first_order_keys={keys}")
    sys.exit(0)


if __name__ == "__main__":
    main()
