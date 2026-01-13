#!/usr/bin/env python3
"""
Test script for Telegram kill switch functionality
Tests that messages are blocked when kill switch is disabled
"""

import os
import sys
import requests
import json
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Try to import backend modules
try:
    from app.services.telegram_notifier import telegram_notifier, _get_telegram_kill_switch_status
    from app.database import SessionLocal
    from app.models.trading_settings import TradingSettings
    from app.core.config import Settings
    BACKEND_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Backend modules not available: {e}")
    print("   Will test via API endpoints only")
    BACKEND_AVAILABLE = False

def get_environment():
    """Get current environment"""
    env = os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "local"
    return env.strip().lower()

def test_via_api():
    """Test kill switch via API endpoints"""
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    print("=" * 60)
    print("Testing Telegram Kill Switch via API")
    print("=" * 60)
    
    # Get current settings
    print("\n1. Getting current Telegram settings...")
    try:
        response = requests.get(f"{base_url}/api/settings/telegram", timeout=5)
        if response.status_code == 200:
            settings = response.json()
            print(f"   ✅ Current environment: {settings.get('env', 'unknown')}")
            print(f"   ✅ Enabled: {settings.get('enabled', False)}")
            print(f"   ✅ Other env ({settings.get('other_env', 'unknown')}): {settings.get('other_enabled', False)}")
            current_env = settings.get('env', 'local')
            current_enabled = settings.get('enabled', False)
        else:
            print(f"   ❌ Failed to get settings: {response.status_code}")
            return
    except Exception as e:
        print(f"   ❌ Error getting settings: {e}")
        return
    
    # Test sending message with current state
    print(f"\n2. Testing message send with kill switch {'ENABLED' if current_enabled else 'DISABLED'}...")
    try:
        response = requests.post(
            f"{base_url}/api/test/send-telegram-message",
            json={
                "symbol": "BTC_USDT",
                "message": f"🧪 Kill Switch Test - {datetime.now().strftime('%H:%M:%S')} - Switch is {'ON' if current_enabled else 'OFF'}"
            },
            timeout=10
        )
        result = response.json()
        if result.get('ok'):
            print(f"   ✅ Message sent successfully!")
            print(f"   📝 Response: {result.get('message', 'N/A')}")
        else:
            print(f"   ⚠️  Message send failed (expected if kill switch is OFF)")
            print(f"   📝 Response: {result.get('message', 'N/A')}")
    except Exception as e:
        print(f"   ❌ Error sending test message: {e}")
    
    # Toggle kill switch and test again
    print(f"\n3. Toggling kill switch to {not current_enabled}...")
    try:
        response = requests.post(
            f"{base_url}/api/settings/telegram",
            json={"enabled": not current_enabled},
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Kill switch toggled to {result.get('enabled', False)}")
            new_state = result.get('enabled', False)
        else:
            print(f"   ❌ Failed to toggle: {response.status_code}")
            return
    except Exception as e:
        print(f"   ❌ Error toggling kill switch: {e}")
        return
    
    # Test sending message with new state
    print(f"\n4. Testing message send with kill switch {'ENABLED' if new_state else 'DISABLED'}...")
    try:
        response = requests.post(
            f"{base_url}/api/test/send-telegram-message",
            json={
                "symbol": "BTC_USDT",
                "message": f"🧪 Kill Switch Test - {datetime.now().strftime('%H:%M:%S')} - Switch is {'ON' if new_state else 'OFF'}"
            },
            timeout=10
        )
        result = response.json()
        if result.get('ok'):
            print(f"   ✅ Message sent successfully!")
            print(f"   📝 Response: {result.get('message', 'N/A')}")
        else:
            print(f"   ⚠️  Message send failed (expected if kill switch is OFF)")
            print(f"   📝 Response: {result.get('message', 'N/A')}")
    except Exception as e:
        print(f"   ❌ Error sending test message: {e}")
    
    # Restore original state
    print(f"\n5. Restoring kill switch to original state ({current_enabled})...")
    try:
        response = requests.post(
            f"{base_url}/api/settings/telegram",
            json={"enabled": current_enabled},
            timeout=5
        )
        if response.status_code == 200:
            print(f"   ✅ Kill switch restored")
        else:
            print(f"   ⚠️  Failed to restore: {response.status_code}")
    except Exception as e:
        print(f"   ⚠️  Error restoring kill switch: {e}")
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)

def test_via_backend():
    """Test kill switch directly via backend modules"""
    print("=" * 60)
    print("Testing Telegram Kill Switch via Backend Modules")
    print("=" * 60)
    
    env = get_environment()
    print(f"\nCurrent environment: {env}")
    
    # Check kill switch status
    print("\n1. Checking kill switch status...")
    kill_switch_enabled = _get_telegram_kill_switch_status(env)
    print(f"   Kill switch for {env}: {'ENABLED' if kill_switch_enabled else 'DISABLED'}")
    
    # Check telegram notifier enabled state
    print("\n2. Checking Telegram notifier state...")
    print(f"   telegram_notifier.enabled: {telegram_notifier.enabled}")
    print(f"   bot_token present: {bool(telegram_notifier.bot_token)}")
    print(f"   chat_id present: {bool(telegram_notifier.chat_id)}")
    
    # Test sending a message
    print("\n3. Testing message send...")
    test_message = f"🧪 Backend Test - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    result = telegram_notifier.send_message(test_message, symbol="BTC_USDT")
    
    if result:
        print(f"   ✅ Message sent successfully!")
    else:
        print(f"   ⚠️  Message send returned False (may be blocked by kill switch)")
    
    print("\n" + "=" * 60)
    print("Backend test completed!")
    print("=" * 60)

if __name__ == "__main__":
    print("\n🔍 Telegram Kill Switch Test Script")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Try API test first
    try:
        test_via_api()
    except Exception as e:
        print(f"\n❌ API test failed: {e}")
        print("   Make sure backend is running on http://localhost:8000")
    
    # Try backend test if modules available
    if BACKEND_AVAILABLE:
        try:
            print("\n")
            test_via_backend()
        except Exception as e:
            print(f"\n❌ Backend test failed: {e}")
    
    print("\n✅ All tests completed!")


