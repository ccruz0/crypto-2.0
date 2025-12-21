#!/usr/bin/env python3
"""Diagnostics script for Telegram polling - manual debugging in production"""
import os
import sys
import requests

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.telegram_commands import BOT_TOKEN, TELEGRAM_ENABLED

def main():
    if not TELEGRAM_ENABLED or not BOT_TOKEN:
        print("❌ Telegram not enabled or bot token missing")
        return
    
    print("=== Telegram Polling Diagnostics ===\n")
    
    # 1. getMe
    print("1. Bot Identity (getMe):")
    try:
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        response.raise_for_status()
        bot_info = response.json()
        if bot_info.get("ok"):
            bot_data = bot_info.get("result", {})
            print(f"   ✅ Username: {bot_data.get('username', 'N/A')}")
            print(f"   ✅ ID: {bot_data.get('id', 'N/A')}")
            print(f"   ✅ First Name: {bot_data.get('first_name', 'N/A')}")
        else:
            print(f"   ❌ Failed: {bot_info}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 2. getWebhookInfo
    print("2. Webhook Status (getWebhookInfo):")
    try:
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
        response.raise_for_status()
        webhook_info = response.json()
        if webhook_info.get("ok"):
            webhook_data = webhook_info.get("result", {})
            url = webhook_data.get("url", "")
            pending = webhook_data.get("pending_update_count", 0)
            last_error = webhook_data.get("last_error_message", "None")
            print(f"   URL: {url or 'None'}")
            print(f"   Pending Updates: {pending}")
            print(f"   Last Error: {last_error}")
            if url:
                print(f"   ⚠️  Webhook is configured!")
            else:
                print(f"   ✅ No webhook (polling mode)")
        else:
            print(f"   ❌ Failed: {webhook_info}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()
    
    # 3. getUpdates probe (no offset, limit=10)
    print("3. Pending Updates Probe (getUpdates, no offset, limit=10):")
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"limit": 10},
            timeout=5
        )
        response.raise_for_status()
        updates_info = response.json()
        if updates_info.get("ok"):
            updates = updates_info.get("result", [])
            print(f"   Updates Available: {len(updates)}")
            if updates:
                print(f"   First Update ID: {updates[0].get('update_id', 'N/A')}")
                print(f"   Last Update ID: {updates[-1].get('update_id', 'N/A')}")
                for u in updates[:3]:
                    msg = u.get("message", {})
                    if msg:
                        text = msg.get("text", "N/A")
                        print(f"   - Update {u.get('update_id')}: {text[:50]}")
            else:
                print(f"   ✅ No pending updates")
        else:
            print(f"   ❌ Failed: {updates_info}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n=== Diagnostics Complete ===")

if __name__ == "__main__":
    main()

