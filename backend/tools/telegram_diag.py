#!/usr/bin/env python3
"""
Telegram Bot Diagnostics CLI Tool

Usage:
    python -m tools.telegram_diag [--delete-webhook] [--probe-updates]

This script performs diagnostics on the Telegram bot:
- getMe: Verify bot identity
- getWebhookInfo: Check webhook status
- deleteWebhook: Optionally delete webhook (use --delete-webhook flag)
- getUpdates probe: Check for pending updates (use --probe-updates flag)

This must work inside the backend container.
"""

import os
import sys
import argparse
import requests
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

def get_bot_token():
    """Get bot token from environment"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN environment variable not set")
        sys.exit(1)
    return token

def print_section(title: str):
    """Print a formatted section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_get_me(bot_token: str) -> bool:
    """Check bot identity via getMe"""
    print_section("1. Bot Identity (getMe)")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok"):
            bot_data = data.get("result", {})
            username = bot_data.get("username", "N/A")
            bot_id = bot_data.get("id", "N/A")
            first_name = bot_data.get("first_name", "N/A")
            can_join_groups = bot_data.get("can_join_groups", False)
            can_read_all_group_messages = bot_data.get("can_read_all_group_messages", False)
            
            print(f"✅ Bot identity verified:")
            print(f"   Username: @{username}")
            print(f"   ID: {bot_id}")
            print(f"   First Name: {first_name}")
            print(f"   Can Join Groups: {can_join_groups}")
            print(f"   Can Read All Group Messages: {can_read_all_group_messages}")
            return True
        else:
            print(f"❌ getMe failed: {data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Error calling getMe: {e}")
        return False

def check_webhook_info(bot_token: str) -> dict:
    """Check webhook status via getWebhookInfo"""
    print_section("2. Webhook Status (getWebhookInfo)")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok"):
            webhook_data = data.get("result", {})
            webhook_url = webhook_data.get("url", "")
            pending_count = webhook_data.get("pending_update_count", 0)
            last_error = webhook_data.get("last_error_message", "")
            last_error_date = webhook_data.get("last_error_date", 0)
            max_connections = webhook_data.get("max_connections", 0)
            allowed_updates = webhook_data.get("allowed_updates", [])
            
            if webhook_url:
                print(f"⚠️  WEBHOOK IS CONFIGURED:")
                print(f"   URL: {webhook_url}")
                print(f"   Pending Updates: {pending_count}")
                print(f"   Max Connections: {max_connections}")
                print(f"   Allowed Updates: {allowed_updates}")
                if last_error:
                    print(f"   Last Error: {last_error}")
                    if last_error_date:
                        from datetime import datetime
                        error_time = datetime.fromtimestamp(last_error_date)
                        print(f"   Last Error Date: {error_time}")
                print(f"\n   ⚠️  WARNING: Webhook is active. Polling will NOT work while webhook exists.")
                return {"has_webhook": True, "url": webhook_url, "pending": pending_count}
            else:
                print(f"✅ No webhook configured (polling mode)")
                return {"has_webhook": False, "url": None, "pending": pending_count}
        else:
            print(f"❌ getWebhookInfo failed: {data.get('description', 'Unknown error')}")
            return {"has_webhook": None, "url": None, "pending": 0}
    except Exception as e:
        print(f"❌ Error calling getWebhookInfo: {e}")
        return {"has_webhook": None, "url": None, "pending": 0}

def delete_webhook(bot_token: str, drop_pending: bool = True) -> bool:
    """Delete webhook"""
    print_section("3. Delete Webhook")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        payload = {"drop_pending_updates": drop_pending}
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok"):
            print(f"✅ Webhook deleted successfully")
            if drop_pending:
                print(f"   (Pending updates were dropped)")
            return True
        else:
            print(f"❌ Failed to delete webhook: {data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Error deleting webhook: {e}")
        return False

