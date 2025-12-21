#!/usr/bin/env python3
"""
Script to check recent LDO_USD orders to find the executed order.
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add the backend directory to the path so we can import app modules
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum

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

def check_recent_ldo_orders():
    """Check recent LDO orders"""
    db = SessionLocal()
    try:
        # Look for orders executed in the last 24 hours
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)
        
        print(f"🔍 Checking LDO_USD orders executed since {format_datetime(yesterday)}")
        print(f"   Looking for order ID: 5755600480766390866\n")
        
        # Check both LDO_USD and LDO_USDT (in case symbol format differs)
        orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol.in_(["LDO_USD", "LDO_USDT"]),
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.side == OrderSideEnum.SELL
        ).order_by(ExchangeOrder.exchange_update_time.desc()).limit(20).all()
        
        if not orders:
            print("❌ No recent SELL orders found for LDO_USD or LDO_USDT")
            
            # Try without status filter
            all_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol.in_(["LDO_USD", "LDO_USDT"]),
                ExchangeOrder.side == OrderSideEnum.SELL
            ).order_by(ExchangeOrder.exchange_update_time.desc()).limit(10).all()
            
            if all_orders:
                print(f"\n📊 Found {len(all_orders)} SELL orders (any status):\n")
                for order in all_orders:
                    print(f"  Order ID: {order.exchange_order_id}")
                    print(f"  Status: {order.status.value if hasattr(order.status, 'value') else order.status}")
                    print(f"  Price: ${format_decimal(order.price)}")
                    print(f"  Quantity: {format_decimal(order.quantity)}")
                    print(f"  Updated: {format_datetime(order.exchange_update_time)}")
                    print()
            return
        
        print(f"📊 Found {len(orders)} recent SELL orders:\n")
        print(f"{'='*80}\n")
        
        target_order_id = "5755600480766390866"
        found_target = False
        
        for idx, order in enumerate(orders, 1):
            is_target = order.exchange_order_id == target_order_id
            if is_target:
                found_target = True
                print(f"🎯 TARGET ORDER FOUND!")
                print(f"{'='*80}\n")
            
            print(f"[{idx}] Order Details:")
            print(f"    🆔 Order ID: {order.exchange_order_id}")
            print(f"    📊 Symbol: {order.symbol}")
            print(f"    📈 Side: {order.side.value if hasattr(order.side, 'value') else order.side}")
            print(f"    💰 Price: ${format_decimal(order.price)}")
            print(f"    ✅ Avg Price: ${format_decimal(order.avg_price)}")
            print(f"    📦 Quantity: {format_decimal(order.quantity)}")
            print(f"    📋 Type: {order.order_type or 'N/A'}")
            print(f"    🏷️ Order Role: {order.order_role or 'N/A'}")
            print(f"    📅 Executed: {format_datetime(order.exchange_update_time)}")
            print(f"    🔗 Parent Order ID: {order.parent_order_id or 'N/A'}")
            print(f"    🔗 OCO Group ID: {order.oco_group_id or 'N/A'}")
            
            if order.parent_order_id:
                parent = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order.parent_order_id
                ).first()
                if parent:
                    print(f"    👆 Parent: {parent.side.value if hasattr(parent.side, 'value') else parent.side} {parent.order_type} @ ${format_decimal(parent.avg_price or parent.price)}")
            
            print()
        
        if not found_target:
            print(f"\n⚠️ Target order ID {target_order_id} not found in recent orders")
            print(f"   This could mean:")
            print(f"   1. The order hasn't been synced to the database yet")
            print(f"   2. The order is older than the records shown")
            print(f"   3. The database connection isn't working properly")
        
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"❌ Error querying database: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_recent_ldo_orders()



















