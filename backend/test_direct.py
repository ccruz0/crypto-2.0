#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Test the exact same import path as the endpoint
from simple_price_fetcher import price_fetcher

print("Testing direct import...")
result = price_fetcher.get_price('DOGE_USDT')
print(f'Direct result: ${result.price} from {result.source} (success: {result.success})')

# Test the endpoint function directly
print("\nTesting endpoint function...")
import requests
url = "https://api.coinpaprika.com/v1/tickers/doge-dogecoin"
response = requests.get(url)
if response.status_code == 200:
    data = response.json()
    if "quotes" in data and "USD" in data["quotes"]:
        direct_price = data["quotes"]["USD"]["price"]
        print(f"Direct API call: ${direct_price}")
    else:
        print("No price data in response")
else:
    print(f"API call failed with status {response.status_code}")

# Test if there's a different fetcher being used
print("\nChecking if there are multiple fetchers...")
import importlib
import simple_price_fetcher
importlib.reload(simple_price_fetcher)
new_fetcher = simple_price_fetcher.price_fetcher
result2 = new_fetcher.get_price('DOGE_USDT')
print(f'Reloaded fetcher: ${result2.price} from {result2.source} (success: {result2.success})')

