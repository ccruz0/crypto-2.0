#!/usr/bin/env python3
"""Diagnostic script to investigate why BTC_USDT alerts are blocked."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
from app.models.market_price import MarketPrice, MarketData
from datetime import datetime, timezone, timedelta
from app.services.signal_throttle import fetch_signal_states, SignalThrottleConfig, should_emit_signal

def diagnose_btc_alerts():
    db = SessionLocal()
    symbol = "BTC_USDT"
    
    print(f"\n{'='*80}")
    print(f"DIAGNÓSTICO COMPLETO PARA {symbol}")
    print(f"{'='*80}\n")
    
    # 1. Check watchlist configuration
    print("1. CONFIGURACIÓN DE WATCHLIST:")
    print("-" * 80)
    watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
    if not watchlist_item:
        print(f"❌ ERROR: {symbol} NO encontrado en watchlist_items")
        return
    else:
        print(f"✅ {symbol} encontrado en watchlist")
        print(f"   - alert_enabled: {watchlist_item.alert_enabled}")
        print(f"   - buy_alert_enabled: {getattr(watchlist_item, 'buy_alert_enabled', 'NOT SET')}")
        print(f"   - sell_alert_enabled: {getattr(watchlist_item, 'sell_alert_enabled', 'NOT SET')}")
        print(f"   - trade_enabled: {watchlist_item.trade_enabled}")
        print(f"   - min_price_change_pct: {getattr(watchlist_item, 'min_price_change_pct', 'NOT SET')}")
        print(f"   - alert_cooldown_minutes: {getattr(watchlist_item, 'alert_cooldown_minutes', 'NOT SET')}")
    
    # 2. Check market data
    print(f"\n2. DATOS DE MERCADO:")
    print("-" * 80)
    market_price = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
    if market_price:
        print(f"✅ MarketPrice encontrado")
        print(f"   - price: {market_price.price}")
        if hasattr(market_price, 'last_updated'):
            print(f"   - last_updated: {market_price.last_updated}")
    else:
        print(f"❌ MarketPrice NO encontrado")
    
    market_data = db.query(MarketData).filter(MarketData.symbol == symbol).first()
    if market_data:
        print(f"✅ MarketData encontrado")
        print(f"   - rsi: {market_data.rsi}")
        print(f"   - ma50: {market_data.ma50}")
        print(f"   - ema10: {market_data.ema10}")
        if hasattr(market_data, 'last_updated'):
            print(f"   - last_updated: {market_data.last_updated}")
    else:
        print(f"❌ MarketData NO encontrado")
    
    # 3. Check throttle states
    print(f"\n3. ESTADO DE THROTTLE:")
    print("-" * 80)
    throttle_states = db.query(SignalThrottleState).filter(
        SignalThrottleState.symbol == symbol
    ).all()
    
    if not throttle_states:
        print(f"⚠️  No hay throttle states registrados para {symbol}")
    else:
        for state in throttle_states:
            print(f"\n   Throttle State ({state.side}, strategy={state.strategy_key}):")
            print(f"   - last_price: {state.last_price}")
            print(f"   - last_time: {state.last_time}")
            print(f"   - emit_reason: {getattr(state, 'emit_reason', 'NOT SET')}")
            print(f"   - force_next_signal: {getattr(state, 'force_next_signal', False)}")
            
            if state.last_time:
                time_diff = datetime.now(timezone.utc) - state.last_time
                print(f"   - tiempo desde última señal: {time_diff.total_seconds() / 60:.2f} minutos")
    
    # 4. Simulate throttle check
    print(f"\n4. SIMULACIÓN DE THROTTLE CHECK:")
    print("-" * 80)
    if market_price and market_data:
        current_price = market_price.price
        from app.services.config_loader import get_alert_thresholds
        from app.services.strategy_profiles import resolve_strategy_profile
        
        # Get strategy profile
        try:
            profile = resolve_strategy_profile(
                watchlist_item.strategy_type,
                watchlist_item.risk_approach
            )
            strategy_key = f"{profile.strategy_type.value}_{profile.risk_approach.value}"
            
            # Get throttle config
            min_price_change_pct = getattr(watchlist_item, 'min_price_change_pct', None)
            alert_cooldown_minutes = getattr(watchlist_item, 'alert_cooldown_minutes', None)
            
            if min_price_change_pct is None or alert_cooldown_minutes is None:
                thresholds = get_alert_thresholds()
                min_price_change_pct = min_price_change_pct or thresholds.get('min_price_change_pct', 0.0)
                alert_cooldown_minutes = alert_cooldown_minutes or thresholds.get('alert_cooldown_minutes', 0.0)
            
            throttle_config = SignalThrottleConfig(
                min_price_change_pct=min_price_change_pct,
                min_interval_minutes=alert_cooldown_minutes
            )
            
            print(f"   Throttle Config:")
            print(f"   - min_price_change_pct: {throttle_config.min_price_change_pct}")
            print(f"   - min_interval_minutes: {throttle_config.min_interval_minutes}")
            print(f"   - strategy_key: {strategy_key}")
            
            # Fetch signal states
            signal_snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
            print(f"\n   Signal Snapshots encontrados: {list(signal_snapshots.keys())}")
            
            # Check BUY
            print(f"\n   BUY Signal Check:")
            last_buy = signal_snapshots.get("BUY")
            if last_buy:
                print(f"   - Última señal BUY: precio={last_buy.price}, tiempo={last_buy.timestamp}")
                if last_buy.timestamp and last_buy.price:
                    time_diff = (datetime.now(timezone.utc) - last_buy.timestamp).total_seconds() / 60
                    price_change = abs((current_price - last_buy.price) / last_buy.price * 100) if last_buy.price > 0 else 0
                    print(f"   - Tiempo desde última BUY: {time_diff:.2f} minutos")
                    print(f"   - Cambio de precio: {price_change:.2f}%")
                    print(f"   - Requiere: {throttle_config.min_interval_minutes} minutos Y {throttle_config.min_price_change_pct}% cambio")
                    if time_diff < throttle_config.min_interval_minutes:
                        print(f"   ❌ BLOQUEADO: Tiempo insuficiente ({time_diff:.2f} < {throttle_config.min_interval_minutes})")
                    if price_change < throttle_config.min_price_change_pct:
                        print(f"   ❌ BLOQUEADO: Cambio de precio insuficiente ({price_change:.2f}% < {throttle_config.min_price_change_pct}%)")
            else:
                print(f"   ✅ No hay señal BUY previa - debería permitir")
            
            buy_allowed, buy_reason = should_emit_signal(
                symbol=symbol,
                side="BUY",
                current_price=current_price,
                current_time=datetime.now(timezone.utc),
                config=throttle_config,
                last_same_side=signal_snapshots.get("BUY"),
                last_opposite_side=signal_snapshots.get("SELL"),
                db=db,
                strategy_key=strategy_key,
            )
            print(f"   - Resultado: {'✅ PERMITIDO' if buy_allowed else '❌ BLOQUEADO'}")
            print(f"   - Razón: {buy_reason}")
            
            # Check SELL
            print(f"\n   SELL Signal Check:")
            last_sell = signal_snapshots.get("SELL")
            if last_sell:
                print(f"   - Última señal SELL: precio={last_sell.price}, tiempo={last_sell.timestamp}")
                if last_sell.timestamp and last_sell.price:
                    time_diff = (datetime.now(timezone.utc) - last_sell.timestamp).total_seconds() / 60
                    price_change = abs((current_price - last_sell.price) / last_sell.price * 100) if last_sell.price > 0 else 0
                    print(f"   - Tiempo desde última SELL: {time_diff:.2f} minutos")
                    print(f"   - Cambio de precio: {price_change:.2f}%")
                    print(f"   - Requiere: {throttle_config.min_interval_minutes} minutos Y {throttle_config.min_price_change_pct}% cambio")
                    if time_diff < throttle_config.min_interval_minutes:
                        print(f"   ❌ BLOQUEADO: Tiempo insuficiente ({time_diff:.2f} < {throttle_config.min_interval_minutes})")
                    if price_change < throttle_config.min_price_change_pct:
                        print(f"   ❌ BLOQUEADO: Cambio de precio insuficiente ({price_change:.2f}% < {throttle_config.min_price_change_pct}%)")
            else:
                print(f"   ✅ No hay señal SELL previa - debería permitir")
            
            sell_allowed, sell_reason = should_emit_signal(
                symbol=symbol,
                side="SELL",
                current_price=current_price,
                current_time=datetime.now(timezone.utc),
                config=throttle_config,
                last_same_side=signal_snapshots.get("SELL"),
                last_opposite_side=signal_snapshots.get("BUY"),
                db=db,
                strategy_key=strategy_key,
            )
            print(f"   - Resultado: {'✅ PERMITIDO' if sell_allowed else '❌ BLOQUEADO'}")
            print(f"   - Razón: {sell_reason}")
        except Exception as e:
            print(f"   ❌ Error en simulación de throttle check: {e}")
            import traceback
            traceback.print_exc()
    
    # 5. Check recent logs pattern
    print(f"\n5. RESUMEN DE RAZONES DE BLOQUEO:")
    print("-" * 80)
    
    if not watchlist_item.alert_enabled:
        print(f"❌ alert_enabled=False - BLOQUEA TODAS LAS ALERTAS")
    if not getattr(watchlist_item, 'buy_alert_enabled', True):
        print(f"❌ buy_alert_enabled=False - BLOQUEA ALERTAS BUY")
    if not getattr(watchlist_item, 'sell_alert_enabled', True):
        print(f"❌ sell_alert_enabled=False - BLOQUEA ALERTAS SELL")
    
    print(f"\n{'='*80}\n")
    db.close()

if __name__ == "__main__":
    diagnose_btc_alerts()

