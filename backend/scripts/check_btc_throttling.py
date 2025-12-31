#!/usr/bin/env python3
"""Check throttling status for BTC_USDT SELL"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.signal_throttle import SignalThrottleState
from app.services.strategy_profiles import resolve_strategy_profile
from app.services.signal_throttle import build_strategy_key, should_emit_signal, SignalThrottleConfig, fetch_signal_states
from app.models.watchlist import WatchlistItem
from datetime import datetime, timezone

db = SessionLocal()
try:
    symbol = 'BTC_USDT'
    
    # Get watchlist item
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol, WatchlistItem.is_deleted == False).first()
    
    # Get strategy
    strategy_profile = resolve_strategy_profile(symbol, db=db, watchlist_item=item)
    strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
    
    # Get throttle state
    throttle_state = db.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == symbol,
        SignalThrottleState.strategy_key == strategy_key,
        SignalThrottleState.side == 'SELL'
    ).first()
    
    if throttle_state:
        print(f'📊 Estado de Throttling SELL para {symbol}:')
        print(f'   Baseline price: ${throttle_state.last_price}')
        print(f'   Last time: {throttle_state.last_time}')
        print(f'   force_next_signal: {throttle_state.force_next_signal}')
        
        # Get current price
        from app.api.routes_dashboard import _get_market_data_for_symbol
        market_data = _get_market_data_for_symbol(db, symbol)
        if market_data and hasattr(market_data, 'price') and market_data.price:
            current_price = float(market_data.price)
            print(f'   Precio actual: ${current_price}')
            
            # Calculate price change
            baseline = throttle_state.last_price
            price_change = current_price - baseline
            price_change_pct = (price_change / baseline * 100) if baseline else 0
            print(f'   Cambio de precio: ${price_change:.2f} ({price_change_pct:+.2f}%)')
            
            # Check time difference
            now = datetime.now(timezone.utc)
            time_diff = (now - throttle_state.last_time).total_seconds()
            print(f'   Tiempo desde última alerta: {time_diff:.1f} segundos ({time_diff/60:.1f} minutos)')
            
            # Check throttling
            from app.services.config_loader import get_alert_thresholds
            thresholds = get_alert_thresholds(strategy_profile[0], strategy_profile[1])
            min_change = thresholds.get('min_price_change_pct', 3.0)
            print(f'   Threshold requerido: {min_change}%')
            
            # Test should_emit_signal
            throttle_config = SignalThrottleConfig(
                min_price_change_pct=min_change,
                min_interval_seconds=60
            )
            
            signal_snapshots = fetch_signal_states(db, symbol, strategy_key)
            last_sell_snapshot = signal_snapshots.get('SELL')
            
            allowed, reason = should_emit_signal(
                symbol=symbol,
                side='SELL',
                current_price=current_price,
                current_time=now,
                config=throttle_config,
                last_same_side=last_sell_snapshot,
                last_opposite_side=signal_snapshots.get('BUY'),
                db=db,
                strategy_key=strategy_key
            )
            
            print(f'\n🔍 Resultado de should_emit_signal:')
            print(f'   allowed: {allowed}')
            print(f'   reason: {reason}')
            
            if not allowed:
                print(f'\n❌ BLOQUEADO por throttling: {reason}')
                if 'TIME' in reason:
                    print(f'   → Necesita esperar más tiempo (60 segundos mínimo)')
                elif 'PRICE' in reason:
                    print(f'   → Necesita más cambio de precio ({abs(price_change_pct):.2f}% < {min_change}%)')
                    print(f'   → Para SELL, el precio debe cambiar {min_change}% desde el baseline')
                    print(f'   → Baseline: ${baseline}, Actual: ${current_price}')
            else:
                print(f'\n✅ Throttling OK - La alerta debería enviarse')
    else:
        print(f'ℹ️  No hay estado de throttling SELL (primera vez)')
finally:
    db.close()











