#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from datetime import datetime, timedelta, timezone

db = SessionLocal()
try:
    # Buscar órdenes TP creadas en las últimas 10 minutos
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    
    recent_tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.order_role == 'TAKE_PROFIT',
        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE]),
        ExchangeOrder.created_at >= recent_time
    ).order_by(ExchangeOrder.created_at.desc()).all()
    
    print(f'📊 Órdenes TP creadas en los últimos 10 minutos: {len(recent_tp_orders)}')
    print()
    
    for order in recent_tp_orders:
        print(f'✅ {order.symbol}')
        print(f'   Order ID: {order.exchange_order_id}')
        print(f'   Precio: ${float(order.price or 0):,.6f}')
        print(f'   Cantidad: {float(order.quantity or 0):,.8f}')
        print(f'   Estado: {order.status.value}')
        print(f'   Creada: {order.created_at}')
        print()
finally:
    db.close()





