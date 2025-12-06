#!/usr/bin/env python3

from simple_price_fetcher import price_fetcher

# Clear cache
price_fetcher.cache = {}

# Test DOGE price after clearing cache
result = price_fetcher.get_price('DOGE_USDT')
print(f'DOGE_USDT after cache clear: ${result.price} from {result.source} (success: {result.success})')
if result.error:
    print(f'Error: {result.error}')

