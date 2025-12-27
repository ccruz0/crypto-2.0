#!/usr/bin/env python3
"""
Reset throttling state for TON_USDT SELL alerts and enable force_next_signal.
This will allow the next SELL signal to trigger immediately.
"""

import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from sqlalchemy import text
from app.services.signal_throttle import set_force_next_signal, build_strategy_key
from app.services.strategy_profiles import resolve_strategy_profile

def reset_ton_throttling():
    """Reset throttling state for TON_USDT SELL"""
    db: Session = SessionLocal()
    
    try:
        symbol = "TON_USDT"
        side = "SELL"
        
        print(f"\n{'='*80}")
        print(f"🔧 Resetting Throttling State: {symbol} {side}")
        print(f"{'='*80}\n")
        
        # Get strategy key
        from app.models.watchlist import WatchlistItem
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            print(f"❌ {symbol} not found in watchlist")
            return False
        
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db=db, watchlist_item=watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        
        # Option 1: Delete throttling state (allows immediate alert)
        result = db.execute(text("""
            DELETE FROM signal_throttle_states 
            WHERE symbol = :symbol AND side = :side
        """), {"symbol": symbol, "side": side})
        
        deleted_count = result.rowcount
        db.commit()
        
        if deleted_count > 0:
            print(f"✅ Deleted {deleted_count} throttling record(s)")
        
        # Option 2: Set force_next_signal for future throttling states
        # (This ensures if a state is created, it will have force_next_signal=True)
        try:
            set_force_next_signal(
                db,
                symbol=symbol,
                strategy_key=strategy_key,
                side=side,
                enabled=True
            )
            print(f"✅ Set force_next_signal=True for {symbol} {side}")
        except Exception as e:
            print(f"⚠️  Could not set force_next_signal (may not exist yet): {e}")
        
        # Check current state
        result2 = db.execute(text("""
            SELECT COUNT(*) FROM signal_throttle_states 
            WHERE symbol = :symbol AND side = :side
        """), {"symbol": symbol, "side": side})
        count = result2.scalar()
        
        print(f"\n📋 Result:")
        if count == 0:
            print(f"✅ Throttling state cleared - next SELL alert will be allowed immediately")
        else:
            print(f"⚠️  Still {count} record(s) found (should be 0)")
        
        print(f"\n{'='*80}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = reset_ton_throttling()
    sys.exit(0 if success else 1)

