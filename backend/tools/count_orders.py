#!/usr/bin/env python3
"""Script to count orders in the database"""
import os
import sys
from sqlalchemy import func
from sqlalchemy.exc import OperationalError

# Add backend/ to path so `app` resolves (tools/ lives under backend/)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import create_db_session, exit_2_if_missing_schema_tables
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum


def count_orders():
    db = create_db_session()
    try:
        # Total orders
        try:
            total_orders = db.query(ExchangeOrder).count()
        except OperationalError as e:
            exit_2_if_missing_schema_tables(
                e,
                table_names=("exchange_orders",),
                stderr_message=(
                    "Connected to the app database, but table `exchange_orders` is missing. "
                    "Run migrations against this DATABASE_URL or point DATABASE_URL at a migrated instance."
                ),
            )
        
        # Orders by status
        orders_by_status = db.query(
            ExchangeOrder.status,
            func.count(ExchangeOrder.id)
        ).group_by(ExchangeOrder.status).all()
        
        # Orders by side
        orders_by_side = db.query(
            ExchangeOrder.side,
            func.count(ExchangeOrder.id)
        ).group_by(ExchangeOrder.side).all()
        
        # Filled BUY orders
        filled_buy_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).count()
        
        # Filled orders by symbol (top 10)
        filled_by_symbol = db.query(
            ExchangeOrder.symbol,
            func.count(ExchangeOrder.id)
        ).filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).group_by(ExchangeOrder.symbol).order_by(func.count(ExchangeOrder.id).desc()).limit(10).all()
        
        print("=" * 60)
        print("ORDER STATISTICS")
        print("=" * 60)
        print(f"\nTotal orders in database: {total_orders}")
        
        print(f"\nFilled BUY orders: {filled_buy_orders}")
        
        print("\nOrders by status:")
        for status, count in orders_by_status:
            print(f"  {status.value if hasattr(status, 'value') else status}: {count}")
        
        print("\nOrders by side:")
        for side, count in orders_by_side:
            print(f"  {side.value if hasattr(side, 'value') else side}: {count}")
        
        print("\nTop 10 symbols by filled orders:")
        for symbol, count in filled_by_symbol:
            print(f"  {symbol}: {count}")
        
        print("=" * 60)
        
    finally:
        db.close()

if __name__ == "__main__":
    count_orders()

