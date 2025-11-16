#!/usr/bin/env python3
"""
Script to verify that all TP orders for LDO executed yesterday had their corresponding SL orders cancelled.
"""
import sys
import os
from datetime import datetime, timedelta, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderRoleEnum
from sqlalchemy import and_, or_

def verify_ldo_tp_sl_cancellation():
    """Verify that all TP orders for LDO executed yesterday had their SL orders cancelled"""
    db = SessionLocal()
    
    try:
        # Calculate yesterday's date range (UTC)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today - timedelta(days=1)
        yesterday_end = today
        
        print(f"🔍 Checking TP orders for LDO executed between:")
        print(f"   Start: {yesterday_start.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"   End: {yesterday_end.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()
        
        # Find all TP orders for LDO that were FILLED yesterday
        # Check both exchange_update_time and updated_at (handle timezone differences)
        tp_orders = db.query(ExchangeOrder).filter(
            and_(
                ExchangeOrder.symbol == "LDO_USDT",
                ExchangeOrder.order_role == OrderRoleEnum.TP,
                ExchangeOrder.status == OrderStatusEnum.FILLED
            )
        ).all()
        
        # Filter by date manually to handle timezone issues
        tp_orders_yesterday = []
        for order in tp_orders:
            order_time = order.exchange_update_time or order.updated_at
            if order_time:
                # Normalize to UTC for comparison
                if hasattr(order_time, 'tzinfo') and order_time.tzinfo is None:
                    order_time = order_time.replace(tzinfo=timezone.utc)
                elif hasattr(order_time, 'tzinfo') and order_time.tzinfo != timezone.utc:
                    order_time = order_time.astimezone(timezone.utc)
                elif not hasattr(order_time, 'tzinfo'):
                    # Assume naive datetime is UTC
                    order_time = order_time.replace(tzinfo=timezone.utc) if isinstance(order_time, datetime) else None
                
                if order_time and yesterday_start <= order_time < yesterday_end:
                    tp_orders_yesterday.append(order)
        
        tp_orders = tp_orders_yesterday
        
        print(f"📊 Found {len(tp_orders)} TP orders executed yesterday")
        print()
        
        if len(tp_orders) == 0:
            print("✅ No TP orders found for yesterday. Nothing to verify.")
            return
        
        # Verify each TP order
        issues = []
        verified = []
        
        for tp_order in tp_orders:
            tp_id = tp_order.exchange_order_id
            tp_time = tp_order.exchange_update_time or tp_order.updated_at
            oco_group_id = tp_order.oco_group_id
            
            print(f"🔍 Checking TP order: {tp_id}")
            print(f"   Time: {tp_time}")
            print(f"   OCO Group ID: {oco_group_id}")
            print(f"   Price: ${tp_order.price or tp_order.avg_price or tp_order.filled_price}")
            print(f"   Quantity: {tp_order.quantity}")
            
            # Find corresponding SL order in the same OCO group
            if oco_group_id:
                sl_order = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == "LDO_USDT",
                        ExchangeOrder.oco_group_id == oco_group_id,
                        ExchangeOrder.order_role == OrderRoleEnum.SL,
                        ExchangeOrder.exchange_order_id != tp_id
                    )
                ).first()
                
                if sl_order:
                    sl_status = sl_order.status
                    sl_time = sl_order.exchange_update_time or sl_order.updated_at
                    
                    print(f"   ✅ Found SL order: {sl_order.exchange_order_id}")
                    print(f"      Status: {sl_status}")
                    print(f"      Updated: {sl_time}")
                    
                    # Check if SL was cancelled
                    if sl_status == OrderStatusEnum.CANCELLED:
                        # Verify cancellation happened after TP was filled
                        if sl_time and tp_time:
                            if sl_time >= tp_time:
                                print(f"      ✅ SL was cancelled AFTER TP was filled (correct)")
                                verified.append({
                                    'tp_id': tp_id,
                                    'tp_time': tp_time,
                                    'sl_id': sl_order.exchange_order_id,
                                    'sl_time': sl_time,
                                    'status': 'OK'
                                })
                            else:
                                print(f"      ⚠️ SL was cancelled BEFORE TP was filled (suspicious)")
                                issues.append({
                                    'tp_id': tp_id,
                                    'tp_time': tp_time,
                                    'sl_id': sl_order.exchange_order_id,
                                    'sl_time': sl_time,
                                    'issue': 'SL cancelled before TP filled'
                                })
                        else:
                            print(f"      ⚠️ Cannot verify timing (missing timestamps)")
                            verified.append({
                                'tp_id': tp_id,
                                'tp_time': tp_time,
                                'sl_id': sl_order.exchange_order_id,
                                'sl_time': sl_time,
                                'status': 'OK (timing unknown)'
                            })
                    else:
                        print(f"      ❌ SL was NOT cancelled! Status: {sl_status}")
                        issues.append({
                            'tp_id': tp_id,
                            'tp_time': tp_time,
                            'sl_id': sl_order.exchange_order_id,
                            'sl_status': sl_status,
                            'issue': f'SL not cancelled (status: {sl_status})'
                        })
                else:
                    print(f"   ⚠️ No SL order found in OCO group {oco_group_id}")
                    issues.append({
                        'tp_id': tp_id,
                        'tp_time': tp_time,
                        'oco_group_id': oco_group_id,
                        'issue': 'No SL order found in OCO group'
                    })
            else:
                print(f"   ⚠️ TP order has no OCO group ID")
                issues.append({
                    'tp_id': tp_id,
                    'tp_time': tp_time,
                    'issue': 'TP order has no OCO group ID'
                })
            
            print()
        
        # Summary
        print("=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"Total TP orders checked: {len(tp_orders)}")
        print(f"✅ Verified (SL cancelled correctly): {len(verified)}")
        print(f"❌ Issues found: {len(issues)}")
        print()
        
        if issues:
            print("❌ ISSUES FOUND:")
            print("-" * 80)
            for issue in issues:
                print(f"TP Order ID: {issue['tp_id']}")
                print(f"  Issue: {issue['issue']}")
                if 'sl_id' in issue:
                    print(f"  SL Order ID: {issue['sl_id']}")
                if 'sl_status' in issue:
                    print(f"  SL Status: {issue['sl_status']}")
                print()
        else:
            print("✅ All TP orders had their corresponding SL orders cancelled correctly!")
        
        return len(issues) == 0
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = verify_ldo_tp_sl_cancellation()
    sys.exit(0 if success else 1)

