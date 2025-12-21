#!/usr/bin/env python3
"""Script completo de diagnóstico para ALGO - Verifica por qué no se envió una alerta"""
import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from sqlalchemy import or_
from app.services.signal_throttle import fetch_signal_states, build_strategy_key
from app.services.strategy_profiles import resolve_strategy_profile

def main():
    db = SessionLocal()
    try:
        symbol = "ALGO_USDT"
        print("=" * 80)
        print(f"🔍 DIAGNÓSTICO COMPLETO: {symbol}")
        print("=" * 80)
        print()
        
        # 1. Verificar watchlist item
        print("📋 1. CONFIGURACIÓN EN WATCHLIST")
        print("-" * 80)
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            print(f"❌ {symbol} NO ENCONTRADO en watchlist!")
            return
        
        print(f"✅ {symbol} encontrado en watchlist (ID: {watchlist_item.id})")
        print()
        
        # Flags de alerta
        alert_enabled = getattr(watchlist_item, 'alert_enabled', False)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', None)
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', None)
        
        print(f"  • alert_enabled: {alert_enabled} {'✅' if alert_enabled else '❌'}")
        print(f"  • buy_alert_enabled: {buy_alert_enabled} {'✅' if (buy_alert_enabled or (alert_enabled and buy_alert_enabled is None)) else '❌'}")
        print(f"  • sell_alert_enabled: {sell_alert_enabled} {'✅' if (sell_alert_enabled or (alert_enabled and sell_alert_enabled is None)) else '❌'}")
        print(f"  • trade_enabled: {getattr(watchlist_item, 'trade_enabled', False)}")
        try:
            is_deleted = getattr(watchlist_item, 'is_deleted', False)
            print(f"  • is_deleted: {is_deleted}")
        except AttributeError:
            print(f"  • is_deleted: N/A (columna no existe en esta BD)")
        print()
        
        # Configuración de throttling
        alert_cooldown_minutes = getattr(watchlist_item, 'alert_cooldown_minutes', None)
        min_price_change_pct = getattr(watchlist_item, 'min_price_change_pct', None)
        
        print(f"  • alert_cooldown_minutes: {alert_cooldown_minutes or 'default (5 min)'}")
        print(f"  • min_price_change_pct: {min_price_change_pct or 'default (1.0%)'}")
        print()
        
        # Verificar si hay problemas con flags
        if not alert_enabled:
            print("  ⚠️  PROBLEMA: alert_enabled=False - Las alertas están deshabilitadas!")
            print("     Solución: Activa 'alert_enabled' en el dashboard")
            print()
        
        if alert_enabled and buy_alert_enabled is False:
            print("  ⚠️  PROBLEMA: buy_alert_enabled=False - Las alertas BUY están deshabilitadas!")
            print("     Solución: Activa 'buy_alert_enabled' en el dashboard")
            print()
        
        # 2. Verificar estado de throttling
        print("⏱️  2. ESTADO DE THROTTLING")
        print("-" * 80)
        
        try:
            strategy_profile = resolve_strategy_profile(symbol, db=db, watchlist_item=watchlist_item)
            strategy_key = build_strategy_key(strategy_profile[0], strategy_profile[1])
            print(f"  • Strategy: {strategy_key}")
            print()
            
            # Obtener estado de throttling para BUY
            buy_states = fetch_signal_states(db, symbol, strategy_key, "BUY")
            if buy_states:
                last_buy = buy_states[0] if buy_states else None
                if last_buy and last_buy.timestamp:
                    last_time = last_buy.timestamp
                    last_price = last_buy.last_price or 0.0
                    now = datetime.now(timezone.utc)
                    
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    
                    time_diff = (now - last_time).total_seconds() / 60  # minutos
                    cooldown = alert_cooldown_minutes or 5.0
                    cooldown_met = time_diff >= cooldown
                    
                    print(f"  📊 Última alerta BUY:")
                    print(f"     • Fecha: {last_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    print(f"     • Precio: ${last_price:.4f}")
                    print(f"     • Tiempo desde última alerta: {time_diff:.2f} minutos")
                    print(f"     • Cooldown requerido: {cooldown} minutos")
                    print(f"     • Cooldown cumplido: {'✅ SÍ' if cooldown_met else f'❌ NO (faltan {cooldown - time_diff:.2f} min)'}")
                    print()
                    
                    if not cooldown_met:
                        print(f"  ⚠️  PROBLEMA: Cooldown no cumplido - Faltan {cooldown - time_diff:.2f} minutos")
                        print(f"     Solución: Espera {cooldown - time_diff:.1f} minutos o reduce 'alert_cooldown_minutes'")
                        print()
                    
                    # Verificar cambio de precio
                    current_price = getattr(watchlist_item, 'price', None)
                    if current_price and last_price > 0:
                        price_change_pct = abs((current_price - last_price) / last_price * 100)
                        min_change = min_price_change_pct or 1.0
                        price_change_met = price_change_pct >= min_change
                        
                        print(f"  💰 Cambio de precio:")
                        print(f"     • Precio anterior: ${last_price:.4f}")
                        print(f"     • Precio actual: ${current_price:.4f}")
                        print(f"     • Cambio: {price_change_pct:.2f}%")
                        print(f"     • Cambio mínimo requerido: {min_change}%")
                        print(f"     • Cambio suficiente: {'✅ SÍ' if price_change_met else f'❌ NO (falta {min_change - price_change_pct:.2f}%)'}")
                        print()
                        
                        if not price_change_met:
                            print(f"  ⚠️  PROBLEMA: Cambio de precio insuficiente - Falta {min_change - price_change_pct:.2f}%")
                            print(f"     Solución: Espera a que el precio cambie más o reduce 'min_price_change_pct'")
                            print()
                        
                        # Verificar si AMBAS condiciones se cumplen
                        if not cooldown_met or not price_change_met:
                            print(f"  ⚠️  THROTTLING ACTIVO:")
                            if not cooldown_met:
                                print(f"     • Cooldown: ❌ No cumplido ({time_diff:.2f} min < {cooldown} min)")
                            if not price_change_met:
                                print(f"     • Cambio precio: ❌ No cumplido ({price_change_pct:.2f}% < {min_change}%)")
                            print(f"     • Se requiere AMBAS condiciones para enviar alerta")
                            print()
                else:
                    print(f"  ✅ No hay alertas BUY previas - La primera alerta se enviará sin throttling")
                    print()
            else:
                print(f"  ✅ No hay estado de throttling para BUY - La primera alerta se enviará sin throttling")
                print()
            
            # Obtener estado de throttling para SELL
            sell_states = fetch_signal_states(db, symbol, strategy_key, "SELL")
            if sell_states:
                last_sell = sell_states[0] if sell_states else None
                if last_sell and last_sell.timestamp:
                    print(f"  📊 Última alerta SELL: {last_sell.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                    print()
        except Exception as e:
            print(f"  ⚠️  Error obteniendo estado de throttling: {e}")
            print()
        
        # 3. Verificar señal actual
        print("📊 3. SEÑAL ACTUAL")
        print("-" * 80)
        current_price = getattr(watchlist_item, 'price', None)
        rsi = getattr(watchlist_item, 'rsi', None)
        decision = getattr(watchlist_item, 'signals', {})
        
        print(f"  • Precio actual: ${current_price:.4f}" if current_price else "  • Precio: N/A")
        print(f"  • RSI: {rsi:.2f}" if rsi else "  • RSI: N/A")
        if decision:
            print(f"  • Señal manual: {decision}")
        print()
        
        # 4. Resumen y recomendaciones
        print("=" * 80)
        print("📝 RESUMEN Y RECOMENDACIONES")
        print("=" * 80)
        print()
        
        issues = []
        if not alert_enabled:
            issues.append("❌ alert_enabled=False - Activa las alertas en el dashboard")
        if alert_enabled and buy_alert_enabled is False:
            issues.append("❌ buy_alert_enabled=False - Activa las alertas BUY en el dashboard")
        
        if issues:
            print("⚠️  PROBLEMAS ENCONTRADOS:")
            for issue in issues:
                print(f"  {issue}")
            print()
        else:
            print("✅ Flags de alerta: OK")
            print()
        
        print("💡 PRÓXIMOS PASOS:")
        print("  1. Revisa los logs del backend para ver mensajes específicos:")
        print(f"     grep '{symbol}' /path/to/logs | grep -E 'alert|BUY|throttle|BLOCKED|SKIPPED'")
        print()
        print("  2. Si el problema es throttling:")
        print("     - Reduce 'alert_cooldown_minutes' en el dashboard")
        print("     - Reduce 'min_price_change_pct' en el dashboard")
        print("     - O espera a que se cumplan las condiciones")
        print()
        print("  3. Verifica que la señal BUY se esté detectando correctamente")
        print("     - Revisa los logs: 'SignalMonitor: BUY signal candidate'")
        print()
        
    finally:
        db.close()

if __name__ == "__main__":
    main()





