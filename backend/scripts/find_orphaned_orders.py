#!/usr/bin/env python3
"""Script to find orphaned SL/TP orders that should have been cancelled"""
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

def find_orphaned_orders(dry_run: bool = True):
    """
    Find orphaned SL/TP orders that should have been cancelled.
    
    An orphaned order is:
    1. An active SL/TP order whose sibling in the same OCO group is FILLED
    2. An active SL/TP order whose parent order is FILLED but sibling is also FILLED
    
    Args:
        dry_run: If True, only shows what would be cancelled without making changes.
    """
    db = SessionLocal()
    try:
        # Find all active SL/TP orders
        active_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        logger.info(f"Found {len(active_sl_tp)} active SL/TP orders to check")
        
        orphaned_orders = []
        
        for order in active_sl_tp:
            is_orphaned = False
            reason = ""
            
            # Check 1: If order has oco_group_id, check if sibling is FILLED
            if order.oco_group_id:
                siblings = db.query(ExchangeOrder).filter(
                    ExchangeOrder.oco_group_id == order.oco_group_id,
                    ExchangeOrder.exchange_order_id != order.exchange_order_id
                ).all()
                
                for sibling in siblings:
                    if sibling.status == OrderStatusEnum.FILLED:
                        is_orphaned = True
                        reason = f"Sibling {sibling.order_role} order {sibling.exchange_order_id} is FILLED (OCO group: {order.oco_group_id})"
                        break
            
            # Check 2: If order has parent_order_id, check if parent is FILLED
            # AND check if there's a sibling SL/TP that's also FILLED
            if not is_orphaned and order.parent_order_id:
                parent = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order.parent_order_id
                ).first()
                
                if parent and parent.status == OrderStatusEnum.FILLED:
                    # Check if there's a sibling SL/TP order that's FILLED
                    # (meaning this order should have been cancelled)
                    sibling_sl_tp = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == order.parent_order_id,
                        ExchangeOrder.exchange_order_id != order.exchange_order_id,
                        ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).first()
                    
                    if sibling_sl_tp:
                        is_orphaned = True
                        reason = f"Parent order {order.parent_order_id} is FILLED and sibling {sibling_sl_tp.order_role} order {sibling_sl_tp.exchange_order_id} is also FILLED"
            
            if is_orphaned:
                orphaned_orders.append({
                    'order': order,
                    'reason': reason
                })
        
        # Report findings
        logger.info(f"\n{'='*80}")
        logger.info(f"ORPHANED ORDERS ANALYSIS")
        logger.info(f"{'='*80}")
        logger.info(f"Total active SL/TP orders checked: {len(active_sl_tp)}")
        logger.info(f"Orphaned orders found: {len(orphaned_orders)}")
        logger.info(f"{'='*80}\n")
        
        if orphaned_orders:
            logger.info("🔍 ORPHANED ORDERS (should be cancelled):\n")
            for idx, item in enumerate(orphaned_orders, 1):
                order = item['order']
                logger.info(f"{idx}. Order ID: {order.exchange_order_id}")
                logger.info(f"   Symbol: {order.symbol}")
                logger.info(f"   Type: {order.order_type} | Role: {order.order_role}")
                logger.info(f"   Side: {order.side.value if order.side else 'N/A'}")
                logger.info(f"   Price: {order.price} | Qty: {order.quantity}")
                logger.info(f"   Status: {order.status.value}")
                logger.info(f"   Parent Order ID: {order.parent_order_id or 'N/A'}")
                logger.info(f"   OCO Group ID: {order.oco_group_id or 'N/A'}")
                logger.info(f"   Reason: {item['reason']}")
                logger.info(f"   Created: {order.created_at}")
                logger.info("")
            
            if not dry_run:
                logger.info("🔄 Cancelling orphaned orders...")
                cancelled_count = 0
                failed_count = 0
                
                for item in orphaned_orders:
                    order = item['order']
                    try:
                        # Try to cancel on exchange
                        result = trade_client.cancel_order(order.exchange_order_id)
                        
                        if "error" not in result:
                            # Update database
                            order.status = OrderStatusEnum.CANCELLED
                            order.updated_at = datetime.now(timezone.utc)
                            logger.info(f"✅ Cancelled orphaned order {order.exchange_order_id} ({order.symbol})")
                            cancelled_count += 1
                        else:
                            error_msg = result.get('error', 'Unknown error')
                            # Check if order might already be cancelled on exchange
                            if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                                # Mark as cancelled in DB
                                order.status = OrderStatusEnum.CANCELLED
                                order.updated_at = datetime.now(timezone.utc)
                                logger.info(f"✅ Marked orphaned order {order.exchange_order_id} as CANCELLED (not found on exchange)")
                                cancelled_count += 1
                            else:
                                logger.error(f"❌ Failed to cancel order {order.exchange_order_id}: {error_msg}")
                                failed_count += 1
                    except Exception as e:
                        logger.error(f"❌ Error cancelling order {order.exchange_order_id}: {e}")
                        failed_count += 1
                
                db.commit()
                logger.info(f"\n{'='*80}")
                logger.info(f"CANCELLATION SUMMARY:")
                logger.info(f"  Successfully cancelled: {cancelled_count}")
                logger.info(f"  Failed: {failed_count}")
                logger.info(f"{'='*80}\n")
            else:
                logger.info(f"\n🔍 DRY RUN: Would cancel {len(orphaned_orders)} orphaned orders")
                logger.info("Run with --execute to actually cancel these orders\n")
        else:
            logger.info("✅ No orphaned orders found - all active SL/TP orders are valid\n")
            
    except Exception as e:
        logger.error(f"Error finding orphaned orders: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Find and optionally cancel orphaned SL/TP orders")
    parser.add_argument("--execute", action="store_true", help="Actually cancel orphaned orders (default is dry-run)")
    
    args = parser.parse_args()
    
    find_orphaned_orders(dry_run=not args.execute)

if __name__ == "__main__":
    main()

