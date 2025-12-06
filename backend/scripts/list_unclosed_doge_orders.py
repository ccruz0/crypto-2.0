#!/usr/bin/env python3
"""
List all DOGE BUY orders that were filled but not fully sold
Uses FIFO (First In First Out) to match SELL orders to BUY orders
Usage: python list_unclosed_doge_orders.py
"""
import sys
import os
from datetime import datetime
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from sqlalchemy import func, or_

def list_unclosed_doge_orders():
    """List all DOGE BUY orders that were filled but not fully sold using FIFO matching"""
    db = SessionLocal()
    
    try:
        # Find all filled BUY orders for DOGE (oldest first for FIFO)
        doge_symbols = ['DOGE_USDT', 'DOGE_USD', 'DOGE/USDT', 'DOGE/USD']
        
        buy_orders = db.query(ExchangeOrder).filter(
            or_(*[ExchangeOrder.symbol == symbol for symbol in doge_symbols]),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.created_at.asc()).all()  # Oldest first for FIFO
        
        # Find all filled SELL orders for DOGE (oldest first for FIFO)
        sell_orders = db.query(ExchangeOrder).filter(
            or_(*[ExchangeOrder.symbol == symbol for symbol in doge_symbols]),
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.created_at.asc()).all()  # Oldest first for FIFO
        
        print(f"📊 Found {len(buy_orders)} filled BUY orders and {len(sell_orders)} filled SELL orders for DOGE\n")
        print("=" * 100)
        
        # FIFO matching: assign SELL orders to BUY orders starting from oldest
        sell_index = 0
        total_bought = Decimal('0')
        total_sold = Decimal('0')
        unclosed_orders = []
        
        for buy_order in buy_orders:
            symbol = buy_order.symbol
            order_id = buy_order.exchange_order_id
            buy_qty = Decimal(str(buy_order.cumulative_quantity or buy_order.quantity or 0))
            buy_price = float(buy_order.avg_price or buy_order.price or 0)
            buy_date = buy_order.created_at or buy_order.exchange_create_time
            
            total_bought += buy_qty
            
            # FIFO: Match SELL orders to this BUY order starting from sell_index
            remaining_buy_qty = buy_qty
            matched_sells = []
            
            while sell_index < len(sell_orders) and remaining_buy_qty > 0:
                sell_order = sell_orders[sell_index]
                sell_qty = Decimal(str(sell_order.cumulative_quantity or sell_order.quantity or 0))
                sell_date = sell_order.created_at or sell_order.exchange_create_time
                
                # Only match SELL orders that happened AFTER this BUY order
                if sell_date >= buy_date:
                    if sell_qty <= remaining_buy_qty:
                        # This SELL order fully covers remaining BUY quantity
                        matched_sells.append({
                            'order_id': sell_order.exchange_order_id,
                            'quantity': sell_qty,
                            'price': float(sell_order.avg_price or sell_order.price or 0),
                            'date': sell_date
                        })
                        remaining_buy_qty -= sell_qty
                        sell_index += 1  # Move to next SELL order
                    else:
                        # This SELL order partially covers remaining BUY quantity
                        matched_qty = remaining_buy_qty
                        matched_sells.append({
                            'order_id': sell_order.exchange_order_id,
                            'quantity': matched_qty,
                            'price': float(sell_order.avg_price or sell_order.price or 0),
                            'date': sell_date,
                            'partial': True,
                            'total_sell_qty': sell_qty
                        })
                        # Update the SELL order's remaining quantity (for next BUY order)
                        # We'll track this by reducing sell_qty in the list
                        remaining_buy_qty = Decimal('0')
                        # Don't increment sell_index - this SELL order still has remaining quantity
                        break
                else:
                    # SELL order happened before this BUY - skip it (shouldn't happen with proper ordering)
                    sell_index += 1
            
            sold_qty = buy_qty - remaining_buy_qty
            total_sold += sold_qty
            
            # Calculate values
            buy_value = float(buy_qty) * buy_price
            remaining_value = float(remaining_buy_qty) * buy_price if remaining_buy_qty > 0 else 0
            
            # Show order details
            print(f"\n🟢 BUY Order: {order_id}")
            print(f"   Symbol: {symbol}")
            print(f"   Date: {buy_date}")
            print(f"   Quantity: {buy_qty:,.2f} DOGE")
            print(f"   Price: ${buy_price:,.4f}")
            print(f"   Total Value: ${buy_value:,.2f}")
            
            if matched_sells:
                print(f"   📉 Matched SELL Orders ({len(matched_sells)}):")
                for sell in matched_sells:
                    partial_note = f" (partial, total: {sell.get('total_sell_qty', 0):,.2f})" if sell.get('partial') else ""
                    print(f"      - {sell['order_id']}: {sell['quantity']:,.2f} DOGE @ ${sell['price']:,.4f} on {sell['date']}{partial_note}")
                print(f"   Total Sold: {sold_qty:,.2f} DOGE")
            else:
                print(f"   📉 Matched SELL Orders: None")
                print(f"   Total Sold: 0 DOGE")
            
            if remaining_buy_qty > 0:
                print(f"   ✅ Remaining: {remaining_buy_qty:,.2f} DOGE (${remaining_value:,.2f})")
                unclosed_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'buy_date': buy_date,
                    'buy_qty': buy_qty,
                    'buy_price': buy_price,
                    'buy_value': buy_value,
                    'sold_qty': sold_qty,
                    'remaining_qty': remaining_buy_qty,
                    'remaining_value': remaining_value,
                    'matched_sells': matched_sells
                })
            else:
                print(f"   ✅ Fully Closed")
            
            print("-" * 100)
        
        # Summary
        print(f"\n📋 SUMMARY")
        print("=" * 100)
        print(f"Total BUY Orders: {len(buy_orders)}")
        print(f"Total SELL Orders: {len(sell_orders)}")
        print(f"Unclosed Orders: {len(unclosed_orders)}")
        print(f"\nTotal Bought: {total_bought:,.2f} DOGE")
        print(f"Total Sold (matched): {total_sold:,.2f} DOGE")
        print(f"Total Remaining: {total_bought - total_sold:,.2f} DOGE")
        
        if unclosed_orders:
            print(f"\n🔴 UNCLOSED ORDERS:")
            print("=" * 100)
            total_remaining_value = sum(o['remaining_value'] for o in unclosed_orders)
            for order in unclosed_orders:
                print(f"\nOrder ID: {order['order_id']}")
                print(f"  Date: {order['buy_date']}")
                print(f"  Bought: {order['buy_qty']:,.2f} DOGE @ ${order['buy_price']:,.4f}")
                print(f"  Sold: {order['sold_qty']:,.2f} DOGE")
                print(f"  Remaining: {order['remaining_qty']:,.2f} DOGE (${order['remaining_value']:,.2f})")
                if order['matched_sells']:
                    print(f"  Matched SELL Orders: {len(order['matched_sells'])}")
            
            print(f"\n💰 Total Remaining Value: ${total_remaining_value:,.2f}")
        else:
            print(f"\n✅ All orders are fully closed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    list_unclosed_doge_orders()

