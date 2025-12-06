#!/usr/bin/env python3
"""Script to cancel BTC_USDT BUY LIMIT orders that don't exist in exchange"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from datetime import datetime, timezone

def main():
    db = SessionLocal()
    try:
        # Buscar órdenes BTC_USDT BUY LIMIT activas
        orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == "BTC_USDT",
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.order_type == "LIMIT",
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()

        print(f"Órdenes BTC_USDT BUY LIMIT activas: {len(orders)}")
        for o in orders:
            print(f"  - ID: {o.exchange_order_id} | Status: {o.status.value} | Price: {o.price} | Qty: {o.quantity}")
            # Marcar como cancelada manualmente
            o.status = OrderStatusEnum.CANCELLED
            o.exchange_update_time = datetime.now(timezone.utc)
            print(f"    ✅ Marcada como CANCELLED")

        if orders:
            db.commit()
            print(f"✅ {len(orders)} órdenes canceladas en la base de datos")
        else:
            print("No se encontraron órdenes BTC_USDT BUY LIMIT activas")
    finally:
        db.close()

if __name__ == "__main__":
    main()






