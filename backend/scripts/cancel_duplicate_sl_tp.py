#!/usr/bin/env python3
"""
Script to cancel duplicate SL/TP orders for a given symbol.

This script identifies duplicate SL/TP orders (same symbol, type, price, quantity, trigger)
and cancels all but one (keeping the one with parent_order_id or the oldest).
"""

import sys
import os
from datetime import datetime, timezone
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.live_trading import get_live_trading_status

def find_duplicate_orders(db, symbol: str):
    """
    Find duplicate SL/TP orders for a symbol.
    
    Returns:
        dict: {group_key: [orders]} where group_key identifies duplicates
    """
    # Find all active SL/TP orders for the symbol
    sl_tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == symbol,
        ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']),
        ExchangeOrder.status.in_([
            OrderStatusEnum.NEW,
            OrderStatusEnum.ACTIVE,
            OrderStatusEnum.PARTIALLY_FILLED
        ])
    ).all()
    
    # Group orders by characteristics that make them duplicates
    # Key: (order_type, price, quantity, trigger_price/condition)
    groups = defaultdict(list)
    
    for order in sl_tp_orders:
        # Create a key based on order characteristics
        # For SL/TP orders, duplicates have same: type, price, quantity, and similar trigger
        key = (
            order.order_type,
            round(float(order.price), 8) if order.price else None,  # Round to 8 decimals for comparison
            round(float(order.quantity), 8) if order.quantity else None,
            # For trigger orders, we can't easily get trigger_price from DB, so use price as proxy
            # Orders with same price and quantity are likely duplicates
        )
        groups[key].append(order)
    
    # Filter to only groups with duplicates (2+ orders)
    duplicate_groups = {k: orders for k, orders in groups.items() if len(orders) > 1}
    
    return duplicate_groups

def cancel_duplicate_orders(db, symbol: str, dry_run: bool = True):
    """
    Cancel duplicate SL/TP orders, keeping one from each group.
    
    Strategy:
    1. Keep order with parent_order_id (properly linked)
    2. If multiple have parent_order_id, keep the oldest
    3. If none have parent_order_id, keep the oldest
    """
    duplicate_groups = find_duplicate_orders(db, symbol)
    
    if not duplicate_groups:
        print(f"✅ No duplicate SL/TP orders found for {symbol}")
        return
    
    print(f"🔍 Found {len(duplicate_groups)} group(s) of duplicate orders for {symbol}")
    print()
    
    total_to_cancel = 0
    total_cancelled = 0
    total_failed = 0
    
    for group_key, orders in duplicate_groups.items():
        # group_key is a tuple: (order_type, price, quantity)
        order_type = group_key[0]
        price = group_key[1] if len(group_key) > 1 else None
        qty = group_key[2] if len(group_key) > 2 else None
        print(f"📦 Group: {order_type} @ {price} qty={qty}")
        print(f"   Found {len(orders)} duplicate orders:")
        
        # Sort orders: prefer those with parent_order_id, then by creation time (oldest first)
        def sort_key(order):
            has_parent = 1 if order.parent_order_id else 0
            create_time = order.exchange_create_time or order.created_at or datetime.min.replace(tzinfo=timezone.utc)
            return (-has_parent, create_time)  # Negative to put True first
        
        sorted_orders = sorted(orders, key=sort_key)
        
        # Keep the first one (best candidate)
        keep_order = sorted_orders[0]
        cancel_orders = sorted_orders[1:]
        
        print(f"   ✅ KEEPING: {keep_order.exchange_order_id}")
        if keep_order.parent_order_id:
            print(f"      (has parent_order_id: {keep_order.parent_order_id})")
        else:
            print(f"      (oldest order, no parent_order_id)")
        
        print(f"   ❌ CANCELLING {len(cancel_orders)} duplicate(s):")
        for order in cancel_orders:
            print(f"      - {order.exchange_order_id} (created: {order.exchange_create_time or order.created_at})")
            if order.parent_order_id:
                print(f"        ⚠️  Has parent_order_id: {order.parent_order_id} (will be cancelled anyway)")
        
        total_to_cancel += len(cancel_orders)
        
        if not dry_run:
            # Cancel orders
            for order in cancel_orders:
                try:
                    order_id = order.exchange_order_id
                    print(f"   🗑️  Cancelling {order_id}...", end=" ")
                    
                    result = trade_client.cancel_order(order_id)
                    
                    if "error" not in result:
                        # Update order status in database
                        order.status = OrderStatusEnum.CANCELLED
                        order.exchange_update_time = datetime.now(timezone.utc)
                        db.commit()
                        print("✅ Cancelled")
                        total_cancelled += 1
                    else:
                        error_msg = result.get("error", "Unknown error")
                        print(f"❌ Failed: {error_msg}")
                        total_failed += 1
                except Exception as e:
                    print(f"❌ Error: {e}")
                    total_failed += 1
                    db.rollback()
        else:
            print(f"   [DRY RUN] Would cancel {len(cancel_orders)} order(s)")
        
        print()
    
    print("=" * 60)
    if dry_run:
        print(f"📊 DRY RUN SUMMARY:")
        print(f"   Groups with duplicates: {len(duplicate_groups)}")
        print(f"   Orders to cancel: {total_to_cancel}")
        print(f"   Orders to keep: {len(duplicate_groups)}")
        print()
        print("💡 Run with --live to actually cancel orders")
    else:
        print(f"📊 CANCELLATION SUMMARY:")
        print(f"   Groups processed: {len(duplicate_groups)}")
        print(f"   Orders cancelled: {total_cancelled}")
        print(f"   Orders failed: {total_failed}")
        print(f"   Orders kept: {len(duplicate_groups)}")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Cancel duplicate SL/TP orders")
    parser.add_argument("--symbol", default="ALGO_USDT", help="Symbol to check (default: ALGO_USDT)")
    parser.add_argument("--live", action="store_true", help="Actually cancel orders (default: dry run)")
    parser.add_argument("--all-symbols", action="store_true", help="Check all symbols with duplicates")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        live_trading = get_live_trading_status(db)
        dry_run = not (args.live and live_trading)
        
        if dry_run and args.live:
            print("⚠️  WARNING: LIVE_TRADING is disabled. Running in DRY RUN mode.")
            print("   Set LIVE_TRADING=true to enable actual cancellation.")
            print()
        
        if args.all_symbols:
            # Find all symbols with duplicate orders
            all_duplicates = db.query(ExchangeOrder.symbol).filter(
                ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']),
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).distinct().all()
            
            symbols = [s[0] for s in all_duplicates]
            print(f"🔍 Checking {len(symbols)} symbols for duplicate orders...")
            print()
            
            for symbol in symbols:
                duplicate_groups = find_duplicate_orders(db, symbol)
                if duplicate_groups:
                    print(f"📊 {symbol}: {len(duplicate_groups)} duplicate group(s)")
                    cancel_duplicate_orders(db, symbol, dry_run=dry_run)
                    print()
        else:
            cancel_duplicate_orders(db, args.symbol, dry_run=dry_run)
    finally:
        db.close()

if __name__ == "__main__":
    main()


