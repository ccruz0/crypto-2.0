"""Exchange synchronization service
Synchronizes data from Crypto.com Exchange API to the database every 5 seconds
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, not_
from app.database import SessionLocal
from app.models.exchange_balance import ExchangeBalance
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.trade_signal import TradeSignal, SignalStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.open_orders import merge_orders, UnifiedOpenOrder
from app.services.open_orders_cache import store_unified_open_orders, update_open_orders_cache

logger = logging.getLogger(__name__)


class ExchangeSyncService:
    """Service to sync exchange data with database"""
    
    def __init__(self):
        self.is_running = False
        self.sync_interval = 5  # seconds
        self.last_sync: Optional[datetime] = None
        self.processed_order_ids: Dict[str, float] = {}  # Track already processed executed orders {order_id: timestamp}
        self.latest_unified_open_orders: List[UnifiedOpenOrder] = []
    
    def _purge_stale_processed_orders(self):
        """Remove processed order IDs older than 10 minutes"""
        current_time = time.time()
        stale_threshold = 600  # 10 minutes in seconds
        
        stale_ids = [
            order_id for order_id, timestamp in self.processed_order_ids.items()
            if (current_time - timestamp) > stale_threshold
        ]
        
        for order_id in stale_ids:
            del self.processed_order_ids[order_id]
        
        if stale_ids:
            logger.debug(f"Purged {len(stale_ids)} stale processed order IDs")
    
    def _mark_order_processed(self, order_id: str):
        """Mark an order as processed with current timestamp"""
        self.processed_order_ids[order_id] = time.time()
    
    def sync_balances(self, db: Session):
        """Sync account balances from Crypto.com"""
        try:
            # Use portfolio_cache to get REAL balances (not simulated)
            # This avoids the DRY_RUN mode that returns simulated 10k USDT
            from app.services.portfolio_cache import get_portfolio_summary
            
            portfolio_summary = get_portfolio_summary(db)
            
            # Update portfolio cache if empty OR if stale (>60 seconds)
            # This runs in background, so timeouts are OK - it will retry next cycle
            needs_portfolio_update = False
            if not portfolio_summary or not portfolio_summary.get("balances"):
                needs_portfolio_update = True
                logger.info("No cached portfolio data, will update cache from Crypto.com...")
            else:
                last_updated = portfolio_summary.get("last_updated")
                if last_updated:
                    age_seconds = time.time() - last_updated
                    if age_seconds > 60:  # Update if cache is >60 seconds old
                        needs_portfolio_update = True
                        logger.debug(f"Portfolio cache is {age_seconds:.1f}s old, will update...")
            
            if needs_portfolio_update:
                try:
                    from app.services.portfolio_cache import update_portfolio_cache
                    # This may take time but runs in background - OK if it takes 30+ seconds
                    update_result = update_portfolio_cache(db)
                    if update_result.get("success"):
                        portfolio_summary = get_portfolio_summary(db)
                        logger.info(f"✅ Portfolio cache updated: ${update_result.get('total_usd', 0):,.2f}")
                        # Use cached portfolio data (real balances) after successful update
                        accounts = []
                        for balance in portfolio_summary.get("balances", []):
                            accounts.append({
                                'currency': balance['currency'],
                                'balance': str(balance['balance']),
                                'available': str(balance['balance'])  # Use balance as available for now
                            })
                    else:
                        logger.warning("Failed to update portfolio cache, will try direct API call")
                        # Fallback to direct API call
                        # Note: get_account_summary() can raise ValueError or RuntimeError if API credentials are not configured
                        # or if there are authentication/network issues. We need to catch these exceptions.
                        try:
                            response = trade_client.get_account_summary()
                            if not response:
                                logger.warning("No balance data received from Crypto.com")
                                return
                            accounts = []
                            if 'accounts' in response:
                                accounts = response.get('accounts', [])
                            elif 'result' in response:
                                result = response.get('result', {})
                                if 'accounts' in result:
                                    accounts = result.get('accounts', [])
                                elif 'data' in result:
                                    data = result.get('data', [])
                                    if isinstance(data, list) and len(data) > 0:
                                        for item in data:
                                            if 'position_balances' in item:
                                                for balance in item['position_balances']:
                                                    accounts.append({
                                                        'currency': balance.get('instrument_name', ''),
                                                        'balance': balance.get('quantity', '0'),
                                                        'available': balance.get('max_withdrawal_balance', balance.get('quantity', '0'))
                                                    })
                        except (ValueError, RuntimeError) as e:
                            # API credentials not configured or authentication/network error
                            logger.warning(f"Failed to get account summary from API: {e}. Using cached data if available.")
                            # If we have cached data from earlier, continue with that
                            if portfolio_summary and portfolio_summary.get("balances"):
                                logger.info("Using previously cached portfolio data")
                                accounts = []
                                for balance in portfolio_summary.get("balances", []):
                                    accounts.append({
                                        'currency': balance['currency'],
                                        'balance': str(balance['balance']),
                                        'available': str(balance['balance'])
                                    })
                            else:
                                # No cached data available, skip this sync cycle
                                logger.warning("No cached data available, skipping balance sync")
                                return
                        except Exception as e:
                            # Catch any other unexpected exceptions
                            logger.error(f"Unexpected error getting account summary: {e}", exc_info=True)
                            # Try to use cached data if available
                            if portfolio_summary and portfolio_summary.get("balances"):
                                logger.info("Using previously cached portfolio data due to error")
                                accounts = []
                                for balance in portfolio_summary.get("balances", []):
                                    accounts.append({
                                        'currency': balance['currency'],
                                        'balance': str(balance['balance']),
                                        'available': str(balance['balance'])
                                    })
                            else:
                                logger.warning("No cached data available, skipping balance sync")
                                return
                except Exception as try_err:
                    logger.error(f"Error in portfolio update block: {try_err}", exc_info=True)
                    return
            else:
                # Use cached portfolio data (real balances)
                accounts = []
                for balance in portfolio_summary.get("balances", []):
                    accounts.append({
                        'currency': balance['currency'],
                        'balance': str(balance['balance']),
                        'available': str(balance['balance'])  # Use balance as available for now
                    })
            
            if not accounts:
                logger.warning("Empty balance data from Crypto.com")
                return
            
            # Track processed assets
            processed_assets = set()
            
            # Process accounts
            for account in accounts:
                asset = account.get('currency', '').upper()
                if not asset:
                    continue
                
                try:
                    free = float(account.get('available', account.get('balance', '0')))
                    balance_total = float(account.get('balance', '0'))
                    locked = max(0, balance_total - free)
                    total = free + locked
                    
                    # Only sync non-zero balances
                    if total <= 0:
                        continue
                    
                    # Track this asset as processed
                    processed_assets.add(asset)
                    
                    # Upsert balance
                    existing = db.query(ExchangeBalance).filter(
                        ExchangeBalance.asset == asset
                    ).first()
                    
                    if existing:
                        existing.free = free
                        existing.locked = locked
                        existing.total = total
                        existing.updated_at = datetime.utcnow()
                    else:
                        new_balance = ExchangeBalance(
                            asset=asset,
                            free=free,
                            locked=locked,
                            total=total
                        )
                        db.add(new_balance)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error processing balance for {asset}: {e}")
                    continue
            
            # After processing accounts, zero out balances for assets that didn't appear
            if processed_assets:
                orphaned_balances = db.query(ExchangeBalance).filter(
                    not_(ExchangeBalance.asset.in_(list(processed_assets)))
                ).all()
                
                for orphaned in orphaned_balances:
                    orphaned.free = 0
                    orphaned.locked = 0
                    orphaned.total = 0
                    orphaned.updated_at = datetime.now(timezone.utc)
                    logger.debug(f"Zeroed out orphaned balance for asset: {orphaned.asset}")
            
            db.commit()
            logger.info(f"Synced {len(accounts)} account balances")
            
        except Exception as e:
            logger.error(f"Error syncing balances: {e}", exc_info=True)
            db.rollback()
    
    def sync_open_orders(self, db: Session):
        """Sync open orders from Crypto.com"""
        try:
            response = trade_client.get_open_orders()
            # Call get_trigger_orders with default parameters (page=0, page_size=200)
            trigger_response = trade_client.get_trigger_orders(page=0, page_size=200)
            
            # Check if API calls failed before processing
            api_failed = (not response or "data" not in response)
            
            if api_failed:
                logger.warning("No open orders data received from Crypto.com - preserving existing cache")
                # Don't update cache with empty data - preserve last valid cached data
                return
            
            orders = response.get("data", [])
            trigger_orders = trigger_response.get("data", []) if trigger_response else []

            unified_orders = merge_orders(orders, trigger_orders)
            # Only update cache if we have valid data
            if unified_orders or orders or trigger_orders:
                update_open_orders_cache(unified_orders)
            
            # Mark orders not in response as cancelled/closed
            # Include both regular orders and trigger orders in the check
            all_exchange_order_ids = set()
            if orders:
                all_exchange_order_ids.update(order.get('order_id') for order in orders if order.get('order_id'))
            if trigger_orders:
                all_exchange_order_ids.update(order.get('order_id') for order in trigger_orders if order.get('order_id'))
            
            if all_exchange_order_ids or orders or trigger_orders:  # Check even if exchange returns empty list
                existing_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.exchange_order_id.notin_(all_exchange_order_ids),
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                    )
                ).all()
                
                for order in existing_orders:
                    # Check if order is filled in history (might have been filled between syncs)
                    # For MARKET orders, they may execute immediately and not appear in open orders
                    # Check order history first before marking as cancelled
                    filled_order = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.exchange_order_id == order.exchange_order_id,
                            ExchangeOrder.status == OrderStatusEnum.FILLED
                        )
                    ).first()
                    
                    if not filled_order:
                        # For MARKET orders, check if they were immediately filled by looking at order history
                        # MARKET orders typically execute immediately and may not appear in open_orders
                        if order.order_type == "MARKET":
                            # Don't mark MARKET orders as CANCELLED immediately - let order history sync determine status
                            logger.debug(f"MARKET order {order.exchange_order_id} ({order.symbol}) not in open orders - will check history on next sync")
                            continue
                        
                        # For LIMIT orders, mark as CANCELLED if not found in open orders or history
                        order.status = OrderStatusEnum.CANCELLED
                        order.exchange_update_time = datetime.now(timezone.utc)
                        logger.info(f"Order {order.exchange_order_id} ({order.symbol}) marked as CANCELLED - not found in open orders")
                    else:
                        logger.debug(f"Order {order.exchange_order_id} is FILLED, skipping cancellation")
            
            # Upsert orders from response
            for order_data in orders:
                order_id = order_data.get('order_id')
                if not order_id:
                    continue
                
                symbol = order_data.get('instrument_name', '')
                side = order_data.get('side', '').upper()
                status_str = order_data.get('status', '').upper()
                
                # Parse timestamps
                create_time = None
                update_time = None
                if order_data.get('create_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        create_time = datetime.fromtimestamp(order_data['create_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                if order_data.get('update_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        update_time = datetime.fromtimestamp(order_data['update_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                
                # Map status
                status_map = {
                    'NEW': OrderStatusEnum.NEW,
                    'ACTIVE': OrderStatusEnum.ACTIVE,
                    'PARTIALLY_FILLED': OrderStatusEnum.PARTIALLY_FILLED,
                    'FILLED': OrderStatusEnum.FILLED,
                    'CANCELLED': OrderStatusEnum.CANCELLED,
                    'REJECTED': OrderStatusEnum.REJECTED,
                    'EXPIRED': OrderStatusEnum.EXPIRED,
                }
                status = status_map.get(status_str, OrderStatusEnum.NEW)
                
                # Get price from limit_price (primary) or price (fallback)
                # Crypto.com API uses 'limit_price' for limit orders
                order_price = order_data.get('limit_price') or order_data.get('price')
                order_price_float = float(order_price) if order_price else None
                
                # Upsert order
                existing = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
                
                if existing:
                    existing.symbol = symbol
                    existing.side = OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL
                    existing.status = status
                    existing.price = order_price_float
                    existing.quantity = float(order_data.get('quantity', 0)) if order_data.get('quantity') else 0
                    existing.cumulative_quantity = float(order_data.get('cumulative_quantity', 0)) if order_data.get('cumulative_quantity') else 0
                    existing.cumulative_value = float(order_data.get('cumulative_value', 0)) if order_data.get('cumulative_value') else 0
                    existing.avg_price = float(order_data.get('avg_price')) if order_data.get('avg_price') else None
                    existing.exchange_create_time = create_time
                    existing.exchange_update_time = update_time
                    existing.updated_at = datetime.utcnow()
                    
                    # Auto-cancel REJECTED TP orders (they should be removed automatically)
                    if status == OrderStatusEnum.REJECTED:
                        order_type_upper = order_data.get('order_type', '').upper()
                        # Check if it's a TP order (TAKE_PROFIT_LIMIT or TAKE_PROFIT)
                        if 'TAKE_PROFIT' in order_type_upper or existing.order_role == 'TAKE_PROFIT':
                            from app.utils.live_trading import get_live_trading_status
                            live_trading = get_live_trading_status(db)
                            
                            if not live_trading:
                                logger.info(f"DRY_RUN: Would cancel REJECTED TP order {order_id} ({symbol})")
                            else:
                                try:
                                    # Try to cancel the order on the exchange (in case it's still there)
                                    cancel_result = trade_client.cancel_order(order_id)
                                    logger.info(f"✅ Cancelled REJECTED TP order {order_id} ({symbol}) on exchange")
                                except Exception as cancel_err:
                                    logger.warning(f"⚠️ Could not cancel REJECTED TP order {order_id} on exchange (may already be cancelled): {cancel_err}")
                            
                            logger.info(f"🗑️ REJECTED TP order {order_id} ({symbol}) detected - marked for cleanup")
                else:
                    new_order = ExchangeOrder(
                        exchange_order_id=order_id,
                        client_oid=order_data.get('client_oid'),
                        symbol=symbol,
                        side=OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL,
                        order_type=order_data.get('order_type', 'LIMIT'),
                        status=status,
                        price=order_price_float,
                        quantity=float(order_data.get('quantity', 0)) if order_data.get('quantity') else 0,
                        cumulative_quantity=float(order_data.get('cumulative_quantity', 0)) if order_data.get('cumulative_quantity') else 0,
                        cumulative_value=float(order_data.get('cumulative_value', 0)) if order_data.get('cumulative_value') else 0,
                        avg_price=float(order_data.get('avg_price')) if order_data.get('avg_price') else None,
                        exchange_create_time=create_time,
                        exchange_update_time=update_time
                    )
                    db.add(new_order)
                
                # Update trade signal status if linked
                if order_id:
                    signal = db.query(TradeSignal).filter(
                        TradeSignal.exchange_order_id == order_id
                    ).first()
                    
                    if signal:
                        if status == OrderStatusEnum.FILLED:
                            signal.status = SignalStatusEnum.FILLED
                        elif status in [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]:
                            signal.status = SignalStatusEnum.ORDER_PLACED
                        signal.last_update_at = datetime.utcnow()
            
            db.commit()
            logger.info(f"Synced {len(orders)} open orders")
            
        except Exception as e:
            logger.error(f"Error syncing open orders: {e}", exc_info=True)
            db.rollback()
    
    def _cancel_oco_sibling(self, db: Session, filled_order: 'ExchangeOrder'):
        """Cancel the sibling order in an OCO group when one is FILLED"""
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from app.services.brokers.crypto_com_trade import trade_client
            from app.services.telegram_notifier import telegram_notifier
            
            # Find the sibling order in the same OCO group
            sibling = db.query(ExchangeOrder).filter(
                ExchangeOrder.oco_group_id == filled_order.oco_group_id,
                ExchangeOrder.exchange_order_id != filled_order.exchange_order_id,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()
            
            if not sibling:
                logger.debug(f"OCO: No active sibling found for {filled_order.exchange_order_id} in group {filled_order.oco_group_id}")
                return
            
            logger.info(f"🔄 OCO: Cancelling sibling {sibling.order_role} order {sibling.exchange_order_id} (filled order: {filled_order.order_role})")
            
            # Cancel the sibling order
            result = trade_client.cancel_order(sibling.exchange_order_id)
            
            if "error" not in result:
                # Update database
                sibling.status = OrderStatusEnum.CANCELLED
                sibling.updated_at = datetime.utcnow()
                db.commit()
                
                logger.info(f"✅ OCO: Cancelled {sibling.order_role} order {sibling.exchange_order_id}")
                
                # Send detailed Telegram notification
                try:
                    from datetime import timezone
                    from app.services.telegram_notifier import telegram_notifier
                    
                    # Get filled order details
                    filled_order_type = filled_order.order_type or "UNKNOWN"
                    # For FILLED orders, prioritize avg_price (actual execution price) over price (limit/trigger price)
                    filled_order_price = filled_order.avg_price or filled_order.price or 0
                    filled_order_qty = filled_order.quantity or filled_order.cumulative_quantity or 0
                    filled_order_time = filled_order.exchange_update_time or filled_order.updated_at
                    
                    # Get cancelled order details
                    cancelled_order_type = sibling.order_type or "UNKNOWN"
                    cancelled_order_price = sibling.price or 0
                    cancelled_order_qty = sibling.quantity or 0
                    cancelled_order_time = datetime.now(timezone.utc)
                    
                    # Format times
                    filled_time_str = filled_order_time.strftime("%Y-%m-%d %H:%M:%S UTC") if filled_order_time else "N/A"
                    cancelled_time_str = cancelled_order_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                    
                    # Calculate profit/loss if possible (for both TP and SL orders)
                    pnl_info = ""
                    if filled_order.parent_order_id:
                        # Try to find parent order for P/L calculation
                        parent_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == filled_order.parent_order_id
                        ).first()
                        if parent_order:
                            entry_price = parent_order.avg_price or parent_order.price or 0
                            parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                            
                            if entry_price > 0 and filled_order_price > 0 and filled_order_qty > 0:
                                # Calculate profit/loss based on parent order side
                                if parent_side == "BUY":
                                    # For BUY orders: profit if exit > entry, loss if exit < entry
                                    pnl_usd = (filled_order_price - entry_price) * filled_order_qty
                                    pnl_pct = ((filled_order_price - entry_price) / entry_price) * 100
                                else:  # SELL (short position)
                                    # For SELL orders: profit if exit < entry, loss if exit > entry
                                    pnl_usd = (entry_price - filled_order_price) * filled_order_qty
                                    pnl_pct = ((entry_price - filled_order_price) / entry_price) * 100
                                
                                # Format profit/loss with emoji and sign
                                if pnl_usd >= 0:
                                    pnl_emoji = "💰"
                                    pnl_label = "Profit"
                                else:
                                    pnl_emoji = "💸"
                                    pnl_label = "Loss"
                                
                                pnl_info = (
                                    f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                                    f"   💵 Entry: ${entry_price:,.4f} → Exit: ${filled_order_price:,.4f}"
                                )
                    
                    message = (
                        f"🔄 <b>OCO: Order Cancelled</b>\n\n"
                        f"📊 Symbol: <b>{sibling.symbol}</b>\n"
                        f"🔗 OCO Group ID: <code>{filled_order.oco_group_id}</code>\n\n"
                        f"✅ <b>Filled Order:</b>\n"
                        f"   🎯 Type: {filled_order_type}\n"
                        f"   📋 Role: {filled_order.order_role or 'N/A'}\n"
                        f"   💵 Price: ${filled_order_price:.4f}\n"
                        f"   📦 Quantity: {filled_order_qty:.8f}\n"
                        f"   ⏰ Time: {filled_time_str}\n"
                        f"{pnl_info}\n"
                        f"❌ <b>Cancelled Order:</b>\n"
                        f"   🎯 Type: {cancelled_order_type}\n"
                        f"   📋 Role: {sibling.order_role or 'N/A'}\n"
                        f"   💵 Price: ${cancelled_order_price:.4f}\n"
                        f"   📦 Quantity: {cancelled_order_qty:.8f}\n"
                        f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                        f"📋 Order IDs:\n"
                        f"   ✅ Filled: <code>{filled_order.exchange_order_id}</code>\n"
                        f"   ❌ Cancelled: <code>{sibling.exchange_order_id}</code>\n\n"
                        f"💡 <b>Reason:</b> One-Cancels-Other (OCO) - When one protection order is filled, the other is automatically cancelled to prevent double execution."
                    )
                    
                    telegram_notifier.send_message(message)
                    logger.info(f"Sent detailed OCO cancellation notification for {sibling.symbol}")
                except Exception as tg_err:
                    logger.warning(f"Failed to send OCO notification: {tg_err}", exc_info=True)
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ OCO: Failed to cancel sibling order {sibling.exchange_order_id}: {error_msg}")
                
                # Send error notification to Telegram
                try:
                    from app.services.telegram_notifier import telegram_notifier
                    telegram_notifier.send_message(
                        f"⚠️ <b>OCO: Cancellation Failed</b>\n\n"
                        f"📊 Symbol: <b>{sibling.symbol}</b>\n"
                        f"🎯 Filled Order: {filled_order.order_role} ({filled_order.exchange_order_id})\n"
                        f"❌ Failed to Cancel: {sibling.order_role} ({sibling.exchange_order_id})\n"
                        f"🔗 OCO Group: <code>{filled_order.oco_group_id}</code>\n\n"
                        f"❌ Error: {error_msg}\n\n"
                        f"⚠️ Please cancel the remaining {sibling.order_role} order manually."
                    )
                except Exception as tg_err:
                    logger.warning(f"Failed to send OCO error notification: {tg_err}")
        
        except Exception as e:
            logger.error(f"❌ OCO: Error cancelling sibling order: {e}", exc_info=True)
    
    def _create_sl_tp_for_filled_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        filled_price: float,
        filled_qty: float,
        order_id: str
    ):
        """Create SL and TP orders automatically when a LIMIT or MARKET order is filled"""
        from app.models.watchlist import WatchlistItem
        from app.api.routes_signals import calculate_stop_loss_and_take_profit
        
        if not filled_price or filled_qty <= 0:
            logger.warning(f"Cannot create SL/TP for order {order_id}: invalid price ({filled_price}) or quantity ({filled_qty})")
            return
        
        # CRITICAL: First check if SL/TP already exist for this order (quick check before lock)
        # This prevents duplicate creation even if the function is called multiple times
        existing_sl_tp_check = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED, OrderStatusEnum.FILLED])
        ).count()
        
        if existing_sl_tp_check > 0:
            logger.info(
                f"⚠️ SL/TP orders already exist for order {order_id} ({symbol}): found {existing_sl_tp_check} existing order(s). "
                f"Skipping duplicate creation."
            )
            return
        
        # CRITICAL: Use a database-level lock to prevent concurrent SL/TP creation for the same order
        # This prevents race conditions where multiple calls create SL/TP simultaneously
        import time
        lock_key = f"sl_tp_creation_{order_id}"
        lock_timeout = 30  # 30 seconds timeout
        
        # Check if we're already creating SL/TP for this order (in-memory lock)
        if hasattr(self, '_sl_tp_creation_locks'):
            if lock_key in self._sl_tp_creation_locks:
                lock_timestamp = self._sl_tp_creation_locks[lock_key]
                if time.time() - lock_timestamp < lock_timeout:
                    logger.warning(
                        f"🚫 BLOCKED: SL/TP creation already in progress for order {order_id} ({symbol}). "
                        f"Skipping to prevent duplicate creation."
                    )
                    return
                else:
                    # Lock expired, remove it
                    del self._sl_tp_creation_locks[lock_key]
        else:
            self._sl_tp_creation_locks = {}
        
        # Set lock
        self._sl_tp_creation_locks[lock_key] = time.time()
        
        try:
            # CRITICAL: Sync open orders from exchange FIRST to get latest status
            # This ensures we see any orders that were created/rejected on the exchange
            # but not yet in our database
            try:
                logger.info(f"🔄 Syncing open orders from exchange before creating SL/TP for {symbol} order {order_id}")
                # sync_open_orders is a regular sync method, not async
                self.sync_open_orders(db)
                logger.info(f"✅ Open orders synced successfully")
            except Exception as sync_err:
                logger.warning(f"⚠️ Failed to sync open orders before creating SL/TP: {sync_err}. Continuing with database check only.")
            
            # CRITICAL: Force database refresh to see any orders that might have been created
            # between the sync and this check
            db.expire_all()
            
            # IMPORTANT: Check if SL/TP orders already exist for this parent order to avoid duplicates
            # Check for ACTIVE orders (NEW, ACTIVE, PARTIALLY_FILLED)
            existing_sl_active = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).first()
            
            existing_tp_active = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()  # Use .all() to check for multiple TP orders
            
            # Also check for REJECTED orders - if a TP was rejected, don't try to create another
            # This prevents the DUPLICATE_CLORDID error 204
            existing_tp_rejected = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status == OrderStatusEnum.REJECTED
            ).first()
            
            # Also check for RECENT REJECTED TP orders for this symbol (last 10 minutes)
            # If a TP was recently rejected, don't try to create another immediately
            # This prevents rapid-fire creation attempts that all get rejected
            from datetime import timedelta, timezone
            recent_rejected_threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
            recent_rejected_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status == OrderStatusEnum.REJECTED,
                ExchangeOrder.created_at >= recent_rejected_threshold
            ).first()
            
            if existing_sl_active or len(existing_tp_active) > 0:
                logger.info(
                    f"⚠️ SL/TP orders already exist (ACTIVE) for order {order_id} ({symbol}): "
                    f"SL={'exists' if existing_sl_active else 'none'}, TP={len(existing_tp_active)} order(s). "
                    f"Skipping duplicate creation to avoid REJECTED orders."
                )
                if len(existing_tp_active) > 1:
                    logger.warning(
                        f"⚠️ WARNING: Found {len(existing_tp_active)} TP orders for order {order_id} ({symbol})! "
                        f"This indicates duplicate creation. TP IDs: {[tp.exchange_order_id for tp in existing_tp_active]}"
                    )
                return
            
            if existing_tp_rejected:
                logger.warning(
                    f"⚠️ TP order was REJECTED for order {order_id} ({symbol}). "
                    f"Not creating another TP to avoid DUPLICATE_CLORDID error. "
                    f"Rejected TP order ID: {existing_tp_rejected.exchange_order_id}"
                )
                return
            
            if recent_rejected_tp:
                logger.warning(
                    f"⚠️ Recent REJECTED TP order exists for {symbol} (created {recent_rejected_tp.created_at}): "
                    f"TP order ID: {recent_rejected_tp.exchange_order_id}, "
                    f"Parent: {recent_rejected_tp.parent_order_id}. "
                    f"Not creating another TP immediately to avoid repeated REJECTED orders. "
                    f"Will retry after cooldown period."
                )
                return
        finally:
            # Always remove lock when done (even if we return early)
            if hasattr(self, '_sl_tp_creation_locks') and lock_key in self._sl_tp_creation_locks:
                del self._sl_tp_creation_locks[lock_key]
        
        # Log the quantity being used for SL/TP
        logger.info(f"Creating SL/TP for {symbol} order {order_id}: filled_price={filled_price}, filled_qty={filled_qty}")
        
        # Get coin configuration from watchlist
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            logger.info(f"No watchlist item found for {symbol}, creating one with default settings for SL/TP creation")
            # Create a temporary watchlist_item with default conservative settings
            watchlist_item = WatchlistItem(
                symbol=symbol,
                exchange="CRYPTO_COM",
                sl_tp_mode="conservative",
                trade_enabled=True,  # Enable trading to allow SL/TP creation
                is_deleted=False
            )
            db.add(watchlist_item)
            db.commit()
            db.refresh(watchlist_item)
            logger.info(f"✅ Created temporary watchlist_item for {symbol} with conservative SL/TP settings")
        
        # CRITICAL: Check if trading is enabled for this symbol before creating SL/TP orders
        # This prevents creating orders when trade_enabled=False
        if not getattr(watchlist_item, 'trade_enabled', False):
            logger.info(
                f"🚫 SL/TP creation blocked for {symbol} order {order_id}: "
                f"trade_enabled=False. Trading is disabled for this symbol."
            )
            return
        
        # CRITICAL: Determine margin mode and leverage for SL/TP orders
        # SL/TP should match the original order's margin mode and leverage
        # First, try to get the original order's leverage from the database
        original_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        # Check if original order was placed with margin
        original_is_margin = False
        original_leverage = None
        
        if original_order:
            # Try to determine if original order was margin from order data
            # Check if order has leverage field or if we can infer from order_type
            if hasattr(original_order, 'leverage') and original_order.leverage:
                original_leverage = float(original_order.leverage)
                original_is_margin = True
            # If no leverage field, check watchlist setting (fallback)
            elif watchlist_item.trade_on_margin:
                original_is_margin = True
                # We don't know the original leverage, so we'll use margin decision helper
        
        # Use margin decision helper to determine correct leverage for this symbol
        # This ensures we never request leverage higher than max allowed
        from app.services.margin_decision_helper import decide_trading_mode, log_margin_decision, DEFAULT_CONFIGURED_LEVERAGE
        
        # If we know the original order's leverage, use it (but still validate against max)
        if original_is_margin and original_leverage:
            # Validate the original leverage is still valid for this symbol
            trading_decision = decide_trading_mode(
                symbol=symbol,
                configured_leverage=original_leverage,  # Use original leverage as configured
                user_wants_margin=True
            )
            # If the decision says to use margin, use the original leverage (or adjusted if needed)
            if trading_decision.use_margin:
                is_margin = True
                leverage = trading_decision.leverage  # This will be min(original_leverage, max_allowed)
            else:
                # Original leverage is no longer valid, fall back to SPOT
                is_margin = False
                leverage = None
        else:
            # No original order info or original was SPOT - use watchlist setting with margin decision
            trading_decision = decide_trading_mode(
                symbol=symbol,
                configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
                user_wants_margin=watchlist_item.trade_on_margin or False
            )
            is_margin = trading_decision.use_margin
            leverage = trading_decision.leverage
        
        # Log the decision for debugging
        log_margin_decision(symbol, trading_decision, original_leverage or DEFAULT_CONFIGURED_LEVERAGE)
        
        logger.info(
            f"SL/TP margin settings for {symbol} order {order_id}: "
            f"original_is_margin={original_is_margin}, original_leverage={original_leverage}, "
            f"final_is_margin={is_margin}, final_leverage={leverage}"
        )
        
        # Dynamically derive SL/TP based on strategy so they always follow the latest fill price
        sl_tp_mode = (watchlist_item.sl_tp_mode or "conservative").lower()
        sl_percentage = watchlist_item.sl_percentage
        tp_percentage = watchlist_item.tp_percentage
        atr = watchlist_item.atr or 0

        def _default_percentages(mode: str) -> tuple[float, float]:
            if mode == "aggressive":
                return 2.0, 2.0  # tighter stops/targets
            return 3.0, 3.0  # conservative baseline

        default_sl_pct, default_tp_pct = _default_percentages(sl_tp_mode)
        effective_sl_pct = abs(sl_percentage) if sl_percentage and sl_percentage > 0 else default_sl_pct
        effective_tp_pct = abs(tp_percentage) if tp_percentage and tp_percentage > 0 else default_tp_pct

        if side == "BUY":
            sl_price = filled_price * (1 - effective_sl_pct / 100)
            tp_price = filled_price * (1 + effective_tp_pct / 100)
        else:
            sl_price = filled_price * (1 + effective_sl_pct / 100)
            tp_price = filled_price * (1 - effective_tp_pct / 100)

        # Blend with ATR-based levels if ATR is available (gives strategy-derived safety margins)
        if atr > 0:
            calculated = calculate_stop_loss_and_take_profit(filled_price, atr)
            if sl_tp_mode == "aggressive":
                atr_sl = calculated["stop_loss"]["aggressive"]["value"]
                atr_tp = calculated["take_profit"]["aggressive"]["value"]
            else:
                atr_sl = calculated["stop_loss"]["conservative"]["value"]
                atr_tp = calculated["take_profit"]["conservative"]["value"]

            if side == "BUY":
                sl_price = min(sl_price, atr_sl)
                tp_price = max(tp_price, atr_tp)
            else:
                sl_price = max(sl_price, atr_sl)
                tp_price = min(tp_price, atr_tp)

        logger.info(
            f"✅ Calculated SL/TP dynamically for {symbol} order {order_id}: "
            f"SL={sl_price} (pct={effective_sl_pct}%), TP={tp_price} (pct={effective_tp_pct}%), mode={sl_tp_mode}, ATR={atr}"
        )

        # Persist the calculated values back to the watchlist for dashboard consistency
        # IMPORTANT: Only persist sl_price and tp_price (calculated prices), NOT the percentages
        # The percentages should only be persisted if the user explicitly set them
        # If the user deleted them (None), we should NOT overwrite with calculated defaults
        watchlist_item.sl_price = sl_price
        watchlist_item.tp_price = tp_price
        # Only update percentages if they were explicitly set by the user (not None)
        # This prevents overwriting user-deleted values with calculated defaults
        if sl_percentage is not None:
            watchlist_item.sl_percentage = effective_sl_pct
        if tp_percentage is not None:
            watchlist_item.tp_percentage = effective_tp_pct
        try:
            db.commit()
        except Exception as persist_err:
            logger.warning(f"Failed to persist dynamic SL/TP to watchlist for {symbol}: {persist_err}")
            db.rollback()

        # Round values if necessary (post-persistence) to match exchange requirements
            if filled_price >= 100:
                sl_price = round(sl_price)
                tp_price = round(tp_price)
            else:
                sl_price = round(sl_price, 4)
                tp_price = round(tp_price, 4)
        
        from app.utils.live_trading import get_live_trading_status
        live_trading = get_live_trading_status(db)
        
        # Generate OCO group ID for linking SL and TP orders
        import uuid
        oco_group_id = f"oco_{order_id}_{int(datetime.utcnow().timestamp())}"
        logger.info(f"Creating SL/TP pair with OCO group: {oco_group_id}")
        
        # Use the reusable TP/SL order creator functions
        from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
        
        # Create SL order using shared logic
        sl_result = create_stop_loss_order(
            db=db,
            symbol=symbol,
            side=side,
            sl_price=sl_price,
            quantity=filled_qty,
            entry_price=filled_price,
            parent_order_id=order_id,
            oco_group_id=oco_group_id,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=not live_trading,
            source="auto"
        )
        sl_order_id = sl_result.get("order_id")
        sl_order_error = sl_result.get("error")
        
        # Log SL order result
        if sl_order_id:
            logger.info(f"✅ SL order created successfully for {symbol} order {order_id}: order_id={sl_order_id}")
        else:
            logger.error(f"❌ SL order creation failed for {symbol} order {order_id}: {sl_order_error}")
        
        # Create TP order using shared logic
        tp_result = create_take_profit_order(
            db=db,
            symbol=symbol,
            side=side,
            tp_price=tp_price,
            quantity=filled_qty,
            entry_price=filled_price,
            parent_order_id=order_id,
            oco_group_id=oco_group_id,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=not live_trading,
            source="auto"
        )
        tp_order_id = tp_result.get("order_id")
        tp_order_error = tp_result.get("error")
        
        # Log TP order result
        if tp_order_id:
            logger.info(f"✅ TP order created successfully for {symbol} order {order_id}: order_id={tp_order_id}")
        else:
            logger.error(f"❌ TP order creation failed for {symbol} order {order_id}: {tp_order_error}")
        
        # Log detailed error information if both failed
        if not sl_order_id and not tp_order_id:
            logger.error(f"❌ BOTH SL/TP orders failed for {symbol} order {order_id}:")
            logger.error(f"   SL Error: {sl_order_error}")
            logger.error(f"   TP Error: {tp_order_error}")
            logger.error(f"   Parameters used:")
            logger.error(f"     - Symbol: {symbol}")
            logger.error(f"     - Side: {side} (original order side)")
            logger.error(f"     - Entry Price: {filled_price}")
            logger.error(f"     - Filled Quantity: {filled_qty}")
            logger.error(f"     - SL Price: {sl_price}")
            logger.error(f"     - TP Price: {tp_price}")
            logger.error(f"     - Live Trading: {live_trading}")
            logger.error(f"     - Source: auto")
        
        # Send Telegram notification when SL/TP orders are created (ALWAYS, even if orders failed)
        # Always send Telegram notifications (even if alert_enabled is false for that coin)
        try:
            from app.services.telegram_notifier import telegram_notifier
            
            # If orders failed, send error notification with detailed error messages
            if not sl_order_id and not tp_order_id and live_trading:
                # Build detailed error message
                error_details = []
                if sl_order_error:
                    error_details.append(f"SL: {sl_order_error}")
                if tp_order_error:
                    error_details.append(f"TP: {tp_order_error}")
                error_summary = " | ".join(error_details) if error_details else "Unknown error"
                
                telegram_notifier.send_message(
                    f"⚠️ <b>SL/TP ORDER CREATION FAILED</b>\n\n"
                    f"📊 Symbol: <b>{symbol}</b>\n"
                    f"📋 Order ID: {order_id}\n"
                    f"💵 Filled Price: ${filled_price:.2f}\n"
                    f"📦 Quantity: {filled_qty}\n"
                    f"🔴 SL Price: ${sl_price:.2f}\n"
                    f"🟢 TP Price: ${tp_price:.2f}\n"
                    f"❌ Error: {error_summary}\n\n"
                    f"Por favor revisa los logs del backend para más detalles."
                )
                logger.warning(f"SL/TP orders failed for {symbol} order {order_id} - sent error notification to Telegram: {error_summary}")
            else:
                # Send normal notification if at least one order succeeded or in DRY_RUN mode
                # Determine SL/TP sides for clarity in Telegram message
                sl_side_for_tp = "SELL" if side == "BUY" else "BUY"  # SL is opposite of original order
                tp_side_for_tp = "SELL" if side == "BUY" else "BUY"  # TP is opposite of original order
                
                # Get trigger and ref prices from the orders if available
                sl_trigger_from_order = sl_price  # trigger_price should equal sl_price
                # TP is now a LIMIT order (not TAKE_PROFIT_LIMIT), so no trigger_price needed
                tp_trigger_from_order = tp_price  # For LIMIT orders, price is the limit price
                sl_ref_from_order = sl_price  # ref_price should equal sl_price (trigger_price)
                
                # Always send notification, even if one order failed
                result = telegram_notifier.send_sl_tp_orders(
                    symbol=symbol,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    quantity=filled_qty,
                    mode=sl_tp_mode,
                    sl_order_id=str(sl_order_id) if sl_order_id else None,
                    tp_order_id=str(tp_order_id) if tp_order_id else None,
                    original_order_id=order_id,
                    sl_side=sl_side_for_tp,  # Add SL side (SELL for BUY orders, BUY for SELL orders)
                    tp_side=tp_side_for_tp,  # Add TP side (SELL for BUY orders, BUY for SELL orders)
                    entry_price=filled_price,  # Add entry price for profit/loss calculation
                    sl_trigger_price=sl_trigger_from_order,  # Add SL trigger price for verification
                    tp_trigger_price=tp_trigger_from_order,  # Add TP limit price (for LIMIT order, not TAKE_PROFIT_LIMIT)
                    sl_ref_price=sl_ref_from_order,  # Add SL ref price for verification
                    sl_percentage=effective_sl_pct,  # Add SL percentage for strategy display
                    tp_percentage=effective_tp_pct,  # Add TP percentage for strategy display
                    original_order_side=side  # Add original order side for correct profit/loss calculation
                )
                if result:
                    logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                else:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
        except Exception as telegram_err:
            logger.error(f"❌ Exception sending Telegram notification for SL/TP: {telegram_err}", exc_info=True)
    
    def _cancel_remaining_sl_tp(self, db: Session, symbol: str, executed_order_type: str, executed_order_id: str):
        """Cancel the remaining SL or TP order when one is executed"""
        try:
            # Determine which order type we need to cancel
            if executed_order_type.upper() == 'STOP_LIMIT':
                # If SL was executed, cancel TP
                target_order_type = 'TAKE_PROFIT_LIMIT'
            elif executed_order_type.upper() == 'TAKE_PROFIT_LIMIT':
                # If TP was executed, cancel SL
                target_order_type = 'STOP_LIMIT'
            else:
                return 0  # Not a SL/TP order
            
            # Get executed order to find parent_order_id and order_role
            executed_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == executed_order_id
            ).first()
            
            # Find open SL/TP orders of the opposite type for the same symbol
            # Try multiple strategies to find the matching SL/TP order:
            # 1. By parent_order_id (if both SL/TP share the same parent)
            # 2. By order_role (STOP_LOSS/TAKE_PROFIT) if available
            # 3. By symbol + order_type + similar creation time (fallback)
            target_orders = []
            
            # Strategy 1: Find by parent_order_id (most reliable)
            if executed_order and executed_order.parent_order_id:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.parent_order_id == executed_order.parent_order_id,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                        ExchangeOrder.exchange_order_id != executed_order_id
                    )
                ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} {target_order_type} orders by parent_order_id {executed_order.parent_order_id}")
            
            # Strategy 2: Find by order_role if Strategy 1 didn't find anything
            if not target_orders and executed_order:
                # Determine target order_role based on executed order's order_role or order_type
                if executed_order.order_role:
                    if executed_order.order_role == "STOP_LOSS":
                        target_role = "TAKE_PROFIT"
                    elif executed_order.order_role == "TAKE_PROFIT":
                        target_role = "STOP_LOSS"
                    else:
                        target_role = None
                else:
                    # Infer from order_type
                    if executed_order_type.upper() == 'STOP_LIMIT':
                        target_role = "TAKE_PROFIT"
                    else:
                        target_role = "STOP_LOSS"
                
                if target_role:
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_role == target_role,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by order_role {target_role}")
            
            # Strategy 3: Find by symbol + order_type + similar creation time (fallback)
            if not target_orders and executed_order:
                # Look for orders created around the same time (within 5 minutes of the executed order)
                if executed_order.exchange_create_time:
                    from datetime import timedelta
                    time_window_start = executed_order.exchange_create_time - timedelta(minutes=5)
                    time_window_end = executed_order.exchange_create_time + timedelta(minutes=5)
                    
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id,
                            ExchangeOrder.exchange_create_time >= time_window_start,
                            ExchangeOrder.exchange_create_time <= time_window_end
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type + time window")
                elif executed_order.created_at:
                    # Fallback to created_at if exchange_create_time is not available
                    from datetime import timedelta
                    time_window_start = executed_order.created_at - timedelta(minutes=5)
                    time_window_end = executed_order.created_at + timedelta(minutes=5)
                    
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                            ExchangeOrder.exchange_order_id != executed_order_id,
                            ExchangeOrder.created_at >= time_window_start,
                            ExchangeOrder.created_at <= time_window_end
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type + time window (using created_at)")
            
            # Strategy 4: Final fallback - just find any open order of the target type for this symbol
            if not target_orders:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                    ExchangeOrder.exchange_order_id != executed_order_id
                )
            ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} {target_order_type} orders by symbol + order_type (fallback)")
            
            if not target_orders:
                logger.debug(f"No open {target_order_type} orders found to cancel for {symbol} (tried parent_order_id, order_role, time window, and symbol+type)")
                return 0
            
            # Cancel each remaining order
            from app.utils.live_trading import get_live_trading_status
            live_trading = get_live_trading_status(db)
            
            for target_order in target_orders:
                try:
                    logger.info(f"Canceling {target_order_type} order {target_order.exchange_order_id} (remaining after {executed_order_type} {executed_order_id} was executed)")
                    
                    if not live_trading:
                        logger.info(f"DRY_RUN: Would cancel {target_order_type} order {target_order.exchange_order_id}")
                    else:
                        # Cancel the order
                        cancel_result = trade_client.cancel_order(target_order.exchange_order_id)
                        if "error" in cancel_result:
                            logger.warning(f"Failed to cancel {target_order_type} order {target_order.exchange_order_id}: {cancel_result.get('error')}")
                            continue
                        
                        # Update order status in database
                        target_order.status = OrderStatusEnum.CANCELLED
                        target_order.updated_at = datetime.utcnow()
                    
                    # Send detailed Telegram notification about cancellation
                    try:
                        from app.services.telegram_notifier import telegram_notifier
                        from datetime import timezone
                        
                        # Get executed order details
                        executed_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == executed_order_id
                        ).first()
                        
                        # For FILLED orders, prioritize avg_price (actual execution price) over price (limit/trigger price)
                        executed_price = executed_order.avg_price or executed_order.price or 0 if executed_order else 0
                        executed_qty = executed_order.quantity or executed_order.cumulative_quantity or 0 if executed_order else 0
                        executed_time = executed_order.exchange_update_time or executed_order.updated_at if executed_order else None
                        
                        cancelled_price = target_order.price or 0
                        cancelled_qty = target_order.quantity or 0
                        cancelled_time = datetime.now(timezone.utc)
                        
                        # Format times
                        executed_time_str = executed_time.strftime("%Y-%m-%d %H:%M:%S UTC") if executed_time else "N/A"
                        cancelled_time_str = cancelled_time.strftime("%Y-%m-%d %H:%M:%S UTC")
                        
                        # Calculate profit/loss if order was executed (for both TP and SL orders)
                        pnl_info = ""
                        if executed_order and executed_order.parent_order_id:
                            parent_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.exchange_order_id == executed_order.parent_order_id
                            ).first()
                            if parent_order:
                                entry_price = parent_order.avg_price or parent_order.price or 0
                                parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                                
                                if entry_price > 0 and executed_price > 0 and executed_qty > 0:
                                    # Calculate profit/loss based on parent order side
                                    if parent_side == "BUY":
                                        # For BUY orders: profit if exit > entry, loss if exit < entry
                                        pnl_usd = (executed_price - entry_price) * executed_qty
                                        pnl_pct = ((executed_price - entry_price) / entry_price) * 100
                                    else:  # SELL (short position)
                                        # For SELL orders: profit if exit < entry, loss if exit > entry
                                        pnl_usd = (entry_price - executed_price) * executed_qty
                                        pnl_pct = ((entry_price - executed_price) / entry_price) * 100
                                    
                                    # Format profit/loss with emoji and sign
                                    if pnl_usd >= 0:
                                        pnl_emoji = "💰"
                                        pnl_label = "Profit"
                                    else:
                                        pnl_emoji = "💸"
                                        pnl_label = "Loss"
                                    
                                    pnl_info = (
                                        f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                                        f"   💵 Entry: ${entry_price:,.4f} → Exit: ${executed_price:,.4f}"
                                    )
                        
                        message = (
                            f"🔄 <b>SL/TP ORDER CANCELLED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🔗 OCO Group ID: <code>{target_order.oco_group_id or 'N/A'}</code>\n\n"
                            f"✅ <b>Executed Order:</b>\n"
                            f"   🎯 Type: {executed_order_type}\n"
                            f"   📋 Role: {executed_order.order_role if executed_order else 'N/A'}\n"
                            f"   💵 Price: ${executed_price:.4f}\n"
                            f"   📦 Quantity: {executed_qty:.8f}\n"
                            f"   ⏰ Time: {executed_time_str}\n"
                            f"{pnl_info}\n"
                            f"❌ <b>Cancelled Order:</b>\n"
                            f"   🎯 Type: {target_order_type}\n"
                            f"   📋 Role: {target_order.order_role or 'N/A'}\n"
                            f"   💵 Price: ${cancelled_price:.4f}\n"
                            f"   📦 Quantity: {cancelled_qty:.8f}\n"
                            f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                            f"📋 Order IDs:\n"
                            f"   ✅ Executed: <code>{executed_order_id}</code>\n"
                            f"   ❌ Cancelled: <code>{target_order.exchange_order_id}</code>\n\n"
                            f"💡 <b>Reason:</b> {executed_order_type} order was executed, so the remaining {target_order_type} order has been automatically cancelled to prevent double execution."
                        )
                        
                        telegram_notifier.send_message(message)
                        logger.info(f"Sent detailed cancellation notification for {target_order_type} order: {target_order.exchange_order_id}")
                    except Exception as telegram_err:
                        logger.warning(f"Failed to send Telegram notification for cancellation: {telegram_err}", exc_info=True)
                    
                except Exception as e:
                    logger.error(f"Error canceling {target_order_type} order {target_order.exchange_order_id}: {e}")
            
            db.commit()
            cancelled_count = len(target_orders)
            logger.info(f"Cancelled {cancelled_count} remaining {target_order_type} order(s) for {symbol}")
            return cancelled_count
            
        except Exception as e:
            logger.error(f"Error in _cancel_remaining_sl_tp for {symbol}: {e}", exc_info=True)
            return 0
    
    def _notify_already_cancelled_sl_tp(self, db: Session, symbol: str, executed_order_type: str, executed_order_id: str):
        """Notify when an SL/TP order was already cancelled by the exchange (OCO auto-cancellation)"""
        try:
            # Determine which order type we're looking for
            if executed_order_type.upper() == 'STOP_LIMIT':
                # If SL was executed, check for cancelled TP
                target_order_type = 'TAKE_PROFIT_LIMIT'
            elif executed_order_type.upper() == 'TAKE_PROFIT_LIMIT':
                # If TP was executed, check for cancelled SL
                target_order_type = 'STOP_LIMIT'
            else:
                return  # Not a SL/TP order
            
            # Get executed order to find parent_order_id and order_role
            executed_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == executed_order_id
            ).first()
            
            if not executed_order:
                return
            
            # Find CANCELLED SL/TP orders of the opposite type for the same symbol
            # Try multiple strategies similar to _cancel_remaining_sl_tp
            target_orders = []
            
            # Strategy 1: Find by parent_order_id
            if executed_order.parent_order_id:
                target_orders = db.query(ExchangeOrder).filter(
                    and_(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.parent_order_id == executed_order.parent_order_id,
                        ExchangeOrder.order_type == target_order_type,
                        ExchangeOrder.status == OrderStatusEnum.CANCELLED,
                        ExchangeOrder.exchange_order_id != executed_order_id
                    )
                ).all()
                if target_orders:
                    logger.info(f"Found {len(target_orders)} already CANCELLED {target_order_type} orders by parent_order_id {executed_order.parent_order_id}")
            
            # Strategy 2: Find by order_role if Strategy 1 didn't find anything
            if not target_orders and executed_order.order_role:
                if executed_order.order_role == "STOP_LOSS":
                    target_role = "TAKE_PROFIT"
                elif executed_order.order_role == "TAKE_PROFIT":
                    target_role = "STOP_LOSS"
                else:
                    target_role = None
                
                if target_role:
                    target_orders = db.query(ExchangeOrder).filter(
                        and_(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.order_role == target_role,
                            ExchangeOrder.order_type == target_order_type,
                            ExchangeOrder.status == OrderStatusEnum.CANCELLED,
                            ExchangeOrder.exchange_order_id != executed_order_id
                        )
                    ).all()
                    if target_orders:
                        logger.info(f"Found {len(target_orders)} already CANCELLED {target_order_type} orders by order_role {target_role}")
            
            if not target_orders:
                logger.debug(f"No already CANCELLED {target_order_type} orders found for {symbol}")
                return
            
            # Send notification for already cancelled orders
            try:
                from app.services.telegram_notifier import telegram_notifier
                from datetime import timezone
                
                # Get executed order details
                executed_price = executed_order.avg_price or executed_order.price or 0
                executed_qty = executed_order.quantity or executed_order.cumulative_quantity or 0
                executed_time = executed_order.exchange_update_time or executed_order.updated_at
                executed_time_str = executed_time.strftime("%Y-%m-%d %H:%M:%S UTC") if executed_time else "N/A"
                
                # Get cancelled order details (use first one if multiple)
                cancelled_order = target_orders[0]
                cancelled_price = cancelled_order.price or 0
                cancelled_qty = cancelled_order.quantity or 0
                cancelled_time = cancelled_order.updated_at or cancelled_order.exchange_update_time
                cancelled_time_str = cancelled_time.strftime("%Y-%m-%d %H:%M:%S UTC") if cancelled_time else "N/A"
                
                # Calculate profit/loss if applicable
                pnl_info = ""
                if executed_order.parent_order_id:
                    parent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == executed_order.parent_order_id
                    ).first()
                    if parent_order:
                        entry_price = parent_order.avg_price or parent_order.price or 0
                        parent_side = parent_order.side.value if hasattr(parent_order.side, 'value') else str(parent_order.side)
                        
                        if entry_price > 0 and executed_price > 0 and executed_qty > 0:
                            if parent_side == "BUY":
                                pnl_usd = (executed_price - entry_price) * executed_qty
                                pnl_pct = ((executed_price - entry_price) / entry_price) * 100
                            else:  # SELL
                                pnl_usd = (entry_price - executed_price) * executed_qty
                                pnl_pct = ((entry_price - executed_price) / entry_price) * 100
                            
                            if pnl_usd >= 0:
                                pnl_emoji = "💰"
                                pnl_label = "Profit"
                            else:
                                pnl_emoji = "💸"
                                pnl_label = "Loss"
                            
                            pnl_info = (
                                f"\n{pnl_emoji} <b>{pnl_label}:</b> ${abs(pnl_usd):,.2f} ({pnl_pct:+.2f}%)\n"
                                f"   💵 Entry: ${entry_price:,.4f} → Exit: ${executed_price:,.4f}"
                            )
                
                message = (
                    f"🔄 <b>SL/TP ORDER ALREADY CANCELLED</b>\n\n"
                    f"📊 Symbol: <b>{symbol}</b>\n\n"
                    f"✅ <b>Executed Order:</b>\n"
                    f"   🎯 Type: {executed_order_type}\n"
                    f"   💵 Price: ${executed_price:.4f}\n"
                    f"   📦 Quantity: {executed_qty:.8f}\n"
                    f"   ⏰ Time: {executed_time_str}\n"
                    f"{pnl_info}\n"
                    f"❌ <b>Auto-Cancelled Order:</b>\n"
                    f"   🎯 Type: {target_order_type}\n"
                    f"   💵 Price: ${cancelled_price:.4f}\n"
                    f"   📦 Quantity: {cancelled_qty:.8f}\n"
                    f"   ⏰ Cancelled: {cancelled_time_str}\n\n"
                    f"📋 Order IDs:\n"
                    f"   ✅ Executed: <code>{executed_order_id}</code>\n"
                    f"   ❌ Cancelled: <code>{cancelled_order.exchange_order_id}</code>\n\n"
                    f"💡 <b>Note:</b> The {target_order_type} order was automatically cancelled by Crypto.com OCO group when the {executed_order_type} order was executed."
                )
                
                telegram_notifier.send_message(message)
                logger.info(f"Sent notification for already CANCELLED {target_order_type} order: {cancelled_order.exchange_order_id}")
            except Exception as telegram_err:
                logger.warning(f"Failed to send Telegram notification for already cancelled SL/TP: {telegram_err}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error in _notify_already_cancelled_sl_tp for {symbol}: {e}", exc_info=True)
    
    def sync_order_history(self, db: Session, page_size: int = 200, max_pages: int = 5):
        """Sync order history from Crypto.com - only adds new executed orders
        
        Args:
            db: Database session
            page_size: Number of orders per page (default 200)
            max_pages: Maximum number of pages to fetch (default 5, can be increased for manual sync)
        """
        try:
            from app.services.telegram_notifier import telegram_notifier
            
            # Purge stale processed order IDs before processing
            self._purge_stale_processed_orders()
            
            # Track orders processed in this cycle - mark as processed only AFTER successful commit
            orders_processed_this_cycle = []
            
            # Get order history with pagination to fetch more historical orders
            # Crypto.com API supports pagination with page parameter
            # We'll fetch multiple pages to get more historical data
            all_orders = []
            logger.info(f"Starting order history sync: page_size={page_size}, max_pages={max_pages}")
            
            # Try to get the most recent order timestamp from DB to optimize search
            # This helps us focus on recent orders
            from app.models.exchange_order import ExchangeOrder
            from sqlalchemy import func
            most_recent_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.status == OrderStatusEnum.FILLED
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_update_time, ExchangeOrder.updated_at).desc()
            ).first()
            
            # Use date range: last 7 days or since most recent order (whichever is more recent)
            from datetime import timedelta
            end_time_ms = int(time.time() * 1000)
            if most_recent_order and most_recent_order.exchange_update_time:
                # Start from 1 day before most recent order to catch any missed orders
                start_time = most_recent_order.exchange_update_time - timedelta(days=1)
                start_time_ms = int(start_time.timestamp() * 1000)
                logger.info(f"Using date range: {start_time} to now (found most recent order at {most_recent_order.exchange_update_time})")
            else:
                # Default: last 7 days
                start_time = datetime.now(timezone.utc) - timedelta(days=7)
                start_time_ms = int(start_time.timestamp() * 1000)
                logger.info(f"Using default date range: last 7 days")
            
            for page_num in range(max_pages):
                response = trade_client.get_order_history(
                    page_size=page_size, 
                    page=page_num,
                    start_time=start_time_ms,
                    end_time=end_time_ms
                )
                
                if not response or 'data' not in response:
                    break
                    
                page_orders = response.get('data', [])
                if not page_orders:
                    break
                    
                all_orders.extend(page_orders)
                logger.debug(f"Fetched page {page_num + 1}: {len(page_orders)} orders (total so far: {len(all_orders)})")
                
                # If we got fewer orders than page_size, we've reached the end
                if len(page_orders) < page_size:
                    break
            
            orders = all_orders
            pages_fetched = min(max_pages, len(all_orders) // page_size + 1) if all_orders else 0
            logger.info(f"📥 Received {len(orders)} total orders from API history (fetched {pages_fetched} pages)")
            
            # Note: private/advanced/get-order-history returns order history (executed orders)
            # These should already be FILLED or other terminal states
            filled_count = sum(1 for o in orders if o.get('status', '').upper() == 'FILLED')
            logger.info(f"✅ Found {filled_count} FILLED orders in API response (out of {len(orders)} total orders)")
            
            new_orders_count = 0
            
            for order_data in orders:
                order_id = str(order_data.get('order_id', ''))
                if not order_id:
                    continue
                
                # Process filled orders, and also CANCELED orders that were partially/fully executed
                status_str = order_data.get('status', '').upper()
                
                # Check if order was executed (cumulative_quantity > 0)
                # Handle both string and numeric cumulative_quantity
                cumulative_qty_raw = order_data.get('cumulative_quantity', 0) or 0
                cumulative_qty = float(cumulative_qty_raw) if cumulative_qty_raw else 0
                original_qty = float(order_data.get('quantity', 0) or 0)
                
                # Process FILLED orders, or CANCELED orders that were executed
                # IMPORTANT: If status is FILLED, always process it (even if cumulative_qty is 0 in edge cases)
                # This ensures orders marked as FILLED in Crypto.com are always processed
                is_executed = (
                    status_str == 'FILLED' or  # Always process FILLED orders
                    (cumulative_qty > 0 and status_str == 'CANCELED' and cumulative_qty >= original_qty * 0.99)  # At least 99% executed
                )
                
                if not is_executed:
                    continue
                
                # Check if this order was already processed in the current cycle (prevent duplicates within same sync)
                if order_id in orders_processed_this_cycle:
                    logger.debug(f"Order {order_id} already processed in this sync cycle, skipping duplicate")
                    continue
                
                # NOTE: We allow re-processing orders that were processed in previous sessions
                # This ensures timestamps and other data are always synced from Crypto.com
                # The processed_order_ids check is removed to allow updates to existing orders
                
                # Extract symbol and side early for use in all code paths
                symbol = order_data.get('instrument_name', '')
                side = order_data.get('side', '').upper()
                
                # Parse timestamps early for use in all code paths
                create_time = None
                update_time = None
                if order_data.get('create_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        create_time = datetime.fromtimestamp(order_data['create_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                if order_data.get('update_time'):
                    try:
                        # CRITICAL FIX: Use timezone.utc to ensure timestamps are interpreted as UTC, not local time
                        update_time = datetime.fromtimestamp(order_data['update_time'] / 1000, tz=timezone.utc)
                    except:
                        pass
                
                # Get price and quantity early for use in all code paths
                # IMPORTANT: For SL/TP creation, we MUST use cumulative_quantity (executed quantity) from MARKET order
                # cumulative_quantity is the actual amount that was executed, not the requested quantity
                order_price = order_data.get('limit_price') or order_data.get('price') or order_data.get('avg_price')
                order_price_float = float(order_price) if order_price else None
                quantity_float = float(order_data.get('quantity', 0)) if order_data.get('quantity') else 0
                
                # Priority: cumulative_quantity (executed) > quantity (requested)
                # For MARKET orders, cumulative_quantity is the actual amount executed
                cumulative_qty_raw = order_data.get('cumulative_quantity', 0) or 0
                if cumulative_qty_raw:
                    executed_qty = float(cumulative_qty_raw)
                else:
                    # Fallback to quantity only if cumulative_quantity is not available
                    executed_qty = quantity_float if quantity_float > 0 else 0
                
                logger.info(f"Order {order_id} quantity: requested={quantity_float}, executed={executed_qty} (cumulative_quantity={cumulative_qty_raw})")
                
                # Check if order already exists in database
                existing = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_id
                ).first()
                
                if existing:
                    # Check if status changed from non-FILLED to FILLED
                    # This happens when a LIMIT order we created gets executed, or when a CANCELLED order
                    # is actually found as FILLED in the history (correction)
                    was_filled_before = existing.status == OrderStatusEnum.FILLED
                    needs_update = False
                    needs_telegram = False  # Only send Telegram if status actually changed
                    
                    # Update order status if it was not FILLED before but is FILLED in history
                    if not was_filled_before and is_executed:
                        needs_update = True
                        needs_telegram = True  # Status changed, send notification
                        logger.info(f"Order {order_id} ({existing.status.value if existing.status else 'UNKNOWN'}) found as FILLED in history - updating status and sending Telegram notification")
                    
                    # Also update if status is FILLED in history but different in DB (e.g., CANCELLED -> FILLED)
                    elif existing.status != OrderStatusEnum.FILLED and status_str == 'FILLED':
                        needs_update = True
                        needs_telegram = True  # Status changed, send notification
                        logger.info(f"Order {order_id} status correction: {existing.status.value if existing.status else 'UNKNOWN'} -> FILLED (found in Crypto.com history)")
                    
                    # Update data even if already FILLED (to sync latest values from API)
                    elif was_filled_before and status_str == 'FILLED':
                        needs_update = True
                        needs_telegram = False  # Already FILLED, don't send notification again
                        logger.debug(f"Order {order_id} already FILLED - updating data from API (no notification)")
                    
                    # CRITICAL: Always update timestamps from Crypto.com if available, even if order already exists
                    # This ensures orders always reflect the actual dates from the exchange
                    if status_str == 'FILLED' and (update_time or create_time):
                        needs_update = True
                        if not was_filled_before:
                            needs_telegram = False  # Don't send notification if we're just updating timestamps
                    
                    # ALWAYS update timestamps from Crypto.com if available, regardless of other conditions
                    # This ensures the order reflects what's actually in Crypto.com
                    if (update_time or create_time) and existing:
                        needs_update = True
                        needs_telegram = False  # Don't send notification when just updating timestamps
                        logger.info(f"Updating timestamps for order {order_id} from Crypto.com (update_time={update_time}, create_time={create_time})")
                    
                    if needs_update:
                        # Update existing order with new status and execution data from Crypto.com history
                        logger.info(f"Updating order {order_id} from {existing.status.value if existing.status else 'UNKNOWN'} to FILLED with data from Crypto.com")
                        
                        existing.status = OrderStatusEnum.FILLED
                        # Always use data from Crypto.com history (more accurate)
                        existing.price = order_price_float if order_price_float else existing.price
                        existing.quantity = executed_qty if executed_qty > 0 else (quantity_float if quantity_float > 0 else existing.quantity)
                        # Parse cumulative_quantity as string if needed
                        cumulative_qty_from_api = order_data.get('cumulative_quantity', '0') or '0'
                        existing.cumulative_quantity = float(cumulative_qty_from_api) if cumulative_qty_from_api else 0
                        cumulative_val_from_api = order_data.get('cumulative_value', '0') or '0'
                        existing.cumulative_value = float(cumulative_val_from_api) if cumulative_val_from_api else 0
                        avg_price_from_api = order_data.get('avg_price', '0') or '0'
                        existing.avg_price = float(avg_price_from_api) if avg_price_from_api else (order_price_float if order_price_float else existing.avg_price)
                        
                        # CRITICAL: Always update timestamps from Crypto.com if available
                        # This ensures the order reflects the actual date from the exchange
                        if update_time:
                            existing.exchange_update_time = update_time
                            logger.info(f"Updated exchange_update_time for order {order_id} to {update_time} from Crypto.com")
                        elif create_time:
                            # If update_time is not available, use create_time
                            existing.exchange_update_time = create_time
                            logger.info(f"Updated exchange_update_time for order {order_id} to {create_time} (from create_time) from Crypto.com")
                        # Only use datetime.utcnow() as last resort if no timestamp is available from Crypto.com
                        elif not existing.exchange_update_time:
                            existing.exchange_update_time = datetime.now(timezone.utc)
                            logger.warning(f"No timestamp from Crypto.com for order {order_id}, using current time")
                        
                        # Always update create_time if available from Crypto.com
                        if create_time:
                            existing.exchange_create_time = create_time
                        
                        existing.updated_at = datetime.now(timezone.utc)
                        
                        logger.info(f"Order {order_id} updated: cumulative_qty={existing.cumulative_quantity}, cumulative_val={existing.cumulative_value}, avg_price={existing.avg_price}")
                        
                        # Mark that we updated an existing order (counts towards new_orders_count for commit)
                        new_orders_count += 1
                        
                        # IMPORTANT: Do NOT mark as processed here - wait until AFTER successful commit
                        # This prevents orders from being skipped in future syncs if commit fails
                        # Track for marking as processed after commit succeeds
                        orders_processed_this_cycle.append(order_id)
                        
                        if needs_telegram:
                            try:
                                from app.services.telegram_notifier import telegram_notifier
                                
                                total_usd = order_price_float * executed_qty if order_price_float and executed_qty else 0
                                order_type = order_data.get('order_type', existing.order_type or 'LIMIT')
                                order_type_upper = order_type.upper()
                                
                                # If this is a SL or TP order, find the original entry order to calculate profit/loss
                                entry_price = None
                                if order_type_upper in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']:
                                    current_side = side or (existing.side.value if existing.side else 'BUY')
                                    
                                    # First try to find by parent_order_id (most reliable)
                                    if existing.parent_order_id:
                                        parent_order = db.query(ExchangeOrder).filter(
                                            ExchangeOrder.exchange_order_id == existing.parent_order_id
                                        ).first()
                                        if parent_order:
                                            entry_price = parent_order.avg_price if parent_order.avg_price else parent_order.price
                                            logger.info(f"Found entry price via parent_order_id for SL/TP order {order_id}: {entry_price} from parent {existing.parent_order_id}")
                                    
                                    # If parent_order_id not found, search for most recent BUY order
                                    if not entry_price and current_side == "SELL":
                                        # This is selling (TP/SL after BUY), so find the original BUY order
                                        # Look for BUY orders created before this TP/SL order
                                        if existing.exchange_create_time:
                                            original_order = db.query(ExchangeOrder).filter(
                                                ExchangeOrder.symbol == (symbol or existing.symbol),
                                                ExchangeOrder.side == "BUY",
                                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                                ExchangeOrder.exchange_order_id != order_id,  # Not the current order
                                                ExchangeOrder.exchange_create_time <= existing.exchange_create_time  # Created before TP/SL
                                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                        else:
                                            # Fallback without time constraint
                                            original_order = db.query(ExchangeOrder).filter(
                                                ExchangeOrder.symbol == (symbol or existing.symbol),
                                                ExchangeOrder.side == "BUY",
                                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                                ExchangeOrder.exchange_order_id != order_id
                                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                        
                                        if original_order:
                                            entry_price = original_order.avg_price if original_order.avg_price else original_order.price
                                            logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from BUY order {original_order.exchange_order_id}")
                                    elif not entry_price and current_side == "BUY":
                                        # This is buying (SL/TP after SELL for short positions), find original SELL order
                                        if existing.exchange_create_time:
                                            original_order = db.query(ExchangeOrder).filter(
                                                ExchangeOrder.symbol == (symbol or existing.symbol),
                                                ExchangeOrder.side == "SELL",
                                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                                ExchangeOrder.exchange_order_id != order_id,
                                                ExchangeOrder.exchange_create_time <= existing.exchange_create_time
                                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                        else:
                                            original_order = db.query(ExchangeOrder).filter(
                                                ExchangeOrder.symbol == (symbol or existing.symbol),
                                                ExchangeOrder.side == "SELL",
                                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                                ExchangeOrder.exchange_order_id != order_id
                                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                                        
                                        if original_order:
                                            entry_price = original_order.avg_price if original_order.avg_price else original_order.price
                                            logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from SELL order {original_order.exchange_order_id}")
                                
                                # Count open BUY orders for this symbol (NEW, ACTIVE, PARTIALLY_FILLED)
                                # CRITICAL: Only count BUY orders, not SELL (SL/TP), because limit is per BUY orders
                                order_symbol = symbol or existing.symbol
                                open_orders_count = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.symbol == order_symbol,
                                    ExchangeOrder.side == OrderSideEnum.BUY,  # Only count BUY orders
                                    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                                ).count()
                                
                                # Infer order_role from order_type if order_role is not set
                                # This helps identify manually created SL/TP orders
                                inferred_order_role = existing.order_role
                                if not inferred_order_role and order_type_upper:
                                    if order_type_upper == 'STOP_LIMIT':
                                        inferred_order_role = 'STOP_LOSS'
                                    elif order_type_upper == 'TAKE_PROFIT_LIMIT':
                                        inferred_order_role = 'TAKE_PROFIT'
                                
                                telegram_notifier.send_executed_order(
                                    symbol=order_symbol,
                                    side=side or (existing.side.value if existing.side else 'BUY'),
                                    price=order_price_float or (existing.price or 0),
                                    quantity=executed_qty or (existing.quantity or 0),
                                    total_usd=total_usd,
                                    order_id=order_id,
                                    order_type=order_type,
                                    entry_price=entry_price,  # Add entry_price for profit/loss calculation
                                    open_orders_count=open_orders_count,  # Add open orders count for monitoring
                                    order_role=inferred_order_role  # Use inferred role if order_role is not set
                                )
                                logger.info(f"Sent Telegram notification for executed order: {symbol or existing.symbol} {side or (existing.side.value if existing.side else 'BUY')} - {order_id}")
                            except Exception as telegram_err:
                                logger.warning(f"Failed to send Telegram notification: {telegram_err}")
                            
                            # Check if this is a SL or TP order that was executed - cancel the other one
                            # Also check if this is a SELL LIMIT order that closes a position - cancel SL
                            order_type_from_history = order_data.get('order_type', '').upper()
                            order_type_from_db = existing.order_type or ''
                            is_sl_tp_executed = (
                                order_type_from_history in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT'] or 
                                order_type_from_db.upper() in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                            )
                            
                            # If this is a SELL LIMIT order (not TP/SL) that closes a position, cancel remaining SL
                            is_sell_limit_that_closes_position = (
                                order_type_from_history == 'LIMIT' and 
                                side == 'SELL' and 
                                not is_sl_tp_executed
                            )
                            
                            if is_sl_tp_executed:
                                # First try to cancel using OCO group ID (more reliable)
                                if existing.oco_group_id:
                                    try:
                                        logger.info(f"Attempting to cancel OCO sibling for order {order_id} (group: {existing.oco_group_id})")
                                        self._cancel_oco_sibling(db, existing)
                                    except Exception as oco_err:
                                        logger.warning(f"Error canceling OCO sibling for {order_id}: {oco_err}")
                                
                                # Also try the fallback method (for orders without OCO group ID)
                                # This will search by parent_order_id, order_role, time window, or symbol+type
                                try:
                                    cancelled_count = self._cancel_remaining_sl_tp(db, symbol or existing.symbol, order_type_from_history or order_type_from_db.upper(), order_id)
                                    if cancelled_count == 0:
                                        # If no active SL/TP found to cancel, check if there's already a CANCELLED one
                                        # This means it was cancelled by Crypto.com OCO automatically, but we should still notify
                                        logger.debug(f"No active {order_type_from_db.upper()} orders found to cancel - checking for already CANCELLED orders")
                                        self._notify_already_cancelled_sl_tp(db, symbol or existing.symbol, order_type_from_history or order_type_from_db.upper(), order_id)
                                except Exception as cancel_err:
                                    logger.warning(f"Error canceling remaining SL/TP for {order_id}: {cancel_err}")
                            
                            # If this is a SELL LIMIT order that closes a position, cancel remaining SL orders
                            elif is_sell_limit_that_closes_position:
                                try:
                                    logger.info(f"SELL LIMIT order {order_id} executed - cancelling remaining SL orders for {symbol or existing.symbol}")
                                    self._cancel_remaining_sl_tp(db, symbol or existing.symbol, 'LIMIT', order_id)
                                except Exception as cancel_err:
                                    logger.warning(f"Error canceling remaining SL orders after SELL LIMIT execution for {order_id}: {cancel_err}")
                        
                        # Create SL/TP for LIMIT orders that were filled (only if status just changed to FILLED)
                        # Do this AFTER we've marked the order for update, but handle errors gracefully
                        # Create SL/TP for both LIMIT and MARKET orders when they are filled
                        # IMPORTANT: NEVER create SL/TP for STOP_LIMIT or TAKE_PROFIT_LIMIT orders
                        order_type_from_history = order_data.get('order_type', '').upper()
                        order_type_from_db = existing.order_type or ''
                        
                        # Check if this is a SL/TP order - if so, do NOT create new SL/TP
                        is_sl_tp_order = (
                            order_type_from_history in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT'] or 
                            order_type_from_db.upper() in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']
                        )
                        
                        # Create SL/TP only for LIMIT and MARKET orders (not for STOP_LIMIT or TAKE_PROFIT_LIMIT)
                        is_main_order = (
                            (order_type_from_history in ['LIMIT', 'MARKET'] or 
                             order_type_from_db.upper() in ['LIMIT', 'MARKET']) and
                            not is_sl_tp_order  # Double check - never create SL/TP for SL/TP orders
                        )
                        
                        # CRITICAL FIX: Always check and create SL/TP for FILLED orders, not just when needs_telegram=True
                        # This ensures SL/TP are created even if the order was already FILLED in the database
                        # The _create_sl_tp_for_filled_order function already checks for duplicates, so it's safe to call multiple times
                        if is_main_order and is_executed:
                            # Check if order was filled within the last hour
                            # This prevents creating SL/TP for old orders where prices may have changed significantly
                            from datetime import timedelta, timezone
                            # Use update_time or create_time from API (now timezone-aware UTC), or fallback to database time
                            order_filled_time = update_time or create_time
                            if not order_filled_time:
                                # Fallback to database time if API times not available
                                order_filled_time = existing.exchange_update_time or existing.exchange_create_time
                            
                            # CRITICAL FIX: If no timestamp is available at all, skip SL/TP creation
                            # Using datetime.now() as fallback would make old orders appear freshly filled,
                            # bypassing the 1-hour check and always creating SL/TP
                            if not order_filled_time:
                                logger.warning(
                                    f"⏰ Skipping SL/TP creation for order {order_id} ({symbol or existing.symbol}): "
                                    f"No timestamp available (update_time, create_time, exchange_update_time, exchange_create_time all None). "
                                    f"Cannot verify if order was filled within 1 hour. Skipping to prevent creating SL/TP for old orders."
                                )
                            else:
                                # Ensure timezone is UTC (should already be UTC from fromtimestamp fix, but handle database times)
                                if order_filled_time.tzinfo is None:
                                    # Database times might be naive - assume UTC
                                    logger.debug(f"Order {order_id} has naive datetime from database, assuming UTC")
                                    order_filled_time = order_filled_time.replace(tzinfo=timezone.utc)
                                elif order_filled_time.tzinfo != timezone.utc:
                                    order_filled_time = order_filled_time.astimezone(timezone.utc)
                                
                                now_utc = datetime.now(timezone.utc)
                                time_since_filled = (now_utc - order_filled_time).total_seconds() / 3600  # hours
                                
                                if time_since_filled > 1.0:
                                    logger.info(
                                        f"⏰ Skipping SL/TP creation for order {order_id} ({symbol or existing.symbol}): "
                                        f"Order was filled {time_since_filled:.2f} hours ago (limit: 1 hour). "
                                        f"Price may have changed significantly."
                                    )
                                else:
                                    # For main orders, use the side from the order itself (which is the original side)
                                    # existing.side is the correct side for the original order
                                    original_side = existing.side.value if existing.side else (side or 'BUY')
                                    logger.info(f"Creating SL/TP for main order {order_id}: original_side={original_side}, order_type={order_type_from_history or order_type_from_db}, filled {time_since_filled:.2f} hours ago")
                                    
                                    try:
                                        self._create_sl_tp_for_filled_order(
                                            db=db,
                                            symbol=symbol or existing.symbol,
                                            side=original_side,  # Use the original order's side (from existing.side)
                                            filled_price=order_price_float or existing.price or 0,
                                            filled_qty=executed_qty,  # Always use executed_qty (cumulative_quantity) from API
                                            order_id=order_id
                                        )
                                    except Exception as sl_tp_err:
                                        # Don't let SL/TP creation errors prevent order status update
                                        # Log but don't re-raise - we want the order status update to be committed
                                        logger.warning(f"Error creating SL/TP for order {order_id}: {sl_tp_err}")
                                        # Continue - order status update should still be committed even if SL/TP fails
                        elif is_sl_tp_order:
                            logger.debug(f"Skipping SL/TP creation for {order_type_from_history or order_type_from_db} order {order_id} - SL/TP orders should not create new SL/TP")
                    else:
                        # No update needed - order is already in correct state
                        logger.debug(f"Order {order_id} already in correct state, skipping update")
                    
                    # Already marked as processed before sending Telegram (see above)
                    continue  # Already synced to database
                
                # Create new order record (variables already extracted above)
                
                # Check if there's an existing order with this ID that might have oco_group_id
                # This happens when an order was created locally but then found in history
                existing_order_for_oco = db.query(ExchangeOrder).filter(ExchangeOrder.exchange_order_id == order_id).first()
                oco_group_id_from_existing = existing_order_for_oco.oco_group_id if existing_order_for_oco else None
                
                new_order = ExchangeOrder(
                    exchange_order_id=order_id,
                    client_oid=order_data.get('client_oid'),
                    symbol=symbol,
                    side=OrderSideEnum.BUY if side == 'BUY' else OrderSideEnum.SELL,
                    order_type=order_data.get('order_type', 'LIMIT'),
                    status=OrderStatusEnum.FILLED,
                    price=order_price_float,  # Will use avg_price for MARKET orders
                    quantity=executed_qty,  # Use cumulative_quantity (executed amount)
                    cumulative_quantity=float(order_data.get('cumulative_quantity', 0)) if order_data.get('cumulative_quantity') else 0,
                    cumulative_value=float(order_data.get('cumulative_value', 0)) if order_data.get('cumulative_value') else 0,
                    avg_price=float(order_data.get('avg_price')) if order_data.get('avg_price') else order_price_float,
                    exchange_create_time=create_time,
                    exchange_update_time=update_time,
                    oco_group_id=oco_group_id_from_existing  # Preserve OCO group ID if it exists
                )
                db.add(new_order)
                db.flush()  # Flush to get the order ID and relationships
                
                # Check if this is a SL or TP order that was executed - cancel the other one
                order_type_upper = order_data.get('order_type', '').upper()
                is_sl_tp_executed = order_type_upper in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']
                
                if is_sl_tp_executed:
                    # First try to cancel using OCO group ID (more reliable)
                    if new_order.oco_group_id:
                        try:
                            logger.info(f"Attempting to cancel OCO sibling for new order {order_id} (group: {new_order.oco_group_id})")
                            self._cancel_oco_sibling(db, new_order)
                        except Exception as oco_err:
                            logger.warning(f"Error canceling OCO sibling for new order {order_id}: {oco_err}")
                    
                    # Also try the fallback method (for orders without OCO group ID or if OCO cancel failed)
                    try:
                        self._cancel_remaining_sl_tp(db, symbol, order_type_upper, order_id)
                    except Exception as cancel_err:
                        logger.warning(f"Error canceling remaining SL/TP for new order {order_id}: {cancel_err}")
                
                # Track for marking as processed AFTER successful commit
                orders_processed_this_cycle.append(order_id)
                new_orders_count += 1
                
                # Create SL/TP for both LIMIT and MARKET orders when they are filled
                # (not for STOP_LIMIT or TAKE_PROFIT_LIMIT)
                # BUT: Only create SL/TP if the order was filled within the last hour
                order_type = order_data.get('order_type', '').upper()
                
                # IMPORTANT: NEVER create SL/TP for STOP_LIMIT or TAKE_PROFIT_LIMIT orders
                if order_type in ['LIMIT', 'MARKET']:
                    # Check if order was filled within the last hour
                    # CRITICAL FIX: update_time and create_time are now already timezone-aware (UTC) from the fix above
                    # No need to use replace() which would mislabel local time as UTC
                    order_filled_time = update_time or create_time
                    
                    # CRITICAL FIX: If no timestamp is available at all, skip SL/TP creation
                    # Using datetime.now() as fallback would make old orders appear freshly filled,
                    # bypassing the 1-hour check and always creating SL/TP
                    if not order_filled_time:
                        logger.warning(
                            f"⏰ Skipping SL/TP creation for new order {order_id} ({symbol}): "
                            f"No timestamp available (update_time and create_time both None). "
                            f"Cannot verify if order was filled within 1 hour. Skipping to prevent creating SL/TP for old orders."
                        )
                    else:
                        # Ensure timezone is UTC (should already be UTC from fromtimestamp fix, but handle edge cases)
                        if order_filled_time.tzinfo is None:
                            # This shouldn't happen with the fix, but handle it just in case
                            logger.warning(f"Order {order_id} has naive datetime, assuming UTC")
                            order_filled_time = order_filled_time.replace(tzinfo=timezone.utc)
                        elif order_filled_time.tzinfo != timezone.utc:
                            order_filled_time = order_filled_time.astimezone(timezone.utc)
                        
                        now_utc = datetime.now(timezone.utc)
                        time_since_filled = (now_utc - order_filled_time).total_seconds() / 3600  # hours
                        
                        if time_since_filled > 1.0:
                            logger.info(
                                f"⏰ Skipping SL/TP creation for new order {order_id} ({symbol}): "
                                f"Order was filled {time_since_filled:.2f} hours ago (limit: 1 hour). "
                                f"Price may have changed significantly."
                            )
                        else:
                            # Try to create SL/TP automatically
                            # Use side from order_data which is the original order's side
                            logger.info(f"Creating SL/TP for new main order {order_id}: side={side}, order_type={order_type}, filled {time_since_filled:.2f} hours ago")
                            try:
                                self._create_sl_tp_for_filled_order(
                                    db=db,
                                    symbol=symbol,
                                    side=side,  # This is the original order's side (BUY or SELL)
                                    filled_price=order_price_float,
                                    filled_qty=executed_qty,  # Always use executed_qty (cumulative_quantity) from API - this is the actual executed amount from MARKET order
                                    order_id=order_id
                                )
                            except Exception as sl_tp_err:
                                logger.warning(f"Error creating SL/TP for order {order_id}: {sl_tp_err}")
                elif order_type in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']:
                    logger.debug(f"Skipping SL/TP creation for {order_type} order {order_id} - SL/TP orders should not create new SL/TP")
                
                # Send Telegram notification for new executed order with execution time
                try:
                    from app.services.telegram_notifier import telegram_notifier
                    
                    # Use the proper method for executed orders
                    total_usd = order_price_float * executed_qty if order_price_float and executed_qty else 0
                    order_type = order_data.get('order_type', 'LIMIT')
                    order_type_upper = order_type.upper()
                    
                    # If this is a SL or TP order, find the original entry order to calculate profit/loss
                    entry_price = None
                    if order_type_upper in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT']:
                        # Find the most recent BUY or SELL order (depending on side) for this symbol
                        # For SL/TP after BUY: find last BUY order
                        # For SL/TP after SELL: find last SELL order
                        # SL/TP after BUY means we're selling (SELL), so find last BUY
                        # SL/TP after SELL means we're buying (BUY), so find last SELL
                        if side == "SELL":
                            # This is selling, so find the original BUY order
                            original_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.symbol == symbol,
                                ExchangeOrder.side == "BUY",
                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                ExchangeOrder.exchange_order_id != order_id  # Not the current order
                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                        else:  # side == "BUY"
                            # This is buying, so find the original SELL order (for short positions)
                            original_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.symbol == symbol,
                                ExchangeOrder.side == "SELL",
                                ExchangeOrder.status == OrderStatusEnum.FILLED,
                                ExchangeOrder.order_type.in_(["MARKET", "LIMIT"]),
                                ExchangeOrder.exchange_order_id != order_id  # Not the current order
                            ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                        
                        if original_order:
                            # Use avg_price if available (more accurate for MARKET orders), otherwise price
                            entry_price = float(original_order.avg_price) if original_order.avg_price else float(original_order.price) if original_order.price else None
                            logger.info(f"Found entry price for SL/TP order {order_id}: {entry_price} from order {original_order.exchange_order_id}")
                    
                    # Count open BUY orders for this symbol (NEW, ACTIVE, PARTIALLY_FILLED)
                    # CRITICAL: Only count BUY orders, not SELL (SL/TP), because limit is per BUY orders
                    open_orders_count = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,  # Only count BUY orders
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                    ).count()
                    
                    # Get order_role from the order if it exists in database
                    order_role = None
                    if order_id:
                        existing_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == order_id
                        ).first()
                        if existing_order:
                            order_role = existing_order.order_role
                    
                    # Infer order_role from order_type if order_role is not set
                    # This helps identify manually created SL/TP orders
                    if not order_role and order_type:
                        order_type_upper = order_type.upper()
                        if order_type_upper == 'STOP_LIMIT':
                            order_role = 'STOP_LOSS'
                        elif order_type_upper == 'TAKE_PROFIT_LIMIT':
                            order_role = 'TAKE_PROFIT'
                    
                    telegram_notifier.send_executed_order(
                        symbol=symbol,
                        side=side,
                        price=order_price_float or 0,
                        quantity=executed_qty,
                        total_usd=total_usd,
                        order_id=order_id,
                        order_type=order_type,
                        entry_price=entry_price,  # Add entry_price for profit/loss calculation
                        open_orders_count=open_orders_count,  # Add open orders count for monitoring
                        order_role=order_role  # Use inferred role if order_role is not set
                    )
                    logger.info(f"Sent Telegram notification for executed order: {symbol} {side} - {order_id}")
                except Exception as telegram_err:
                    logger.warning(f"Failed to send Telegram notification: {telegram_err}")
            
            # Always commit to ensure status updates are saved
            # Even if SL/TP creation fails, we want to save the order status update
            try:
                db.commit()
                # CRITICAL FIX: Mark orders as processed ONLY AFTER successful commit
                # This prevents orders from being skipped in future syncs if commit fails
                for order_id in orders_processed_this_cycle:
                    self._mark_order_processed(order_id)
                
                if new_orders_count > 0:
                    logger.info(f"✅ Committed: Synced {new_orders_count} executed orders from history (new + updated), marked {len(orders_processed_this_cycle)} as processed")
                else:
                    if filled_count > 0:
                        logger.debug(f"No new executed orders to sync (all {filled_count} filled orders already in DB or updated)")
                    else:
                        logger.debug("No filled orders found in API history")
            except Exception as commit_err:
                logger.error(f"Error committing order history updates: {commit_err}", exc_info=True)
                db.rollback()
                # Do NOT mark orders as processed if commit failed - they should be retried in next sync
                raise
            
        except Exception as e:
            logger.error(f"Error syncing order history: {e}", exc_info=True)
            # Check if it's an authentication error
            if "40101" in str(e) or "Authentication" in str(e):
                logger.warning("Authentication error when syncing order history - check API credentials")
            try:
                db.rollback()
            except:
                pass
    
    def _run_sync_sync(self, db: Session):
        """Run one sync cycle - synchronous worker that runs in thread pool"""
        self.sync_balances(db)
        self.sync_open_orders(db)
        # Sync order history every cycle (every 5 seconds) to catch all new orders
        # Increased page_size to 200 and max_pages to 10 to get more recent orders
        # This ensures we catch orders from the last ~2000 orders (10 pages * 200 orders)
        self.sync_order_history(db, page_size=200, max_pages=10)
    
    async def run_sync(self):
        """Run one sync cycle - async wrapper that delegates to thread pool"""
        db = SessionLocal()
        try:
            await asyncio.to_thread(self._run_sync_sync, db)
            self.last_sync = datetime.now(timezone.utc)
        finally:
            db.close()
    
    async def start(self):
        """Start the sync service - OPTIMIZED: delayed initial sync to avoid blocking startup"""
        # Prevent multiple instances from starting
        if self.is_running:
            logger.warning("⚠️ Exchange sync service is already running, skipping duplicate start")
            return
        self.is_running = True
        logger.info("🚀 Exchange sync service started")
        
        # OPTIMIZATION: Wait before first sync to avoid blocking initial HTTP requests
        # This allows the server to handle requests quickly on startup
        await asyncio.sleep(15)  # Wait 15 seconds before first sync
        
        # Run first sync after delay to set last_sync
        try:
            await self.run_sync()
        except Exception as e:
            logger.error(f"Error in initial sync cycle: {e}", exc_info=True)
        
        while self.is_running:
            try:
                await self.run_sync()
            except Exception as e:
                logger.error(f"Error in sync cycle: {e}", exc_info=True)
            
            await asyncio.sleep(self.sync_interval)
    
    def stop(self):
        """Stop the sync service"""
        self.is_running = False
        logger.info("Exchange sync service stopped")


# Global instance
exchange_sync_service = ExchangeSyncService()
