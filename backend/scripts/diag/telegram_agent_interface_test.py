#!/usr/bin/env python3
"""
Diagnostic script: discover Telegram bot token and chat ID from all sources,
then send a test message to confirm the agent interface location.

Usage:
  cd backend
  PYTHONPATH=. python scripts/diag/telegram_agent_interface_test.py
"""

from __future__ import annotations

import sys

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

from app.config.telegram_config_loader import load_telegram_config


def main() -> int:
    cfg = load_telegram_config()
    token = cfg["bot_token"]
    chat_id = cfg["chat_id"]
    sources = cfg["sources"]

    print("Telegram token source:", sources["bot_token"])
    print("Telegram chat id source:", sources["chat_id"])
    print("Telegram chat id:", chat_id if chat_id else "(none)")

    if not token:
        print("\nTELEGRAM_BOT_TOKEN not found.", file=sys.stderr)
        print("Checked:", file=sys.stderr)
        print("  • Environment", file=sys.stderr)
        print("  • secrets/runtime.env", file=sys.stderr)
        print("  • .env", file=sys.stderr)
        print("  • .env.aws", file=sys.stderr)
        print("  • AWS SSM", file=sys.stderr)
        sys.exit(1)

    if not chat_id:
        print("\nTELEGRAM_CHAT_ID not found.", file=sys.stderr)
        print("Checked:", file=sys.stderr)
        print("  • Environment", file=sys.stderr)
        print("  • secrets/runtime.env", file=sys.stderr)
        print("  • .env", file=sys.stderr)
        print("  • .env.aws", file=sys.stderr)
        print("  • AWS SSM", file=sys.stderr)
        print("Use scripts/diag/get_telegram_channel_id.py to discover channel IDs.", file=sys.stderr)
        sys.exit(1)

    message = "Agent interface ready. Send /help to see available agents."

    print("\nSending Telegram test message…")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=20,
        )
    except requests.RequestException as e:
        print(f"Error: HTTP request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not resp.ok:
        print(f"Telegram API error (HTTP {resp.status_code}):", file=sys.stderr)
        try:
            body = resp.json()
            print(body, file=sys.stderr)
        except Exception:
            print(resp.text, file=sys.stderr)
        sys.exit(1)

    print("Telegram message sent successfully.")

    print("\nRun command:")
    print("  cd ~/crypto-2.0")
    print("  source .venv/bin/activate")
    print("  cd backend")
    print("  PYTHONPATH=. python scripts/diag/telegram_agent_interface_test.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
