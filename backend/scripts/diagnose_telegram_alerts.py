#!/usr/bin/env python3
"""
Diagnostic script to check why Telegram alerts are not being received.

This script checks:
1. Telegram bot token and chat ID configuration
2. RUNTIME_ORIGIN environment variable
3. RUN_TELEGRAM flag
4. Telegram notifier initialization status
5. Test sending a message to Telegram
"""

import os
import sys
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings
from app.core.runtime import get_runtime_origin, is_aws_runtime
from app.services.telegram_notifier import telegram_notifier

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def check_environment_variables():
    """Check all relevant environment variables"""
    print("\n" + "="*60)
    print("ENVIRONMENT VARIABLES CHECK")
    print("="*60)
    
    env_vars = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID"),
        "RUNTIME_ORIGIN": os.getenv("RUNTIME_ORIGIN"),
        "RUN_TELEGRAM": os.getenv("RUN_TELEGRAM"),
        "APP_ENV": os.getenv("APP_ENV"),
        "ENVIRONMENT": os.getenv("ENVIRONMENT"),
    }
    
    for var_name, var_value in env_vars.items():
        if var_value:
            # Mask sensitive values
            if "TOKEN" in var_name:
                display_value = f"{var_value[:10]}...{var_value[-5:]}" if len(var_value) > 15 else "***"
            elif "CHAT_ID" in var_name:
                display_value = var_value  # Chat ID is not as sensitive
            else:
                display_value = var_value
            print(f"✅ {var_name}: {display_value}")
        else:
            print(f"❌ {var_name}: NOT SET")
    
    return env_vars


def check_settings():
    """Check Settings object values"""
    print("\n" + "="*60)
    print("SETTINGS CHECK")
    print("="*60)
    
    settings = Settings()
    
    print(f"TELEGRAM_BOT_TOKEN: {'✅ SET' if settings.TELEGRAM_BOT_TOKEN else '❌ NOT SET'}")
    if settings.TELEGRAM_BOT_TOKEN:
        token_preview = f"{settings.TELEGRAM_BOT_TOKEN[:10]}...{settings.TELEGRAM_BOT_TOKEN[-5:]}"
        print(f"  Preview: {token_preview}")
    
    print(f"TELEGRAM_CHAT_ID: {'✅ SET' if settings.TELEGRAM_CHAT_ID else '❌ NOT SET'}")
    if settings.TELEGRAM_CHAT_ID:
        print(f"  Value: {settings.TELEGRAM_CHAT_ID}")
    
    print(f"RUNTIME_ORIGIN: {settings.RUNTIME_ORIGIN or 'NOT SET (defaults to LOCAL)'}")
    print(f"RUN_TELEGRAM: {settings.RUN_TELEGRAM or 'NOT SET (defaults to true)'}")
    print(f"APP_ENV: {settings.APP_ENV or 'NOT SET'}")
    print(f"ENVIRONMENT: {settings.ENVIRONMENT or 'NOT SET'}")
    
    return settings


def check_runtime_origin():
    """Check runtime origin detection"""
    print("\n" + "="*60)
    print("RUNTIME ORIGIN CHECK")
    print("="*60)
    
    runtime_origin = get_runtime_origin()
    is_aws = is_aws_runtime()
    
    print(f"get_runtime_origin(): {runtime_origin}")
    print(f"is_aws_runtime(): {is_aws}")
    
    if runtime_origin == "AWS":
        print("✅ Runtime origin is AWS - alerts should be sent")
    else:
        print("❌ Runtime origin is LOCAL - alerts will be BLOCKED")
        print("   FIX: Set RUNTIME_ORIGIN=AWS in docker-compose.yml for market-updater-aws service")
    
    return runtime_origin, is_aws


