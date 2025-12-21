#!/usr/bin/env python3
"""
Script to set trade_amount_usd to 10 for all active watchlist items.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def set_all_trade_amounts(amount_usd: float = 10.0):
    """Set trade_amount_usd to specified amount for all active watchlist items."""
    db = SessionLocal()
    try:
        # Get all active (not deleted) watchlist items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not items:
            logger.warning("No active watchlist items found")
            return
        
        updated_count = 0
        for item in items:
            if item.trade_amount_usd != amount_usd:
                item.trade_amount_usd = amount_usd
                updated_count += 1
                logger.info(f"✅ Set trade_amount_usd to ${amount_usd} for {item.symbol}")
            else:
                logger.debug(f"⏭️  {item.symbol} already has trade_amount_usd = ${amount_usd}")
        
        db.commit()
        
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ Successfully updated trade_amount_usd for {updated_count} out of {len(items)} items")
        logger.info(f"{'='*60}")
        
        # Show summary
        with_amount = sum(1 for item in items if item.trade_amount_usd == amount_usd)
        
        logger.info(f"\nSummary:")
        logger.info(f"  - Total active items: {len(items)}")
        logger.info(f"  - Items with trade_amount_usd = ${amount_usd}: {with_amount}/{len(items)}")
        
        # Show items that still have different amounts
        different_amounts = [item for item in items if item.trade_amount_usd != amount_usd and item.trade_amount_usd is not None]
        if different_amounts:
            logger.warning(f"\n⚠️  Items with different amounts:")
            for item in different_amounts:
                logger.warning(f"    - {item.symbol}: ${item.trade_amount_usd}")
        
    except Exception as e:
        logger.error(f"❌ Error setting trade amounts: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Set trade_amount_usd for all watchlist items")
    parser.add_argument("--amount", type=float, default=10.0, help="Trade amount in USD (default: 10.0)")
    args = parser.parse_args()
    
    print("="*60)
    print("Set All Trade Amounts Script")
    print("="*60)
    print(f"Setting trade_amount_usd to ${args.amount} for all active items")
    print()
    set_all_trade_amounts(args.amount)














