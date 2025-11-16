#!/usr/bin/env python3
"""
Script to fix uncancelled SL orders for TP orders that were executed yesterday.
Applies the new OCO cancellation logic to historical orders.
"""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService

def fix_uncancelled_sl_orders():
    """Fix uncancelled SL orders for TP orders executed yesterday"""
    db = SessionLocal()
    sync_service = ExchangeSyncService()
    
    try:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today - timedelta(days=1)
        yesterday_end = today
        
        print(f"🔍 Looking for TP orders executed on {yesterday_start.strftime('%Y-%m-%d')} with uncancelled SL orders...")
        print()
        
        # Find TP orders executed yesterday
        tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.order_type.in_(["TAKE_PROFIT", "TAKE_PROFIT_LIMIT"]),
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
        
        tp_orders_yesterday = []
        for order in tp_orders:
            order_time = order.exchange_update_time or order.updated_at
            if order_time:
                if hasattr(order_time, "tzinfo") and order_time.tzinfo is None:
                    order_time = order_time.replace(tzinfo=timezone.utc)
                elif hasattr(order_time, "tzinfo") and order_time.tzinfo != timezone.utc:
                    order_time = order_time.astimezone(timezone.utc)
                if yesterday_start <= order_time < yesterday_end:
                    tp_orders_yesterday.append(order)
        
        print(f"📊 Found {len(tp_orders_yesterday)} TP orders executed yesterday")
        print()
        
        if len(tp_orders_yesterday) == 0:
            print("✅ No TP orders found for yesterday.")
            return
        
        # Find TP orders with uncancelled SL orders
        orders_to_fix = []
        for tp_order in tp_orders_yesterday:
            if not tp_order.oco_group_id:
                continue
            
            # Find SL order in same OCO group
            sl_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == tp_order.symbol,
                ExchangeOrder.oco_group_id == tp_order.oco_group_id,
                ExchangeOrder.order_type.in_(["STOP_LOSS", "STOP_LIMIT"]),
                ExchangeOrder.exchange_order_id != tp_order.exchange_order_id,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()
            
            if sl_order:
                orders_to_fix.append({
                    'tp_order': tp_order,
                    'sl_order': sl_order
                })
        
        print(f"🔧 Found {len(orders_to_fix)} TP orders with uncancelled SL orders")
        print()
        
        if len(orders_to_fix) == 0:
            print("✅ All SL orders are already cancelled or no OCO groups found.")
            return
        
        # Ask user to select one (or process the first one)
        print("📋 Orders to fix:")
        for i, item in enumerate(orders_to_fix[:5], 1):  # Show first 5
            tp = item['tp_order']
            sl = item['sl_order']
            print(f"   {i}. {tp.symbol} - TP: {tp.exchange_order_id}, SL: {sl.exchange_order_id} (Status: {sl.status})")
        print()
        
        # Process the first one
        if orders_to_fix:
            item = orders_to_fix[0]
            tp_order = item['tp_order']
            sl_order = item['sl_order']
            
            print(f"🔧 Processing: {tp_order.symbol}")
            print(f"   TP Order ID: {tp_order.exchange_order_id}")
            print(f"   SL Order ID: {sl_order.exchange_order_id}")
            print(f"   OCO Group ID: {tp_order.oco_group_id}")
            print(f"   SL Status: {sl_order.status}")
            print()
            
            # Apply the new cancellation logic
            try:
                print("🔄 Calling _cancel_oco_sibling...")
                import asyncio
                asyncio.run(sync_service._cancel_oco_sibling(db, tp_order))
                print("✅ Cancellation logic applied successfully!")
                print()
                print("📱 Check Telegram for the detailed notification.")
            except Exception as e:
                print(f"❌ Error applying cancellation logic: {e}")
                import traceback
                traceback.print_exc()
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    fix_uncancelled_sl_orders()

