#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the exact same modules as the server
from simple_price_fetcher import price_fetcher

print("=== DEBUGGING SERVER PRICE FETCHING ===")
print(f"Fetcher module: {price_fetcher}")
print(f"Fetcher class: {price_fetcher.__class__}")

# Test DOGE price
result = price_fetcher.get_price('DOGE_USDT')
print(f"DOGE_USDT result: ${result.price} from {result.source}")
print(f"Success: {result.success}")
print(f"Error: {result.error}")

# Test BTC price
result = price_fetcher.get_price('BTC_USDT')
print(f"BTC_USDT result: ${result.price} from {result.source}")
print(f"Success: {result.success}")
print(f"Error: {result.error}")

# Check if there's a different instance being used
print(f"\nFetcher cache: {price_fetcher.cache}")
print(f"Fetcher mappings: {list(price_fetcher.symbol_mappings.keys())[:5]}...")

# Test the exact same logic as the endpoint
print("\n=== TESTING ENDPOINT LOGIC ===")
symbol = "DOGE_USDT"
price_result = price_fetcher.get_price(symbol)
current_price = price_result.price if price_result.success else 1.0
print(f"Endpoint logic result: ${current_price}")
print(f"price_result.success: {price_result.success}")
print(f"price_result.source: {price_result.source}")

