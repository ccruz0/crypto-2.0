#!/usr/bin/env python3
"""
Quick script to check order in database using app's database connection
"""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from sqlalchemy import and_, or_
from datetime import datetime, timezone, timedelta

def check_order():
    db = SessionLocal()
    
    try:
        order_id = "5755600481538037740"
        
        # Check for the specific order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if order:
            print(f"✅ Found order: {order_id}")
            print(f"   Symbol: {order.symbol}")
            print(f"   Side: {order.side.value}")
            print(f"   Status: {order.status.value}")
            print(f"   Type: {order.order_type}")
            print(f"   Created: {order.created_at}")
            
            # Check for SL/TP
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
            
            print(f"   🛑 SL: {'✅' if sl_orders else '❌ MISSING'}")
            print(f"   🚀 TP: {'✅' if tp_orders else '❌ MISSING'}")
        else:
            print(f"❌ Order {order_id} not found")
            
            # Check for any DOT_USDT orders
            dot_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == "DOT_USDT"
            ).order_by(ExchangeOrder.created_at.desc()).limit(5).all()
            
            if dot_orders:
                print(f"\n📌 Found {len(dot_orders)} DOT_USDT order(s):")
                for o in dot_orders:
                    print(f"   - {o.exchange_order_id} ({o.side.value}, {o.status.value}, {o.created_at})")
            
            # Check for recent SELL orders
            last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            sell_orders = db.query(ExchangeOrder).filter(
                and_(
                    ExchangeOrder.side == 'SELL',
                    or_(
                        ExchangeOrder.created_at >= last_24h,
                        ExchangeOrder.exchange_create_time >= last_24h
                    )
                )
            ).order_by(ExchangeOrder.created_at.desc()).limit(5).all()
            
            if sell_orders:
                print(f"\n📌 Found {len(sell_orders)} recent SELL order(s):")
                for o in sell_orders:
                    print(f"   - {o.exchange_order_id} ({o.symbol}, {o.status.value}, {o.created_at})")
        
    finally:
        db.close()

if __name__ == "__main__":
    check_order()





