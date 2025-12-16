#!/usr/bin/env python3
"""
Script to create SL/TP orders with 2% for the most recent filled BTC order
Temporarily enables LIVE_TRADING, creates orders, then disables it
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.models.trading_settings import TradingSettings
from app.services.exchange_sync import exchange_sync_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def set_live_trading(db, enabled: bool):
    """Set LIVE_TRADING in database"""
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == "LIVE_TRADING"
        ).first()
        
        if setting:
            old_value = setting.setting_value
            setting.setting_value = "true" if enabled else "false"
            logger.info(f"Updated LIVE_TRADING: {old_value} → {setting.setting_value}")
        else:
            setting = TradingSettings(
                setting_key="LIVE_TRADING",
                setting_value="true" if enabled else "false"
            )
            db.add(setting)
            logger.info(f"Created LIVE_TRADING setting: {setting.setting_value}")
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting LIVE_TRADING: {e}")
        db.rollback()
        return False

def create_sl_tp_for_order(order_id: str, sl_percentage=2.0, tp_percentage=2.0):
    """Create SL/TP orders for a specific order ID"""
    db = SessionLocal()
    live_trading_was_enabled = None
    
    try:
        # Check current LIVE_TRADING status
        from app.utils.live_trading import get_live_trading_status
        live_trading_was_enabled = get_live_trading_status(db)
        logger.info(f"Current LIVE_TRADING status: {live_trading_was_enabled}")
        
        # Enable LIVE_TRADING in both database and environment
        logger.info("🔴 Enabling LIVE_TRADING...")
        if not set_live_trading(db, True):
            logger.error("Failed to enable LIVE_TRADING")
            return False
        
        # Also set environment variable (trade_client reads from env)
        os.environ['LIVE_TRADING'] = 'true'
        
        # Verify it's enabled
        live_trading_now = get_live_trading_status(db)
        if not live_trading_now:
            logger.error("LIVE_TRADING is still disabled after setting it to true")
            return False
        
        logger.info("✅ LIVE_TRADING enabled successfully (database + environment)")
        
        logger.info(f"Finding order: {order_id}")
        
        # Find the specific order in database
        last_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        # If not in database, try to fetch from exchange
        if not last_order:
            logger.info(f"Order {order_id} not found in database, checking exchange...")
            from app.services.brokers.crypto_com_trade import trade_client
            
            # First check open orders
            try:
                logger.info("Checking open orders...")
                open_orders_result = trade_client.get_open_orders()
                open_orders = open_orders_result.get('data', []) if open_orders_result else []
                
                # Search for the order in open orders
                found_order = None
                for o in open_orders:
                    if str(o.get('order_id', '')) == order_id:
                        found_order = o
                        break
                
                if found_order:
                    logger.info(f"✅ Found order in open orders: {found_order.get('instrument_name')} {found_order.get('side')}")
                    logger.warning(f"⚠️  Order is still OPEN (status: {found_order.get('status')})")
                    logger.warning(f"⚠️  SL/TP can only be created for FILLED orders")
                    logger.info(f"   Please wait for the order to fill, then run this script again")
                    return False
            except Exception as e:
                logger.warning(f"Error checking open orders: {e}")
            
            # Try to sync order history
            try:
                logger.info("Syncing order history from exchange...")
                from app.services.exchange_sync import exchange_sync_service
                exchange_sync_service.sync_order_history(db, page_size=200, max_pages=5)
                
                # Try to find it again
                last_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
            except Exception as e:
                logger.warning(f"Error syncing order history: {e}")
        
        if not last_order:
            logger.error(f"Order {order_id} not found in database and could not be fetched from exchange")
            logger.info("Possible reasons:")
            logger.info("  1. Order ID is incorrect")
            logger.info("  2. Order is very recent and hasn't been synced yet")
            logger.info("  3. Order is still open (not filled) - SL/TP can only be created for FILLED orders")
            logger.info("  4. Backend needs to sync orders from exchange first")
            return False
        
        if last_order.status != OrderStatusEnum.FILLED:
            logger.error(f"Order {order_id} is not FILLED (status: {last_order.status.value})")
            logger.info(f"SL/TP can only be created for FILLED orders")
            return False
        
        symbol = last_order.symbol
        
        logger.info(f"Found order: {last_order.exchange_order_id}")
        logger.info(f"  Symbol: {last_order.symbol}")
        logger.info(f"  Side: {last_order.side.value}")
        logger.info(f"  Status: {last_order.status.value}")
        
        # Check if this order already has SL/TP orders
        existing_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == last_order.exchange_order_id,
            ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if existing_sl_tp:
            logger.warning(f"Order {last_order.exchange_order_id} already has {len(existing_sl_tp)} SL/TP order(s):")
            for order in existing_sl_tp:
                logger.warning(f"  - {order.order_role} ({order.exchange_order_id}) - {order.status.value}")
            
            # Cancel existing SL/TP orders before creating new ones
            logger.info("🗑️  Cancelling existing SL/TP orders...")
            from app.services.brokers.crypto_com_trade import trade_client
            cancelled_count = 0
            for order in existing_sl_tp:
                try:
                    result = trade_client.cancel_order(order.exchange_order_id)
                    if "error" not in result:
                        # Mark as cancelled in database
                        order.status = OrderStatusEnum.CANCELLED
                        cancelled_count += 1
                        logger.info(f"  ✅ Cancelled {order.order_role} order {order.exchange_order_id}")
                    else:
                        logger.warning(f"  ⚠️  Failed to cancel {order.order_role} order {order.exchange_order_id}: {result.get('error')}")
                except Exception as e:
                    logger.error(f"  ❌ Error cancelling {order.order_role} order {order.exchange_order_id}: {e}")
            
            db.commit()
            logger.info(f"✅ Cancelled {cancelled_count}/{len(existing_sl_tp)} existing SL/TP orders")
        
        # Get filled price and quantity
        filled_price = float(last_order.avg_price) if last_order.avg_price else float(last_order.price) if last_order.price else None
        filled_qty = float(last_order.cumulative_quantity) if last_order.cumulative_quantity else float(last_order.quantity) if last_order.quantity else None
        
        if not filled_price or not filled_qty:
            logger.error(f"Cannot create SL/TP: invalid price ({filled_price}) or quantity ({filled_qty})")
            return False
        
        logger.info(f"Order details:")
        logger.info(f"  Filled Price: ${filled_price:.2f}")
        logger.info(f"  Filled Quantity: {filled_qty}")
        
        # Calculate SL/TP prices
        sl_price = filled_price * (1 - sl_percentage / 100)
        tp_price = filled_price * (1 + tp_percentage / 100)
        
        logger.info(f"Calculated SL/TP prices:")
        logger.info(f"  SL: ${sl_price:.2f} ({sl_percentage}% below entry)")
        logger.info(f"  TP: ${tp_price:.2f} ({tp_percentage}% above entry)")
        
        # Create SL/TP orders directly using the order creator functions
        from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
        from app.utils.live_trading import get_live_trading_status
        import uuid
        from datetime import datetime
        
        live_trading = get_live_trading_status(db)
        
        # Generate OCO group ID for linking SL and TP orders
        oco_group_id = f"oco_{last_order.exchange_order_id}_{int(datetime.utcnow().timestamp())}"
        logger.info(f"Creating SL/TP pair with OCO group: {oco_group_id}")
        
        # Determine margin settings from original order
        is_margin = False
        leverage = None
        if hasattr(last_order, 'leverage') and last_order.leverage:
            is_margin = True
            leverage = float(last_order.leverage)
        
        # Create SL order
        logger.info(f"Creating SL order...")
        sl_result = create_stop_loss_order(
            db=db,
            symbol=symbol,
            side=last_order.side.value,
            sl_price=sl_price,
            quantity=filled_qty,
            entry_price=filled_price,
            parent_order_id=last_order.exchange_order_id,
            oco_group_id=oco_group_id,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=not live_trading,
            source="manual"
        )
        sl_order_id = sl_result.get("order_id")
        sl_order_error = sl_result.get("error")
        
        if sl_order_id:
            logger.info(f"✅ SL order created: {sl_order_id}")
        else:
            logger.error(f"❌ SL order creation failed: {sl_order_error}")
        
        # Create TP order
        logger.info(f"Creating TP order...")
        tp_result = create_take_profit_order(
            db=db,
            symbol=symbol,
            side=last_order.side.value,
            tp_price=tp_price,
            quantity=filled_qty,
            entry_price=filled_price,
            parent_order_id=last_order.exchange_order_id,
            oco_group_id=oco_group_id,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=not live_trading,
            source="manual"
        )
        tp_order_id = tp_result.get("order_id")
        tp_order_error = tp_result.get("error")
        
        if tp_order_id:
            logger.info(f"✅ TP order created: {tp_order_id}")
        else:
            logger.error(f"❌ TP order creation failed: {tp_order_error}")
        
        # Verify the orders were created
        new_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == last_order.exchange_order_id,
            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if new_sl_tp:
            logger.info(f"✅ Created {len(new_sl_tp)} SL/TP order(s):")
            for order in new_sl_tp:
                logger.info(f"  - {order.order_role} ({order.exchange_order_id}) - Price: ${float(order.price):.2f}")
            success = True
        else:
            logger.error(f"❌ No SL/TP orders were created. SL error: {sl_order_error}, TP error: {tp_order_error}")
            success = False
        
        # Disable LIVE_TRADING in both database and environment
        logger.info("🟢 Disabling LIVE_TRADING...")
        if live_trading_was_enabled is not None:
            set_live_trading(db, live_trading_was_enabled)
            os.environ['LIVE_TRADING'] = 'true' if live_trading_was_enabled else 'false'
            logger.info(f"✅ LIVE_TRADING restored to: {live_trading_was_enabled}")
        else:
            set_live_trading(db, False)
            os.environ['LIVE_TRADING'] = 'false'
            logger.info("✅ LIVE_TRADING disabled")
        
        return success
            
    except Exception as e:
        logger.exception(f"Error creating SL/TP for BTC order")
        db.rollback()
        # Make sure to disable LIVE_TRADING even on error
        try:
            if live_trading_was_enabled is not None:
                set_live_trading(db, live_trading_was_enabled)
                os.environ['LIVE_TRADING'] = 'true' if live_trading_was_enabled else 'false'
            else:
                set_live_trading(db, False)
                os.environ['LIVE_TRADING'] = 'false'
            logger.info("✅ LIVE_TRADING disabled after error")
        except:
            pass
        return False
    finally:
        db.close()

def create_sl_tp_for_btc(sl_percentage=2.0, tp_percentage=2.0):
    """Create SL/TP orders for the most recent filled BTC order (backward compatibility)"""
    db = SessionLocal()
    try:
        symbol = "BTC_USDT"
        logger.info(f"Finding most recent filled BTC order...")
        
        # Find the last filled BUY order for BTC
        last_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"])
        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not last_order:
            logger.error(f"No filled BUY orders found for {symbol}")
            return False
        
        return create_sl_tp_for_order(last_order.exchange_order_id, sl_percentage, tp_percentage)
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    # Check if order ID provided as argument
    if len(sys.argv) > 1:
        order_id = sys.argv[1]
        logger.info(f"Using provided order ID: {order_id}")
        success = create_sl_tp_for_order(order_id, sl_percentage=2.0, tp_percentage=2.0)
    else:
        logger.info("No order ID provided, finding most recent BTC order...")
        success = create_sl_tp_for_btc(sl_percentage=2.0, tp_percentage=2.0)
    sys.exit(0 if success else 1)


