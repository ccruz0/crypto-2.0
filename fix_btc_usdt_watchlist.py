#!/usr/bin/env python3
"""Script to fix BTC_USDT visibility in watchlist"""
import requests
import json
import os
from typing import Optional, Dict, Any

# Try to get API URL from environment or use default
API_URL = os.getenv("API_URL", "http://localhost:8000/api")
API_KEY = os.getenv("API_KEY", "demo-key")

def get_watchlist_item(symbol: str) -> Optional[Dict[str, Any]]:
    """Get watchlist item by symbol (may return deleted items)"""
    try:
        response = requests.get(
            f"{API_URL}/dashboard/symbol/{symbol}",
            headers={"X-API-Key": API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            print(f"❌ Error getting {symbol}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Exception getting {symbol}: {e}")
        return None

def get_all_watchlist_items() -> list:
    """Get all active watchlist items"""
    try:
        response = requests.get(
            f"{API_URL}/dashboard",
            headers={"X-API-Key": API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ Error getting watchlist: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        print(f"❌ Exception getting watchlist: {e}")
        return []

def restore_watchlist_item_by_symbol(symbol: str) -> bool:
    """Restore a deleted watchlist item by symbol"""
    try:
        response = requests.put(
            f"{API_URL}/dashboard/symbol/{symbol}/restore",
            headers={
                "X-API-Key": API_KEY,
                "Content-Type": "application/json"
            },
            timeout=10
        )
        if response.status_code == 200:
            result = response.json()
            print(f"✅ {result.get('message', f'Restored {symbol}')}")
            return True
        else:
            print(f"❌ Error restoring {symbol}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception restoring {symbol}: {e}")
        return False

def restore_watchlist_item(item_id: int, symbol: str) -> bool:
    """Restore a deleted watchlist item by setting is_deleted=False (fallback method)"""
    try:
        response = requests.put(
            f"{API_URL}/dashboard/{item_id}",
            headers={
                "X-API-Key": API_KEY,
                "Content-Type": "application/json"
            },
            json={"is_deleted": False},
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ Restored {symbol} (ID: {item_id})")
            return True
        else:
            print(f"❌ Error restoring {symbol}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception restoring {symbol}: {e}")
        return False

def create_watchlist_item(symbol: str) -> bool:
    """Create a new watchlist item"""
    try:
        response = requests.post(
            f"{API_URL}/dashboard",
            headers={
                "X-API-Key": API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "symbol": symbol,
                "exchange": "CRYPTO_COM",
                "alert_enabled": False,
                "trade_enabled": False,
                "is_deleted": False
            },
            timeout=10
        )
        if response.status_code == 200:
            print(f"✅ Created {symbol}")
            return True
        else:
            print(f"❌ Error creating {symbol}: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception creating {symbol}: {e}")
        return False

def main():
    symbol = "BTC_USDT"
    print(f"🔍 Checking {symbol} in watchlist...")
    print(f"   API URL: {API_URL}")
    print()
    
    # Check if BTC_USDT exists (even if deleted)
    item = get_watchlist_item(symbol)
    
    if item:
        item_id = item.get("id")
        is_deleted = item.get("is_deleted", False) or item.get("deleted", False)
        
        print(f"📋 Found {symbol}:")
        print(f"   ID: {item_id}")
        print(f"   Symbol: {item.get('symbol')}")
        print(f"   Exchange: {item.get('exchange')}")
        print(f"   is_deleted: {is_deleted}")
        print(f"   alert_enabled: {item.get('alert_enabled')}")
        print(f"   trade_enabled: {item.get('trade_enabled')}")
        print()
        
        if is_deleted:
            print(f"⚠️  {symbol} is marked as deleted (is_deleted=True)")
            print(f"   Restoring...")
            # Try new restore endpoint first, fallback to item_id method
            if restore_watchlist_item_by_symbol(symbol):
                print(f"✅ {symbol} has been restored and should now be visible in watchlist")
            elif restore_watchlist_item(item_id, symbol):
                print(f"✅ {symbol} has been restored and should now be visible in watchlist")
            else:
                print(f"❌ Failed to restore {symbol}")
        else:
            print(f"✅ {symbol} is active (is_deleted=False) and should be visible")
            print(f"   If it's not showing, there may be another issue (frontend filter, etc.)")
    else:
        print(f"❌ {symbol} not found in database")
        print(f"   Creating new entry...")
        if create_watchlist_item(symbol):
            print(f"✅ {symbol} has been created and should now be visible in watchlist")
        else:
            print(f"❌ Failed to create {symbol}")
    
    # Verify by checking active watchlist
    print()
    print("🔍 Verifying active watchlist...")
    active_items = get_all_watchlist_items()
    btc_found = [item for item in active_items if item.get("symbol", "").upper() == symbol]
    
    if btc_found:
        print(f"✅ {symbol} is now in active watchlist ({len(active_items)} total items)")
    else:
        print(f"❌ {symbol} is still not in active watchlist ({len(active_items)} total items)")
        print(f"   This may indicate a different issue (database connection, etc.)")

if __name__ == "__main__":
    main()


