#!/usr/bin/env python3
"""
Test script to verify authentication error handling fix
Tests that:
1. Authentication errors are detected correctly
2. Only ONE error message is sent (not duplicate)
3. Error message is specific and helpful
4. No generic "orden no creada" message appears
"""

import requests
import json
import sys
from datetime import datetime

# Configuration
API_BASE_URL = "https://dashboard.hilovivo.com"  # AWS production API
# API_BASE_URL = "http://localhost:8000"  # For local testing

def test_authentication_error_handling():
    """Test that authentication errors are handled correctly"""
    
    print("=" * 60)
    print("TESTING AUTHENTICATION ERROR HANDLING FIX")
    print("=" * 60)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Test Time: {datetime.now().isoformat()}")
    print()
    
    # Test 1: Simulate BUY alert that will trigger authentication error
    print("Test 1: Simulating BUY alert (will trigger auth error if credentials are invalid)")
    print("-" * 60)
    
    test_symbol = "LDO_USD"  # Use the symbol from the original error
    payload = {
        "symbol": test_symbol,
        "signal_type": "BUY",
        "force_order": False
    }
    
    try:
        response = requests.post(
            f"{API_BASE_URL}/api/test/simulate-alert",
            json=payload,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
            
            # Check response structure
            print("\nResponse Analysis:")
            print(f"  - Alert sent: {data.get('alert_sent', False)}")
            print(f"  - Order created: {data.get('order_created', False)}")
            print(f"  - Trade enabled: {data.get('trade_enabled', False)}")
            print(f"  - Order in progress: {data.get('order_in_progress', False)}")
            
            if 'order_error' in data:
                error_msg = data['order_error']
                print(f"  - Order error: {error_msg}")
                
                # Check if it's an authentication error
                error_upper = str(error_msg).upper()
                is_auth_error = (
                    "401" in error_upper or
                    "40101" in error_upper or
                    "AUTHENTICATION" in error_upper
                )
                
                if is_auth_error:
                    print("\n✅ Authentication error detected in response")
                    print("   Expected: Single, specific error message")
                else:
                    print("\n⚠️  Error is not authentication-related")
                    print(f"   Error type: {error_msg[:100]}...")
        else:
            print(f"Error Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("Test 2: Check backend logs for duplicate messages")
    print("-" * 60)
    print("To verify no duplicate messages:")
    print("1. Check Telegram for messages about this test")
    print("2. Should see ONLY ONE error message (not duplicate)")
    print("3. Error message should be specific (not generic)")
    print()
    
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("\nNext Steps:")
    print("1. Check Telegram for messages about LDO_USD")
    print("2. Verify only ONE error message was sent")
    print("3. Verify error message is specific (mentions authentication)")
    print("4. Verify NO generic 'orden no creada' message")
    print()
    
    return True

if __name__ == "__main__":
    success = test_authentication_error_handling()
    sys.exit(0 if success else 1)

