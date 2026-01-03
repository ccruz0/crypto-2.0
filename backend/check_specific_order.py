#!/usr/bin/env python3
"""
Script to check a specific order and its SL/TP status
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from sqlalchemy import and_

def check_specific_order(order_id: str):
    """Check a specific order and its SL/TP status"""
    db = SessionLocal()
    
    try:
        print(f"\n🔍 Checking order: {order_id}\n")
        print("=" * 80)
        
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            print(f"❌ Order {order_id} not found in database")
            print("\n💡 Possible reasons:")
            print("   1. Order was just created and hasn't been synced to database yet")
            print("   2. Order is in a different database/environment")
            print("   3. Order ID format might be different")
            print("\n📋 To check orders in the exchange, you can:")
            print("   - Wait for exchange_sync to run (usually every few minutes)")
            print("   - Manually trigger sync via API endpoint")
            print("   - Check the exchange directly via Crypto.com API")
            return 1
        
        # Order found - display details
        symbol = order.symbol
        side = order.side.value if hasattr(order.side, 'value') else str(order.side)
        order_type = order.order_type
        status = order.status.value if hasattr(order.status, 'value') else str(order.status)
        price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
        quantity = float(order.quantity) if order.quantity else 0
        created_at = order.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if order.created_at else "N/A"
        exchange_create_time = order.exchange_create_time.strftime("%Y-%m-%d %H:%M:%S UTC") if order.exchange_create_time else "N/A"
        
        side_emoji = "🟢" if side == "BUY" else "🔴"
        print(f"{side_emoji} Order Details:")
        print(f"   Order ID: {order.exchange_order_id}")
        print(f"   Symbol: {symbol}")
        print(f"   Side: {side} | Type: {order_type} | Status: {status}")
        print(f"   Price: ${price:.4f} | Quantity: {quantity:.8f}")
        print(f"   Created (local): {created_at}")
        print(f"   Created (exchange): {exchange_create_time}")
        print(f"   Parent Order ID: {order.parent_order_id or 'None (this is a main order)'}")
        print(f"   Order Role: {order.order_role or 'None (main order)'}")
        print()
        
        # Check if this is a main order or SL/TP order
        if order.parent_order_id:
            print("ℹ️  This is a SL/TP order (has parent_order_id)")
            parent_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order.parent_order_id
            ).first()
            if parent_order:
                print(f"   Parent Order: {parent_order.exchange_order_id} ({parent_order.symbol} {parent_order.side.value})")
        else:
            print("ℹ️  This is a main order. Checking for SL/TP orders...\n")
            
            # Check for SL orders
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
            
            # Check for TP orders
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
            
            sl_status = "✅" if has_sl else "❌ MISSING"
            tp_status = "✅" if has_tp else "❌ MISSING"
            
            print(f"   🛑 Stop Loss: {sl_status}")
            if has_sl:
                for sl in sl_orders:
                    sl_price = float(sl.price) if sl.price else 0
                    sl_status_val = sl.status.value if hasattr(sl.status, 'value') else str(sl.status)
                    print(f"      - ID: {sl.exchange_order_id}, Price: ${sl_price:.4f}, Status: {sl_status_val}")
            else:
                print(f"      ⚠️  No SL order found for this order")
            
            print(f"   🚀 Take Profit: {tp_status}")
            if has_tp:
                for tp in tp_orders:
                    tp_price = float(tp.price) if tp.price else 0
                    tp_status_val = tp.status.value if hasattr(tp.status, 'value') else str(tp.status)
                    print(f"      - ID: {tp.exchange_order_id}, Price: ${tp_price:.4f}, Status: {tp_status_val}")
            else:
                print(f"      ⚠️  No TP order found for this order")
            
            print()
            
            if not has_sl or not has_tp:
                print("⚠️  RECOMMENDATION:")
                missing = []
                if not has_sl:
                    missing.append("SL")
                if not has_tp:
                    missing.append("TP")
                print(f"   This order is missing {', '.join(missing)} orders.")
                print(f"   You can create them manually using:")
                print(f"   POST /api/orders/create-sl-tp/{order_id}")
                print(f"   Or wait for exchange_sync to create them automatically if the order is FILLED.")
        
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error checking order: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check_specific_order.py <order_id>")
        print("Example: python3 check_specific_order.py 5755600481538037740")
        sys.exit(1)
    
    order_id = sys.argv[1]
    exit(check_specific_order(order_id))





