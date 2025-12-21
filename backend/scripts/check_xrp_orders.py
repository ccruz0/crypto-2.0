#!/usr/bin/env python3
"""
Script to check XRP orders in the database
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from sqlalchemy import or_

def check_xrp_orders():
    """Check all XRP orders in the database"""
    db = SessionLocal()
    try:
        # Check for XRP orders with different symbol variants
        symbol_variants = ['XRP', 'XRP_USDT', 'XRP_USD']
        
        print("=" * 80)
        print("Checking XRP Orders in Database")
        print("=" * 80)
        
        all_orders = []
        for variant in symbol_variants:
            orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == variant
            ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
            
            if orders:
                print(f"\n📊 Found {len(orders)} orders for {variant}:")
                for order in orders[:10]:  # Show first 10
                    status = order.status.value if hasattr(order.status, 'value') else str(order.status)
                    side = order.side.value if hasattr(order.side, 'value') else str(order.side)
                    price = order.avg_price or order.price or 0
                    qty = order.cumulative_quantity or order.quantity or 0
                    
                    print(f"  - Order ID: {order.exchange_order_id[:20]}...")
                    print(f"    Side: {side}, Status: {status}")
                    print(f"    Price: ${price:.6f}, Qty: {qty:.8f}")
                    print(f"    Created: {order.exchange_create_time}")
                    print()
                
                all_orders.extend(orders)
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        if not all_orders:
            print("❌ No XRP orders found in database")
            print("\nThis explains why Purchase Value shows $0.00:")
            print("  - The system needs FILLED or PARTIALLY_FILLED BUY orders to calculate purchase value")
            print("  - Without these orders, it cannot determine the cost basis")
            return
        
        # Count by status
        status_counts = {}
        side_counts = {}
        filled_buy_orders = []
        
        for order in all_orders:
            status = order.status.value if hasattr(order.status, 'value') else str(order.status)
            side = order.side.value if hasattr(order.side, 'value') else str(order.side)
            
            status_counts[status] = status_counts.get(status, 0) + 1
            side_counts[side] = side_counts.get(side, 0) + 1
            
            # Check for FILLED or PARTIALLY_FILLED BUY orders
            if side == 'BUY' and status in ['FILLED', 'PARTIALLY_FILLED']:
                filled_buy_orders.append(order)
        
        print(f"Total orders found: {len(all_orders)}")
        print(f"\nBy Status:")
        for status, count in sorted(status_counts.items()):
            print(f"  - {status}: {count}")
        
        print(f"\nBy Side:")
        for side, count in sorted(side_counts.items()):
            print(f"  - {side}: {count}")
        
        print(f"\n✅ FILLED/PARTIALLY_FILLED BUY orders: {len(filled_buy_orders)}")
        
        if filled_buy_orders:
            print("\nThese orders can be used to calculate purchase value:")
            total_value = 0
            total_qty = 0
            for order in filled_buy_orders:
                price = order.avg_price or order.price or 0
                qty = order.cumulative_quantity or order.quantity or 0
                value = price * qty
                total_value += value
                total_qty += qty
                print(f"  - {order.exchange_order_id[:20]}...: {qty:.8f} @ ${price:.6f} = ${value:.2f}")
            
            if total_qty > 0:
                avg_price = total_value / total_qty
                print(f"\n  Weighted Average Price: ${avg_price:.6f}")
                print(f"  Total Quantity: {total_qty:.8f}")
                print(f"  Total Value: ${total_value:.2f}")
        else:
            print("\n❌ No FILLED or PARTIALLY_FILLED BUY orders found!")
            print("   This is why Purchase Value shows $0.00")
            print("\n   Solutions:")
            print("   1. Import order history from Crypto.com")
            print("   2. Manually enter purchase price (feature to be added)")
        
    finally:
        db.close()

if __name__ == "__main__":
    check_xrp_orders()







