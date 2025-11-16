#!/usr/bin/env python3
"""Create SL/TP orders for the last SOL_USDT order that doesn't have SL/TP"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.services.exchange_sync import exchange_sync_service

def create_sl_tp_for_last_sol_order():
    """Create SL/TP for the last SOL_USDT order without SL/TP"""
    db = SessionLocal()
    try:
        symbol = "SOL_USDT"
        
        # Find the last filled BUY order for SOL_USDT
        # Look for MARKET or LIMIT orders that are FILLED
        last_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"])
        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not last_order:
            print(f"❌ No filled BUY orders found for {symbol}")
            return
        
        print(f"✅ Found last order: {last_order.exchange_order_id}")
        print(f"   Type: {last_order.order_type}")
        print(f"   Side: {last_order.side.value}")
        print(f"   Status: {last_order.status.value}")
        print(f"   Price: ${last_order.avg_price or last_order.price}")
        print(f"   Quantity: {last_order.cumulative_quantity or last_order.quantity}")
        
        # Check if this order already has SL/TP orders
        existing_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == last_order.exchange_order_id,
            ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if existing_sl_tp:
            print(f"\n⚠️ Order {last_order.exchange_order_id} already has {len(existing_sl_tp)} SL/TP order(s):")
            for order in existing_sl_tp:
                print(f"   - {order.order_type} (ID: {order.exchange_order_id}, Status: {order.status.value})")
            return
        
        print(f"\n✅ No SL/TP orders found for order {last_order.exchange_order_id}")
        print(f"   Creating SL/TP orders...")
        
        # Get filled price and quantity
        filled_price = float(last_order.avg_price) if last_order.avg_price else float(last_order.price) if last_order.price else None
        filled_qty = float(last_order.cumulative_quantity) if last_order.cumulative_quantity else float(last_order.quantity) if last_order.quantity else None
        
        if not filled_price or not filled_qty:
            print(f"❌ Cannot create SL/TP: invalid price ({filled_price}) or quantity ({filled_qty})")
            return
        
        # Use the same logic as exchange_sync._create_sl_tp_for_filled_order
        exchange_sync_service._create_sl_tp_for_filled_order(
            db=db,
            symbol=symbol,
            side=last_order.side.value,  # "BUY"
            filled_price=filled_price,
            filled_qty=filled_qty,
            order_id=last_order.exchange_order_id
        )
        
        print(f"\n✅ SL/TP orders created successfully for order {last_order.exchange_order_id}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_sl_tp_for_last_sol_order()

