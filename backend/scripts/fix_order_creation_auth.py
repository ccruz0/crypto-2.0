#!/usr/bin/env python3
"""
Potential fix for order creation authentication issues
Tests different signature generation approaches for list parameters
"""

import os
import sys
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_params_to_str_list_handling():
    """
    Test how _params_to_str handles list parameters like exec_inst
    This is critical for margin orders which include exec_inst: ["MARGIN_ORDER"]
    """
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    
    client = CryptoComTradeClient()
    
    # Test case 1: Order with exec_inst (margin order)
    params_with_list = {
        "instrument_name": "BTC_USDT",
        "side": "SELL",
        "type": "MARKET",
        "quantity": "0.0001",
        "client_oid": "test-123",
        "leverage": "10",
        "exec_inst": ["MARGIN_ORDER"]
    }
    
    # Test case 2: Order without exec_inst (spot order)
    params_without_list = {
        "instrument_name": "BTC_USDT",
        "side": "SELL",
        "type": "MARKET",
        "quantity": "0.0001",
        "client_oid": "test-123"
    }
    
    print("="*60)
    print("Testing _params_to_str with list parameters")
    print("="*60)
    
    print("\n1. Params WITH exec_inst (margin order):")
    print(f"   Params: {json.dumps(params_with_list, indent=2)}")
    params_str_with = client._params_to_str(params_with_list, 0)
    print(f"   Params string: '{params_str_with}'")
    print(f"   Length: {len(params_str_with)}")
    
    print("\n2. Params WITHOUT exec_inst (spot order):")
    print(f"   Params: {json.dumps(params_without_list, indent=2)}")
    params_str_without = client._params_to_str(params_without_list, 0)
    print(f"   Params string: '{params_str_without}'")
    print(f"   Length: {len(params_str_without)}")
    
    print("\n3. Analysis:")
    print(f"   Difference: {len(params_str_with) - len(params_str_without)} characters")
    
    # Check if exec_inst is included correctly
    if "MARGIN_ORDER" in params_str_with:
        print("   ✅ 'MARGIN_ORDER' found in params string")
    else:
        print("   ❌ 'MARGIN_ORDER' NOT found in params string")
        print("   ⚠️  This could cause signature mismatch!")
    
    # Check alphabetical ordering
    sorted_keys = sorted(params_with_list.keys())
    print(f"\n4. Key ordering:")
    print(f"   Sorted keys: {sorted_keys}")
    print(f"   First key in string: {params_str_with[:len(sorted_keys[0])] if params_str_with else 'N/A'}")
    
    return params_str_with, params_str_without

def test_signature_generation():
    """Test signature generation for both cases"""
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    import hmac
    import hashlib
    import time
    
    client = CryptoComTradeClient()
    
    method = "private/create-order"
    request_id = 1
    api_key = client.api_key
    nonce = int(time.time() * 1000)
    
    # Test with exec_inst
    params_with_list = {
        "client_oid": "test-123",
        "exec_inst": ["MARGIN_ORDER"],
        "instrument_name": "BTC_USDT",
        "leverage": "10",
        "quantity": "0.0001",
        "side": "SELL",
        "type": "MARKET"
    }
    
    # Test without exec_inst
    params_without_list = {
        "client_oid": "test-123",
        "instrument_name": "BTC_USDT",
        "quantity": "0.0001",
        "side": "SELL",
        "type": "MARKET"
    }
    
    print("\n" + "="*60)
    print("Testing Signature Generation")
    print("="*60)
    
    for test_name, params in [("WITH exec_inst", params_with_list), ("WITHOUT exec_inst", params_without_list)]:
        print(f"\n{test_name}:")
        params_str = client._params_to_str(params, 0) if params else ""
        string_to_sign = method + str(request_id) + api_key + params_str + str(nonce)
        
        print(f"   Params string: '{params_str}'")
        print(f"   String to sign length: {len(string_to_sign)}")
        print(f"   String to sign preview: {string_to_sign[:50]}...{string_to_sign[-20:]}")
        
        signature = hmac.new(
            bytes(str(client.api_secret), 'utf-8'),
            msg=bytes(string_to_sign, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        print(f"   Signature: {signature[:20]}...{signature[-20:]}")

def suggest_fix():
    """Suggest potential fixes based on analysis"""
    print("\n" + "="*60)
    print("POTENTIAL FIXES")
    print("="*60)
    
    print("\n1. Check exec_inst formatting:")
    print("   - Verify exec_inst: ['MARGIN_ORDER'] is formatted correctly in signature")
    print("   - Crypto.com may require specific format for list parameters")
    
    print("\n2. Try removing exec_inst:")
    print("   - Some APIs don't require exec_inst in the request")
    print("   - The presence of 'leverage' parameter may be sufficient")
    print("   - Test with: is_margin=True but no exec_inst parameter")
    
    print("\n3. Check params ordering:")
    print("   - Ensure params in request body match signature order")
    print("   - Both should be alphabetically sorted")
    
    print("\n4. Verify list serialization:")
    print("   - Check if Crypto.com expects JSON array string vs concatenated values")
    print("   - Current: exec_inst values concatenated directly")
    print("   - Alternative: May need JSON.stringify(['MARGIN_ORDER']) in signature")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("ORDER CREATION AUTHENTICATION - PARAMS ANALYSIS")
    print("="*60)
    
    try:
        params_str_with, params_str_without = test_params_to_str_list_handling()
        test_signature_generation()
        suggest_fix()
        
        print("\n" + "="*60)
        print("RECOMMENDATION")
        print("="*60)
        print("\nIf authentication fails for margin orders but works for spot orders:")
        print("→ The issue is likely with how exec_inst list is formatted in signature")
        print("\nTry this fix:")
        print("1. Test creating a SPOT order (is_margin=False)")
        print("2. If spot works but margin fails, the issue is exec_inst formatting")
        print("3. Check Crypto.com documentation for exact list parameter format")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

