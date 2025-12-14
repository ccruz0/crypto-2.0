#!/usr/bin/env python3
"""
Script para encontrar la orden de compra (BUY) original que generó las órdenes SL/TP
de SOL_USD que se ejecutaron hoy.
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
    
    print("=" * 80)
    print("BÚSQUEDA DE ORDEN DE COMPRA ORIGINAL PARA SOL_USD")
    print("=" * 80)
    print()
    
    db = SessionLocal()
    try:
        # Buscar la orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        print("🔍 Paso 1: Buscando orden TAKE_PROFIT_LIMIT ejecutada hoy...")
        print()
        
        tp_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == 'SOL_USD',
            ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_update_time >= today_start,
            ExchangeOrder.exchange_update_time <= today_end
        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not tp_order:
            print("⚠️  No se encontró orden TP de hoy. Buscando la más reciente...")
            tp_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == 'SOL_USD',
                ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
                ExchangeOrder.status == OrderStatusEnum.FILLED
            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not tp_order:
            print("❌ No se encontró ninguna orden TAKE_PROFIT_LIMIT de SOL_USD.")
            db.close()
            sys.exit(0)
        
        print("✅ Orden TAKE_PROFIT_LIMIT encontrada:")
        print(f"   Order ID: {tp_order.exchange_order_id}")
        print(f"   Fecha ejecución: {tp_order.exchange_update_time or tp_order.updated_at}")
        print(f"   Precio ejecución: ${tp_order.avg_price or tp_order.price}")
        print(f"   Cantidad: {tp_order.quantity}")
        print(f"   Parent Order ID: {tp_order.parent_order_id or 'N/A'}")
        print()
        
        if not tp_order.parent_order_id:
            print("⚠️  Esta orden TP NO tiene Parent Order ID.")
            print("   Buscando órdenes BUY recientes de SOL_USD como alternativa...")
            print()
            
            # Buscar órdenes BUY recientes de SOL_USD
            buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == 'SOL_USD',
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status == OrderStatusEnum.FILLED,
                ExchangeOrder.order_type.in_(['LIMIT', 'MARKET'])
            ).order_by(ExchangeOrder.exchange_update_time.desc()).limit(5).all()
            
            if buy_orders:
                print(f"📋 Encontradas {len(buy_orders)} órdenes BUY recientes de SOL_USD:")
                print()
                for i, buy in enumerate(buy_orders, 1):
                    print(f"   {i}. Order ID: {buy.exchange_order_id}")
                    print(f"      Fecha: {buy.exchange_update_time or buy.updated_at}")
                    print(f"      Precio: ${buy.avg_price or buy.price}")
                    print(f"      Cantidad: {buy.quantity}")
                    print(f"      Tipo: {buy.order_type}")
                    print()
                
                # Buscar SL/TP asociadas a estas órdenes BUY
                print("🔍 Buscando órdenes SL/TP asociadas a estas compras...")
                print()
                for buy in buy_orders[:3]:  # Revisar las 3 más recientes
                    sl_orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == buy.exchange_order_id,
                        ExchangeOrder.order_type == 'STOP_LIMIT'
                    ).all()
                    tp_orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == buy.exchange_order_id,
                        ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT'
                    ).all()
                    
                    if sl_orders or tp_orders:
                        print(f"✅ Orden BUY {buy.exchange_order_id} tiene SL/TP asociadas:")
                        print(f"   - SL: {len(sl_orders)} orden(es)")
                        print(f"   - TP: {len(tp_orders)} orden(es)")
                        if tp_orders:
                            for tp in tp_orders:
                                if tp.exchange_order_id == tp_order.exchange_order_id:
                                    print(f"   ⭐ Esta es la orden TP ejecutada hoy!")
                                    print()
                                    print("=" * 80)
                                    print("✅ ORDEN DE COMPRA ORIGINAL ENCONTRADA:")
                                    print("=" * 80)
                                    print(f"   Order ID: {buy.exchange_order_id}")
                                    print(f"   Tipo: {buy.order_type}")
                                    print(f"   Lado: BUY (Compra)")
                                    print(f"   Estado: FILLED (Ejecutada)")
                                    print(f"   Precio de compra: ${buy.avg_price or buy.price}")
                                    print(f"   Cantidad: {buy.quantity}")
                                    print(f"   Valor total: ${float(buy.cumulative_value) if buy.cumulative_value else float(buy.avg_price or buy.price) * float(buy.quantity):.2f}")
                                    print(f"   Fecha de compra: {buy.exchange_update_time or buy.updated_at}")
                                    print()
                                    print("📊 Resumen de la operación completa:")
                                    print(f"   1. Compra ejecutada: {buy.exchange_order_id}")
                                    print(f"      - Precio: ${buy.avg_price or buy.price}")
                                    print(f"      - Cantidad: {buy.quantity}")
                                    print()
                                    print(f"   2. SL/TP creadas automáticamente:")
                                    for sl in sl_orders:
                                        print(f"      - SL: {sl.exchange_order_id} (Estado: {sl.status.value if hasattr(sl.status, 'value') else sl.status})")
                                    for tp in tp_orders:
                                        status_icon = "✅" if tp.status == OrderStatusEnum.FILLED else "⏳"
                                        print(f"      - TP: {tp.exchange_order_id} {status_icon} (Estado: {tp.status.value if hasattr(tp.status, 'value') else tp.status})")
                                        if tp.status == OrderStatusEnum.FILLED:
                                            print(f"        Precio ejecución: ${tp.avg_price or tp.price}")
                                            print(f"        Ganancia: ${float(tp.cumulative_value) - float(buy.cumulative_value) if (tp.cumulative_value and buy.cumulative_value) else 'N/A'}")
                                    db.close()
                                    sys.exit(0)
                        print()
        else:
            print("🔍 Paso 2: Buscando orden padre (compra original)...")
            print(f"   Parent Order ID: {tp_order.parent_order_id}")
            print()
            
            parent_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == tp_order.parent_order_id
            ).first()
            
            if parent_order:
                print("=" * 80)
                print("✅ ORDEN DE COMPRA ORIGINAL ENCONTRADA:")
                print("=" * 80)
                print(f"   Order ID: {parent_order.exchange_order_id}")
                print(f"   Tipo: {parent_order.order_type}")
                print(f"   Lado: {parent_order.side.value if hasattr(parent_order.side, 'value') else parent_order.side}")
                print(f"   Estado: {parent_order.status.value if hasattr(parent_order.status, 'value') else parent_order.status}")
                print(f"   Precio de compra: ${parent_order.avg_price or parent_order.price}")
                print(f"   Cantidad: {parent_order.quantity}")
                print(f"   Valor total: ${float(parent_order.cumulative_value) if parent_order.cumulative_value else float(parent_order.avg_price or parent_order.price) * float(parent_order.quantity):.2f}")
                print(f"   Fecha de compra: {parent_order.exchange_update_time or parent_order.updated_at}")
                print()
                
                # Verificar si es una compra BUY
                if parent_order.side == OrderSideEnum.BUY:
                    print("✅ Confirmado: Esta es una orden de COMPRA (BUY)")
                    print()
                    
                    # Buscar todas las órdenes SL/TP asociadas
                    sl_orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == parent_order.exchange_order_id,
                        ExchangeOrder.order_type == 'STOP_LIMIT'
                    ).all()
                    tp_orders = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == parent_order.exchange_order_id,
                        ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT'
                    ).all()
                    
                    print("📊 Resumen de la operación completa:")
                    print(f"   1. Compra ejecutada: {parent_order.exchange_order_id}")
                    print(f"      - Precio: ${parent_order.avg_price or parent_order.price}")
                    print(f"      - Cantidad: {parent_order.quantity}")
                    print(f"      - Fecha: {parent_order.exchange_update_time or parent_order.updated_at}")
                    print()
                    print(f"   2. SL/TP creadas automáticamente:")
                    for sl in sl_orders:
                        status_icon = "✅" if sl.status == OrderStatusEnum.CANCELLED else "⏳" if sl.status in [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE] else "❌"
                        print(f"      - SL: {sl.exchange_order_id} {status_icon} (Estado: {sl.status.value if hasattr(sl.status, 'value') else sl.status})")
                        if sl.price:
                            print(f"        Precio trigger: ${sl.price}")
                    for tp in tp_orders:
                        status_icon = "✅" if tp.status == OrderStatusEnum.FILLED else "⏳" if tp.status in [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE] else "❌"
                        print(f"      - TP: {tp.exchange_order_id} {status_icon} (Estado: {tp.status.value if hasattr(tp.status, 'value') else tp.status})")
                        if tp.status == OrderStatusEnum.FILLED:
                            print(f"        Precio ejecución: ${tp.avg_price or tp.price}")
                            # Calcular ganancia
                            buy_value = float(parent_order.cumulative_value) if parent_order.cumulative_value else float(parent_order.avg_price or parent_order.price) * float(parent_order.quantity)
                            tp_value = float(tp.cumulative_value) if tp.cumulative_value else float(tp.avg_price or tp.price) * float(tp.quantity)
                            profit = tp_value - buy_value
                            profit_pct = (profit / buy_value * 100) if buy_value > 0 else 0
                            print(f"        Ganancia: ${profit:.2f} ({profit_pct:+.2f}%)")
                    print()
                    print("=" * 80)
                    print("CONCLUSIÓN:")
                    print("=" * 80)
                    print("✅ Las órdenes SL/TP fueron creadas AUTOMÁTICAMENTE")
                    print(f"   a partir de la orden de compra {parent_order.exchange_order_id}")
                    print()
                    print("📋 Flujo:")
                    print("   1. Orden BUY ejecutada → Sistema detecta FILLED")
                    print("   2. Sistema crea automáticamente SL y TP")
                    print("   3. TP se ejecutó hoy con ganancia")
                    print("   4. SL debería haberse cancelado automáticamente")
                else:
                    print("⚠️  La orden padre NO es una compra BUY")
                    print(f"   Es: {parent_order.side.value if hasattr(parent_order.side, 'value') else parent_order.side}")
            else:
                print(f"❌ No se encontró la orden padre con ID: {tp_order.parent_order_id}")
                print("   La orden de compra original puede haber sido eliminada o no está en la base de datos.")
    
    finally:
        db.close()

except ImportError as e:
    print(f"❌ Error al importar módulos: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()


