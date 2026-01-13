#!/usr/bin/env python3
"""
Diagnostic script to check if active signals are following strategy parameters.

This script:
1. Loads the current strategy configuration
2. Checks active signals from the database/API
3. Validates each signal against its configured strategy parameters
4. Reports any signals that don't meet the criteria
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.services.config_loader import get_strategy_rules, load_config
from app.services.strategy_profiles import resolve_strategy_profile, StrategyType, RiskApproach
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_data import MarketData
from app.models.market_price import MarketPrice
from app.services.trading_signals import should_trigger_buy_signal

def check_signal_compliance():
    """Check if signals comply with strategy parameters."""
    db = SessionLocal()
    
    try:
        # Get all watchlist items with alert_enabled
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True
        ).all()
        
        print(f"\n{'='*80}")
        print(f"Checking {len(watchlist_items)} symbols for strategy compliance")
        print(f"{'='*80}\n")
        
        violations = []
        compliant = []
        
        for item in watchlist_items:
            symbol = item.symbol
            if not symbol:
                continue
            
            # Resolve strategy profile
            try:
                strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
            except Exception as e:
                print(f"⚠️  {symbol}: Failed to resolve strategy profile: {e}")
                continue
            
            # Get strategy rules
            preset_name = strategy_type.value.lower()
            risk_mode = risk_approach.value.capitalize()
            rules = get_strategy_rules(preset_name, risk_mode)
            
            rsi_buy_below = rules.get("rsi", {}).get("buyBelow")
            
            # Get current market data
            md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
            mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
            
            if not md or not mp:
                print(f"⚠️  {symbol}: No market data available")
                continue
            
            price = mp.price
            rsi = md.rsi
            ma50 = md.ma50
            ma200 = md.ma200
            ema10 = md.ema10
            
            # Check if signal should trigger
            decision = should_trigger_buy_signal(
                symbol=symbol,
                price=price,
                rsi=rsi,
                ma200=ma200,
                ma50=ma50,
                ema10=ema10,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
            )
            
            # Check compliance
            issues = []
            
            # RSI check
            if rsi_buy_below is not None:
                if rsi is not None and rsi >= rsi_buy_below:
                    issues.append(f"RSI {rsi:.2f} >= {rsi_buy_below} (threshold)")
            
            # Check if decision says should_buy
            if decision.should_buy:
                if issues:
                    violations.append({
                        "symbol": symbol,
                        "strategy": f"{preset_name}/{risk_mode}",
                        "rsi": rsi,
                        "rsi_threshold": rsi_buy_below,
                        "price": price,
                        "issues": issues,
                        "decision_reasons": decision.reasons,
                    })
                else:
                    compliant.append({
                        "symbol": symbol,
                        "strategy": f"{preset_name}/{risk_mode}",
                        "rsi": rsi,
                        "rsi_threshold": rsi_buy_below,
                        "price": price,
                    })
            else:
                # Signal is not triggered, which is correct if there are issues
                if not issues:
                    # No issues but signal not triggered - might be other conditions
                    print(f"ℹ️  {symbol}: Signal not triggered (no RSI violation, but other conditions not met)")
                    print(f"   Decision: {decision.summary}")
        
        # Print results
        print(f"\n{'='*80}")
        print(f"RESULTS")
        print(f"{'='*80}\n")
        
        if violations:
            print(f"❌ FOUND {len(violations)} SIGNALS WITH VIOLATIONS:\n")
            for v in violations:
                print(f"  {v['symbol']}:")
                print(f"    Strategy: {v['strategy']}")
                print(f"    RSI: {v['rsi']:.2f} (threshold: {v['rsi_threshold']})")
                print(f"    Price: ${v['price']:.4f}")
                print(f"    Issues: {', '.join(v['issues'])}")
                print(f"    Decision reasons: {v['decision_reasons']}")
                print()
        else:
            print("✅ No violations found - all signals comply with strategy parameters\n")
        
        if compliant:
            print(f"✅ {len(compliant)} signals are compliant:\n")
            for c in compliant[:10]:  # Show first 10
                print(f"  {c['symbol']}: RSI {c['rsi']:.2f} < {c['rsi_threshold']} ✓")
            if len(compliant) > 10:
                print(f"  ... and {len(compliant) - 10} more")
            print()
        
        return len(violations) == 0
        
    finally:
        db.close()

if __name__ == "__main__":
    try:
        is_compliant = check_signal_compliance()
        sys.exit(0 if is_compliant else 1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)






