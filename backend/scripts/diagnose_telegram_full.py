#!/usr/bin/env python3
"""Comprehensive Telegram bot diagnostic"""
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

print("=" * 60)
print("TELEGRAM BOT DIAGNOSTIC")
print("=" * 60)
print()

# 1. Bot Info
print("1️⃣  BOT INFO")
print("-" * 60)
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
    bot = r.json().get("result", {})
    print(f"   ✅ Username: @{bot.get('username')}")
    print(f"   ✅ ID: {bot.get('id')}")
    print(f"   ✅ First Name: {bot.get('first_name')}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 2. Webhook Status
print("2️⃣  WEBHOOK STATUS")
print("-" * 60)
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
    wh = r.json().get("result", {})
    url = wh.get("url")
    pending = wh.get("pending_update_count", 0)
    
    if url:
        print(f"   ⚠️  WEBHOOK IS SET: {url}")
        print(f"   ⚠️  Pending updates: {pending}")
        print("   🔧 Deleting webhook...")
        r2 = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", 
                          json={"drop_pending_updates": True}, timeout=5)
        if r2.json().get("ok"):
            print("   ✅ Webhook deleted")
        else:
            print(f"   ❌ Failed to delete: {r2.json()}")
    else:
        print("   ✅ No webhook set (good for polling)")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 3. Recent Updates
print("3️⃣  RECENT UPDATES (last 10)")
print("-" * 60)
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=10", timeout=5)
    updates = r.json().get("result", [])
    print(f"   Found: {len(updates)} updates")
    
    if updates:
        print("   Recent messages:")
        for u in updates[-5:]:
            msg = u.get("message", {})
            if msg:
                text = msg.get("text", "N/A")
                chat_id = msg.get("chat", {}).get("id")
                user_id = msg.get("from", {}).get("id") if msg.get("from") else None
                update_id = u.get("update_id")
                print(f"   - Update {update_id}: {text[:40]}")
                print(f"     chat_id={chat_id}, user_id={user_id}")
    else:
        print("   ⚠️  NO UPDATES FOUND")
        print("   This could mean:")
        print("   - Updates were already consumed")
        print("   - Updates expired (24h limit)")
        print("   - Another instance is polling")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 4. Test sendMessage
print("4️⃣  TEST SEND MESSAGE")
print("-" * 60)
if AUTH_CHAT_ID:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": AUTH_CHAT_ID,
                "text": "🧪 Test message from diagnostic script"
            },
            timeout=5
        )
        if r.json().get("ok"):
            print("   ✅ sendMessage works - bot can SEND messages")
        else:
            print(f"   ❌ sendMessage failed: {r.json()}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
else:
    print("   ⚠️  TELEGRAM_CHAT_ID not set, skipping test")
print()

# 5. Test getUpdates with long polling
print("5️⃣  TEST LONG POLLING (waiting 5 seconds)")
print("-" * 60)
print("   👉 If you send a message NOW, it should appear below...")
try:
    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=5",
        timeout=10
    )
    updates = r.json().get("result", [])
    if updates:
        print(f"   ✅ Received {len(updates)} update(s) - bot CAN receive!")
        for u in updates:
            msg = u.get("message", {})
            if msg:
                text = msg.get("text", "N/A")
                print(f"   - {text[:50]}")
    else:
        print("   ❌ No updates received - bot CANNOT receive messages")
        print("   Possible causes:")
        print("   - Another instance/webhook consuming updates")
        print("   - Bot lacks permission in group")
        print("   - Network/firewall blocking Telegram API")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 6. Configuration Check
print("6️⃣  CONFIGURATION")
print("-" * 60)
print(f"   BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Not set'} ({len(BOT_TOKEN) if BOT_TOKEN else 0} chars)")
print(f"   AUTH_CHAT_ID: {'✅ Set' if AUTH_CHAT_ID else '❌ Not set'} ({AUTH_CHAT_ID if AUTH_CHAT_ID else 'N/A'})")
print()

print("=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
print()
print("📋 SUMMARY:")
print("   - If sendMessage works but getUpdates returns 0:")
print("     → Another instance/webhook is consuming updates")
print("   - If getUpdates works in this test but not in service:")
print("     → Check service logs for errors")
print("   - If bot has no permission in group:")
print("     → Add bot as admin or give 'Read Messages' permission")

