#!/usr/bin/env python3
"""
Test script to verify Telegram sendMessage works with a given chat_id.

Exits 0 if send succeeds (ok=true and message_id exists), else exits 3.
"""

import os
import sys
import requests
import json

def mask_token(token):
    """Mask token for safe logging: show first 6 + last 4 chars."""
    if not token or len(token) < 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"

def main():
    # Get token (priority: DEV > LOCAL > PROD)
    token = os.getenv("TELEGRAM_BOT_TOKEN_DEV") or os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: No Telegram bot token found", file=sys.stderr)
        print("   Set one of: TELEGRAM_BOT_TOKEN_DEV, TELEGRAM_BOT_TOKEN_LOCAL, or TELEGRAM_BOT_TOKEN", file=sys.stderr)
        sys.exit(3)
    
    # Get chat_id (priority: DEV > LOCAL > PROD)
    chat_id = os.getenv("TELEGRAM_CHAT_ID_DEV") or os.getenv("TELEGRAM_CHAT_ID_LOCAL") or os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("❌ ERROR: No Telegram chat_id found", file=sys.stderr)
        print("   Set one of: TELEGRAM_CHAT_ID_DEV, TELEGRAM_CHAT_ID_LOCAL, or TELEGRAM_CHAT_ID", file=sys.stderr)
        sys.exit(3)
    
    # Identify token source
    if os.getenv("TELEGRAM_BOT_TOKEN_DEV"):
        token_source = "TELEGRAM_BOT_TOKEN_DEV"
    elif os.getenv("TELEGRAM_BOT_TOKEN_LOCAL"):
        token_source = "TELEGRAM_BOT_TOKEN_LOCAL"
    else:
        token_source = "TELEGRAM_BOT_TOKEN"
    
    print(f"🔍 Token: {mask_token(token)} ({token_source})")
    print(f"🔍 Chat ID: {chat_id}")
    print()
    
    # Send message
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "ATP local: send test OK"
    }
    
    print("📤 Sending test message...")
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        
        print()
        print("📥 Response:")
        print(json.dumps(result, indent=2))
        print()
        
        if result.get("ok") and result.get("result", {}).get("message_id"):
            message_id = result["result"]["message_id"]
            print(f"✅ SUCCESS: Message sent (message_id: {message_id})")
            print()
            print("✅ Telegram sendMessage works! Ready for end-to-end test.")
            sys.exit(0)
        else:
            error_code = result.get("error_code", "unknown")
            description = result.get("description", "unknown error")
            print(f"❌ FAILED: ok={result.get('ok')}, error_code={error_code}")
            print(f"   Description: {description}")
            sys.exit(3)
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_body = e.response.json()
                print(f"   Response: {json.dumps(error_body, indent=2)}", file=sys.stderr)
            except:
                print(f"   Response text: {e.response.text[:200]}", file=sys.stderr)
        sys.exit(3)

if __name__ == "__main__":
    main()
