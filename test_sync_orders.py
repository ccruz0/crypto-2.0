#!/usr/bin/env python3
"""
Test script to verify order history sync endpoint
"""
import requests
import json
import sys
from datetime import datetime

# Try to detect API URL
API_BASE = None

# Check if running locally or on AWS
if len(sys.argv) > 1:
    API_BASE = sys.argv[1]
else:
    # Try common endpoints
    for base_url in [
        'http://localhost:8002/api',
        'https://dashboard.hilovivo.com/api',
        '/api'  # Relative path
    ]:
        try:
            response = requests.get(f"{base_url}/health", timeout=3)
            if response.status_code == 200:
                API_BASE = base_url
                print(f"✅ Found backend at: {API_BASE}")
                break
        except:
            continue

if not API_BASE:
    print("❌ Could not find backend. Please provide API URL as argument:")
    print("   python test_sync_orders.py http://localhost:8002/api")
    sys.exit(1)

print(f"\n🔄 Testing order history sync endpoint...")
print(f"   API Base: {API_BASE}")
print(f"   Endpoint: POST {API_BASE}/orders/sync-history")
print()

try:
    # Test sync endpoint
    response = requests.post(
        f"{API_BASE}/orders/sync-history",
        timeout=60,  # Sync can take time
        headers={"Content-Type": "application/json"}
    )
    
    print(f"📊 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Sync completed successfully!")
        print(f"   Response: {json.dumps(data, indent=2)}")
    else:
        print(f"❌ Sync failed!")
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
        
except requests.exceptions.Timeout:
    print("❌ Request timed out (sync may be taking longer than expected)")
except requests.exceptions.ConnectionError as e:
    print(f"❌ Connection error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n📋 Testing order history retrieval...")
try:
    # Get order history to see if orders were synced
    response = requests.get(
        f"{API_BASE}/orders/history?limit=10&offset=0",
        timeout=10
    )
    
    if response.status_code == 200:
        data = response.json()
        orders = data.get('orders', [])
        print(f"✅ Retrieved {len(orders)} orders from history")
        
        if orders:
            print(f"\n📊 Most recent orders:")
            for i, order in enumerate(orders[:5], 1):
                symbol = order.get('instrument_name', 'N/A')
                side = order.get('side', 'N/A')
                status = order.get('status', 'N/A')
                update_time = order.get('update_datetime', 'N/A')
                print(f"   {i}. {symbol} {side} - {status} (Updated: {update_time})")
        else:
            print("   No orders found in history")
    else:
        print(f"❌ Failed to retrieve order history: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error retrieving order history: {e}")

print("\n✅ Test completed!")















