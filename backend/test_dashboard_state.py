#!/usr/bin/env python3
"""
Test script to check what the dashboard state endpoint returns
"""
import sys
import os
import json

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_dashboard_state():
    """Test the dashboard state endpoint"""
    try:
        from app.api.routes_dashboard import get_dashboard_state
        from app.database import SessionLocal
        
        print("=" * 60)
        print("Testing Dashboard State Endpoint")
        print("=" * 60)
        
        db = SessionLocal()
        try:
            result = get_dashboard_state(db=db)
            
            print("\n📊 Dashboard State Response:")
            print(f"  - Source: {result.get('source', 'N/A')}")
            print(f"  - Total USD Value: ${result.get('total_usd_value', 0):,.2f}")
            print(f"  - Balances Count: {len(result.get('balances', []))}")
            print(f"  - Portfolio Assets Count: {len(result.get('portfolio', {}).get('assets', []))}")
            print(f"  - Open Orders Count: {len(result.get('open_orders', []))}")
            print(f"  - Fast Signals Count: {len(result.get('fast_signals', []))}")
            print(f"  - Slow Signals Count: {len(result.get('slow_signals', []))}")
            print(f"  - Partial: {result.get('partial', False)}")
            print(f"  - Errors: {result.get('errors', [])}")
            
            # Show first few balances
            balances = result.get('balances', [])
            if balances:
                print(f"\n💰 First 5 Balances:")
                for i, bal in enumerate(balances[:5], 1):
                    print(f"  {i}. {bal.get('asset', 'N/A')}: balance={bal.get('balance', 0)}, usd_value=${bal.get('usd_value', 0):,.2f}")
            else:
                print("\n⚠️  No balances found!")
            
            # Show portfolio assets
            portfolio = result.get('portfolio', {})
            assets = portfolio.get('assets', [])
            if assets:
                print(f"\n📈 First 5 Portfolio Assets:")
                for i, asset in enumerate(assets[:5], 1):
                    print(f"  {i}. {asset.get('coin', 'N/A')}: balance={asset.get('balance', 0)}, value_usd=${asset.get('value_usd', 0):,.2f}")
            else:
                print("\n⚠️  No portfolio assets found!")
            
            # Show open orders
            open_orders = result.get('open_orders', [])
            if open_orders:
                print(f"\n📋 First 3 Open Orders:")
                for i, order in enumerate(open_orders[:3], 1):
                    print(f"  {i}. {order.get('symbol', 'N/A')}: {order.get('side', 'N/A')} {order.get('order_type', 'N/A')} - Status: {order.get('status', 'N/A')}")
            else:
                print("\n⚠️  No open orders found!")
            
            # Check for errors
            errors = result.get('errors', [])
            if errors:
                print(f"\n❌ Errors found: {errors}")
            
            # Summary
            print("\n" + "=" * 60)
            if len(balances) > 0 or len(assets) > 0:
                print("✅ Portfolio data is being returned")
            else:
                print("❌ Portfolio data is EMPTY - this is the problem!")
            
            if len(open_orders) > 0:
                print("✅ Open orders are being returned")
            else:
                print("⚠️  No open orders (this might be normal if there are no open orders)")
            
            print("=" * 60)
            
            return result
            
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Error testing dashboard state: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_dashboard_state()

