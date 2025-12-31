#!/usr/bin/env python3
"""
Reset throttling state for ETC_USDT SELL alerts.
This will allow the next SELL signal to trigger immediately.
"""

import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from sqlalchemy import text

def reset_etc_throttling():
    """Reset throttling state for ETC_USDT SELL"""
    db: Session = SessionLocal()
    
    try:
        symbol = "ETC_USDT"
        side = "SELL"
        
        print(f"\n{'='*80}")
        print(f"🔧 Resetting Throttling State: {symbol} {side}")
        print(f"{'='*80}\n")
        
        # Check current state
        result = db.execute(text("""
            SELECT last_price, last_time, emit_reason 
            FROM signal_throttle_states 
            WHERE symbol = :symbol AND side = :side
        """), {"symbol": symbol, "side": side})
        row = result.fetchone()
        
        if row:
            print(f"📊 Current State:")
            print(f"   Last Price: ${row[0]:.4f}" if row[0] else "   Last Price: None")
            print(f"   Last Time: {row[1]}" if row[1] else "   Last Time: None")
            print(f"   Reason: {row[2]}" if row[2] else "   Reason: None")
            print()
        
        # Delete throttling state
        result = db.execute(text("""
            DELETE FROM signal_throttle_states 
            WHERE symbol = :symbol AND side = :side
        """), {"symbol": symbol, "side": side})
        
        deleted_count = result.rowcount
        db.commit()
        
        if deleted_count > 0:
            print(f"✅ Successfully reset throttling state for {symbol} {side}")
            print(f"   Deleted {deleted_count} record(s)")
            print()
            print(f"📋 Next Steps:")
            print(f"   1. The next SELL signal will be allowed immediately")
            print(f"   2. No time gate or price gate will apply to the first alert")
            print(f"   3. After the first alert, normal throttling (60s + 1% price change) will apply")
        else:
            print(f"ℹ️  No throttling state found for {symbol} {side}")
            print(f"   This means alerts should already be allowed")
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()
    
    return True

if __name__ == "__main__":
    success = reset_etc_throttling()
    sys.exit(0 if success else 1)











