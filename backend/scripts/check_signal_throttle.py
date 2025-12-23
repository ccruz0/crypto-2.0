#!/usr/bin/env python3
"""
Diagnostic script to check signal throttle state for a symbol.
Shows the last price reference used for throttling buy/sell signals.
"""

import sys
import os
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.signal_throttle import SignalThrottleState
from app.services.strategy_profiles import StrategyType, RiskApproach
from app.services.signal_throttle import build_strategy_key
from datetime import datetime, timezone

def check_signal_throttle(symbol: str, strategy_type: str = "swing", risk_approach: str = "conservative"):
    """Check signal throttle state for a symbol."""
    symbol = symbol.upper()
    
    # Build strategy key
    try:
        strategy_enum = StrategyType[strategy_type.upper()]
        risk_enum = RiskApproach[risk_approach.upper()]
        strategy_key = build_strategy_key(strategy_enum, risk_enum)
    except KeyError:
        strategy_key = f"{strategy_type.lower()}:{risk_approach.lower()}"
    
    db: Session = SessionLocal()
    try:
        # Get all throttle states for this symbol
        states = (
            db.query(SignalThrottleState)
            .filter(SignalThrottleState.symbol == symbol)
            .all()
        )
        
        if not states:
            print(f"\n❌ No throttle state found for {symbol}")
            print(f"   Strategy key searched: {strategy_key}")
            print(f"   This means no signals have been sent yet for this symbol.")
            return
        
        print(f"\n📊 Signal Throttle State for {symbol}")
        print(f"   Strategy key: {strategy_key}")
        print(f"   Found {len(states)} throttle state(s):\n")
        
        for state in states:
            print(f"   Side: {state.side}")
            print(f"   Strategy: {state.strategy_key}")
            print(f"   Last Price: ${state.last_price:.2f}" if state.last_price else "   Last Price: None")
            print(f"   Previous Price: ${state.previous_price:.2f}" if state.previous_price else "   Previous Price: None")
            print(f"   Last Time: {state.last_time.isoformat() if state.last_time else 'None'}")
            print(f"   Last Source: {state.last_source or 'None'}")
            print(f"   Emit Reason: {state.emit_reason or 'None'}")
            print(f"   Force Next Signal: {state.force_next_signal}")
            
            # Calculate time since last signal
            if state.last_time:
                time_diff = datetime.now(timezone.utc) - state.last_time.replace(tzinfo=timezone.utc)
                hours = time_diff.total_seconds() / 3600
                print(f"   Time Since Last Signal: {hours:.2f} hours ({time_diff.total_seconds() / 60:.1f} minutes)")
            
            print()
        
        # Check if there's a matching strategy key
        matching_state = next((s for s in states if s.strategy_key == strategy_key), None)
        if matching_state and matching_state.side == "BUY":
            last_price = matching_state.last_price
            if last_price:
                print(f"✅ BUY throttle reference found:")
                print(f"   Last BUY signal price: ${last_price:.2f}")
                print(f"   This is the price reference used to block new BUY signals.")
                print(f"   New BUY signals will be blocked unless price changes by at least 1% (default)")
                print(f"   from ${last_price:.2f}")
            else:
                print(f"⚠️  BUY throttle state exists but last_price is None")
        elif matching_state and matching_state.side == "SELL":
            print(f"ℹ️  Only SELL throttle state found for this strategy")
        else:
            print(f"⚠️  No matching throttle state for strategy '{strategy_key}' and side 'BUY'")
            print(f"   Available states: {[(s.strategy_key, s.side) for s in states]}")
            
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_signal_throttle.py <SYMBOL> [strategy_type] [risk_approach]")
        print("Example: python check_signal_throttle.py BTC_USDT swing conservative")
        sys.exit(1)
    
    symbol = sys.argv[1]
    strategy_type = sys.argv[2] if len(sys.argv) > 2 else "swing"
    risk_approach = sys.argv[3] if len(sys.argv) > 3 else "conservative"
    
    check_signal_throttle(symbol, strategy_type, risk_approach)

