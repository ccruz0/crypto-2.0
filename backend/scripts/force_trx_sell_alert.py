#!/usr/bin/env python3
"""
Script to force send a SELL alert for TRX_USDT by bypassing throttling.

This script:
1. Sets force_next_signal flag for TRX_USDT SELL
2. This allows the next signal evaluation to bypass throttling
3. The alert will be sent on the next signal monitor cycle (within 30 seconds)
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.services.signal_throttle import set_force_next_signal, build_strategy_key
from app.services.watchlist_selector import get_canonical_watchlist_item

def force_trx_sell_alert():
    """Force next SELL alert for TRX_USDT."""
    db: Session = SessionLocal()
    
    try:
        symbol = "TRX_USDT"
        side = "SELL"
        
        print("=" * 80)
        print("FORCE TRX_USDT SELL ALERT")
        print("=" * 80)
        print()
        
        # Get watchlist item to determine strategy
        watchlist_item = get_canonical_watchlist_item(db, symbol)
        if not watchlist_item:
            print(f"❌ {symbol} not found in watchlist!")
            print("   → Add TRX_USDT to watchlist first")
            return
        
        # Build strategy key
        strategy_key = build_strategy_key(watchlist_item)
        print(f"📊 Symbol: {symbol}")
        print(f"📊 Strategy key: {strategy_key}")
        print()
        
        # Set force flag
        print("🔧 Setting force_next_signal flag...")
        set_force_next_signal(
            db=db,
            symbol=symbol,
            strategy_key=strategy_key,
            side=side,
            enabled=True
        )
        
        print("✅ Force flag set successfully!")
        print()
        print("ℹ️  The next SELL signal evaluation (within 30 seconds) will bypass throttling")
        print("   and send the alert immediately.")
        print()
        print("⚠️  Note: This only works if:")
        print("   1. alert_enabled = True")
        print("   2. sell_alert_enabled = True")
        print("   3. A SELL signal is actually detected")
        print()
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    force_trx_sell_alert()

