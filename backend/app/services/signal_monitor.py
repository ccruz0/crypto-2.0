"""Signal monitoring service
Monitors trading signals and automatically creates orders when BUY/SELL conditions are met
for coins with alert_enabled = true
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.api.routes_signals import get_signals
from app.services.trading_signals import calculate_trading_signals
from app.api.routes_signals import calculate_stop_loss_and_take_profit

logger = logging.getLogger(__name__)


class SignalMonitorService:
    """Service to monitor trading signals and create orders automatically
    
    Advanced order creation logic:
    - Creates first order when BUY signal is detected (no previous orders)
    - Maximum 3 open orders per symbol
    - Requires 3% price change from last order before creating another
    - Does NOT reset when signal changes to WAIT (preserves order tracking)
    """
    
    def __init__(self):
        self.is_running = False
        self.monitor_interval = 30  # Check signals every 30 seconds
        self.last_signal_states: Dict[str, Dict] = {}  # Track previous signal states: {symbol: {state: BUY/WAIT/SELL, last_order_price: float, orders_count: int}}
        self.processed_orders: set = set()  # Track orders we've created to avoid duplicates
        self.order_creation_locks: Dict[str, float] = {}  # Track when we're creating orders: {symbol: timestamp}
        self.MAX_OPEN_ORDERS_PER_SYMBOL = 3  # Maximum open orders per symbol
        self.MIN_PRICE_CHANGE_PCT = 1.0  # Minimum 1% price change to create another order
        self.ORDER_CREATION_LOCK_SECONDS = 10  # Lock for 10 seconds after creating an order
        # Alert throttling state: {symbol: {side: {last_alert_time: datetime, last_alert_price: float}}}
        self.last_alert_states: Dict[str, Dict[str, Dict]] = {}  # Track last alert per symbol and side
        self.ALERT_COOLDOWN_MINUTES = 5  # 5 minutes cooldown between same-side alerts
        self.ALERT_MIN_PRICE_CHANGE_PCT = 1.0  # Minimum 1% price change for same-side alerts
        self.alert_sending_locks: Dict[str, float] = {}  # Track when we're sending alerts: {symbol_side: timestamp}
        self.ALERT_SENDING_LOCK_SECONDS = 2  # Lock for 2 seconds after checking/sending alert to prevent race conditions
        # Bloqueo temporal para evitar reintentos con margen cuando hay error 609
        self.margin_error_609_locks: Dict[str, float] = {}  # Track symbols with error 609: {symbol: timestamp}
        self.MARGIN_ERROR_609_LOCK_MINUTES = 30  # Bloquear por 30 minutos después de error 609
    
    @staticmethod
    def _should_block_open_orders(per_symbol_open: int, max_per_symbol: int, global_open: Optional[int] = None) -> bool:
        """
        Determine if we should block based on per-symbol open positions.
        The global count is informational only and never blocks orders.
        """
        return per_symbol_open >= max_per_symbol
    
    def _count_total_open_buy_orders(self, db: Session) -> int:
        """
        Count total open LONG exposure across ALL symbols using the unified
        definition of "órdenes abiertas".

        This now delegates to the shared helper in order_position_service so
        that global protection, per-symbol logic and dashboard/Telegram can all
        share the exact same calculation.
        """
        try:
            from app.services.order_position_service import count_total_open_positions

            total = count_total_open_positions(db)
            logger.info(f"📊 Total exposición (unified): {total} posiciones/órdenes abiertas")
            return total
        except Exception as e:
            logger.error(f"Error counting total open positions (unified): {e}", exc_info=True)
            # On error, return a safe default (assume we're at limit to be conservative)
            return self.MAX_OPEN_ORDERS_PER_SYMBOL
    
    def should_send_alert(self, symbol: str, side: str, current_price: float, trade_enabled: bool = True, min_price_change_pct: Optional[float] = None) -> tuple[bool, str]:
        """
        Check if an alert should be sent based on throttling rules.
        
        Rules:
        - For same-side alerts (BUY->BUY or SELL->SELL): 
          * If trade_enabled=True: require 5 minutes OR min_price_change_pct% price change
          * If trade_enabled=False: require min_price_change_pct% price change ONLY (no time-based cooldown)
        - For opposite-side alerts (BUY->SELL or SELL->BUY): always send immediately
        
        Args:
            symbol: Trading symbol (e.g., "BTC_USDT")
            side: Alert side ("BUY" or "SELL")
            current_price: Current price for the symbol
            trade_enabled: Whether trading is enabled for this symbol (affects throttling rules)
            min_price_change_pct: Minimum price change % required (defaults to self.ALERT_MIN_PRICE_CHANGE_PCT)
            
        Returns:
            tuple[bool, str]: (should_send, reason)
                - should_send: True if alert should be sent, False otherwise
                - reason: Explanation for the decision (for logging)
        """
        from datetime import timedelta, timezone
        import time
        
        # CRITICAL: Check if another thread is already processing this alert
        # This prevents race conditions when multiple cycles run simultaneously
        lock_key = f"{symbol}_{side}"
        if lock_key in self.alert_sending_locks:
            lock_timestamp = self.alert_sending_locks[lock_key]
            if time.time() - lock_timestamp < self.ALERT_SENDING_LOCK_SECONDS:
                return False, f"Another thread is already processing {symbol} {side} alert (lock age: {time.time() - lock_timestamp:.2f}s)"
        
        # Get last alert state for this symbol and side
        symbol_alerts = self.last_alert_states.get(symbol, {})
        last_alert = symbol_alerts.get(side)
        
        # If no previous alert for this symbol+side, check lock first to prevent duplicates
        if not last_alert:
            # Double-check lock to ensure we're the first to process this
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                if time.time() - lock_timestamp < self.ALERT_SENDING_LOCK_SECONDS:
                    return False, f"Another thread is already processing first {symbol} {side} alert"
            return True, "First alert for this symbol and side"
        
        last_alert_time = last_alert.get("last_alert_time")
        last_alert_price = last_alert.get("last_alert_price", 0.0)
        
        # If no previous time or price recorded, send
        if not last_alert_time or last_alert_price == 0.0:
            return True, "No previous alert time/price recorded"
        
        # Normalize timezone for last_alert_time (used in both direction check and throttling)
        if last_alert_time.tzinfo is None:
            last_alert_time_normalized = last_alert_time.replace(tzinfo=timezone.utc)
        elif last_alert_time.tzinfo != timezone.utc:
            last_alert_time_normalized = last_alert_time.astimezone(timezone.utc)
        else:
            last_alert_time_normalized = last_alert_time
        
        # Check if this is an opposite-side alert (direction change)
        # Get the other side's last alert to check for direction change
        opposite_side = "SELL" if side == "BUY" else "BUY"
        opposite_alert = symbol_alerts.get(opposite_side)
        
        # If there's an opposite-side alert, check which one is more recent
        # If the opposite-side alert is more recent, this is a direction change - always send immediately
        if opposite_alert:
            opposite_time = opposite_alert.get("last_alert_time")
            if opposite_time:
                # Normalize timezone for comparison
                if opposite_time.tzinfo is None:
                    opposite_time_normalized = opposite_time.replace(tzinfo=timezone.utc)
                elif opposite_time.tzinfo != timezone.utc:
                    opposite_time_normalized = opposite_time.astimezone(timezone.utc)
                else:
                    opposite_time_normalized = opposite_time
                
                # If opposite-side alert is more recent, this is a direction change
                if last_alert_time_normalized < opposite_time_normalized:
                    return True, f"Direction change detected ({opposite_side}->{side}), sending immediately"
        
        # Same-side alert - apply throttling rules
        now_utc = datetime.now(timezone.utc)
        
        # Calculate time since last alert
        time_diff = (now_utc - last_alert_time_normalized).total_seconds() / 60  # minutes
        cooldown_met = time_diff >= self.ALERT_COOLDOWN_MINUTES
        
        # Calculate price change percentage
        if last_alert_price > 0:
            price_change_pct = abs((current_price - last_alert_price) / last_alert_price * 100)
        else:
            price_change_pct = 100.0  # If no previous price, consider it a big change
        
        # Use provided min_price_change_pct or fallback to default
        alert_min_price_change = min_price_change_pct if min_price_change_pct is not None else self.ALERT_MIN_PRICE_CHANGE_PCT
        price_change_met = price_change_pct >= alert_min_price_change
        
        # IMPORTANT: Different rules for trade_enabled vs trade_disabled
        if not trade_enabled:
            # When trade_enabled=False: ONLY send if price changed by threshold (no time-based cooldown)
            # This prevents spam when trading is disabled
            if price_change_met:
                return True, f"Price change met ({price_change_pct:.2f}% >= {alert_min_price_change:.2f}%) - sending (trade_enabled=False, requires {alert_min_price_change:.2f}% change)"
            else:
                return False, f"Throttled (trade_enabled=False): price change {price_change_pct:.2f}% < {alert_min_price_change:.2f}% required (last price: ${last_alert_price:.4f}, current: ${current_price:.4f})"
        
        # When trade_enabled=True: send if EITHER condition is met:
        # - 5 minutes have passed, OR
        # - Price changed by more than threshold
        # This allows significant price movements to trigger alerts even if cooldown hasn't passed
        if price_change_met:
            # Significant price change - send immediately even if cooldown not met
            return True, f"Price change met ({price_change_pct:.2f}% >= {alert_min_price_change:.2f}%) - sending despite cooldown ({time_diff:.1f} min < {self.ALERT_COOLDOWN_MINUTES} min)"
        elif cooldown_met:
            # Cooldown met but price change not significant - still send (cooldown is primary protection)
            return True, f"Cooldown met ({time_diff:.1f} min >= {self.ALERT_COOLDOWN_MINUTES} min) - sending (price change: {price_change_pct:.2f}%)"
        else:
            # Neither condition met - throttle
            return False, f"Throttled: cooldown not met ({time_diff:.1f} min < {self.ALERT_COOLDOWN_MINUTES} min) AND price change not met ({price_change_pct:.2f}% < {alert_min_price_change:.2f}%, last price: ${last_alert_price:.4f}, current: ${current_price:.4f})"
    
    def _update_alert_state(self, symbol: str, side: str, price: float):
        """Update the last alert state for a symbol and side"""
        from datetime import timezone
        
        if symbol not in self.last_alert_states:
            self.last_alert_states[symbol] = {}
        
        self.last_alert_states[symbol][side] = {
            "last_alert_time": datetime.now(timezone.utc),
            "last_alert_price": price
        }
    
    def _fetch_watchlist_items_sync(self, db: Session) -> list:
        """Synchronous helper to fetch watchlist items from database
        This function runs in a thread pool to avoid blocking the event loop
        
        Returns:
            List of WatchlistItem objects with alert_enabled = True
        """
        # IMPORTANT: Refresh the session to ensure we get the latest alert_enabled values
        # This prevents issues where alert_enabled was changed in the dashboard but the
        # signal_monitor is using a stale database session
        db.expire_all()
        
        # Get all watchlist items with alert_enabled = true (for alerts)
        # Note: This includes coins that may have trade_enabled = false
        # IMPORTANT: Do NOT reference non-existent columns (e.g., is_deleted) for legacy DBs
        try:
            watchlist_items = db.query(WatchlistItem).filter(
                WatchlistItem.alert_enabled == True
            ).all()
        except Exception as e:
            logger.warning(f"Error querying alert_enabled items, falling back to trade_enabled: {e}")
            try:
                db.rollback()
            except Exception:
                pass
            watchlist_items = db.query(WatchlistItem).filter(
                WatchlistItem.trade_enabled == True
            ).all()
        
        if not watchlist_items:
            logger.warning("⚠️ No watchlist items with alert_enabled = true found in database!")
            return []
        
        logger.info(f"📊 Monitoring {len(watchlist_items)} coins with alert_enabled = true:")
        for item in watchlist_items:
            # Refresh the item from database to get latest values (important for trade_amount_usd)
            db.refresh(item)
            logger.info(f"   - {item.symbol}: alert_enabled={item.alert_enabled}, trade_enabled={item.trade_enabled}, trade_amount=${item.trade_amount_usd or 0}")
        
        return watchlist_items
    
    async def monitor_signals(self, db: Session):
        """Monitor signals for all coins with alert_enabled = true (for alerts)
        Orders are only created if trade_enabled = true in addition to alert_enabled = true
        """
        try:
            # Fetch watchlist items in a thread pool to avoid blocking the event loop
            watchlist_items = await asyncio.to_thread(self._fetch_watchlist_items_sync, db)
            
            if not watchlist_items:
                return
            
            for item in watchlist_items:
                try:
                    await self._check_signal_for_coin(db, item)
                except Exception as e:
                    logger.error(f"Error monitoring signal for {item.symbol}: {e}", exc_info=True)
                    continue  # Continue with next coin even if one fails
        except Exception as e:
            logger.error(f"Error in monitor_signals: {e}", exc_info=True)
    
    async def _check_signal_for_coin(self, db: Session, watchlist_item: WatchlistItem):
        """Check signal for a specific coin and take action if needed"""
        symbol = watchlist_item.symbol
        exchange = watchlist_item.exchange or "CRYPTO_COM"
        
        # IMPORTANT: Query fresh from database to get latest trade_amount_usd
        # This ensures we have the most recent value even if it was just updated from the dashboard
        # Using a fresh query instead of refresh() to avoid any session caching issues
        try:
            # Try to filter by is_deleted if column exists, otherwise just filter by symbol
            try:
                fresh_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol,
                    WatchlistItem.is_deleted == False
                ).first()
            except Exception:
                # If is_deleted column doesn't exist, fall back to filtering only by symbol
                fresh_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
            if fresh_item:
                old_amount = watchlist_item.trade_amount_usd
                old_margin = watchlist_item.trade_on_margin if hasattr(watchlist_item, 'trade_on_margin') else None
                # Update the watchlist_item object with fresh values
                watchlist_item.trade_amount_usd = fresh_item.trade_amount_usd
                watchlist_item.trade_enabled = fresh_item.trade_enabled
                watchlist_item.alert_enabled = fresh_item.alert_enabled
                # CRITICAL: Also refresh trade_on_margin from database
                if hasattr(fresh_item, 'trade_on_margin'):
                    watchlist_item.trade_on_margin = fresh_item.trade_on_margin
                logger.info(f"🔄 Refreshed {symbol} from DB: trade_amount_usd={old_amount} -> {watchlist_item.trade_amount_usd}, trade_enabled={watchlist_item.trade_enabled}, trade_on_margin={old_margin} -> {getattr(watchlist_item, 'trade_on_margin', None)}")
            else:
                logger.warning(f"Could not find {symbol} in database for refresh")
        except Exception as e:
            logger.warning(f"Could not refresh {symbol} from DB: {e}")
        
        # ========================================================================
        # PRIMERA VERIFICACIÓN DE SEGURIDAD: Contar exposición abierta (Global y Base)
        # ========================================================================
        # Bloquear si ya hay 3 o más posiciones/órdenes abiertas (global o por base)
        # Esto previene sobre-exposición del portfolio
        try:
            total_open_buy_orders = self._count_total_open_buy_orders(db)
            try:
                from app.services.order_position_service import count_open_positions_for_symbol
                base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                base_open = count_open_positions_for_symbol(db, base_symbol)
            except Exception as _e:
                logger.warning(f"Failed to compute base exposure (first check) for {symbol}: {_e}")
                base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                base_open = total_open_buy_orders
            MAX_OPEN_ORDERS_PER_SYMBOL = self.MAX_OPEN_ORDERS_PER_SYMBOL
            
            logger.info(
                f"🔍 SEGURIDAD 1/2 para {symbol}: Global={total_open_buy_orders}/{MAX_OPEN_ORDERS_PER_SYMBOL}, "
                f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}"
            )
            if self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=total_open_buy_orders):
                logger.warning(
                    f"🚫 SEGURIDAD: {symbol} - Bloqueado por límite de símbolo. "
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (global={total_open_buy_orders}). "
                    f"No se procesará ninguna nueva orden de compra hasta que se libere este símbolo."
                )
                # Enviar notificación a Telegram para alertar al usuario
                try:
                    telegram_notifier.send_message(
                        f"🛡️ <b>PROTECCIÓN ACTIVADA</b>\n\n"
                        f"📊 Se detectó señal BUY para <b>{symbol}</b>\n"
                        f"🚫 <b>BLOQUEADA</b> por límite de símbolo\n\n"
                        f"📈 {base_symbol}: <b>{base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}</b> "
                        f"(global={total_open_buy_orders})\n"
                        f"⚠️ No se crearán nuevas órdenes hasta que se cierren órdenes existentes."
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram security notification: {e}")
                return  # Salir temprano - no procesar esta señal
            else:
                logger.debug(
                    f"✅ SEGURIDAD 1/2: {symbol} - Verificación pasada. "
                    f"Global={total_open_buy_orders}/{MAX_OPEN_ORDERS_PER_SYMBOL}, "
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}"
                )
        except Exception as e:
            logger.error(f"Error en primera verificación de seguridad para {symbol}: {e}", exc_info=True)
            # En caso de error, ser conservador y bloquear
            logger.warning(f"🚫 SEGURIDAD 1/2: {symbol} - Error en verificación, bloqueando por seguridad")
            return
        
        try:
            # Get current signals using the signals endpoint logic
            # We'll call the internal calculation function directly
            from app.services.data_sources import data_manager
            from price_fetcher import get_price_with_fallback
            
            # Get price data with indicators
            try:
                result = get_price_with_fallback(symbol, "15m")
                current_price = result.get('price', 0)
                if not current_price:
                    logger.warning(f"No price data for {symbol}, skipping signal check")
                    return
                
                rsi = result.get('rsi', 50)
                ma50 = result.get('ma50', current_price)
                ma200 = result.get('ma200', current_price)
                ema10 = result.get('ma10', current_price)
                atr = result.get('atr', current_price * 0.02)
                
                # Calculate resistance levels
                price_precision = 2 if current_price >= 100 else 4
                res_up = round(current_price * 1.02, price_precision)
                res_down = round(current_price * 0.98, price_precision)
                
            except Exception as e:
                logger.warning(f"Error fetching price data for {symbol}: {e}")
                return
            
            # Calculate trading signals
            signals = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ema10=ema10,
                buy_target=watchlist_item.buy_target,
                last_buy_price=watchlist_item.purchase_price,
                position_size_usd=watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 0,
                rsi_buy_threshold=40,
                rsi_sell_threshold=70
            )
            
            buy_signal = signals.get("buy_signal", False)
            sell_signal = signals.get("sell_signal", False)
            sl_price = signals.get("sl")
            tp_price = signals.get("tp")
            
            # Log signal detection for debugging
            logger.info(f"🔍 {symbol} signal check: buy_signal={buy_signal}, sell_signal={sell_signal}, price=${current_price:.4f}, RSI={rsi:.1f}")
            
            # Determine current signal state
            current_state = "WAIT"  # Default
            if buy_signal:
                current_state = "BUY"
                logger.info(f"🟢 BUY signal detected for {symbol}")
            elif sell_signal:
                current_state = "SELL"
                logger.info(f"🔴 SELL signal detected for {symbol}")
            else:
                logger.debug(f"⚪ WAIT signal for {symbol} (no buy/sell conditions met)")
            
            # Get previous signal state for this symbol
            prev_state = self.last_signal_states.get(symbol, {})
            prev_signal_state = prev_state.get("state", "WAIT")
            last_order_price = prev_state.get("last_order_price", 0.0)
            orders_count = prev_state.get("orders_count", 0)
            
            # Detect if this is the first BUY signal (no previous order price recorded)
            is_first_buy = (current_state == "BUY" and last_order_price == 0.0)
            is_new_buy_transition = (current_state == "BUY" and prev_signal_state != "BUY")
            
            # Log state transition
            if prev_signal_state != current_state:
                logger.info(f"📊 {symbol} signal state changed: {prev_signal_state} -> {current_state}")
            
            # Update signal state (preserve last_order_price)
            self.last_signal_states[symbol] = {
                "state": current_state,
                "last_order_price": last_order_price,  # Preserve last order price
                "orders_count": orders_count,
                "timestamp": datetime.utcnow()
            }
            
            # CRITICAL: Check database for recent orders BEFORE creating new ones
            # This prevents consecutive orders even if service restarts or state is lost
            from datetime import timedelta, timezone
            from sqlalchemy import or_
            recent_orders_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)  # 5 minute cooldown
            
            # Query database for recent BUY orders for this symbol
            # Check both exchange_create_time and created_at (fallback) to handle timezone issues
            # Also check FILLED orders (not just NEW/ACTIVE) to catch recently executed orders
            # Use COALESCE to handle None values in order_by
            from sqlalchemy import func
            # FIX: Count by base currency to prevent duplicate orders across pairs
            symbol_base_recent_check = symbol.split('_')[0] if '_' in symbol else symbol
            recent_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol.like(f"{symbol_base_recent_check}_%"),
                ExchangeOrder.side == OrderSideEnum.BUY,
                or_(
                    ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                    ExchangeOrder.created_at >= recent_orders_threshold
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).all()
            # Also check exact match for symbols without underscore
            if '_' not in symbol:
                exact_recent_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    or_(
                        ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                        ExchangeOrder.created_at >= recent_orders_threshold
                    )
                ).order_by(
                    func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
                ).all()
                # Merge results (avoid duplicates)
                existing_recent_symbols = {o.exchange_order_id for o in recent_buy_orders}
                for order in exact_recent_orders:
                    if order.exchange_order_id not in existing_recent_symbols:
                        recent_buy_orders.append(order)
            
            # Query database for open BUY orders
            # FIX: Count by base currency (e.g., ADA_USD and ADA_USDT both count as ADA)
            # This prevents creating too many orders of the same coin across different pairs
            symbol_base = symbol.split('_')[0] if '_' in symbol else symbol
            
            # Get all open BUY orders for this base currency (e.g., ADA_USD, ADA_USDT both for ADA)
            open_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol.like(f"{symbol_base}_%"),  # Match all pairs (ADA_USD, ADA_USDT, etc.)
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            # Also check exact symbol match in case symbol doesn't have underscore
            if '_' not in symbol:
                exact_match_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                ).all()
                # Merge results (avoid duplicates)
                existing_symbols = {o.symbol for o in open_buy_orders}
                for order in exact_match_orders:
                    if order.symbol not in existing_symbols:
                        open_buy_orders.append(order)
            
            # Get the most recent OPEN BUY order price from database (more reliable than memory)
            # CRITICAL: Only use OPEN orders (not filled/executed) to calculate price change threshold
            # If all BUY orders are filled/executed, there's no open position, so no price change check needed
            from datetime import timedelta
            all_recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)  # Check last 24 hours for price reference
            # FIX: Count by base currency to get the most recent order across all pairs
            symbol_base_recent = symbol.split('_')[0] if '_' in symbol else symbol
            all_recent_open_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol.like(f"{symbol_base_recent}_%"),
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                or_(
                    ExchangeOrder.exchange_create_time >= all_recent_threshold,
                    ExchangeOrder.created_at >= all_recent_threshold
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).limit(1).all()
            # Also check exact match for symbols without underscore
            if '_' not in symbol and not all_recent_open_buy_orders:
                exact_recent_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]),
                    or_(
                        ExchangeOrder.exchange_create_time >= all_recent_threshold,
                        ExchangeOrder.created_at >= all_recent_threshold
                    )
                ).order_by(
                    func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
                ).limit(1).all()
                if exact_recent_orders:
                    all_recent_open_buy_orders = exact_recent_orders
            
            db_last_order_price = 0.0
            if all_recent_open_buy_orders:
                # Only use price from OPEN orders (not filled/executed)
                most_recent_order = all_recent_open_buy_orders[0]
                if most_recent_order.price:
                    db_last_order_price = float(most_recent_order.price)
                elif most_recent_order.avg_price:
                    db_last_order_price = float(most_recent_order.avg_price)
                elif most_recent_order.filled_price:
                    db_last_order_price = float(most_recent_order.filled_price)
            
            # Use database price if available, otherwise fall back to memory
            effective_last_price = db_last_order_price if db_last_order_price > 0 else last_order_price
            
            db_open_orders_count = len(open_buy_orders)
            # Unified open-position count (pending BUY + net BUY after SELL offsets)
            try:
                from app.services.order_position_service import count_open_positions_for_symbol
                # Use base currency so we count exposure across all pairs for this coin
                unified_open_positions = count_open_positions_for_symbol(db, symbol_base)
            except Exception as e:
                logger.warning(f"Could not compute unified open position count for {symbol_base}: {e}")
                unified_open_positions = db_open_orders_count

            # Log which symbols are being counted together
            if db_open_orders_count > 0:
                symbols_counted = [o.symbol for o in open_buy_orders]
                logger.info(f"🔍 {symbol} order check: counting orders from {len(set(symbols_counted))} symbol(s): {', '.join(set(symbols_counted))}")
            logger.info(
                f"🔍 {symbol} (base: {symbol_base}) order check: "
                f"recent_orders={len(recent_buy_orders)}, "
                f"open_orders_raw={db_open_orders_count}/{self.MAX_OPEN_ORDERS_PER_SYMBOL} (BUY pending only), "
                f"open_orders_unified={unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL} (pending BUY + net BUY positions), "
                f"db_last_price=${db_last_order_price:.4f}, mem_last_price=${last_order_price:.4f}, "
                f"effective_last_price=${effective_last_price:.4f}"
            )
            
            # Check if we're currently creating an order for this symbol (lock check) - BEFORE any order creation logic
            import time
            current_time = time.time()
            if symbol in self.order_creation_locks:
                lock_time = self.order_creation_locks[symbol]
                if current_time - lock_time < self.ORDER_CREATION_LOCK_SECONDS:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} has active order creation lock "
                        f"({current_time - lock_time:.1f}s ago). Skipping to prevent duplicate orders."
                    )
                    return  # Exit early if locked
                else:
                    # Lock expired, remove it
                    del self.order_creation_locks[symbol]
            
            # Handle BUY signal
            # Create order if:
            # 1. First BUY signal (no previous order price), OR
            # 2. New BUY signal after WAIT/SELL (transition) AND no recent orders, OR
            # 3. Already in BUY but price has changed at least 3% from last order AND no recent orders
            should_create_order = False
            
            # FIRST CHECK: Block if max open orders limit reached (most restrictive).
            # Use the UNIFIED count so that per-symbol logic matches global protection.
            if unified_open_positions >= self.MAX_OPEN_ORDERS_PER_SYMBOL:
                logger.warning(
                    f"🚫 BLOCKED: {symbol} has reached maximum open orders limit "
                    f"({unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}). Skipping new order."
                )
                should_create_order = False
            # SECOND CHECK: Block if there are recent orders (within 5 minutes) - prevents consecutive orders
            # IMPORTANT: Even if more than 5 minutes passed, we still need to check 3% price change
            elif recent_buy_orders:
                # Get most recent time, handling timezone and None values
                most_recent_order = recent_buy_orders[0]
                most_recent_time = most_recent_order.exchange_create_time or most_recent_order.created_at
                
                if most_recent_time:
                    # Normalize timezone for comparison
                    if most_recent_time.tzinfo is None:
                        most_recent_time = most_recent_time.replace(tzinfo=timezone.utc)
                    elif most_recent_time.tzinfo != timezone.utc:
                        most_recent_time = most_recent_time.astimezone(timezone.utc)
                    
                    now_utc = datetime.now(timezone.utc)
                    time_since_last = (now_utc - most_recent_time).total_seconds() / 60
                    
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} has {len(recent_buy_orders)} recent BUY order(s) "
                        f"(most recent: {time_since_last:.1f} minutes ago, order_id: {most_recent_order.exchange_order_id}). "
                        f"Cooldown period active - skipping new order to prevent consecutive orders."
                    )
                else:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} has {len(recent_buy_orders)} recent BUY order(s) "
                        f"(order_id: {most_recent_order.exchange_order_id}, but timestamp is None). "
                        f"Cooldown period active - skipping new order to prevent consecutive orders."
                    )
                should_create_order = False
            # THIRD CHECK: Even if no recent orders (passed 5 minutes), ALWAYS verify price change threshold
            # This prevents creating orders just because time passed, without significant price movement
            elif effective_last_price > 0:
                # Get min_price_change_pct from watchlist_item, fallback to default
                # Check if attribute exists (for backward compatibility)
                if hasattr(watchlist_item, 'min_price_change_pct') and watchlist_item.min_price_change_pct is not None:
                    min_price_change_pct = watchlist_item.min_price_change_pct
                else:
                    min_price_change_pct = self.MIN_PRICE_CHANGE_PCT
                
                # We have a previous price - MUST verify price change threshold before creating new order
                # This applies to ALL cases: first_buy, new_transition, or continuing BUY state
                price_change_pct = abs((current_price - effective_last_price) / effective_last_price * 100)
                if price_change_pct >= min_price_change_pct:
                    # Price change requirement met - allow order creation
                    if is_first_buy:
                        should_create_order = True
                        logger.info(f"🟢 NEW BUY signal detected for {symbol} (first order in memory, but price found in DB, price changed {price_change_pct:.2f}%) - will create order")
                    elif is_new_buy_transition:
                        should_create_order = True
                        logger.info(f"🟢 NEW BUY signal detected for {symbol} (transition from {prev_signal_state}, price changed {price_change_pct:.2f}%) - will create order")
                    elif current_state == "BUY":
                        should_create_order = True
                        logger.info(f"🟢 Price changed {price_change_pct:.2f}% for {symbol} (last: ${effective_last_price:.2f}, now: ${current_price:.2f}) - creating another order")
                else:
                    # Price change NOT met - block order creation REGARDLESS of is_first_buy or is_new_buy_transition
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} price change {price_change_pct:.2f}% < {min_price_change_pct:.2f}% "
                        f"(last: ${effective_last_price:.2f}, now: ${current_price:.2f}) - skipping to prevent consecutive orders. "
                        f"Even though 5+ minutes passed (or is_first_buy/is_new_transition), price change requirement not met."
                    )
                    should_create_order = False
            elif is_first_buy:
                # First BUY signal - only create order if NO previous price exists in database
                # This means truly the first order ever for this symbol
                should_create_order = True
                logger.info(f"🟢 NEW BUY signal detected for {symbol} (first order, no previous price in DB or memory) - will create order")
            elif is_new_buy_transition and effective_last_price == 0:
                # New BUY signal after WAIT/SELL transition, but no previous price - allow order
                should_create_order = True
                logger.info(f"🟢 NEW BUY signal detected for {symbol} (transition from {prev_signal_state}, no previous price) - will create order")
            elif current_state == "BUY" and effective_last_price == 0:
                # In BUY state but no previous price - this shouldn't happen, but allow order creation
                should_create_order = True
                logger.warning(f"⚠️ {symbol} in BUY state but no previous price found - allowing order creation")
            elif current_state == "BUY":
                # In BUY state but price check already handled above - no action needed
                logger.debug(f"ℹ️ {symbol} in BUY state - price check already performed above")
            
            if should_create_order:
                # CRITICAL: Double-check for recent orders just before creating (race condition protection)
                # Refresh the query to catch any orders that might have been created between checks
                # FIX: Count by base currency to match the main check above
                db.expire_all()  # Force refresh from database
                symbol_base_final = symbol.split('_')[0] if '_' in symbol else symbol
                final_recent_check = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol.like(f"{symbol_base_final}_%"),
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    or_(
                        ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                        ExchangeOrder.created_at >= recent_orders_threshold
                    )
                ).count()
                # Also check exact match for symbols without underscore
                if '_' not in symbol:
                    exact_final_check = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        or_(
                            ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                            ExchangeOrder.created_at >= recent_orders_threshold
                        )
                    ).count()
                    final_recent_check = max(final_recent_check, exact_final_check)
                
                if final_recent_check > 0:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} - Found {final_recent_check} recent order(s) in final check. "
                        f"Order creation cancelled to prevent duplicate."
                    )
                    should_create_order = False
                    return  # Exit early
                
                # Set lock BEFORE creating order to prevent concurrent creation
                import time
                self.order_creation_locks[symbol] = time.time()
                logger.info(f"🔒 Lock set for {symbol} order creation")
                
                logger.info(f"🟢 NEW BUY signal detected for {symbol}")
                
                # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
                # This ensures only one thread can check and send an alert at a time
                # IMPORTANT: Set lock FIRST, before any checks, to prevent race conditions
                lock_key = f"{symbol}_BUY"
                lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
                current_time = time.time()
                
                # Check if we're already processing an alert for this symbol+side
                if lock_key in self.alert_sending_locks:
                    lock_timestamp = self.alert_sending_locks[lock_key]
                    if current_time - lock_timestamp < lock_timeout:
                        logger.debug(f"🔒 Alert sending already in progress for {symbol} BUY (lock age: {current_time - lock_timestamp:.2f}s), skipping duplicate check")
                        return
                    else:
                        # Lock expired, remove it
                        logger.debug(f"🔓 Expired lock removed for {symbol} BUY (age: {current_time - lock_timestamp:.2f}s)")
                        del self.alert_sending_locks[lock_key]
                
                # Set lock IMMEDIATELY to prevent other cycles from processing the same alert
                # This must happen BEFORE should_send_alert to prevent both cycles from seeing "first alert"
                self.alert_sending_locks[lock_key] = current_time
                logger.debug(f"🔒 Lock acquired for {symbol} BUY alert")
                
                try:
                    # Check if alert should be sent (throttling logic)
                    # Pass trade_enabled to apply stricter rules when trading is disabled
                    # Check if attribute exists (for backward compatibility)
                    if hasattr(watchlist_item, 'min_price_change_pct') and watchlist_item.min_price_change_pct is not None:
                        min_price_change = watchlist_item.min_price_change_pct
                    else:
                        min_price_change = None  # Use default from should_send_alert
                    should_send, reason = self.should_send_alert(symbol, "BUY", current_price, trade_enabled=watchlist_item.trade_enabled, min_price_change_pct=min_price_change)
                    
                    if should_send:
                        # CRITICAL: Update alert state BEFORE sending to prevent race conditions
                        # This ensures that if multiple calls happen simultaneously, only the first one will send
                        self._update_alert_state(symbol, "BUY", current_price)
                except Exception as e:
                    logger.warning(f"Error checking alert for {symbol}: {e}")
                
                # ========================================================================
                # VERIFICACIÓN FINAL: Re-verificar órdenes abiertas ANTES de enviar alerta
                # ========================================================================
                # Esta verificación adicional previene que se envíen alertas cuando hay 3+ órdenes abiertas
                # incluso si la señal BUY se detectó (protección contra race conditions)
                db.expire_all()  # Force refresh from database
                final_total_open_orders = self._count_total_open_buy_orders(db)
                # Also compute per-base exposure for this symbol
                try:
                    from app.services.order_position_service import count_open_positions_for_symbol
                    base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                    base_open = count_open_positions_for_symbol(db, base_symbol)
                except Exception as _e:
                    logger.warning(f"Failed to compute base exposure for {symbol}: {_e}")
                    base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                    base_open = final_total_open_orders  # fallback worst-case
                MAX_OPEN_ORDERS_PER_SYMBOL = self.MAX_OPEN_ORDERS_PER_SYMBOL
                
                # Log detallado para debugging
                logger.info(
                    f"🔍 VERIFICACIÓN FINAL para {symbol}: "
                    f"Global={final_total_open_orders}/{MAX_OPEN_ORDERS_PER_SYMBOL}, "
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}, "
                    f"bloquear={self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=final_total_open_orders)}"
                )
                
                if self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=final_total_open_orders):
                    logger.warning(
                        f"🚫 BLOQUEO FINAL: {symbol} - No se enviará alerta BUY por límite de símbolo. "
                        f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (global={final_total_open_orders}). "
                        f"La señal fue detectada pero está bloqueada por seguridad."
                    )
                    # Enviar notificación de bloqueo en lugar de la alerta BUY
                    try:
                        telegram_notifier.send_message(
                            f"🛡️ <b>PROTECCIÓN ACTIVADA</b>\n\n"
                            f"📊 Se detectó señal BUY para <b>{symbol}</b>\n"
                            f"🚫 <b>ALERTA BLOQUEADA</b> por límite de símbolo\n\n"
                            f"{base_symbol}: <b>{base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}</b> "
                            f"(global={final_total_open_orders})\n"
                            f"💵 Precio detectado: ${current_price:,.4f}\n"
                            f"⚠️ No se enviará alerta ni se creará orden hasta que se cierren órdenes existentes."
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram security notification: {e}")
                    # Salir sin enviar la alerta BUY ni crear la orden
                    if symbol in self.order_creation_locks:
                        del self.order_creation_locks[symbol]
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                    return  # Salir temprano - no procesar esta señal
                else:
                    logger.info(
                        f"✅ VERIFICACIÓN FINAL PASADA para {symbol}: "
                        f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}. "
                        f"Procediendo con alerta BUY."
                    )
                
                # Send Telegram alert (always send if alert_enabled = true, which we already filtered)
                try:
                    # Get strategy from watchlist item (sl_tp_mode: conservative or aggressive)
                    strategy = watchlist_item.sl_tp_mode or "conservative"
                    telegram_notifier.send_buy_signal(
                        symbol=symbol,
                        price=current_price,
                        reason=f"RSI={rsi:.1f}, Price={current_price:.4f}, MA50={ma50:.2f}, EMA10={ema10:.2f}",
                        strategy=strategy
                    )
                    logger.info(f"✅ BUY alert sent for {symbol} - {reason}")
                except Exception as e:
                    logger.warning(f"Failed to send Telegram BUY alert for {symbol}: {e}")
                    # If sending failed, we should still keep the state update to prevent spam retries
                finally:
                    # Always remove lock when done
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                
                # Create order automatically ONLY if trade_enabled = true AND alert_enabled = true
                # alert_enabled = true is already filtered, so we only need to check trade_enabled
                logger.info(f"🔍 Checking order creation for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}, alert_enabled={watchlist_item.alert_enabled}")
                if watchlist_item.trade_enabled:
                    if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                        logger.info(f"✅ Trade enabled for {symbol} - creating BUY order automatically")
                        try:
                            order_result = await self._create_buy_order(db, watchlist_item, current_price, res_up, res_down)
                            if order_result:
                                filled_price = order_result.get("filled_price")
                                state_entry = self.last_signal_states.get(symbol, {})
                                if filled_price:
                                    state_entry["last_order_price"] = filled_price
                                    # Update orders_count from database (more reliable than incrementing)
                                    # Expire all objects to force refresh from database
                                    db.expire_all()
                                    updated_open_orders = db.query(ExchangeOrder).filter(
                                        ExchangeOrder.symbol == symbol,
                                        ExchangeOrder.side == OrderSideEnum.BUY,
                                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                                    ).count()
                                    state_entry["orders_count"] = updated_open_orders
                                state_entry["state"] = "BUY"
                                state_entry["timestamp"] = datetime.utcnow()
                                self.last_signal_states[symbol] = state_entry
                                logger.info(f"✅ Updated state for {symbol}: last_order_price=${filled_price:.4f}, orders_count={state_entry.get('orders_count', 0)}")
                                # Lock will expire naturally after ORDER_CREATION_LOCK_SECONDS
                            else:
                                # Order creation failed, remove lock immediately
                                if symbol in self.order_creation_locks:
                                    del self.order_creation_locks[symbol]
                                    logger.info(f"🔓 Lock removed for {symbol} (order creation returned None)")
                        except Exception as order_err:
                            # Order creation failed, remove lock immediately
                            if symbol in self.order_creation_locks:
                                del self.order_creation_locks[symbol]
                            logger.error(f"❌ Order creation failed for {symbol}: {order_err}", exc_info=True)
                            raise
                    else:
                        # Send error notification to Telegram - Amount USD is REQUIRED for automatic orders
                        error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
                        logger.warning(f"Skipping automatic order creation for {symbol}: trade_amount_usd not configured (trade_enabled={watchlist_item.trade_enabled}, alert_enabled={watchlist_item.alert_enabled})")
                        
                        # Send error notification to Telegram
                        try:
                            telegram_notifier.send_message(
                                f"❌ <b>AUTOMATIC ORDER CREATION FAILED</b>\n\n"
                                f"📊 Symbol: <b>{symbol}</b>\n"
                                f"🟢 Side: BUY\n"
                                f"📊 Signal: BUY signal detected\n"
                                f"⚠️ Trade enabled: {watchlist_item.trade_enabled}\n"
                                f"❌ Error: {error_message}"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send Telegram error notification: {e}")
                else:
                    # alert_enabled = true but trade_enabled = false - send alert only, no order
                    logger.info(f"ℹ️ Alert sent for {symbol} but trade_enabled = false - no order created (trade_amount_usd={watchlist_item.trade_amount_usd})")
            
            # Handle SELL signal (only alerts, no orders)
            # DISABLED: SELL signals are not sent anymore per user request
            # The system will still detect SELL signals internally but will not send alerts
            if current_state == "SELL" and prev_signal_state != "SELL":
                logger.info(f"🔴 SELL signal detected for {symbol} - alert sending DISABLED (signal detected but not sent)")
                # Do not send SELL alerts - just log that signal was detected
                # This allows the system to track SELL signals internally without notifying

                state_entry = self.last_signal_states.get(symbol, {})
                state_entry.update({
                    "state": "SELL",
                    "timestamp": datetime.utcnow(),
                    "orders_count": 0
                })
                self.last_signal_states[symbol] = state_entry
        
        except Exception as e:
            logger.error(f"Error checking signal for {symbol}: {e}", exc_info=True)
            # CRITICAL: Do NOT mark watchlist_item as deleted or hidden on error
            # The symbol must remain visible in the watchlist even if order creation fails
            # Only log the error - do not modify is_deleted, is_active, or any visibility flags
    
    async def _create_buy_order(self, db: Session, watchlist_item: WatchlistItem, 
                                current_price: float, res_up: float, res_down: float):
        """Create a BUY order automatically based on signal"""
        symbol = watchlist_item.symbol
        
        # Validate that trade_amount_usd is configured - REQUIRED, no default
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
            logger.error(f"Cannot create BUY order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
            
            # Send error notification to Telegram
            try:
                telegram_notifier.send_message(
                    f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                    f"📊 Symbol: <b>{symbol}</b>\n"
                    f"🟢 Side: BUY\n"
                    f"❌ Error: {error_message}"
                )
            except Exception as e:
                logger.warning(f"Failed to send Telegram error notification: {e}")
            
            raise ValueError(error_message)
        
        amount_usd = watchlist_item.trade_amount_usd
        
        # ========================================================================
        # VERIFICACIÓN PREVIA: Balance disponible antes de crear orden
        # ========================================================================
        # Verificar balance disponible ANTES de intentar crear la orden
        # Esto previene errores 306 (INSUFFICIENT_AVAILABLE_BALANCE) para SPOT
        try:
            account_summary = trade_client.get_account_summary()
            available_balance = 0
            
            if 'accounts' in account_summary or 'data' in account_summary:
                accounts = account_summary.get('accounts') or account_summary.get('data', {}).get('accounts', [])
                for acc in accounts:
                    currency = acc.get('currency', '').upper()
                    if currency in ['USD', 'USDT']:
                        available = float(acc.get('available', '0') or '0')
                        available_balance += available
            
            # Para SPOT, necesitamos el monto completo (sin leverage)
            spot_required = amount_usd * 1.1  # 10% buffer
            logger.info(f"💰 Balance check para {symbol}: available=${available_balance:,.2f}, required=${spot_required:,.2f} para ${amount_usd:,.2f} orden SPOT")
            
            # Si no hay suficiente balance para SPOT, no intentar crear la orden
            if available_balance < spot_required:
                logger.warning(
                    f"🚫 BLOQUEO POR BALANCE: {symbol} - Balance insuficiente para orden SPOT. "
                    f"Available: ${available_balance:,.2f} < Required: ${spot_required:,.2f}. "
                    f"No se intentará crear la orden para evitar error 306."
                )
                # Enviar notificación informativa (no como error crítico)
                try:
                    telegram_notifier.send_message(
                        f"💰 <b>BALANCE INSUFICIENTE</b>\n\n"
                        f"📊 Se detectó señal BUY para <b>{symbol}</b>\n"
                        f"💵 Amount requerido: <b>${amount_usd:,.2f}</b>\n"
                        f"💰 Balance disponible: <b>${available_balance:,.2f}</b>\n\n"
                        f"⚠️ <b>No se creará orden</b> - Balance insuficiente\n"
                        f"💡 Deposita más fondos o reduce el tamaño de las órdenes"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram balance notification: {e}")
                return None  # No intentar crear la orden
        except Exception as balance_check_err:
            logger.warning(f"⚠️ No se pudo verificar balance para {symbol}: {balance_check_err}. Continuando con creación de orden...")
            # Si no podemos verificar balance, continuar (el exchange rechazará si no hay suficiente)
        
        # Read trade_on_margin from database - CRITICAL for margin trading
        user_wants_margin = watchlist_item.trade_on_margin or False
        
        # ========================================================================
        # VERIFICACIÓN: Bloqueo temporal por error 609 (INSUFFICIENT_MARGIN)
        # ========================================================================
        # Si este símbolo tuvo un error 609 recientemente, forzar SPOT en lugar de MARGIN
        # para evitar reintentos innecesarios que seguirán fallando
        import time
        if symbol in self.margin_error_609_locks:
            lock_timestamp = self.margin_error_609_locks[symbol]
            lock_age_minutes = (time.time() - lock_timestamp) / 60
            
            if lock_age_minutes < self.MARGIN_ERROR_609_LOCK_MINUTES:
                logger.warning(
                    f"🛡️ PROTECCIÓN: {symbol} tiene bloqueo activo por error 609 (INSUFFICIENT_MARGIN). "
                    f"Bloqueo activo desde hace {lock_age_minutes:.1f} minutos. "
                    f"Forzando SPOT en lugar de MARGIN para evitar fallos repetidos."
                )
                # Forzar SPOT en lugar de MARGIN
                user_wants_margin = False
            else:
                # Bloqueo expirado, removerlo
                logger.info(f"🔓 Bloqueo por error 609 expirado para {symbol} ({lock_age_minutes:.1f} minutos). Permitir MARGIN nuevamente.")
                del self.margin_error_609_locks[symbol]
        
        # CRITICAL: Decide trading mode and leverage based on instrument capabilities
        # This prevents error 306 by ensuring we never request leverage higher than max allowed
        from app.services.margin_decision_helper import decide_trading_mode, log_margin_decision, DEFAULT_CONFIGURED_LEVERAGE
        
        trading_decision = decide_trading_mode(
            symbol=symbol,
            configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
            user_wants_margin=user_wants_margin
        )
        
        # Log the decision for debugging
        log_margin_decision(symbol, trading_decision, DEFAULT_CONFIGURED_LEVERAGE)
        
        use_margin = trading_decision.use_margin
        leverage_value = trading_decision.leverage
        
        # Log margin settings for debugging
        logger.info(f"💰 MARGIN SETTINGS for {symbol}: user_wants_margin={user_wants_margin}, use_margin={use_margin}, leverage={leverage_value}")
        if use_margin:
            logger.info(f"📊 MARGIN ORDER ENABLED: {symbol} will be placed with margin (leverage={leverage_value}x)")
            
            # NOTE: We don't pre-check balance for margin orders because:
            # 1. Available margin is calculated by Crypto.com based on total portfolio value (not just USD/USDT balance)
            # 2. The dashboard shows "Available Margin: $18,231.48" which includes value of all positions
            # 3. Our get_account_summary() only returns USD/USDT available, not the actual margin available
            # 4. Crypto.com API will reject with error 306 if there's truly insufficient margin
            # 5. Our progressive leverage reduction and SPOT fallback will handle failures gracefully
            
            # Calculate margin required for logging purposes
            margin_required = (amount_usd / leverage_value) * 1.15 if leverage_value else amount_usd
            logger.info(f"💰 MARGIN ORDER: amount=${amount_usd:,.2f}, leverage={leverage_value}x, margin_required=${margin_required:,.2f} for {symbol}")
            logger.info(f"📊 Note: Actual available margin is calculated by Crypto.com (includes all positions). Dashboard shows ~$18k available.")
        else:
            logger.info(f"📊 SPOT ORDER: {symbol} will be placed without margin")
        
        # Check if we already created an order for this signal (avoid duplicates)
        signal_key = f"{symbol}_{datetime.utcnow().timestamp():.0f}"
        if signal_key in self.processed_orders:
            logger.debug(f"Order already created for {symbol} signal, skipping")
            return
        
        # ========================================================================
        # SEGUNDA VERIFICACIÓN DE SEGURIDAD: Verificar órdenes abiertas totales
        # ========================================================================
        # Verificar nuevamente justo antes de ejecutar la orden (doble seguridad)
        # Esto previene race conditions donde múltiples señales se procesan simultáneamente
        try:
            total_open_buy_orders_final = self._count_total_open_buy_orders(db)
            try:
                from app.services.order_position_service import count_open_positions_for_symbol
                base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                base_open = count_open_positions_for_symbol(db, base_symbol)
            except Exception as _e:
                logger.warning(f"Failed to compute base exposure (segunda verificación) para {symbol}: {_e}")
                base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                base_open = total_open_buy_orders_final
            MAX_OPEN_ORDERS_PER_SYMBOL = self.MAX_OPEN_ORDERS_PER_SYMBOL
            
            if self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=total_open_buy_orders_final):
                logger.error(
                    f"🚫 SEGURIDAD 2/2: {symbol} - BLOQUEADO en verificación final por límite de símbolo. "
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (global={total_open_buy_orders_final}). "
                    f"Orden cancelada justo antes de ejecutar (posible race condition detectada)."
                )
                # Enviar notificación crítica a Telegram
                try:
                    telegram_notifier.send_message(
                        f"🚨 <b>PROTECCIÓN CRÍTICA ACTIVADA</b>\n\n"
                        f"📊 Orden de compra para <b>{symbol}</b> fue <b>CANCELADA</b>\n"
                        f"🛡️ Verificación final de seguridad activada\n\n"
                        f"{base_symbol}: <b>{base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}</b> "
                        f"(global={total_open_buy_orders_final})\n"
                        f"⚠️ La orden fue bloqueada justo antes de ejecutarse para prevenir sobre-exposición."
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram critical security notification: {e}")
                return None  # Cancelar orden
            else:
                logger.info(
                    f"✅ SEGURIDAD 2/2: {symbol} - Verificación final pasada. "
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (global={total_open_buy_orders_final})"
                )
        except Exception as e:
            logger.error(f"Error en segunda verificación de seguridad para {symbol}: {e}", exc_info=True)
            # En caso de error, ser conservador y cancelar la orden
            logger.error(f"🚫 SEGURIDAD 2/2: {symbol} - Error en verificación final, cancelando orden por seguridad")
            return None
        
        # CRITICAL: Double-check for recent orders RIGHT BEFORE creating order (prevents race conditions)
        from datetime import timedelta, timezone
        from sqlalchemy import or_
        final_check_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        final_recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            or_(
                ExchangeOrder.exchange_create_time >= final_check_threshold,
                ExchangeOrder.created_at >= final_check_threshold
            )
        ).count()
        
        if final_recent_orders > 0:
            logger.warning(
                f"🚫 BLOCKED at final check: {symbol} has {final_recent_orders} recent BUY order(s) "
                f"within 5 minutes. Skipping order creation to prevent race condition."
            )
            return None
        
        try:
            from app.utils.live_trading import get_live_trading_status
            live_trading = get_live_trading_status(db)
            dry_run_mode = not live_trading
            
            logger.info(f"🔵 Creating automatic BUY order for {symbol}: amount_usd={amount_usd}, margin={use_margin}")
            
            # Place MARKET order
            side_upper = "BUY"
            
            # BUY market order: use notional (amount in USD)
            # Add retry logic for 500 errors (API might be temporarily unavailable)
            max_retries = 2
            retry_delay = 2  # seconds
            result = None
            last_error = None
            
            # MARGIN TRADING: Use the leverage from trading_decision (already calculated above)
            # leverage_value is already set from trading_decision above
            logger.info(f"📊 ORDER PARAMETERS: symbol={symbol}, side={side_upper}, notional={amount_usd}, is_margin={use_margin}, leverage={leverage_value}")
            
            for attempt in range(max_retries + 1):
                try:
                    result = trade_client.place_market_order(
                        symbol=symbol,
                        side=side_upper,
                        notional=amount_usd,
                        is_margin=use_margin,  # CRITICAL: Always pass trade_on_margin value
                        leverage=leverage_value,  # Always pass leverage when margin is enabled
                        dry_run=dry_run_mode
                    )
                    
                    # If no error in result, break out of retry loop
                    if "error" not in result:
                        break
                    
                    # Check if it's a 500 error that we should retry
                    error_msg = result.get("error", "")
                    # Log margin status in error messages
                    margin_info = f" (margin={use_margin}, leverage={leverage_value})" if use_margin else " (spot order)"
                    if "500" in error_msg and attempt < max_retries:
                        last_error = error_msg
                        logger.warning(f"❌ Order creation attempt {attempt + 1}/{max_retries + 1} failed for {symbol}{margin_info}: {error_msg}. Retrying in {retry_delay}s...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Not a retryable error or max retries reached
                        logger.error(f"❌ Order creation failed for {symbol}{margin_info}: {error_msg}")
                        break
                        
                except Exception as e:
                    margin_info = f" (margin={use_margin}, leverage={leverage_value})" if use_margin else " (spot order)"
                    if attempt < max_retries and "500" in str(e):
                        last_error = str(e)
                        logger.warning(f"❌ Order creation attempt {attempt + 1}/{max_retries + 1} failed with exception for {symbol}{margin_info}: {e}. Retrying in {retry_delay}s...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Not retryable or max retries reached
                        logger.error(f"❌ Order creation exception for {symbol}{margin_info}: {e}")
                        result = {"error": str(e)}
                        break
            
            # Record successful margin order (for learning)
            if result and "error" not in result and use_margin and leverage_value:
                from app.services.margin_leverage_cache import get_leverage_cache
                leverage_cache = get_leverage_cache()
                leverage_cache.record_leverage_success(
                    symbol=symbol,
                    working_leverage=leverage_value
                )
                logger.info(f"✅ Recorded successful margin order for {symbol} with leverage {leverage_value}x")
            
            # Check for errors
            if not result or "error" in result:
                error_msg = result.get("error", last_error) if result else last_error
                margin_info = f" (margin={use_margin}, leverage={leverage_value})" if use_margin else " (spot order)"
                logger.error(f"❌ Order creation failed for {symbol}{margin_info} after {max_retries + 1} attempt(s): {error_msg}")
                logger.error(f"📊 FAILED ORDER DETAILS: symbol={symbol}, side={side_upper}, notional={amount_usd}, is_margin={use_margin}, leverage={leverage_value}, dry_run={dry_run_mode}")
                
                # ========================================================================
                # FALLBACK 1: Error 609 (INSUFFICIENT_MARGIN) - No hay suficiente margen disponible
                # ========================================================================
                # Si falla con error 609, significa que la cuenta no tiene suficiente margen
                # En este caso, intentar automáticamente con SPOT en lugar de MARGIN
                if use_margin and error_msg and ("609" in error_msg or "INSUFFICIENT_MARGIN" in error_msg.upper()):
                    # Activar bloqueo temporal inmediatamente para evitar reintentos con margen
                    import time
                    self.margin_error_609_locks[symbol] = time.time()
                    logger.warning(
                        f"🔒 Bloqueo temporal activado para {symbol}: "
                        f"No se intentarán órdenes MARGIN por {self.MARGIN_ERROR_609_LOCK_MINUTES} minutos "
                        f"(error 609 detectado: margen insuficiente)"
                    )
                    
                    logger.error(
                        f"🚫 ERROR 609 (INSUFFICIENT_MARGIN) para {symbol}: "
                        f"No hay suficiente margen disponible en la cuenta. "
                        f"Intentando automáticamente con SPOT como fallback..."
                    )
                    
                    # Intentar inmediatamente con SPOT (sin margen)
                    try:
                        spot_result = trade_client.place_market_order(
                            symbol=symbol,
                            side=side_upper,
                            notional=amount_usd,
                            is_margin=False,  # Force SPOT order
                            leverage=None,  # No leverage for spot
                            dry_run=dry_run_mode
                        )
                        
                        if spot_result and "error" not in spot_result:
                            logger.info(
                                f"✅ ÉXITO: Orden SPOT creada como fallback para {symbol} "
                                f"(orden MARGIN falló con error 609 - margen insuficiente)"
                            )
                            result = spot_result
                            # Actualizar use_margin para logging
                            use_margin = False
                            leverage_value = None
                            # Limpiar error_msg para indicar éxito
                            error_msg = None
                        else:
                            spot_error = spot_result.get("error", "Unknown error") if spot_result else "No response"
                            logger.error(
                                f"❌ FALLO: Orden SPOT también falló para {symbol}: {spot_error}. "
                                f"La cuenta no tiene suficiente balance ni margen disponible."
                            )
                            # Enviar notificación crítica a Telegram
                            try:
                                telegram_notifier.send_message(
                                    f"🚨 <b>ERROR CRÍTICO: INSUFFICIENTE BALANCE</b>\n\n"
                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                    f"🟢 Side: BUY\n"
                                    f"💰 Amount: ${amount_usd:,.2f}\n\n"
                                    f"❌ <b>Error 609: INSUFFICIENT_MARGIN</b>\n"
                                    f"⚠️ Orden MARGIN falló: margen insuficiente\n"
                                    f"❌ Orden SPOT falló: {spot_error}\n\n"
                                    f"💡 <b>Acción requerida:</b>\n"
                                    f"• Depositar más fondos en la cuenta\n"
                                    f"• Reducir el tamaño de las órdenes\n"
                                    f"• Cerrar posiciones existentes para liberar margen"
                                )
                            except Exception as e:
                                logger.warning(f"Failed to send Telegram critical notification: {e}")
                            error_msg = f"Error 609 (INSUFFICIENT_MARGIN): MARGIN falló | SPOT falló: {spot_error}"
                            # Activar bloqueo temporal para evitar reintentos con margen
                            import time
                            self.margin_error_609_locks[symbol] = time.time()
                            logger.warning(
                                f"🔒 Bloqueo temporal activado para {symbol}: "
                                f"No se intentarán órdenes MARGIN por {self.MARGIN_ERROR_609_LOCK_MINUTES} minutos "
                                f"(error 609: margen insuficiente)"
                            )
                    except Exception as spot_err:
                        logger.error(f"❌ Excepción durante fallback SPOT para {symbol}: {spot_err}")
                        error_msg = f"Error 609 (INSUFFICIENT_MARGIN): MARGIN falló | SPOT exception: {str(spot_err)}"
                        # Activar bloqueo temporal incluso si el fallback SPOT falló
                        import time
                        self.margin_error_609_locks[symbol] = time.time()
                        logger.warning(
                            f"🔒 Bloqueo temporal activado para {symbol}: "
                            f"No se intentarán órdenes MARGIN por {self.MARGIN_ERROR_609_LOCK_MINUTES} minutos "
                            f"(error 609: margen insuficiente, fallback SPOT también falló)"
                        )
                
                # ========================================================================
                # FALLBACK 2: Error 306 (INSUFFICIENT_AVAILABLE_BALANCE) - Leverage demasiado alto
                # ========================================================================
                # Si falla con error 306, significa que el leverage fue demasiado alto para este par
                # Recordar el fallo e intentar con leverage reducido
                elif use_margin and error_msg and "306" in error_msg and "INSUFFICIENT_AVAILABLE_BALANCE" in error_msg:
                    from app.services.margin_leverage_cache import get_leverage_cache
                    leverage_cache = get_leverage_cache()
                    
                    # Record the failure
                    leverage_cache.record_leverage_failure(
                        symbol=symbol,
                        attempted_leverage=leverage_value,
                        error_code=306
                    )
                    
                    # Get next leverage to try (reduced)
                    next_leverage = leverage_cache.get_next_try_leverage(
                        symbol=symbol,
                        failed_leverage=leverage_value,
                        min_leverage=1.0
                    )
                    
                    if next_leverage and next_leverage >= 1.0:
                        # Try again with reduced leverage
                        logger.info(
                            f"🔄 Retrying {symbol} with reduced leverage: {leverage_value}x -> {next_leverage}x "
                            f"(learned from error 306)"
                        )
                        try:
                            retry_result = trade_client.place_market_order(
                                symbol=symbol,
                                side=side_upper,
                                notional=amount_usd,
                                is_margin=True,  # Still margin, just lower leverage
                                leverage=next_leverage,
                                dry_run=dry_run_mode
                            )
                            
                            if retry_result and "error" not in retry_result:
                                # Success with reduced leverage!
                                logger.info(
                                    f"✅ Successfully placed order for {symbol} with reduced leverage {next_leverage}x "
                                    f"(original {leverage_value}x failed)"
                                )
                                leverage_cache.record_leverage_success(
                                    symbol=symbol,
                                    working_leverage=next_leverage
                                )
                                result = retry_result
                                # Update leverage_value for logging consistency
                                leverage_value = next_leverage
                            else:
                                retry_error = retry_result.get("error", "Unknown error") if retry_result else "No response"
                                
                                # If this retry also failed with 306, try the next lower leverage
                                if retry_error and "306" in retry_error and "INSUFFICIENT_AVAILABLE_BALANCE" in retry_error:
                                    # Record this failure too
                                    leverage_cache.record_leverage_failure(
                                        symbol=symbol,
                                        attempted_leverage=next_leverage,
                                        error_code=306
                                    )
                                    
                                    # Get the next lower leverage to try
                                    next_next_leverage = leverage_cache.get_next_try_leverage(
                                        symbol=symbol,
                                        failed_leverage=next_leverage,
                                        min_leverage=1.0
                                    )
                                    
                                    if next_next_leverage and next_next_leverage >= 1.0:
                                        # Try with even lower leverage
                                        logger.info(
                                            f"🔄 Further reducing leverage for {symbol}: {next_leverage}x -> {next_next_leverage}x "
                                            f"(multiple attempts to find working leverage)"
                                        )
                                        try:
                                            retry_retry_result = trade_client.place_market_order(
                                                symbol=symbol,
                                                side=side_upper,
                                                notional=amount_usd,
                                                is_margin=True,
                                                leverage=next_next_leverage,
                                                dry_run=dry_run_mode
                                            )
                                            
                                            if retry_retry_result and "error" not in retry_retry_result:
                                                # Success with even lower leverage!
                                                logger.info(
                                                    f"✅ Successfully placed order for {symbol} with leverage {next_next_leverage}x "
                                                    f"({leverage_value}x and {next_leverage}x failed)"
                                                )
                                                leverage_cache.record_leverage_success(
                                                    symbol=symbol,
                                                    working_leverage=next_next_leverage
                                                )
                                                result = retry_retry_result
                                                leverage_value = next_next_leverage
                                                # Success - clear error_msg to skip SPOT fallback
                                                error_msg = None
                                            else:
                                                # Still failed, continue to SPOT
                                                retry_retry_error = retry_retry_result.get("error", "Unknown error") if retry_retry_result else "No response"
                                                logger.warning(
                                                    f"⚠️ Retry with leverage {next_next_leverage}x also failed for {symbol}: {retry_retry_error}"
                                                )
                                                error_msg = f"Margin {leverage_value}x, {next_leverage}x, {next_next_leverage}x all failed"
                                        except Exception as retry_retry_err:
                                            logger.error(f"❌ Exception during second leverage retry for {symbol}: {retry_retry_err}")
                                            error_msg = f"Margin {leverage_value}x, {next_leverage}x failed, {next_next_leverage}x exception: {str(retry_retry_err)}"
                                    else:
                                        # No more leverage to try, go to SPOT
                                        logger.warning(
                                            f"⚠️ Retry with leverage {next_leverage}x failed for {symbol}: {retry_error}. No more leverage levels to try, attempting SPOT."
                                        )
                                        error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error}"
                                else:
                                    # Different error (not 306), don't continue trying leverage
                                    logger.warning(
                                        f"⚠️ Retry with leverage {next_leverage}x failed for {symbol}: {retry_error} (not error 306, stopping leverage reduction)"
                                    )
                                    error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error}"
                        except Exception as retry_err:
                            logger.error(f"❌ Exception during leverage retry for {symbol}: {retry_err}")
                            error_msg = f"Margin {leverage_value}x failed: {error_msg} | Leverage retry exception: {str(retry_err)}"
                    
                    # If reduced leverage didn't work or we're at minimum, try SPOT fallback
                    # Only try SPOT if we haven't already succeeded with a lower leverage
                    if (not result or "error" in result) and error_msg:
                        logger.warning(f"⚠️ Margin order failed with error 306. Checking if SPOT fallback is possible for {symbol}...")
                    
                    # Check available balance for SPOT order
                    try:
                        # trade_client is already imported at top of file
                        account_summary = trade_client.get_account_summary()
                        available_balance = 0
                        
                        if 'accounts' in account_summary:
                            for acc in account_summary['accounts']:
                                currency = acc.get('currency', '').upper()
                                if currency in ['USD', 'USDT']:
                                    available = float(acc.get('available', '0') or '0')
                                    available_balance += available
                        
                        # For SPOT, we need full notional (no leverage)
                        spot_required = amount_usd * 1.1  # 10% buffer for SPOT orders
                        logger.info(f"💰 SPOT FALLBACK CHECK: available=${available_balance:,.2f}, spot_required=${spot_required:,.2f} for ${amount_usd:,.2f} order")
                        
                        if available_balance >= spot_required:
                            # We have enough for SPOT - try it
                            logger.info(f"✅ Sufficient balance for SPOT fallback. Attempting SPOT order...")
                            try:
                                spot_result = trade_client.place_market_order(
                                    symbol=symbol,
                                    side=side_upper,
                                    notional=amount_usd,
                                    is_margin=False,  # Force SPOT order
                                    leverage=None,  # No leverage for spot
                                    dry_run=dry_run_mode
                                )
                                
                                if spot_result and "error" not in spot_result:
                                    logger.info(f"✅ Successfully placed SPOT order as fallback for {symbol} (margin order failed)")
                                    # Use the spot result as if it was successful
                                    result = spot_result
                                else:
                                    spot_error = spot_result.get("error", "Unknown error") if spot_result else "No response"
                                    logger.error(f"❌ SPOT order fallback also failed for {symbol}: {spot_error}")
                                    error_msg = f"Margin failed: {error_msg} | Spot failed: {spot_error}"
                            except Exception as spot_err:
                                logger.error(f"❌ Exception during SPOT order fallback for {symbol}: {spot_err}")
                                error_msg = f"Margin failed: {error_msg} | Spot exception: {str(spot_err)}"
                        else:
                            # Not enough balance even for SPOT
                            # Try to reduce order size to fit available balance
                            max_spot_amount = (available_balance / 1.1) * 0.95  # 95% of available with buffer
                            
                            if max_spot_amount >= 100:  # Minimum order size
                                logger.warning(
                                    f"⚠️ INSUFFICIENT BALANCE for full SPOT order: "
                                    f"available=${available_balance:,.2f} < required=${spot_required:,.2f} "
                                    f"for ${amount_usd:,.2f} order. "
                                    f"Attempting reduced size: ${max_spot_amount:,.2f}"
                                )
                                
                                try:
                                    reduced_spot_result = trade_client.place_market_order(
                                        symbol=symbol,
                                        side=side_upper,
                                        notional=max_spot_amount,
                                        is_margin=False,  # Force SPOT order
                                        leverage=None,  # No leverage for spot
                                        dry_run=dry_run_mode
                                    )
                                    
                                    if reduced_spot_result and "error" not in reduced_spot_result:
                                        logger.info(
                                            f"✅ Successfully placed REDUCED SPOT order for {symbol}: "
                                            f"${max_spot_amount:,.2f} (original ${amount_usd:,.2f} failed due to insufficient balance)"
                                        )
                                        result = reduced_spot_result
                                        # Update amount_usd for logging consistency
                                        amount_usd = max_spot_amount
                                    else:
                                        reduced_error = reduced_spot_result.get("error", "Unknown error") if reduced_spot_result else "No response"
                                        logger.error(
                                            f"❌ Reduced SPOT order also failed for {symbol}: {reduced_error}"
                                        )
                                        error_msg = f"Margin failed: {error_msg} | Spot fallback blocked: insufficient balance (${available_balance:,.2f} < ${spot_required:,.2f}) | Reduced order also failed: {reduced_error}"
                                except Exception as reduced_spot_err:
                                    logger.error(f"❌ Exception during reduced SPOT order for {symbol}: {reduced_spot_err}")
                                    error_msg = f"Margin failed: {error_msg} | Spot fallback blocked: insufficient balance | Reduced order exception: {str(reduced_spot_err)}"
                            else:
                                # Even reduced order would be too small
                                logger.error(
                                    f"❌ INSUFFICIENT BALANCE for SPOT fallback: "
                                    f"available=${available_balance:,.2f} < required=${spot_required:,.2f} "
                                    f"for ${amount_usd:,.2f} SPOT order. "
                                    f"Even reduced order (${max_spot_amount:,.2f}) is below minimum ($100). Cannot fallback to SPOT."
                                )
                                error_msg = f"Margin failed: {error_msg} | Spot fallback blocked: insufficient balance (${available_balance:,.2f} < ${spot_required:,.2f}, min order $100)"
                    except Exception as balance_check_err:
                        logger.warning(f"⚠️ Could not check balance for SPOT fallback: {balance_check_err}. Skipping fallback...")
                        error_msg = f"Margin failed: {error_msg} | Spot fallback check failed: {str(balance_check_err)}"
                
                # If still failed after fallback, send error notification
                if not result or "error" in result:
                    # CRITICAL: Do NOT modify watchlist_item visibility on error
                    # The symbol must remain visible in the watchlist even if order creation fails
                    # Only log and notify - do not set is_deleted, is_active, or any flags
                    
                    # Send Telegram notification about the error
                    try:
                        error_details = error_msg
                        if use_margin:
                            error_details += "\n\n⚠️ <b>MARGIN ORDER FAILED</b> - Insufficient margin balance available.\nThe account may be over-leveraged or margin trading may not be enabled."
                        
                        telegram_notifier.send_message(
                            f"❌ <b>AUTOMATIC ORDER CREATION FAILED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🟢 Side: BUY\n"
                            f"💰 Amount: ${amount_usd:,.2f}\n"
                            f"📊 Type: {'MARGIN' if use_margin else 'SPOT'}\n"
                            f"❌ Error: {error_details}\n\n"
                            f"⚠️ The symbol remains in your watchlist. Please check the configuration and try again."
                        )
                    except Exception as notify_err:
                        logger.warning(f"Failed to send Telegram error notification: {notify_err}")
                    
                    # Return None to indicate failure, but do NOT modify watchlist_item
                    return None
            
            # Get order_id from result
            order_id = result.get("order_id") or result.get("client_order_id")
            if not order_id:
                logger.error(f"Order placed but no order_id returned for {symbol}")
                return None
            
            # Mark as processed
            self.processed_orders.add(signal_key)

            filled_price = None
            try:
                if result.get("avg_price"):
                    filled_price = float(result.get("avg_price"))
            except (TypeError, ValueError):
                filled_price = None
            if not filled_price:
                filled_price = current_price
            
            # Send Telegram notification when order is created
            try:
                telegram_notifier.send_order_created(
                    symbol=symbol,
                    side="BUY",
                    price=0,  # Market price will be determined at execution
                    quantity=amount_usd,  # For BUY, this is the amount in USD
                    order_id=str(order_id),
                    margin=use_margin,
                    leverage=10 if use_margin else None,
                    dry_run=dry_run_mode,
                    order_type="MARKET"
                )
                logger.info(f"Sent Telegram notification for automatic order: {symbol} BUY - {order_id}")
            except Exception as telegram_err:
                logger.warning(f"Failed to send Telegram notification for order creation: {telegram_err}")
            
            # Save order to database (BOTH order_history_db AND ExchangeOrder for immediate visibility)
            try:
                from app.services.order_history_db import order_history_db
                from datetime import timezone
                import time
                
                result_status = result.get("status", "").upper()
                cumulative_qty = float(result.get("cumulative_quantity", 0) or 0)
                
                # Determine actual status
                if result_status in ["FILLED", "filled"]:
                    db_status = OrderStatusEnum.FILLED
                    db_status_str = "FILLED"
                elif result_status in ["CANCELLED", "CANCELED"]:
                    if cumulative_qty > 0:
                        db_status = OrderStatusEnum.FILLED
                        db_status_str = "FILLED"
                    else:
                        db_status = OrderStatusEnum.CANCELLED
                        db_status_str = "CANCELLED"
                else:
                    db_status = OrderStatusEnum.NEW
                    db_status_str = "OPEN"
                
                estimated_qty = float(amount_usd / current_price)  # Ensure Python float, not numpy
                now_utc = datetime.now(timezone.utc)
                
                # Helper function to convert numpy types to Python native types
                def to_python_float(val):
                    """Convert numpy float to Python float"""
                    if val is None:
                        return None
                    try:
                        import numpy as np
                        if isinstance(val, (np.integer, np.floating)):
                            return float(val)
                    except ImportError:
                        pass
                    return float(val) if val else None
                
                # Save to order_history_db (SQLite)
                order_data = {
                    "order_id": str(order_id),
                    "client_oid": str(result.get("client_order_id", order_id)),
                    "instrument_name": symbol,
                    "order_type": "MARKET",
                    "side": "BUY",
                    "status": db_status_str,
                    "quantity": str(estimated_qty),
                    "price": str(result.get("avg_price", "0")) if result.get("avg_price") else "0",
                    "avg_price": str(result.get("avg_price")) if result.get("avg_price") else None,
                    "cumulative_quantity": str(result.get("cumulative_quantity")) if result.get("cumulative_quantity") else str(estimated_qty),
                    "cumulative_value": str(result.get("cumulative_value")) if result.get("cumulative_value") else None,
                    "create_time": int(time.time() * 1000),
                    "update_time": int(time.time() * 1000),
                }
                order_history_db.upsert_order(order_data)
                
                # CRITICAL: Also save to ExchangeOrder (PostgreSQL) immediately for cooldown checks
                try:
                    existing_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == str(order_id)
                    ).first()
                    
                    if not existing_order:
                        # Convert all numpy types to Python native types
                        safe_price = to_python_float(result.get("avg_price")) if result.get("avg_price") else None
                        safe_qty = to_python_float(estimated_qty)
                        safe_cumulative_qty = to_python_float(result.get("cumulative_quantity")) if result.get("cumulative_quantity") else safe_qty
                        safe_cumulative_val = to_python_float(result.get("cumulative_value")) if result.get("cumulative_value") else None
                        safe_avg_price = to_python_float(result.get("avg_price")) if result.get("avg_price") else None
                        
                        new_exchange_order = ExchangeOrder(
                            exchange_order_id=str(order_id),
                            client_oid=str(result.get("client_order_id", order_id)),
                            symbol=symbol,
                            side=OrderSideEnum.BUY,
                            order_type="MARKET",
                            status=db_status,
                            price=safe_price,
                            quantity=safe_qty,
                            cumulative_quantity=safe_cumulative_qty,
                            cumulative_value=safe_cumulative_val,
                            avg_price=safe_avg_price,
                            exchange_create_time=now_utc,  # CRITICAL: Set timestamp for cooldown checks
                            exchange_update_time=now_utc,
                            created_at=now_utc,
                            updated_at=now_utc
                        )
                        db.add(new_exchange_order)
                        db.commit()
                        logger.info(f"✅ Automatic BUY order saved to ExchangeOrder (PostgreSQL): {symbol} - {order_id} with exchange_create_time={now_utc}")
                    else:
                        logger.debug(f"Order {order_id} already exists in ExchangeOrder, skipping duplicate")
                except Exception as pg_err:
                    logger.error(f"Error saving automatic order to ExchangeOrder (PostgreSQL): {pg_err}", exc_info=True)
                    db.rollback()
                    # Continue - order_history_db save succeeded
                
                logger.info(f"Automatic BUY order saved to database: {symbol} - {order_id}")
            except Exception as e:
                logger.error(f"Error saving automatic order to database: {e}", exc_info=True)
            
            logger.info(f"✅ Automatic BUY order created successfully: {symbol} - {order_id}")
        
        except Exception as e:
            logger.error(f"Error creating automatic BUY order for {symbol}: {e}", exc_info=True)
            return None

        # Get filled quantity from result
        filled_quantity = None
        try:
            if result.get("cumulative_quantity"):
                filled_quantity = float(result.get("cumulative_quantity"))
            elif result.get("quantity"):
                filled_quantity = float(result.get("quantity"))
            else:
                # Estimate from amount_usd and filled_price
                if filled_price:
                    filled_quantity = amount_usd / filled_price
        except (TypeError, ValueError):
            filled_quantity = None
        
        # Get order status
        order_status = result.get("status", "UNKNOWN")
        
        return {
            "order_id": str(order_id),
            "filled_price": filled_price,
            "filled_quantity": filled_quantity,
            "status": order_status,
            "avg_price": result.get("avg_price")
        }
    
    async def start(self):
        """Start the signal monitoring service"""
        self.is_running = True
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL MONITORING SERVICE STARTED")
        logger.info(f"   - Monitor interval: {self.monitor_interval} seconds")
        logger.info(f"   - Max orders per symbol: {self.MAX_OPEN_ORDERS_PER_SYMBOL}")
        logger.info(f"   - Min price change: {self.MIN_PRICE_CHANGE_PCT}%")
        logger.info("=" * 60)
        
        cycle_count = 0
        while self.is_running:
            try:
                cycle_count += 1
                logger.info(f"🔍 Signal Monitor Cycle #{cycle_count} - Checking watchlist for alerts...")
                
                db = SessionLocal()
                try:
                    await self.monitor_signals(db)
                finally:
                    db.close()
                    
                logger.info(f"✅ Signal Monitor Cycle #{cycle_count} completed. Next check in {self.monitor_interval}s...")
            except Exception as e:
                logger.error(f"❌ Error in signal monitoring cycle #{cycle_count}: {e}", exc_info=True)
            
            await asyncio.sleep(self.monitor_interval)
    
    def stop(self):
        """Stop the signal monitoring service"""
        self.is_running = False
        logger.info("Signal monitoring service stopped")


# Global instance
signal_monitor_service = SignalMonitorService()

