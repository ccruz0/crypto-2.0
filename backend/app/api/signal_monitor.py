"""Signal monitoring service
Monitors trading signals and automatically creates orders when BUY/SELL conditions are met
for coins with alert_enabled = true
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.api.routes_signals import get_signals
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
from app.api.routes_signals import calculate_stop_loss_and_take_profit
from app.services.config_loader import get_alert_thresholds
from app.services.order_position_service import calculate_portfolio_value_for_symbol

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
        self.ALERT_COOLDOWN_MINUTES = 5  # default fallback
        self.ALERT_MIN_PRICE_CHANGE_PCT = 1.0
        self.alert_sending_locks: Dict[str, float] = {}  # Track when we're sending alerts: {symbol_side: timestamp}
        self.ALERT_SENDING_LOCK_SECONDS = 2  # Lock for 2 seconds after checking/sending alert to prevent race conditions
        self.ALERT_REQUIRE_COOLDOWN_AND_PRICE_CHANGE = False

    def _resolve_alert_thresholds(self, watchlist_item: WatchlistItem) -> Tuple[Optional[float], Optional[float]]:
        """
        Determine strategy-aware alert thresholds for a coin.

        Priority order:
            1. Per-coin override (watchlist_item.min_price_change_pct)
            2. Strategy defaults from trading_config.json
            3. Global defaults from trading_config.json
            4. Service-level fallback constants
        """
        min_pct = getattr(watchlist_item, "min_price_change_pct", None)
        cooldown = None
        try:
            strategy_key = getattr(watchlist_item, "sl_tp_mode", None)
            symbol = (watchlist_item.symbol or "").upper()
            preset_min, preset_cooldown = get_alert_thresholds(symbol, strategy_key)
            if min_pct is None:
                min_pct = preset_min
            cooldown = preset_cooldown
        except Exception as e:
            logger.warning(f"Failed to resolve alert thresholds for {getattr(watchlist_item, 'symbol', '?')}: {e}")
        if min_pct is None:
            min_pct = self.ALERT_MIN_PRICE_CHANGE_PCT
        if cooldown is None:
            cooldown = self.ALERT_COOLDOWN_MINUTES
        return min_pct, cooldown
    
    def should_send_alert(
        self,
        symbol: str,
        side: str,
        current_price: float,
        trade_enabled: bool = True,
        min_price_change_pct: Optional[float] = None,
        cooldown_minutes: Optional[float] = None,
    ) -> tuple[bool, str]:
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
        cooldown_limit = cooldown_minutes if cooldown_minutes is not None else self.ALERT_COOLDOWN_MINUTES
        cooldown_met = time_diff >= cooldown_limit
        
        # Calculate price change percentage
        if last_alert_price > 0:
            price_change_pct = abs((current_price - last_alert_price) / last_alert_price * 100)
        else:
            price_change_pct = 100.0  # If no previous price, consider it a big change
        
        # Use provided min_price_change_pct or fallback to default
        alert_min_price_change = min_price_change_pct if min_price_change_pct is not None else self.ALERT_MIN_PRICE_CHANGE_PCT
        price_change_met = price_change_pct >= alert_min_price_change
        
        if not price_change_met and not cooldown_met:
            minutes_remaining = max(0.0, cooldown_limit - time_diff)
            return False, (
                f"Throttled: cooldown {time_diff:.1f} min < {cooldown_limit} min "
                f"(remaining {minutes_remaining:.1f} min) AND price change "
                f"{price_change_pct:.2f}% < {alert_min_price_change:.2f}% "
                f"(last price: ${last_alert_price:.4f}, current: ${current_price:.4f})"
            )

        reasons = []
        if cooldown_met:
            reasons.append(f"cooldown met ({time_diff:.1f} min >= {cooldown_limit} min)")
        if price_change_met:
            reasons.append(f"price change met ({price_change_pct:.2f}% >= {alert_min_price_change:.2f}%)")
        reason_text = " AND ".join(reasons) if reasons else "threshold satisfied"

        return True, reason_text
    
    def _update_alert_state(self, symbol: str, side: str, price: float):
        """Update the last alert state for a symbol and side"""
        from datetime import timezone
        
        if symbol not in self.last_alert_states:
            self.last_alert_states[symbol] = {}
        
        self.last_alert_states[symbol][side] = {
            "last_alert_time": datetime.now(timezone.utc),
            "last_alert_price": price
        }

    def _get_last_alert_price(self, symbol: str, side: str) -> Optional[float]:
        symbol_alerts = self.last_alert_states.get(symbol)
        if not symbol_alerts:
            return None
        last_alert = symbol_alerts.get(side)
        if not last_alert:
            return None
        return last_alert.get("last_alert_price")

    @staticmethod
    def _format_price_variation(previous_price: Optional[float], current_price: float) -> Optional[str]:
        if previous_price is None or previous_price <= 0:
            return None
        try:
            change_pct = ((current_price - previous_price) / previous_price) * 100
        except ZeroDivisionError:
            return None
        return f"{change_pct:+.2f}%"
    
    async def monitor_signals(self, db: Session):
        """Monitor signals for all coins with alert_enabled = true (for alerts)
        Orders are only created if trade_enabled = true in addition to alert_enabled = true
        """
        try:
            # IMPORTANT: Refresh the session to ensure we get the latest alert_enabled values
            # This prevents issues where alert_enabled was changed in the dashboard but the
            # signal_monitor is using a stale database session
            db.expire_all()
            
            # Get all watchlist items with alert_enabled = true (for alerts)
            # Note: This includes coins that may have trade_enabled = false
            # IMPORTANT: Only process non-deleted items (is_deleted = False)
            try:
                # Use SQLAlchemy query with proper filtering
                watchlist_items = db.query(WatchlistItem).filter(
                    WatchlistItem.alert_enabled == True,
                    WatchlistItem.is_deleted == False
                ).all()
            except Exception as e:
                # Columns might not exist yet - fall back to basic query
                logger.warning(f"Error querying with filters, using fallback: {e}")
                try:
                    # Try without is_deleted filter
                    watchlist_items = db.query(WatchlistItem).filter(
                        WatchlistItem.alert_enabled == True
                    ).all()
                except Exception:
                    # Try without any filters (for old databases)
                    watchlist_items = db.query(WatchlistItem).filter(
                        WatchlistItem.trade_enabled == True
                    ).all()
            
            if not watchlist_items:
                logger.warning("⚠️ No watchlist items with alert_enabled = true found in database!")
                return
            
            logger.info(f"📊 Monitoring {len(watchlist_items)} coins with alert_enabled = true:")
            for item in watchlist_items:
                # Refresh the item from database to get latest values (important for trade_amount_usd)
                db.refresh(item)
                logger.info(f"   - {item.symbol}: alert_enabled={item.alert_enabled}, trade_enabled={item.trade_enabled}, trade_amount=${item.trade_amount_usd or 0}")
            
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
                # Update the watchlist_item object with fresh values
                watchlist_item.trade_amount_usd = fresh_item.trade_amount_usd
                watchlist_item.trade_enabled = fresh_item.trade_enabled
                watchlist_item.alert_enabled = fresh_item.alert_enabled
                logger.info(f"🔄 Refreshed {symbol} from DB: trade_amount_usd={old_amount} -> {watchlist_item.trade_amount_usd}, trade_enabled={watchlist_item.trade_enabled}")
            else:
                logger.warning(f"Could not find {symbol} in database for refresh")
        except Exception as e:
            logger.warning(f"Could not refresh {symbol} from DB: {e}")
        
        try:
            strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)

            # Get current signals using the signals endpoint logic
            # We'll call the internal calculation function directly
            from app.services.data_sources import data_manager
            from price_fetcher import get_price_with_fallback
            
            # Get price data with indicators and volume data
            # FIX: Fetch volume data from database (same as /api/signals endpoint) to ensure accurate volume checks
            try:
                # Try to get data from database first (includes volume data)
                from app.models.market_price import MarketData
                market_data = db.query(MarketData).filter(
                    MarketData.symbol == symbol
                ).first()
                
                if market_data and market_data.price and market_data.price > 0:
                    # Use data from database (includes volume)
                    current_price = market_data.price
                    rsi = market_data.rsi or 50.0
                    ma50 = market_data.ma50  # None if not available
                    ma200 = market_data.ma200  # None if not available
                    ema10 = market_data.ema10  # None if not available
                    atr = market_data.atr or (current_price * 0.02)
                    current_volume = market_data.current_volume  # Can be None
                    avg_volume = market_data.avg_volume  # Can be None - keep None instead of 0.0 for semantic clarity
                    
                    # FIX: Try to fetch fresh volume data if database volume seems stale or missing
                    # This ensures signal_monitor uses same fresh data as /api/signals endpoint
                    try:
                        from market_updater import fetch_ohlcv_data
                        from app.api.routes_signals import calculate_volume_index
                        
                        ohlcv_data = fetch_ohlcv_data(symbol, "1h", 6)
                        if ohlcv_data and len(ohlcv_data) > 0:
                            volumes = [candle.get("v", 0) for candle in ohlcv_data if candle.get("v", 0) > 0]
                            if len(volumes) >= 6:
                                # Recalculate volume index with fresh data - this is the source of truth
                                volume_index = calculate_volume_index(volumes, period=5)
                                fresh_current_volume = volume_index.get("current_volume")
                                fresh_avg_volume = volume_index.get("average_volume")
                                
                                # Use fresh values if available, otherwise fall back to DB values
                                if fresh_current_volume and fresh_current_volume > 0:
                                    current_volume = fresh_current_volume
                                    logger.debug(f"📊 {symbol}: Using fresh current_volume={current_volume} (was {market_data.current_volume})")
                                if fresh_avg_volume and fresh_avg_volume > 0:
                                    avg_volume = fresh_avg_volume
                                    logger.debug(f"📊 {symbol}: Using fresh avg_volume={avg_volume} (was {market_data.avg_volume})")
                    except Exception as vol_fetch_err:
                        # Don't fail if volume fetch fails - use DB values as fallback
                        logger.debug(f"📊 {symbol}: Could not fetch fresh volume: {vol_fetch_err}, using DB values")
                    
                    logger.debug(f"📊 {symbol}: Using database data - price=${current_price}, volume={current_volume}, avg_volume={avg_volume}")
                else:
                    # Fallback to price fetcher if database doesn't have data
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
                    current_volume = None  # Price fetcher doesn't provide volume
                    avg_volume = None
                    
                    logger.debug(f"📊 {symbol}: Using price fetcher fallback - price=${current_price}, volume=unavailable")
                
                # Calculate resistance levels
                price_precision = 2 if current_price >= 100 else 4
                res_up = round(current_price * 1.02, price_precision)
                res_down = round(current_price * 0.98, price_precision)
                
            except Exception as e:
                logger.warning(f"Error fetching price data for {symbol}: {e}")
                return
            
            # Calculate trading signals with volume data
            signals = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ma200=ma200,
                ema10=ema10,
                volume=current_volume,  # FIX: Pass volume data from database
                avg_volume=avg_volume,  # FIX: Pass avg_volume from database
                buy_target=watchlist_item.buy_target,
                last_buy_price=watchlist_item.purchase_price,
                position_size_usd=watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 0,
                rsi_buy_threshold=40,
                rsi_sell_threshold=70,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
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
            recent_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                or_(
                    ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                    ExchangeOrder.created_at >= recent_orders_threshold
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).all()
            
            # Query database for open BUY orders
            open_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            # Get the most recent OPEN BUY order price from database (more reliable than memory)
            # CRITICAL: Only use OPEN orders (not filled/executed) to calculate price change threshold
            # If all BUY orders are filled/executed, there's no open position, so no price change check needed
            from datetime import timedelta
            all_recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)  # Check last 24 hours for price reference
            all_recent_open_buy_orders = db.query(ExchangeOrder).filter(
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
            logger.info(f"🔍 {symbol} order check: recent_orders={len(recent_buy_orders)}, open_orders={db_open_orders_count}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}, db_last_price=${db_last_order_price:.4f}, mem_last_price=${last_order_price:.4f}, effective_last_price=${effective_last_price:.4f}")
            
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
            
            # FIRST CHECK: Block if max open orders limit reached (most restrictive)
            if db_open_orders_count >= self.MAX_OPEN_ORDERS_PER_SYMBOL:
                logger.warning(
                    f"🚫 BLOCKED: {symbol} has reached maximum open orders limit "
                    f"({db_open_orders_count}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}). Skipping new order."
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
                min_price_change_pct = watchlist_item.min_price_change_pct if watchlist_item.min_price_change_pct is not None else self.MIN_PRICE_CHANGE_PCT
                
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
                db.expire_all()  # Force refresh from database
                final_recent_check = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    or_(
                        ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                        ExchangeOrder.created_at >= recent_orders_threshold
                    )
                ).count()
                
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
                
                prev_buy_price: Optional[float] = None
                try:
                    # Check if alert should be sent (throttling logic)
                    # Pass trade_enabled to apply stricter rules when trading is disabled
                    min_price_change, alert_cooldown = self._resolve_alert_thresholds(watchlist_item)
                    should_send, reason = self.should_send_alert(
                        symbol,
                        "BUY",
                        current_price,
                        trade_enabled=watchlist_item.trade_enabled,
                        min_price_change_pct=min_price_change,
                        cooldown_minutes=alert_cooldown,
                    )
                    
                    if should_send:
                        # Check portfolio value limit: Block BUY alerts if portfolio_value > 3x trade_amount_usd
                        trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                        limit_value = 3 * trade_amount_usd
                        try:
                            portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                            if portfolio_value > limit_value:
                                logger.warning(
                                    f"🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                                    f"Valor en cartera (${portfolio_value:.2f}) > 3x trade_amount (${limit_value:.2f}). "
                                    f"Net qty: {net_quantity:.4f}, Precio: ${current_price:.4f}"
                                )
                                # Bloquear silenciosamente - no enviar notificación a Telegram
                                # Skip sending alert
                                should_send = False
                                reason = f"Portfolio value ${portfolio_value:.2f} > limit ${limit_value:.2f}"
                            else:
                                logger.debug(
                                    f"✅ Portfolio value check passed for {symbol}: "
                                    f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}"
                                )
                        except Exception as portfolio_check_err:
                            logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with alert...")
                            # On error, continue (don't block alerts if we can't calculate portfolio value)
                        
                        if should_send:
                            prev_buy_price = self._get_last_alert_price(symbol, "BUY")
                            # CRITICAL: Update alert state BEFORE sending to prevent race conditions
                            # This ensures that if multiple calls happen simultaneously, only the first one will send
                            self._update_alert_state(symbol, "BUY", current_price)
                            
                            # Send Telegram alert (always send if alert_enabled = true, which we already filtered)
                            try:
                                price_variation = self._format_price_variation(prev_buy_price, current_price)
                                ma50_text = f"{ma50:.2f}" if ma50 is not None else "N/A"
                                ema10_text = f"{ema10:.2f}" if ema10 is not None else "N/A"
                                ma200_text = f"{ma200:.2f}" if ma200 is not None else "N/A"
                                reason_text = (
                                    f"{strategy_type.value.title()}/{risk_approach.value.title()} | "
                                    f"RSI={rsi:.1f}, Price={current_price:.4f}, "
                                    f"MA50={ma50_text}, EMA10={ema10_text}, MA200={ma200_text}"
                                )
                                telegram_notifier.send_buy_signal(
                                    symbol=symbol,
                                    price=current_price,
                                    reason=reason_text,
                                    strategy_type=strategy_type.value.title(),
                                    risk_approach=risk_approach.value.title(),
                                    price_variation=price_variation,
                                    throttle_status="SENT",
                                    throttle_reason=reason,
                                )
                                logger.info(f"✅ BUY alert sent for {symbol} - {reason_text}")
                                
                                # Record signal event in throttle table for monitoring dashboard
                                try:
                                    from app.services.signal_throttle import record_signal_event, build_strategy_key
                                    strategy_key = build_strategy_key(strategy_type, risk_approach)
                                    record_signal_event(
                                        db=db,
                                        symbol=symbol,
                                        strategy_key=strategy_key,
                                        side="BUY",
                                        price=current_price,
                                        source="alert",
                                    )
                                    logger.debug(f"📝 Recorded BUY signal event for {symbol} in throttle table")
                                except Exception as record_err:
                                    logger.warning(f"⚠️ Could not record signal event for {symbol}: {record_err}")
                            except Exception as e:
                                logger.warning(f"Failed to send Telegram BUY alert for {symbol}: {e}")
                                # If sending failed, we should still keep the state update to prevent spam retries
                    else:
                        logger.info(f"🚫 BUY alert throttled for {symbol}: {reason}")
                finally:
                    # Always remove lock when done
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                
                # Create order automatically ONLY if trade_enabled = true AND alert_enabled = true
                # alert_enabled = true is already filtered, so we only need to check trade_enabled
                logger.info(f"🔍 Checking order creation for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}, alert_enabled={watchlist_item.alert_enabled}")
                
                # Check portfolio value limit: Block BUY orders if portfolio_value > 3x trade_amount_usd
                trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                limit_value = 3 * trade_amount_usd
                portfolio_check_passed = True
                try:
                    portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                    if portfolio_value > limit_value:
                        logger.warning(
                            f"🚫 ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                            f"Valor en cartera (${portfolio_value:.2f}) > 3x trade_amount (${limit_value:.2f}). "
                            f"Net qty: {net_quantity:.4f}, Precio: ${current_price:.4f}. "
                            f"No se creará orden aunque se detectó señal BUY."
                        )
                        # Bloquear silenciosamente - no enviar notificación a Telegram
                        portfolio_check_passed = False
                    else:
                        logger.debug(
                            f"✅ Portfolio value check passed for {symbol}: "
                            f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}"
                        )
                except Exception as portfolio_check_err:
                    logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with order creation...")
                    # On error, continue (don't block orders if we can't calculate portfolio value)
                
                if watchlist_item.trade_enabled and portfolio_check_passed:
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
                                logger.info(f"✅ Updated state for {symbol}: last_order_price=${filled_price:.4f}, orders_count={updated_open_orders}")
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
            if current_state == "SELL" and prev_signal_state != "SELL":
                logger.info(f"🔴 NEW SELL signal detected for {symbol} - sending alert only")
                
                # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
                # This ensures only one thread can check and send an alert at a time
                import time
                lock_key = f"{symbol}_SELL"
                lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
                
                # Check if we're already processing an alert for this symbol+side
                if lock_key in self.alert_sending_locks:
                    lock_timestamp = self.alert_sending_locks[lock_key]
                    if time.time() - lock_timestamp < lock_timeout:
                        logger.debug(f"🔒 Alert sending already in progress for {symbol} SELL, skipping duplicate check")
                        return
                    else:
                        # Lock expired, remove it
                        del self.alert_sending_locks[lock_key]
                
                # Set lock BEFORE checking to prevent race conditions
                self.alert_sending_locks[lock_key] = time.time()
                
                try:
                    # Check if alert should be sent (throttling logic)
                    # Pass trade_enabled to apply stricter rules when trading is disabled
                    min_price_change, alert_cooldown = self._resolve_alert_thresholds(watchlist_item)
                    should_send, reason = self.should_send_alert(
                        symbol,
                        "SELL",
                        current_price,
                        trade_enabled=watchlist_item.trade_enabled,
                        min_price_change_pct=min_price_change,
                        cooldown_minutes=alert_cooldown,
                    )
                    
                    if should_send:
                        # CRITICAL: Update alert state BEFORE sending to prevent race conditions
                        # This ensures that if multiple calls happen simultaneously, only the first one will send
                        self._update_alert_state(symbol, "SELL", current_price)
                        
                        # Send Telegram alert (always send if alert_enabled = true, which we already filtered)
                        try:
                            telegram_notifier.send_message(
                                f"🔴 <b>SELL SIGNAL DETECTED</b>\n\n"
                                f"📊 Symbol: <b>{symbol}</b>\n"
                                f"💵 Price: ${current_price:,.4f}\n"
                                f"📈 RSI: {rsi:.1f}\n"
                                f"📊 MA50: ${ma50:.2f}\n"
                                f"📊 EMA10: ${ema10:.2f}\n"
                                f"⚠️ SELL signals only generate alerts, no orders are created automatically"
                            )
                            logger.info(f"✅ SELL alert sent for {symbol} - {reason}")
                            
                            # Record signal event in throttle table for monitoring dashboard
                            try:
                                from app.services.signal_throttle import record_signal_event, build_strategy_key
                                strategy_key = build_strategy_key(strategy_type, risk_approach)
                                record_signal_event(
                                    db=db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="SELL",
                                    price=current_price,
                                    source="alert",
                                )
                                logger.debug(f"📝 Recorded SELL signal event for {symbol} in throttle table")
                            except Exception as record_err:
                                logger.warning(f"⚠️ Could not record signal event for {symbol}: {record_err}")
                        except Exception as e:
                            logger.warning(f"Failed to send Telegram SELL alert for {symbol}: {e}")
                            # If sending failed, we should still keep the state update to prevent spam retries
                    else:
                        logger.info(f"🚫 SELL alert throttled for {symbol}: {reason}")
                finally:
                    # Always remove lock when done
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]

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
        use_margin = watchlist_item.trade_on_margin or False
        
        # Check if we already created an order for this signal (avoid duplicates)
        signal_key = f"{symbol}_{datetime.utcnow().timestamp():.0f}"
        if signal_key in self.processed_orders:
            logger.debug(f"Order already created for {symbol} signal, skipping")
            return
        
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
            
            logger.info(f"Creating automatic BUY order for {symbol}: amount_usd={amount_usd}, margin={use_margin}")
            
            # Place MARKET order
            side_upper = "BUY"
            
            # BUY market order: use notional (amount in USD)
            # Add retry logic for 500 errors (API might be temporarily unavailable)
            max_retries = 2
            retry_delay = 2  # seconds
            result = None
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = trade_client.place_market_order(
                        symbol=symbol,
                        side=side_upper,
                        notional=amount_usd,
                        is_margin=use_margin,
                        leverage=10 if use_margin else None,
                        dry_run=dry_run_mode
                    )
                    
                    # If no error in result, break out of retry loop
                    if "error" not in result:
                        break
                    
                    # Check if it's a 500 error that we should retry
                    error_msg = result.get("error", "")
                    if "500" in error_msg and attempt < max_retries:
                        last_error = error_msg
                        logger.warning(f"Order creation attempt {attempt + 1}/{max_retries + 1} failed with 500 error for {symbol}: {error_msg}. Retrying in {retry_delay}s...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Not a retryable error or max retries reached
                        break
                        
                except Exception as e:
                    if attempt < max_retries and "500" in str(e):
                        last_error = str(e)
                        logger.warning(f"Order creation attempt {attempt + 1}/{max_retries + 1} failed with exception for {symbol}: {e}. Retrying in {retry_delay}s...")
                        import asyncio
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # Not retryable or max retries reached
                        result = {"error": str(e)}
                        break
            
            # Check for errors
            if not result or "error" in result:
                error_msg = result.get("error", last_error) if result else last_error
                logger.error(f"Order creation failed for {symbol} after {max_retries + 1} attempt(s): {error_msg}")
                
                # CRITICAL: Do NOT modify watchlist_item visibility on error
                # The symbol must remain visible in the watchlist even if order creation fails
                # Only log and notify - do not set is_deleted, is_active, or any flags
                
                # Send Telegram notification about the error
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>AUTOMATIC ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🟢 Side: BUY\n"
                        f"💰 Amount: ${amount_usd:,.2f}\n"
                        f"❌ Error: {error_msg}\n\n"
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

