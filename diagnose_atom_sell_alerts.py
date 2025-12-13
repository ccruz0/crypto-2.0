#!/usr/bin/env python3
"""Diagnostic script to check why ATOM SELL alerts are not being sent"""
import sys
import os

backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if os.path.exists(backend_path):
    sys.path.insert(0, backend_path)

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile

def diagnose_atom_sell_alerts():
    """Diagnose why ATOM SELL alerts are not being sent"""
    db = SessionLocal()
    try:
        # Get ATOM watchlist item
        atom = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'ATOM_USDT',
            WatchlistItem.is_deleted == False
        ).first()
        
        if not atom:
            print('❌ ATOM_USDT not found in watchlist or is deleted')
            return
        
        print('📊 ATOM_USDT Watchlist Configuration:')
        print(f'   alert_enabled: {atom.alert_enabled}')
        print(f'   sell_alert_enabled: {atom.sell_alert_enabled}')
        print(f'   buy_alert_enabled: {atom.buy_alert_enabled}')
        print(f'   is_deleted: {atom.is_deleted}')
        
        # Get market data
        mp = db.query(MarketPrice).filter(MarketPrice.symbol == 'ATOM_USDT').first()
        md = db.query(MarketData).filter(MarketData.symbol == 'ATOM_USDT').first()
        
        if not mp or not md:
            print('\n❌ Missing market data')
            return
        
        print('\n📈 Current Market Data:')
        print(f'   Price: {mp.price:.4f}')
        print(f'   RSI: {md.rsi:.2f} (threshold: 70)')
        print(f'   MA50: {md.ma50:.4f}')
        print(f'   EMA10: {md.ema10:.4f}')
        print(f'   MA10w: {md.ma10w:.4f}')
        print(f'   Current Volume: {getattr(md, "current_volume", None)}')
        print(f'   Avg Volume: {getattr(md, "avg_volume", None)}')
        
        # Get strategy
        strategy_type, risk_approach = resolve_strategy_profile(atom.symbol)
        print(f'\n🎯 Strategy: {strategy_type.value}/{risk_approach.value}')
        
        # Calculate signals with proper volume data
        current_volume = getattr(md, 'current_volume', None)
        if not current_volume and mp.volume_24h:
            current_volume = mp.volume_24h / 24.0
        
        avg_volume = getattr(md, 'avg_volume', None)
        if not avg_volume and mp.volume_24h:
            avg_volume = mp.volume_24h / 24.0
        
        signals = calculate_trading_signals(
            symbol='ATOM_USDT',
            price=mp.price,
            rsi=md.rsi,
            atr14=md.atr,
            ma50=md.ma50,
            ma200=md.ma200,
            ema10=md.ema10,
            ma10w=md.ma10w,
            volume=current_volume,
            avg_volume=avg_volume,
            resistance_up=None,
            buy_target=atom.buy_target,
            strategy_type=strategy_type,
            risk_approach=risk_approach,
        )
        
        print('\n🔍 SELL Signal Analysis:')
        print(f'   sell_signal: {signals.get("sell_signal")}')
        print(f'   buy_signal: {signals.get("buy_signal")}')
        print(f'   decision: {signals.get("strategy", {}).get("decision")}')
        
        reasons = signals.get('strategy', {}).get('reasons', {})
        print('\n   SELL Conditions:')
        print(f'     sell_rsi_ok: {reasons.get("sell_rsi_ok")} (RSI {md.rsi:.2f} > 70)')
        print(f'     sell_trend_ok: {reasons.get("sell_trend_ok")}')
        print(f'     sell_volume_ok: {reasons.get("sell_volume_ok")} (volume ratio: {current_volume/avg_volume if current_volume and avg_volume else 0:.2f}x)')
        
        # Check if all conditions are met
        all_conditions_met = (
            reasons.get("sell_rsi_ok") == True and
            reasons.get("sell_trend_ok") == True and
            reasons.get("sell_volume_ok") == True
        )
        
        print(f'\n✅ All SELL conditions met: {all_conditions_met}')
        
        if all_conditions_met and atom.sell_alert_enabled:
            print('\n💡 SELL alert SHOULD be sent!')
            print('   Possible reasons it\'s not being sent:')
            print('   1. Signal monitor hasn\'t run yet (runs every 30 seconds)')
            print('   2. Alert cooldown period (5 minutes default)')
            print('   3. Minimum price change threshold (1.0% default)')
            print('   4. Signal monitor is not running')
        elif not all_conditions_met:
            print('\n❌ SELL conditions NOT met - check which condition is failing above')
        elif not atom.sell_alert_enabled:
            print('\n❌ sell_alert_enabled is False - alerts will not be sent')
        
        # Check if ATOM would be included in signal monitor query
        print('\n🔍 Signal Monitor Query Check:')
        monitor_items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.is_deleted == False
        ).all()
        
        atom_in_monitor = any(item.symbol == 'ATOM_USDT' for item in monitor_items)
        print(f'   ATOM_USDT in monitor query: {atom_in_monitor}')
        print(f'   Total symbols being monitored: {len(monitor_items)}')
        
    except Exception as e:
        print(f'❌ Error: {e}', file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    diagnose_atom_sell_alerts()

