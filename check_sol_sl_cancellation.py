#!/usr/bin/env python3
"""
Script para verificar si la orden de Stop Loss de SOL_USD se canceló correctamente
cuando se ejecutó la orden de Take Profit hoy.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
    from sqlalchemy import and_, or_
    
    print("=" * 80)
    print("VERIFICACIÓN DE CANCELACIÓN DE STOP LOSS PARA SOL_USD")
    print("=" * 80)
    print()
    
    db = SessionLocal()
    try:
        # Buscar la orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        print(f"📅 Buscando órdenes TAKE_PROFIT_LIMIT de SOL_USD ejecutadas hoy ({today_start.date()})...")
        print()
        
        tp_orders = db.query(ExchangeOrder).filter(
            and_(
                ExchangeOrder.symbol == 'SOL_USD',
                ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
                ExchangeOrder.status == OrderStatusEnum.FILLED,
                ExchangeOrder.exchange_update_time >= today_start,
                ExchangeOrder.exchange_update_time <= today_end
            )
        ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
        
        if not tp_orders:
            print("⚠️  No se encontró ninguna orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy.")
            print("   Buscando la más reciente...")
            
            # Buscar la más reciente sin restricción de fecha
            tp_orders = db.query(ExchangeOrder).filter(
                and_(
                    ExchangeOrder.symbol == 'SOL_USD',
                    ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
                    ExchangeOrder.status == OrderStatusEnum.FILLED
                )
            ).order_by(ExchangeOrder.exchange_update_time.desc()).limit(1).all()
        
        if tp_orders:
            tp_order = tp_orders[0]
            print("✅ Orden TAKE_PROFIT_LIMIT encontrada:")
            print(f"   Order ID: {tp_order.exchange_order_id}")
            print(f"   Fecha ejecución: {tp_order.exchange_update_time or tp_order.updated_at}")
            print(f"   Precio límite: ${tp_order.price}")
            print(f"   Precio promedio: ${tp_order.avg_price}")
            print(f"   Cantidad: {tp_order.quantity}")
            print(f"   Parent Order ID: {tp_order.parent_order_id or 'N/A'}")
            print(f"   OCO Group ID: {tp_order.oco_group_id or 'N/A'}")
            print(f"   Order Role: {tp_order.order_role or 'N/A'}")
            print()
            
            # Buscar la orden STOP_LIMIT asociada
            print("🔍 Buscando orden STOP_LIMIT asociada...")
            print()
            
            sl_orders = []
            
            # Estrategia 1: Buscar por parent_order_id
            if tp_order.parent_order_id:
                print(f"   Estrategia 1: Buscando por parent_order_id = {tp_order.parent_order_id}")
                sl_by_parent = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == 'SOL_USD',
                        ExchangeOrder.order_type == 'STOP_LIMIT',
                        ExchangeOrder.parent_order_id == tp_order.parent_order_id
                    )
                ).all()
                sl_orders.extend(sl_by_parent)
                if sl_by_parent:
                    print(f"   ✅ Encontradas {len(sl_by_parent)} órdenes SL por parent_order_id")
            
            # Estrategia 2: Buscar por oco_group_id
            if tp_order.oco_group_id:
                print(f"   Estrategia 2: Buscando por oco_group_id = {tp_order.oco_group_id}")
                sl_by_oco = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == 'SOL_USD',
                        ExchangeOrder.order_type == 'STOP_LIMIT',
                        ExchangeOrder.oco_group_id == tp_order.oco_group_id
                    )
                ).all()
                # Evitar duplicados
                existing_ids = {o.exchange_order_id for o in sl_orders}
                sl_by_oco_unique = [o for o in sl_by_oco if o.exchange_order_id not in existing_ids]
                sl_orders.extend(sl_by_oco_unique)
                if sl_by_oco_unique:
                    print(f"   ✅ Encontradas {len(sl_by_oco_unique)} órdenes SL por oco_group_id")
            
            # Estrategia 3: Buscar por order_role y ventana de tiempo
            if tp_order.exchange_create_time:
                time_window_start = tp_order.exchange_create_time - timedelta(minutes=10)
                time_window_end = tp_order.exchange_create_time + timedelta(minutes=10)
                print(f"   Estrategia 3: Buscando por ventana de tiempo (±10 min)")
                sl_by_time = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == 'SOL_USD',
                        ExchangeOrder.order_type == 'STOP_LIMIT',
                        ExchangeOrder.order_role == 'STOP_LOSS',
                        ExchangeOrder.exchange_create_time >= time_window_start,
                        ExchangeOrder.exchange_create_time <= time_window_end,
                        ExchangeOrder.exchange_order_id != tp_order.exchange_order_id
                    )
                ).all()
                # Evitar duplicados
                existing_ids = {o.exchange_order_id for o in sl_orders}
                sl_by_time_unique = [o for o in sl_by_time if o.exchange_order_id not in existing_ids]
                sl_orders.extend(sl_by_time_unique)
                if sl_by_time_unique:
                    print(f"   ✅ Encontradas {len(sl_by_time_unique)} órdenes SL por ventana de tiempo")
            
            print()
            
            if sl_orders:
                # Eliminar duplicados
                unique_sl_orders = {}
                for sl in sl_orders:
                    if sl.exchange_order_id not in unique_sl_orders:
                        unique_sl_orders[sl.exchange_order_id] = sl
                
                sl_orders = list(unique_sl_orders.values())
                
                print(f"📊 Encontradas {len(sl_orders)} orden(es) STOP_LIMIT asociada(s):")
                print()
                
                for i, sl_order in enumerate(sl_orders, 1):
                    print(f"   Orden SL #{i}:")
                    print(f"   Order ID: {sl_order.exchange_order_id}")
                    print(f"   Status: {sl_order.status.value if hasattr(sl_order.status, 'value') else sl_order.status}")
                    print(f"   Precio trigger: ${sl_order.trigger_condition or sl_order.price}")
                    print(f"   Cantidad: {sl_order.quantity}")
                    print(f"   Parent Order ID: {sl_order.parent_order_id or 'N/A'}")
                    print(f"   OCO Group ID: {sl_order.oco_group_id or 'N/A'}")
                    print(f"   Order Role: {sl_order.order_role or 'N/A'}")
                    print(f"   Fecha creación: {sl_order.exchange_create_time or sl_order.created_at}")
                    print(f"   Fecha actualización: {sl_order.exchange_update_time or sl_order.updated_at}")
                    
                    # Verificar si está cancelada
                    is_cancelled = sl_order.status in [
                        OrderStatusEnum.CANCELLED,
                        OrderStatusEnum.EXPIRED
                    ]
                    is_open = sl_order.status in [
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.OPEN,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED
                    ]
                    
                    if is_cancelled:
                        print(f"   ✅ Estado: CANCELADA (correcto)")
                    elif is_open:
                        print(f"   ⚠️  Estado: ABIERTA (debería estar cancelada)")
                        print(f"   ⚠️  ACCIÓN REQUERIDA: Esta orden debería cancelarse manualmente")
                    elif sl_order.status == OrderStatusEnum.FILLED:
                        print(f"   ℹ️  Estado: EJECUTADA (se ejecutó antes que el TP)")
                    else:
                        print(f"   ℹ️  Estado: {sl_order.status.value if hasattr(sl_order.status, 'value') else sl_order.status}")
                    print()
                
                # Resumen
                cancelled_count = sum(1 for sl in sl_orders if sl.status in [OrderStatusEnum.CANCELLED, OrderStatusEnum.EXPIRED])
                open_count = sum(1 for sl in sl_orders if sl.status in [OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                
                print("=" * 80)
                print("RESUMEN:")
                print("=" * 80)
                print(f"   Órdenes SL encontradas: {len(sl_orders)}")
                print(f"   ✅ Canceladas: {cancelled_count}")
                print(f"   ⚠️  Abiertas: {open_count}")
                print(f"   ℹ️  Otros estados: {len(sl_orders) - cancelled_count - open_count}")
                print()
                
                if open_count > 0:
                    print("⚠️  ADVERTENCIA: Hay órdenes de Stop Loss aún abiertas.")
                    print("   Estas deberían haberse cancelado automáticamente cuando se ejecutó el Take Profit.")
                    print("   Se recomienda cancelarlas manualmente para evitar ejecuciones no deseadas.")
                else:
                    print("✅ Todas las órdenes de Stop Loss fueron canceladas correctamente.")
            else:
                print("⚠️  No se encontró ninguna orden STOP_LIMIT asociada.")
                print("   Esto puede significar:")
                print("   1. La orden SL nunca se creó")
                print("   2. La orden SL se canceló antes de que se ejecutara el TP")
                print("   3. La orden SL se ejecutó antes que el TP")
                print("   4. No hay suficiente información de vinculación (parent_order_id, oco_group_id)")
        else:
            print("❌ No se encontró ninguna orden TAKE_PROFIT_LIMIT de SOL_USD.")
            print("   Verifica que la orden se haya ejecutado hoy y esté en la base de datos.")
    
    finally:
        db.close()

except ImportError as e:
    print(f"❌ Error al importar módulos: {e}")
    print("   Asegúrate de que el backend esté configurado correctamente.")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()







