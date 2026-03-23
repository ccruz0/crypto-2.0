#!/usr/bin/env python3
"""Script de diagnóstico para LDO - Verifica por qué no se creó alerta u orden"""
import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from sqlalchemy import or_
from app.services.signal_throttle import fetch_signal_states, build_strategy_key, should_emit_signal
from app.services.strategy_profiles import resolve_strategy_profile
from app.services.order_position_service import count_open_positions_for_symbol, calculate_portfolio_value_for_symbol

def main():
    db = create_db_session()
    try:
        # Buscar LDO en todas las variantes posibles
        symbols = ["LDO_USDT", "LDO_USD", "LDO"]
        
        print("=" * 80)
        print("🔍 DIAGNÓSTICO COMPLETO: LDO (Alertas y Órdenes)")
        print("=" * 80)
        print()
        
        watchlist_item = None
        symbol = None
        
        for sym in symbols:
            item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == sym
            ).first()
            if item:
                watchlist_item = item
                symbol = sym
                break
        
        if not watchlist_item:
            print(f"❌ LDO NO ENCONTRADO en watchlist!")
            print(f"   Buscado: {', '.join(symbols)}")
            return
        
        print(f"✅ {symbol} encontrado en watchlist (ID: {watchlist_item.id})")
        print()
        
        # ========================================================================
        # 1. CONFIGURACIÓN EN WATCHLIST
        # ========================================================================
        print("📋 1. CONFIGURACIÓN EN WATCHLIST")
        print("-" * 80)
        
        alert_enabled = getattr(watchlist_item, 'alert_enabled', False)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', None)
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', None)
        trade_enabled = getattr(watchlist_item, 'trade_enabled', False)
        trade_amount_usd = getattr(watchlist_item, 'trade_amount_usd', None)
        
        print(f"  • alert_enabled: {alert_enabled} {'✅' if alert_enabled else '❌ BLOQUEA ALERTAS'}")
        print(f"  • buy_alert_enabled: {buy_alert_enabled} {'✅' if (buy_alert_enabled or (alert_enabled and buy_alert_enabled is None)) else '❌ BLOQUEA ALERTAS BUY'}")
        print(f"  • sell_alert_enabled: {sell_alert_enabled}")
        print(f"  • trade_enabled: {trade_enabled} {'✅' if trade_enabled else '❌ BLOQUEA ÓRDENES'}")
        print(f"  • trade_amount_usd: {trade_amount_usd} {'✅' if (trade_amount_usd and trade_amount_usd > 0) else '❌ REQUERIDO PARA ÓRDENES'}")
        
        try:
            is_deleted = getattr(watchlist_item, 'is_deleted', False)
            print(f"  • is_deleted: {is_deleted} {'❌ BLOQUEA TODO' if is_deleted else '✅'}")
        except AttributeError:
            print(f"  • is_deleted: N/A (columna no existe)")
        
        # Configuración de throttling
        alert_cooldown_minutes = getattr(watchlist_item, 'alert_cooldown_minutes', None)
        min_price_change_pct = getattr(watchlist_item, 'min_price_change_pct', None)
        
        print(f"  • alert_cooldown_minutes: {alert_cooldown_minutes or 'default (5 min)'}")
        print(f"  • min_price_change_pct: {min_price_change_pct or 'default (1.0%)'}")
        print()
        
        # Verificar problemas con flags
        issues = []
        if not alert_enabled:
            issues.append("❌ alert_enabled=False - Las alertas están deshabilitadas")
        if alert_enabled and buy_alert_enabled is False:
            issues.append("❌ buy_alert_enabled=False - Las alertas BUY están deshabilitadas")
        if not trade_enabled:
            issues.append("⚠️  trade_enabled=False - Las órdenes están deshabilitadas (pero alertas pueden enviarse)")
        if not trade_amount_usd or trade_amount_usd <= 0:
            issues.append("⚠️  trade_amount_usd no configurado - Las órdenes no se crearán (pero alertas pueden enviarse)")
        
        if issues:
            print("  ⚠️  PROBLEMAS DETECTADOS:")
            for issue in issues:
                print(f"     {issue}")
            print()
        
        # ========================================================================
        # 2. ESTADO DE THROTTLING
        # ========================================================================
        print("⏱️  2. ESTADO DE THROTTLING (Cooldown y Cambio de Precio)")
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
                    print(f"     • Tiempo transcurrido: {time_diff:.2f} minutos")
                    print(f"     • Cooldown requerido: {cooldown} minutos")
                    print(f"     • Cooldown cumplido: {'✅ SÍ' if cooldown_met else f'❌ NO (faltan {cooldown - time_diff:.2f} min)'}")
                    print()
                    
                    # Verificar cambio de precio
                    current_price = watchlist_item.price or 0.0
                    if last_price > 0 and current_price > 0:
                        price_change_pct = abs((current_price - last_price) / last_price) * 100
                        min_change = min_price_change_pct or 1.0
                        price_change_met = price_change_pct >= min_change
                        
                        print(f"  💰 Cambio de precio:")
                        print(f"     • Precio anterior: ${last_price:.4f}")
                        print(f"     • Precio actual: ${current_price:.4f}")
                        print(f"     • Cambio: {price_change_pct:.2f}%")
                        print(f"     • Cambio mínimo requerido: {min_change}%")
                        print(f"     • Cambio cumplido: {'✅ SÍ' if price_change_met else f'❌ NO (faltan {min_change - price_change_pct:.2f}%)'}")
                        print()
                        
                        # Verificar si throttle permite enviar
                        if cooldown_met and price_change_met:
                            print(f"  ✅ THROTTLE: Permitido (cooldown ✅ y cambio de precio ✅)")
                        else:
                            print(f"  ❌ THROTTLE: Bloqueado")
                            if not cooldown_met:
                                print(f"     • Razón: Cooldown no cumplido ({time_diff:.2f} min < {cooldown} min)")
                            if not price_change_met:
                                print(f"     • Razón: Cambio de precio insuficiente ({price_change_pct:.2f}% < {min_change}%)")
                    else:
                        print(f"  ⚠️  No se puede calcular cambio de precio (precio anterior o actual no disponible)")
                else:
                    print(f"  ✅ No hay alertas BUY previas - throttle no bloquea")
            else:
                print(f"  ✅ No hay alertas BUY previas - throttle no bloquea")
            print()
        except Exception as e:
            print(f"  ⚠️  Error verificando throttle: {e}")
            print()
        
        # ========================================================================
        # 3. ÓRDENES ABIERTAS
        # ========================================================================
        print("📊 3. ÓRDENES ABIERTAS (Límites)")
        print("-" * 80)
        
        try:
            base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
            open_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).count()
            
            base_open = count_open_positions_for_symbol(db, base_symbol)
            MAX_OPEN = 3
            
            print(f"  • Órdenes abiertas para {symbol}: {open_orders}")
            print(f"  • Órdenes abiertas para {base_symbol} (base): {base_open}/{MAX_OPEN}")
            print(f"  • Límite máximo: {MAX_OPEN} órdenes por símbolo")
            
            if base_open >= MAX_OPEN:
                print(f"  ❌ LÍMITE ALCANZADO: {base_open} >= {MAX_OPEN} - Las órdenes están bloqueadas")
            else:
                print(f"  ✅ Límite OK: {base_open} < {MAX_OPEN}")
            print()
        except Exception as e:
            print(f"  ⚠️  Error verificando órdenes abiertas: {e}")
            print()
        
        # ========================================================================
        # 4. VALOR DE PORTFOLIO
        # ========================================================================
        print("💰 4. VALOR DE PORTFOLIO (Límite 3x trade_amount_usd)")
        print("-" * 80)
        
        try:
            current_price = watchlist_item.price or 0.0
            if current_price > 0 and trade_amount_usd:
                portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                limit_value = 3 * trade_amount_usd
                
                print(f"  • Precio actual: ${current_price:.4f}")
                print(f"  • trade_amount_usd: ${trade_amount_usd:.2f}")
                print(f"  • Límite (3x): ${limit_value:.2f}")
                print(f"  • Valor de portfolio para {symbol}: ${portfolio_value:.2f}")
                print(f"  • Cantidad neta: {net_quantity:.4f}")
                
                if portfolio_value > limit_value:
                    print(f"  ❌ LÍMITE EXCEDIDO: ${portfolio_value:.2f} > ${limit_value:.2f}")
                    print(f"     Las órdenes están bloqueadas, pero las alertas se envían")
                else:
                    print(f"  ✅ Límite OK: ${portfolio_value:.2f} <= ${limit_value:.2f}")
            else:
                print(f"  ⚠️  No se puede verificar (precio o trade_amount_usd no disponible)")
            print()
        except Exception as e:
            print(f"  ⚠️  Error verificando portfolio: {e}")
            print()
        
        # ========================================================================
        # 5. INDICADORES TÉCNICOS (MAs)
        # ========================================================================
        print("📈 5. INDICADORES TÉCNICOS (Requeridos para Órdenes)")
        print("-" * 80)
        
        ma50 = watchlist_item.ma50
        ema10 = watchlist_item.ema10
        ma200 = watchlist_item.ma200
        
        print(f"  • MA50: {ma50 if ma50 else '❌ NO DISPONIBLE'}")
        print(f"  • EMA10: {ema10 if ema10 else '❌ NO DISPONIBLE'}")
        print(f"  • MA200: {ma200 if ma200 else 'N/A'}")
        
        if ma50 is None or ema10 is None:
            print(f"  ❌ MAs REQUERIDOS FALTANTES: Las órdenes NO se crearán sin MAs")
            print(f"     (Las alertas SÍ se envían aunque falten MAs)")
        else:
            print(f"  ✅ MAs disponibles - Las órdenes pueden crearse")
        print()
        
        # ========================================================================
        # 6. RESUMEN Y RECOMENDACIONES
        # ========================================================================
        print("=" * 80)
        print("📝 RESUMEN Y RECOMENDACIONES")
        print("=" * 80)
        print()
        
        # Verificar condiciones para alertas
        can_send_alert = (
            alert_enabled and 
            (buy_alert_enabled or (alert_enabled and buy_alert_enabled is None))
        )
        
        # Verificar condiciones para órdenes
        can_create_order = (
            can_send_alert and
            trade_enabled and
            trade_amount_usd and trade_amount_usd > 0 and
            ma50 is not None and
            ema10 is not None and
            base_open < MAX_OPEN
        )
        
        print(f"🔔 ALERTAS:")
        if can_send_alert:
            print(f"   ✅ Condiciones básicas cumplidas")
            print(f"   ⚠️  Verificar throttle (cooldown y cambio de precio)")
        else:
            print(f"   ❌ Condiciones básicas NO cumplidas:")
            if not alert_enabled:
                print(f"      • Activar 'alert_enabled' en el dashboard")
            if alert_enabled and buy_alert_enabled is False:
                print(f"      • Activar 'buy_alert_enabled' en el dashboard")
        
        print()
        print(f"📦 ÓRDENES:")
        if can_create_order:
            print(f"   ✅ Condiciones básicas cumplidas")
            print(f"   ⚠️  Verificar throttle y límites de portfolio")
        else:
            print(f"   ❌ Condiciones básicas NO cumplidas:")
            if not can_send_alert:
                print(f"      • Primero activar alertas (ver arriba)")
            if not trade_enabled:
                print(f"      • Activar 'trade_enabled' en el dashboard")
            if not trade_amount_usd or trade_amount_usd <= 0:
                print(f"      • Configurar 'trade_amount_usd' en el dashboard")
            if ma50 is None or ema10 is None:
                print(f"      • Esperar a que los MAs estén disponibles (se actualizan automáticamente)")
            if base_open >= MAX_OPEN:
                print(f"      • Cerrar órdenes existentes (máximo {MAX_OPEN} órdenes por símbolo)")
        
        print()
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error en diagnóstico: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()





