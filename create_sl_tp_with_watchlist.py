#!/usr/bin/env python3
"""
Script para crear órdenes SL/TP con watchlist_item configurado
"""
import os
import sys

sys.path.insert(0, '/app')

def create_sl_tp_with_watchlist(order_id: str):
    """Crear SL/TP con watchlist_item configurado"""
    
    print("=" * 80)
    print("🛡️ CREAR ÓRDENES SL/TP (Con Watchlist)")
    print("=" * 80)
    print(f"📋 Order ID: {order_id}")
    print()
    
    try:
        from app.database import SessionLocal
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from app.services.exchange_sync import exchange_sync_service
        from app.models.watchlist import WatchlistItem
        
        db = SessionLocal()
        
        try:
            # Buscar la orden
            print("🔍 Buscando orden...")
            order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order_id
            ).first()
            
            if not order:
                print(f"❌ Orden {order_id} no encontrada")
                return False
            
            symbol = order.symbol
            print(f"✅ Orden encontrada: {symbol} {order.side.value if hasattr(order.side, 'value') else order.side}")
            print(f"   Status: {order.status.value if hasattr(order.status, 'value') else order.status}")
            print()
            
            # Verificar/Crear watchlist_item
            print(f"🔍 Verificando watchlist_item para {symbol}...")
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if not watchlist_item:
                print(f"⚠️ No hay watchlist_item para {symbol}")
                print("   Creando watchlist_item con configuración por defecto...")
                
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    sl_tp_mode="conservative",
                    trade_enabled=True,  # CRÍTICO: Debe estar activado
                    is_deleted=False
                )
                db.add(watchlist_item)
                db.commit()
                db.refresh(watchlist_item)
                print(f"✅ Watchlist item creado para {symbol}")
            else:
                print(f"✅ Watchlist item encontrado para {symbol}")
                
                # Verificar si trade_enabled está activado
                if not getattr(watchlist_item, 'trade_enabled', False):
                    print(f"⚠️ trade_enabled está desactivado para {symbol}")
                    print("   Activando trade_enabled...")
                    watchlist_item.trade_enabled = True
                    db.commit()
                    db.refresh(watchlist_item)
                    print(f"✅ trade_enabled activado")
            
            print()
            print(f"📊 Configuración de watchlist:")
            print(f"   SL/TP Mode: {watchlist_item.sl_tp_mode or 'conservative'}")
            print(f"   Trade Enabled: {watchlist_item.trade_enabled}")
            if watchlist_item.sl_percentage:
                print(f"   SL Percentage: {watchlist_item.sl_percentage}%")
            if watchlist_item.tp_percentage:
                print(f"   TP Percentage: {watchlist_item.tp_percentage}%")
            print()
            
            # Obtener detalles de la orden
            side = order.side.value if hasattr(order.side, 'value') else str(order.side)
            filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
            filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
            
            print(f"📊 Creando SL/TP para:")
            print(f"   Symbol: {symbol}")
            print(f"   Side: {side}")
            print(f"   Filled Price: ${filled_price:,.4f}")
            print(f"   Filled Quantity: {filled_qty:.8f}")
            print()
            print("⏳ Creando órdenes SL/TP...")
            print()
            
            # Crear SL/TP (saltando el sync de open orders que causa error)
            # Llamar directamente a la parte que crea las órdenes
            try:
                # Omitir el sync de open orders que falla
                # y llamar directamente a la creación
                exchange_sync_service._create_sl_tp_for_filled_order(
                    db=db,
                    symbol=symbol,
                    side=side,
                    filled_price=filled_price,
                    filled_qty=filled_qty,
                    order_id=order_id
                )
                
                # Verificar que se crearon
                new_sl_tp = db.query(ExchangeOrder).filter(
                    ExchangeOrder.parent_order_id == order_id,
                    ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                ).all()
                
                if new_sl_tp:
                    print("✅ ✅ ✅ ÉXITO! Órdenes SL/TP creadas")
                    print()
                    print(f"🛡️ Órdenes de Protección Creadas: {len(new_sl_tp)}")
                    print()
                    for sl_tp_order in new_sl_tp:
                        role = sl_tp_order.order_role or "UNKNOWN"
                        sl_tp_id = sl_tp_order.exchange_order_id
                        status = sl_tp_order.status.value if hasattr(sl_tp_order.status, 'value') else str(sl_tp_order.status)
                        price = float(sl_tp_order.price) if sl_tp_order.price else None
                        quantity = float(sl_tp_order.quantity) if sl_tp_order.quantity else None
                        
                        emoji = "🛑" if role == "STOP_LOSS" else "🎯"
                        print(f"   {emoji} {role}:")
                        print(f"      Order ID: {sl_tp_id}")
                        print(f"      Status: {status}")
                        if price:
                            print(f"      Price: ${price:,.4f}")
                        if quantity:
                            print(f"      Quantity: {quantity:.8f}")
                        print()
                    return True
                else:
                    print("⚠️ No se crearon órdenes SL/TP")
                    print("   Revisa los logs para más detalles")
                    return False
                    
            except Exception as create_err:
                print(f"❌ Error al crear SL/TP: {create_err}")
                import traceback
                traceback.print_exc()
                return False
                
        finally:
            db.close()
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    order_id = sys.argv[1] if len(sys.argv) > 1 else "5755600480818690399"
    success = create_sl_tp_with_watchlist(order_id)
    sys.exit(0 if success else 1)

