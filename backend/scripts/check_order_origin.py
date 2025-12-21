#!/usr/bin/env python3
"""
Script to check the origin of an order by querying the database.
Shows order details including parent_order_id, order_role, and related orders.
"""
import sys
import os
from pathlib import Path

# Add the backend directory to the path so we can import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from datetime import datetime

def format_decimal(value):
    """Format decimal values for display"""
    if value is None:
        return "N/A"
    return f"{float(value):,.8f}"

def format_datetime(dt):
    """Format datetime for display"""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def check_order_origin(order_id: str):
    """Check the origin of an order by querying the database"""
    db = SessionLocal()
    try:
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            print(f"❌ Order {order_id} not found in database")
            return
        
        print(f"\n{'='*80}")
        print(f"📊 ORDER DETAILS")
        print(f"{'='*80}\n")
        
        print(f"🆔 Order ID: {order.exchange_order_id}")
        print(f"📊 Symbol: {order.symbol}")
        print(f"📈 Side: {order.side.value if hasattr(order.side, 'value') else order.side}")
        print(f"💰 Price: ${format_decimal(order.price)}")
        print(f"📦 Quantity: {format_decimal(order.quantity)}")
        print(f"✅ Avg Price: ${format_decimal(order.avg_price)}")
        print(f"📋 Type: {order.order_type or 'N/A'}")
        print(f"📊 Status: {order.status.value if hasattr(order.status, 'value') else order.status}")
        print(f"🏷️ Order Role: {order.order_role or 'N/A'}")
        print(f"📅 Created At (DB): {format_datetime(order.created_at)}")
        print(f"📅 Exchange Create Time: {format_datetime(order.exchange_create_time)}")
        print(f"📅 Exchange Update Time: {format_datetime(order.exchange_update_time)}")
        print(f"📅 Updated At (DB): {format_datetime(order.updated_at)}")
        
        # Check if this is a SL/TP order
        if order.parent_order_id:
            print(f"\n{'='*80}")
            print(f"🔗 PARENT ORDER (This order was created as SL/TP for)")
            print(f"{'='*80}\n")
            
            parent = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order.parent_order_id
            ).first()
            
            if parent:
                print(f"🆔 Parent Order ID: {parent.exchange_order_id}")
                print(f"📊 Symbol: {parent.symbol}")
                print(f"📈 Side: {parent.side.value if hasattr(parent.side, 'value') else parent.side}")
                print(f"💰 Price: ${format_decimal(parent.price)}")
                print(f"✅ Avg Price: ${format_decimal(parent.avg_price)}")
                print(f"📋 Type: {parent.order_type or 'N/A'}")
                print(f"📊 Status: {parent.status.value if hasattr(parent.status, 'value') else parent.status}")
                print(f"📅 Created: {format_datetime(parent.exchange_create_time)}")
                print(f"📅 Executed: {format_datetime(parent.exchange_update_time)}")
                
                # Determine what this order is
                if order.order_role == "STOP_LOSS":
                    print(f"\n✅ This is a STOP LOSS order for the parent BUY order above")
                elif order.order_role == "TAKE_PROFIT":
                    print(f"\n✅ This is a TAKE PROFIT order for the parent BUY order above")
                
            else:
                print(f"⚠️ Parent order {order.parent_order_id} not found in database")
        
        # Check for OCO group (related SL/TP orders)
        if order.oco_group_id:
            print(f"\n{'='*80}")
            print(f"🔗 RELATED ORDERS (Same OCO Group: {order.oco_group_id})")
            print(f"{'='*80}\n")
            
            related = db.query(ExchangeOrder).filter(
                ExchangeOrder.oco_group_id == order.oco_group_id,
                ExchangeOrder.exchange_order_id != order_id
            ).all()
            
            if related:
                for idx, related_order in enumerate(related, 1):
                    print(f"\n[{idx}] Related Order:")
                    print(f"    🆔 Order ID: {related_order.exchange_order_id}")
                    print(f"    🏷️ Role: {related_order.order_role or 'N/A'}")
                    print(f"    📋 Type: {related_order.order_type or 'N/A'}")
                    print(f"    💰 Price: ${format_decimal(related_order.price)}")
                    print(f"    📊 Status: {related_order.status.value if hasattr(related_order.status, 'value') else related_order.status}")
            else:
                print("No other orders found in this OCO group")
        
        # Check if this order has children (SL/TP orders created for it)
        children = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id
        ).all()
        
        if children:
            print(f"\n{'='*80}")
            print(f"👶 CHILD ORDERS (SL/TP orders created for this order)")
            print(f"{'='*80}\n")
            
            for idx, child in enumerate(children, 1):
                print(f"\n[{idx}] Child Order:")
                print(f"    🆔 Order ID: {child.exchange_order_id}")
                print(f"    🏷️ Role: {child.order_role or 'N/A'}")
                print(f"    📋 Type: {child.order_type or 'N/A'}")
                print(f"    💰 Price: ${format_decimal(child.price)}")
                print(f"    📊 Status: {child.status.value if hasattr(child.status, 'value') else child.status}")
        
        # Summary
        print(f"\n{'='*80}")
        print(f"📝 ORDER ORIGIN SUMMARY")
        print(f"{'='*80}\n")
        
        if order.parent_order_id:
            print(f"🔗 This is a SL/TP order (role: {order.order_role or 'unknown'})")
            print(f"   Created automatically for parent order: {order.parent_order_id}")
            if order.order_role == "TAKE_PROFIT":
                print(f"   ✅ This is a TAKE PROFIT order - executed when price reached target")
            elif order.order_role == "STOP_LOSS":
                print(f"   🛑 This is a STOP LOSS order - executed when price hit stop level")
        else:
            print(f"📌 This appears to be a MANUAL or PRIMARY order")
            print(f"   No parent_order_id found - it was created independently")
            if order.order_type == "LIMIT" and order.side.value == "SELL":
                print(f"   This SELL LIMIT order could have been:")
                print(f"   - Manually placed via the dashboard")
                print(f"   - Created to close a position")
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        print(f"❌ Error querying database: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_order_origin.py <order_id>")
        print("\nExample:")
        print("  python check_order_origin.py 5755600480766390866")
        sys.exit(1)
    
    order_id = sys.argv[1]
    check_order_origin(order_id)



















