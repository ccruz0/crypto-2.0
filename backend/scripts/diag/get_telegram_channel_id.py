#!/usr/bin/env python3
"""Extract channel/group chat IDs from Telegram getUpdates. Run on PROD where token exists."""
import os
import sys

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)

BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN_AWS")
    or os.getenv("TELEGRAM_BOT_TOKEN")
    or ""
).strip()

if not BOT_TOKEN:
    print("TELEGRAM_BOT_TOKEN not set in env", file=sys.stderr)
    sys.exit(1)

print("Fetching getUpdates (limit=50)...")
r = requests.get(
    f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=50",
    timeout=10,
)
data = r.json()
if not data.get("ok"):
    print(f"API error: {data}", file=sys.stderr)
    sys.exit(1)

chats = {}
for u in data.get("result", []):
    msg = u.get("channel_post") or u.get("message", {})
    chat = msg.get("chat", {})
    cid = chat.get("id")
    if cid is None:
        continue
    if cid not in chats:
        chats[cid] = {
            "id": cid,
            "type": chat.get("type", "?"),
            "title": chat.get("title") or chat.get("username") or chat.get("first_name", "?"),
        }

print("\nChat IDs from recent updates (negative = channel/group):\n")
print(f"{'Chat ID':<18} {'Type':<12} Title")
print("-" * 60)
for cid in sorted(chats.keys()):
    c = chats[cid]
    marker = "📢" if c["type"] == "channel" else "👥" if c["id"] < 0 else "👤"
    print(f"{marker} {str(c['id']):<16} {c['type']:<12} {c['title'][:35]}")

channels = [c for c in chats.values() if c["type"] == "channel" or c["id"] < 0]
if channels:
    print("\n--- Channel/group IDs (use for TELEGRAM_CHAT_ID) ---")
    for c in channels:
        print(f"  TELEGRAM_CHAT_ID={c['id']}  # {c['title'][:40]}")
else:
    print("\nNo channel/group updates found.")
    print("Post a message in the target channel, then run this again.")
