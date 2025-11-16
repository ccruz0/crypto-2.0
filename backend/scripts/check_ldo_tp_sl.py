#!/usr/bin/env python3
import sys
import os
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/app")
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

db = SessionLocal()
try:
    # Check last 7 days to find recent TP orders
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    
    print(f"🔍 Checking TP orders for LDO executed in the last 7 days:")
    print(f"   From: {week_ago.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"   To: {today.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    tp_orders_all = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == "LDO_USDT",
        ExchangeOrder.order_role == "TAKE_PROFIT",
        ExchangeOrder.status == OrderStatusEnum.FILLED
    ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
    
    tp_orders = []
    for order in tp_orders_all:
        order_time = order.exchange_update_time or order.updated_at
        if order_time:
            if hasattr(order_time, "tzinfo") and order_time.tzinfo is None:
                order_time = order_time.replace(tzinfo=timezone.utc)
            elif hasattr(order_time, "tzinfo") and order_time.tzinfo != timezone.utc:
                order_time = order_time.astimezone(timezone.utc)
            if week_ago <= order_time < today:
                tp_orders.append(order)
    
    # Also check yesterday specifically
    yesterday_start = today - timedelta(days=1)
    yesterday_end = today
    tp_orders_yesterday = []
    for o in tp_orders:
        o_time = o.exchange_update_time or o.updated_at
        if o_time:
            if hasattr(o_time, "tzinfo") and o_time.tzinfo is None:
                o_time = o_time.replace(tzinfo=timezone.utc)
            elif hasattr(o_time, "tzinfo") and o_time.tzinfo != timezone.utc:
                o_time = o_time.astimezone(timezone.utc)
            if yesterday_start <= o_time < yesterday_end:
                tp_orders_yesterday.append(o)
    
    print(f"📊 Found {len(tp_orders)} TP orders executed in last 7 days")
    print(f"📊 Found {len(tp_orders_yesterday)} TP orders executed yesterday")
    print()
    
    if len(tp_orders) == 0:
        print("✅ No TP orders found in the last 7 days. Nothing to verify.")
    else:
        # Use yesterday's orders if available, otherwise use all recent orders
        orders_to_check = tp_orders_yesterday if tp_orders_yesterday else tp_orders
        check_period = "yesterday" if tp_orders_yesterday else "last 7 days"
        
        print(f"🔍 Verifying {len(orders_to_check)} TP orders from {check_period}:")
        print()
        
        if len(orders_to_check) == 0:
            print("✅ No TP orders found for the specified period. Nothing to verify.")
        else:
            issues = []
            verified = []
            
            for tp_order in orders_to_check:
                tp_id = tp_order.exchange_order_id
                tp_time = tp_order.exchange_update_time or tp_order.updated_at
                oco_group_id = tp_order.oco_group_id
                
                print(f"🔍 Checking TP order: {tp_id}")
                print(f"   Time: {tp_time}")
                print(f"   OCO Group ID: {oco_group_id}")
                
                if oco_group_id:
                    sl_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == "LDO_USDT",
                        ExchangeOrder.oco_group_id == oco_group_id,
                        ExchangeOrder.order_role == "STOP_LOSS",
                        ExchangeOrder.exchange_order_id != tp_id
                    ).first()
                    
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
                            issues.append({"tp_id": tp_id, "sl_status": status_str, "issue": f"SL not cancelled (status: {status_str})"})
                    else:
                        print(f"   ⚠️ No SL order found in OCO group {oco_group_id}")
                        issues.append({"tp_id": tp_id, "issue": "No SL order found in OCO group"})
                else:
                    print(f"   ⚠️ TP order has no OCO group ID")
                    issues.append({"tp_id": tp_id, "issue": "TP order has no OCO group ID"})
                
                print()
            
            print("=" * 80)
            print("📊 SUMMARY")
            print("=" * 80)
            print(f"Total TP orders checked: {len(orders_to_check)}")
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
