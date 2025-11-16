#!/usr/bin/env python3
"""Check SOL_USDT orders and their SL/TP status"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum

def check_sol_orders():
    db = SessionLocal()
    try:
        symbol = "SOL_USDT"
        
        # Get all filled BUY orders for SOL_USDT
        orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"])
        ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
        
        print(f"Found {len(orders)} filled BUY orders for {symbol}:\n")
        
        for order in orders:
            print(f"Order ID: {order.exchange_order_id}")
            print(f"  Type: {order.order_type}")
            print(f"  Status: {order.status.value}")
            print(f"  Price: ${order.avg_price or order.price}")
            print(f"  Quantity: {order.cumulative_quantity or order.quantity}")
            
            # Check for SL/TP orders
            sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order.exchange_order_id,
                ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]),
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            if sl_tp:
                print(f"  ✅ Has {len(sl_tp)} SL/TP order(s):")
                for o in sl_tp:
                    print(f"     - {o.order_type} (ID: {o.exchange_order_id}, Status: {o.status.value})")
            else:
                print(f"  ❌ No SL/TP orders")
            print()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_sol_orders()

