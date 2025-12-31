#!/usr/bin/env python3
"""
Script to check and update DOT_USDT watchlist settings for SL/TP percentages.

Usage:
    python check_update_dot_usdt_settings.py                    # Check current settings
    python check_update_dot_usdt_settings.py --update 5.0 5.0  # Update to 5% SL and 5% TP
    python check_update_dot_usdt_settings.py --mode aggressive # Change mode to aggressive
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SYMBOL = "DOT_USDT"


def check_settings(db: Session) -> dict:
    """Check current DOT_USDT settings"""
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == SYMBOL).first()
    
    if not item:
        return {
            "exists": False,
            "message": f"❌ {SYMBOL} not found in watchlist"
        }
    
    return {
        "exists": True,
        "symbol": item.symbol,
        "sl_percentage": item.sl_percentage,
        "tp_percentage": item.tp_percentage,
        "sl_tp_mode": item.sl_tp_mode,
        "sl_price": item.sl_price,
        "tp_price": item.tp_price,
        "trade_enabled": item.trade_enabled,
        "alert_enabled": item.alert_enabled,
        "exchange": item.exchange
    }


def update_percentages(db: Session, sl_pct: float, tp_pct: float, mode: str = None) -> bool:
    """Update SL/TP percentages for DOT_USDT"""
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == SYMBOL).first()
    
    if not item:
        logger.error(f"{SYMBOL} not found in watchlist. Creating new entry...")
        item = WatchlistItem(
            symbol=SYMBOL,
            exchange="CRYPTO_COM",
            sl_percentage=sl_pct,
            tp_percentage=tp_pct,
            sl_tp_mode=mode or "conservative",
            is_deleted=False
        )
        db.add(item)
    else:
        logger.info(f"Updating existing {SYMBOL} settings...")
        item.sl_percentage = sl_pct
        item.tp_percentage = tp_pct
        if mode:
            item.sl_tp_mode = mode
    
    try:
        db.commit()
        logger.info(f"✅ Successfully updated {SYMBOL}: SL={sl_pct}%, TP={tp_pct}%")
        if mode:
            logger.info(f"   Mode set to: {mode}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update: {e}")
        db.rollback()
        return False


def update_mode(db: Session, mode: str) -> bool:
    """Update only the SL/TP mode"""
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == SYMBOL).first()
    
    if not item:
        logger.error(f"{SYMBOL} not found in watchlist")
        return False
    
    old_mode = item.sl_tp_mode
    item.sl_tp_mode = mode
    
    try:
        db.commit()
        logger.info(f"✅ Updated {SYMBOL} mode: {old_mode} → {mode}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update mode: {e}")
        db.rollback()
        return False


def print_settings(settings: dict):
    """Print settings in a formatted way"""
    if not settings.get("exists"):
        print(settings["message"])
        return
    
    print(f"\n📊 Current settings for {settings['symbol']}:")
    print(f"   Exchange: {settings['exchange']}")
    print(f"   Mode: {settings['sl_tp_mode'] or 'N/A (will use conservative)'}")
    print(f"   SL Percentage: {settings['sl_percentage'] if settings['sl_percentage'] is not None else 'NULL (will use defaults)'}")
    print(f"   TP Percentage: {settings['tp_percentage'] if settings['tp_percentage'] is not None else 'NULL (will use defaults)'}")
    print(f"   SL Price: {settings['sl_price'] if settings['sl_price'] else 'N/A'}")
    print(f"   TP Price: {settings['tp_price'] if settings['tp_price'] else 'N/A'}")
    print(f"   Trade Enabled: {settings['trade_enabled']}")
    print(f"   Alert Enabled: {settings['alert_enabled']}")
    
    # Show what will be used
    mode = settings['sl_tp_mode'] or 'conservative'
    default_sl = 2.0 if mode.lower() == 'aggressive' else 3.0
    default_tp = 2.0 if mode.lower() == 'aggressive' else 3.0
    
    effective_sl = settings['sl_percentage'] if (settings['sl_percentage'] is not None and settings['sl_percentage'] > 0) else default_sl
    effective_tp = settings['tp_percentage'] if (settings['tp_percentage'] is not None and settings['tp_percentage'] > 0) else default_tp
    
    print(f"\n🎯 Effective percentages (what will be used):")
    if settings['sl_percentage'] is not None and settings['sl_percentage'] > 0:
        print(f"   SL: {effective_sl}% (from watchlist)")
    else:
        print(f"   SL: {effective_sl}% (default for {mode} mode)")
    
    if settings['tp_percentage'] is not None and settings['tp_percentage'] > 0:
        print(f"   TP: {effective_tp}% (from watchlist)")
    else:
        print(f"   TP: {effective_tp}% (default for {mode} mode)")


def main():
    parser = argparse.ArgumentParser(description="Check and update DOT_USDT SL/TP settings")
    parser.add_argument("--update", nargs=2, type=float, metavar=("SL_PCT", "TP_PCT"),
                       help="Update SL and TP percentages (e.g., --update 5.0 5.0)")
    parser.add_argument("--mode", choices=["conservative", "aggressive"],
                       help="Update SL/TP mode only")
    parser.add_argument("--all", nargs=3, type=str, metavar=("SL_PCT", "TP_PCT", "MODE"),
                       help="Update percentages and mode (e.g., --all 5.0 5.0 aggressive)")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        if args.all:
            sl_pct = float(args.all[0])
            tp_pct = float(args.all[1])
            mode = args.all[2]
            
            if mode not in ["conservative", "aggressive"]:
                print(f"❌ Invalid mode: {mode}. Must be 'conservative' or 'aggressive'")
                return
            
            # Show current settings first
            print("📋 Current settings:")
            settings = check_settings(db)
            print_settings(settings)
            
            print(f"\n🔄 Updating to: SL={sl_pct}%, TP={tp_pct}%, Mode={mode}")
            update_percentages(db, sl_pct, tp_pct, mode)
            
            # Show updated settings
            print("\n📋 Updated settings:")
            settings = check_settings(db)
            print_settings(settings)
            
        elif args.update:
            sl_pct = args.update[0]
            tp_pct = args.update[1]
            
            # Validate percentages
            if sl_pct <= 0 or tp_pct <= 0:
                print("❌ Percentages must be greater than 0")
                return
            
            # Show current settings first
            print("📋 Current settings:")
            settings = check_settings(db)
            print_settings(settings)
            
            print(f"\n🔄 Updating percentages: SL={sl_pct}%, TP={tp_pct}%")
            update_percentages(db, sl_pct, tp_pct)
            
            # Show updated settings
            print("\n📋 Updated settings:")
            settings = check_settings(db)
            print_settings(settings)
            
        elif args.mode:
            # Show current settings first
            print("📋 Current settings:")
            settings = check_settings(db)
            print_settings(settings)
            
            print(f"\n🔄 Updating mode to: {args.mode}")
            update_mode(db, args.mode)
            
            # Show updated settings
            print("\n📋 Updated settings:")
            settings = check_settings(db)
            print_settings(settings)
            
        else:
            # Just check settings
            print(f"🔍 Checking settings for {SYMBOL}...")
            settings = check_settings(db)
            print_settings(settings)
            
    finally:
        db.close()


if __name__ == "__main__":
    main()



