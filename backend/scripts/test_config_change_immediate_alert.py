#!/usr/bin/env python3
"""
Test script to verify that changing configuration triggers immediate signal evaluation.
This script simulates what happens when the API endpoint processes a config change.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import create_db_session
from app.models.watchlist import WatchlistItem
from app.models.signal_throttle import SignalThrottleState
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'TON_USDT'
    
    db = create_db_session()
    try:
        
        print(f"\n🧪 Probando evaluación inmediata de alertas después de cambio de configuración...\n")
        print(f"📋 Símbolo: {symbol}\n")
        
        # 1. Get current state
        print("=" * 70)
        print("1. ESTADO ACTUAL (ANTES DEL CAMBIO)")
        print("=" * 70)
        
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
        print(f"   min_price_change_pct: {item.min_price_change_pct}")
        print(f"   trade_amount_usd: {item.trade_amount_usd}")
        
        # Check throttling state before
        from app.services.strategy_profiles import resolve_strategy_profile
        from app.services.signal_throttle import build_strategy_key
        
        strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
        strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
        
        throttle_buy_before = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "BUY"
        ).first()
        
        throttle_sell_before = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "SELL"
        ).first()
        
        print(f"\n📊 Estado de Throttling ANTES:")
        if throttle_buy_before:
            print(f"   BUY: force_next_signal={throttle_buy_before.force_next_signal}")
            print(f"        last_time={throttle_buy_before.last_time}")
            print(f"        last_price={throttle_buy_before.last_price}")
        else:
            print(f"   BUY: No existe registro de throttling")
            
        if throttle_sell_before:
            print(f"   SELL: force_next_signal={throttle_sell_before.force_next_signal}")
            print(f"         last_time={throttle_sell_before.last_time}")
            print(f"         last_price={throttle_sell_before.last_price}")
        else:
            print(f"   SELL: No existe registro de throttling")
        
        # 2. Simulate config change - toggle sell_alert_enabled
        print("\n" + "=" * 70)
        print("2. SIMULANDO CAMBIO DE CONFIGURACIÓN")
        print("=" * 70)
        
        old_sell_alert = getattr(item, 'sell_alert_enabled', False)
        new_sell_alert = not old_sell_alert  # Toggle
        
        print(f"   Cambiando sell_alert_enabled: {old_sell_alert} → {new_sell_alert}")
        
        # Store old value (as the API does)
        sell_alert_enabled_old_value = old_sell_alert
        
        # Apply the change (simulating what _apply_watchlist_updates does)
        setattr(item, 'sell_alert_enabled', new_sell_alert)
        db.add(item)
        db.commit()
        db.refresh(item)
        
        print(f"   ✅ Cambio aplicado en base de datos")
        
        # 3. Execute throttling reset logic (as the API does)
        print("\n" + "=" * 70)
        print("3. EJECUTANDO RESET DE THROTTLING (Lógica del API)")
        print("=" * 70)
        
        try:
            from app.services.signal_throttle import (
                reset_throttle_state,
                set_force_next_signal,
            )
            from app.services.signal_monitor import signal_monitor_service
            
            # Get current strategy
            strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
            strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
            
            # Reset throttle state (config_hash is optional, skip for simplicity)
            current_price = getattr(item, "price", None)
            reset_throttle_state(
                db,
                symbol=item.symbol,
                strategy_key=strategy_key,
                current_price=current_price,
                parameter_change_reason=f"CONFIG_CHANGE: sell_alert_enabled ({'YES' if sell_alert_enabled_old_value else 'NO'} → {'YES' if new_sell_alert else 'NO'})",
            )
            print(f"   ✅ Throttling reseteado")
            
            # Set force_next_signal for both BUY and SELL
            set_force_next_signal(db, symbol=item.symbol, strategy_key=strategy_key, side="BUY", enabled=True)
            set_force_next_signal(db, symbol=item.symbol, strategy_key=strategy_key, side="SELL", enabled=True)
            print(f"   ✅ force_next_signal = True para BUY y SELL")
            
            # Clear order creation limitations
            signal_monitor_service.clear_order_creation_limitations(item.symbol)
            print(f"   ✅ Limitaciones de creación de órdenes limpiadas")
            
        except Exception as e:
            print(f"   ❌ Error en reset de throttling: {e}")
            logger.error(f"Error: {e}", exc_info=True)
            db.rollback()
            return
        
        # 4. Verify throttle state after reset
        print("\n" + "=" * 70)
        print("4. VERIFICANDO ESTADO DESPUÉS DEL RESET")
        print("=" * 70)
        
        db.refresh(throttle_buy_before) if throttle_buy_before else None
        throttle_buy_after = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "BUY"
        ).first()
        
        throttle_sell_after = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "SELL"
        ).first()
        
        if throttle_buy_after:
            print(f"   BUY: force_next_signal={throttle_buy_after.force_next_signal}")
            print(f"        last_time={throttle_buy_after.last_time}")
            if throttle_buy_after.force_next_signal:
                print(f"        ✅ Bypass activo")
            else:
                print(f"        ❌ Bypass NO activo")
        else:
            print(f"   BUY: No existe registro (se creará en próxima evaluación)")
            
        if throttle_sell_after:
            print(f"   SELL: force_next_signal={throttle_sell_after.force_next_signal}")
            print(f"         last_time={throttle_sell_after.last_time}")
            if throttle_sell_after.force_next_signal:
                print(f"         ✅ Bypass activo")
            else:
                print(f"         ❌ Bypass NO activo")
        else:
            print(f"   SELL: No existe registro (se creará en próxima evaluación)")
        
        # 5. Test immediate signal evaluation
        print("\n" + "=" * 70)
        print("5. EVALUANDO SEÑALES INMEDIATAMENTE")
        print("=" * 70)
        
        try:
            # Refresh item to get latest values
            db.refresh(item)
            
            print(f"   Llamando _check_signal_for_coin_sync() para {symbol}...")
            
            # This should evaluate signals and send alerts if criteria are met
            signal_monitor_service._check_signal_for_coin_sync(db, item)
            
            print(f"   ✅ Evaluación completada")
            print(f"   ⚠️  Revisa los logs del servicio para ver si se envió alguna alerta")
            
        except Exception as e:
            print(f"   ❌ Error en evaluación inmediata: {e}")
            logger.error(f"Error: {e}", exc_info=True)
        
        # 6. Final verification
        print("\n" + "=" * 70)
        print("6. VERIFICACIÓN FINAL")
        print("=" * 70)
        
        # Check throttle state one more time after signal evaluation
        throttle_sell_final = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == symbol,
            SignalThrottleState.strategy_key == strategy_key,
            SignalThrottleState.side == "SELL"
        ).first()
        
        if throttle_sell_final:
            print(f"   SELL después de evaluación:")
            print(f"      force_next_signal={throttle_sell_final.force_next_signal}")
            print(f"      last_time={throttle_sell_final.last_time}")
            if throttle_sell_final.last_time:
                print(f"      ⚠️  Nota: Si se envió una alerta, last_time debería haberse actualizado")
        
        # 7. Summary
        print("\n" + "=" * 70)
        print("7. RESUMEN")
        print("=" * 70)
        print(f"✅ Prueba completada para {symbol}")
        print(f"\n📝 Lo que debería haber pasado:")
        print(f"   1. ✅ Throttling reseteado para {symbol}")
        print(f"   2. ✅ force_next_signal = True activado para BUY y SELL")
        print(f"   3. ✅ Señales evaluadas inmediatamente")
        print(f"   4. ✅ Si hay señal activa y flags habilitados → Alerta enviada")
        print(f"\n🔍 Verifica los logs del servicio backend-aws para confirmar:")
        print(f"   - Si se detectó una señal")
        print(f"   - Si se envió una alerta")
        print(f"   - Si se creó una orden (si trade_enabled=True)")
        print(f"\n💡 Para ver logs en tiempo real:")
        print(f"   docker compose logs -f backend-aws | grep -i '{symbol}'")
        
    except Exception as e:
        logger.error(f"❌ Error durante prueba: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()

