#!/usr/bin/env python3
"""
Capture the latest Telegram update payload for debugging.
Fetches from getUpdates (without consuming) and writes to payload.json.

Usage:
  TELEGRAM_BOT_TOKEN=xxx python scripts/diag/capture_telegram_payload.py
  # Or with offset to get specific update:
  TELEGRAM_BOT_TOKEN=xxx python scripts/diag/capture_telegram_payload.py --offset 123456
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, help="Offset for getUpdates (default: -1 to get latest)")
    parser.add_argument("-o", "--output", default="payload.json", help="Output file path")
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN_DEV")
    if not token:
        print("Set TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_DEV", file=sys.stderr)
        return 1

    import requests
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"timeout": 10}
    if args.offset is not None:
        params["offset"] = args.offset

    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        print(f"API error: {data}", file=sys.stderr)
        return 1

    updates = data.get("result", [])
    if not updates:
        print("No updates received. Send /start to the bot and run again.")
        return 0

    # Take the latest update
    latest = updates[-1]
    with open(args.output, "w") as f:
        json.dump(latest, f, indent=2, default=str)

    print(f"Captured update_id={latest.get('update_id')} to {args.output}")
    print("Fields: message=%s edited_message=%s channel_post=%s" % (
        "message" in latest,
        "edited_message" in latest,
        "channel_post" in latest,
    ))
    msg = latest.get("message") or latest.get("edited_message") or latest.get("channel_post")
    if msg:
        print("text=%s caption=%s chat.id=%s" % (
            repr((msg.get("text") or "")[:80]),
            repr((msg.get("caption") or "")[:80]),
            msg.get("chat", {}).get("id"),
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
