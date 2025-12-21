#!/usr/bin/env python3
"""
Script para crear órdenes SL/TP directamente usando el código del backend
"""
import os
import sys

# Agregar el directorio backend al path
sys.path.insert(0, '/app')

def create_sl_tp_direct(order_id: str):
    """Crear SL/TP directamente usando el código del backend"""
    
    print("=" * 80)
    print("🛡️ CREAR ÓRDENES SL/TP (Método Directo)")
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
            print("🔍 Buscando orden en la base de datos...")
            order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order_id
            ).first()
            
            if not order:
                print(f"❌ Orden {order_id} no encontrada en la base de datos")
                print()
                print("💡 Posibles causas:")
                print("   - La orden aún no se ha sincronizado desde Crypto.com")
                print("   - El order_id es incorrecto")
                print("   - Necesitas esperar a que exchange_sync sincronice la orden")
                return False
            
            print(f"✅ Orden encontrada: {order.symbol} {order.side.value if hasattr(order.side, 'value') else order.side}")
            print(f"   Status: {order.status.value if hasattr(order.status, 'value') else order.status}")
            print(f"   Price: ${float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0):,.4f}")
            print(f"   Quantity: {float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0):.8f}")
            print()
            
            # Verificar que esté FILLED
            if order.status != OrderStatusEnum.FILLED:
                print(f"⚠️ La orden no está FILLED (status: {order.status.value if hasattr(order.status, 'value') else order.status})")
                print("   Las órdenes SL/TP solo se pueden crear para órdenes FILLED")
                print()
                print("💡 Espera a que la orden se ejecute completamente")
                return False
            
            # Verificar si ya tiene SL/TP
            existing_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            if existing_sl_tp:
                print(f"ℹ️ La orden ya tiene {len(existing_sl_tp)} orden(es) SL/TP:")
                for sl_tp_order in existing_sl_tp:
                    role = sl_tp_order.order_role or "UNKNOWN"
                    sl_tp_id = sl_tp_order.exchange_order_id
                    status = sl_tp_order.status.value if hasattr(sl_tp_order.status, 'value') else str(sl_tp_order.status)
                    emoji = "🛑" if role == "STOP_LOSS" else "🎯"
                    print(f"   {emoji} {role}: {sl_tp_id} (Status: {status})")
                return True
            
            # Obtener detalles de la orden
            symbol = order.symbol
            side = order.side.value if hasattr(order.side, 'value') else str(order.side)
            filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
            filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
            
            if not filled_price or filled_qty <= 0:
                print(f"❌ Orden tiene precio o cantidad inválidos")
                print(f"   Price: {filled_price}, Quantity: {filled_qty}")
                return False
            
            print(f"📊 Creando SL/TP para:")
            print(f"   Symbol: {symbol}")
            print(f"   Side: {side}")
            print(f"   Filled Price: ${filled_price:,.4f}")
            print(f"   Filled Quantity: {filled_qty:.8f}")
            print()
            
            # Verificar watchlist_item
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if watchlist_item:
                print(f"✅ Watchlist item encontrado:")
                print(f"   SL/TP Mode: {watchlist_item.sl_tp_mode or 'conservative'}")
                if watchlist_item.sl_percentage:
                    print(f"   SL Percentage: {watchlist_item.sl_percentage}%")
                if watchlist_item.tp_percentage:
                    print(f"   TP Percentage: {watchlist_item.tp_percentage}%")
            else:
                print(f"⚠️ No hay watchlist_item para {symbol}, usando valores por defecto (3% conservative)")
            
            print()
            print("⏳ Creando órdenes SL/TP...")
            
            # Crear SL/TP
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
                print()
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
                print()
                print("⚠️ No se crearon órdenes SL/TP")
                print("   Puede que haya ocurrido un error silencioso")
                return False
                
        finally:
            db.close()
            
    except Exception as e:
        print()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    order_id = sys.argv[1] if len(sys.argv) > 1 else "5755600480818690399"
    success = create_sl_tp_direct(order_id)
    sys.exit(0 if success else 1)



















