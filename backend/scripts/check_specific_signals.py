#!/usr/bin/env python3
"""
Quick check for specific signals mentioned by user:
- FIL_USDT: RSI 24.43 (should pass if threshold is 30)
- SUI_USDT: RSI 33.62 (should FAIL if threshold is 30)
- UNI_USDT: RSI 39.64 (should FAIL if threshold is 30)
- DOT_USDT: RSI 34.59 (should FAIL if threshold is 30)
"""

import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.services.config_loader import get_strategy_rules
from app.services.strategy_profiles import resolve_strategy_profile
from app.services.trading_signals import should_trigger_buy_signal
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData

symbols_to_check = ["FIL_USDT", "SUI_USDT", "UNI_USDT", "DOT_USDT"]

def check_signals():
    db = SessionLocal()
    
    try:
        print(f"\n{'='*80}")
        print("Checking specific signals against strategy parameters")
        print(f"{'='*80}\n")
        
        for symbol in symbols_to_check:
            print(f"\n📊 {symbol}:")
            print("-" * 60)
            
            # Get watchlist item
            item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
            if not item:
                print(f"  ⚠️  Not in watchlist")
                continue
            
            # Resolve strategy
            strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
            preset_name = strategy_type.value.lower()
            risk_mode = risk_approach.value.capitalize()
            
            print(f"  Strategy: {preset_name} / {risk_mode}")
            
            # Get rules
            rules = get_strategy_rules(preset_name, risk_mode)
            rsi_buy_below = rules.get("rsi", {}).get("buyBelow")
            print(f"  RSI Buy Below Threshold: {rsi_buy_below}")
            
            # Get market data
            md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
            mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
            
            if not md or not mp:
                print(f"  ⚠️  No market data available")
                continue
            
            rsi = md.rsi
            price = mp.price
            ma50 = md.ma50
            ma200 = md.ma200
            ema10 = md.ema10
            
            print(f"  Current RSI: {rsi:.2f}")
            print(f"  Current Price: ${price:.4f}")
            
            # Check if should trigger
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
            
            print(f"  Should Buy: {decision.should_buy}")
            print(f"  Decision Summary: {decision.summary}")
            
            # Check RSI compliance
            if rsi_buy_below is not None:
                if rsi is not None:
                    if rsi < rsi_buy_below:
                        print(f"  ✅ RSI {rsi:.2f} < {rsi_buy_below} (PASSES threshold)")
                    else:
                        print(f"  ❌ RSI {rsi:.2f} >= {rsi_buy_below} (FAILS threshold)")
                        print(f"     This signal should NOT be shown as BUY!")
            
            if decision.should_buy:
                print(f"  ✅ Signal would trigger BUY")
            else:
                print(f"  ❌ Signal would NOT trigger BUY")
                if decision.missing_indicators:
                    print(f"     Missing indicators: {', '.join(decision.missing_indicators)}")
        
        print(f"\n{'='*80}\n")
        
    finally:
        db.close()

if __name__ == "__main__":
    check_signals()

