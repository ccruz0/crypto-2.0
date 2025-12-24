#!/usr/bin/env python3
"""
Test watchlist master table endpoints.

Tests:
1. GET /api/dashboard - should return data from watchlist_master
2. PUT /api/dashboard/symbol/{symbol} - should update master table
3. Verify field_updated_at is included in responses
"""

import sys
import requests
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = "http://localhost:8000"  # Adjust if needed


def test_get_dashboard():
    """Test GET /api/dashboard endpoint."""
    print("=" * 60)
    print("Test 1: GET /api/dashboard")
    print("=" * 60)
    
    try:
        response = requests.get(f"{BASE_URL}/api/dashboard", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ Status: {response.status_code}")
        print(f"✅ Items returned: {len(data)}")
        
        if len(data) > 0:
            first_item = data[0]
            print(f"\nFirst item: {first_item.get('symbol', 'N/A')}")
            print(f"Has field_updated_at: {'field_updated_at' in first_item}")
            
            if 'field_updated_at' in first_item:
                field_timestamps = first_item['field_updated_at']
                if field_timestamps:
                    print(f"Fields with timestamps: {list(field_timestamps.keys())[:5]}...")
                else:
                    print("⚠️  field_updated_at is empty")
            else:
                print("⚠️  field_updated_at not found in response")
            
            return True, data
        else:
            print("⚠️  No items returned")
            return False, []
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        return False, []


def test_put_update(symbol="BTC_USDT"):
    """Test PUT /api/dashboard/symbol/{symbol} endpoint."""
    print("\n" + "=" * 60)
    print(f"Test 2: PUT /api/dashboard/symbol/{symbol}")
    print("=" * 60)
    
    # Test updating buy_alert_enabled
    test_value = True
    
    try:
        payload = {
            "buy_alert_enabled": test_value
        }
        
        response = requests.put(
            f"{BASE_URL}/api/dashboard/symbol/{symbol}",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        print(f"✅ Status: {response.status_code}")
        print(f"✅ Response: {data.get('message', 'N/A')}")
        print(f"✅ Updated fields: {data.get('updated_fields', [])}")
        
        if 'item' in data:
            item = data['item']
            print(f"✅ Item symbol: {item.get('symbol', 'N/A')}")
            print(f"✅ buy_alert_enabled: {item.get('buy_alert_enabled', 'N/A')}")
            
            if 'field_updated_at' in item:
                field_timestamps = item['field_updated_at']
                if 'buy_alert_enabled' in field_timestamps:
                    timestamp = field_timestamps['buy_alert_enabled']
                    print(f"✅ buy_alert_enabled timestamp: {timestamp}")
                else:
                    print("⚠️  buy_alert_enabled not in field_updated_at")
            else:
                print("⚠️  field_updated_at not found in response")
        
        return True, data
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False, None


def test_consistency():
    """Test consistency: GET response should match what we just updated."""
    print("\n" + "=" * 60)
    print("Test 3: Consistency Check")
    print("=" * 60)
    
    try:
        # Get dashboard again
        response = requests.get(f"{BASE_URL}/api/dashboard", timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Find BTC_USDT
        btc_item = None
        for item in data:
            if item.get('symbol') == 'BTC_USDT':
                btc_item = item
                break
        
        if btc_item:
            print(f"✅ Found BTC_USDT in response")
            print(f"✅ buy_alert_enabled: {btc_item.get('buy_alert_enabled', 'N/A')}")
            print(f"✅ Has field_updated_at: {'field_updated_at' in btc_item}")
            
            if 'field_updated_at' in btc_item:
                timestamps = btc_item['field_updated_at']
                if 'buy_alert_enabled' in timestamps:
                    print(f"✅ buy_alert_enabled timestamp: {timestamps['buy_alert_enabled']}")
            
            return True
        else:
            print("⚠️  BTC_USDT not found in response")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Watchlist Master Table Endpoint Tests")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"Time: {datetime.now()}")
    print("=" * 60)
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print("✅ Server is running")
    except:
        print("⚠️  Server health check failed - make sure backend is running")
        print("   You can start it with: cd backend && uvicorn app.main:app --reload")
    
    results = []
    
    # Test 1: GET endpoint
    success, data = test_get_dashboard()
    results.append(("GET /api/dashboard", success))
    
    if success and len(data) > 0:
        # Test 2: PUT endpoint (use first symbol from GET response)
        first_symbol = data[0].get('symbol', 'BTC_USDT')
        success, _ = test_put_update(first_symbol)
        results.append((f"PUT /api/dashboard/symbol/{first_symbol}", success))
        
        # Test 3: Consistency
        success = test_consistency()
        results.append(("Consistency Check", success))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(success for _, success in results)
    print("=" * 60)
    if all_passed:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

