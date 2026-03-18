#!/usr/bin/env python3
"""Verify Telegram token by sending a test message. Uses token loader (prompts if missing)."""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json
import urllib.request
import urllib.error

from app.utils.telegram_token_loader import get_telegram_token, mask_token

def main():
    token = get_telegram_token()
    if not token:
        print("❌ No token available")
        sys.exit(1)

    chat_id = (
        os.getenv("TELEGRAM_CHAT_ID_TRADING")
        or os.getenv("TELEGRAM_CHAT_ID")
        or ""
    ).strip()
    if not chat_id:
        print("❌ Set TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID_TRADING for destination")
        sys.exit(1)

    print(f"📤 Sending test message (token: {mask_token(token)}, chat_id: {chat_id})...")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": "✅ ATP: Token verified — send test OK"}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read().decode())
        if result.get("ok") and result.get("result", {}).get("message_id"):
            print("✅ Message sent successfully. Check Telegram.")
            sys.exit(0)
        else:
            print(f"❌ Unexpected response: {result}")
            sys.exit(1)
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"❌ HTTP {e.code}: {body[:200]}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Send failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
