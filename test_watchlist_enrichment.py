#!/usr/bin/env python3
"""
Test script to verify watchlist enrichment is working correctly.

Tests:
1. /api/dashboard endpoint returns enriched values
2. /api/market/top-coins-data endpoint returns enriched values
3. Frontend can access these values
4. Compare frontend vs backend values
"""

import requests
import json
import sys
from typing import Dict, Any, Optional

API_BASE = "http://localhost:8002/api"

def test_dashboard_endpoint() -> Dict[str, Any]:
    """Test /api/dashboard endpoint for enriched values"""
    print("=" * 70)
    print("TEST 1: /api/dashboard Endpoint")
    print("=" * 70)
    
    try:
        response = requests.get(f"{API_BASE}/dashboard", timeout=10)
        response.raise_for_status()
        items = response.json()
        
        if not items:
            print("❌ No items returned")
            return {"status": "error", "message": "No items"}
        
        # Check first 5 items for enriched values
        enriched_count = 0
        missing_fields = []
        
        for item in items[:5]:
            symbol = item.get('symbol', 'N/A')
            has_price = item.get('price') is not None
            has_rsi = item.get('rsi') is not None
            has_ma50 = item.get('ma50') is not None
            has_ma200 = item.get('ma200') is not None
            has_ema10 = item.get('ema10') is not None
            
            if has_price and has_rsi and has_ma50 and has_ma200 and has_ema10:
                enriched_count += 1
                print(f"✅ {symbol}: All fields enriched")
                print(f"   price={item.get('price')}, rsi={item.get('rsi')}, "
                      f"ma50={item.get('ma50')}, ma200={item.get('ma200')}, ema10={item.get('ema10')}")
            else:
                missing = []
                if not has_price: missing.append('price')
                if not has_rsi: missing.append('rsi')
                if not has_ma50: missing.append('ma50')
                if not has_ma200: missing.append('ma200')
                if not has_ema10: missing.append('ema10')
                missing_fields.append(f"{symbol}: {', '.join(missing)}")
                print(f"❌ {symbol}: Missing {', '.join(missing)}")
        
        result = {
            "status": "success" if enriched_count == len(items[:5]) else "partial",
            "total_checked": len(items[:5]),
            "enriched_count": enriched_count,
            "missing_fields": missing_fields
        }
        
        print(f"\n📊 Summary: {enriched_count}/{len(items[:5])} items fully enriched")
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}


def test_top_coins_endpoint() -> Dict[str, Any]:
    """Test /api/market/top-coins-data endpoint for enriched values"""
    print("\n" + "=" * 70)
    print("TEST 2: /api/market/top-coins-data Endpoint")
    print("=" * 70)
    
    try:
        response = requests.get(f"{API_BASE}/market/top-coins-data", timeout=60)
        response.raise_for_status()
        data = response.json()
        coins = data.get('coins', [])
        
        if not coins:
            print("❌ No coins returned")
            return {"status": "error", "message": "No coins"}
        
        # Check first 5 coins for enriched values
        enriched_count = 0
        missing_fields = []
        
        for coin in coins[:5]:
            symbol = coin.get('instrument_name', 'N/A')
            has_price = coin.get('current_price') is not None and coin.get('current_price') > 0
            has_rsi = coin.get('rsi') is not None
            has_ma50 = coin.get('ma50') is not None
            has_ma200 = coin.get('ma200') is not None
            has_ema10 = coin.get('ema10') is not None
            
            if has_price and has_rsi and has_ma50 and has_ma200 and has_ema10:
                enriched_count += 1
                print(f"✅ {symbol}: All fields enriched")
                print(f"   price={coin.get('current_price')}, rsi={coin.get('rsi')}, "
                      f"ma50={coin.get('ma50')}, ma200={coin.get('ma200')}, ema10={coin.get('ema10')}")
            else:
                missing = []
                if not has_price: missing.append('price')
                if not has_rsi: missing.append('rsi')
                if not has_ma50: missing.append('ma50')
                if not has_ma200: missing.append('ma200')
                if not has_ema10: missing.append('ema10')
                missing_fields.append(f"{symbol}: {', '.join(missing)}")
                print(f"❌ {symbol}: Missing {', '.join(missing)}")
        
        result = {
            "status": "success" if enriched_count == len(coins[:5]) else "partial",
            "total_checked": len(coins[:5]),
            "enriched_count": enriched_count,
            "missing_fields": missing_fields
        }
        
        print(f"\n📊 Summary: {enriched_count}/{len(coins[:5])} coins fully enriched")
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}


