#!/usr/bin/env python3
"""Diagnose why CRO BUY alert is not being sent"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import get_db
from app.models.watchlist import WatchlistItem
from sqlalchemy.orm import Session

def diagnose_cro_alert():
    db: Session = next(get_db())
    
    # Find CRO watchlist item
    cro_item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == "CRO",
        WatchlistItem.is_deleted == False
    ).first()
    
    if not cro_item:
        print("❌ CRO not found in watchlist")
        return
    
    print(f"📊 CRO Watchlist Item Configuration:")
    print(f"   Symbol: {cro_item.symbol}")
    print(f"   alert_enabled: {cro_item.alert_enabled}")
    print(f"   buy_alert_enabled: {getattr(cro_item, 'buy_alert_enabled', 'N/A')}")
    print(f"   sell_alert_enabled: {getattr(cro_item, 'sell_alert_enabled', 'N/A')}")
    print(f"   trade_enabled: {cro_item.trade_enabled}")
    print(f"   trade_amount_usd: {cro_item.trade_amount_usd}")
    
    # Check if flags are blocking
    if not cro_item.alert_enabled:
        print("\n🚫 BLOCKED: alert_enabled=False (master switch is OFF)")
    elif not getattr(cro_item, 'buy_alert_enabled', False):
        print("\n🚫 BLOCKED: buy_alert_enabled=False (BUY alerts are disabled)")
    else:
        print("\n✅ Alert flags are enabled - checking other potential blockers...")
        
        # Check portfolio value
        try:
            from app.services.order_position_service import calculate_portfolio_value_for_symbol
            # Get current price (approximate)
            current_price = 0.1  # Approximate CRO price
            portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, "CRO", current_price)
            trade_amount = cro_item.trade_amount_usd if cro_item.trade_amount_usd and cro_item.trade_amount_usd > 0 else 100.0
            limit_value = 3 * trade_amount
            
            print(f"\n💰 Portfolio Check:")
            print(f"   Portfolio value: ${portfolio_value:.2f}")
            print(f"   Trade amount: ${trade_amount:.2f}")
            print(f"   Limit (3x trade_amount): ${limit_value:.2f}")
            
            if portfolio_value > limit_value:
                print(f"   🚫 BLOCKED: Portfolio value (${portfolio_value:.2f}) > 3x trade_amount (${limit_value:.2f})")
            else:
                print(f"   ✅ Portfolio check passed")
        except Exception as e:
            print(f"   ⚠️  Could not check portfolio value: {e}")
    
    # Check recent signal throttle state
    try:
        from app.services.signal_throttle import fetch_signal_states, build_strategy_key
        from app.services.strategy_profiles import resolve_strategy_profile
        
        strategy_type, risk_approach = resolve_strategy_profile("CRO", db, cro_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        
        signal_snapshots = fetch_signal_states(db, symbol="CRO", strategy_key=strategy_key)
        
        print(f"\n⏱️  Throttle State:")
        if "BUY" in signal_snapshots:
            buy_snapshot = signal_snapshots["BUY"]
            print(f"   Last BUY alert: {buy_snapshot.last_signal_time}")
            print(f"   Last BUY price: ${buy_snapshot.last_signal_price}")
        else:
            print(f"   No previous BUY alerts recorded")
    except Exception as e:
        print(f"   ⚠️  Could not check throttle state: {e}")

if __name__ == "__main__":
    diagnose_cro_alert()

