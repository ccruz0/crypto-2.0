#!/usr/bin/env python3
"""Simple test to verify Telegram bot can receive updates"""
import os
import sys
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTH_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AUTH_USER_IDS_STR = os.getenv("TELEGRAM_AUTH_USER_ID", "")

if not BOT_TOKEN:
    print("❌ Missing TELEGRAM_BOT_TOKEN")
    sys.exit(1)

# Parse authorized user IDs
AUTHORIZED_USER_IDS = set()
if AUTH_USER_IDS_STR:
    for user_id in AUTH_USER_IDS_STR.replace(",", " ").split():
        user_id = user_id.strip()
        if user_id:
            AUTHORIZED_USER_IDS.add(user_id)
elif AUTH_CHAT_ID:
    # Fallback to TELEGRAM_CHAT_ID for backward compatibility
    AUTHORIZED_USER_IDS.add(str(AUTH_CHAT_ID))

print(f"TELEGRAM_CHAT_ID (channel): {AUTH_CHAT_ID}")
print(f"TELEGRAM_AUTH_USER_ID: {AUTH_USER_IDS_STR or '(not set)'}")
print(f"Authorized user IDs: {AUTHORIZED_USER_IDS}")

print("=== Simple Telegram Test ===\n")

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

# 3. Get updates
print("3. Getting updates (waiting 5 seconds for new messages)...")
print("   Send a message NOW in Telegram!")
time.sleep(5)
r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=5", timeout=10)
updates = r.json().get("result", [])
print(f"   Updates received: {len(updates)}")
if updates:
    for u in updates:
        msg = u.get("message", {})
        if msg:
            text = msg.get("text", "N/A")
            chat_id = msg.get("chat", {}).get("id")
            user_id = msg.get("from", {}).get("id") if msg.get("from") else None
            print(f"   - {text[:50]}")
            print(f"     chat_id={chat_id}, user_id={user_id}")
            print(f"     TELEGRAM_CHAT_ID={AUTH_CHAT_ID}")
            print(f"     AUTHORIZED_USER_IDS={AUTHORIZED_USER_IDS}")
            # Check authorization using new logic
            is_authorized = (
                (AUTH_CHAT_ID and str(chat_id) == str(AUTH_CHAT_ID)) or
                (user_id and str(user_id) in AUTHORIZED_USER_IDS) or
                (str(chat_id) in AUTHORIZED_USER_IDS)
            )
            print(f"     authorized: {is_authorized}")
else:
    print("   ⚠️ NO UPDATES - Telegram is not delivering updates")
    print("   Possible causes:")
    print("   - Another instance/webhook is consuming updates")
    print("   - Updates expired (Telegram keeps them 24h)")
    print("   - Bot doesn't have permission in group")

print("\n=== Test Complete ===")

