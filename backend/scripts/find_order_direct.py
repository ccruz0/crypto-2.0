#!/usr/bin/env python3
"""
Script to find order directly from Crypto.com using backend credentials
"""
import sys
import os
from pathlib import Path

# Load .env.local credentials
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)
env_file = Path(project_root) / '.env.local'

if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

os.environ['LIVE_TRADING'] = 'true'
sys.path.insert(0, backend_dir)

from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from datetime import datetime, timedelta
import time

# Create client with credentials
client = CryptoComTradeClient()
client.live_trading = True

print(f"API Key: {'✅ Configured' if client.api_key else '❌ Not configured'}")
print(f"Using Proxy: {client.use_proxy}")
print(f"Live Trading: {client.live_trading}")

if not client.api_key and not client.use_proxy:
    print("\n❌ Cannot search - no API credentials or proxy")
    sys.exit(1)

order_id = sys.argv[1] if len(sys.argv) > 1 else None
if not order_id:
    print("Usage: python3 find_order_direct.py <order_id>")
    sys.exit(1)

print(f"\n🔍 Searching for order {order_id}...")

# Check open orders
print("\n1. Checking open orders...")
try:
    result = client.get_open_orders()
    orders = result.get('data', []) if result else []
    found = [o for o in orders if str(o.get('order_id', '')) == order_id]
    if found:
        o = found[0]
        print(f"✅ FOUND in open orders!")
        print(f"   Order ID: {o.get('order_id')}")
        print(f"   Symbol: {o.get('instrument_name')}")
        print(f"   Side: {o.get('side')}")
        print(f"   Status: {o.get('status')}")
        print(f"   Price: {o.get('limit_price') or o.get('price')}")
        print(f"   Quantity: {o.get('quantity')}")
        sys.exit(0)
    print(f"   Not found in {len(orders)} open orders")
except Exception as e:
    print(f"   Error: {e}")

# Check trigger orders
print("\n2. Checking trigger orders...")
try:
    result = client.get_trigger_orders()
    orders = result.get('data', []) if result else []
    found = [o for o in orders if str(o.get('order_id', '')) == order_id]
    if found:
        o = found[0]
        print(f"✅ FOUND in trigger orders!")
        print(f"   Order ID: {o.get('order_id')}")
        print(f"   Symbol: {o.get('instrument_name')}")
        print(f"   Side: {o.get('side')}")
        print(f"   Status: {o.get('status')}")
        sys.exit(0)
    print(f"   Not found in {len(orders)} trigger orders")
except Exception as e:
    print(f"   Error: {e}")

# Search history - go back 180 days
print("\n3. Searching order history (last 180 days)...")
end_time = int(time.time() * 1000)
start_time = int((datetime.now() - timedelta(days=180)).timestamp() * 1000)

for page in range(20):  # Search up to 20 pages
    try:
        result = client.get_order_history(
            page_size=200,
            start_time=start_time,
            end_time=end_time,
            page=page
        )
        orders = result.get('data', []) if result else []
        
        if not orders:
            break
        
        found = [o for o in orders if str(o.get('order_id', '')) == order_id]
        if found:
            o = found[0]
            print(f"\n✅ FOUND in order history (page {page + 1})!")
            print(f"   Order ID: {o.get('order_id')}")
            print(f"   Symbol: {o.get('instrument_name')}")
            print(f"   Side: {o.get('side')}")
            print(f"   Status: {o.get('status')}")
            print(f"   Price: {o.get('limit_price') or o.get('price') or o.get('avg_price')}")
            print(f"   Quantity: {o.get('quantity')}")
            print(f"   Cumulative Qty: {o.get('cumulative_quantity')}")
            print(f"   Avg Price: {o.get('avg_price')}")
            if o.get('create_time'):
                print(f"   Create Time: {datetime.fromtimestamp(o['create_time'] / 1000)}")
            sys.exit(0)
        
        if len(orders) < 200:
            break
            
        if (page + 1) % 5 == 0:
            print(f"   Searched {page + 1} pages ({len(orders) * (page + 1)} orders)...")
    except Exception as e:
        print(f"   Error on page {page + 1}: {e}")
        break

print(f"\n❌ Order {order_id} not found")
print("   Searched:")
print("   - Open orders")
print("   - Trigger orders") 
print("   - Order history (last 180 days, 20 pages)")
sys.exit(1)


