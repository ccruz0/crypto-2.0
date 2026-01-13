#!/usr/bin/env python3
"""Get Telegram chat ID for Hilovivo-alerts group"""
import os
import sys
import requests
import json

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN not set")
    print("Please set it in your environment or .env.aws file")
    sys.exit(1)

print("=== Getting Telegram Chat IDs ===\n")
print("This script will show all chat IDs from recent Telegram updates.\n")
print("To get the chat ID for 'Hilovivo-alerts':")
print("1. Make sure the bot is in the 'Hilovivo-alerts' group")
print("2. Send a message in that group (or have someone send one)")
print("3. Run this script\n")

# Get updates
print("Fetching recent updates...")
try:
    r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?limit=100", timeout=10)
    updates = r.json().get("result", [])
    
    if not updates:
        print("⚠️  No updates found.")
        print("\nTo get updates:")
        print("1. Send a message in the 'Hilovivo-alerts' group")
        print("2. Or forward a message to the bot")
        print("3. Then run this script again\n")
        sys.exit(0)
    
    # Collect unique chats
    chats = {}
    for u in updates:
        msg = u.get("message", {})
        if msg:
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            chat_title = chat.get("title") or chat.get("username") or chat.get("first_name", "Unknown")
            chat_type = chat.get("type", "unknown")
            
            if chat_id:
                key = f"{chat_id}"
                if key not in chats:
                    chats[key] = {
                        "id": chat_id,
                        "title": chat_title,
                        "type": chat_type,
                        "count": 0
                    }
                chats[key]["count"] += 1
    
    print(f"\nFound {len(chats)} unique chat(s):\n")
    print(f"{'Chat ID':<20} {'Type':<15} {'Title/Name':<40} {'Messages'}")
    print("-" * 95)
    
    # Sort by chat ID (negative group IDs first)
    sorted_chats = sorted(chats.values(), key=lambda x: x["id"])
    
    for chat in sorted_chats:
        chat_id = chat["id"]
        chat_type = chat["type"]
        title = chat["title"][:38] if len(chat["title"]) > 38 else chat["title"]
        count = chat["count"]
        
        # Highlight groups/supergroups
        if chat_type in ["group", "supergroup"]:
            marker = "👥"
        elif chat_type == "channel":
            marker = "📢"
        else:
            marker = "💬"
        
        print(f"{marker} {str(chat_id):<18} {chat_type:<15} {title:<40} {count}")
    
    # Look for "Hilovivo-alerts" specifically
    print("\n" + "="*95)
    print("\n🔍 Looking for 'Hilovivo-alerts' group...")
    
    hilovivo_alerts = None
    for chat in chats.values():
        title_lower = chat["title"].lower()
        if "hilovivo" in title_lower and "alerts" in title_lower and "local" not in title_lower:
            hilovivo_alerts = chat
            break
    
    if hilovivo_alerts:
        print(f"✅ Found 'Hilovivo-alerts' group!")
        print(f"   Chat ID: {hilovivo_alerts['id']}")
        print(f"   Type: {hilovivo_alerts['type']}")
        print(f"   Title: {hilovivo_alerts['title']}")
        print(f"\n📝 Update your .env.aws file:")
        print(f"   TELEGRAM_CHAT_ID={hilovivo_alerts['id']}")
    else:
        print("❌ Could not find 'Hilovivo-alerts' group in recent updates.")
        print("\nTo fix this:")
        print("1. Make sure the bot is added to the 'Hilovivo-alerts' group")
        print("2. Send a message in that group")
        print("3. Run this script again")
        print("\nOr manually update .env.aws with the chat ID from the list above.")
    
    print("\n" + "="*95)
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)










