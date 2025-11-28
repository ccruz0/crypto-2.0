#!/usr/bin/env python3
"""Count alerts from API endpoint"""
import json
import sys
import urllib.request

try:
    url = "https://dashboard.hilovivo.com/api/dashboard"
    req = urllib.request.Request(url)
    req.add_header("Content-Type", "application/json")
    
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read())
        items = data if isinstance(data, list) else []
        
        buy_yes = sum(1 for i in items if i.get('buy_alert_enabled'))
        sell_yes = sum(1 for i in items if i.get('sell_alert_enabled'))
        both_yes = sum(1 for i in items if i.get('buy_alert_enabled') and i.get('sell_alert_enabled'))
        trade_yes = sum(1 for i in items if i.get('trade_enabled'))
        
        buy_coins = [i.get('symbol', '') for i in items if i.get('buy_alert_enabled')]
        sell_coins = [i.get('symbol', '') for i in items if i.get('sell_alert_enabled')]
        both_coins = [i.get('symbol', '') for i in items if i.get('buy_alert_enabled') and i.get('sell_alert_enabled')]
        trade_coins = [i.get('symbol', '') for i in items if i.get('trade_enabled')]
        
        print('=' * 60)
        print('ALERT STATUS SUMMARY')
        print('=' * 60)
        print(f'\nTotal watchlist items: {len(items)}')
        print(f'\nBUY Alerts Enabled: {buy_yes} coins')
        print(f'SELL Alerts Enabled: {sell_yes} coins')
        print(f'Both BUY & SELL Enabled: {both_yes} coins')
        print(f'TRADE Enabled: {trade_yes} coins')
        
        print(f'\n{"─" * 60}')
        print(f'Coins with BUY alerts ({buy_yes}):')
        if buy_coins:
            print(f'  {", ".join(buy_coins)}')
        else:
            print('  None')
        
        print(f'\nCoins with SELL alerts ({sell_yes}):')
        if sell_coins:
            print(f'  {", ".join(sell_coins)}')
        else:
            print('  None')
        
        print(f'\nCoins with BOTH alerts ({both_yes}):')
        if both_coins:
            print(f'  {", ".join(both_coins)}')
        else:
            print('  None')
        
        print(f'\nCoins with TRADE enabled ({trade_yes}):')
        if trade_coins:
            print(f'  {", ".join(trade_coins)}')
        else:
            print('  None')
        
        print('=' * 60)
        
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)





