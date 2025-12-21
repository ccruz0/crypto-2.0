#!/usr/bin/env python3
import os
import requests
import json

token = os.getenv("TELEGRAM_BOT_TOKEN")
if not token:
    print("ERROR: TELEGRAM_BOT_TOKEN not set")
    exit(1)

# Delete webhook to ensure we use getUpdates
print("Deleting webhook...")
r = requests.post(f"https://api.telegram.org/bot{token}/deleteWebhook", json={"drop_pending_updates": False}, timeout=5)
print(f"Delete webhook status: {r.status_code}")
print(r.json())

# Check webhook status
print("\nChecking webhook info...")
r2 = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=5)
webhook_info = r2.json()
print(f"Webhook info: {webhook_info}")

# Get all pending updates (offset=-1 means get all, but Telegram doesn't support -1, so use 0)
print("\nGetting all pending updates...")
r3 = requests.get(f"https://api.telegram.org/bot{token}/getUpdates?timeout=1", timeout=3)
print(f"Status: {r3.status_code}")
data = r3.json()
result = data.get("result", [])
print(f"Updates found: {len(result)}")

if result:
    print(f"\nLatest {min(5, len(result))} updates:")
    for update in result[-5:]:
        update_id = update.get("update_id")
        msg = update.get("message", {})
        if msg:
            text = msg.get("text", "N/A")
            chat_id = msg.get("chat", {}).get("id")
            print(f"  Update ID: {update_id}, Chat: {chat_id}, Text: {text[:50]}")
else:
    print("No pending updates found")

