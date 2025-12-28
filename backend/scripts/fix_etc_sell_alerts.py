#!/usr/bin/env python3
"""
Quick fix script to enable SELL alerts and orders for ETC_USDT.
This script will:
1. Enable alert_enabled
2. Enable sell_alert_enabled
3. Enable trade_enabled (for orders)
4. Set trade_amount_usd if not configured
"""

import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def fix_etc_sell_alerts():
    """Enable SELL alerts and orders for ETC_USDT"""
    db: Session = SessionLocal()
    
    try:
        symbol = "ETC_USDT"
        
        print(f"\n{'='*80}")
        print(f"🔧 FIXING: {symbol} - Enabling SELL Alerts and Orders")
        print(f"{'='*80}\n")
        
        # Find watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            print(f"❌ ERROR: {symbol} not found in watchlist")
            print(f"   Please add {symbol} to the watchlist first via the dashboard")
            return False
        
        print(f"✅ Found {symbol} in watchlist")
        
        # Track changes
        changes = []
        
        # 1. Enable alert_enabled (master switch)
        if not watchlist_item.alert_enabled:
            watchlist_item.alert_enabled = True
            changes.append("alert_enabled: False → True")
            print(f"   ✅ Enabling alert_enabled (master switch)")
        else:
            print(f"   ✓ alert_enabled already enabled")
        
        # 2. Enable sell_alert_enabled
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', False)
        if not sell_alert_enabled:
            watchlist_item.sell_alert_enabled = True
            changes.append("sell_alert_enabled: False → True")
            print(f"   ✅ Enabling sell_alert_enabled (SELL-specific)")
        else:
            print(f"   ✓ sell_alert_enabled already enabled")
        
        # 3. Enable trade_enabled (for orders)
        if not watchlist_item.trade_enabled:
            watchlist_item.trade_enabled = True
            changes.append("trade_enabled: False → True")
            print(f"   ✅ Enabling trade_enabled (for order creation)")
        else:
            print(f"   ✓ trade_enabled already enabled")
        
        # 4. Set trade_amount_usd if not configured
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            # Use a default of $10 if not configured
            default_amount = 10.0
            watchlist_item.trade_amount_usd = default_amount
            changes.append(f"trade_amount_usd: {watchlist_item.trade_amount_usd} → {default_amount}")
            print(f"   ✅ Setting trade_amount_usd to ${default_amount}")
        else:
            print(f"   ✓ trade_amount_usd already configured: ${watchlist_item.trade_amount_usd}")
        
        # Commit changes
        if changes:
            try:
                db.add(watchlist_item)
                db.commit()
                db.refresh(watchlist_item)
                
                print(f"\n{'='*80}")
                print(f"✅ SUCCESS: Changes applied to {symbol}")
                print(f"{'='*80}")
                print(f"\nChanges made:")
                for change in changes:
                    print(f"   • {change}")
                
                print(f"\n📋 Current Configuration:")
                print(f"   alert_enabled: {watchlist_item.alert_enabled}")
                print(f"   sell_alert_enabled: {getattr(watchlist_item, 'sell_alert_enabled', False)}")
                print(f"   trade_enabled: {watchlist_item.trade_enabled}")
                print(f"   trade_amount_usd: ${watchlist_item.trade_amount_usd}")
                
                print(f"\n✅ {symbol} is now configured for SELL alerts and orders!")
                print(f"\n⚠️  Note: If throttling is blocking, wait 60 seconds or reset throttling state.")
                print(f"   To reset throttling: DELETE FROM signal_throttle_states WHERE symbol='{symbol}' AND side='SELL';")
                
                return True
            except Exception as e:
                db.rollback()
                print(f"\n❌ ERROR: Failed to save changes: {e}")
                return False
        else:
            print(f"\n✅ No changes needed - {symbol} is already configured correctly!")
            return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = fix_etc_sell_alerts()
    sys.exit(0 if success else 1)









