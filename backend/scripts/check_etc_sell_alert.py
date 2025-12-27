#!/usr/bin/env python3
"""
Diagnostic script to check why ETC_USDT is not creating alerts and sell orders.
Checks all the conditions required for SELL alerts and orders.
"""

import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_throttle import fetch_signal_states
from datetime import datetime, timezone

def check_etc_configuration():
    """Check ETC_USDT configuration and identify issues"""
    db: Session = SessionLocal()
    
    try:
        symbol = "ETC_USDT"
        
        print(f"\n{'='*80}")
        print(f"🔍 DIAGNÓSTICO: {symbol} - Alertas y Órdenes SELL")
        print(f"{'='*80}\n")
        
        # 1. Check if watchlist item exists
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            print(f"❌ PROBLEMA CRÍTICO: {symbol} no existe en la watchlist")
            print(f"   Solución: Agregar {symbol} a la watchlist desde el dashboard")
            return
        
        print(f"✅ {symbol} existe en la watchlist")
        
        # 2. Check alert flags
        alert_enabled = watchlist_item.alert_enabled
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', False)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', False)
        trade_enabled = watchlist_item.trade_enabled
        
        print(f"\n📋 Flags de Configuración:")
        print(f"   alert_enabled: {alert_enabled} {'✅' if alert_enabled else '❌ (REQUERIDO)'}")
        print(f"   sell_alert_enabled: {sell_alert_enabled} {'✅' if sell_alert_enabled else '❌ (REQUERIDO para alertas SELL)'}")
        print(f"   buy_alert_enabled: {buy_alert_enabled} {'✅' if buy_alert_enabled else '⚠️ (solo afecta BUY)'}")
        print(f"   trade_enabled: {trade_enabled} {'✅' if trade_enabled else '❌ (REQUERIDO para crear órdenes)'}")
        
        # 3. Check if flags are blocking
        issues = []
        if not alert_enabled:
            issues.append("alert_enabled=False - Master switch deshabilitado")
        if not sell_alert_enabled:
            issues.append("sell_alert_enabled=False - Alertas SELL deshabilitadas")
        if not trade_enabled:
            issues.append("trade_enabled=False - Trading automático deshabilitado (bloquea órdenes, no alertas)")
        
        # 4. Check throttling state
        print(f"\n⏱️ Estado de Throttling (SELL):")
        try:
            signal_states = fetch_signal_states(db, symbol)
            sell_state = signal_states.get("SELL")
            
            if sell_state:
                last_price = sell_state.last_price
                last_time = sell_state.last_time
                force_next = getattr(sell_state, 'force_next_signal', False)
                
                print(f"   Última alerta SELL enviada:")
                print(f"     Precio: ${last_price:.4f}" if last_price else "     Precio: N/A")
                print(f"     Timestamp: {last_time.isoformat() if last_time else 'N/A'}")
                print(f"     Force next signal: {force_next}")
                
                if last_time:
                    now = datetime.now(timezone.utc)
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    time_diff = (now - last_time).total_seconds()
                    print(f"     Tiempo desde última alerta: {time_diff:.1f} segundos")
                    if time_diff < 60:
                        remaining = 60 - time_diff
                        issues.append(f"Throttling TIME GATE: Faltan {remaining:.1f} segundos (mínimo 60s entre alertas)")
            else:
                print(f"   ✅ No hay registro previo - primera alerta permitida inmediatamente")
        except Exception as e:
            print(f"   ⚠️ Error al consultar throttling: {e}")
        
        # 5. Check strategy configuration
        print(f"\n📊 Configuración de Estrategia:")
        strategy_id = getattr(watchlist_item, 'strategy_id', None)
        strategy_name = getattr(watchlist_item, 'strategy_name', None)
        sl_tp_mode = getattr(watchlist_item, 'sl_tp_mode', 'conservative')
        min_price_change_pct = getattr(watchlist_item, 'min_price_change_pct', None)
        
        print(f"   strategy_id: {strategy_id}")
        print(f"   strategy_name: {strategy_name}")
        print(f"   sl_tp_mode: {sl_tp_mode}")
        print(f"   min_price_change_pct: {min_price_change_pct}%")
        
        # 6. Check trade amount
        trade_amount_usd = watchlist_item.trade_amount_usd
        print(f"\n💰 Configuración de Trading:")
        print(f"   trade_amount_usd: ${trade_amount_usd}" if trade_amount_usd else "   trade_amount_usd: ❌ NO CONFIGURADO (requerido para órdenes)")
        if not trade_amount_usd or trade_amount_usd <= 0:
            issues.append("trade_amount_usd no configurado o <= 0 - Bloquea creación de órdenes")
        
        # 7. Summary
        print(f"\n{'='*80}")
        print(f"📝 RESUMEN DE PROBLEMAS:")
        print(f"{'='*80}")
        
        if not issues:
            print(f"✅ No se encontraron problemas de configuración")
            print(f"\n⚠️ Si aún no se crean alertas/órdenes, verificar:")
            print(f"   1. Que exista una señal SELL activa (RSI > 70, etc.)")
            print(f"   2. Que el throttling de precio se cumpla (cambio mínimo desde última alerta)")
            print(f"   3. Logs del backend para ver si hay señales SELL detectadas")
        else:
            for i, issue in enumerate(issues, 1):
                print(f"   {i}. ❌ {issue}")
        
        # 8. Provide SQL fix commands
        print(f"\n{'='*80}")
        print(f"🔧 COMANDOS SQL PARA CORREGIR:")
        print(f"{'='*80}")
        
        fixes = []
        if not alert_enabled:
            fixes.append(f"UPDATE watchlist_items SET alert_enabled = TRUE WHERE symbol = '{symbol}';")
        if not sell_alert_enabled:
            fixes.append(f"UPDATE watchlist_items SET sell_alert_enabled = TRUE WHERE symbol = '{symbol}';")
        if not trade_enabled:
            fixes.append(f"UPDATE watchlist_items SET trade_enabled = TRUE WHERE symbol = '{symbol}';")
        if not trade_amount_usd or trade_amount_usd <= 0:
            fixes.append(f"UPDATE watchlist_items SET trade_amount_usd = 10.0 WHERE symbol = '{symbol}'; -- Ajustar monto según necesidad")
        
        if fixes:
            print(f"\nEjecutar estos comandos SQL en la base de datos:")
            for fix in fixes:
                print(f"   {fix}")
        else:
            print(f"\n✅ No se requieren correcciones SQL")
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        import traceback
        print(f"❌ Error durante diagnóstico: {e}")
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_etc_configuration()

