#!/usr/bin/env python3
"""
Diagnostic script to extract a valid Telegram chat_id for local testing.

This script:
1. Checks bot info and webhook status
2. Removes webhook if present (webhooks block getUpdates)
3. Polls getUpdates to extract chat_id from recent messages
4. Provides clear instructions if no messages found
"""

import os
import sys
import time
import requests
import json

def mask_token(token):
    """Mask token for safe logging: show first 6 + last 4 chars."""
    if not token or len(token) < 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"

def get_bot_token():
    """Get bot token from env vars.
    
    Priority order (for local dev):
    1. TELEGRAM_BOT_TOKEN_DEV (recommended for local to avoid 409 conflicts)
    2. TELEGRAM_BOT_TOKEN_LOCAL (fallback)
    3. TELEGRAM_BOT_TOKEN (production token, not recommended for local)
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN_DEV") or os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: No Telegram bot token found", file=sys.stderr)
        print("   Set one of:", file=sys.stderr)
        print("   - TELEGRAM_BOT_TOKEN_DEV (recommended for local dev)", file=sys.stderr)
        print("   - TELEGRAM_BOT_TOKEN_LOCAL", file=sys.stderr)
        print("   - TELEGRAM_BOT_TOKEN (production, not recommended for local)", file=sys.stderr)
        sys.exit(1)
    
    # Identify which token source is being used
    if os.getenv("TELEGRAM_BOT_TOKEN_DEV"):
        token_source = "TELEGRAM_BOT_TOKEN_DEV"
    elif os.getenv("TELEGRAM_BOT_TOKEN_LOCAL"):
        token_source = "TELEGRAM_BOT_TOKEN_LOCAL"
    else:
        token_source = "TELEGRAM_BOT_TOKEN (⚠️ production token)"
    
    return token, token_source

def call_api(method, params=None):
    """Call Telegram Bot API."""
    token, _ = get_bot_token()
    base_url = f"https://api.telegram.org/bot{token}"
    url = f"{base_url}/{method}"
    
    try:
        if params:
            resp = requests.post(url, json=params, timeout=10)
        else:
            resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ API call failed: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_body = e.response.json()
                print(f"   Response: {error_body}", file=sys.stderr)
            except:
                print(f"   Response text: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(1)

def main():
    token, token_source = get_bot_token()
    print(f"🔍 Using bot token: {mask_token(token)}")
    print(f"   Source: {token_source}")
    print()
    
    # 1. Check bot info
    print("1️⃣ Checking bot info...")
    me = call_api("getMe")
    if me.get("ok"):
        bot_info = me["result"]
        print(f"   ✅ Bot: @{bot_info.get('username', 'N/A')} (id: {bot_info.get('id')})")
        print(f"   Name: {bot_info.get('first_name', 'N/A')}")
    else:
        print(f"   ❌ getMe failed: {me}", file=sys.stderr)
        sys.exit(1)
    print()
    
    # 2. Check webhook status
    print("2️⃣ Checking webhook status...")
    webhook_info = call_api("getWebhookInfo")
    if webhook_info.get("ok"):
        wh = webhook_info["result"]
        webhook_url = wh.get("url", "")
        pending = wh.get("pending_update_count", 0)
        last_error = wh.get("last_error_message", "")
        
        print(f"   Webhook URL: {webhook_url if webhook_url else '(none)'}")
        print(f"   Pending updates: {pending}")
        if last_error:
            print(f"   Last error: {last_error}")
        
        # 3. Remove webhook if present
        if webhook_url:
            print()
            print("3️⃣ Webhook detected! Removing webhook (webhooks block getUpdates)...")
            delete_result = call_api("deleteWebhook", {"drop_pending_updates": False})
            if delete_result.get("ok"):
                print("   ✅ Webhook removed")
                # Verify removal
                wh_check = call_api("getWebhookInfo")
                if wh_check.get("ok") and not wh_check["result"].get("url"):
                    print("   ✅ Confirmed: webhook URL is now empty")
                else:
                    print("   ⚠️ Warning: webhook URL still present", file=sys.stderr)
            else:
                print(f"   ❌ Failed to remove webhook: {delete_result}", file=sys.stderr)
        else:
            print("   ✅ No webhook configured")
    else:
        print(f"   ❌ getWebhookInfo failed: {webhook_info}", file=sys.stderr)
    print()
    
    # 4. Poll getUpdates
    print("4️⃣ Polling getUpdates (5 attempts, 2s between)...")
    chat_ids_found = []
    
    for attempt in range(1, 6):
        print(f"   Attempt {attempt}/5...", end=" ", flush=True)
        # Use GET with query params for getUpdates
        token, _ = get_bot_token()
        url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=10"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            updates = resp.json()
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            # Handle 409 Conflict (another bot instance is polling)
            if "409" in error_msg or "Conflict" in error_msg:
                print("⚠️ 409 Conflict: Another bot instance is polling getUpdates")
                print("   💡 Stop any running backend/uvicorn processes, then rerun this script")
                if attempt == 1:
                    print("   💡 Or wait 30 seconds and rerun (conflict may clear)")
            else:
                print(f"failed: {e}")
            time.sleep(2)
            continue
        
        if updates.get("ok"):
            results = updates.get("result", [])
            print(f"found {len(results)} updates")
            
            for update in results:
                update_id = update.get("update_id")
                msg = update.get("message") or update.get("edited_message") or update.get("channel_post")
                
                if msg and msg.get("chat"):
                    chat = msg["chat"]
                    chat_id = chat.get("id")
                    chat_type = chat.get("type", "unknown")
                    chat_title = chat.get("title", "")
                    chat_username = chat.get("username", "")
                    msg_text = msg.get("text", "")[:60] if msg.get("text") else "(no text)"
                    
                    if chat_id and chat_id not in chat_ids_found:
                        chat_ids_found.append(chat_id)
                        print(f"      ✅ Found chat_id: {chat_id}")
                        print(f"         Type: {chat_type}")
                        if chat_title:
                            print(f"         Title: {chat_title}")
                        if chat_username:
                            print(f"         Username: @{chat_username}")
                        print(f"         Message: {msg_text}")
        else:
            print(f"failed: {updates}")
        
        if attempt < 5:
            time.sleep(2)
    
    print()
    
    # 5. Results
    if chat_ids_found:
        # Use the most recent (last in list)
        recommended_chat_id = chat_ids_found[-1]
        print("✅ SUCCESS: Found valid chat_id(s)")
        print()
        print("📋 Use this chat_id:")
        print(f"   export TELEGRAM_CHAT_ID_LOCAL=\"{recommended_chat_id}\"")
        print()
        print("🧪 Then test sendMessage:")
        print("   python3 scripts/telegram_send_test.py")
        print()
        # Print for shell parsing
        print(f"USE_THIS_CHAT_ID={recommended_chat_id}")
        sys.exit(0)
    else:
        print("❌ No chat_id found after polling")
        print()
        print("📝 To get a chat_id:")
        print("   1. Open Telegram (desktop or mobile)")
        print("   2. Search for: @HILOVIVO30_bot")
        print("   3. Press 'Start' or send /start")
        print("   4. Send a test message (e.g., 'ping')")
        print("   5. Rerun this script:")
        print("      python3 scripts/telegram_chat_id_doctor.py")
        print()
        sys.exit(2)

if __name__ == "__main__":
    main()
