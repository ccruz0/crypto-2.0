#!/usr/bin/env python3
"""
Simulate price movement alerts (dry run mode).

Fetches a pair from DB, simulates price below/above thresholds,
and runs signal evaluation directly (no scheduler).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData
from app.models.telegram_message import TelegramMessage
from app.services.trading_signals import should_trigger_buy_signal, calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile, StrategyType, RiskApproach
from datetime import datetime, timezone
import json

DRY_RUN = True

def simulate_price_test():
    """Simulate price movements and trigger alerts."""
    print("="*80)
    print("PRICE MOVEMENT ALERT SIMULATION (DRY RUN)")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Fetch a pair from DB
        item = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.alert_enabled == True
        ).first()
        
        if not item:
            print("❌ No enabled watchlist items found")
            return 1
        
        symbol = item.symbol
        print(f"\n📊 Testing pair: {symbol}")
        
        # Get current market data
        market_data = db.query(MarketData).filter(
            MarketData.symbol == symbol
        ).first()
        
        if not market_data or not market_data.price:
            print(f"❌ No market data found for {symbol}")
            return 1
        
        current_price = float(market_data.price)
        print(f"💰 Current price: ${current_price:.4f}")
        
        # Get strategy profile
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
        print(f"📈 Strategy: {strategy_type.value} / {risk_approach.value}")
        
        # Get indicators
        rsi = market_data.rsi
        ma50 = market_data.ma50
        ma200 = market_data.ma200
        ema10 = market_data.ema10
        
        print(f"📊 Indicators: RSI={rsi}, MA50={ma50}, MA200={ma200}, EMA10={ema10}")
        
        # Simulate BUY: Price below threshold
        print("\n" + "-"*80)
        print("SIMULATION 1: BUY Signal (Price below threshold)")
        print("-"*80)
        
        # Simulate price 5% below current
        buy_price = current_price * 0.95
        print(f"💰 Simulated BUY price: ${buy_price:.4f} (5% below current)")
        
        # Evaluate BUY signal
        buy_decision = should_trigger_buy_signal(
            symbol=symbol,
            price=buy_price,
            rsi=rsi,
            ma200=ma200,
            ma50=ma50,
            ema10=ema10,
            strategy_type=strategy_type,
            risk_approach=risk_approach
        )
        
        print(f"✅ BUY Decision: should_buy={buy_decision.should_buy}")
        print(f"   Reasons: {', '.join(buy_decision.reasons)}")
        if buy_decision.missing_indicators:
            print(f"   Missing: {', '.join(buy_decision.missing_indicators)}")
        
        # Generate full signal payload
        buy_signal_payload = calculate_trading_signals(
            symbol=symbol,
            price=buy_price,
            rsi=rsi,
            ma50=ma50,
            ma200=ma200,
            ema10=ema10,
            strategy_type=strategy_type,
            risk_approach=risk_approach
        )
        
        print(f"\n📦 BUY Signal Payload:")
        print(json.dumps({
            "alert_type": buy_signal_payload.get("alert_type"),
            "signal": buy_signal_payload.get("signal"),
            "should_buy": buy_signal_payload.get("should_buy"),
            "price": buy_signal_payload.get("price"),
        }, indent=2))
        
        # Simulate SELL: Price above threshold
        print("\n" + "-"*80)
        print("SIMULATION 2: SELL Signal (Price above threshold)")
        print("-"*80)
        
        # Simulate price 5% above current
        sell_price = current_price * 1.05
        print(f"💰 Simulated SELL price: ${sell_price:.4f} (5% above current)")
        
        # For SELL, we need to check if price is above resistance or RSI is high
        # Use calculate_trading_signals which handles both BUY and SELL
        sell_signal_payload = calculate_trading_signals(
            symbol=symbol,
            price=sell_price,
            rsi=rsi + 20 if rsi else 70,  # Simulate higher RSI for SELL
            ma50=ma50,
            ma200=ma200,
            ema10=ema10,
            strategy_type=strategy_type,
            risk_approach=risk_approach
        )
        
        print(f"✅ SELL Signal Payload:")
        print(json.dumps({
            "alert_type": sell_signal_payload.get("alert_type"),
            "signal": sell_signal_payload.get("signal"),
            "should_sell": sell_signal_payload.get("should_sell"),
            "price": sell_signal_payload.get("price"),
        }, indent=2))
        
        # Check monitoring table for new entries
        print("\n" + "-"*80)
        print("CHECKING MONITORING TABLE")
        print("-"*80)
        
        # Get count before
        count_before = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol
        ).count()
        
        print(f"📊 Monitoring entries for {symbol} before: {count_before}")
        print(f"ℹ️  Note: In dry-run mode, alerts are not actually sent to Telegram")
        print(f"    Signal evaluation completed successfully")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error in price simulation: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(simulate_price_test())
