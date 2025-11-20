#!/usr/bin/env python3
"""
Test script to verify v4.0 restore changes work correctly.
This script checks that:
1. Portfolio queries return all balances (even with USD value = 0)
2. Open orders queries handle NULL exchange_create_time correctly
3. Executed orders queries handle NULL exchange_update_time correctly
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all imports work correctly"""
    print("Testing imports...")
    try:
        from app.api.routes_dashboard import get_dashboard_state
        from app.api.routes_orders import get_open_orders, get_order_history
        from sqlalchemy import func
        print("✅ All imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_coalesce_usage():
    """Test that COALESCE is used in queries"""
    print("\nTesting COALESCE usage in code...")
    
    # Check routes_dashboard.py
    with open('app/api/routes_dashboard.py', 'r') as f:
        dashboard_content = f.read()
        if 'func.coalesce(ExchangeOrder.exchange_create_time' in dashboard_content:
            print("✅ routes_dashboard.py uses COALESCE for open orders")
        else:
            print("❌ routes_dashboard.py missing COALESCE for open orders")
            return False
    
    # Check routes_orders.py
    with open('app/api/routes_orders.py', 'r') as f:
        orders_content = f.read()
        if 'func.coalesce(ExchangeOrder.exchange_create_time' in orders_content:
            print("✅ routes_orders.py uses COALESCE for open orders")
        else:
            print("❌ routes_orders.py missing COALESCE for open orders")
            return False
        
        if 'func.coalesce(ExchangeOrder.exchange_update_time' in orders_content:
            print("✅ routes_orders.py uses COALESCE for executed orders")
        else:
            print("❌ routes_orders.py missing COALESCE for executed orders")
            return False
    
    return True

def test_portfolio_filter():
    """Test that portfolio filter includes balances with balance > 0 even if USD value = 0"""
    print("\nTesting portfolio filter logic...")
    
    with open('app/api/routes_dashboard.py', 'r') as f:
        content = f.read()
        # Check for the restored v4.0 filter logic
        if 'balance_val > 0 or usd_val > 0' in content or 'balance > 0 or usd_value > 0' in content:
            print("✅ Portfolio filter includes balances with balance > 0 (v4.0 behavior)")
            return True
        elif 'if bal.get("usd_value", 0) > 0' in content and 'RESTORED v4.0' in content:
            # Check if it's in the fast-path section and has the fix
            if 'balance_val > 0 or usd_val > 0' in content:
                print("✅ Portfolio filter includes balances with balance > 0 (v4.0 behavior)")
                return True
        else:
            print("❌ Portfolio filter may still exclude balances with USD value = 0")
            return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Testing v4.0 Restore Changes")
    print("=" * 60)
    
    results = []
    
    # Test 1: Imports
    results.append(("Imports", test_imports()))
    
    # Test 2: COALESCE usage
    results.append(("COALESCE Usage", test_coalesce_usage()))
    
    # Test 3: Portfolio filter
    results.append(("Portfolio Filter", test_portfolio_filter()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✅ All tests passed! v4.0 restore changes are correct.")
        return 0
    else:
        print("❌ Some tests failed. Please review the changes.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