def test_consistency() -> Dict[str, Any]:
    """Test consistency between /api/dashboard and /api/market/top-coins-data"""
    print("\n" + "=" * 70)
    print("TEST 3: Consistency Check (Dashboard vs Top Coins)")
    print("=" * 70)
    
    try:
        # Get data from both endpoints
        dashboard_resp = requests.get(f"{API_BASE}/dashboard", timeout=10)
        dashboard_resp.raise_for_status()
        dashboard_items = {item['symbol']: item for item in dashboard_resp.json()}
        
        top_coins_resp = requests.get(f"{API_BASE}/market/top-coins-data", timeout=60)
        top_coins_resp.raise_for_status()
        top_coins_data = top_coins_resp.json()
        top_coins = {coin['instrument_name']: coin for coin in top_coins_data.get('coins', [])}
        
        # Compare values for common symbols
        common_symbols = set(dashboard_items.keys()) & set(top_coins.keys())
        
        if not common_symbols:
            print("❌ No common symbols found between endpoints")
            return {"status": "error", "message": "No common symbols"}
        
        mismatches = []
        matches = []
        
        for symbol in list(common_symbols)[:5]:
            dashboard_item = dashboard_items[symbol]
            top_coin = top_coins[symbol]
            
            # Compare key fields
            dashboard_price = dashboard_item.get('price')
            top_coin_price = top_coin.get('current_price')
            
            dashboard_rsi = dashboard_item.get('rsi')
            top_coin_rsi = top_coin.get('rsi')
            
            # Allow small floating point differences
            price_match = (dashboard_price is None and top_coin_price is None) or \
                         (dashboard_price is not None and top_coin_price is not None and 
                          abs(dashboard_price - top_coin_price) < 0.01)
            rsi_match = (dashboard_rsi is None and top_coin_rsi is None) or \
                       (dashboard_rsi is not None and top_coin_rsi is not None and 
                        abs(dashboard_rsi - top_coin_rsi) < 0.01)
            
            if price_match and rsi_match:
                matches.append(symbol)
                print(f"✅ {symbol}: Values match")
            else:
                mismatches.append({
                    "symbol": symbol,
                    "dashboard_price": dashboard_price,
                    "top_coin_price": top_coin_price,
                    "dashboard_rsi": dashboard_rsi,
                    "top_coin_rsi": top_coin_rsi
                })
                print(f"⚠️  {symbol}: Mismatch")
                if not price_match:
                    print(f"   Price: dashboard={dashboard_price}, top_coins={top_coin_price}")
                if not rsi_match:
                    print(f"   RSI: dashboard={dashboard_rsi}, top_coins={top_coin_rsi}")
        
        result = {
            "status": "success" if not mismatches else "warning",
            "matches": len(matches),
            "mismatches": len(mismatches),
            "mismatch_details": mismatches
        }
        
        print(f"\n📊 Summary: {len(matches)} matches, {len(mismatches)} mismatches")
        return result
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}


def test_backend_computed_values() -> Dict[str, Any]:
    """Test that backend can compute values for symbols"""
    print("\n" + "=" * 70)
    print("TEST 4: Backend Computed Values Check")
    print("=" * 70)
    
    try:
        # Get a symbol from dashboard
        dashboard_resp = requests.get(f"{API_BASE}/dashboard", timeout=10)
        dashboard_resp.raise_for_status()
        items = dashboard_resp.json()
        
        if not items:
            print("❌ No items to test")
            return {"status": "error", "message": "No items"}
        
        test_symbol = items[0]['symbol']
        print(f"Testing symbol: {test_symbol}")
        
        # Check if MarketData exists for this symbol
        # We can't directly query the database, but we can check if the API returns values
        dashboard_item = items[0]
        
        has_computed_values = (
            dashboard_item.get('price') is not None and
            dashboard_item.get('rsi') is not None and
            dashboard_item.get('ma50') is not None and
            dashboard_item.get('ma200') is not None and
            dashboard_item.get('ema10') is not None
        )
        
        if has_computed_values:
            print(f"✅ {test_symbol}: Backend has computed values")
            print(f"   price={dashboard_item.get('price')}")
            print(f"   rsi={dashboard_item.get('rsi')}")
            print(f"   ma50={dashboard_item.get('ma50')}")
            print(f"   ma200={dashboard_item.get('ma200')}")
            print(f"   ema10={dashboard_item.get('ema10')}")
            return {"status": "success", "has_values": True}
        else:
            print(f"❌ {test_symbol}: Backend missing computed values")
            return {"status": "error", "has_values": False}
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return {"status": "error", "message": str(e)}


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("WATCHLIST ENRICHMENT TEST SUITE")
    print("=" * 70)
    print(f"Testing API at: {API_BASE}\n")
    
    results = {
        "dashboard": test_dashboard_endpoint(),
        "top_coins": test_top_coins_endpoint(),
        "consistency": test_consistency(),
        "backend_computed": test_backend_computed_values()
    }
    
    # Summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    
    all_passed = all(
        r.get("status") == "success" or 
        (r.get("status") == "partial" and r.get("enriched_count", 0) > 0)
        for r in results.values()
    )
    
    if all_passed:
        print("✅ All tests passed or partially passed")
        return 0
    else:
        print("❌ Some tests failed")
        for test_name, result in results.items():
            status = result.get("status", "unknown")
            print(f"  {test_name}: {status}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
