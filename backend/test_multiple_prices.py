#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_price_fetcher import price_fetcher

if __name__ == "__main__":
    print("Testing get_multiple_prices...")
    
    symbols = ["BTC_USDT", "ETH_USDT", "DOGE_USDT"]
    results = price_fetcher.get_multiple_prices(symbols)
    
    for symbol, result in results.items():
        print(f"{symbol}: ${result.price} from {result.source} (success: {result.success})")
        if not result.success:
            print(f"  Error: {result.error}")

