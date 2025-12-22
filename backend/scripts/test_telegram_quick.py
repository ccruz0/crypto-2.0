#!/usr/bin/env python3
"""Quick Telegram bot test - no waiting"""
import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AUTH_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set")
    sys.exit(1)

print("=" * 60)
print("QUICK TELEGRAM TEST")
print("=" * 60)
print()

# 1. Bot Info
print("1. Bot Info:")
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
    bot = r.json().get("result", {})
    print(f"   ✅ Username: @{bot.get('username')}")
    print(f"   ✅ ID: {bot.get('id')}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 2. Webhook Check
print("2. Webhook Status:")
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
    wh = r.json().get("result", {})
    url = wh.get("url")
    pending = wh.get("pending_update_count", 0)
    
    if url:
        print(f"   ⚠️  WEBHOOK ACTIVE: {url}")
        print(f"   ⚠️  Pending: {pending}")
        print("   🔧 Deleting webhook...")
        r2 = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", 
                          json={"drop_pending_updates": True}, timeout=5)
        if r2.json().get("ok"):
            print("   ✅ Webhook deleted")
        else:
            print(f"   ❌ Failed: {r2.json()}")
    else:
        print("   ✅ No webhook (good for polling)")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 3. Recent Updates
print("3. Recent Updates (last 10):")
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=10", timeout=5)
    updates = r.json().get("result", [])
    print(f"   Found: {len(updates)} updates")
    
    if updates:
        print("   ✅ Bot CAN receive updates!")
        print("   Recent messages:")
        for u in updates[-3:]:
            msg = u.get("message", {})
            if msg:
                text = msg.get("text", "N/A")
                update_id = u.get("update_id")
                print(f"   - Update {update_id}: {text[:50]}")
    else:
        print("   ⚠️  NO UPDATES FOUND")
        print("   Possible reasons:")
        print("   - Updates already consumed")
        print("   - Updates expired (24h limit)")
        print("   - Another instance polling")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# 4. Test Send
print("4. Test Send Message:")
if AUTH_CHAT_ID:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": AUTH_CHAT_ID,
                "text": "🧪 Quick test - bot can send messages"
            },
            timeout=5
        )
        if r.json().get("ok"):
            print("   ✅ Bot CAN send messages")
        else:
            print(f"   ❌ Failed: {r.json()}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
else:
    print("   ⚠️  TELEGRAM_CHAT_ID not set")
print()

# 5. Summary
print("=" * 60)
print("SUMMARY")
print("=" * 60)
if updates and len(updates) > 0:
    print("✅ Bot CAN receive updates")
    print("   → If commands not working, check service logs")
else:
    print("❌ Bot CANNOT receive updates")
    print("   → Check if another instance/webhook is active")
    print("   → Check bot permissions in group")
    print("   → Check service is running and polling")
print()

