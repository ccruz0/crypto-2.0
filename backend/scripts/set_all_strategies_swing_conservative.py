#!/usr/bin/env python3
"""
Script to set all strategies to "Swing conservative".

This updates:
1. trading_config.json: Sets all coins' preset to "swing"
2. Database watchlist_items: Sets all items' sl_tp_mode to "conservative"
"""

import sys
import os
import json
from pathlib import Path

# Add parent directories to path
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.config_loader import CONFIG_PATH, load_config, save_config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_trading_config():
    """Update all coins in trading_config.json to use 'swing' preset."""
    logger.info(f"Loading config from {CONFIG_PATH}")
    cfg = load_config()
    
    coins = cfg.get("coins", {})
    updated_count = 0
    
    for symbol, coin_config in coins.items():
        old_preset = coin_config.get("preset")
        # Set preset to "swing" (without risk suffix, as risk is handled by sl_tp_mode)
        if old_preset != "swing":
            coin_config["preset"] = "swing"
            updated_count += 1
            logger.info(f"Updated {symbol}: {old_preset} -> swing")
    
    if updated_count > 0:
        logger.info(f"Saving config with {updated_count} coin updates...")
        save_config(cfg)
        logger.info("✅ Config saved successfully")
    else:
        logger.info("No coins needed updating in config (all already set to 'swing')")
    
    return updated_count


def update_database_watchlist():
    """Update all watchlist items in database to have sl_tp_mode='conservative'."""
    try:
        db = SessionLocal()
        updated_count = 0
        
        try:
            # Get all non-deleted watchlist items
            items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).all()
            
            logger.info(f"Found {len(items)} watchlist items")
            
            for item in items:
                if item.sl_tp_mode != "conservative":
                    old_mode = item.sl_tp_mode
                    item.sl_tp_mode = "conservative"
                    updated_count += 1
                    logger.info(f"Updated {item.symbol}: sl_tp_mode {old_mode} -> conservative")
            
            if updated_count > 0:
                db.commit()
                logger.info(f"✅ Committed {updated_count} watchlist updates to database")
            else:
                logger.info("No watchlist items needed updating (all already set to 'conservative')")
            
            return updated_count
        except Exception as e:
            logger.error(f"Error updating database: {e}", exc_info=True)
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"⚠️ Could not connect to database: {e}")
        logger.info("Database update skipped. You can update manually using SQL:")
        logger.info("  UPDATE watchlist_items SET sl_tp_mode = 'conservative' WHERE is_deleted = false;")
        logger.info("Or run this script when the database is accessible.")
        return 0


def main():
    logger.info("=" * 60)
    logger.info("Setting all strategies to 'Swing conservative'")
    logger.info("=" * 60)
    
    # Update trading config
    logger.info("\n[1/2] Updating trading_config.json...")
    config_updates = update_trading_config()
    
    # Update database
    logger.info("\n[2/2] Updating database watchlist_items...")
    db_updates = update_database_watchlist()
    
    logger.info("\n" + "=" * 60)
    logger.info("✅ SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Config file: {config_updates} coins updated")
    logger.info(f"Database: {db_updates} watchlist items updated")
    
    if db_updates == 0 and config_updates > 0:
        logger.info("\n⚠️ Note: Database update was skipped due to connection issues.")
        logger.info("To update the database, run the SQL script:")
        logger.info("  backend/migrations/set_all_strategies_swing_conservative.sql")
        logger.info("Or re-run this script when the database is accessible.")
    
    logger.info("\n✅ Config file updated: All strategies set to 'Swing conservative'!")


if __name__ == "__main__":
    main()














