#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_price_fetcher import price_fetcher

if __name__ == "__main__":
    print("Testing CoinGecko fallback...")
    
    # Test DOGE_USDT
    result = price_fetcher.get_price("DOGE_USDT")
    print(f"DOGE_USDT: ${result.price} from {result.source} (success: {result.success})")
    if not result.success:
        print(f"Error: {result.error}")
    
    # Test BTC_USDT
    result = price_fetcher.get_price("BTC_USDT")
    print(f"BTC_USDT: ${result.price} from {result.source} (success: {result.success})")
    if not result.success:
        print(f"Error: {result.error}")
    
    # Test direct CoinGecko call
    import requests
    try:
        response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=dogecoin&vs_currencies=usd", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"Direct CoinGecko DOGE: ${data['dogecoin']['usd']}")
        else:
            print(f"CoinGecko direct call failed: {response.status_code}")
    except Exception as e:
        print(f"CoinGecko direct call error: {e}")

