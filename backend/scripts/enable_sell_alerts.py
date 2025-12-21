#!/usr/bin/env python3
"""
Enable sell alerts for all symbols with alert_enabled=True.

This script sets sell_alert_enabled=True for all watchlist items that have
alert_enabled=True but sell_alert_enabled is False or None.
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal

def enable_sell_alerts():
    """Enable sell_alert_enabled for all symbols with alert_enabled=True"""
    db: Session = SessionLocal()
    try:
        print("=" * 80)
        print("ENABLING SELL ALERTS")
        print("=" * 80)
        
        # Use raw SQL to avoid model column issues
        # First, check if sell_alert_enabled column exists
        try:
            result = db.execute(text("""
                SELECT id, symbol, alert_enabled, 
                       COALESCE(sell_alert_enabled, 0) as sell_alert_enabled
                FROM watchlist_items 
                WHERE alert_enabled = 1
                ORDER BY symbol
            """))
            rows = result.fetchall()
        except Exception as e:
            print(f"❌ Error querying database: {e}")
            return 0
        
        print(f"\nFound {len(rows)} items with alert_enabled=True")
        
        enabled_count = 0
        already_enabled_count = 0
        symbols_to_update = []
        
        for row in rows:
            item_id = row[0]
            symbol = row[1]
            alert_enabled = bool(row[2])
            sell_alert_enabled = bool(row[3])
            
            if sell_alert_enabled:
                already_enabled_count += 1
                print(f"✅ {symbol:15} - sell_alert_enabled already True")
            else:
                symbols_to_update.append((item_id, symbol))
                enabled_count += 1
                print(f"🔧 {symbol:15} - Will enable sell_alert_enabled")
        
        # Update all items that need enabling
        if symbols_to_update:
            for item_id, symbol in symbols_to_update:
                try:
                    db.execute(text("""
                        UPDATE watchlist_items 
                        SET sell_alert_enabled = 1 
                        WHERE id = :item_id
                    """), {"item_id": item_id})
                    print(f"✅ {symbol:15} - ENABLED sell_alert_enabled")
                except Exception as e:
                    print(f"❌ {symbol:15} - Error updating: {e}")
            
            db.commit()
            print(f"\n✅ Successfully enabled sell alerts for {enabled_count} symbols")
        else:
            print(f"\n✅ All {len(rows)} symbols already have sell_alert_enabled=True")
        
        print(f"\nSummary:")
        print(f"  - Total symbols: {len(rows)}")
        print(f"  - Already enabled: {already_enabled_count}")
        print(f"  - Newly enabled: {enabled_count}")
        
        return enabled_count
    except Exception as e:
        db.rollback()
        print(f"\n❌ Error enabling sell alerts: {e}")
        import traceback
        traceback.print_exc()
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    count = enable_sell_alerts()
    if count > 0:
        print("\n⚠️  Note: Sell alerts will only be sent if:")
        print("   1. sell_signal=True (RSI > 70, MA reversal, volume OK)")
        print("   2. alert_enabled=True ✅")
        print("   3. sell_alert_enabled=True ✅ (just enabled)")
        print("   4. Throttle check passes")
        print("\n   Check backend logs to verify sell alerts are being generated.")




