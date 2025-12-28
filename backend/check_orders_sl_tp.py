#!/usr/bin/env python3
"""
Script to check orders created today and verify if they have SL/TP orders
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from sqlalchemy import and_, or_

def check_orders_sl_tp():
    """Check orders created today and their SL/TP status"""
    db = SessionLocal()
    
    try:
        # Get today's date range (UTC)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # Also check last 24 hours in case orders are from yesterday
        last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        
        print(f"\n🔍 Checking orders created today ({today_start.date()} UTC) and last 24 hours\n")
        print("=" * 80)
        
        # First, check for the specific DOT_USDT order mentioned
        dot_order_id = "5755600481538037740"
        dot_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == dot_order_id
        ).first()
        
        # Also check for any DOT_USDT orders
        dot_orders = db.query(ExchangeOrder).filter(
            and_(
                ExchangeOrder.symbol == "DOT_USDT",
                ExchangeOrder.parent_order_id.is_(None),
                ExchangeOrder.order_type.in_(['MARKET', 'LIMIT'])
            )
        ).order_by(ExchangeOrder.created_at.desc()).limit(5).all()
        
        if dot_order:
            print(f"📌 Found specific order mentioned: {dot_order_id}\n")
        elif dot_orders:
            print(f"📌 Found {len(dot_orders)} DOT_USDT order(s) (not the specific one mentioned)\n")
            today_orders.extend(dot_orders)
        
        # Query all orders created today or in last 24 hours (excluding SL/TP orders themselves)
        # Check both created_at and exchange_create_time
        today_orders = db.query(ExchangeOrder).filter(
            and_(
                or_(
                    ExchangeOrder.created_at >= last_24h,
                    ExchangeOrder.exchange_create_time >= last_24h,
                    ExchangeOrder.updated_at >= last_24h
                ),
                # Exclude SL/TP orders (they have parent_order_id set)
                ExchangeOrder.parent_order_id.is_(None),
                # Only main orders (MARKET, LIMIT)
                ExchangeOrder.order_type.in_(['MARKET', 'LIMIT'])
            )
        ).order_by(ExchangeOrder.created_at.desc()).all()
        
        # Add the specific DOT order if found and not already in the list
        if dot_order and dot_order not in today_orders:
            today_orders.append(dot_order)
        
        # Remove duplicates
        seen_ids = set()
        unique_orders = []
        for order in today_orders:
            if order.exchange_order_id not in seen_ids:
                seen_ids.add(order.exchange_order_id)
                unique_orders.append(order)
        today_orders = unique_orders
        
        # If still no orders, get the most recent 10 orders regardless of date
        if not today_orders:
            print("⚠️  No orders found in last 24 hours. Checking most recent orders...\n")
            today_orders = db.query(ExchangeOrder).filter(
                and_(
                    ExchangeOrder.parent_order_id.is_(None),
                    ExchangeOrder.order_type.in_(['MARKET', 'LIMIT'])
                )
            ).order_by(ExchangeOrder.created_at.desc()).limit(10).all()
        
        # Also check for any SELL orders specifically
        sell_orders = db.query(ExchangeOrder).filter(
            and_(
                ExchangeOrder.side == 'SELL',
                ExchangeOrder.parent_order_id.is_(None),
                ExchangeOrder.order_type.in_(['MARKET', 'LIMIT']),
                or_(
                    ExchangeOrder.created_at >= last_24h,
                    ExchangeOrder.exchange_create_time >= last_24h
                )
            )
        ).order_by(ExchangeOrder.created_at.desc()).all()
        
        if sell_orders:
            print(f"📌 Found {len(sell_orders)} SELL order(s) in last 24 hours\n")
            for so in sell_orders:
                if so.exchange_order_id not in seen_ids:
                    today_orders.append(so)
                    seen_ids.add(so.exchange_order_id)
        
        if not today_orders:
            print("✅ No orders created today (excluding SL/TP orders)")
            return
        
        print(f"📊 Found {len(today_orders)} main order(s) created today:\n")
        
        orders_without_sl_tp = []
        orders_with_sl_tp = []
        
        for order in today_orders:
            order_id = order.exchange_order_id
            symbol = order.symbol
            side = order.side.value if hasattr(order.side, 'value') else str(order.side)
            order_type = order.order_type
            status = order.status.value if hasattr(order.status, 'value') else str(order.status)
            price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
            quantity = float(order.quantity) if order.quantity else 0
            created_at = order.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if order.created_at else "N/A"
            
            # Check for SL/TP orders associated with this order
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
            
            # Print order details
            side_emoji = "🟢" if side == "BUY" else "🔴"
            print(f"{side_emoji} Order: {order_id}")
            print(f"   Symbol: {symbol}")
            print(f"   Side: {side} | Type: {order_type} | Status: {status}")
            print(f"   Price: ${price:.4f} | Quantity: {quantity:.8f}")
            print(f"   Created: {created_at}")
            
            # Check SL/TP status
            sl_status = "✅" if has_sl else "❌ MISSING"
            tp_status = "✅" if has_tp else "❌ MISSING"
            
            print(f"   🛑 Stop Loss: {sl_status}", end="")
            if has_sl:
                sl_ids = [o.exchange_order_id for o in sl_orders]
                sl_statuses = [o.status.value if hasattr(o.status, 'value') else str(o.status) for o in sl_orders]
                print(f" (IDs: {', '.join(sl_ids)}, Status: {', '.join(sl_statuses)})")
            else:
                print()
            
            print(f"   🚀 Take Profit: {tp_status}", end="")
            if has_tp:
                tp_ids = [o.exchange_order_id for o in tp_orders]
                tp_statuses = [o.status.value if hasattr(o.status, 'value') else str(o.status) for o in tp_orders]
                print(f" (IDs: {', '.join(tp_ids)}, Status: {', '.join(tp_statuses)})")
            else:
                print()
            
            if has_sl and has_tp:
                orders_with_sl_tp.append(order)
                print("   ✅ Has both SL and TP")
            else:
                orders_without_sl_tp.append(order)
                missing = []
                if not has_sl:
                    missing.append("SL")
                if not has_tp:
                    missing.append("TP")
                print(f"   ⚠️  Missing: {', '.join(missing)}")
            
            print()
        
        # Summary
        print("=" * 80)
        print(f"\n📊 Summary:")
        print(f"   Total orders today: {len(today_orders)}")
        print(f"   ✅ Orders with SL/TP: {len(orders_with_sl_tp)}")
        print(f"   ⚠️  Orders missing SL/TP: {len(orders_without_sl_tp)}")
        
        if orders_without_sl_tp:
            print(f"\n⚠️  Orders missing SL/TP:")
            for order in orders_without_sl_tp:
                missing = []
                sl_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.parent_order_id == order.exchange_order_id,
                        ExchangeOrder.order_role == 'STOP_LOSS'
                    )
                ).count()
                tp_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.parent_order_id == order.exchange_order_id,
                        ExchangeOrder.order_role == 'TAKE_PROFIT'
                    )
                ).count()
                
                if sl_orders == 0:
                    missing.append("SL")
                if tp_orders == 0:
                    missing.append("TP")
                
                print(f"   - {order.exchange_order_id} ({order.symbol} {order.side.value}) - Missing: {', '.join(missing)}")
        
        print()
        
    except Exception as e:
        print(f"❌ Error checking orders: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0

if __name__ == "__main__":
    exit(check_orders_sl_tp())

