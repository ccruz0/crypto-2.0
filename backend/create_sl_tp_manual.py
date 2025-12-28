#!/usr/bin/env python3
"""
Script to manually create SL/TP orders for a filled order
Usage: python3 create_sl_tp_manual.py <order_id> [--force]
"""
import sys
import argparse
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService

def create_sl_tp_for_order(order_id: str, force: bool = False):
    """Manually create SL/TP for a filled order"""
    db = SessionLocal()
    
    try:
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            print(f"❌ Order {order_id} not found in database")
            return False
        
        print(f"📊 Order Details:")
        print(f"   ID: {order.exchange_order_id}")
        print(f"   Symbol: {order.symbol}")
        print(f"   Side: {order.side.value}")
        print(f"   Status: {order.status.value}")
        print(f"   Price: {order.price or order.avg_price}")
        print(f"   Avg Price: {order.avg_price}")
        print(f"   Quantity: {order.quantity}")
        print()
        
        if order.status != OrderStatusEnum.FILLED:
            print(f"❌ Order is not FILLED (status: {order.status.value})")
            print("   SL/TP can only be created for FILLED orders")
            return False
        
        # Check if SL/TP already exist
        sl_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'STOP_LOSS'
        ).all()
        
        tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'TAKE_PROFIT'
        ).all()
        
        if sl_orders or tp_orders:
            print(f"⚠️  SL/TP orders already exist:")
            if sl_orders:
                for s in sl_orders:
                    print(f"   SL: {s.exchange_order_id} - {s.status.value}")
            if tp_orders:
                for t in tp_orders:
                    print(f"   TP: {t.exchange_order_id} - {t.status.value}")
            
            if not force:
                print("\n   Use --force to create anyway (will skip if active orders exist)")
                return False
        
        # Get filled price and quantity
        filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
        filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
        
        if filled_price <= 0 or filled_qty <= 0:
            print(f"❌ Invalid order data: price={filled_price}, qty={filled_qty}")
            return False
        
        print(f"🔄 Creating SL/TP orders...")
        print(f"   Entry Price: ${filled_price:.4f}")
        print(f"   Quantity: {filled_qty:.6f}")
        print(f"   Side: {order.side.value}")
        print()
        
        # Create SL/TP using exchange_sync service
        exchange_sync = ExchangeSyncService()
        result = exchange_sync._create_sl_tp_for_filled_order(
            db=db,
            symbol=order.symbol,
            side=order.side.value,
            filled_price=filled_price,
            filled_qty=filled_qty,
            order_id=order.exchange_order_id,
            force=force,
            source="manual"
        )
        
        # Check if SL/TP were created
        db.refresh(order)
        sl_new = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'STOP_LOSS'
        ).all()
        
        tp_new = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role == 'TAKE_PROFIT'
        ).all()
        
        print(f"✅ SL/TP Creation Complete:")
        print(f"   🛑 Stop Loss: {len(sl_new)} order(s)")
        print(f"   🚀 Take Profit: {len(tp_new)} order(s)")
        
        if sl_new:
            for s in sl_new:
                print(f"      SL: {s.exchange_order_id} - {s.status.value} - ${s.price:.4f}")
        if tp_new:
            for t in tp_new:
                print(f"      TP: {t.exchange_order_id} - {t.status.value} - ${t.price:.4f}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating SL/TP: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manually create SL/TP for a filled order")
    parser.add_argument("order_id", help="Order ID to create SL/TP for")
    parser.add_argument("--force", action="store_true", help="Force creation even if SL/TP already exist")
    
    args = parser.parse_args()
    
    success = create_sl_tp_for_order(args.order_id, force=args.force)
    sys.exit(0 if success else 1)

