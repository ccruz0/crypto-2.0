#!/usr/bin/env python3
"""
Check why BTC_USD is not sending SELL alerts despite showing SELL signal in dashboard.
"""

import sys
import os
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.services.strategy_profiles import resolve_strategy_profile

def check_btc_usd_sell_alert():
    """Check BTC_USD sell alert configuration and signal status"""
    db: Session = SessionLocal()
    try:
        symbol = "BTC_USD"
        
        print("=" * 80)
        print(f"BTC_USD SELL ALERT DIAGNOSTIC")
        print("=" * 80)
        print()
        
        # Get watchlist item
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.deleted == False if hasattr(WatchlistItem, 'deleted') else True
        ).first()
        
        if not item:
            print(f"❌ {symbol} not found in watchlist")
            return
        
        # Check flags
        alert_enabled = item.alert_enabled
        sell_alert_enabled = getattr(item, 'sell_alert_enabled', False)
        buy_alert_enabled = getattr(item, 'buy_alert_enabled', False)
        
        print(f"📋 Configuration:")
        print(f"   alert_enabled: {alert_enabled}")
        print(f"   buy_alert_enabled: {buy_alert_enabled}")
        print(f"   sell_alert_enabled: {sell_alert_enabled}")
        print()
        
        # Get strategy
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
        print(f"📊 Strategy: {strategy_type.value}-{risk_approach.value}")
        print()
        
        # Evaluate signal
        print(f"🔍 Evaluating signal...")
        eval_result = evaluate_signal_for_symbol(db, item, symbol)
        
        print(f"📈 Signal Status:")
        print(f"   sell_signal: {eval_result['sell_signal']}")
        print(f"   can_emit_sell_alert: {eval_result['can_emit_sell_alert']}")
        print(f"   sell_flag_allowed: {eval_result['sell_flag_allowed']}")
        print(f"   throttle_status_sell: {eval_result['throttle_status_sell']}")
        print(f"   throttle_reason_sell: {eval_result['throttle_reason_sell']}")
        print()
        
        # Get market data
        mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
        md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
        
        if mp:
            print(f"💰 Price Data:")
            print(f"   Current Price: ${mp.price:,.2f}" if mp.price else "   Current Price: N/A")
            print()
        
        if md:
            print(f"📊 Technical Indicators:")
            print(f"   RSI: {md.rsi:.2f}" if md.rsi else "   RSI: N/A")
            print(f"   MA50: ${md.ma50:,.2f}" if md.ma50 else "   MA50: N/A")
            print(f"   EMA10: ${md.ema10:,.2f}" if md.ema10 else "   EMA10: N/A")
            print(f"   Volume Ratio: {eval_result.get('volume_ratio', 'N/A')}")
            print()
        
        # Debug flags
        debug_flags = eval_result.get('debug_flags', {})
        print(f"🔍 Debug Flags:")
        print(f"   sell_rsi_ok: {debug_flags.get('sell_rsi_ok')}")
        print(f"   sell_trend_ok: {debug_flags.get('sell_trend_ok')}")
        print(f"   sell_volume_ok: {debug_flags.get('sell_volume_ok')}")
        print()
        
        # Determine why alert isn't being sent
        print(f"🔎 Analysis:")
        print()
        
        if not eval_result['sell_signal']:
            print(f"❌ No sell_signal detected")
            if not debug_flags.get('sell_rsi_ok'):
                print(f"   → RSI condition not met")
            if not debug_flags.get('sell_trend_ok'):
                print(f"   → Trend reversal condition not met")
            if not debug_flags.get('sell_volume_ok'):
                print(f"   → Volume condition not met")
        else:
            print(f"✅ sell_signal = True")
            
            if not sell_alert_enabled:
                print(f"❌ sell_alert_enabled = False → Alert will NOT be sent")
            elif not alert_enabled:
                print(f"❌ alert_enabled = False → Alert will NOT be sent")
            elif not eval_result['can_emit_sell_alert']:
                print(f"❌ can_emit_sell_alert = False")
                if eval_result['throttle_status_sell'] == 'BLOCKED':
                    print(f"   → Throttled: {eval_result['throttle_reason_sell']}")
                elif not eval_result['sell_flag_allowed']:
                    print(f"   → Flag check failed (sell_flag_allowed = False)")
            else:
                print(f"✅ All conditions met - alert SHOULD be sent!")
                print(f"   → Check backend logs for 'SELL alert SENT' or 'SELL alert BLOCKED'")
        
        print()
        print("=" * 80)
        
    finally:
        db.close()

if __name__ == "__main__":
    check_btc_usd_sell_alert()




