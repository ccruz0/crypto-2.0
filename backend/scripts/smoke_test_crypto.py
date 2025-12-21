#!/usr/bin/env python3
"""
Smoke test for Crypto.com API connectivity
Tests both public and private endpoints with redacted output
"""
import sys
import os
from pathlib import Path
import requests

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

# Now import and create client
from app.services.brokers.crypto_com_trade import CryptoComTradeClient

def redact_secret(value: str, show_chars: int = 4) -> str:
    """Redact secret, showing only first and last N characters"""
    if not value or len(value) <= show_chars * 2:
        return "<REDACTED>"
    return f"{value[:show_chars]}...{value[-show_chars:]}"

def test_public_endpoint():
    """Test public endpoint (no auth required)"""
    print("\n" + "="*60)
    print("TEST 1: Public Endpoint (No Auth)")
    print("="*60)
    try:
        # Try v2 endpoint first (works in test_crypto_connection.py)
        response = requests.get(
            'https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT',
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'data' in data['result']:
                ticker = data['result']['data'][0]
                price = float(ticker.get("a", 0))
                print(f"✅ SUCCESS: Public API works")
                print(f"   BTC_USDT price: ${price:,.2f}")
                return True
        # Fallback: try exchange/v1 endpoint
        response = requests.get(
            'https://api.crypto.com/exchange/v1/public/get-tickers',
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            print(f"✅ SUCCESS: Public API works (v1 endpoint)")
            return True
        else:
            print(f"❌ FAILED: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

def test_private_endpoint(client: CryptoComTradeClient):
    """Test private endpoint (requires auth)"""
    print("\n" + "="*60)
    print("TEST 2: Private Endpoint (Auth Required)")
    print("="*60)
    
    # Show redacted credentials
    api_key = getattr(client, 'api_key', '')
    api_secret = getattr(client, 'api_secret', '')
    print(f"API Key: {redact_secret(api_key) if api_key else 'NOT SET'}")
    print(f"API Secret: {'SET' if api_secret else 'NOT SET'} (length: {len(api_secret) if api_secret else 0})")
    print(f"Base URL: {getattr(client, 'base_url', 'N/A')}")
    print(f"Using Proxy: {getattr(client, 'use_proxy', False)}")
    
    try:
        result = client.get_account_summary()
        if result and 'accounts' in result:
            accounts = result['accounts']
            print(f"✅ SUCCESS: Private API works")
            print(f"   Found {len(accounts)} account(s)")
            if accounts:
                sample = accounts[0]
                currency = sample.get('currency', 'N/A')
                balance = sample.get('balance', '0')
                print(f"   Sample: {currency} - Balance: {balance}")
            return True
        elif 'error' in result:
            error_msg = result.get('error', 'Unknown error')
            print(f"❌ FAILED: {error_msg}")
            return False
        else:
            print(f"⚠️  WARNING: Unexpected response format")
            print(f"   Keys: {list(result.keys())[:5] if result else 'None'}")
            return False
    except Exception as e:
        error_str = str(e)
        # Redact any potential secrets in error messages
        if api_key and api_key in error_str:
            error_str = error_str.replace(api_key, redact_secret(api_key))
        print(f"❌ ERROR: {error_str}")
        return False

def main():
    print("="*60)
    print("Crypto.com API Smoke Test")
    print("="*60)
    
    # Test 1: Public endpoint
    public_ok = test_public_endpoint()
    
    # Test 2: Private endpoint
    client = CryptoComTradeClient()
    client.live_trading = True
    private_ok = test_private_endpoint(client)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Public API:  {'✅ PASS' if public_ok else '❌ FAIL'}")
    print(f"Private API: {'✅ PASS' if private_ok else '❌ FAIL'}")
    
    if public_ok and private_ok:
        print("\n✅ All tests passed!")
        return 0
    elif public_ok:
        print("\n⚠️  Public API works but private API fails")
        print("   This suggests an authentication/authorization issue")
        return 1
    else:
        print("\n❌ Public API failed - network/connectivity issue")
        return 1

if __name__ == "__main__":
    sys.exit(main())





