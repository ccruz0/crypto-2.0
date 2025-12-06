#!/usr/bin/env python3
"""
Diagnostic script to inspect watchlist_items and MarketPrice counts.

Usage:
    cd backend
    python tools/inspect_watchlist_counts.py
"""

import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice

def main():
    db = SessionLocal()
    try:
        # Count watchlist_items
        total_watchlist_items = db.query(WatchlistItem).count()
        active_watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).count()
        deleted_watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == True
        ).count()
        
        print("=" * 60)
        print("WATCHLIST_ITEMS STATISTICS")
        print("=" * 60)
        print(f"Total rows: {total_watchlist_items}")
        print(f"Active (is_deleted=False): {active_watchlist_items}")
        print(f"Deleted (is_deleted=True): {deleted_watchlist_items}")
        
        # Sample symbols from watchlist_items
        if active_watchlist_items > 0:
            active_items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).limit(10).all()
            print(f"\nSample active symbols ({min(10, active_watchlist_items)}):")
            for item in active_items:
                print(f"  - {item.symbol} (exchange: {item.exchange})")
        
        if deleted_watchlist_items > 0:
            deleted_items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == True
            ).limit(10).all()
            print(f"\nSample deleted symbols ({min(10, deleted_watchlist_items)}):")
            for item in deleted_items:
                print(f"  - {item.symbol} (exchange: {item.exchange})")
        
        # Count MarketPrice entries
        total_market_prices = db.query(MarketPrice).count()
        
        print("\n" + "=" * 60)
        print("MARKETPRICE STATISTICS")
        print("=" * 60)
        print(f"Total rows: {total_market_prices}")
        
        # Sample symbols from MarketPrice
        if total_market_prices > 0:
            market_prices = db.query(MarketPrice).limit(20).all()
            print(f"\nSample symbols ({min(20, total_market_prices)}):")
            for mp in market_prices:
                print(f"  - {mp.symbol}: price={mp.price}")
        
        # Compare: symbols in MarketPrice but not in watchlist_items
        market_symbols = {mp.symbol for mp in db.query(MarketPrice).all()}
        watchlist_symbols = {item.symbol for item in db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()}
        
        missing_in_watchlist = market_symbols - watchlist_symbols
        print("\n" + "=" * 60)
        print("COMPARISON")
        print("=" * 60)
        print(f"Symbols in MarketPrice: {len(market_symbols)}")
        print(f"Symbols in watchlist_items (active): {len(watchlist_symbols)}")
        print(f"Symbols in MarketPrice but NOT in watchlist_items: {len(missing_in_watchlist)}")
        
        if missing_in_watchlist:
            print(f"\nMissing symbols (first 20):")
            for symbol in sorted(list(missing_in_watchlist))[:20]:
                print(f"  - {symbol}")
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

