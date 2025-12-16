#!/usr/bin/env python3
"""
Test connection to Crypto.com Exchange
"""
import sys
import os
from pathlib import Path

# Load credentials from .env.local BEFORE importing anything
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
    print("✅ Loaded credentials from .env.local")
else:
    print(f"⚠️  .env.local not found at {env_file}")

# Set LIVE_TRADING before importing
os.environ['LIVE_TRADING'] = 'true'
sys.path.insert(0, backend_dir)

# Now import and create client (it will read from environment)
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
import requests

# Create a NEW client instance (not the singleton)
client = CryptoComTradeClient()
# Force enable live trading
client.live_trading = True

print('=' * 60)
print('Crypto.com Connection Test')
print('=' * 60)
print(f'API Key: {"✅ Configured" if client.api_key else "❌ Not configured"}')
print(f'API Secret: {"✅ Configured" if client.api_secret else "❌ Not configured"}')
print(f'Base URL: {client.base_url}')
print(f'Using Proxy: {client.use_proxy}')
print(f'Proxy URL: {client.proxy_url if client.use_proxy else "N/A"}')
print(f'Live Trading: {client.live_trading}')
print()

# Test 1: Public endpoint (no auth needed)
print('1. Testing public endpoint (no auth)...')
try:
    response = requests.get('https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT', timeout=5)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data and 'data' in data['result']:
            ticker = data['result']['data'][0]
            print(f'   ✅ Public API works! BTC_USDT price: ${float(ticker.get("a", 0)):.2f}')
        else:
            print(f'   ⚠️  Public API responded but unexpected format')
    else:
        print(f'   ❌ Public API failed: {response.status_code}')
except Exception as e:
    print(f'   ❌ Public API error: {e}')

print()

# Test 2: Private endpoint (with auth)
print('2. Testing private endpoint (get_account_summary)...')
try:
    result = client.get_account_summary()
    if result and 'accounts' in result:
        accounts = result['accounts']
        print(f'   ✅ Private API works! Found {len(accounts)} account(s)')
        if accounts:
            print(f'   Sample account: {accounts[0].get("currency")} - Balance: {accounts[0].get("balance")}')
    elif 'error' in result:
        print(f'   ❌ Private API error: {result.get("error")}')
    else:
        print(f'   ⚠️  Private API responded but unexpected format: {list(result.keys())[:5] if result else "None"}')
except Exception as e:
    print(f'   ❌ Private API error: {e}')

print()

# Test 3: Get open orders
print('3. Testing get open orders...')
try:
    result = client.get_open_orders()
    if result and 'data' in result:
        orders = result['data']
        print(f'   ✅ Open orders API works! Found {len(orders)} open order(s)')
        if orders:
            print(f'   Sample order: {orders[0].get("order_id")} - {orders[0].get("instrument_name")} {orders[0].get("side")}')
    elif 'error' in result:
        print(f'   ❌ Open orders API error: {result.get("error")}')
    else:
        print(f'   ⚠️  Open orders API responded but unexpected format')
except Exception as e:
    print(f'   ❌ Open orders API error: {e}')

print()

# Test 4: Get order history
print('4. Testing get order history...')
try:
    result = client.get_order_history(page_size=10, page=0)
    if result and 'data' in result:
        orders = result['data']
        print(f'   ✅ Order history API works! Found {len(orders)} order(s) in history')
        if orders:
            print(f'   Most recent: {orders[0].get("order_id")} - {orders[0].get("instrument_name")} {orders[0].get("side")} {orders[0].get("status")}')
    elif 'error' in result:
        print(f'   ❌ Order history API error: {result.get("error")}')
    else:
        print(f'   ⚠️  Order history API responded but unexpected format')
except Exception as e:
    print(f'   ❌ Order history API error: {e}')

print()
print('=' * 60)
