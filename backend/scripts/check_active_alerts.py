#!/usr/bin/env python3
"""Script to check active alert toggles in watchlist"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    try:
        # Get all non-deleted items
        all_items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
        
        # Count active toggles
        buy_count = sum(1 for item in all_items if item.buy_alert_enabled == True)
        sell_count = sum(1 for item in all_items if item.sell_alert_enabled == True)
        total_toggles = buy_count + sell_count
        
        print(f"📊 Watchlist Items (not deleted): {len(all_items)}")
        print(f"🟢 BUY toggles active: {buy_count}")
        print(f"🔴 SELL toggles active: {sell_count}")
        print(f"📈 TOTAL active toggles: {total_toggles}")
        print("")
        print("📋 Items with active alerts:")
        
        items_with_alerts = [item for item in all_items if item.buy_alert_enabled == True or item.sell_alert_enabled == True]
        for item in items_with_alerts[:30]:  # Show first 30
            buy = "✅" if item.buy_alert_enabled else "❌"
            sell = "✅" if item.sell_alert_enabled else "❌"
            print(f"  {item.symbol}: BUY={buy} SELL={sell}")
        
        if len(items_with_alerts) > 30:
            print(f"  ... and {len(items_with_alerts) - 30} more")
        
        print("")
        print(f"✅ Expected Active Alerts count: {total_toggles}")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()











