#!/usr/bin/env python3
"""Check watchlist runtime state for ALGO, LDO, TON"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import get_canonical_watchlist_item
import json

def main():
    db = SessionLocal()
    try:
        symbols = ["ALGO_USDT", "LDO_USDT", "TON_USDT"]
        print("="*60)
        print("WATCHLIST RUNTIME STATE CHECK")
        print("="*60)
        
        for symbol in symbols:
            item = get_canonical_watchlist_item(db, symbol)
            if item:
                print(f"\n{symbol}:")
                print(f"  ID: {item.id}")
                print(f"  alert_enabled: {item.alert_enabled}")
                print(f"  buy_alert_enabled: {getattr(item, 'buy_alert_enabled', False)}")
                print(f"  trade_enabled: {item.trade_enabled}")
                print(f"  trade_amount_usd: {item.trade_amount_usd}")
            else:
                print(f"\n{symbol}: No watchlist item found")
    finally:
        db.close()

if __name__ == "__main__":
    main()






