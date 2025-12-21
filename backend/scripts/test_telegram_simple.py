#!/usr/bin/env python3
"""Simple test to verify Telegram bot can receive updates"""
import os
import sys
import requests
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTH_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not AUTH_CHAT_ID:
    print("❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    sys.exit(1)

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
            print(f"     AUTH_CHAT_ID={AUTH_CHAT_ID}")
            print(f"     authorized: {str(chat_id) == str(AUTH_CHAT_ID) or str(user_id) == str(AUTH_CHAT_ID)}")
else:
    print("   ⚠️ NO UPDATES - Telegram is not delivering updates")
    print("   Possible causes:")
    print("   - Another instance/webhook is consuming updates")
    print("   - Updates expired (Telegram keeps them 24h)")
    print("   - Bot doesn't have permission in group")

print("\n=== Test Complete ===")

