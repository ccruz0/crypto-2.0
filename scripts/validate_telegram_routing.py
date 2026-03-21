#!/usr/bin/env python3
"""
Validate Telegram routing by sending one controlled test message per configured channel.
Uses same env loading and channel config as send_channel_descriptions.py.

Usage (from repo root):
  python scripts/validate_telegram_routing.py

Messages sent:
  [TEST][ATP_CONTROL] routing validation
  [TEST][AWS_ALERTS] routing validation
  [TEST][CLAW] routing validation
  [TEST][ATP_ALERTS] routing validation
"""
import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

# Load env files (order matters - later overrides)
for f in [".env", ".env.aws", "secrets/runtime.env", "backend/.env"]:
    p = REPO_ROOT / f
    if p.exists():
        with open(p) as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"\'')
                    if k and v and k not in os.environ:
                        os.environ[k] = v


def _mask_token(token: str) -> str:
    """Mask token for logging: show last 4 chars only."""
    if not token or len(token) < 4:
        return "****"
    return f"...{token[-4:]}"


def send_message(token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Send message via Telegram API. Returns (success, error_msg)."""
    if not token or not chat_id:
        return False, "token or chat_id empty"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read().decode())
            if out.get("ok"):
                return True, ""
            return False, out.get("description", "unknown")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        try:
            err = json.loads(body).get("description", body) if body else str(e)
        except Exception:
            err = body or str(e)
        return False, f"HTTP {e.code}: {err}"
    except Exception as e:
        return False, str(e)


CHANNELS = [
    {
        "name": "ATP Control",
        "key": "ATP_CONTROL",
        "token_var": "TELEGRAM_ATP_CONTROL_BOT_TOKEN",
        "chat_var": "TELEGRAM_ATP_CONTROL_CHAT_ID",
        "fallback_token": "TELEGRAM_CLAW_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CLAW_CHAT_ID",
    },
    {
        "name": "AWS Alerts",
        "key": "AWS_ALERTS",
        "token_var": "TELEGRAM_ALERT_BOT_TOKEN",
        "chat_var": "TELEGRAM_ALERT_CHAT_ID",
        "fallback_token": "TELEGRAM_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CHAT_ID_OPS",
    },
    {
        "name": "Claw",
        "key": "CLAW",
        "token_var": "TELEGRAM_CLAW_BOT_TOKEN",
        "chat_var": "TELEGRAM_CLAW_CHAT_ID",
        "fallback_token": "TELEGRAM_BOT_TOKEN",
        "fallback_chat": "TELEGRAM_CHAT_ID",
    },
    {
        "name": "ATP Alerts",
        "key": "ATP_ALERTS",
        "token_var": "TELEGRAM_BOT_TOKEN",
        "chat_var": "TELEGRAM_CHAT_ID_TRADING",
        "fallback_token": "TELEGRAM_BOT_TOKEN_AWS",
        "fallback_chat": "TELEGRAM_CHAT_ID_AWS",
    },
]


def main():
    print("=== Telegram Routing Validation ===\n")
    print("Sending one [TEST][CHANNEL] message per logical channel. No grouping.\n")

    results = []
    for ch in CHANNELS:
        token = (os.environ.get(ch["token_var"]) or "").strip()
        chat = (os.environ.get(ch["chat_var"]) or "").strip()
        if not token and ch.get("fallback_token"):
            token = (os.environ.get(ch["fallback_token"]) or "").strip()
        if not chat and ch.get("fallback_chat"):
            chat = (os.environ.get(ch["fallback_chat"]) or "").strip()
        if not chat and ch.get("chat_var") == "TELEGRAM_CHAT_ID_TRADING":
            chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()

        msg = f"[TEST][{ch['key']}] routing validation"
        if not token or not chat:
            print(f"⏭️  {ch['name']}: SKIP (token or chat_id not set)")
            results.append({"channel": ch["name"], "status": "SKIP", "reason": "config missing"})
            continue

        print(f"[SEND] channel={ch['name']} key=[TEST][{ch['key']}] token={_mask_token(token)} chat_id={chat} msg={msg}")
        ok, err = send_message(token, chat, msg)
        if ok:
            print(f"✅ {ch['name']}: sent [TEST][{ch['key']}]")
            results.append({"channel": ch["name"], "status": "SENT", "message": msg})
        else:
            print(f"❌ {ch['name']}: FAILED - {err}")
            results.append({"channel": ch["name"], "status": "FAIL", "error": err})

    print("\nDone. Check each Telegram channel for the test message.")
    return 0 if all(r.get("status") in ("SENT", "SKIP") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
