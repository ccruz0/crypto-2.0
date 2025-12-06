#!/usr/bin/env python3
"""Check BONK orders for positions without SL/TP"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from sqlalchemy import and_, or_

db = SessionLocal()
try:
    # Buscar órdenes BUY ejecutadas (FILLED) para BONK
    bonk_buy_orders = db.query(ExchangeOrder).filter(
        and_(
            ExchangeOrder.symbol.like('BONK%'),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        )
    ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
    
    print(f'📊 Órdenes BUY ejecutadas (FILLED) para BONK: {len(bonk_buy_orders)}')
    for order in bonk_buy_orders:
        qty = getattr(order, 'filled_quantity', None) or getattr(order, 'quantity', None) or 0
        price = getattr(order, 'filled_price', None) or getattr(order, 'price', None) or 0
        created = getattr(order, 'exchange_create_time', None) or getattr(order, 'created_at', None)
        print(f'  - Order ID: {order.exchange_order_id}')
        print(f'    Symbol: {order.symbol}')
        print(f'    Quantity: {qty}')
        print(f'    Price: {price}')
        print(f'    Status: {order.status}')
        print(f'    Created: {created}')
        print()
    
    # Buscar órdenes SL/TP abiertas para BONK
    bonk_sl_tp_orders = db.query(ExchangeOrder).filter(
        and_(
            ExchangeOrder.symbol.like('BONK%'),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
            or_(
                ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']),
                ExchangeOrder.order_role.in_(['STOP_LOSS', 'TAKE_PROFIT'])
            )
        )
    ).all()
    
    print(f'📊 Órdenes SL/TP abiertas para BONK: {len(bonk_sl_tp_orders)}')
    for order in bonk_sl_tp_orders:
        print(f'  - Order ID: {order.exchange_order_id}')
        print(f'    Symbol: {order.symbol}')
        print(f'    Type: {order.order_type}')
        print(f'    Role: {order.order_role}')
        print(f'    Side: {order.side}')
        print(f'    Quantity: {order.quantity}')
        print(f'    Status: {order.status}')
        print()
    
    # Verificar si hay órdenes BUY FILLED sin SL/TP asociadas
    bonk_buy_without_sl_tp = []
    for buy_order in bonk_buy_orders:
        # Buscar SL/TP asociadas a esta orden BUY
        sl_tp_found = False
        buy_qty = float(getattr(buy_order, 'filled_quantity', None) or getattr(buy_order, 'quantity', None) or 0)
        
        for sl_tp_order in bonk_sl_tp_orders:
            # Verificar si la SL/TP está relacionada con esta orden BUY por cantidad similar
            sl_tp_qty = float(sl_tp_order.quantity or 0)
            if buy_qty > 0 and sl_tp_qty > 0:
                qty_diff = abs(buy_qty - sl_tp_qty) / buy_qty
                if qty_diff <= 0.3:  # 30% tolerance
                    sl_tp_found = True
                    break
        
        if not sl_tp_found:
            bonk_buy_without_sl_tp.append(buy_order)
    
    print(f'⚠️ Órdenes BUY ejecutadas SIN SL/TP: {len(bonk_buy_without_sl_tp)}')
    if bonk_buy_without_sl_tp:
        for order in bonk_buy_without_sl_tp:
            qty = getattr(order, 'filled_quantity', None) or getattr(order, 'quantity', None) or 0
            price = getattr(order, 'filled_price', None) or getattr(order, 'price', None) or 0
            created = getattr(order, 'exchange_create_time', None) or getattr(order, 'created_at', None)
            print(f'  - Order ID: {order.exchange_order_id}')
            print(f'    Symbol: {order.symbol}')
            print(f'    Quantity: {qty}')
            print(f'    Price: {price}')
            print(f'    Created: {created}')
            print()
    else:
        print('  ✅ Todas las órdenes BUY tienen SL/TP asociadas')
finally:
    db.close()

