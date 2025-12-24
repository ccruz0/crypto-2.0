#!/usr/bin/env python3
"""
Test script to diagnose authentication issues specifically for order creation
Compares successful read operations vs order creation to identify differences
"""

import os
import sys
import requests
import hmac
import hashlib
import time
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient, _clean_env_secret, _preview_secret

def test_read_operation():
    """Test a read operation that we know works"""
    print("\n" + "="*60)
    print("TEST 1: Read Operation (get_account_summary)")
    print("="*60)
    
    client = CryptoComTradeClient()
    
    try:
        result = client.get_account_summary()
        if result and "accounts" in result:
            print("✅ Read operation SUCCESS")
            print(f"   Retrieved {len(result.get('accounts', []))} accounts")
            return True
        else:
            print("❌ Read operation returned unexpected format")
            print(f"   Result: {result}")
            return False
    except Exception as e:
        print(f"❌ Read operation FAILED: {e}")
        return False

def test_order_creation():
    """Test order creation with minimal params"""
    print("\n" + "="*60)
    print("TEST 2: Order Creation (place_market_order)")
    print("="*60)
    
    client = CryptoComTradeClient()
    
    # Enable diagnostic logging
    client.crypto_auth_diag = True
    
    # Try a small test order (will be dry-run if LIVE_TRADING=false)
    try:
        result = client.place_market_order(
            symbol="BTC_USDT",
            side="SELL",
            qty=0.0001,  # Very small quantity for testing
            is_margin=False,
            dry_run=True  # Use dry-run to avoid actual order
        )
        
        if result and "error" not in result:
            print("✅ Order creation SUCCESS (dry-run)")
            print(f"   Order ID: {result.get('order_id', 'N/A')}")
            return True
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            print(f"❌ Order creation FAILED: {error}")
            
            # Check if it's an authentication error
            error_str = str(error).upper()
            if "401" in error_str or "AUTHENTICATION" in error_str:
                print("\n🔍 AUTHENTICATION ERROR DETECTED")
                print("   This suggests a difference in how order creation is authenticated")
                print("   vs read operations.")
            
            return False
    except Exception as e:
        print(f"❌ Order creation EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

def compare_signature_generation():
    """Compare signature generation for read vs write operations"""
    print("\n" + "="*60)
    print("TEST 3: Compare Signature Generation")
    print("="*60)
    
    client = CryptoComTradeClient()
    
    # Test 1: Read operation signature (empty params)
    read_method = "private/user-balance"
    read_params = {}
    read_payload = client.sign_request(read_method, read_params)
    
    print(f"Read operation:")
    print(f"  Method: {read_method}")
    print(f"  Params: {read_params}")
    print(f"  Payload keys: {list(read_payload.keys())}")
    print(f"  Has sig: {'sig' in read_payload}")
    
    # Test 2: Write operation signature (with params)
    write_method = "private/create-order"
    write_params = {
        "instrument_name": "BTC_USDT",
        "side": "SELL",
        "type": "MARKET",
        "quantity": "0.0001",
        "client_oid": "test-123"
    }
    write_payload = client.sign_request(write_method, write_params)
    
    print(f"\nWrite operation:")
    print(f"  Method: {write_method}")
    print(f"  Params: {write_params}")
    print(f"  Payload keys: {list(write_payload.keys())}")
    print(f"  Has sig: {'sig' in write_payload}")
    
    # Compare
    print(f"\n🔍 Comparison:")
    print(f"  Same method format: {read_method.split('/')[0] == write_method.split('/')[0]}")
    print(f"  Read has params: {bool(read_params)}")
    print(f"  Write has params: {bool(write_params)}")
    print(f"  Both have sig: {'sig' in read_payload and 'sig' in write_payload}")

def check_connection_method():
    """Check if proxy vs direct connection is being used"""
    print("\n" + "="*60)
    print("TEST 4: Connection Method Check")
    print("="*60)
    
    client = CryptoComTradeClient()
    
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    
    print(f"USE_CRYPTO_PROXY env: {os.getenv('USE_CRYPTO_PROXY', 'not set')}")
    print(f"Client use_proxy: {client.use_proxy}")
    print(f"Client base_url: {getattr(client, 'base_url', 'N/A')}")
    print(f"Client live_trading: {client.live_trading}")
    
    if client.use_proxy:
        print(f"Proxy URL: {client.proxy_url}")
        print("⚠️  Using PROXY - order creation goes through proxy")
    else:
        print("✅ Using DIRECT connection - order creation goes directly to API")

def main():
    print("\n" + "="*60)
    print("ORDER CREATION AUTHENTICATION DIAGNOSTIC")
    print("="*60)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check credentials
    api_key = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    
    if not api_key or not api_secret:
        print("\n❌ ERROR: API credentials not configured")
        print("   Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        return 1
    
    print(f"\nAPI Key: {_preview_secret(api_key)}")
    print(f"API Secret: {'<SET>' if api_secret else '<NOT_SET>'}")
    
    # Run tests
    check_connection_method()
    compare_signature_generation()
    
    read_ok = test_read_operation()
    order_ok = test_order_creation()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    if read_ok and not order_ok:
        print("🔍 DIAGNOSIS: Read works but order creation fails")
        print("\nPossible causes:")
        print("1. Signature generation difference for params vs empty params")
        print("2. Request format difference (params ordering, serialization)")
        print("3. Endpoint-specific authentication requirements")
        print("4. Proxy vs direct connection difference")
        print("\nNext steps:")
        print("- Enable CRYPTO_AUTH_DIAG=true to see detailed signature logs")
        print("- Check backend logs for exact request/response")
        print("- Compare signature string_to_sign for read vs write")
    elif read_ok and order_ok:
        print("✅ Both operations work - issue may be intermittent or context-specific")
    else:
        print("❌ Both operations fail - check API credentials and IP whitelist")
    
    return 0 if (read_ok and order_ok) else 1

if __name__ == "__main__":
    sys.exit(main())

