#!/usr/bin/env python3

from simple_price_fetcher import price_fetcher

# Test DOGE price
result = price_fetcher.get_price('DOGE_USDT')
print(f'DOGE_USDT: ${result.price} from {result.source} (success: {result.success})')
if result.error:
    print(f'Error: {result.error}')

# Test BTC price
result = price_fetcher.get_price('BTC_USDT')
print(f'BTC_USDT: ${result.price} from {result.source} (success: {result.success})')
if result.error:
    print(f'Error: {result.error}')

