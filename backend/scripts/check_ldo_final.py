#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from datetime import datetime, timedelta, timezone

db = SessionLocal()
try:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today - timedelta(days=1)
    yesterday_end = today
    
    tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == "LDO_USDT",
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
    
    print(f"🔍 Found {len(tp_orders_yesterday)} TP orders executed yesterday (2025-11-10)")
    print()
    
    if len(tp_orders_yesterday) == 0:
        print("✅ No TP orders found for yesterday.")
    else:
        issues = []
        verified = []
        
        for tp_order in tp_orders_yesterday:
            tp_id = tp_order.exchange_order_id
            tp_time = tp_order.exchange_update_time or tp_order.updated_at
            oco_group_id = tp_order.oco_group_id
            
            print(f"🔍 Checking TP order: {tp_id}")
            print(f"   Time: {tp_time}")
            print(f"   OCO Group ID: {oco_group_id}")
            print(f"   Order Type: {tp_order.order_type}")
            
            sl_order = None
            if oco_group_id:
                sl_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == "LDO_USDT",
                    ExchangeOrder.oco_group_id == oco_group_id,
                    ExchangeOrder.order_type.in_(["STOP_LOSS", "STOP_LIMIT"]),
                    ExchangeOrder.exchange_order_id != tp_id
                ).first()
            
            if not sl_order and tp_time:
                time_window_start = tp_time - timedelta(minutes=5)
                time_window_end = tp_time + timedelta(minutes=5)
                sl_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == "LDO_USDT",
                    ExchangeOrder.order_type.in_(["STOP_LOSS", "STOP_LIMIT"]),
                    ExchangeOrder.exchange_order_id != tp_id,
                    ExchangeOrder.exchange_create_time >= time_window_start,
                    ExchangeOrder.exchange_create_time <= time_window_end
                ).all()
                if sl_orders:
                    sl_order = sl_orders[0]
            
            if sl_order:
                sl_status = sl_order.status
                sl_time = sl_order.exchange_update_time or sl_order.updated_at
                
                print(f"   ✅ Found SL order: {sl_order.exchange_order_id}")
                print(f"      Status: {sl_status}")
                print(f"      Updated: {sl_time}")
                
                if sl_status == OrderStatusEnum.CANCELLED:
                    if sl_time and tp_time:
                        if sl_time >= tp_time:
                            print(f"      ✅ SL was cancelled AFTER TP was filled (correct)")
                            verified.append({"tp_id": tp_id})
                        else:
                            print(f"      ⚠️ SL was cancelled BEFORE TP was filled (suspicious)")
                            issues.append({"tp_id": tp_id, "issue": "SL cancelled before TP filled"})
                    else:
                        verified.append({"tp_id": tp_id})
                else:
                    status_str = str(sl_status)
                    print(f"      ❌ SL was NOT cancelled! Status: {status_str}")
                    issues.append({"tp_id": tp_id, "sl_status": status_str, "issue": "SL not cancelled"})
            else:
                print(f"   ⚠️ No SL order found")
                issues.append({"tp_id": tp_id, "issue": "No SL order found"})
            
            print()
        
        print("=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"Total TP orders checked: {len(tp_orders_yesterday)}")
        print(f"✅ Verified (SL cancelled correctly): {len(verified)}")
        print(f"❌ Issues found: {len(issues)}")
        print()
        
        if issues:
            print("❌ ISSUES FOUND:")
            print("-" * 80)
            for issue in issues:
                tp_id_val = issue["tp_id"]
                issue_msg = issue["issue"]
                print(f"TP Order ID: {tp_id_val}")
                print(f"  Issue: {issue_msg}")
                if "sl_status" in issue:
                    sl_status_val = issue["sl_status"]
                    print(f"  SL Status: {sl_status_val}")
                print()
        else:
            print("✅ All TP orders had their corresponding SL orders cancelled correctly!")
finally:
    db.close()

