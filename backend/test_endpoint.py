#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from simple_price_fetcher import price_fetcher

# Simulate the endpoint logic
symbol = "DOGE_USDT"
exchange = "CRYPTO_COM"

print(f"Testing endpoint logic for {symbol}...")

# Get current price with caching
price_result = price_fetcher.get_price(symbol)
current_price = price_result.price if price_result.success else 1.0

print(f"💰 Price for {symbol}: ${current_price} from {price_result.source}")
print(f"Success: {price_result.success}")
if price_result.error:
    print(f"Error: {price_result.error}")

# Test the price directly
print(f"\nDirect API test:")
import requests
url = "https://api.coinpaprika.com/v1/tickers/doge-dogecoin"
response = requests.get(url)
if response.status_code == 200:
    data = response.json()
    if "quotes" in data and "USD" in data["quotes"]:
        direct_price = data["quotes"]["USD"]["price"]
        print(f"Direct API price: ${direct_price}")
    else:
        print("No price data in direct API response")
else:
    print(f"Direct API failed with status {response.status_code}")

