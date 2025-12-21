#!/usr/bin/env python3
"""
Script to add BTC_USDT to the watchlist database if it doesn't exist.
"""

import sys
import os
from pathlib import Path

# Add parent directories to path
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.config_loader import load_config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_btc_usdt_to_watchlist():
    """Add BTC_USDT to watchlist if it doesn't exist."""
    db = SessionLocal()
    
    try:
        symbol = "BTC_USDT"
        exchange = "CRYPTO_COM"
        
        # Check if it already exists
        existing = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.exchange == exchange
        ).first()
        
        if existing:
            # Check if it's deleted
            if hasattr(existing, 'is_deleted') and existing.is_deleted:
                logger.info(f"Found deleted {symbol}, restoring it...")
                existing.is_deleted = False
                db.commit()
                db.refresh(existing)
                logger.info(f"✅ Restored {symbol} to watchlist")
                return existing
            else:
                logger.info(f"✅ {symbol} already exists in watchlist (not deleted)")
                return existing
        
        # Load config to get preset
        cfg = load_config()
        coins = cfg.get("coins", {})
        coin_config = coins.get(symbol, {})
        preset = coin_config.get("preset", "swing")
        
        # Create new watchlist item
        logger.info(f"Creating new watchlist item for {symbol}...")
        item = WatchlistItem(
            symbol=symbol,
            exchange=exchange,
            is_deleted=False,
            alert_enabled=False,  # Default to False to prevent unwanted alerts
            trade_enabled=False,
            sl_tp_mode="conservative",  # Swing conservative
        )
        
        db.add(item)
        db.commit()
        db.refresh(item)
        
        logger.info(f"✅ Successfully added {symbol} to watchlist")
        logger.info(f"   - Symbol: {symbol}")
        logger.info(f"   - Exchange: {exchange}")
        logger.info(f"   - ID: {item.id}")
        logger.info(f"   - Preset (from config): {preset}")
        logger.info(f"   - sl_tp_mode: {item.sl_tp_mode}")
        
        return item
        
    except Exception as e:
        logger.error(f"Error adding {symbol} to watchlist: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Adding BTC_USDT to watchlist")
    logger.info("=" * 60)
    
    try:
        item = add_btc_usdt_to_watchlist()
        logger.info("\n✅ Done! BTC_USDT should now be visible in the watchlist.")
    except Exception as e:
        logger.error(f"\n❌ Failed: {e}")
        sys.exit(1)














