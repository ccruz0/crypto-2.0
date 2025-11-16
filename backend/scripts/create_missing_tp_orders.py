#!/usr/bin/env python3
"""
Script to create missing TP orders for BUY orders that have SL but no active TP.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.tp_sl_order_creator import create_take_profit_order
from app.utils.live_trading import get_live_trading_status
from datetime import datetime, timedelta, timezone
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_tp_price(filled_price: float, watchlist_item: WatchlistItem) -> float:
    """Calculate TP price based on watchlist configuration"""
    from app.api.routes_signals import calculate_stop_loss_and_take_profit
    
    sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
    tp_percentage = watchlist_item.tp_percentage
    atr = watchlist_item.atr or 0
    
    def _default_percentages(mode: str) -> tuple[float, float]:
        if mode == "aggressive":
            return 2.0, 2.0
        return 3.0, 3.0
    
    default_sl_pct, default_tp_pct = _default_percentages(sl_tp_mode)
    effective_tp_pct = abs(tp_percentage) if tp_percentage and tp_percentage > 0 else default_tp_pct
    
    # Calculate TP price
    tp_price = filled_price * (1 + effective_tp_pct / 100)
    
    # Blend with ATR if available
    if atr > 0:
        calculated = calculate_stop_loss_and_take_profit(filled_price, atr)
        if sl_tp_mode == "aggressive":
            atr_tp = calculated["take_profit"]["aggressive"]["value"]
        else:
            atr_tp = calculated["take_profit"]["conservative"]["value"]
        tp_price = max(tp_price, atr_tp)
    
    # Round if necessary
    if filled_price >= 100:
        tp_price = round(tp_price)
    else:
        tp_price = round(tp_price, 4)
    
    return tp_price

def create_missing_tp_orders():
    """Create missing TP orders for BUY orders that have SL but no active TP"""
    db = SessionLocal()
    try:
        # Find recent filled BUY orders
        recent_threshold = datetime.now(timezone.utc) - timedelta(days=2)
        filled_buy_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_create_time >= recent_threshold,
            ExchangeOrder.order_type.in_(["LIMIT", "MARKET"])
        ).order_by(ExchangeOrder.exchange_create_time.desc()).all()
        
        logger.info(f"📊 Found {len(filled_buy_orders)} recent FILLED BUY orders")
        
        orders_needing_tp = []
        
        for order in filled_buy_orders:
            # Check for active SL orders
            sl_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order.exchange_order_id,
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            # Check for active TP orders
            tp_orders_active = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order.exchange_order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            # Check for FILLED TP orders - if TP was already executed, position is closed, don't create new TP
            tp_orders_filled = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order.exchange_order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status == OrderStatusEnum.FILLED
            ).count()
            
            if len(sl_orders) > 0 and len(tp_orders_active) == 0 and tp_orders_filled == 0:
                # Get OCO group ID from SL order if available
                oco_group_id = sl_orders[0].oco_group_id if sl_orders else None
                
                orders_needing_tp.append({
                    "order": order,
                    "sl_orders": sl_orders,
                    "oco_group_id": oco_group_id
                })
        
        logger.info(f"🔍 Found {len(orders_needing_tp)} orders needing TP")
        
        if len(orders_needing_tp) == 0:
            logger.info("✅ No orders need TP creation")
            return
        
        live_trading = get_live_trading_status(db)
        logger.info(f"💰 LIVE_TRADING mode: {live_trading}")
        
        created_count = 0
        failed_count = 0
        
        for item in orders_needing_tp:
            order = item["order"]
            oco_group_id = item["oco_group_id"]
            
            logger.info(f"\n{'='*80}")
            logger.info(f"📋 Processing: {order.symbol} | Order ID: {order.exchange_order_id}")
            
            # Get watchlist item for configuration
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == order.symbol
            ).first()
            
            if not watchlist_item:
                logger.warning(f"⚠️ No watchlist item found for {order.symbol}, skipping")
                failed_count += 1
                continue
            
            # Calculate TP price
            filled_price_raw = order.avg_price or order.price or 0
            filled_qty_raw = order.cumulative_quantity or order.quantity or 0
            
            # Convert to float if Decimal
            filled_price = float(filled_price_raw) if filled_price_raw else 0.0
            filled_qty = float(filled_qty_raw) if filled_qty_raw else 0.0
            
            if filled_price <= 0 or filled_qty <= 0:
                logger.warning(f"⚠️ Invalid price ({filled_price}) or quantity ({filled_qty}) for order {order.exchange_order_id}")
                failed_count += 1
                continue
            
            tp_price = calculate_tp_price(filled_price, watchlist_item)
            
            logger.info(f"   Entry Price: ${filled_price:.4f}")
            logger.info(f"   Quantity: {filled_qty:.8f}")
            logger.info(f"   Calculated TP Price: ${tp_price:.4f}")
            logger.info(f"   OCO Group ID: {oco_group_id or 'None (will create new)'}")
            
            # Create TP order
            try:
                tp_result = create_take_profit_order(
                    db=db,
                    symbol=order.symbol,
                    side="BUY",  # Original order side
                    tp_price=tp_price,
                    quantity=filled_qty,
                    entry_price=filled_price,
                    parent_order_id=order.exchange_order_id,
                    oco_group_id=oco_group_id,
                    dry_run=not live_trading,
                    source="manual_fix"
                )
                
                tp_order_id = tp_result.get("order_id")
                tp_error = tp_result.get("error")
                
                if tp_order_id:
                    logger.info(f"✅ TP order created successfully: {tp_order_id}")
                    created_count += 1
                else:
                    logger.error(f"❌ Failed to create TP order: {tp_error}")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"❌ Error creating TP order: {e}", exc_info=True)
                failed_count += 1
        
        logger.info(f"\n{'='*80}")
        logger.info(f"📊 Summary:")
        logger.info(f"   ✅ Created: {created_count}")
        logger.info(f"   ❌ Failed: {failed_count}")
        logger.info(f"   📋 Total processed: {len(orders_needing_tp)}")
        
    except Exception as e:
        logger.error(f"❌ Error in create_missing_tp_orders: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    create_missing_tp_orders()

