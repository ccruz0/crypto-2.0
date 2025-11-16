#!/usr/bin/env python3
"""
Script to create SL/TP orders for the last filled order of a symbol.
Can be run directly from the backend directory when database is accessible.
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.services.exchange_sync import exchange_sync_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sl_tp_for_last_order(symbol: str = "SOL_USDT"):
    """Create SL/TP orders for the last filled order of a symbol"""
    db = SessionLocal()
    try:
        logger.info(f"Creating SL/TP for last order of {symbol}")
        
        # Find the last filled BUY order for the symbol
        last_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"])
        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not last_order:
            logger.error(f"❌ No filled BUY orders found for {symbol}")
            return False
        
        logger.info(f"✅ Found last order: {last_order.exchange_order_id}")
        logger.info(f"   Type: {last_order.order_type}")
        logger.info(f"   Side: {last_order.side.value}")
        logger.info(f"   Status: {last_order.status.value}")
        logger.info(f"   Price: ${last_order.avg_price or last_order.price}")
        logger.info(f"   Quantity: {last_order.cumulative_quantity or last_order.quantity}")
        
        # Check if this order already has SL/TP orders
        existing_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == last_order.exchange_order_id,
            ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if existing_sl_tp:
            logger.warning(f"⚠️ Order {last_order.exchange_order_id} already has {len(existing_sl_tp)} SL/TP order(s):")
            for order in existing_sl_tp:
                logger.info(f"   - {order.order_type} (ID: {order.exchange_order_id}, Status: {order.status.value})")
            return False
        
        logger.info(f"✅ No SL/TP orders found for order {last_order.exchange_order_id}")
        logger.info(f"   Creating SL/TP orders...")
        
        # Get filled price and quantity
        filled_price = float(last_order.avg_price) if last_order.avg_price else float(last_order.price) if last_order.price else None
        filled_qty = float(last_order.cumulative_quantity) if last_order.cumulative_quantity else float(last_order.quantity) if last_order.quantity else None
        
        if not filled_price or not filled_qty:
            logger.error(f"❌ Cannot create SL/TP: invalid price ({filled_price}) or quantity ({filled_qty})")
            return False
        
        logger.info(f"Creating SL/TP for order {last_order.exchange_order_id}: price={filled_price}, qty={filled_qty}")
        
        # Use the same logic as exchange_sync._create_sl_tp_for_filled_order
        exchange_sync_service._create_sl_tp_for_filled_order(
            db=db,
            symbol=symbol,
            side=last_order.side.value,  # "BUY"
            filled_price=filled_price,
            filled_qty=filled_qty,
            order_id=last_order.exchange_order_id
        )
        
        logger.info(f"✅ SL/TP orders created successfully for order {last_order.exchange_order_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        db.rollback()
        return False
    finally:
        db.close()


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "SOL_USDT"
    success = create_sl_tp_for_last_order(symbol)
    sys.exit(0 if success else 1)

