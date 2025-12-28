#!/usr/bin/env python3
"""
Script to sync a specific order from exchange and check/create SL/TP
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService
from app.services.brokers.crypto_com_trade import trade_client
from sqlalchemy import and_

def sync_and_check_order(order_id: str):
    """Sync order from exchange and check/create SL/TP"""
    db = SessionLocal()
    
    try:
        print(f"\n🔄 Syncing order {order_id} from exchange...\n")
        
        # First check if order is already in database
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if order:
            print(f"✅ Order found in database\n")
            return check_order_sl_tp(db, order_id)
        
        # If not in database, try to sync order history
        print(f"🔄 Order not in database. Syncing order history from exchange...")
        try:
            exchange_sync = ExchangeSyncService()
            exchange_sync.sync_order_history(db, page_size=200, max_pages=2)
            
            # Check again if order is now in database
            order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order_id
            ).first()
            
            if order:
                print(f"✅ Order synced to database\n")
                return check_order_sl_tp(db, order_id)
            else:
                print(f"⚠️  Order not found in database after sync")
                print(f"   Possible reasons:")
                print(f"   1. Order ID might be incorrect")
                print(f"   2. Order might be in a different database/environment")
                print(f"   3. Order might be too old (sync only gets recent orders)")
                print(f"\n💡 The order will be synced automatically when exchange_sync runs.")
                return 1
                
        except Exception as e:
            print(f"❌ Error syncing order history: {e}")
            import traceback
            traceback.print_exc()
            return 1
        
    finally:
        db.close()

def check_order_sl_tp(db, order_id: str):
    """Check if order has SL/TP and create if missing"""
    order = db.query(ExchangeOrder).filter(
        ExchangeOrder.exchange_order_id == order_id
    ).first()
    
    if not order:
        print(f"❌ Order {order_id} not found in database")
        return 1
    
    symbol = order.symbol
    side = order.side.value if hasattr(order.side, 'value') else str(order.side)
    status = order.status.value if hasattr(order.status, 'value') else str(order.status)
    
    print(f"📊 Order Details:")
    print(f"   Order ID: {order.exchange_order_id}")
    print(f"   Symbol: {symbol}")
    print(f"   Side: {side} | Status: {status}")
    print()
    
    # Check for SL/TP orders
    sl_orders = db.query(ExchangeOrder).filter(
        and_(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'STOP_LOSS',
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED,
                OrderStatusEnum.FILLED
            ])
        )
    ).all()
    
    tp_orders = db.query(ExchangeOrder).filter(
        and_(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'TAKE_PROFIT',
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED,
                OrderStatusEnum.FILLED
            ])
        )
    ).all()
    
    has_sl = len(sl_orders) > 0
    has_tp = len(tp_orders) > 0
    
    print(f"   🛑 Stop Loss: {'✅' if has_sl else '❌ MISSING'}")
    if has_sl:
        for sl in sl_orders:
            print(f"      - ID: {sl.exchange_order_id}, Status: {sl.status.value}")
    
    print(f"   🚀 Take Profit: {'✅' if has_tp else '❌ MISSING'}")
    if has_tp:
        for tp in tp_orders:
            print(f"      - ID: {tp.exchange_order_id}, Status: {tp.status.value}")
    
    print()
    
    # If order is FILLED and missing SL/TP, create them
    if status == "FILLED" and (not has_sl or not has_tp):
        print(f"⚠️  Order is FILLED but missing SL/TP. Creating them now...\n")
        
        filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
        filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
        
        if not filled_price or filled_qty <= 0:
            print(f"❌ Cannot create SL/TP: invalid price ({filled_price}) or quantity ({filled_qty})")
            return 1
        
        try:
            exchange_sync = ExchangeSyncService()
            exchange_sync._create_sl_tp_for_filled_order(
                db=db,
                symbol=symbol,
                side=side,
                filled_price=filled_price,
                filled_qty=filled_qty,
                order_id=order_id,
                source="manual"
            )
            print(f"✅ SL/TP creation initiated. Checking again...\n")
            
            # Re-check SL/TP
            db.expire_all()
            sl_orders = db.query(ExchangeOrder).filter(
                and_(
                    ExchangeOrder.parent_order_id == order_id,
                    ExchangeOrder.order_role == 'STOP_LOSS'
                )
            ).all()
            tp_orders = db.query(ExchangeOrder).filter(
                and_(
                    ExchangeOrder.parent_order_id == order_id,
                    ExchangeOrder.order_role == 'TAKE_PROFIT'
                )
            ).all()
            
            has_sl = len(sl_orders) > 0
            has_tp = len(tp_orders) > 0
            
            if has_sl and has_tp:
                print(f"✅ Successfully created SL/TP orders!")
                for sl in sl_orders:
                    print(f"   🛑 SL: {sl.exchange_order_id}")
                for tp in tp_orders:
                    print(f"   🚀 TP: {tp.exchange_order_id}")
                return 0
            else:
                print(f"⚠️  SL/TP creation may have failed or is still processing")
                if not has_sl:
                    print(f"   Missing: SL")
                if not has_tp:
                    print(f"   Missing: TP")
                return 1
                
        except Exception as e:
            print(f"❌ Error creating SL/TP: {e}")
            import traceback
            traceback.print_exc()
            return 1
    elif status != "FILLED":
        print(f"ℹ️  Order status is {status}. SL/TP will be created automatically when order becomes FILLED.")
        return 0
    else:
        print(f"✅ Order has both SL and TP")
        return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sync_and_check_order.py <order_id>")
        print("Example: python3 sync_and_check_order.py 5755600481538037740")
        sys.exit(1)
    
    order_id = sys.argv[1]
    exit(sync_and_check_order(order_id))

