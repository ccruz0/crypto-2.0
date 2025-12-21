#!/usr/bin/env python3
"""Script to verify orders against exchange and mark stale orders as CANCELLED"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.services.brokers.crypto_com_trade import trade_client
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def verify_and_cleanup_stale_orders(symbol: str = None, dry_run: bool = False):
    """
    Verify orders in database against exchange and mark stale ones as CANCELLED.
    
    Args:
        symbol: Optional symbol to check (e.g., "BTC_USDT"). If None, checks all symbols.
        dry_run: If True, only shows what would be changed without making changes.
    """
    db = SessionLocal()
    try:
        # Get all active orders from database
        query = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW, 
                OrderStatusEnum.ACTIVE, 
                OrderStatusEnum.PARTIALLY_FILLED
            ])
        )
        
        if symbol:
            query = query.filter(ExchangeOrder.symbol == symbol.upper())
        
        db_orders = query.all()
        logger.info(f"Found {len(db_orders)} active orders in database" + (f" for {symbol}" if symbol else ""))
        
        if not db_orders:
            logger.info("No active orders found in database")
            return
        
        # Get actual open orders from exchange
        logger.info("Fetching open orders from exchange...")
        try:
            exchange_response = trade_client.get_open_orders()
            exchange_orders = exchange_response.get("data", [])
            
            # Also get trigger orders
            trigger_response = trade_client.get_trigger_orders()
            trigger_orders = trigger_response.get("data", []) if trigger_response else []
            
            # Combine all exchange orders
            all_exchange_orders = exchange_orders + trigger_orders
            exchange_order_ids = {order.get('order_id') for order in all_exchange_orders if order.get('order_id')}
            
            logger.info(f"Found {len(exchange_order_ids)} open orders on exchange")
            
        except Exception as e:
            logger.error(f"Error fetching orders from exchange: {e}")
            logger.warning("Cannot verify orders - exchange API call failed")
            return
        
        # Check each database order
        stale_orders = []
        valid_orders = []
        
        for db_order in db_orders:
            order_id = db_order.exchange_order_id
            if order_id in exchange_order_ids:
                valid_orders.append(db_order)
                logger.debug(f"✅ Order {order_id} ({db_order.symbol}) exists on exchange")
            else:
                stale_orders.append(db_order)
                logger.warning(f"❌ Order {order_id} ({db_order.symbol}) NOT found on exchange - marking as CANCELLED")
        
        # Report findings
        logger.info(f"\n{'='*60}")
        logger.info(f"Verification Results:")
        logger.info(f"  Valid orders: {len(valid_orders)}")
        logger.info(f"  Stale orders: {len(stale_orders)}")
        logger.info(f"{'='*60}\n")
        
        if stale_orders:
            logger.info("Stale orders to be marked as CANCELLED:")
            for order in stale_orders:
                logger.info(f"  - {order.exchange_order_id} | {order.symbol} | {order.side.value} | "
                          f"{order.order_type} | Price: {order.price} | Qty: {order.quantity} | "
                          f"Status: {order.status.value}")
            
            if not dry_run:
                # Mark stale orders as CANCELLED
                for order in stale_orders:
                    order.status = OrderStatusEnum.CANCELLED
                    order.exchange_update_time = datetime.now(timezone.utc)
                    logger.info(f"✅ Marked order {order.exchange_order_id} as CANCELLED")
                
                db.commit()
                logger.info(f"\n✅ Successfully marked {len(stale_orders)} orders as CANCELLED")
            else:
                logger.info(f"\n🔍 DRY RUN: Would mark {len(stale_orders)} orders as CANCELLED")
        else:
            logger.info("✅ All database orders exist on exchange - no cleanup needed")
            
    except Exception as e:
        logger.error(f"Error verifying orders: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Verify and cleanup stale orders")
    parser.add_argument("--symbol", "-s", type=str, help="Symbol to check (e.g., BTC_USDT). If not provided, checks all symbols.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without making changes")
    
    args = parser.parse_args()
    
    verify_and_cleanup_stale_orders(symbol=args.symbol, dry_run=args.dry_run)

if __name__ == "__main__":
    main()






