#!/usr/bin/env python3
"""
Script para diagnosticar por qué no se recibió la notificación de Telegram
cuando se crearon las órdenes SL/TP de SOL_USD.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

print("=" * 80)
print("DIAGNÓSTICO: ¿Por qué no se recibió notificación de Telegram para SL/TP?")
print("=" * 80)
print()

# 1. Verificar configuración de Telegram
print("1️⃣ Verificando configuración de Telegram...")
print()

try:
    from app.services.telegram_notifier import telegram_notifier
    from app.core.runtime import get_runtime_origin
    
    print(f"   ✅ TelegramNotifier importado correctamente")
    print(f"   - Habilitado: {telegram_notifier.enabled}")
    print(f"   - Bot Token presente: {'Sí' if telegram_notifier.bot_token else 'No'}")
    print(f"   - Chat ID presente: {'Sí' if telegram_notifier.chat_id else 'No'}")
    print()
    
    # Verificar RUNTIME_ORIGIN
    runtime_origin = get_runtime_origin()
    print(f"   - RUNTIME_ORIGIN: {runtime_origin}")
    
    if runtime_origin != "AWS":
        print(f"   ⚠️  PROBLEMA ENCONTRADO: RUNTIME_ORIGIN={runtime_origin}")
        print(f"      Las notificaciones solo se envían cuando RUNTIME_ORIGIN=AWS")
        print(f"      Esto explica por qué no recibiste la notificación.")
    else:
        print(f"   ✅ RUNTIME_ORIGIN está configurado como AWS")
    print()
    
except Exception as e:
    print(f"   ❌ Error al importar: {e}")
    print()

# 2. Verificar si hay logs de intentos de envío
print("2️⃣ Buscando logs de creación de SL/TP para SOL_USD...")
print()

try:
    from app.database import SessionLocal
    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
    
    db = SessionLocal()
    try:
        # Buscar órdenes SL/TP de SOL_USD creadas recientemente
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        sl_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == 'SOL_USD',
            ExchangeOrder.order_type == 'STOP_LIMIT',
            ExchangeOrder.created_at >= week_ago
        ).order_by(ExchangeOrder.created_at.desc()).limit(5).all()
        
        tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == 'SOL_USD',
            ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
            ExchangeOrder.created_at >= week_ago
        ).order_by(ExchangeOrder.created_at.desc()).limit(5).all()
        
        print(f"   Órdenes SL encontradas: {len(sl_orders)}")
        print(f"   Órdenes TP encontradas: {len(tp_orders)}")
        print()
        
        if tp_orders:
            print("   📋 Últimas órdenes TP de SOL_USD:")
            for tp in tp_orders[:3]:
                print(f"      - Order ID: {tp.exchange_order_id}")
                print(f"        Creada: {tp.created_at}")
                print(f"        Parent Order ID: {tp.parent_order_id or 'N/A'}")
                print()
        
        # Buscar la orden TP ejecutada hoy
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == 'SOL_USD',
            ExchangeOrder.order_type == 'TAKE_PROFIT_LIMIT',
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_update_time >= today_start
        ).first()
        
        if today_tp:
            print("   ✅ Orden TP ejecutada hoy encontrada:")
            print(f"      Order ID: {today_tp.exchange_order_id}")
            print(f"      Parent Order ID: {today_tp.parent_order_id or 'N/A'}")
            print(f"      Creada: {today_tp.created_at}")
            print()
            
            if today_tp.parent_order_id:
                # Buscar orden de compra original
                buy_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == today_tp.parent_order_id
                ).first()
                
                if buy_order:
                    print("   📅 Orden de compra original:")
                    print(f"      Order ID: {buy_order.exchange_order_id}")
                    print(f"      Fecha compra: {buy_order.exchange_update_time or buy_order.created_at}")
                    print()
                    
                    # Calcular cuándo se deberían haber creado las SL/TP
                    if buy_order.exchange_update_time:
                        buy_time = buy_order.exchange_update_time
                        tp_create_time = today_tp.created_at
                        time_diff = (tp_create_time - buy_time).total_seconds() / 60  # minutos
                        
                        print(f"   ⏱️  Tiempo entre compra y creación de TP: {time_diff:.1f} minutos")
                        print()
                        
                        if time_diff > 60:
                            print(f"   ⚠️  La TP se creó {time_diff:.0f} minutos después de la compra")
                            print(f"      Esto puede indicar que se creó manualmente o hubo un retraso")
                        else:
                            print(f"   ✅ La TP se creó poco después de la compra (automático)")
    finally:
        db.close()
        
except Exception as e:
    print(f"   ❌ Error al consultar base de datos: {e}")
    print()

# 3. Resumen y recomendaciones
print("=" * 80)
print("RESUMEN Y RECOMENDACIONES:")
print("=" * 80)
print()

if runtime_origin != "AWS":
    print("❌ PROBLEMA PRINCIPAL: RUNTIME_ORIGIN no está configurado como 'AWS'")
    print()
    print("🔧 SOLUCIÓN:")
    print("   1. Verifica que el servicio backend-aws tenga RUNTIME_ORIGIN=AWS en docker-compose.yml")
    print("   2. O configura la variable de entorno RUNTIME_ORIGIN=AWS")
    print("   3. Reinicia el servicio backend-aws")
    print()
    print("📝 El gatekeeper de Telegram bloquea notificaciones cuando origin != 'AWS'")
    print("   para prevenir envíos accidentales desde entornos de desarrollo.")
else:
    print("✅ RUNTIME_ORIGIN está configurado correctamente")
    print()
    print("🔍 Otras posibles causas:")
    print("   1. Telegram bot token o chat ID no configurados")
    print("   2. Error al enviar la notificación (revisar logs del backend)")
    print("   3. Las órdenes SL/TP se crearon antes de implementar las notificaciones")
    print("   4. Las órdenes se crearon en modo DRY_RUN (simulado)")

print()
print("📋 Para verificar los logs del backend:")
print("   docker compose logs backend-aws | grep -i 'sl/tp\|telegram\|notification'")


