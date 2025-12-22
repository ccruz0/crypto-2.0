#!/usr/bin/env python3
"""
Script para migrar DOT_USD a DOT_USDT en la base de datos.
Esto corrige la inconsistencia donde el código usa DOT_USDT pero la BD tiene DOT_USD.
"""

import sys
import os

# Agregar el directorio backend al path
script_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(os.path.dirname(script_dir)) == 'scripts' and os.path.basename(os.path.dirname(os.path.dirname(script_dir))) == 'backend':
    backend_dir = os.path.dirname(os.path.dirname(script_dir))
    sys.path.insert(0, backend_dir)
else:
    backend_dir = os.path.join(script_dir, 'backend')
    if os.path.exists(backend_dir):
        sys.path.insert(0, backend_dir)

sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData
from app.models.exchange_order import ExchangeOrder
from app.models.signal_throttle import SignalThrottleState

def migrate_dot_symbol():
    """Migrar DOT_USD a DOT_USDT"""
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("🔄 MIGRACIÓN: DOT_USD → DOT_USDT")
        print("=" * 60)
        print()
        
        # 1. Verificar si DOT_USDT ya existe
        print("1️⃣ Verificando si DOT_USDT ya existe...")
        dot_usdt_exists = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'DOT_USDT',
            WatchlistItem.is_deleted == False
        ).first()
        
        if dot_usdt_exists:
            print(f"⚠️  DOT_USDT ya existe en watchlist (ID: {dot_usdt_exists.id})")
            print(f"   alert_enabled: {dot_usdt_exists.alert_enabled}")
            print(f"   buy_alert_enabled: {getattr(dot_usdt_exists, 'buy_alert_enabled', 'N/A')}")
            response = input("\n¿Deseas continuar y actualizar DOT_USD a DOT_USDT? (s/n): ")
            if response.lower() != 's':
                print("❌ Migración cancelada")
                return
        else:
            print("✅ DOT_USDT no existe, continuando con la migración...")
        print()
        
        # 2. Buscar DOT_USD
        print("2️⃣ Buscando DOT_USD en watchlist...")
        dot_usd = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'DOT_USD',
            WatchlistItem.is_deleted == False
        ).first()
        
        if not dot_usd:
            print("❌ DOT_USD no encontrado en watchlist (o está eliminado)")
            print("   No hay nada que migrar.")
            return
        
        print(f"✅ DOT_USD encontrado (ID: {dot_usd.id})")
        print(f"   alert_enabled: {dot_usd.alert_enabled}")
        print(f"   buy_alert_enabled: {getattr(dot_usd, 'buy_alert_enabled', 'N/A')}")
        print(f"   trade_enabled: {dot_usd.trade_enabled}")
        print()
        
        # 3. Verificar órdenes asociadas
        print("3️⃣ Verificando órdenes asociadas...")
        orders_count = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == 'DOT_USD'
        ).count()
        print(f"   Órdenes con DOT_USD: {orders_count}")
        if orders_count > 0:
            print("   ⚠️  Hay órdenes asociadas a DOT_USD - estas NO se actualizarán automáticamente")
        print()
        
        # 4. Actualizar watchlist_items
        print("4️⃣ Actualizando watchlist_items...")
        dot_usd.symbol = 'DOT_USDT'
        print(f"   ✅ Símbolo actualizado a DOT_USDT")
        print()
        
        # 5. Manejar market_price (eliminar DOT_USD si DOT_USDT ya existe)
        print("5️⃣ Manejando market_price...")
        market_price_usd = db.query(MarketPrice).filter(
            MarketPrice.symbol == 'DOT_USD'
        ).first()
        market_price_usdt = db.query(MarketPrice).filter(
            MarketPrice.symbol == 'DOT_USDT'
        ).first()
        
        if market_price_usdt:
            print("   ℹ️  DOT_USDT ya existe en market_price")
            if market_price_usd:
                print(f"   🗑️  Eliminando DOT_USD (ID: {market_price_usd.id}) - DOT_USDT ya existe")
                db.delete(market_price_usd)
        elif market_price_usd:
            market_price_usd.symbol = 'DOT_USDT'
            print(f"   ✅ MarketPrice actualizado a DOT_USDT (precio: ${market_price_usd.price:.4f})")
        else:
            print("   ℹ️  No hay registros en market_price")
        print()
        
        # 6. Manejar market_data (eliminar DOT_USD si DOT_USDT ya existe)
        print("6️⃣ Manejando market_data...")
        market_data_usd = db.query(MarketData).filter(
            MarketData.symbol == 'DOT_USD'
        ).first()
        market_data_usdt = db.query(MarketData).filter(
            MarketData.symbol == 'DOT_USDT'
        ).first()
        
        if market_data_usdt:
            print("   ℹ️  DOT_USDT ya existe en market_data")
            if market_data_usd:
                print(f"   🗑️  Eliminando DOT_USD (ID: {market_data_usd.id}) - DOT_USDT ya existe")
                db.delete(market_data_usd)
        elif market_data_usd:
            market_data_usd.symbol = 'DOT_USDT'
            print(f"   ✅ MarketData actualizado a DOT_USDT (precio: ${market_data_usd.price:.4f}, RSI: {market_data_usd.rsi})")
        else:
            print("   ℹ️  No hay registros en market_data")
        print()
        
        # 7. Actualizar signal_throttle_states (usando SQL directo para evitar problemas con campos del modelo)
        print("7️⃣ Actualizando signal_throttle_states...")
        from sqlalchemy import text
        result = db.execute(
            text("UPDATE signal_throttle_states SET symbol = 'DOT_USDT' WHERE symbol = 'DOT_USD'")
        )
        throttle_count = result.rowcount
        if throttle_count > 0:
            print(f"   ✅ {throttle_count} estado(s) de throttle actualizado(s)")
        else:
            print("   ℹ️  No hay estados de throttle para DOT_USD")
        print()
        
        # 8. Confirmar cambios
        print("8️⃣ Confirmando cambios en la base de datos...")
        db.commit()
        print("   ✅ Cambios confirmados")
        print()
        
        # 9. Verificación final
        print("9️⃣ Verificación final...")
        dot_usdt_verify = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'DOT_USDT',
            WatchlistItem.is_deleted == False
        ).first()
        
        if dot_usdt_verify:
            print(f"✅ DOT_USDT existe en watchlist (ID: {dot_usdt_verify.id})")
            print(f"   alert_enabled: {dot_usdt_verify.alert_enabled}")
            print(f"   buy_alert_enabled: {getattr(dot_usdt_verify, 'buy_alert_enabled', 'N/A')}")
            print(f"   trade_enabled: {dot_usdt_verify.trade_enabled}")
        else:
            print("❌ ERROR: DOT_USDT no se encontró después de la migración")
            return
        
        # Verificar que DOT_USD ya no existe (o está eliminado)
        dot_usd_verify = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'DOT_USD',
            WatchlistItem.is_deleted == False
        ).first()
        if dot_usd_verify:
            print("⚠️  ADVERTENCIA: DOT_USD todavía existe (no eliminado)")
        else:
            print("✅ DOT_USD ya no existe (o está eliminado)")
        
        print()
        print("=" * 60)
        print("✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")
        print("=" * 60)
        print()
        print("📋 PRÓXIMOS PASOS:")
        print("1. Verificar que el servicio SignalMonitorService procese DOT_USDT")
        print("2. Verificar logs: docker logs backend-aws | grep 'DOT_USDT'")
        print("3. Verificar dashboard que muestra datos correctos")
        print("4. Si hay órdenes abiertas con DOT_USD, considerar actualizarlas manualmente")
        
    except Exception as e:
        print(f"\n❌ ERROR durante la migración: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        print("\n🔄 Cambios revertidos (rollback)")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate_dot_symbol()

