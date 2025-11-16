"""
SL/TP Checker Service
Checks all open positions for missing SL/TP orders and sends Telegram alerts
"""
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.services.exchange_sync import exchange_sync_service
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order

logger = logging.getLogger(__name__)


class SLTPCheckerService:
    """Service to check open positions for missing SL/TP orders and OCO integrity"""
    
    def __init__(self):
        self.last_check_date = None
    
    def _check_oco_issues(self, db: Session) -> Dict:
        """
        Check for OCO-related issues
        Returns: Dict with orphaned orders and incomplete groups
        """
        issues = {'orphaned_orders': [], 'incomplete_groups': [], 'total_oco_groups': 0}
        
        try:
            # Find active SL/TP orders
            active_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            logger.info(f"Checking {len(active_sl_tp)} active SL/TP orders for OCO issues")
            
            # Check for orphaned orders
            for order in active_sl_tp:
                if not order.parent_order_id or not order.oco_group_id:
                    issues['orphaned_orders'].append({
                        'order_id': order.exchange_order_id,
                        'symbol': order.symbol,
                        'type': order.order_role or order.order_type,
                        'price': float(order.price) if order.price else None,
                        'missing': 'parent_order_id' if not order.parent_order_id else 'oco_group_id',
                        'quantity': float(order.quantity) if order.quantity else None
                    })
            
            # Group by oco_group_id
            from collections import defaultdict
            oco_groups = defaultdict(list)
            for order in active_sl_tp:
                if order.oco_group_id:
                    oco_groups[order.oco_group_id].append(order)
            
            issues['total_oco_groups'] = len(oco_groups)
            
            # Check for incomplete groups
            for oco_id, orders in oco_groups.items():
                has_sl = any(o.order_role == "STOP_LOSS" for o in orders)
                has_tp = any(o.order_role == "TAKE_PROFIT" for o in orders)
                
                if not (has_sl and has_tp):
                    symbol = orders[0].symbol if orders else "Unknown"
                    issues['incomplete_groups'].append({
                        'oco_group_id': oco_id,
                        'symbol': symbol,
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'missing': "STOP_LOSS" if not has_sl else "TAKE_PROFIT"
                    })
            
            logger.info(f"OCO check: {len(issues['orphaned_orders'])} orphaned, {len(issues['incomplete_groups'])} incomplete")
            
        except Exception as e:
            logger.error(f"Error checking OCO issues: {e}", exc_info=True)
            issues['error'] = str(e)
        
        return issues
    
    def check_positions_for_sl_tp(self, db: Session) -> Dict:
        """
        Check all open positions and verify if they have SL/TP orders
        
        Returns:
            Dict with positions missing SL/TP
        """
        try:
            # Get account balance to find open positions
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            logger.info(f"Received {len(accounts)} accounts from get_account_summary")
            if len(accounts) > 0:
                logger.info(f"Sample account: {accounts[0]}")
            
            # Filter positions with positive balance (excluding USDT/USD)
            open_positions = []
            for account in accounts:
                # Handle both 'currency' and 'instrument_name' fields
                currency = account.get('currency', '').upper()
                if not currency:
                    # Try instrument_name if currency is not available
                    currency = account.get('instrument_name', '').upper()
                
                if not currency:
                    logger.warning(f"Account missing currency/instrument_name: {account}")
                    continue
                    
                balance_str = account.get('balance', '0')
                
                # Handle balance format - could be string or number
                try:
                    balance = float(balance_str)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid balance format for {currency}: {balance_str}")
                    continue
                
                # Skip if balance is zero or negative
                if balance <= 0:
                    logger.debug(f"Skipping {currency} - balance is {balance}")
                    continue
                
                # Handle currency format - could be "ETH" or "ETH_USDT"
                if '_' in currency:
                    # Format is already like "ETH_USDT" - extract base currency
                    base_currency = currency.split('_')[0]
                    symbol = currency  # Keep full symbol for later use
                else:
                    # Format is just currency like "ETH" - assume USDT pair
                    base_currency = currency
                    symbol = f"{currency}_USDT"
                
                # Skip stablecoins (USDT, USD, USDC, etc.) and fiat (EUR, GBP, JPY, etc.)
                stablecoins = ['USDT', 'USD', 'USDC', 'BUSD', 'DAI', 'TUSD']
                fiat = ['EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'CHF', 'NZD', 'SGD', 'HKD', 'KRW']
                if base_currency in stablecoins or base_currency in fiat:
                    logger.debug(f"Skipping stablecoin/fiat: {base_currency}")
                    continue
                
                open_positions.append({
                    'currency': base_currency,
                    'symbol': symbol,
                    'balance': balance
                })
                
                logger.info(f"Found open position: {symbol} ({base_currency}) = {balance}")
            
            logger.info(f"Found {len(open_positions)} open positions to check for SL/TP")
            
            # For each position, check if there are active SL/TP orders
            positions_missing_sl_tp = []
            
            for position in open_positions:
                currency = position['currency']
                symbol = position.get('symbol', f"{currency}_USDT")  # Use symbol from position or default
                
                # Create symbol variants to check (BONK_USDT, BONK_USD, etc.)
                symbol_variants = [symbol]
                if symbol.endswith('_USDT'):
                    symbol_variants.append(symbol.replace('_USDT', '_USD'))
                elif symbol.endswith('_USD'):
                    symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Try to find symbol in watchlist - try exact match first
                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
                
                if not watchlist_item:
                    # Try pattern match
                    watchlist_item = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol.like(f"%{currency}%")
                    ).first()
                    if watchlist_item:
                        symbol = watchlist_item.symbol  # Use symbol from watchlist if found
                        # Update symbol variants
                        symbol_variants = [symbol]
                        if symbol.endswith('_USDT'):
                            symbol_variants.append(symbol.replace('_USDT', '_USD'))
                        elif symbol.endswith('_USD'):
                            symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Check for active SL/TP orders from Crypto.com Exchange API directly
                # This is more reliable than checking database status
                has_sl = False
                has_tp = False
                
                try:
                    # Get ALL open orders (trigger orders may not be filtered by symbol in the API)
                    all_open_orders = trade_client.get_open_orders()
                    all_orders_data = all_open_orders.get('data', [])
                    
                    logger.debug(f"Retrieved {len(all_orders_data)} total open orders from Exchange")
                    if all_orders_data:
                        # Log sample to understand format
                        sample_order = all_orders_data[0] if len(all_orders_data) > 0 else {}
                        logger.debug(f"Sample order: instrument={sample_order.get('instrument_name')}, type={sample_order.get('order_type')}, symbol_variants={symbol_variants}")
                    
                    # Filter orders for this symbol and variants
                    # Handle both BONK/USD (with slash) and BONK_USD (with underscore)
                    open_orders_data = []
                    for order in all_orders_data:
                        order_instrument = order.get('instrument_name', '')
                        # Normalize: convert slash to underscore for comparison
                        order_symbol_normalized = order_instrument.replace('/', '_').upper()
                        variant_normalized = [v.upper() for v in symbol_variants]
                        
                        # Check if this order matches our symbol or variants
                        if order_symbol_normalized in variant_normalized or \
                           any(v.replace('_', '/') == order_instrument for v in symbol_variants):
                            open_orders_data.append(order)
                            logger.debug(f"Matched order: {order_instrument} (normalized: {order_symbol_normalized}) for {symbol}")
                    
                    logger.debug(f"Filtered {len(open_orders_data)} orders for {symbol} from {len(all_orders_data)} total orders")
                    
                    # Filter for SL/TP orders with flexible matching
                    sl_orders_open = []
                    tp_orders_open = []
                    
                    for o in open_orders_data:
                        order_type = o.get('order_type', '')
                        order_type_lower = order_type.lower()
                        order_type_upper = order_type.upper()
                        trigger_price = o.get('trigger_price')
                        side = o.get('side', '')
                        
                        # Check for SL orders (Stop Loss / Stop Limit)
                        # Also check if it's a LIMIT order with trigger_price and side SELL (indicating SL)
                        is_sl_order = False
                        if any(sl_term in order_type_lower for sl_term in ['stop', 'stop_loss', 'stop_loss_limit']):
                            is_sl_order = True
                        elif order_type_upper == 'LIMIT' and trigger_price and side.upper() == 'SELL':
                            # LIMIT order with trigger_price is a Stop Loss order in Crypto.com
                            # Only consider it SL if it's a SELL order (closing a long position)
                            is_sl_order = True
                        
                        if is_sl_order:
                            sl_orders_open.append(o)
                            logger.debug(f"Found SL order for {symbol}: {order_type} (trigger_price={trigger_price}, side={side}) - {o.get('order_id')}")
                        
                        # Check for TP orders (Take Profit)
                        if any(tp_term in order_type_lower for tp_term in ['take-profit', 'take_profit', 'take profit', 'profit_limit']) or \
                           ('profit' in order_type_lower and 'take' in order_type_lower):
                            tp_orders_open.append(o)
                            logger.debug(f"Found TP order for {symbol}: {order_type} - {o.get('order_id')}")
                    
                    logger.info(f"Position {symbol}: Filtered {len(sl_orders_open)} SL and {len(tp_orders_open)} TP orders from {len(open_orders_data)} matched orders")
                    
                    # CRITICAL: Check order status - only count ACTIVE orders, not CANCELLED or FILLED
                    # Crypto.com API may return orders with status 'CANCELLED' or 'FILLED' in get_open_orders()
                    active_sl_orders = []
                    active_tp_orders = []
                    
                    # Get current position balance for comparison
                    position_balance = position.get('balance', 0)
                    
                    for o in sl_orders_open:
                        order_status = o.get('order_status', '').upper() or o.get('status', '').upper()
                        order_quantity = float(o.get('quantity', 0) or o.get('qty', 0) or 0)
                        
                        # Only count orders that are ACTIVE, NEW, or PENDING
                        if order_status in ['ACTIVE', 'NEW', 'PENDING'] or not order_status:
                            # CRITICAL: Verify order quantity matches position balance (within 5% tolerance)
                            # This ensures we're not counting old orders from previous positions
                            if order_quantity > 0 and position_balance > 0:
                                quantity_match = abs(order_quantity - position_balance) / position_balance <= 0.05
                                if quantity_match:
                                    active_sl_orders.append(o)
                                    logger.debug(f"Position {symbol}: Including SL order {o.get('order_id')} - qty={order_quantity}, position={position_balance}, match={quantity_match}")
                                else:
                                    logger.info(f"Position {symbol}: Excluding SL order {o.get('order_id')} - qty={order_quantity} doesn't match position={position_balance} (diff: {abs(order_quantity - position_balance)})")
                            else:
                                # If no quantity info, assume active (legacy behavior)
                                active_sl_orders.append(o)
                                logger.debug(f"Position {symbol}: Including SL order {o.get('order_id')} - no quantity info, assuming active")
                        else:
                            logger.debug(f"Position {symbol}: Excluding SL order {o.get('order_id')} - status: {order_status}")
                    
                    for o in tp_orders_open:
                        order_status = o.get('order_status', '').upper() or o.get('status', '').upper()
                        order_quantity = float(o.get('quantity', 0) or o.get('qty', 0) or 0)
                        
                        # Only count orders that are ACTIVE, NEW, or PENDING
                        if order_status in ['ACTIVE', 'NEW', 'PENDING'] or not order_status:
                            # CRITICAL: Verify order quantity matches position balance (within 5% tolerance)
                            # This ensures we're not counting old orders from previous positions
                            if order_quantity > 0 and position_balance > 0:
                                quantity_match = abs(order_quantity - position_balance) / position_balance <= 0.05
                                if quantity_match:
                                    active_tp_orders.append(o)
                                    logger.debug(f"Position {symbol}: Including TP order {o.get('order_id')} - qty={order_quantity}, position={position_balance}, match={quantity_match}")
                                else:
                                    logger.info(f"Position {symbol}: Excluding TP order {o.get('order_id')} - qty={order_quantity} doesn't match position={position_balance} (diff: {abs(order_quantity - position_balance)})")
                            else:
                                # If no quantity info, assume active (legacy behavior)
                                active_tp_orders.append(o)
                                logger.debug(f"Position {symbol}: Including TP order {o.get('order_id')} - no quantity info, assuming active")
                        else:
                            logger.debug(f"Position {symbol}: Excluding TP order {o.get('order_id')} - status: {order_status}")
                    
                    has_sl = len(active_sl_orders) > 0
                    has_tp = len(active_tp_orders) > 0
                    
                    logger.info(f"Position {symbol}: Found {len(active_sl_orders)} active SL and {len(active_tp_orders)} active TP orders matching position balance={position_balance} (total found: {len(sl_orders_open)} SL, {len(tp_orders_open)} TP)")
                    if sl_orders_open:
                        logger.info(f"SL orders for {symbol}: {[(o.get('order_id'), o.get('order_status') or o.get('status', 'NO_STATUS'), o.get('quantity') or o.get('qty', 'NO_QTY')) for o in sl_orders_open]}")
                    if tp_orders_open:
                        logger.info(f"TP orders for {symbol}: {[(o.get('order_id'), o.get('order_status') or o.get('status', 'NO_STATUS'), o.get('quantity') or o.get('qty', 'NO_QTY')) for o in tp_orders_open]}")
                except Exception as e:
                    logger.warning(f"Error checking open orders from Exchange API for {symbol}: {e}")
                    # Fallback to database check
                    try:
                        from sqlalchemy import or_
                        # Check database for active orders (status NEW or ACTIVE, not FILLED)
                        sl_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        tp_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        has_sl = len(sl_orders_db) > 0
                        has_tp = len(tp_orders_db) > 0
                        logger.info(f"Position {symbol}: Found {len(sl_orders_db)} SL and {len(tp_orders_db)} TP orders from database")
                    except Exception as db_err:
                        logger.error(f"Error querying orders from database for {symbol}: {db_err}", exc_info=True)
                        has_sl = False
                        has_tp = False
                
                # has_sl and has_tp are now set from Exchange API or database fallback
                logger.info(f"Position {symbol}: Final check - has_sl={has_sl}, has_tp={has_tp}")
                
                # Check if user skipped reminder for this symbol
                skip_reminder = watchlist_item.skip_sl_tp_reminder if watchlist_item else False
                
                logger.info(f"Position {symbol}: has_sl={has_sl}, has_tp={has_tp}, skip_reminder={skip_reminder}, will_include={((not has_sl or not has_tp) and not skip_reminder)}")
                
                if (not has_sl or not has_tp) and not skip_reminder:
                    # Get SL/TP prices from watchlist if available
                    sl_price = watchlist_item.sl_price if watchlist_item else None
                    tp_price = watchlist_item.tp_price if watchlist_item else None
                    
                    positions_missing_sl_tp.append({
                        'symbol': symbol,
                        'currency': currency,
                        'balance': position['balance'],
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'sl_price': sl_price,
                        'tp_price': tp_price,
                        'watchlist_item': watchlist_item
                    })
            
            logger.info(f"Found {len(positions_missing_sl_tp)} positions missing SL/TP")
            
            # Check for OCO-related issues
            oco_issues = self._check_oco_issues(db)
            
            return {
                'positions_missing_sl_tp': positions_missing_sl_tp,
                'total_positions': len(open_positions),
                'oco_issues': oco_issues,
                'checked_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error checking positions for SL/TP: {e}", exc_info=True)
            return {
                'positions_missing_sl_tp': [],
                'total_positions': 0,
                'error': str(e)
            }
    
    def send_sl_tp_reminder(self, db: Session) -> bool:
        """
        Check positions and send Telegram reminder - one message per position
        Also sends OCO issues alerts
        
        Returns:
            bool: True if reminder was sent, False otherwise
        """
        try:
            # Check positions
            result = self.check_positions_for_sl_tp(db)
            positions_missing = result.get('positions_missing_sl_tp', [])
            oco_issues = result.get('oco_issues', {})
            
            if not positions_missing:
                logger.info("All positions have SL/TP orders, no reminder needed")
                return False
            
            # Send one message per position with specific options
            reminders_sent = 0
            for pos in positions_missing:
                symbol = pos['symbol']
                balance = pos['balance']
                has_sl = pos['has_sl']
                has_tp = pos['has_tp']
                sl_price = pos['sl_price']
                tp_price = pos['tp_price']
                currency = pos['currency']
                
                # Determine what's missing
                missing_items = []
                if not has_sl:
                    missing_items.append("SL")
                if not has_tp:
                    missing_items.append("TP")
                
                if not missing_items:
                    continue  # Skip if nothing is missing (shouldn't happen, but just in case)
                
                # Build message for this specific position
                message = f"⚠️ <b>UNPROTECTED POSITION: {symbol}</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                message += f"💰 Balance: {balance:.6f} {currency}\n\n"
                
                # Show status of SL and TP
                sl_status = "✅" if has_sl else "❌ MISSING"
                tp_status = "✅" if has_tp else "❌ MISSING"
                
                message += f"🛑 Stop Loss: {sl_status}"
                if sl_price:
                    message += f" @ ${sl_price:.4f}" if has_sl else f" (suggested price: ${sl_price:.4f})"
                message += "\n"
                
                message += f"🚀 Take Profit: {tp_status}"
                if tp_price:
                    message += f" @ ${tp_price:.4f}" if has_tp else f" (suggested price: ${tp_price:.4f})"
                message += "\n\n"
                
                # Show what's missing (buttons will provide options)
                if not has_sl and not has_tp:
                    # Missing both
                    message += "❌ Missing SL and TP\n\n"
                    message += "💡 Use buttons below to create orders:"
                elif not has_sl:
                    # Only missing SL
                    message += "❌ Missing SL\n\n"
                    message += "💡 Use buttons below to create order:"
                elif not has_tp:
                    # Only missing TP
                    message += "❌ Missing TP\n\n"
                    message += "💡 Use buttons below to create order:"
                
                # Build buttons based on what's missing
                buttons = []
                
                if not has_sl and not has_tp:
                    # Missing both - show buttons for both
                    buttons.append([
                        {"text": "✅ Create SL & TP", "callback_data": f"create_sl_tp_{symbol}"},
                    ])
                    buttons.append([
                        {"text": "🛑 SL Only", "callback_data": f"create_sl_{symbol}"},
                        {"text": "🚀 TP Only", "callback_data": f"create_tp_{symbol}"}
                    ])
                elif not has_sl:
                    # Only missing SL
                    buttons.append([
                        {"text": "🛑 Create SL", "callback_data": f"create_sl_{symbol}"}
                    ])
                elif not has_tp:
                    # Only missing TP
                    buttons.append([
                        {"text": "🚀 Create TP", "callback_data": f"create_tp_{symbol}"}
                    ])
                
                # Always add skip button at the end
                buttons.append([
                    {"text": "⏭️ Don't Ask Again", "callback_data": f"skip_sl_tp_{symbol}"}
                ])
                
                # Send individual message for this position with buttons
                try:
                    telegram_notifier.send_message_with_buttons(message, buttons)
                    reminders_sent += 1
                    logger.info(f"Sent SL/TP reminder for {symbol} with buttons (missing: {', '.join(missing_items)})")
                except Exception as e:
                    logger.error(f"Error sending Telegram reminder for {symbol}: {e}")
            
            logger.info(f"Sent {reminders_sent} SL/TP reminders (one per position)")
            
            # Send OCO issues alerts
            oco_alerts_sent = self._send_oco_alerts(oco_issues)
            
            # Store reminder state for later processing
            self.last_reminder_positions = positions_missing
            self.last_reminder_time = datetime.utcnow()
            
            return (reminders_sent > 0 or oco_alerts_sent > 0)
            
        except Exception as e:
            logger.error(f"Error sending SL/TP reminder: {e}", exc_info=True)
            return False
    
    def _send_oco_alerts(self, oco_issues: Dict) -> int:
        """Send Telegram alerts for OCO issues"""
        alerts_sent = 0
        
        try:
            orphaned = oco_issues.get('orphaned_orders', [])
            incomplete = oco_issues.get('incomplete_groups', [])
            
            if not orphaned and not incomplete:
                logger.info("No OCO issues found")
                return 0
            
            # Build message
            message = "🔧 <b>OCO SYSTEM HEALTH CHECK</b>\n\n"
            message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"📊 Total OCO Groups: {oco_issues.get('total_oco_groups', 0)}\n\n"
            
            if orphaned:
                message += f"⚠️ <b>ORPHANED ORDERS: {len(orphaned)}</b>\n\n"
                for order in orphaned:  # Show ALL orphaned orders
                    message += f"• <b>{order['symbol']}</b> - {order['type']}\n"
                    if order['price']:
                        message += f"  ${order['price']:,.4f}\n"
                    message += f"  Missing: {order['missing']}\n"
                    if order.get('order_id'):
                        message += f"  Order ID: {order['order_id']}\n"
                    message += "\n"
            
            if incomplete:
                message += f"❌ <b>INCOMPLETE GROUPS: {len(incomplete)}</b>\n\n"
                for group in incomplete:  # Show ALL incomplete groups
                    message += f"• <b>{group['symbol']}</b>\n"
                    message += f"  Has: {group.get('missing') and 'TP' if group.get('missing') == 'STOP_LOSS' else 'SL'}\n"
                    message += f"  Missing: {group['missing']}\n"
                    if group.get('oco_group_id'):
                        message += f"  OCO Group ID: {group['oco_group_id']}\n"
                    message += "\n"
            
            message += "💡 Review with /orders command"
            
            telegram_notifier.send_message(message)
            alerts_sent += 1
            logger.info(f"Sent OCO alert: {len(orphaned)} orphaned, {len(incomplete)} incomplete")
            
        except Exception as e:
            logger.error(f"Error sending OCO alerts: {e}", exc_info=True)
        
        return alerts_sent
    
    def create_sl_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only SL order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=False, force=force)
    
    def create_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only TP order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=False, create_tp=True, force=force)
    
    def _create_protection_order(self, db: Session, symbol: str, create_sl: bool = True, create_tp: bool = True, force: bool = False) -> Dict:
        """
        Internal method to create SL and/or TP orders for a position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            create_sl: Whether to create SL order
            create_tp: Whether to create TP order
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        try:
            # First, verify there's an open position
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            # Extract base currency from symbol (e.g., ETH from ETH_USDT)
            base_currency = symbol.split('_')[0] if '_' in symbol else symbol
            
            logger.debug(f"Looking for position balance for {symbol} (base currency: {base_currency})")
            logger.debug(f"Available accounts (first 5): {[(acc.get('currency'), acc.get('balance')) for acc in accounts[:5]]}")
            
            position_balance = 0.0
            for account in accounts:
                currency = account.get('currency', '').upper()
                balance_str = account.get('balance', '0')
                
                # Handle formats:
                # 1. currency = "ETH" -> matches base_currency "ETH"
                # 2. currency = "ETH_USDT" -> matches symbol "ETH_USDT"
                # 3. currency = "ETH/USDT" -> matches symbol "ETH_USDT"
                # 4. currency = "BONK/USD" -> matches symbol "BONK_USDT" (flexible)
                
                currency_normalized = currency.replace('/', '_').upper()
                symbol_normalized = symbol.upper()
                base_normalized = base_currency.upper()
                
                # Check if currency matches symbol directly or base currency
                matches = (
                    currency == symbol.upper() or  # Exact match: "ETH_USDT" == "ETH_USDT"
                    currency_normalized == symbol_normalized or  # Normalized match: "ETH/USDT" == "ETH_USDT"
                    currency == base_normalized or  # Base match: "ETH" == "ETH"
                    currency_normalized == base_normalized or  # Normalized base: "ETH/USDT" -> "ETH"
                    currency.startswith(base_normalized + '_') or  # Starts with base: "ETH_USDT" starts with "ETH_"
                    currency.startswith(base_normalized + '/')  # Starts with base and slash: "ETH/USDT" starts with "ETH/"
                )
                
                if matches:
                    try:
                        position_balance = float(balance_str)
                        logger.debug(f"Found balance for {currency}: {position_balance}")
                        if position_balance > 0:
                            break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid balance format for {currency}: {balance_str}, error: {e}")
                        continue
            
            if position_balance <= 0:
                available_currencies = [acc.get('currency') for acc in accounts[:10]]
                logger.warning(f"No open position found for {symbol}. Available currencies: {available_currencies}")
                return {
                    'success': False,
                    'error': f'No open position found for {symbol}. Please verify you have balance in {base_currency}.'
                }
            
            # Get watchlist item (if exists)
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            # If no watchlist item, create one with default values
            if not watchlist_item:
                logger.info(f"Watchlist item not found for {symbol}, creating with default values")
                
                # Get current price for calculations (skip if async - will get from order instead)
                current_price = None
                
                # Try to get entry price from most recent filled BUY order
                entry_price = None
                try:
                    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                    recent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                    
                    if recent_order:
                        entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                        logger.info(f"Found entry price from recent order: {entry_price}")
                except Exception as e:
                    logger.warning(f"Could not get entry price from orders: {e}")
                
                # Use entry price if available, otherwise use current price
                purchase_price = entry_price or current_price
                
                # Create watchlist item with default values
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    trade_enabled=False,
                    alert_enabled=False,
                    sl_tp_mode="conservative",
                    skip_sl_tp_reminder=False,
                    purchase_price=purchase_price,
                    price=current_price
                )
                db.add(watchlist_item)
                db.commit()
                logger.info(f"Created watchlist item for {symbol} with purchase_price={purchase_price}, current_price={current_price}")
            
            # Check if reminder was skipped
            if watchlist_item.skip_sl_tp_reminder and not force:
                return {
                    'success': False,
                    'error': f'SL/TP reminder skipped for {symbol} (use force=True to override)'
                }
            
            # Get SL/TP prices from watchlist
            sl_price = watchlist_item.sl_price
            tp_price = watchlist_item.tp_price
            
            # Calculate from percentages if prices not available
            if (create_sl and not sl_price) or (create_tp and not tp_price):
                # Get entry price: ALWAYS use filled BUY order price if available
                entry_price = None
                
                # 1. ALWAYS try to get from most recent filled BUY order (most accurate entry price)
                from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                recent_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status == OrderStatusEnum.FILLED
                ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                
                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    if entry_price:
                        logger.info(f"✅ Using entry price from filled BUY order for {symbol}: {entry_price} (Order ID: {recent_order.exchange_order_id})")
                    else:
                        logger.warning(f"⚠️ Filled BUY order found for {symbol} but price is None (Order ID: {recent_order.exchange_order_id})")
                
                # 2. Fallback: use purchase_price from watchlist (only if no BUY order found)
                if not entry_price:
                    entry_price = watchlist_item.purchase_price
                    if entry_price:
                        logger.info(f"Using purchase_price from watchlist for {symbol}: {entry_price} (no filled BUY order found)")
                
                # 3. Last resort: use last known price from watchlist (only if no BUY order and no purchase_price)
                if not entry_price:
                    entry_price = watchlist_item.price
                    if entry_price:
                        logger.info(f"Using last known price from watchlist for {symbol}: {entry_price} (no filled BUY order or purchase_price found)")
                
                # 4. Final fallback: if we have an open position but no entry price, use current market price
                # This handles cases where position exists but order history is missing
                if not entry_price and position_balance > 0:
                    try:
                        import sys
                        # Add parent directory to path to import simple_price_fetcher
                        # os is already imported at the top of the file
                        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if parent_dir not in sys.path:
                            sys.path.insert(0, parent_dir)
                        from simple_price_fetcher import get_price
                        current_market_price = get_price(symbol)
                        if current_market_price and current_market_price > 0:
                            entry_price = current_market_price
                            logger.warning(f"⚠️ Using current market price as entry price for {symbol}: {entry_price} (position exists but no BUY order found in database)")
                            # Update watchlist_item with current price for future use
                            watchlist_item.price = entry_price
                            if not watchlist_item.purchase_price:
                                watchlist_item.purchase_price = entry_price
                            db.commit()
                    except Exception as e:
                        logger.warning(f"Could not fetch current market price for {symbol}: {e}")
                
                if not entry_price:
                    return {
                        'success': False,
                        'error': f'Cannot determine entry price for {symbol}. No filled BUY order found in database. Please ensure there is a recent filled BUY order, or configure purchase_price/price in watchlist.'
                    }
                
                # Get strategy mode and percentages
                strategy_mode = watchlist_item.sl_tp_mode or "conservative"
                
                # Use configured percentages or defaults based on strategy
                if watchlist_item.sl_percentage is not None:
                    sl_percentage = watchlist_item.sl_percentage
                else:
                    # Default percentages based on strategy
                    sl_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                
                if watchlist_item.tp_percentage is not None:
                    tp_percentage = watchlist_item.tp_percentage
                else:
                    # Default percentages based on strategy
                    tp_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                
                logger.info(f"Calculating SL/TP for {symbol}: entry_price={entry_price}, strategy={strategy_mode}, sl_percentage={sl_percentage}%, tp_percentage={tp_percentage}%")
                
                # Calculate SL/TP from entry price using strategy percentages
                if create_sl and not sl_price:
                    sl_price = entry_price * (1 - sl_percentage / 100)
                    logger.info(f"Calculated SL price for {symbol}: {sl_price} (entry: {entry_price}, -{sl_percentage}%)")
                
                if create_tp and not tp_price:
                    tp_price = entry_price * (1 + tp_percentage / 100)
                    logger.info(f"Calculated TP price for {symbol}: {tp_price} (entry: {entry_price}, +{tp_percentage}%)")
            
            # Round prices to reasonable precision before passing to exchange
            # The exchange will further format according to instrument tick size
            if sl_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
            if tp_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)
            
            live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            dry_run_mode = not live_trading
            
            # Ensure entry_price is available for order creation (even if prices were already set)
            if not entry_price:
                # Try to get entry price from most recent filled BUY order
                from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                recent_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status == OrderStatusEnum.FILLED
                ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                
                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    if entry_price:
                        logger.info(f"✅ Using entry price from filled BUY order for {symbol}: {entry_price} (Order ID: {recent_order.exchange_order_id})")
            
            # Get parent order ID from most recent filled BUY order (for linking TP/SL)
            parent_order_id = None
            oco_group_id = None
            if entry_price:
                try:
                    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                    recent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                    
                    if recent_order:
                        parent_order_id = recent_order.exchange_order_id
                        # Generate OCO group ID for linking SL and TP orders (same as automatic creation)
                        import uuid
                        oco_group_id = f"oco_{parent_order_id}_{int(datetime.utcnow().timestamp())}"
                        logger.info(f"Found parent order {parent_order_id} for {symbol}, using OCO group: {oco_group_id}")
                except Exception as e:
                    logger.warning(f"Could not get parent order ID for {symbol}: {e}")
            
            # Use the reusable TP/SL order creator functions (same as automatic creation)
            # Create SL order if requested
            sl_order_id = None
            sl_error = None
            if create_sl and sl_price and entry_price:
                sl_result = create_stop_loss_order(
                    db=db,
                    symbol=symbol,
                    side="BUY",  # Original order side (we assume BUY positions)
                    sl_price=sl_price,
                    quantity=position_balance,
                    entry_price=entry_price,
                    parent_order_id=parent_order_id,
                    oco_group_id=oco_group_id,
                    dry_run=dry_run_mode,
                    source="manual"
                )
                sl_order_id = sl_result.get("order_id")
                sl_error = sl_result.get("error")
            
            # Create TP order if requested
            tp_order_id = None
            tp_error = None
            if create_tp and tp_price and entry_price:
                tp_result = create_take_profit_order(
                    db=db,
                    symbol=symbol,
                    side="BUY",  # Original order side (we assume BUY positions)
                    tp_price=tp_price,
                    quantity=position_balance,
                    entry_price=entry_price,
                    parent_order_id=parent_order_id,
                    oco_group_id=oco_group_id,
                    dry_run=dry_run_mode,
                    source="manual"
                )
                tp_order_id = tp_result.get("order_id")
                tp_error = tp_result.get("error")
            
            # Send notification
            if sl_order_id or tp_order_id:
                try:
                    # Get percentages from watchlist or calculate from prices
                    sl_pct = watchlist_item.sl_percentage if watchlist_item.sl_percentage else None
                    tp_pct = watchlist_item.tp_percentage if watchlist_item.tp_percentage else None
                    
                    # If percentages not set, calculate from entry price and SL/TP prices
                    if entry_price and entry_price > 0:
                        if not sl_pct and sl_price:
                            sl_pct = abs((entry_price - sl_price) / entry_price * 100)
                        if not tp_pct and tp_price:
                            tp_pct = abs((tp_price - entry_price) / entry_price * 100)
                    
                    telegram_notifier.send_sl_tp_orders(
                        symbol=symbol,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        quantity=position_balance,
                        mode=watchlist_item.sl_tp_mode or "conservative",
                        sl_order_id=str(sl_order_id) if sl_order_id else None,
                        tp_order_id=str(tp_order_id) if tp_order_id else None,
                        original_order_id=None,
                        entry_price=entry_price,
                        sl_percentage=sl_pct,
                        tp_percentage=tp_pct
                    )
                    logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - {e}", exc_info=True)
            
            success = (create_sl and sl_order_id) or (create_tp and tp_order_id) or (not create_sl and not create_tp)
            
            # If there's an error and no success, include it in the main error field
            main_error = None
            if not success:
                if create_sl and sl_error:
                    main_error = f"SL order failed: {sl_error}"
                elif create_tp and tp_error:
                    main_error = f"TP order failed: {tp_error}"
                elif create_sl and not sl_order_id:
                    main_error = sl_error or "SL order creation failed (unknown reason)"
                elif create_tp and not tp_order_id:
                    main_error = tp_error or "TP order creation failed (unknown reason)"
            
            return {
                'success': success,
                'symbol': symbol,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'sl_error': sl_error,
                'tp_error': tp_error,
                'error': main_error,  # Add main error field for easier access
                'dry_run': dry_run_mode
            }
            
        except Exception as e:
            logger.error(f"Error creating protection order for position {symbol}: {e}", exc_info=True)
            error_msg = str(e)
            # Provide more specific error message
            if "Watchlist item not found" in error_msg:
                return {
                    'success': False,
                    'error': f'Watchlist item not found for {symbol}. First add {symbol} to watchlist.'
                }
            elif "No open position" in error_msg:
                return {
                    'success': False,
                    'error': error_msg  # Already has good message
                }
            else:
                return {
                    'success': False,
                    'error': f'Error creating order: {error_msg}'
                }
    
    def create_sl_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create both SL and TP orders for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=True, force=force)
    
    def skip_reminder_for_symbol(self, db: Session, symbol: str) -> bool:
        """Mark symbol to skip SL/TP reminders"""
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if not watchlist_item:
                # Create watchlist item if it doesn't exist
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    skip_sl_tp_reminder=True
                )
                db.add(watchlist_item)
            else:
                watchlist_item.skip_sl_tp_reminder = True
            
            db.commit()
            logger.info(f"Marked {symbol} to skip SL/TP reminders")
            return True
            
        except Exception as e:
            logger.error(f"Error skipping reminder for {symbol}: {e}")
            db.rollback()
            return False


# Global instance
sl_tp_checker_service = SLTPCheckerService()


"""
SL/TP Checker Service
Checks all open positions for missing SL/TP orders and sends Telegram alerts
"""
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.services.exchange_sync import exchange_sync_service
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order

logger = logging.getLogger(__name__)


class SLTPCheckerService:
    """Service to check open positions for missing SL/TP orders and OCO integrity"""
    
    def __init__(self):
        self.last_check_date = None
    
    def _check_oco_issues(self, db: Session) -> Dict:
        """
        Check for OCO-related issues
        Returns: Dict with orphaned orders and incomplete groups
        """
        issues = {'orphaned_orders': [], 'incomplete_groups': [], 'total_oco_groups': 0}
        
        try:
            # Find active SL/TP orders
            active_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            logger.info(f"Checking {len(active_sl_tp)} active SL/TP orders for OCO issues")
            
            # Check for orphaned orders
            for order in active_sl_tp:
                if not order.parent_order_id or not order.oco_group_id:
                    issues['orphaned_orders'].append({
                        'order_id': order.exchange_order_id,
                        'symbol': order.symbol,
                        'type': order.order_role or order.order_type,
                        'price': float(order.price) if order.price else None,
                        'missing': 'parent_order_id' if not order.parent_order_id else 'oco_group_id',
                        'quantity': float(order.quantity) if order.quantity else None
                    })
            
            # Group by oco_group_id
            from collections import defaultdict
            oco_groups = defaultdict(list)
            for order in active_sl_tp:
                if order.oco_group_id:
                    oco_groups[order.oco_group_id].append(order)
            
            issues['total_oco_groups'] = len(oco_groups)
            
            # Check for incomplete groups
            for oco_id, orders in oco_groups.items():
                has_sl = any(o.order_role == "STOP_LOSS" for o in orders)
                has_tp = any(o.order_role == "TAKE_PROFIT" for o in orders)
                
                if not (has_sl and has_tp):
                    symbol = orders[0].symbol if orders else "Unknown"
                    issues['incomplete_groups'].append({
                        'oco_group_id': oco_id,
                        'symbol': symbol,
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'missing': "STOP_LOSS" if not has_sl else "TAKE_PROFIT"
                    })
            
            logger.info(f"OCO check: {len(issues['orphaned_orders'])} orphaned, {len(issues['incomplete_groups'])} incomplete")
            
        except Exception as e:
            logger.error(f"Error checking OCO issues: {e}", exc_info=True)
            issues['error'] = str(e)
        
        return issues
    
    def check_positions_for_sl_tp(self, db: Session) -> Dict:
        """
        Check all open positions and verify if they have SL/TP orders
        
        Returns:
            Dict with positions missing SL/TP
        """
        try:
            # Get account balance to find open positions
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            logger.info(f"Received {len(accounts)} accounts from get_account_summary")
            if len(accounts) > 0:
                logger.info(f"Sample account: {accounts[0]}")
            
            # Filter positions with positive balance (excluding USDT/USD)
            open_positions = []
            for account in accounts:
                # Handle both 'currency' and 'instrument_name' fields
                currency = account.get('currency', '').upper()
                if not currency:
                    # Try instrument_name if currency is not available
                    currency = account.get('instrument_name', '').upper()
                
                if not currency:
                    logger.warning(f"Account missing currency/instrument_name: {account}")
                    continue
                    
                balance_str = account.get('balance', '0')
                
                # Handle balance format - could be string or number
                try:
                    balance = float(balance_str)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid balance format for {currency}: {balance_str}")
                    continue
                
                # Skip if balance is zero or negative
                if balance <= 0:
                    logger.debug(f"Skipping {currency} - balance is {balance}")
                    continue
                
                # Handle currency format - could be "ETH" or "ETH_USDT"
                if '_' in currency:
                    # Format is already like "ETH_USDT" - extract base currency
                    base_currency = currency.split('_')[0]
                    symbol = currency  # Keep full symbol for later use
                else:
                    # Format is just currency like "ETH" - assume USDT pair
                    base_currency = currency
                    symbol = f"{currency}_USDT"
                
                # Skip stablecoins (USDT, USD, USDC, etc.) and fiat (EUR, GBP, JPY, etc.)
                stablecoins = ['USDT', 'USD', 'USDC', 'BUSD', 'DAI', 'TUSD']
                fiat = ['EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'CHF', 'NZD', 'SGD', 'HKD', 'KRW']
                if base_currency in stablecoins or base_currency in fiat:
                    logger.debug(f"Skipping stablecoin/fiat: {base_currency}")
                    continue
                
                open_positions.append({
                    'currency': base_currency,
                    'symbol': symbol,
                    'balance': balance
                })
                
                logger.info(f"Found open position: {symbol} ({base_currency}) = {balance}")
            
            logger.info(f"Found {len(open_positions)} open positions to check for SL/TP")
            
            # For each position, check if there are active SL/TP orders
            positions_missing_sl_tp = []
            
            for position in open_positions:
                currency = position['currency']
                symbol = position.get('symbol', f"{currency}_USDT")  # Use symbol from position or default
                
                # Create symbol variants to check (BONK_USDT, BONK_USD, etc.)
                symbol_variants = [symbol]
                if symbol.endswith('_USDT'):
                    symbol_variants.append(symbol.replace('_USDT', '_USD'))
                elif symbol.endswith('_USD'):
                    symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Try to find symbol in watchlist - try exact match first
                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
                
                if not watchlist_item:
                    # Try pattern match
                    watchlist_item = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol.like(f"%{currency}%")
                    ).first()
                    if watchlist_item:
                        symbol = watchlist_item.symbol  # Use symbol from watchlist if found
                        # Update symbol variants
                        symbol_variants = [symbol]
                        if symbol.endswith('_USDT'):
                            symbol_variants.append(symbol.replace('_USDT', '_USD'))
                        elif symbol.endswith('_USD'):
                            symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Check for active SL/TP orders from Crypto.com Exchange API directly
                # This is more reliable than checking database status
                has_sl = False
                has_tp = False
                
                try:
                    # Get ALL open orders (trigger orders may not be filtered by symbol in the API)
                    all_open_orders = trade_client.get_open_orders()
                    all_orders_data = all_open_orders.get('data', [])
                    
                    logger.debug(f"Retrieved {len(all_orders_data)} total open orders from Exchange")
                    if all_orders_data:
                        # Log sample to understand format
                        sample_order = all_orders_data[0] if len(all_orders_data) > 0 else {}
                        logger.debug(f"Sample order: instrument={sample_order.get('instrument_name')}, type={sample_order.get('order_type')}, symbol_variants={symbol_variants}")
                    
                    # Filter orders for this symbol and variants
                    # Handle both BONK/USD (with slash) and BONK_USD (with underscore)
                    open_orders_data = []
                    for order in all_orders_data:
                        order_instrument = order.get('instrument_name', '')
                        # Normalize: convert slash to underscore for comparison
                        order_symbol_normalized = order_instrument.replace('/', '_').upper()
                        variant_normalized = [v.upper() for v in symbol_variants]
                        
                        # Check if this order matches our symbol or variants
                        if order_symbol_normalized in variant_normalized or \
                           any(v.replace('_', '/') == order_instrument for v in symbol_variants):
                            open_orders_data.append(order)
                            logger.debug(f"Matched order: {order_instrument} (normalized: {order_symbol_normalized}) for {symbol}")
                    
                    logger.debug(f"Filtered {len(open_orders_data)} orders for {symbol} from {len(all_orders_data)} total orders")
                    
                    # Filter for SL/TP orders with flexible matching
                    sl_orders_open = []
                    tp_orders_open = []
                    
                    for o in open_orders_data:
                        order_type = o.get('order_type', '')
                        order_type_lower = order_type.lower()
                        order_type_upper = order_type.upper()
                        
                        # Check for SL orders (Stop Loss / Stop Limit)
                        if any(sl_term in order_type_lower for sl_term in ['stop', 'stop_loss', 'stop_loss_limit']):
                            sl_orders_open.append(o)
                            logger.debug(f"Found SL order for {symbol}: {order_type} - {o.get('order_id')}")
                        
                        # Check for TP orders (Take Profit)
                        if any(tp_term in order_type_lower for tp_term in ['take-profit', 'take_profit', 'take profit', 'profit_limit']) or \
                           'profit' in order_type_lower and 'take' in order_type_lower:
                            tp_orders_open.append(o)
                            logger.debug(f"Found TP order for {symbol}: {order_type} - {o.get('order_id')}")
                    
                    logger.info(f"Position {symbol}: Filtered {len(sl_orders_open)} SL and {len(tp_orders_open)} TP orders from {len(open_orders_data)} matched orders")
                    
                    has_sl = len(sl_orders_open) > 0
                    has_tp = len(tp_orders_open) > 0
                    
                    logger.info(f"Position {symbol}: Found {len(sl_orders_open)} SL and {len(tp_orders_open)} TP orders from Exchange API")
                    if tp_orders_open:
                        logger.info(f"TP orders for {symbol}: {[o.get('order_id') for o in tp_orders_open]}")
                except Exception as e:
                    logger.warning(f"Error checking open orders from Exchange API for {symbol}: {e}")
                    # Fallback to database check
                    try:
                        from sqlalchemy import or_
                        # Check database for active orders (status NEW or ACTIVE, not FILLED)
                        sl_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['STOP_LIMIT', 'STOP_LOSS']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        tp_orders_db = db.query(ExchangeOrder).filter(
                            or_(*[ExchangeOrder.symbol == variant for variant in symbol_variants]),
                            ExchangeOrder.order_type.in_(['TAKE_PROFIT_LIMIT', 'TAKE_PROFIT']),
                            ExchangeOrder.status.in_([
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PENDING
                            ])
                        ).all()
                        
                        has_sl = len(sl_orders_db) > 0
                        has_tp = len(tp_orders_db) > 0
                        logger.info(f"Position {symbol}: Found {len(sl_orders_db)} SL and {len(tp_orders_db)} TP orders from database")
                    except Exception as db_err:
                        logger.error(f"Error querying orders from database for {symbol}: {db_err}", exc_info=True)
                        has_sl = False
                        has_tp = False
                
                # has_sl and has_tp are now set from Exchange API or database fallback
                logger.info(f"Position {symbol}: Final check - has_sl={has_sl}, has_tp={has_tp}")
                
                # Check if user skipped reminder for this symbol
                skip_reminder = watchlist_item.skip_sl_tp_reminder if watchlist_item else False
                
                logger.info(f"Position {symbol}: has_sl={has_sl}, has_tp={has_tp}, skip_reminder={skip_reminder}, will_include={((not has_sl or not has_tp) and not skip_reminder)}")
                
                if (not has_sl or not has_tp) and not skip_reminder:
                    # Get SL/TP prices from watchlist if available
                    sl_price = watchlist_item.sl_price if watchlist_item else None
                    tp_price = watchlist_item.tp_price if watchlist_item else None
                    
                    positions_missing_sl_tp.append({
                        'symbol': symbol,
                        'currency': currency,
                        'balance': position['balance'],
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'sl_price': sl_price,
                        'tp_price': tp_price,
                        'watchlist_item': watchlist_item
                    })
            
            logger.info(f"Found {len(positions_missing_sl_tp)} positions missing SL/TP")
            
            # Check for OCO-related issues
            oco_issues = self._check_oco_issues(db)
            
            return {
                'positions_missing_sl_tp': positions_missing_sl_tp,
                'total_positions': len(open_positions),
                'oco_issues': oco_issues,
                'checked_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error checking positions for SL/TP: {e}", exc_info=True)
            return {
                'positions_missing_sl_tp': [],
                'total_positions': 0,
                'error': str(e)
            }
    
    def send_sl_tp_reminder(self, db: Session) -> bool:
        """
        Check positions and send Telegram reminder - one message per position
        Also sends OCO issues alerts
        
        Returns:
            bool: True if reminder was sent, False otherwise
        """
        try:
            # Check positions
            result = self.check_positions_for_sl_tp(db)
            positions_missing = result.get('positions_missing_sl_tp', [])
            oco_issues = result.get('oco_issues', {})
            
            if not positions_missing:
                logger.info("All positions have SL/TP orders, no reminder needed")
                return False
            
            # Send one message per position with specific options
            reminders_sent = 0
            for pos in positions_missing:
                symbol = pos['symbol']
                balance = pos['balance']
                has_sl = pos['has_sl']
                has_tp = pos['has_tp']
                sl_price = pos['sl_price']
                tp_price = pos['tp_price']
                currency = pos['currency']
                
                # Determine what's missing
                missing_items = []
                if not has_sl:
                    missing_items.append("SL")
                if not has_tp:
                    missing_items.append("TP")
                
                if not missing_items:
                    continue  # Skip if nothing is missing (shouldn't happen, but just in case)
                
                # Build message for this specific position
                message = f"⚠️ <b>UNPROTECTED POSITION: {symbol}</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                message += f"💰 Balance: {balance:.6f} {currency}\n\n"
                
                # Show status of SL and TP
                sl_status = "✅" if has_sl else "❌ MISSING"
                tp_status = "✅" if has_tp else "❌ MISSING"
                
                message += f"🛑 Stop Loss: {sl_status}"
                if sl_price:
                    message += f" @ ${sl_price:.4f}" if has_sl else f" (suggested price: ${sl_price:.4f})"
                message += "\n"
                
                message += f"🚀 Take Profit: {tp_status}"
                if tp_price:
                    message += f" @ ${tp_price:.4f}" if has_tp else f" (suggested price: ${tp_price:.4f})"
                message += "\n\n"
                
                # Show what's missing (buttons will provide options)
                if not has_sl and not has_tp:
                    # Missing both
                    message += "❌ Missing SL and TP\n\n"
                    message += "💡 Use buttons below to create orders:"
                elif not has_sl:
                    # Only missing SL
                    message += "❌ Missing SL\n\n"
                    message += "💡 Use buttons below to create order:"
                elif not has_tp:
                    # Only missing TP
                    message += "❌ Missing TP\n\n"
                    message += "💡 Use buttons below to create order:"
                
                # Build buttons based on what's missing
                buttons = []
                
                if not has_sl and not has_tp:
                    # Missing both - show buttons for both
                    buttons.append([
                        {"text": "✅ Create SL & TP", "callback_data": f"create_sl_tp_{symbol}"},
                    ])
                    buttons.append([
                        {"text": "🛑 SL Only", "callback_data": f"create_sl_{symbol}"},
                        {"text": "🚀 TP Only", "callback_data": f"create_tp_{symbol}"}
                    ])
                elif not has_sl:
                    # Only missing SL
                    buttons.append([
                        {"text": "🛑 Create SL", "callback_data": f"create_sl_{symbol}"}
                    ])
                elif not has_tp:
                    # Only missing TP
                    buttons.append([
                        {"text": "🚀 Create TP", "callback_data": f"create_tp_{symbol}"}
                    ])
                
                # Always add skip button at the end
                buttons.append([
                    {"text": "⏭️ Don't Ask Again", "callback_data": f"skip_sl_tp_{symbol}"}
                ])
                
                # Send individual message for this position with buttons
                try:
                    telegram_notifier.send_message_with_buttons(message, buttons)
                    reminders_sent += 1
                    logger.info(f"Sent SL/TP reminder for {symbol} with buttons (missing: {', '.join(missing_items)})")
                except Exception as e:
                    logger.error(f"Error sending Telegram reminder for {symbol}: {e}")
            
            logger.info(f"Sent {reminders_sent} SL/TP reminders (one per position)")
            
            # Send OCO issues alerts
            oco_alerts_sent = self._send_oco_alerts(oco_issues)
            
            # Store reminder state for later processing
            self.last_reminder_positions = positions_missing
            self.last_reminder_time = datetime.utcnow()
            
            return (reminders_sent > 0 or oco_alerts_sent > 0)
            
        except Exception as e:
            logger.error(f"Error sending SL/TP reminder: {e}", exc_info=True)
            return False
    
    def _send_oco_alerts(self, oco_issues: Dict) -> int:
        """Send Telegram alerts for OCO issues"""
        alerts_sent = 0
        
        try:
            orphaned = oco_issues.get('orphaned_orders', [])
            incomplete = oco_issues.get('incomplete_groups', [])
            
            if not orphaned and not incomplete:
                logger.info("No OCO issues found")
                return 0
            
            # Build message
            message = "🔧 <b>OCO SYSTEM HEALTH CHECK</b>\n\n"
            message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"📊 Total OCO Groups: {oco_issues.get('total_oco_groups', 0)}\n\n"
            
            if orphaned:
                message += f"⚠️ <b>ORPHANED ORDERS: {len(orphaned)}</b>\n\n"
                for order in orphaned:  # Show ALL orphaned orders
                    message += f"• <b>{order['symbol']}</b> - {order['type']}\n"
                    if order['price']:
                        message += f"  ${order['price']:,.4f}\n"
                    message += f"  Missing: {order['missing']}\n"
                    if order.get('order_id'):
                        message += f"  Order ID: {order['order_id']}\n"
                    message += "\n"
            
            if incomplete:
                message += f"❌ <b>INCOMPLETE GROUPS: {len(incomplete)}</b>\n\n"
                for group in incomplete:  # Show ALL incomplete groups
                    message += f"• <b>{group['symbol']}</b>\n"
                    message += f"  Has: {group.get('missing') and 'TP' if group.get('missing') == 'STOP_LOSS' else 'SL'}\n"
                    message += f"  Missing: {group['missing']}\n"
                    if group.get('oco_group_id'):
                        message += f"  OCO Group ID: {group['oco_group_id']}\n"
                    message += "\n"
            
            message += "💡 Review with /orders command"
            
            telegram_notifier.send_message(message)
            alerts_sent += 1
            logger.info(f"Sent OCO alert: {len(orphaned)} orphaned, {len(incomplete)} incomplete")
            
        except Exception as e:
            logger.error(f"Error sending OCO alerts: {e}", exc_info=True)
        
        return alerts_sent
    
    def create_sl_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only SL order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=False, force=force)
    
    def create_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only TP order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=False, create_tp=True, force=force)
    
    def _create_protection_order(self, db: Session, symbol: str, create_sl: bool = True, create_tp: bool = True, force: bool = False) -> Dict:
        """
        Internal method to create SL and/or TP orders for a position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            create_sl: Whether to create SL order
            create_tp: Whether to create TP order
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        try:
            # First, verify there's an open position
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            # Extract base currency from symbol (e.g., ETH from ETH_USDT)
            base_currency = symbol.split('_')[0] if '_' in symbol else symbol
            
            logger.debug(f"Looking for position balance for {symbol} (base currency: {base_currency})")
            logger.debug(f"Available accounts (first 5): {[(acc.get('currency'), acc.get('balance')) for acc in accounts[:5]]}")
            
            position_balance = 0.0
            for account in accounts:
                currency = account.get('currency', '').upper()
                balance_str = account.get('balance', '0')
                
                # Handle formats:
                # 1. currency = "ETH" -> matches base_currency "ETH"
                # 2. currency = "ETH_USDT" -> matches symbol "ETH_USDT"
                # 3. currency = "ETH/USDT" -> matches symbol "ETH_USDT"
                # 4. currency = "BONK/USD" -> matches symbol "BONK_USDT" (flexible)
                
                currency_normalized = currency.replace('/', '_').upper()
                symbol_normalized = symbol.upper()
                base_normalized = base_currency.upper()
                
                # Check if currency matches symbol directly or base currency
                matches = (
                    currency == symbol.upper() or  # Exact match: "ETH_USDT" == "ETH_USDT"
                    currency_normalized == symbol_normalized or  # Normalized match: "ETH/USDT" == "ETH_USDT"
                    currency == base_normalized or  # Base match: "ETH" == "ETH"
                    currency_normalized == base_normalized or  # Normalized base: "ETH/USDT" -> "ETH"
                    currency.startswith(base_normalized + '_') or  # Starts with base: "ETH_USDT" starts with "ETH_"
                    currency.startswith(base_normalized + '/')  # Starts with base and slash: "ETH/USDT" starts with "ETH/"
                )
                
                if matches:
                    try:
                        position_balance = float(balance_str)
                        logger.debug(f"Found balance for {currency}: {position_balance}")
                        if position_balance > 0:
                            break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid balance format for {currency}: {balance_str}, error: {e}")
                        continue
            
            if position_balance <= 0:
                available_currencies = [acc.get('currency') for acc in accounts[:10]]
                logger.warning(f"No open position found for {symbol}. Available currencies: {available_currencies}")
                return {
                    'success': False,
                    'error': f'No open position found for {symbol}. Please verify you have balance in {base_currency}.'
                }
            
            # Get watchlist item (if exists)
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            # If no watchlist item, create one with default values
            if not watchlist_item:
                logger.info(f"Watchlist item not found for {symbol}, creating with default values")
                
                # Get current price for calculations (skip if async - will get from order instead)
                current_price = None
                
                # Try to get entry price from most recent filled BUY order
                entry_price = None
                try:
                    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                    recent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                    
                    if recent_order:
                        entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                        logger.info(f"Found entry price from recent order: {entry_price}")
                except Exception as e:
                    logger.warning(f"Could not get entry price from orders: {e}")
                
                # Use entry price if available, otherwise use current price
                purchase_price = entry_price or current_price
                
                # Create watchlist item with default values
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    trade_enabled=False,
                    alert_enabled=False,
                    sl_tp_mode="conservative",
                    skip_sl_tp_reminder=False,
                    purchase_price=purchase_price,
                    price=current_price
                )
                db.add(watchlist_item)
                db.commit()
                logger.info(f"Created watchlist item for {symbol} with purchase_price={purchase_price}, current_price={current_price}")
            
            # Check if reminder was skipped
            if watchlist_item.skip_sl_tp_reminder and not force:
                return {
                    'success': False,
                    'error': f'SL/TP reminder skipped for {symbol} (use force=True to override)'
                }
            
            # Get SL/TP prices from watchlist
            sl_price = watchlist_item.sl_price
            tp_price = watchlist_item.tp_price
            
            # Calculate from percentages if prices not available
            if (create_sl and not sl_price) or (create_tp and not tp_price):
                # Get entry price: ALWAYS use filled BUY order price if available
                entry_price = None
                
                # 1. ALWAYS try to get from most recent filled BUY order (most accurate entry price)
                from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                recent_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status == OrderStatusEnum.FILLED
                ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                
                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    if entry_price:
                        logger.info(f"✅ Using entry price from filled BUY order for {symbol}: {entry_price} (Order ID: {recent_order.exchange_order_id})")
                    else:
                        logger.warning(f"⚠️ Filled BUY order found for {symbol} but price is None (Order ID: {recent_order.exchange_order_id})")
                
                # 2. Fallback: use purchase_price from watchlist (only if no BUY order found)
                if not entry_price:
                    entry_price = watchlist_item.purchase_price
                    if entry_price:
                        logger.info(f"Using purchase_price from watchlist for {symbol}: {entry_price} (no filled BUY order found)")
                
                # 3. Last resort: use last known price from watchlist (only if no BUY order and no purchase_price)
                if not entry_price:
                    entry_price = watchlist_item.price
                    if entry_price:
                        logger.info(f"Using last known price from watchlist for {symbol}: {entry_price} (no filled BUY order or purchase_price found)")
                
                # 4. Final fallback: if we have an open position but no entry price, use current market price
                # This handles cases where position exists but order history is missing
                if not entry_price and position_balance > 0:
                    try:
                        import sys
                        # Add parent directory to path to import simple_price_fetcher
                        # os is already imported at the top of the file
                        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        if parent_dir not in sys.path:
                            sys.path.insert(0, parent_dir)
                        from simple_price_fetcher import get_price
                        current_market_price = get_price(symbol)
                        if current_market_price and current_market_price > 0:
                            entry_price = current_market_price
                            logger.warning(f"⚠️ Using current market price as entry price for {symbol}: {entry_price} (position exists but no BUY order found in database)")
                            # Update watchlist_item with current price for future use
                            watchlist_item.price = entry_price
                            if not watchlist_item.purchase_price:
                                watchlist_item.purchase_price = entry_price
                            db.commit()
                    except Exception as e:
                        logger.warning(f"Could not fetch current market price for {symbol}: {e}")
                
                if not entry_price:
                    return {
                        'success': False,
                        'error': f'Cannot determine entry price for {symbol}. No filled BUY order found in database. Please ensure there is a recent filled BUY order, or configure purchase_price/price in watchlist.'
                    }
                
                # Get strategy mode and percentages
                strategy_mode = watchlist_item.sl_tp_mode or "conservative"
                
                # Use configured percentages or defaults based on strategy
                if watchlist_item.sl_percentage is not None:
                    sl_percentage = watchlist_item.sl_percentage
                else:
                    # Default percentages based on strategy
                    sl_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                
                if watchlist_item.tp_percentage is not None:
                    tp_percentage = watchlist_item.tp_percentage
                else:
                    # Default percentages based on strategy
                    tp_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                
                logger.info(f"Calculating SL/TP for {symbol}: entry_price={entry_price}, strategy={strategy_mode}, sl_percentage={sl_percentage}%, tp_percentage={tp_percentage}%")
                
                # Calculate SL/TP from entry price using strategy percentages
                if create_sl and not sl_price:
                    sl_price = entry_price * (1 - sl_percentage / 100)
                    logger.info(f"Calculated SL price for {symbol}: {sl_price} (entry: {entry_price}, -{sl_percentage}%)")
                
                if create_tp and not tp_price:
                    tp_price = entry_price * (1 + tp_percentage / 100)
                    logger.info(f"Calculated TP price for {symbol}: {tp_price} (entry: {entry_price}, +{tp_percentage}%)")
            
            # Round prices to reasonable precision before passing to exchange
            # The exchange will further format according to instrument tick size
            if sl_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
            if tp_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)
            
            live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            dry_run_mode = not live_trading
            
            # Ensure entry_price is available for order creation (even if prices were already set)
            if not entry_price:
                # Try to get entry price from most recent filled BUY order
                from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                recent_order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status == OrderStatusEnum.FILLED
                ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                
                if recent_order:
                    entry_price = float(recent_order.avg_price) if recent_order.avg_price else float(recent_order.price) if recent_order.price else None
                    if entry_price:
                        logger.info(f"✅ Using entry price from filled BUY order for {symbol}: {entry_price} (Order ID: {recent_order.exchange_order_id})")
            
            # Get parent order ID from most recent filled BUY order (for linking TP/SL)
            parent_order_id = None
            oco_group_id = None
            if entry_price:
                try:
                    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
                    recent_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                    
                    if recent_order:
                        parent_order_id = recent_order.exchange_order_id
                        # Generate OCO group ID for linking SL and TP orders (same as automatic creation)
                        import uuid
                        oco_group_id = f"oco_{parent_order_id}_{int(datetime.utcnow().timestamp())}"
                        logger.info(f"Found parent order {parent_order_id} for {symbol}, using OCO group: {oco_group_id}")
                except Exception as e:
                    logger.warning(f"Could not get parent order ID for {symbol}: {e}")
            
            # Use the reusable TP/SL order creator functions (same as automatic creation)
            # Create SL order if requested
            sl_order_id = None
            sl_error = None
            if create_sl and sl_price and entry_price:
                sl_result = create_stop_loss_order(
                    db=db,
                    symbol=symbol,
                    side="BUY",  # Original order side (we assume BUY positions)
                    sl_price=sl_price,
                    quantity=position_balance,
                    entry_price=entry_price,
                    parent_order_id=parent_order_id,
                    oco_group_id=oco_group_id,
                    dry_run=dry_run_mode,
                    source="manual"
                )
                sl_order_id = sl_result.get("order_id")
                sl_error = sl_result.get("error")
            
            # Create TP order if requested
            tp_order_id = None
            tp_error = None
            if create_tp and tp_price and entry_price:
                tp_result = create_take_profit_order(
                    db=db,
                    symbol=symbol,
                    side="BUY",  # Original order side (we assume BUY positions)
                    tp_price=tp_price,
                    quantity=position_balance,
                    entry_price=entry_price,
                    parent_order_id=parent_order_id,
                    oco_group_id=oco_group_id,
                    dry_run=dry_run_mode,
                    source="manual"
                )
                tp_order_id = tp_result.get("order_id")
                tp_error = tp_result.get("error")
            
            # Send notification
            if sl_order_id or tp_order_id:
                try:
                    # Get percentages from watchlist or calculate from prices
                    sl_pct = watchlist_item.sl_percentage if watchlist_item.sl_percentage else None
                    tp_pct = watchlist_item.tp_percentage if watchlist_item.tp_percentage else None
                    
                    # If percentages not set, calculate from entry price and SL/TP prices
                    if entry_price and entry_price > 0:
                        if not sl_pct and sl_price:
                            sl_pct = abs((entry_price - sl_price) / entry_price * 100)
                        if not tp_pct and tp_price:
                            tp_pct = abs((tp_price - entry_price) / entry_price * 100)
                    
                    telegram_notifier.send_sl_tp_orders(
                        symbol=symbol,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        quantity=position_balance,
                        mode=watchlist_item.sl_tp_mode or "conservative",
                        sl_order_id=str(sl_order_id) if sl_order_id else None,
                        tp_order_id=str(tp_order_id) if tp_order_id else None,
                        original_order_id=None,
                        entry_price=entry_price,
                        sl_percentage=sl_pct,
                        tp_percentage=tp_pct
                    )
                    logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - {e}", exc_info=True)
            
            success = (create_sl and sl_order_id) or (create_tp and tp_order_id) or (not create_sl and not create_tp)
            
            # If there's an error and no success, include it in the main error field
            main_error = None
            if not success:
                if create_sl and sl_error:
                    main_error = f"SL order failed: {sl_error}"
                elif create_tp and tp_error:
                    main_error = f"TP order failed: {tp_error}"
                elif create_sl and not sl_order_id:
                    main_error = sl_error or "SL order creation failed (unknown reason)"
                elif create_tp and not tp_order_id:
                    main_error = tp_error or "TP order creation failed (unknown reason)"
            
            return {
                'success': success,
                'symbol': symbol,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'sl_error': sl_error,
                'tp_error': tp_error,
                'error': main_error,  # Add main error field for easier access
                'dry_run': dry_run_mode
            }
            
        except Exception as e:
            logger.error(f"Error creating protection order for position {symbol}: {e}", exc_info=True)
            error_msg = str(e)
            # Provide more specific error message
            if "Watchlist item not found" in error_msg:
                return {
                    'success': False,
                    'error': f'Watchlist item not found for {symbol}. First add {symbol} to watchlist.'
                }
            elif "No open position" in error_msg:
                return {
                    'success': False,
                    'error': error_msg  # Already has good message
                }
            else:
                return {
                    'success': False,
                    'error': f'Error creating order: {error_msg}'
                }
    
    def create_sl_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create both SL and TP orders for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=True, force=force)
    
    def skip_reminder_for_symbol(self, db: Session, symbol: str) -> bool:
        """Mark symbol to skip SL/TP reminders"""
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if not watchlist_item:
                # Create watchlist item if it doesn't exist
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    skip_sl_tp_reminder=True
                )
                db.add(watchlist_item)
            else:
                watchlist_item.skip_sl_tp_reminder = True
            
            db.commit()
            logger.info(f"Marked {symbol} to skip SL/TP reminders")
            return True
            
        except Exception as e:
            logger.error(f"Error skipping reminder for {symbol}: {e}")
            db.rollback()
            return False


# Global instance
sl_tp_checker_service = SLTPCheckerService()

