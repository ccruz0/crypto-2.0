#!/usr/bin/env python3
"""
Verify that each logical Telegram channel resolves to its own distinct destination.
Loads same env sources as backend/scripts. Reports resolved routing and any duplicates.

Usage (from repo root):
  python scripts/verify_telegram_destinations.py

Output:
  - Resolved routing table (token fingerprint, chat_id per channel)
  - Duplicate destination detection
  - Exit 1 if any channels share chat_id unexpectedly
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)

# Load env files (same order as send_channel_descriptions.py, validate_telegram_routing.py)
ENV_FILES = [".env", ".env.aws", "secrets/runtime.env", "backend/.env"]
for f in ENV_FILES:
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
    if not token or len(token) < 4:
        return "****"
    return f"...{token[-4:]}"


# Channel config: primary vars + fallbacks (same as validate_telegram_routing.py)
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


def resolve_channel(ch: dict) -> dict | None:
    """Resolve token and chat_id for a channel. Returns None if not configured."""
    token = (os.environ.get(ch["token_var"]) or "").strip()
    chat = (os.environ.get(ch["chat_var"]) or "").strip()
    used_fallback_token = False
    used_fallback_chat = False
    if not token and ch.get("fallback_token"):
        token = (os.environ.get(ch["fallback_token"]) or "").strip()
        used_fallback_token = True
    if not chat and ch.get("fallback_chat"):
        chat = (os.environ.get(ch["fallback_chat"]) or "").strip()
        used_fallback_chat = True
    if not chat and ch.get("chat_var") == "TELEGRAM_CHAT_ID_TRADING":
        chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
        used_fallback_chat = True

    if not token or not chat:
        return None

    chat_source = ch["chat_var"] if not used_fallback_chat else (ch.get("fallback_chat") or "TELEGRAM_CHAT_ID")
    token_source = ch["token_var"] if not used_fallback_token else (ch.get("fallback_token") or "")

    return {
        "name": ch["name"],
        "key": ch["key"],
        "token": token,
        "chat_id": chat,
        "token_var": ch["token_var"],
        "chat_var": ch["chat_var"],
        "token_source": token_source,
        "chat_source": chat_source,
        "used_fallback": used_fallback_token or used_fallback_chat,
    }


def main() -> int:
    print("=== Telegram Destination Verification ===\n")
    print("Env sources (first wins, later override):", ", ".join(ENV_FILES))
    print()

    # Resolve all channels
    resolved = []
    for ch in CHANNELS:
        r = resolve_channel(ch)
        if r:
            resolved.append(r)
        else:
            print(f"⏭️  {ch['name']}: SKIP (token or chat_id not set)")

    if not resolved:
        print("\nNo channels configured. Set env vars and retry.")
        return 1

    # Build routing table
    print("Resolved routing table:")
    print("-" * 115)
    print(f"{'Channel':<18} {'Token var':<32} {'Token':<10} {'Chat var':<28} {'Chat ID':<18} {'Source':<8}")
    print("-" * 115)

    for r in resolved:
        src = "fallback" if r.get("used_fallback") else "primary"
        print(f"{r['name']:<18} {r['token_var']:<32} {_mask_token(r['token']):<10} {r['chat_var']:<28} {r['chat_id']:<18} {src:<8}")

    print("-" * 100)

    # Detect shared destinations: (token, chat_id) -> list of channels
    by_dest: dict[tuple[str, str], list[str]] = {}
    for r in resolved:
        key = (r["token"], r["chat_id"])
        by_dest.setdefault(key, []).append(r["name"])

    duplicates = {k: v for k, v in by_dest.items() if len(v) > 1}

    if duplicates:
        print("\n⚠️  ROUTING MISCONFIGURATION: Multiple logical channels share the same destination:\n")
        for (token, chat_id), channels in duplicates.items():
            print(f"  chat_id={chat_id} token={_mask_token(token)}")
            for c in channels:
                print(f"    → {c}")
            print()
        print("Fix: Set distinct TELEGRAM_*_CHAT_ID for each channel so they route to separate Telegram chats.")
        return 1

    print("\n✅ All logical channels have distinct destinations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
