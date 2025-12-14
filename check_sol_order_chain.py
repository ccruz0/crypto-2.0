#!/usr/bin/env python3
"""
Script para verificar la cadena de órdenes: Compra → SL/TP automáticos
Verifica si la orden TP ejecutada hoy fue creada automáticamente a partir de una compra.
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
    
    print("=" * 80)
    print("VERIFICACIÓN DE CADENA DE ÓRDENES: COMPRA → SL/TP AUTOMÁTICOS")
    print("=" * 80)
    print()
    
    db = SessionLocal()
    try:
        # Buscar la orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        print("🔍 Buscando orden TAKE_PROFIT_LIMIT de SOL_USD ejecutada hoy...")
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
            return
        
        print("✅ Orden TAKE_PROFIT_LIMIT encontrada:")
        print(f"   Order ID: {tp_order.exchange_order_id}")
        print(f"   Fecha ejecución: {tp_order.exchange_update_time or tp_order.updated_at}")
        print(f"   Precio: ${tp_order.avg_price or tp_order.price}")
        print(f"   Cantidad: {tp_order.quantity}")
        print(f"   Parent Order ID: {tp_order.parent_order_id or 'N/A'}")
        print(f"   OCO Group ID: {tp_order.oco_group_id or 'N/A'}")
        print(f"   Order Role: {tp_order.order_role or 'N/A'}")
        print()
        
        # Verificar si tiene parent_order_id (orden padre = compra original)
        if tp_order.parent_order_id:
            print("🔗 Esta orden tiene un Parent Order ID, buscando la orden padre (compra original)...")
            print()
            
            parent_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == tp_order.parent_order_id
            ).first()
            
            if parent_order:
                print("✅ Orden PADRE (Compra Original) encontrada:")
                print(f"   Order ID: {parent_order.exchange_order_id}")
                print(f"   Tipo: {parent_order.order_type}")
                print(f"   Lado: {parent_order.side.value if hasattr(parent_order.side, 'value') else parent_order.side}")
                print(f"   Estado: {parent_order.status.value if hasattr(parent_order.status, 'value') else parent_order.status}")
                print(f"   Precio: ${parent_order.avg_price or parent_order.price}")
                print(f"   Cantidad: {parent_order.quantity}")
                print(f"   Fecha creación: {parent_order.exchange_create_time or parent_order.created_at}")
                print(f"   Fecha ejecución: {parent_order.exchange_update_time or parent_order.updated_at}")
                print()
                
                # Verificar si es una orden BUY (compra)
                is_buy = parent_order.side == OrderSideEnum.BUY
                is_filled = parent_order.status == OrderStatusEnum.FILLED
                is_limit_or_market = parent_order.order_type in ['LIMIT', 'MARKET']
                
                if is_buy and is_filled and is_limit_or_market:
                    print("✅ CONFIRMADO: Esta orden TP fue creada AUTOMÁTICAMENTE")
                    print("   ✓ Orden padre es una COMPRA (BUY)")
                    print("   ✓ Orden padre está EJECUTADA (FILLED)")
                    print("   ✓ Orden padre es LIMIT o MARKET (tipo que genera SL/TP automático)")
                    print()
                    print("📋 FLUJO:")
                    print(f"   1. Orden BUY ejecutada: {parent_order.exchange_order_id}")
                    print(f"      - Precio: ${parent_order.avg_price or parent_order.price}")
                    print(f"      - Cantidad: {parent_order.quantity}")
                    print(f"      - Fecha: {parent_order.exchange_update_time or parent_order.updated_at}")
                    print()
                    print(f"   2. Sistema creó automáticamente SL/TP:")
                    print(f"      - SL (Stop Loss): Orden STOP_LIMIT asociada")
                    print(f"      - TP (Take Profit): {tp_order.exchange_order_id} ✅ EJECUTADA")
                    print()
                    
                    # Buscar la orden SL asociada
                    sl_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == tp_order.parent_order_id,
                        ExchangeOrder.order_type == 'STOP_LIMIT',
                        ExchangeOrder.order_role == 'STOP_LOSS'
                    ).first()
                    
                    if sl_order:
                        print(f"   3. SL (Stop Loss) asociada:")
                        print(f"      - Order ID: {sl_order.exchange_order_id}")
                        print(f"      - Estado: {sl_order.status.value if hasattr(sl_order.status, 'value') else sl_order.status}")
                        print(f"      - Precio trigger: ${sl_order.trigger_condition or sl_order.price}")
                    else:
                        print(f"   3. SL (Stop Loss): No encontrada o ya cancelada")
                else:
                    print("⚠️  La orden padre NO es una compra BUY ejecutada")
                    print(f"   - Es BUY: {is_buy}")
                    print(f"   - Está FILLED: {is_filled}")
                    print(f"   - Es LIMIT/MARKET: {is_limit_or_market}")
            else:
                print(f"⚠️  No se encontró la orden padre con ID: {tp_order.parent_order_id}")
                print("   Esto puede significar que la orden padre fue eliminada o no está en la base de datos.")
        else:
            print("⚠️  Esta orden NO tiene Parent Order ID")
            print("   Esto significa que:")
            print("   1. Fue creada manualmente (no automáticamente)")
            print("   2. O la vinculación se perdió")
            print("   3. O es una orden muy antigua antes de implementar parent_order_id")
        
        print()
        print("=" * 80)
        print("RESUMEN:")
        print("=" * 80)
        if tp_order.parent_order_id:
            if parent_order and parent_order.side == OrderSideEnum.BUY:
                print("✅ SÍ: Las órdenes SL/TP fueron creadas automáticamente a partir de una COMPRA")
                print(f"   Orden de compra: {parent_order.exchange_order_id}")
                print(f"   Orden TP ejecutada: {tp_order.exchange_order_id}")
            else:
                print("❓ La orden TP tiene parent_order_id pero la orden padre no es una compra BUY")
        else:
            print("❌ NO: La orden TP no tiene parent_order_id, no se puede confirmar si fue automática")
    
    finally:
        db.close()

except ImportError as e:
    print(f"❌ Error al importar módulos: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()


