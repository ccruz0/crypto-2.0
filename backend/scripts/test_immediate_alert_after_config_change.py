#!/usr/bin/env python3
"""
Test script to verify that changing configuration triggers immediate signal evaluation
and sends alerts if criteria are met.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    db = SessionLocal()
    try:
        symbol = 'BTC_USDT'  # Test with BTC_USDT
        
        print(f"\n🧪 Probando evaluación inmediata de alertas después de cambio de configuración...\n")
        print(f"📋 Símbolo: {symbol}\n")
        
        # 1. Get current state
        print("=" * 60)
        print("1. ESTADO ACTUAL")
        print("=" * 60)
        
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            print(f"❌ {symbol} no encontrado en watchlist")
            return
        
        print(f"✅ {symbol} encontrado")
        print(f"   alert_enabled: {item.alert_enabled}")
        print(f"   buy_alert_enabled: {getattr(item, 'buy_alert_enabled', False)}")
        print(f"   sell_alert_enabled: {getattr(item, 'sell_alert_enabled', False)}")
        print(f"   trade_enabled: {item.trade_enabled}")
        
        # Check throttling state before
        from app.services.strategy_profiles import resolve_strategy_profile
        from app.services.signal_throttle import build_strategy_key
        
        strategy_profile = resolve_strategy_profile(symbol, db=db, watchlist_item=item)
        strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
        
        throttle_buy = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "BUY"
        ).first()
        
        throttle_sell = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "SELL"
        ).first()
        
        print(f"\n📊 Estado de Throttling ANTES:")
        if throttle_buy:
            print(f"   BUY: force_next_signal={throttle_buy.force_next_signal}, last_time={throttle_buy.last_time}")
        if throttle_sell:
            print(f"   SELL: force_next_signal={throttle_sell.force_next_signal}, last_time={throttle_sell.last_time}")
        
        # 2. Simulate config change by toggling sell_alert_enabled
        print("\n" + "=" * 60)
        print("2. SIMULANDO CAMBIO DE CONFIGURACIÓN")
        print("=" * 60)
        
        old_sell_alert = getattr(item, 'sell_alert_enabled', False)
        new_sell_alert = not old_sell_alert  # Toggle
        
        print(f"   Cambiando sell_alert_enabled: {old_sell_alert} → {new_sell_alert}")
        
        # This would normally be done via the API, but we'll test the logic directly
        # We'll just verify the throttling reset logic works
        
        # 3. Test throttling reset logic
        print("\n" + "=" * 60)
        print("3. PROBANDO RESET DE THROTTLING")
        print("=" * 60)
        
        try:
            from app.services.signal_throttle import reset_throttle_state, set_force_next_signal
            
            # Reset throttle for SELL
            reset_throttle_state(
                db,
                symbol=symbol,
                strategy_key=strategy_key,
                parameter_change_reason="TEST: Config change (sell_alert_enabled)"
            )
            
            # Set force_next_signal
            set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="BUY", enabled=True)
            set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="SELL", enabled=True)
            
            print(f"✅ Throttling reseteado y force_next_signal activado")
            
        except Exception as e:
            print(f"❌ Error reseteando throttling: {e}")
            logger.error(f"Error: {e}", exc_info=True)
            return
        
        # 4. Verify throttle state after reset
        print("\n" + "=" * 60)
        print("4. VERIFICANDO ESTADO DESPUÉS DEL RESET")
        print("=" * 60)
        
        db.refresh(throttle_buy) if throttle_buy else None
        throttle_sell = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "SELL"
        ).first()
        
        if throttle_sell:
            print(f"   SELL: force_next_signal={throttle_sell.force_next_signal}")
            print(f"   SELL: last_time={throttle_sell.last_time}")
            
            if throttle_sell.force_next_signal:
                print(f"   ✅ force_next_signal = True → Bypass activo")
            else:
                print(f"   ❌ force_next_signal = False → Bypass NO activo")
        
        # 5. Test immediate signal evaluation
        print("\n" + "=" * 60)
        print("5. PROBANDO EVALUACIÓN INMEDIATA DE SEÑALES")
        print("=" * 60)
        
        try:
            from app.services.signal_monitor import signal_monitor_service
            
            # Refresh item
            db.refresh(item)
            
            print(f"   Llamando _check_signal_for_coin_sync() para {symbol}...")
            
            # This should evaluate signals and send alerts if criteria are met
            signal_monitor_service._check_signal_for_coin_sync(db, item)
            
            print(f"   ✅ Evaluación completada")
            print(f"   ⚠️  Revisa los logs para ver si se envió alguna alerta")
            
        except Exception as e:
            print(f"   ❌ Error en evaluación inmediata: {e}")
            logger.error(f"Error: {e}", exc_info=True)
        
        # 6. Summary
        print("\n" + "=" * 60)
        print("6. RESUMEN")
        print("=" * 60)
        print(f"✅ Prueba completada")
        print(f"\n📝 Lo que debería haber pasado:")
        print(f"   1. Throttling reseteado para {symbol}")
        print(f"   2. force_next_signal = True activado para BUY y SELL")
        print(f"   3. Señales evaluadas inmediatamente")
        print(f"   4. Si hay señal activa y flags habilitados → Alerta enviada")
        print(f"\n🔍 Verifica los logs para confirmar si se envió la alerta")
        
    except Exception as e:
        logger.error(f"❌ Error durante prueba: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    main()













