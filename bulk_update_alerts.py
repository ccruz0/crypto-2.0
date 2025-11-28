#!/usr/bin/env python3
"""
Bulk update script to set all BUY/SELL alerts to YES and all TRADE to NO.

This script:
1. Sets buy_alert_enabled = True for all watchlist items
2. Sets sell_alert_enabled = True for all watchlist items
3. Sets trade_enabled = False for all watchlist items

Usage:
    python bulk_update_alerts.py
"""

import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def bulk_update_alerts():
    """Update all watchlist items: BUY/SELL alerts = YES, TRADE = NO"""
    db = SessionLocal()
    
    try:
        # Get all active watchlist items (not deleted)
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not items:
            logger.warning("No watchlist items found")
            return
        
        logger.info(f"Found {len(items)} watchlist items to update")
        
        updated_count = 0
        for item in items:
            changes = []
            
            # Set BUY alert to YES
            if not item.buy_alert_enabled:
                item.buy_alert_enabled = True
                changes.append("BUY alert: NO -> YES")
            
            # Set SELL alert to YES
            if not item.sell_alert_enabled:
                item.sell_alert_enabled = True
                changes.append("SELL alert: NO -> YES")
            
            # Set TRADE to NO
            if item.trade_enabled:
                item.trade_enabled = False
                changes.append("TRADE: YES -> NO")
            
            if changes:
                updated_count += 1
                logger.info(f"Updated {item.symbol}: {', '.join(changes)}")
        
        # Commit all changes
        db.commit()
        logger.info(f"✅ Successfully updated {updated_count} watchlist items")
        logger.info(f"   - BUY alerts: All set to YES")
        logger.info(f"   - SELL alerts: All set to YES")
        logger.info(f"   - TRADE: All set to NO")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating watchlist items: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("🔄 Starting bulk update of watchlist alerts...")
    print("   Setting all BUY/SELL alerts to YES")
    print("   Setting all TRADE to NO")
    print()
    
    try:
        bulk_update_alerts()
        print()
        print("✅ Bulk update completed successfully!")
    except Exception as e:
        print()
        print(f"❌ Bulk update failed: {e}")
        sys.exit(1)


