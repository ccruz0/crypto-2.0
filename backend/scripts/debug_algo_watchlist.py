#!/usr/bin/env python3
"""Debug script to check ALGO_USDT in watchlist"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from sqlalchemy import or_

def main():
    db = SessionLocal()
    try:
        # Query all ALGO-related rows
        algo_items = db.query(WatchlistItem).filter(
            or_(
                WatchlistItem.symbol.ilike('%ALGO%'),
                WatchlistItem.symbol == 'ALGO_USDT',
                WatchlistItem.symbol == 'ALGO_USD',
            )
        ).all()
        
        print(f"Found {len(algo_items)} ALGO-related watchlist items:")
        print("-" * 80)
        
        for item in algo_items:
            print(f"ID: {item.id}")
            print(f"  Symbol: {item.symbol}")
            print(f"  alert_enabled: {getattr(item, 'alert_enabled', None)}")
            print(f  "  buy_alert_enabled: {getattr(item, 'buy_alert_enabled', None)}")
            print(f"  sell_alert_enabled: {getattr(item, 'sell_alert_enabled', None)}")
            print(f"  trade_enabled: {getattr(item, 'trade_enabled', None)}")
            print(f"  is_deleted: {getattr(item, 'is_deleted', None)}")
            print(f"  exchange: {getattr(item, 'exchange', None)}")
            print(f"  preset: {getattr(item, 'preset', None)}")
            print(f"  strategy_key: {getattr(item, 'strategy_key', None)}")
            print(f"  trade_amount_usd: {getattr(item, 'trade_amount_usd', None)}")
            print(f"  purchase_price: {getattr(item, 'purchase_price', None)}")
            print("-" * 80)
        
        # Check specifically for ALGO_USDT
        algo_usdt = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'ALGO_USDT'
        ).first()
        
        if algo_usdt:
            print(f"\n✅ ALGO_USDT found:")
            print(f"  alert_enabled: {algo_usdt.alert_enabled}")
            print(f"  is_deleted: {getattr(algo_usdt, 'is_deleted', False)}")
            if not algo_usdt.alert_enabled:
                print("  ⚠️  WARNING: alert_enabled is False!")
            if getattr(algo_usdt, 'is_deleted', False):
                print("  ⚠️  WARNING: is_deleted is True!")
        else:
            print("\n❌ ALGO_USDT NOT FOUND in watchlist!")
            
    finally:
        db.close()

if __name__ == "__main__":
    main()




