def probe_updates(bot_token: str) -> bool:
    """Probe getUpdates without offset to check for pending updates"""
    print_section("4. Pending Updates Probe (getUpdates)")
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {"limit": 10, "timeout": 0}  # No offset, quick check
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok"):
            updates = data.get("result", [])
            update_count = len(updates)
            
            if update_count > 0:
                update_ids = [u.get("update_id", 0) for u in updates]
                max_id = max(update_ids) if update_ids else 0
                min_id = min(update_ids) if update_ids else 0
                
                print(f"⚠️  Found {update_count} pending updates:")
                print(f"   Update IDs: {update_ids}")
                print(f"   Min ID: {min_id}, Max ID: {max_id}")
                
                # Show sample update types
                update_types = []
                for u in updates[:3]:  # Show first 3
                    if u.get("message"):
                        update_types.append("message")
                    elif u.get("callback_query"):
                        update_types.append("callback_query")
                    elif u.get("my_chat_member"):
                        update_types.append("my_chat_member")
                    else:
                        update_types.append("other")
                print(f"   Sample types: {update_types}")
                
                print(f"\n   ℹ️  These updates are waiting to be processed.")
                print(f"   If polling is working, they should be consumed soon.")
                return True
            else:
                print(f"✅ No pending updates (all caught up)")
                return True
        else:
            error_desc = data.get("description", "Unknown error")
            print(f"❌ getUpdates failed: {error_desc}")
            if "409" in error_desc or "conflict" in error_desc.lower():
                print(f"\n   ⚠️  This usually means another webhook or polling client is active.")
            return False
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 409:
            print(f"❌ getUpdates conflict (409): Another webhook or polling client is active")
            print(f"   This means updates are being consumed elsewhere.")
        else:
            print(f"❌ HTTP error calling getUpdates: {e}")
        return False
    except Exception as e:
        print(f"❌ Error probing updates: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Telegram Bot Diagnostics Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic diagnostics
  python -m tools.telegram_diag
  
  # Delete webhook if present
  python -m tools.telegram_diag --delete-webhook
  
  # Probe for pending updates
  python -m tools.telegram_diag --probe-updates
  
  # Full diagnostics
  python -m tools.telegram_diag --delete-webhook --probe-updates
        """
    )
    parser.add_argument(
        "--delete-webhook",
        action="store_true",
        help="Delete webhook if present (use with caution)"
    )
    parser.add_argument(
        "--probe-updates",
        action="store_true",
        help="Probe getUpdates to check for pending updates"
    )
    
    args = parser.parse_args()
    
    bot_token = get_bot_token()
    
    print("\n" + "="*60)
    print("  Telegram Bot Diagnostics")
    print("="*60)
    
    # Always run getMe and getWebhookInfo
    get_me_ok = check_get_me(bot_token)
    webhook_info = check_webhook_info(bot_token)
    
    # Optionally delete webhook
    if args.delete_webhook:
        if webhook_info.get("has_webhook"):
            delete_webhook(bot_token)
            # Re-check webhook status
            print("\n" + "-"*60)
            print("Re-checking webhook status after deletion...")
            check_webhook_info(bot_token)
        else:
            print("\n" + "-"*60)
            print("No webhook to delete (already in polling mode)")
    
    # Optionally probe updates
    if args.probe_updates:
        probe_updates(bot_token)
    
    # Summary
    print_section("Summary")
    if get_me_ok:
        print("✅ Bot identity verified")
    else:
        print("❌ Bot identity check failed")
    
    if webhook_info.get("has_webhook"):
        print(f"⚠️  Webhook is configured at: {webhook_info.get('url')}")
        print(f"   Polling will NOT work until webhook is deleted")
    else:
        print("✅ No webhook (polling mode should work)")
    
    if webhook_info.get("pending", 0) > 0:
        print(f"⚠️  {webhook_info.get('pending')} pending updates in webhook queue")
    
    print("\n" + "="*60)
    print("Diagnostics complete")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()

