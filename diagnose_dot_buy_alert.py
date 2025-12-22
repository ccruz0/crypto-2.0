#!/usr/bin/env python3
"""
Script de diagnóstico para DOT_USDT BUY alert
Verifica configuración en base de datos y estado del throttle
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Agregar el directorio backend al path
# Funciona tanto desde la raíz del proyecto como desde backend/scripts
script_dir = os.path.dirname(os.path.abspath(__file__))

# Si el script está en backend/scripts, subir un nivel para llegar a backend
if os.path.basename(os.path.dirname(script_dir)) == 'scripts' and os.path.basename(os.path.dirname(os.path.dirname(script_dir))) == 'backend':
    backend_dir = os.path.dirname(os.path.dirname(script_dir))
    sys.path.insert(0, backend_dir)
# Si el script está en la raíz, agregar backend
elif os.path.basename(script_dir) != 'backend' and os.path.basename(script_dir) != 'scripts':
    backend_dir = os.path.join(script_dir, 'backend')
    if os.path.exists(backend_dir):
        sys.path.insert(0, backend_dir)

# También intentar /app para Docker (cuando se ejecuta dentro del contenedor)
sys.path.insert(0, '/app')

try:
    from app.database import SessionLocal
    from app.models.watchlist import WatchlistItem
    from app.models.signal_throttle import SignalThrottleState
    from app.models.market_data import MarketData
    from app.models.market_price import MarketPrice
    from app.models.exchange_order import ExchangeOrder, OrderSideEnum
    from sqlalchemy import func
except ImportError as e:
    print(f"❌ Error importando módulos: {e}")
    print(f"Script dir: {script_dir}")
    print(f"Backend dir: {backend_dir}")
    print(f"Python path: {sys.path}")
    print("\nAsegúrate de ejecutar este script desde:")
    print("  1. El directorio raíz del proyecto: python3 diagnose_dot_buy_alert.py")
    print("  2. O desde backend/scripts: python3 scripts/diagnose_dot_buy_alert.py")
    sys.exit(1)

SYMBOL = "DOT_USDT"

def main():
    print("=" * 60)
    print(f"🔍 DIAGNÓSTICO: {SYMBOL} BUY Alert")
    print("=" * 60)
    print()
    
    db = SessionLocal()
    try:
        # 1. Verificar configuración del watchlist
        print("1️⃣ CONFIGURACIÓN DEL WATCHLIST")
        print("-" * 60)
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == SYMBOL,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            print(f"❌ {SYMBOL} no encontrado en watchlist o está marcado como eliminado")
            # Buscar todos los registros
            all_items = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == SYMBOL
            ).all()
            if all_items:
                print(f"⚠️  Se encontraron {len(all_items)} registros (algunos pueden estar eliminados):")
                for i in all_items:
                    print(f"   - ID: {i.id}, alert_enabled: {getattr(i, 'alert_enabled', 'N/A')}, is_deleted: {getattr(i, 'is_deleted', False)}")
            return
        
        print(f"✅ {SYMBOL} encontrado en watchlist")
        print(f"   - alert_enabled: {item.alert_enabled}")
        print(f"   - buy_alert_enabled: {getattr(item, 'buy_alert_enabled', 'N/A')}")
        print(f"   - sell_alert_enabled: {getattr(item, 'sell_alert_enabled', 'N/A')}")
        print(f"   - trade_enabled: {item.trade_enabled}")
        print(f"   - trade_on_margin: {getattr(item, 'trade_on_margin', 'N/A')}")
        print(f"   - trade_amount_usd: {item.trade_amount_usd}")
        print(f"   - min_price_change_pct: {getattr(item, 'min_price_change_pct', 'N/A')}")
        print(f"   - alert_cooldown_minutes: {getattr(item, 'alert_cooldown_minutes', 'N/A')}")
        print()
        
        # Verificar flags críticos
        if not item.alert_enabled:
            print("🚫 PROBLEMA: alert_enabled = False (master switch deshabilitado)")
        if not getattr(item, 'buy_alert_enabled', False):
            print("🚫 PROBLEMA: buy_alert_enabled = False (alertas BUY deshabilitadas)")
        if item.alert_enabled and getattr(item, 'buy_alert_enabled', False):
            print("✅ Flags de alerta están habilitados")
        print()
        
        # 2. Verificar estado del throttle
        print("2️⃣ ESTADO DEL THROTTLE (Últimas señales)")
        print("-" * 60)
        throttle_states = db.query(SignalThrottleState).filter(
            SignalThrottleState.symbol == SYMBOL
        ).order_by(SignalThrottleState.last_time.desc().nulls_last()).all()
        
        if not throttle_states:
            print("ℹ️  No hay registros de throttle (primera señal o nunca se ha enviado)")
        else:
            for state in throttle_states[:5]:  # Mostrar últimos 5
                print(f"   - Side: {state.side}, Strategy: {state.strategy_key}")
                print(f"     Last Price: ${state.last_price:.4f}" if state.last_price else "     Last Price: N/A")
                print(f"     Last Time: {state.last_time}" if state.last_time else "     Last Time: N/A")
                print(f"     Force Next: {getattr(state, 'force_next_signal', False)}")
                print()
                
                # Calcular tiempo desde última señal
                if state.last_time and state.side == "BUY":
                    now = datetime.now(timezone.utc)
                    if state.last_time.tzinfo is None:
                        last_time_utc = state.last_time.replace(tzinfo=timezone.utc)
                    else:
                        last_time_utc = state.last_time.astimezone(timezone.utc)
                    
                    elapsed = now - last_time_utc
                    elapsed_minutes = elapsed.total_seconds() / 60.0
                    cooldown = getattr(item, 'alert_cooldown_minutes', 0) or 0
                    
                    print(f"     ⏱️  Tiempo desde última señal BUY: {elapsed_minutes:.1f} minutos")
                    if cooldown > 0:
                        if elapsed_minutes < cooldown:
                            remaining = cooldown - elapsed_minutes
                            print(f"     🚫 Cooldown activo: faltan {remaining:.1f} minutos")
                        else:
                            print(f"     ✅ Cooldown cumplido")
        print()
        
        # 3. Verificar precio actual y cambio desde última señal
        print("3️⃣ PRECIO ACTUAL Y CAMBIO")
        print("-" * 60)
        market_price = db.query(MarketPrice).filter(
            MarketPrice.symbol == SYMBOL
        ).order_by(MarketPrice.updated_at.desc()).first()
        
        if market_price:
            current_price = market_price.price
            print(f"   Precio actual: ${current_price:.4f}")
            print(f"   Última actualización: {market_price.updated_at}")
            
            # Comparar con última señal BUY
            last_buy_state = next((s for s in throttle_states if s.side == "BUY"), None)
            if last_buy_state and last_buy_state.last_price:
                price_change = abs((current_price - last_buy_state.last_price) / last_buy_state.last_price * 100)
                min_change = getattr(item, 'min_price_change_pct', 0) or 0
                print(f"   Última señal BUY: ${last_buy_state.last_price:.4f}")
                print(f"   Cambio de precio: {price_change:.2f}%")
                print(f"   Mínimo requerido: {min_change}%")
                if min_change > 0:
                    if price_change < min_change:
                        remaining_pct = min_change - price_change
                        print(f"   🚫 Cambio insuficiente: faltan {remaining_pct:.2f}%")
                    else:
                        print(f"   ✅ Cambio de precio suficiente")
        else:
            print("   ⚠️  No se encontró precio de mercado")
        print()
        
        # 4. Verificar órdenes recientes
        print("4️⃣ ÓRDENES RECIENTES")
        print("-" * 60)
        recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == SYMBOL,
            ExchangeOrder.side == OrderSideEnum.BUY
        ).order_by(
            func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
        ).limit(5).all()
        
        if recent_orders:
            print(f"   Últimas {len(recent_orders)} órdenes BUY:")
            for order in recent_orders:
                create_time = order.exchange_create_time or order.created_at
                print(f"   - {create_time}: {order.status.value} @ ${order.price:.4f}")
        else:
            print("   ℹ️  No hay órdenes BUY recientes")
        print()
        
        # 5. Resumen y recomendaciones
        print("5️⃣ RESUMEN Y RECOMENDACIONES")
        print("-" * 60)
        
        issues = []
        if not item.alert_enabled:
            issues.append("❌ alert_enabled = False")
        if not getattr(item, 'buy_alert_enabled', False):
            issues.append("❌ buy_alert_enabled = False")
        
        last_buy_state = next((s for s in throttle_states if s.side == "BUY"), None)
        if last_buy_state and last_buy_state.last_time and market_price:
            now = datetime.now(timezone.utc)
            if last_buy_state.last_time.tzinfo is None:
                last_time_utc = last_buy_state.last_time.replace(tzinfo=timezone.utc)
            else:
                last_time_utc = last_buy_state.last_time.astimezone(timezone.utc)
            
            elapsed_minutes = (now - last_time_utc).total_seconds() / 60.0
            cooldown = getattr(item, 'alert_cooldown_minutes', 0) or 0
            
            if cooldown > 0 and elapsed_minutes < cooldown:
                issues.append(f"⏱️  Cooldown activo: {elapsed_minutes:.1f}/{cooldown} minutos")
            
            price_change = abs((market_price.price - last_buy_state.last_price) / last_buy_state.last_price * 100)
            min_change = getattr(item, 'min_price_change_pct', 0) or 0
            if min_change > 0 and price_change < min_change:
                issues.append(f"💰 Cambio de precio insuficiente: {price_change:.2f}% < {min_change}%")
        
        if not issues:
            print("✅ No se encontraron problemas obvios en la configuración")
            print("   Verificar logs del backend para ver si el bot está corriendo")
        else:
            print("🚫 PROBLEMAS ENCONTRADOS:")
            for issue in issues:
                print(f"   {issue}")
        
        print()
        print("=" * 60)
        print("✅ DIAGNÓSTICO COMPLETADO")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Error durante diagnóstico: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()

