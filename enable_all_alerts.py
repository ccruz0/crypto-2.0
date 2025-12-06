#!/usr/bin/env python3
"""Enable all BUY and SELL alerts for all watchlist items"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from sqlalchemy import update

def enable_all_alerts():
    """Enable buy_alert_enabled and sell_alert_enabled for all non-deleted watchlist items"""
    db = SessionLocal()
    try:
        # Get count of items to update
        count_query = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).count()
        
        print(f"�� Found {count_query} non-deleted watchlist items to update")
        
        # Update all non-deleted items
        updated = db.execute(
            update(WatchlistItem)
            .where(WatchlistItem.is_deleted == False)
            .values(
                buy_alert_enabled=True,
                sell_alert_enabled=True
            )
        )
        
        db.commit()
        
        print(f"✅ Successfully enabled BUY and SELL alerts for {updated.rowcount} watchlist items")
        
        # Verify the update
        enabled_buy = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.buy_alert_enabled == True
        ).count()
        
        enabled_sell = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.sell_alert_enabled == True
        ).count()
        
        print(f"📊 Verification:")
        print(f"   - Items with buy_alert_enabled=True: {enabled_buy}/{count_query}")
        print(f"   - Items with sell_alert_enabled=True: {enabled_sell}/{count_query}")
        
        return True
    except Exception as e:
        print(f"❌ Error enabling alerts: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("🔄 Enabling all BUY and SELL alerts for all watchlist items...")
    success = enable_all_alerts()
    sys.exit(0 if success else 1)
