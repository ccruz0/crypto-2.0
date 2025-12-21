#!/usr/bin/env python3
"""Test if bot can receive Telegram updates"""
import os
import sys
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTH_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

print("=== Testing Telegram Update Reception ===\n")

# 1. Delete webhook
print("1. Deleting webhook...")
r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", json={"drop_pending_updates": True}, timeout=5)
print(f"   Result: {r.json()}\n")

# 2. Get bot info
print("2. Bot info:")
r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
bot = r.json().get("result", {})
print(f"   Username: {bot.get('username')}")
print(f"   ID: {bot.get('id')}\n")

# 3. Check webhook status
print("3. Webhook status:")
r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
wh = r.json().get("result", {})
print(f"   URL: {wh.get('url') or 'None'}")
print(f"   Pending updates: {wh.get('pending_update_count', 0)}\n")

# 4. Get updates (no offset - should get recent updates)
print("4. Getting recent updates (no offset, limit=10)...")
r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=10", timeout=5)
updates = r.json().get("result", [])
print(f"   Updates found: {len(updates)}")
if updates:
    print("   Recent updates:")
    for u in updates[-5:]:  # Show last 5
        msg = u.get("message", {})
        if msg:
            text = msg.get("text", "N/A")
            chat_id = msg.get("chat", {}).get("id")
            update_id = u.get("update_id")
            print(f"   - Update {update_id}: {text[:50]}")
            print(f"     chat_id={chat_id}")
else:
    print("   ⚠️ NO UPDATES FOUND")
    print("   This means either:")
    print("   - All updates were already consumed")
    print("   - Updates expired (Telegram keeps them 24h)")
    print("   - Another instance/webhook is consuming updates\n")

# 5. Test with long polling (wait for new message)
print("5. Testing long polling (waiting 10 seconds for NEW message)...")
print("   👉 SEND A MESSAGE NOW in Telegram!")
time.sleep(2)  # Give user time to read
r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=10", timeout=15)
updates = r.json().get("result", [])
print(f"   Updates received: {len(updates)}")
if updates:
    print("   ✅ Bot CAN receive updates!")
    for u in updates:
        msg = u.get("message", {})
        if msg:
            text = msg.get("text", "N/A")
            print(f"   - {text[:50]}")
else:
    print("   ❌ Bot did NOT receive updates")
    print("   Possible causes:")
    print("   - Another instance/webhook is consuming updates")
    print("   - Bot doesn't have permission in group")
    print("   - Network/firewall blocking Telegram API")

print("\n=== Test Complete ===")

