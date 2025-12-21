#!/usr/bin/env python3
"""
Diagnostic script to check MarketData status via API
Identifies why RSI/Volume show defaults (50/0) instead of calculated values
"""
import requests
import json
from datetime import datetime
from typing import List, Dict, Optional

# API base URL - adjust if needed
API_BASE_URL = "https://dashboard.hilovivo.com/api"

def get_api_key() -> Optional[str]:
    """Try to get API key from environment or config"""
    import os
    return os.getenv("API_KEY") or os.getenv("X_API_KEY")

def check_market_data_via_dashboard():
    """Check MarketData by fetching watchlist items from dashboard endpoint"""
    print("=" * 80)
    print("MarketData Diagnostic Report (via API)")
    print("=" * 80)
    print()
    
    headers = {}
    api_key = get_api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    
    try:
        # Fetch watchlist items (they should be enriched with MarketData)
        print("Fetching watchlist items from /api/dashboard...")
        response = requests.get(f"{API_BASE_URL}/dashboard", headers=headers, timeout=30)
        response.raise_for_status()
        watchlist_items = response.json()
        
        if not watchlist_items:
            print("❌ No watchlist items returned!")
            return
        
        print(f"✅ Retrieved {len(watchlist_items)} watchlist items")
        print()
        
        # Analyze the data
        rsi_default_count = 0
        volume_zero_count = 0
        items_with_data = 0
        items_without_data = 0
        
        sample_items = watchlist_items[:10]  # Check first 10 items
        
        print("Sample Data Analysis (first 10 items):")
        print("-" * 80)
        print(f"{'Symbol':<12} | {'Price':<12} | {'RSI':<8} | {'Volume':<10} | {'MA50':<12} | Status")
        print("-" * 80)
        
        for item in sample_items:
            symbol = item.get("symbol", "UNKNOWN")
            price = item.get("price")
            rsi = item.get("rsi")
            volume_ratio = item.get("volume_ratio")  # Check if volume_ratio exists
            ma50 = item.get("ma50")
            
            # Check if values are defaults
            is_rsi_default = rsi is not None and abs(float(rsi) - 50.0) < 0.01
            is_volume_zero = volume_ratio is None or (volume_ratio is not None and abs(float(volume_ratio)) < 0.01)
            
            price_str = f"${price:.2f}" if price else "N/A"
            rsi_str = f"{rsi:.2f}" if rsi is not None else "NULL"
            vol_str = f"{volume_ratio:.2f}x" if volume_ratio is not None else "NULL"
            ma50_str = f"${ma50:.2f}" if ma50 else "NULL"
            
            # Determine status
            if price and not is_rsi_default and not is_volume_zero:
                status = "✅ REAL"
                items_with_data += 1
            elif price:
                status = "⚠️ DEFAULTS"
                items_without_data += 1
                if is_rsi_default:
                    rsi_default_count += 1
                if is_volume_zero:
                    volume_zero_count += 1
            else:
                status = "❌ NO DATA"
                items_without_data += 1
            
            print(f"{symbol:<12} | {price_str:<12} | {rsi_str:<8} | {vol_str:<10} | {ma50_str:<12} | {status}")
        
        print("-" * 80)
        print()
        
        # Overall statistics - count from all items, not just sample
        total_items = len(watchlist_items)
        total_rsi_default = 0
        total_volume_zero = 0
        
        for item in watchlist_items:
            rsi = item.get("rsi")
            volume_ratio = item.get("volume_ratio")
            
            if rsi is not None and abs(float(rsi) - 50.0) < 0.01:
                total_rsi_default += 1
            if volume_ratio is None or (volume_ratio is not None and abs(float(volume_ratio)) < 0.01):
                total_volume_zero += 1
        
        rsi_default_count = total_rsi_default
        volume_zero_count = total_volume_zero
        
        print("=" * 80)
        print("Summary:")
        print(f"  Total items checked: {total_items}")
        if total_items > 0:
            print(f"  Items with RSI=50 (default): {rsi_default_count}/{total_items} ({rsi_default_count*100/total_items:.1f}%)")
            print(f"  Items with Volume=0/NULL: {volume_zero_count}/{total_items} ({volume_zero_count*100/total_items:.1f}%)")
        print(f"  Items with real calculated values: {items_with_data}/{len(sample_items)} in sample")
        print()
        
        # Diagnostics
        if rsi_default_count == total_items:
            print("⚠️  ALL items have default RSI=50!")
            print("   Possible causes:")
            print("   1. Market updater process is NOT running")
            print("   2. Market updater is failing to fetch OHLCV data")
            print("   3. OHLCV fetches returning < 50 candles (insufficient data)")
            print()
            print("   Action: Check market-updater-aws logs on AWS:")
            print("   docker-compose --profile aws logs market-updater-aws --tail=100")
        elif rsi_default_count > total_items * 0.7:
            print("⚠️  Most items (>70%) have default RSI=50")
            print("   This suggests market updater is partially failing")
            print("   Check market-updater-aws logs for errors")
        else:
            print("✅ Most items have real RSI values (not defaults)")
        
        if volume_zero_count == total_items:
            print("⚠️  ALL items have Volume=0!")
            print("   Possible causes:")
            print("   1. Volume calculation failing in market updater")
            print("   2. 5-minute OHLCV data not available")
            print("   3. Volume calculation returning defaults")
        elif volume_zero_count > total_items * 0.7:
            print("⚠️  Most items (>70%) have Volume=0")
            print("   Volume calculation may be failing")
        else:
            print("✅ Most items have real volume values")
        
        # Check if we can get signals endpoint for one symbol to see raw data
        if sample_items:
            test_symbol = sample_items[0].get("symbol")
            if test_symbol:
                print()
                print(f"Checking /api/signals endpoint for {test_symbol}...")
                try:
                    signals_response = requests.get(
                        f"{API_BASE_URL}/signals",
                        params={
                            "exchange": "CRYPTO_COM",
                            "symbol": test_symbol
                        },
                        headers=headers,
                        timeout=10
                    )
                    if signals_response.status_code == 200:
                        signals_data = signals_response.json()
                        print(f"  RSI: {signals_data.get('rsi', 'N/A')}")
                        print(f"  Volume ratio: {signals_data.get('volume_ratio', 'N/A')}")
                        print(f"  Source: {signals_data.get('source', 'N/A')}")
                        if signals_data.get('rsi') == 50.0:
                            print("  ⚠️  Signals endpoint also returns default RSI=50")
                except Exception as e:
                    print(f"  ⚠️  Could not check signals endpoint: {e}")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ API Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"   Status Code: {e.response.status_code}")
            print(f"   Response: {e.response.text[:200]}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_market_data_via_dashboard()

