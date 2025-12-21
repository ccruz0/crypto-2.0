#!/usr/bin/env python3
"""
Script to set trade_amount_usd for a specific symbol.
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

def set_trade_amount(symbol: str, amount_usd: float):
    """Set trade_amount_usd for a specific symbol."""
    db = SessionLocal()
    try:
        symbol = symbol.upper()
        
        # Find the watchlist item
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not item:
            logger.error(f"❌ Watchlist item not found for symbol: {symbol}")
            return False
        
        old_amount = item.trade_amount_usd
        item.trade_amount_usd = amount_usd
        db.commit()
        db.refresh(item)
        
        logger.info(f"✅ Updated {symbol}: trade_amount_usd = ${old_amount} → ${amount_usd}")
        logger.info(f"   Current settings:")
        logger.info(f"   - trade_enabled: {item.trade_enabled}")
        logger.info(f"   - trade_amount_usd: ${item.trade_amount_usd}")
        logger.info(f"   - trade_on_margin: {item.trade_on_margin}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error setting trade amount: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Set trade_amount_usd for a specific symbol")
    parser.add_argument("symbol", type=str, help="Trading symbol (e.g., BTC_USD)")
    parser.add_argument("amount", type=float, help="Trade amount in USD")
    args = parser.parse_args()
    
    print("="*60)
    print("Set Trade Amount Script")
    print("="*60)
    print(f"Setting trade_amount_usd to ${args.amount} for {args.symbol}")
    print()
    set_trade_amount(args.symbol, args.amount)














