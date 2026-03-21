#!/usr/bin/env python3
"""
Script to test the new executed order notification format with order origin information.
"""
import sys
import os
import requests
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Shared env (API_BASE_URL, AWS_BACKEND_URL, API_URL) or local default 8002
def _get_api_base():
    return (
        os.getenv("API_BASE_URL")
        or os.getenv("AWS_BACKEND_URL")
        or os.getenv("API_URL")
        or "http://localhost:8002"
    )

def test_executed_order_notification():
    """Test different order origin scenarios"""
    
    api_url = _get_api_base()
    print(f"API Base: {api_url}\n")
    
    # Test cases
    test_cases = [
        {
            "name": "SL/TP Order (Stop Loss)",
            "data": {
                "symbol": "ETH_USDT",
                "side": "SELL",
                "price": 2500.0,
                "quantity": 0.1,
                "order_id": "TEST_SL_001",
                "order_type": "STOP_LIMIT",
                "order_role": "STOP_LOSS",
                "entry_price": 2600.0
            }
        },
        {
            "name": "SL/TP Order (Take Profit) triggered by alert",
            "data": {
                "symbol": "BTC_USDT",
                "side": "SELL",
                "price": 46000.0,
                "quantity": 0.01,
                "order_id": "TEST_TP_001",
                "order_type": "TAKE_PROFIT_LIMIT",
                "order_role": "TAKE_PROFIT",
                "trade_signal_id": 123,
                "entry_price": 45000.0
            }
        },
        {
            "name": "Order created by Alert",
            "data": {
                "symbol": "DOGE_USDT",
                "side": "BUY",
                "price": 0.08,
                "quantity": 1000,
                "order_id": "TEST_ALERT_001",
                "order_type": "MARKET",
                "trade_signal_id": 456
            }
        },
        {
            "name": "Manual Order",
            "data": {
                "symbol": "SOL_USDT",
                "side": "BUY",
                "price": 100.0,
                "quantity": 1.0,
                "order_id": "TEST_MANUAL_001",
                "order_type": "LIMIT"
            }
        }
    ]
    
    print("🧪 Testing Executed Order Notifications with New Format\n")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: {test_case['name']}")
        print("-" * 60)
        
        try:
            response = requests.post(
                f"{api_url}/api/test/send-executed-order",
                json=test_case["data"],
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Success!")
                print(f"   Order Origin: {result.get('order_origin', 'N/A')}")
                print(f"   Symbol: {result.get('symbol')}")
                print(f"   Side: {result.get('side')}")
            else:
                print(f"❌ Failed: {response.status_code}")
                print(f"   Response: {response.text}")
                
        except requests.exceptions.ConnectionError:
            print(f"❌ Connection Error: Could not connect to {api_url}")
            print(f"   Make sure the API server is running")
            break
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    print("\n" + "=" * 60)
    print("✅ Test completed!")

if __name__ == "__main__":
    test_executed_order_notification()







