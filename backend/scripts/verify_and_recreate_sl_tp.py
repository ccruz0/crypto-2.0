#!/usr/bin/env python3
"""Verify remaining positions and recreate SL/TP if needed"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.services.exchange_sync import ExchangeSyncService
from sqlalchemy import or_
from datetime import datetime, timedelta, timezone

db = SessionLocal()
exchange_sync = ExchangeSyncService()

try:
    symbols_to_check = ['DGB_USD', 'ALGO_USDT']
    
    print('📊 VERIFYING REMAINING POSITIONS AND RECREATING SL/TP\n')
    print('=' * 80)
    
    for symbol in symbols_to_check:
        print(f'\n🔍 Analyzing {symbol}...')
        
        # Get all FILLED BUY orders for this symbol
        buy_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
        
        orders_with_positions = []
        
        for buy_order in buy_orders:
            buy_order_id = buy_order.exchange_order_id
            buy_qty = float(getattr(buy_order, 'filled_quantity', None) or getattr(buy_order, 'quantity', None) or 0)
            buy_price = float(getattr(buy_order, 'avg_price', None) or getattr(buy_order, 'filled_price', None) or getattr(buy_order, 'price', None) or 0)
            buy_time = buy_order.exchange_create_time or buy_order.created_at
            
            if not buy_qty or not buy_price:
                continue
            
            # Check SELL orders after this BUY
            sell_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.SELL,
                ExchangeOrder.status == OrderStatusEnum.FILLED,
                ExchangeOrder.exchange_create_time >= buy_time
            ).all()
            
            sold_qty = sum(float(getattr(o, 'filled_quantity', None) or getattr(o, 'quantity', None) or 0) for o in sell_orders)
            remaining_qty = buy_qty - sold_qty
            
            # Check if this order has active SL/TP
            open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
            active_sl_tp = db.query(ExchangeOrder).filter(
                or_(
                    ExchangeOrder.parent_order_id == str(buy_order_id),
                    ExchangeOrder.parent_order_id == buy_order_id
                ),
                or_(
                    ExchangeOrder.order_role.in_(['STOP_LOSS', 'TAKE_PROFIT']),
                    ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT'])
                ),
                ExchangeOrder.status.in_(open_statuses)
            ).count()
            
            if remaining_qty > 0.001:
                has_sl_tp = active_sl_tp > 0
                orders_with_positions.append({
                    'order_id': buy_order_id,
                    'remaining_qty': remaining_qty,
                    'entry_price': buy_price,
                    'has_sl_tp': has_sl_tp,
                    'active_sl_tp_count': active_sl_tp
                })
                
                status = '✅ Has SL/TP' if has_sl_tp else '❌ Missing SL/TP'
                print(f'   Order {buy_order_id}: {remaining_qty:,.6f} remaining - {status} ({active_sl_tp} active)')
        
        # Calculate total remaining position
        total_remaining = sum(o['remaining_qty'] for o in orders_with_positions)
        orders_needing_sl_tp = [o for o in orders_with_positions if not o['has_sl_tp']]
        
        print(f'\n   📊 Summary:')
        print(f'      Total remaining position: {total_remaining:,.6f}')
        print(f'      Orders with positions: {len(orders_with_positions)}')
        print(f'      Orders needing SL/TP: {len(orders_needing_sl_tp)}')
        
        # Recreate SL/TP for orders that need them
        if orders_needing_sl_tp:
            print(f'\n   🔧 Recreating SL/TP for {len(orders_needing_sl_tp)} orders...')
            
            for order_info in orders_needing_sl_tp:
                order_id = order_info['order_id']
                remaining_qty = order_info['remaining_qty']
                entry_price = order_info['entry_price']
                
                print(f'\n      Creating SL/TP for order {order_id}...')
                print(f'         Remaining: {remaining_qty:,.6f}, Entry: ${entry_price:,.6f}')
                
                try:
                    # Use exchange_sync to create SL/TP
                    result = exchange_sync._create_sl_tp_for_filled_order(
                        db=db,
                        symbol=symbol,
                        side='BUY',
                        filled_price=entry_price,
                        filled_qty=remaining_qty,
                        order_id=str(order_id)
                    )
                    
                    if result:
                        print(f'         ✅ SL/TP created successfully')
                    else:
                        print(f'         ⚠️  SL/TP creation returned False (may already exist or failed)')
                
                except Exception as e:
                    print(f'         ❌ Error creating SL/TP: {e}')
                    import traceback
                    traceback.print_exc()
            
            db.commit()
            print(f'\n   ✅ Completed SL/TP recreation for {symbol}')
        else:
            print(f'\n   ✅ All orders already have SL/TP protection')
    
    print('\n' + '=' * 80)
    print('✅ VERIFICATION AND SL/TP RECREATION COMPLETE')
    print('=' * 80)
    
finally:
    db.close()