def check_telegram_notifier():
    """Check Telegram notifier initialization"""
    print("\n" + "="*60)
    print("TELEGRAM NOTIFIER CHECK")
    print("="*60)
    
    notifier = telegram_notifier
    
    print(f"Enabled: {notifier.enabled}")
    print(f"Bot Token Present: {bool(notifier.bot_token)}")
    print(f"Chat ID Present: {bool(notifier.chat_id)}")
    
    if notifier.enabled:
        print("✅ Telegram notifier is enabled and ready")
    else:
        print("❌ Telegram notifier is disabled")
        if not notifier.bot_token:
            print("   Reason: Missing TELEGRAM_BOT_TOKEN")
        if not notifier.chat_id:
            print("   Reason: Missing TELEGRAM_CHAT_ID")
    
    return notifier


def test_telegram_send():
    """Test sending a message to Telegram"""
    print("\n" + "="*60)
    print("TELEGRAM SEND TEST")
    print("="*60)
    
    notifier = telegram_notifier
    
    if not notifier.enabled:
        print("❌ Cannot test: Telegram notifier is disabled")
        return False
    
    runtime_origin = get_runtime_origin()
    
    test_message = f"🧪 TEST ALERT - Diagnostic script check\n\nRuntime Origin: {runtime_origin}\nTimestamp: {os.popen('date').read().strip()}"
    
    print(f"Sending test message with origin={runtime_origin}...")
    print(f"Message: {test_message[:100]}...")
    
    try:
        result = notifier.send_message(test_message, origin=runtime_origin)
        if result:
            print("✅ Test message sent successfully!")
            print("   Check your Telegram chat to verify receipt")
            return True
        else:
            print("❌ Test message failed to send (returned False)")
            print("   Check logs for [TELEGRAM_GATEKEEPER] or [TELEGRAM_BLOCKED] messages")
            return False
    except Exception as e:
        print(f"❌ Test message failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all diagnostic checks"""
    print("\n" + "="*60)
    print("TELEGRAM ALERTS DIAGNOSTIC")
    print("="*60)
    print("\nThis script will check why Telegram alerts are not being received.")
    
    # Run all checks
    env_vars = check_environment_variables()
    settings = check_settings()
    runtime_origin, is_aws = check_runtime_origin()
    notifier = check_telegram_notifier()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    issues = []
    
    if not env_vars.get("TELEGRAM_BOT_TOKEN"):
        issues.append("❌ TELEGRAM_BOT_TOKEN environment variable not set")
    if not env_vars.get("TELEGRAM_CHAT_ID"):
        issues.append("❌ TELEGRAM_CHAT_ID environment variable not set")
    if runtime_origin != "AWS":
        issues.append(f"❌ RUNTIME_ORIGIN is '{runtime_origin}' (should be 'AWS' for alerts to send)")
    if not notifier.enabled:
        issues.append("❌ Telegram notifier is disabled")
    
    if not issues:
        print("✅ All checks passed! Telegram alerts should be working.")
        print("\nTesting actual message send...")
        test_result = test_telegram_send()
        if test_result:
            print("\n✅ DIAGNOSIS COMPLETE: Telegram is configured correctly and test message was sent.")
        else:
            print("\n⚠️  DIAGNOSIS: Configuration looks correct but test message failed.")
            print("   Check backend logs for [TELEGRAM_GATEKEEPER] or [TELEGRAM_ERROR] messages")
    else:
        print("❌ Issues found:")
        for issue in issues:
            print(f"   {issue}")
        print("\nFIXES NEEDED:")
        if runtime_origin != "AWS":
            print("   1. Set RUNTIME_ORIGIN=AWS in docker-compose.yml for market-updater-aws service")
        if not env_vars.get("TELEGRAM_BOT_TOKEN") or not env_vars.get("TELEGRAM_CHAT_ID"):
            print("   2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.aws file")
        if not notifier.enabled:
            print("   3. Set RUN_TELEGRAM=true in docker-compose.yml or .env.aws")
    
    print("\n" + "="*60)


if __name__ == "__main__":
    main()




