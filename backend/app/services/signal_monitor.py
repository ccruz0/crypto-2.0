"""Signal monitoring service
Monitors trading signals and automatically creates orders when BUY/SELL conditions are met
for coins with alert_enabled = true
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import (
    get_canonical_watchlist_item,
    select_preferred_watchlist_item,
)
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.api.routes_signals import get_signals
from app.services.trading_signals import calculate_trading_signals
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.services.strategy_profiles import (
    resolve_strategy_profile,
    StrategyType,
    RiskApproach,
)
from app.api.routes_signals import calculate_stop_loss_and_take_profit
from app.services.config_loader import get_alert_thresholds
from app.services.order_position_service import (
    calculate_portfolio_value_for_symbol,
    _normalized_symbol_filter,
    INCLUDE_OPEN_ORDERS_IN_RISK,
)
from app.services.signal_throttle import (
    LastSignalSnapshot,
    SignalThrottleConfig,
    build_strategy_key,
    fetch_signal_states,
    record_signal_event,
    should_emit_signal,
)
from app.core.runtime import get_runtime_origin
from app.services.alert_emitter import emit_alert

logger = logging.getLogger(__name__)


class SignalMonitorService:
    """Service to monitor trading signals and create orders automatically
    
    Advanced order creation logic:
    - Creates first order when BUY signal is detected (no previous orders)
    - Maximum 3 open orders per symbol
    - Requires 3% price change from last order before creating another
    - Does NOT reset when signal changes to WAIT (preserves order tracking)
    """
    
    INACTIVE_MONITOR_PERIOD = 60  # Seconds: Check inactive coins every 60 seconds
    
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
        self.ALERT_SENDING_LOCK_SECONDS = 300  # Lock for 5 minutes (300 seconds) after checking/sending alert to prevent duplicate alerts and race conditions
        # Use OR between cooldown and price-change thresholds (per strategy config).
        self.ALERT_REQUIRE_COOLDOWN_AND_PRICE_CHANGE = False
        # Bloqueo temporal para evitar reintentos con margen cuando hay error 609
        self.margin_error_609_locks: Dict[str, float] = {}  # Track symbols with error 609: {symbol: timestamp}
        self.MARGIN_ERROR_609_LOCK_MINUTES = 30  # Bloquear por 30 minutos después de error 609
        # Dual-frequency polling: Track last time inactive coins were monitored
        self.last_inactive_monitor_time: float = time.time()  # Initialize to current time
        # Protection notification throttling: {symbol: {last_notification_time: datetime, last_orders_count: int}}
        self.last_protection_notifications: Dict[str, Dict] = {}
        self.PROTECTION_NOTIFICATION_COOLDOWN_MINUTES = 30  # 30 minutes cooldown between protection notifications
        self._task: Optional[asyncio.Task] = None
        self.last_run_at: Optional[datetime] = None
        self.status_file_path = Path(os.getenv("SIGNAL_MONITOR_STATUS_FILE", "/tmp/signal_monitor_status.json"))
        self._latest_status_snapshot: Dict[str, str] = {}
        self._load_persisted_status()
        # Log initialization after all attributes are set
        logger.info(
            "[SignalMonitorService] initialized | interval=%ss | max_orders_per_symbol=%d | "
            "min_price_change_pct=%.2f%% | alert_cooldown_minutes=%.1fm",
            self.monitor_interval,
            self.MAX_OPEN_ORDERS_PER_SYMBOL,
            self.MIN_PRICE_CHANGE_PCT,
            self.ALERT_COOLDOWN_MINUTES,
        )

    def _load_persisted_status(self) -> None:
        """Load last known status from disk so diagnostics can read state cross-process."""
        try:
            if not self.status_file_path.exists():
                return
            data = json.loads(self.status_file_path.read_text().strip() or "{}")
            self._latest_status_snapshot = data
            last_run_at = data.get("last_run_at")
            if last_run_at:
                try:
                    self.last_run_at = datetime.fromisoformat(last_run_at)
                except ValueError:
                    pass
            is_running = bool(data.get("is_running"))
            updated_at = data.get("updated_at")
            if is_running and updated_at:
                try:
                    updated_dt = datetime.fromisoformat(updated_at)
                    stale = datetime.now(timezone.utc) - updated_dt > timedelta(seconds=self.monitor_interval * 2)
                    if stale:
                        is_running = False
                except ValueError:
                    pass
            if not self.is_running:
                self.is_running = is_running
        except Exception:
            logger.debug("Failed to load persisted signal monitor status", exc_info=True)

    def _persist_status(self, state: str) -> None:
        """Persist current status so other processes can inspect it."""
        payload = {
            "state": state,
            "is_running": self.is_running,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        }
        try:
            self.status_file_path.write_text(json.dumps(payload))
            self._latest_status_snapshot = payload
        except Exception:
            logger.debug("Failed to persist signal monitor status", exc_info=True)

    def _log_symbol_context(
        self,
        symbol: str,
        side: str,
        watchlist_item: WatchlistItem,
        strategy_display: str,
        risk_display: str,
    ) -> None:
        context = {
            "alert_enabled": getattr(watchlist_item, "alert_enabled", None),
            "buy_alert_enabled": getattr(watchlist_item, "buy_alert_enabled", None),
            "sell_alert_enabled": getattr(watchlist_item, "sell_alert_enabled", None),
            "trade_enabled": getattr(watchlist_item, "trade_enabled", None),
            "strategy": strategy_display,
            "risk": risk_display,
            "sl_tp_mode": getattr(watchlist_item, "sl_tp_mode", None),
        }
        logger.info("SignalMonitor: evaluating symbol=%s side=%s context=%s", symbol, side, context)

    def _log_signal_candidate(self, symbol: str, side: str, details: Dict[str, Any]) -> None:
        logger.info("SignalMonitor: %s signal candidate for %s details=%s", side, symbol, details)

    def _log_signal_rejection(self, symbol: str, side: str, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        logger.info(
            "SignalMonitor: %s signal discarded for %s reason=%s details=%s",
            side,
            symbol,
            reason,
            details or {},
        )

    def _log_signal_accept(self, symbol: str, side: str, details: Optional[Dict[str, Any]] = None) -> None:
        logger.info(
            "SignalMonitor: %s signal ACCEPTED for %s details=%s",
            side,
            symbol,
            details or {},
        )

    def _evaluate_alert_flag(
        self,
        watchlist_item: WatchlistItem,
        side: str,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Centralized helper to determine whether alerts are enabled for a symbol/side.

        Returns (allowed, reason_code, details) so callers can log consistently.
        
        IMPORTANT: If alert_enabled=True but buy_alert_enabled/sell_alert_enabled is None,
        we default to True (enabled) to match UI behavior where enabling alerts enables both buy and sell.
        """
        side = side.upper()
        alert_enabled = bool(getattr(watchlist_item, "alert_enabled", False))
        # CRITICAL FIX: If alert_enabled=True but buy_alert_enabled is None, default to True
        # This matches UI behavior where enabling alerts enables both buy and sell by default
        buy_alert_enabled_raw = getattr(watchlist_item, "buy_alert_enabled", None)
        if alert_enabled and buy_alert_enabled_raw is None:
            buy_enabled = True  # Default to enabled when alert_enabled=True
        else:
            buy_enabled = bool(buy_alert_enabled_raw if buy_alert_enabled_raw is not None else False)
        
        sell_alert_enabled_raw = getattr(watchlist_item, "sell_alert_enabled", None)
        if alert_enabled and sell_alert_enabled_raw is None:
            sell_enabled = True  # Default to enabled when alert_enabled=True
        else:
            sell_enabled = bool(sell_alert_enabled_raw if sell_alert_enabled_raw is not None else False)

        if not alert_enabled:
            return False, "DISABLED_ALERT", {
                "alert_enabled": alert_enabled,
                "buy_alert_enabled": buy_enabled,
                "sell_alert_enabled": sell_enabled,
            }

        if side == "BUY" and not buy_enabled:
            return False, "DISABLED_BUY_SELL_FLAG", {
                "alert_enabled": alert_enabled,
                "buy_alert_enabled": buy_enabled,
            }

        if side == "SELL" and not sell_enabled:
            return False, "DISABLED_BUY_SELL_FLAG", {
                "alert_enabled": alert_enabled,
                "sell_alert_enabled": sell_enabled,
            }

        return True, "ALERT_ENABLED", {
            "alert_enabled": alert_enabled,
            "buy_alert_enabled": buy_enabled,
            "sell_alert_enabled": sell_enabled,
        }

    @staticmethod
    def _classify_throttle_reason(reason: Optional[str]) -> str:
        if not reason:
            return "THROTTLED"
        normalized = reason.lower()
        if "cooldown" in normalized or "minutes" in normalized:
            return "THROTTLED_MIN_TIME"
        if "price change" in normalized or "%" in normalized:
            return "THROTTLED_MIN_CHANGE"
        return "THROTTLED"
    
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
    
    def _should_monitor_inactive_coin(self) -> bool:
        """Determines if the full monitoring cycle should run for inactive coins."""
        now = time.time()
        # Check if the time elapsed since the last inactive check exceeds the period
        if now - self.last_inactive_monitor_time >= self.INACTIVE_MONITOR_PERIOD:
            self.last_inactive_monitor_time = now
            return True
        return False

    def _resolve_alert_thresholds(self, watchlist_item: WatchlistItem) -> Tuple[Optional[float], Optional[float]]:
        """
        Determine which alert thresholds apply to this coin.
        Priority order:
            1. Explicit per-coin override (min_price_change_pct and alert_cooldown_minutes columns in database)
            2. Strategy/preset defaults from trading_config.json
            3. Global defaults from trading_config.json
            4. Service-wide defaults (self.ALERT_* constants)
        """
        # Get values from database first (highest priority)
        min_pct = getattr(watchlist_item, "min_price_change_pct", None)
        cooldown = getattr(watchlist_item, "alert_cooldown_minutes", None)
        
        # If not set in database, try to get from config
        try:
            strategy_key = watchlist_item.sl_tp_mode or None
            symbol = (watchlist_item.symbol or "").upper()
            preset_min, preset_cooldown = get_alert_thresholds(symbol, strategy_key)
            if min_pct is None:
                min_pct = preset_min
            if cooldown is None:
                cooldown = preset_cooldown
        except Exception as e:
            logger.warning(f"Failed to load alert thresholds for {getattr(watchlist_item, 'symbol', '?')}: {e}")
        
        # Fallback to service-wide defaults
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
        import time
        
        # CRITICAL: Check if another thread is already processing this alert
        # This prevents race conditions when multiple cycles run simultaneously
        lock_key = f"{symbol}_{side}"
        current_time_check = time.time()
        if lock_key in self.alert_sending_locks:
            lock_timestamp = self.alert_sending_locks[lock_key]
            lock_age = current_time_check - lock_timestamp
            if lock_age < self.ALERT_SENDING_LOCK_SECONDS:
                remaining_seconds = self.ALERT_SENDING_LOCK_SECONDS - lock_age
                return False, f"Another thread is already processing {symbol} {side} alert (lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s)"
            else:
                # Lock expired, remove it
                logger.debug(f"🔓 Expired lock removed for {symbol} {side} alert (age: {lock_age:.2f}s)")
                del self.alert_sending_locks[lock_key]
        
        # Get last alert state for this symbol and side
        symbol_alerts = self.last_alert_states.get(symbol, {})
        last_alert = symbol_alerts.get(side)
        
        # If no previous alert for this symbol+side, check lock first to prevent duplicates
        if not last_alert:
            # Double-check lock to ensure we're the first to process this
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                lock_age = current_time_check - lock_timestamp
                if lock_age < self.ALERT_SENDING_LOCK_SECONDS:
                    remaining_seconds = self.ALERT_SENDING_LOCK_SECONDS - lock_age
                    return False, f"Another thread is already processing first {symbol} {side} alert (lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s)"
                else:
                    # Lock expired, remove it
                    logger.debug(f"🔓 Expired lock removed for first {symbol} {side} alert (age: {lock_age:.2f}s)")
                    del self.alert_sending_locks[lock_key]
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

    def _should_send_protection_notification(self, symbol: str, base_open: int, global_open: int) -> bool:
        """
        Check if we should send a protection notification for this symbol.
        Returns True if:
        - No previous notification was sent for this symbol, OR
        - At least PROTECTION_NOTIFICATION_COOLDOWN_MINUTES have passed since last notification, OR
        - The number of open orders has changed (increased or decreased)
        """
        now_utc = datetime.now(timezone.utc)
        last_notification = self.last_protection_notifications.get(symbol)
        
        if not last_notification:
            # First time blocking this symbol - always send notification
            return True
        
        last_time = last_notification.get("last_notification_time")
        last_base_open = last_notification.get("last_base_open", -1)
        last_global_open = last_notification.get("last_global_open", -1)
        
        if not last_time:
            return True
        
        # Normalize timezone
        if last_time.tzinfo is None:
            last_time_normalized = last_time.replace(tzinfo=timezone.utc)
        elif last_time.tzinfo != timezone.utc:
            last_time_normalized = last_time.astimezone(timezone.utc)
        else:
            last_time_normalized = last_time
        
        # Check if enough time has passed
        time_diff_minutes = (now_utc - last_time_normalized).total_seconds() / 60
        if time_diff_minutes >= self.PROTECTION_NOTIFICATION_COOLDOWN_MINUTES:
            return True
        
        # Check if the number of open orders has changed
        if base_open != last_base_open or global_open != last_global_open:
            return True
        
        # Otherwise, don't send (throttled)
        return False
    
    def _update_protection_notification_state(self, symbol: str, base_open: int, global_open: int):
        """Update the last protection notification state for a symbol"""
        self.last_protection_notifications[symbol] = {
            "last_notification_time": datetime.now(timezone.utc),
            "last_base_open": base_open,
            "last_global_open": global_open
        }
    
    @staticmethod
    def _format_price_variation(previous_price: Optional[float], current_price: float) -> Optional[str]:
        if previous_price is None or previous_price <= 0:
            return None
        try:
            change_pct = ((current_price - previous_price) / previous_price) * 100
        except ZeroDivisionError:
            return None
        return f"{change_pct:+.2f}%"
    
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
        
        # Get all watchlist items (including disabled) so we can deterministically pick a canonical row per symbol
        # IMPORTANT: Do NOT reference non-existent columns (e.g., alert_cooldown_minutes) for legacy DBs
        try:
            # CRITICAL: Rollback any previous failed transaction first to reset connection state
            try:
                db.rollback()
            except Exception:
                pass
            
            # Use load_only to avoid loading columns that don't exist in the database
            # This prevents errors when alert_cooldown_minutes or other optional columns are missing
            from sqlalchemy.orm import load_only
            columns = [
                WatchlistItem.id,
                WatchlistItem.symbol,
                WatchlistItem.exchange,
                WatchlistItem.alert_enabled,
                WatchlistItem.buy_alert_enabled,
                WatchlistItem.sell_alert_enabled,
                WatchlistItem.trade_enabled,
                WatchlistItem.trade_amount_usd,
                WatchlistItem.trade_on_margin,
                WatchlistItem.created_at,
            ]
            optional_columns = [
                getattr(WatchlistItem, "is_deleted", None),
                getattr(WatchlistItem, "take_profit", None),
                getattr(WatchlistItem, "stop_loss", None),
                getattr(WatchlistItem, "buy_target", None),
                getattr(WatchlistItem, "sell_price", None),
                getattr(WatchlistItem, "quantity", None),
                getattr(WatchlistItem, "purchase_price", None),
                getattr(WatchlistItem, "sold", None),
            ]
            for col in optional_columns:
                if col is not None:
                    columns.append(col)
            try:
                # Try with is_deleted filter first
                watchlist_rows = (
                    db.query(WatchlistItem)
                    .options(load_only(*columns))
                    .filter(WatchlistItem.is_deleted == False)
                    .all()
                )
            except Exception as e1:
                # If is_deleted column doesn't exist, rollback and try without it
                logger.debug(f"is_deleted filter failed, trying without it: {e1}")
                try:
                    db.rollback()  # Rollback the failed transaction
                    watchlist_rows = (
                        db.query(WatchlistItem)
                        .options(load_only(*columns))
                        .all()
                    )
                except Exception as e2:
                    logger.error(f"Query failed even with load_only: {e2}", exc_info=True)
                    db.rollback()
                    return []
            
            if not watchlist_rows:
                logger.warning("⚠️ No watchlist rows found in database!")
                return []
            
            grouped: Dict[str, List[WatchlistItem]] = {}
            for row in watchlist_rows:
                symbol = (row.symbol or "").upper()
                if not symbol:
                    continue
                grouped.setdefault(symbol, []).append(row)

            canonical_items: List[WatchlistItem] = []
            for symbol, rows in grouped.items():
                preferred = select_preferred_watchlist_item(rows, symbol)
                if not preferred:
                    continue
                logger.info(
                    "[MONITOR_CANONICAL] symbol=%s id=%s alert_enabled=%s buy_alert_enabled=%s sell_alert_enabled=%s trade_enabled=%s",
                    symbol,
                    getattr(preferred, "id", None),
                    getattr(preferred, "alert_enabled", None),
                    getattr(preferred, "buy_alert_enabled", None),
                    getattr(preferred, "sell_alert_enabled", None),
                    getattr(preferred, "trade_enabled", None),
                )
                if getattr(preferred, "alert_enabled", False):
                    canonical_items.append(preferred)
                else:
                    logger.info(
                        "SignalMonitor: skipping %s canonical row id=%s because alert_enabled=%s",
                        symbol,
                        getattr(preferred, "id", None),
                        getattr(preferred, "alert_enabled", None),
                    )
            
            logger.info(f"📊 Monitoring {len(canonical_items)} canonical coins with alert_enabled = true")
            return canonical_items
        except Exception as e:
            logger.error(f"Error querying alert_enabled items: {e}", exc_info=True)
            # CRITICAL: Do NOT fallback to trade_enabled - this causes alerts for coins with alert_enabled=False
            # If we can't query alert_enabled, return empty list to prevent sending alerts to wrong coins
            logger.warning("⚠️ Cannot query alert_enabled - returning empty list to prevent incorrect alerts")
            try:
                db.rollback()
            except Exception:
                pass
            return []  # Return empty list instead of using trade_enabled fallback
    
    async def monitor_signals(self, db: Session, cycle_stats: Optional[Dict[str, int]] = None):
        """Monitor signals for all coins with alert_enabled = true (for alerts)
        Orders are only created if trade_enabled = true in addition to alert_enabled = true
        """
        try:
            # Fetch watchlist items in a thread pool to avoid blocking the event loop
            watchlist_items = await asyncio.to_thread(self._fetch_watchlist_items_sync, db)
            
            if not watchlist_items:
                return
            
            if cycle_stats is None:
                cycle_stats = {
                    "symbols_processed": 0,
                    "alerts_emitted": 0,
                    "buys": 0,
                    "sells": 0,
                    "throttled": 0,
                }
            
            for item in watchlist_items:
                try:
                    cycle_stats["symbols_processed"] += 1
                    await self._check_signal_for_coin(db, item, cycle_stats)
                except Exception as e:
                    logger.error(f"Error monitoring signal for {item.symbol}: {e}", exc_info=True)
                    continue  # Continue with next coin even if one fails
        except Exception as e:
            logger.error(f"Error in monitor_signals: {e}", exc_info=True)
    
    async def _check_signal_for_coin(self, db: Session, watchlist_item: WatchlistItem, cycle_stats: Optional[Dict[str, int]] = None):
        """Async wrapper to run the synchronous signal check in a thread"""
        await asyncio.to_thread(self._check_signal_for_coin_sync, db, watchlist_item, cycle_stats)

    def _check_signal_for_coin_sync(self, db: Session, watchlist_item: WatchlistItem, cycle_stats: Optional[Dict[str, int]] = None):
        """Check signal for a specific coin and take action if needed"""
        symbol = watchlist_item.symbol
        exchange = watchlist_item.exchange or "CRYPTO_COM"
        
        try:
            # IMPORTANT: Query the canonical row again to ensure we respect dashboard updates
            fresh_item = get_canonical_watchlist_item(db, symbol)
            if fresh_item:
                old_amount = watchlist_item.trade_amount_usd
                old_alert = watchlist_item.alert_enabled
                old_margin = watchlist_item.trade_on_margin if hasattr(watchlist_item, 'trade_on_margin') else None
                # Update the watchlist_item object with fresh values
                watchlist_item.trade_amount_usd = fresh_item.trade_amount_usd
                watchlist_item.trade_enabled = fresh_item.trade_enabled
                watchlist_item.alert_enabled = fresh_item.alert_enabled
                # CRITICAL: Also refresh trade_on_margin from database
                if hasattr(fresh_item, 'trade_on_margin'):
                    watchlist_item.trade_on_margin = fresh_item.trade_on_margin
                
                # Log alert_enabled change if it changed
                if old_alert != fresh_item.alert_enabled:
                    logger.warning(
                        f"⚠️ CAMBIO DETECTADO: {symbol} - alert_enabled cambió de {old_alert} a {fresh_item.alert_enabled} "
                        f"después del refresh. Usando valor más reciente: {fresh_item.alert_enabled}"
                    )
                
                logger.info(
                    f"🔄 Refreshed {symbol} from DB: "
                    f"trade_amount_usd={old_amount} -> {watchlist_item.trade_amount_usd}, "
                    f"trade_enabled={watchlist_item.trade_enabled}, "
                    f"alert_enabled={old_alert} -> {watchlist_item.alert_enabled}, "
                    f"trade_on_margin={old_margin} -> {getattr(watchlist_item, 'trade_on_margin', None)}"
                )
            else:
                logger.warning(f"Could not find {symbol} in database for refresh")
                
                # CRITICAL: If we can't find the item, check if there are multiple entries
                try:
                    all_matching = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).all()
                    if len(all_matching) > 1:
                        logger.error(
                            f"❌ MÚLTIPLES ENTRADAS: {symbol} tiene {len(all_matching)} entradas en la base de datos. "
                            f"Esto puede causar alertas incorrectas. IDs: {[item.id for item in all_matching]}"
                        )
                        # Use the most recent non-deleted entry
                        non_deleted = [item for item in all_matching if not getattr(item, 'is_deleted', False)]
                        if non_deleted:
                            # Sort by ID (assuming higher ID = more recent) or use updated_at if available
                            latest = max(non_deleted, key=lambda x: getattr(x, 'updated_at', x.id) if hasattr(x, 'updated_at') else x.id)
                            watchlist_item.alert_enabled = latest.alert_enabled
                            watchlist_item.trade_enabled = latest.trade_enabled
                            logger.warning(
                                f"⚠️ Usando entrada más reciente para {symbol}: ID={latest.id}, "
                                f"alert_enabled={latest.alert_enabled}"
                            )
                except Exception as e:
                    logger.warning(f"Error checking for multiple entries for {symbol}: {e}")
        except Exception as e:
            logger.warning(f"Could not refresh {symbol} from DB: {e}")
        
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        strategy_display = strategy_type.value.title()
        risk_display = risk_approach.value.title()

        self._log_symbol_context(symbol, "BUY", watchlist_item, strategy_display, risk_display)
        self._log_symbol_context(symbol, "SELL", watchlist_item, strategy_display, risk_display)

        min_price_change_pct, alert_cooldown_minutes = self._resolve_alert_thresholds(watchlist_item)

        # ========================================================================
        # CRITICAL: Verify alert_enabled is True after refresh - exit early if False
        # ========================================================================
        # This prevents processing and sending alerts for coins with alert_enabled=False
        if not watchlist_item.alert_enabled:
            blocked_msg = (
                f"🚫 BLOQUEADO: {symbol} - alert_enabled=False después del refresh. "
                f"No se procesará señal ni se enviarán alertas."
            )
            self._log_signal_rejection(
                symbol,
                "BUY",
                "DISABLED_ALERT",
                {"alert_enabled": False},
            )
            self._log_signal_rejection(
                symbol,
                "SELL",
                "DISABLED_ALERT",
                {"alert_enabled": False},
            )
            logger.warning(blocked_msg)
            # Register blocked message
            try:
                from app.api.routes_monitoring import add_telegram_message
                add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
            except Exception:
                pass  # Non-critical, continue
            return  # Exit early - do not process signals or send alerts
        else:
            logger.debug(
                f"✅ {symbol} - alert_enabled=True verificado después del refresh. "
                f"Procediendo con procesamiento de señales."
            )
        
        # ========================================================================
        # DUAL-FREQUENCY POLLING: Skip heavy processing for inactive coins
        # ========================================================================
        # Check if the coin is inactive and should be skipped in this cycle
        if not watchlist_item.alert_enabled and not watchlist_item.trade_enabled:
            # If the coin is inactive, only run the heavy logic if the global inactive period is met
            if not self._should_monitor_inactive_coin():
                # Check for critical cleanup functions that must always run (e.g., SL/TP)
                # If there are no immediate actions, simply log and return
                logger.debug(f"Skipping heavy monitoring for inactive coin {watchlist_item.symbol} to save resources.")
                return
        
        # ========================================================================
        # VERIFICACIÓN DE EXPOSICIÓN: Contar exposición abierta (Global y Base)
        # ========================================================================
        # NOTA: Los límites NO bloquean las alertas, solo la creación de órdenes.
        # Las alertas siempre se envían para mantener al usuario informado.
        # La creación de órdenes se bloquea más adelante si se alcanza el límite.
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
                f"🔍 EXPOSICIÓN ACTUAL para {symbol}: Global={total_open_buy_orders}, "
                f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (informativo, no bloquea alertas)"
            )
            
            # Solo registrar si hay límite alcanzado, pero NO bloquear alertas
            if base_open >= MAX_OPEN_ORDERS_PER_SYMBOL:
                logger.info(
                    f"ℹ️  {symbol} tiene {base_open} posiciones abiertas (límite: {MAX_OPEN_ORDERS_PER_SYMBOL}). "
                    f"La alerta se enviará, pero la creación de órdenes se bloqueará si se alcanza el límite."
                )
        except Exception as e:
            logger.error(f"Error verificando exposición para {symbol}: {e}", exc_info=True)
            # No bloquear por error - continuar con el procesamiento
        
        # ========================================================================
        # CANONICAL SIGNAL EVALUATION: Use shared helper to ensure exact match with debug script
        # ========================================================================
        try:
            # Use the canonical evaluator (same logic as debug_live_signals_all.py)
            eval_result = evaluate_signal_for_symbol(db, watchlist_item, symbol)
            
            if eval_result.get("error"):
                logger.warning(f"⚠️ {symbol}: Evaluation error: {eval_result['error']}")
                if eval_result["error"] == "No price data":
                    return
                # Continue with other errors but log them
            
            # Extract values from canonical result
            decision = eval_result["decision"]
            buy_signal = eval_result["buy_signal"]
            sell_signal = eval_result["sell_signal"]
            strategy_index = eval_result["index"]
            current_price = eval_result["price"]
            rsi = eval_result["rsi"]
            ma50 = eval_result["ma50"]
            ma200 = eval_result["ma200"]
            ema10 = eval_result["ema10"]
            volume_ratio = eval_result["volume_ratio"]
            min_volume_ratio = eval_result["min_volume_ratio"]
            buy_allowed = eval_result["buy_allowed"]
            sell_allowed = eval_result["sell_allowed"]
            buy_flag_allowed = eval_result["buy_flag_allowed"]
            sell_flag_allowed = eval_result["sell_flag_allowed"]
            can_emit_buy = eval_result["can_emit_buy_alert"]
            can_emit_sell = eval_result["can_emit_sell_alert"]
            buy_throttle_status = eval_result["throttle_status_buy"]
            sell_throttle_status = eval_result["throttle_status_sell"]
            buy_reason = eval_result["throttle_reason_buy"]
            sell_reason = eval_result["throttle_reason_sell"]
            preset_name = eval_result["preset"].split("-")[0] if "-" in eval_result["preset"] else eval_result["preset"]
            risk_mode = eval_result["preset"].split("-")[1] if "-" in eval_result["preset"] else "Conservative"
            
            # Validate MAs are available before proceeding with order creation
            if ma50 is None or ema10 is None:
                missing_mas = []
                if ma50 is None:
                    missing_mas.append("MA50")
                if ema10 is None:
                    missing_mas.append("EMA10")
                logger.warning(
                    f"⚠️ {symbol}: MAs REQUIRED but missing: {', '.join(missing_mas)}. "
                    f"Cannot create buy orders without MA validation. Alerts will still be sent if conditions are met."
                )
                # Don't return - allow alerts to be sent even without MAs
            
            # Calculate resistance levels (needed for order placement)
            price_precision = 2 if current_price >= 100 else 4
            res_up = round(current_price * 1.02, price_precision)
            res_down = round(current_price * 0.98, price_precision)
            
            # Get TP/SL from signals (needed for order placement)
            # We need to call calculate_trading_signals again to get TP/SL, but use the canonical decision
            from app.models.market_price import MarketPrice, MarketData
            from price_fetcher import get_price_with_fallback
            
            mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
            md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
            
            volume_24h = mp.volume_24h or 0.0 if mp else 0.0
            current_volume = None
            if md and md.current_volume is not None and md.current_volume > 0:
                current_volume = md.current_volume
            elif volume_24h > 0:
                current_volume = volume_24h / 24.0
            
            avg_volume = None
            if md and md.avg_volume is not None and md.avg_volume > 0:
                avg_volume = md.avg_volume
            else:
                avg_volume = (volume_24h / 24.0) if volume_24h > 0 else None
            
            atr = eval_result.get("debug_flags", {}).get("atr") or (current_price * 0.02)
            ma10w = ma200 if ma200 and ma200 > 0 else (ma50 if ma50 and ma50 > 0 else current_price)
            
            # Get TP/SL for order placement (if needed)
            signals_for_tp_sl = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ma200=ma200,
                ema10=ema10,
                ma10w=ma10w,
                volume=current_volume,
                avg_volume=avg_volume,
                resistance_up=res_up,
                buy_target=watchlist_item.buy_target,
                last_buy_price=watchlist_item.purchase_price if watchlist_item.purchase_price and watchlist_item.purchase_price > 0 else None,
                position_size_usd=watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0,
                rsi_buy_threshold=40,
                rsi_sell_threshold=70,
                strategy_type=strategy_type,
                risk_approach=risk_approach,
            )
            sl_price = signals_for_tp_sl.get("sl")
            tp_price = signals_for_tp_sl.get("tp")
            
            # Determine current signal state
            current_state = decision  # Use decision from canonical evaluator
            
            # Log signal detection
            ma_info = f", MA50={ma50:.2f}, EMA10={ema10:.2f}" if ma50 is not None and ema10 is not None else ", MAs=N/A"
            logger.info(f"🔍 {symbol} signal check: buy_signal={buy_signal}, sell_signal={sell_signal}, price=${current_price:.4f}, RSI={rsi:.1f if rsi else 'N/A'}{ma_info}")
            
            if buy_signal:
                logger.info(f"🟢 BUY signal detected for {symbol}")
            elif sell_signal:
                logger.info(f"🔴 SELL signal detected for {symbol}")
            else:
                logger.debug(f"⚪ WAIT signal for {symbol} (no buy/sell conditions met)")
            
            # Handle blocked signals (throttled)
            if buy_signal and not buy_allowed:
                blocked_msg = f"🚫 BLOQUEADO: {symbol} BUY - {buy_reason}"
                if cycle_stats:
                    cycle_stats["throttled"] += 1
                self._log_signal_rejection(
                    symbol,
                    "BUY",
                    self._classify_throttle_reason(buy_reason),
                    {"throttle_reason": buy_reason},
                )
                try:
                    from app.api.routes_monitoring import add_telegram_message
                    add_telegram_message(
                        blocked_msg,
                        symbol=symbol,
                        blocked=True,
                        throttle_status="BLOCKED",
                        throttle_reason=buy_reason,
                    )
                except Exception:
                    pass
            
            if sell_signal and not sell_allowed:
                blocked_msg = f"🚫 BLOQUEADO: {symbol} SELL - {sell_reason}"
                if cycle_stats:
                    cycle_stats["throttled"] += 1
                self._log_signal_rejection(
                    symbol,
                    "SELL",
                    self._classify_throttle_reason(sell_reason),
                    {"throttle_reason": sell_reason},
                )
                try:
                    from app.api.routes_monitoring import add_telegram_message
                    add_telegram_message(
                        blocked_msg,
                        symbol=symbol,
                        blocked=True,
                        throttle_status="BLOCKED",
                        throttle_reason=sell_reason,
                    )
                    logger.info(
                        f"[LIVE_SELL_MONITORING] symbol={symbol} blocked=True throttle_status=BLOCKED reason={sell_reason}"
                    )
                except Exception:
                    pass
            
            # Log comprehensive decision (ALWAYS, even for WAIT) - matching debug script format
            origin = get_runtime_origin()
            volume_ratio_str = f"{volume_ratio:.4f}" if volume_ratio is not None else "N/A"
            alert_enabled = getattr(watchlist_item, "alert_enabled", False)
            buy_alert_enabled_raw = getattr(watchlist_item, "buy_alert_enabled", None)
            sell_alert_enabled_raw = getattr(watchlist_item, "sell_alert_enabled", None)
            trade_enabled = getattr(watchlist_item, "trade_enabled", False)
            
            logger.info(
                f"[LIVE_ALERT_DECISION] symbol={symbol} decision={decision} buy_signal={buy_signal} sell_signal={sell_signal} "
                f"can_emit_buy={can_emit_buy} can_emit_sell={can_emit_sell} buy_allowed={buy_allowed} sell_allowed={sell_allowed} "
                f"buy_flag_allowed={buy_flag_allowed} sell_flag_allowed={sell_flag_allowed} index={strategy_index} "
                f"buy_thr={buy_throttle_status} sell_thr={sell_throttle_status} "
                f"preset={eval_result['preset']} volume_ratio={volume_ratio_str} min_volume_ratio={min_volume_ratio:.4f} origin={origin}"
            )
            
            # Initialize state tracking
            now_utc = datetime.now(timezone.utc)
            buy_state_recorded = False
            sell_state_recorded = False
            
        except Exception as e:
            logger.error(f"Error in canonical signal evaluation for {symbol}: {e}", exc_info=True)
            return
        
        # ========================================================================
        # ENVÍO DE ALERTAS: Use canonical evaluator result (can_emit_buy_alert / can_emit_sell_alert)
        # IMPORTANTE: Hacer esto ANTES de toda la lógica de órdenes para garantizar que las alertas
        # se envíen incluso si hay algún return temprano en la lógica de órdenes
        # CRITICAL: Use can_emit_buy from canonical evaluator (matches debug script exactly)
        # ========================================================================
        # Log alert decision with all flags for clarity
        if buy_signal:
            if can_emit_buy:
                logger.info(
                    f"[LIVE_BUY_CALL] symbol={symbol} decision={decision} index={strategy_index} "
                    f"can_emit=True buy_thr={buy_throttle_status} "
                    f"buy_flag_allowed={buy_flag_allowed} buy_allowed={buy_allowed}"
                )
            else:
                # Determine skip reason
                skip_reason = []
                if not buy_allowed:
                    skip_reason.append(f"throttled ({buy_reason})")
                if not buy_flag_allowed:
                    skip_reason.append("buy_alert_enabled=False or alert_enabled=False")
                reason_text = ", ".join(skip_reason) or "flags/throttle blocked"
                logger.info(
                    f"[LIVE_BUY_SKIPPED] symbol={symbol} reason={reason_text} "
                    f"buy_signal=True buy_allowed={buy_allowed} buy_flag_allowed={buy_flag_allowed}"
                )
                self._log_signal_rejection(
                    symbol,
                    "BUY",
                    reason_text,
                    {"buy_allowed": buy_allowed, "buy_flag_allowed": buy_flag_allowed},
                )
        
        # CRITICAL: Use can_emit_buy from canonical evaluator (matches debug script exactly)
        if buy_signal and can_emit_buy:
            logger.info(f"🟢 NEW BUY signal detected for {symbol} - processing alert")
            logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: buy_signal=True, buy_flag_allowed=True, proceeding to alert sending logic")
            
            # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
            # This ensures only one thread can check and send an alert at a time
            # IMPORTANT: Set lock FIRST, before any checks, to prevent race conditions
            lock_key = f"{symbol}_BUY"
            lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
            import time
            current_time = time.time()
            
            # Check if we're already processing an alert for this symbol+side
            should_skip_alert = False
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                lock_age = current_time - lock_timestamp
                if lock_age < lock_timeout:
                    remaining_seconds = lock_timeout - lock_age
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: Alert sending locked (age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s), skipping duplicate check")
                    should_skip_alert = True
                else:
                    # Lock expired, remove it
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: Expired lock removed (age: {lock_age:.2f}s), proceeding")
                    del self.alert_sending_locks[lock_key]
            
            if not should_skip_alert:
                logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: No lock conflict, proceeding with alert processing")
                # Set lock IMMEDIATELY to prevent other cycles from processing the same alert
                self.alert_sending_locks[lock_key] = current_time
                logger.debug(f"🔒 Lock acquired for {symbol} BUY alert")
                
                prev_buy_price: Optional[float] = self._get_last_alert_price(symbol, "BUY")
                
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
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}"
                )
                
                # Verificar límite - solo afecta creación de órdenes, NO alertas
                # Las alertas SIEMPRE se envían para mantener al usuario informado
                should_block_order_creation = self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=final_total_open_orders)
                
                if should_block_order_creation:
                    logger.warning(
                        f"ℹ️  LÍMITE ALCANZADO para {symbol}: {base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}. "
                        f"La alerta se enviará, pero la creación de órdenes estará bloqueada."
                    )
                else:
                    logger.info(
                        f"✅ VERIFICACIÓN FINAL PASADA para {symbol}: "
                        f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}. "
                        f"Procediendo con alerta BUY y posible creación de orden."
                    )
                
                # CRITICAL: Final check - verify alert_enabled is still True before sending alert
                # This prevents alerts for coins that had alert_enabled changed while processing
                # Also refresh from database one more time to ensure we have the latest value
                db.expire_all()  # Force refresh from database
                try:
                    fresh_check = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).first()
                    if fresh_check:
                        watchlist_item.alert_enabled = fresh_check.alert_enabled
                        logger.debug(f"🔄 Última verificación de alert_enabled para {symbol}: {fresh_check.alert_enabled}")
                except Exception as e:
                    logger.warning(f"Error en última verificación de alert_enabled para {symbol}: {e}")
                
                # CRITICAL: Re-check both alert_enabled AND buy_alert_enabled before sending
                # Refresh both flags from database to ensure we have latest values
                try:
                    fresh_check = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).first()
                    if fresh_check:
                        watchlist_item.alert_enabled = fresh_check.alert_enabled
                        setattr(
                            watchlist_item,
                            "buy_alert_enabled",
                            getattr(fresh_check, "buy_alert_enabled", False),
                        )
                        setattr(
                            watchlist_item,
                            "sell_alert_enabled",
                            getattr(fresh_check, "sell_alert_enabled", False),
                        )
                        # CRITICAL FIX: If alert_enabled=True but buy_alert_enabled is None, default to True
                        buy_alert_enabled_raw = getattr(fresh_check, "buy_alert_enabled", None)
                        if fresh_check.alert_enabled and buy_alert_enabled_raw is None:
                            buy_alert_enabled = True  # Default to enabled when alert_enabled=True
                        else:
                            buy_alert_enabled = bool(buy_alert_enabled_raw if buy_alert_enabled_raw is not None else False)
                        logger.debug(
                            f"🔄 Última verificación para {symbol}: "
                            f"alert_enabled={fresh_check.alert_enabled}, "
                            f"buy_alert_enabled={buy_alert_enabled}"
                        )
                except Exception as e:
                    logger.warning(f"Error en última verificación de flags para {symbol}: {e}")
                
                final_flag_allowed, final_flag_reason, final_flag_details = self._evaluate_alert_flag(
                    watchlist_item, "BUY"
                )
                logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: Final flag check - allowed={final_flag_allowed}, reason={final_flag_reason}, details={final_flag_details}")
                
                if not final_flag_allowed:
                    if final_flag_reason == "DISABLED_ALERT":
                        blocked_msg = (
                            f"🚫 BLOQUEADO: {symbol} - alert_enabled=False en verificación final. "
                            f"No se enviará alerta aunque se detectó señal BUY."
                        )
                        log_func = logger.error
                    else:
                        blocked_msg = (
                            f"🚫 BLOQUEADO: {symbol} - buy_alert_enabled=False en verificación final. "
                            f"No se enviará alerta BUY aunque se detectó señal BUY y alert_enabled=True."
                        )
                        log_func = logger.warning
                    log_func(f"[DEBUG_ALERT_FLOW] {symbol} BUY: {blocked_msg}")
                    self._log_signal_rejection(
                        symbol,
                        "BUY",
                        final_flag_reason,
                        final_flag_details,
                    )
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: Alert BLOCKED by flag check, exiting alert flow")
                else:
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: Final flag check PASSED, proceeding to portfolio risk check")
                    # CRITICAL FIX: Portfolio risk check should ONLY block ORDERS, NEVER alerts
                    # Alerts must ALWAYS be sent when decision=BUY and alert_enabled=true
                    # This ensures users are informed even when orders are blocked by risk limits
                    should_send = True  # Always send alerts - portfolio risk only blocks orders
                    should_block_order_creation = False
                    
                    # Check portfolio value limit: Block ORDER CREATION (not alerts) if portfolio_value > 3x trade_amount_usd
                    trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                    limit_value = 3 * trade_amount_usd
                    max_position_multiple = 3
                    try:
                        portfolio_value, balance_qty = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                        
                        # Get breakdown for detailed message (re-query to get balance and open orders separately)
                        base_currency = symbol.split("_")[0] if "_" in symbol else symbol
                        base_currency = base_currency.upper()
                        balance_value_usd = 0.0
                        open_buy_value_usd = 0.0
                        
                        try:
                            from app.models.portfolio import PortfolioBalance
                            from app.services.portfolio_cache import _normalize_currency_name
                            from app.services.order_position_service import INCLUDE_OPEN_ORDERS_IN_RISK
                            
                            normalized_currency = _normalize_currency_name(base_currency)
                            portfolio_balances = (
                                db.query(PortfolioBalance)
                                .filter(PortfolioBalance.currency == normalized_currency)
                                .all()
                            )
                            for bal in portfolio_balances:
                                balance_value_usd += float(bal.usd_value) if bal.usd_value else 0.0
                            
                            if INCLUDE_OPEN_ORDERS_IN_RISK:
                                symbol_filter = _normalized_symbol_filter(symbol)
                                pending_statuses = [
                                    OrderStatusEnum.NEW,
                                    OrderStatusEnum.ACTIVE,
                                    OrderStatusEnum.PARTIALLY_FILLED,
                                ]
                                main_role_filter = or_(
                                    ExchangeOrder.order_role.is_(None),
                                    not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
                                )
                                open_buy_orders = (
                                    db.query(ExchangeOrder)
                                    .filter(
                                        symbol_filter,
                                        ExchangeOrder.side == OrderSideEnum.BUY,
                                        ExchangeOrder.status.in_(pending_statuses),
                                        main_role_filter,
                                    )
                                    .all()
                                )
                                for order in open_buy_orders:
                                    order_price = float(order.price) if order.price else current_price
                                    order_qty = float(order.cumulative_quantity or order.quantity or 0)
                                    open_buy_value_usd += order_qty * order_price
                        except Exception as breakdown_err:
                            logger.debug(f"Could not get breakdown for {symbol}: {breakdown_err}")
                        
                        should_block_order_creation = portfolio_value > limit_value
                        
                        # Log risk check result
                        logger.info(
                            "[RISK_PORTFOLIO_CHECK] symbol=%s balance_qty=%.8f balance_value_usd=%.2f "
                            "open_buy_orders_value_usd=%.2f total_value_usd=%.2f trade_amount=%.2f "
                            "limit_multiple=%s order_blocked=%s alert_will_send=True",
                            symbol,
                            balance_qty,
                            balance_value_usd,
                            open_buy_value_usd,
                            portfolio_value,
                            trade_amount_usd,
                            max_position_multiple,
                            should_block_order_creation,
                        )
                        
                        if should_block_order_creation:
                            # Build detailed message with breakdown
                            if INCLUDE_OPEN_ORDERS_IN_RISK and open_buy_value_usd > 0:
                                info_msg = (
                                    f"ℹ️ ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                                    f"Valor en cartera: ${portfolio_value:.2f} USD = "
                                    f"${balance_value_usd:.2f} balance + ${open_buy_value_usd:.2f} órdenes abiertas. "
                                    f"Límite: ${limit_value:.2f} (3x trade_amount). "
                                    f"ALERTA SE ENVIARÁ (solo se bloquea creación de orden)."
                                )
                            else:
                                info_msg = (
                                    f"ℹ️ ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                                    f"Valor en cartera: ${portfolio_value:.2f} USD (balance actual en exchange). "
                                    f"Límite: ${limit_value:.2f} (3x trade_amount). "
                                    f"ALERTA SE ENVIARÁ (solo se bloquea creación de orden)."
                                )
                            logger.info(info_msg)
                            # Note: We do NOT add this to monitoring messages - it's just a log
                            # The alert will still be sent to inform the user
                        else:
                            logger.debug(
                                f"✅ Portfolio value check passed for {symbol}: "
                                f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}. "
                                f"Both alert and order will proceed."
                            )
                    except Exception as portfolio_check_err:
                        logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with alert and order...")
                        # On error, continue (don't block alerts or orders if we can't calculate portfolio value)
                        should_block_order_creation = False
                    
                    # Send Telegram alert (only if alert_enabled = true and should_send = true)
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: About to check should_send={should_send} before sending alert")
                    if should_send:
                        logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY: should_send=True, CALLING telegram_notifier.send_buy_signal()")
                        try:
                            price_variation = self._format_price_variation(prev_buy_price, current_price)
                            ma50_text = f"{ma50:.2f}" if ma50 is not None else "N/A"
                            ema10_text = f"{ema10:.2f}" if ema10 is not None else "N/A"
                            ma200_text = f"{ma200:.2f}" if ma200 is not None else "N/A"
                            reason_text = (
                                f"{strategy_display}/{risk_display} | "
                                f"RSI={rsi:.1f}, Price={current_price:.4f}, "
                                f"MA50={ma50_text}, "
                                f"EMA10={ema10_text}, "
                                f"MA200={ma200_text}"
                            )
                            logger.info(
                                "TELEGRAM_EMIT_DEBUG | emitter=SignalMonitorService | symbol=%s | side=%s | strategy_key=%s | price=%s",
                                symbol,
                                "BUY",
                                strategy_key,
                                current_price,
                            )
                            origin = get_runtime_origin()
                            # Use central emit_alert helper
                            context = {
                                "preset": preset_name if 'preset_name' in locals() else None,
                                "risk": risk_level if 'risk_level' in locals() else None,
                                "strategy": strategy_display,
                                "risk_approach": risk_display,
                                "throttle_status": "SENT",
                                "throttle_reason": buy_reason,
                            }
                            
                            result = emit_alert(
                                symbol=symbol,
                                side="BUY",
                                reason=reason_text,
                                price=current_price,
                                context=context,
                                strategy_type=strategy_display,
                                risk_approach=risk_display,
                                price_variation=price_variation,
                                throttle_status="SENT",
                                throttle_reason=buy_reason,
                            )
                            
                            # Update cycle stats
                            if result:
                                if cycle_stats:
                                    cycle_stats["alerts_emitted"] += 1
                                    cycle_stats["buys"] += 1
                                logger.info(
                                    f"✅ BUY alert SENT for {symbol}: alert_enabled={watchlist_item.alert_enabled}, "
                                    f"buy_alert_enabled={buy_alert_enabled}, sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)} - {reason_text}"
                                )
                            else:
                                # Telegram API may have failed, but alert was attempted - log as warning, not block
                                logger.warning(
                                    f"[ALERT_EMIT_FINAL] side=BUY symbol={symbol} origin={origin} "
                                    f"sent=False blocked=False throttle_status=SENT throttle_reason={buy_reason} "
                                    f"monitoring_saved={monitoring_saved} error=telegram_api_failed"
                                )
                            
                            # Always log signal acceptance and update state - alert was attempted regardless of Telegram API result
                            self._log_signal_accept(
                                symbol,
                                "BUY",
                                {"telegram": "sent" if result else "telegram_api_failed", "reason": reason_text},
                            )
                            # CRITICAL: Update alert state ONLY after send attempt to prevent duplicate alerts
                            # This ensures that if multiple calls happen simultaneously, only the first one will update the state
                            self._update_alert_state(symbol, "BUY", current_price)
                            try:
                                record_signal_event(
                                    db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="BUY",
                                    price=current_price,
                                    source="alert",
                                )
                                buy_state_recorded = True
                            except Exception as state_err:
                                logger.warning(f"Failed to persist BUY throttle state for {symbol}: {state_err}")
                        except Exception as e:
                            logger.warning(f"Failed to send Telegram BUY alert for {symbol}: {e}")
                            # If sending failed, do NOT update the state - allow retry on next cycle
                    else:
                        logger.warning(f"[DEBUG_ALERT_FLOW] {symbol} BUY: ⏭️  ALERT BLOCKED - should_send=False. This should NOT happen when decision=BUY and alert_enabled=True!")
                
                # Always remove lock when done
                if lock_key in self.alert_sending_locks:
                    del self.alert_sending_locks[lock_key]
            
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
            
            # ========================================================================
            # NOTA: El bloque de alertas ahora se ejecuta ANTES de la lógica de órdenes
            # (líneas 765-965) para garantizar que las alertas se envíen incluso si hay
            # algún return temprano en la lógica de órdenes
            # BLOQUE DUPLICADO REMOVIDO - Las alertas se procesan arriba (líneas 765-965)
            # ========================================================================
            
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
                
                prev_buy_price: Optional[float] = self._get_last_alert_price(symbol, "BUY")
                
                # CRITICAL: Throttling was already checked earlier using should_emit_signal() (database-based)
                # At this point, if buy_signal=True, it means throttle passed. We should send the alert.
                # The should_send_alert() check here is redundant and uses in-memory state which can be out of sync.
                # We'll skip it and proceed directly to sending, but keep the lock mechanism for race condition prevention.
                should_send = True  # Early throttle already passed, so we should send
                throttle_reason = "Early throttle check passed (database-based)"
                
                self._log_signal_accept(
                    symbol,
                    "BUY",
                    {
                        "price": current_price,
                        "trade_enabled": getattr(watchlist_item, "trade_enabled", None),
                        "min_price_change_pct": throttle_config.min_price_change_pct,
                        "cooldown_minutes": throttle_config.min_interval_minutes,
                    },
                )
                
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
                    f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}"
                )
                
                # Verificar límite - solo afecta creación de órdenes, NO alertas
                # Las alertas SIEMPRE se envían para mantener al usuario informado
                should_block_order_creation = self._should_block_open_orders(base_open, MAX_OPEN_ORDERS_PER_SYMBOL, global_open=final_total_open_orders)
                
                if should_block_order_creation:
                    logger.warning(
                        f"ℹ️  LÍMITE ALCANZADO para {symbol}: {base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}. "
                        f"La alerta se enviará, pero la creación de órdenes estará bloqueada."
                    )
                    # Bloquear creación de órdenes, pero NO bloquear alertas
                    should_create_order = False
                else:
                    logger.info(
                        f"✅ VERIFICACIÓN FINAL PASADA para {symbol}: "
                        f"{base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL}. "
                        f"Procediendo con alerta BUY y posible creación de orden."
                    )
                
                # CRITICAL: Final check - verify alert_enabled is still True before sending alert
                # This prevents alerts for coins that had alert_enabled changed while processing
                # Also refresh from database one more time to ensure we have the latest value
                db.expire_all()  # Force refresh from database
                try:
                    fresh_check = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).first()
                    if fresh_check:
                        watchlist_item.alert_enabled = fresh_check.alert_enabled
                        logger.debug(f"🔄 Última verificación de alert_enabled para {symbol}: {fresh_check.alert_enabled}")
                except Exception as e:
                    logger.warning(f"Error en última verificación de alert_enabled para {symbol}: {e}")
                
                if not watchlist_item.alert_enabled:
                    blocked_msg = (
                        f"🚫 BLOQUEADO: {symbol} - alert_enabled=False en verificación final. "
                        f"No se enviará alerta aunque se detectó señal BUY."
                    )
                    logger.error(blocked_msg)
                    # Register blocked message
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    # Remove locks and exit
                    if symbol in self.order_creation_locks:
                        del self.order_creation_locks[symbol]
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                    return  # Exit without sending alert
                
                # CRITICAL FIX: Portfolio risk check should ONLY block ORDERS, NEVER alerts
                # Alerts must ALWAYS be sent when decision=BUY and alert_enabled=true
                # This ensures users are informed even when orders are blocked by risk limits
                should_send = True  # Always send alerts - portfolio risk only blocks orders
                should_block_order_creation = False
                
                # Check portfolio value limit: Block ORDER CREATION (not alerts) if portfolio_value > 3x trade_amount_usd
                trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                limit_value = 3 * trade_amount_usd
                max_position_multiple = 3
                try:
                    portfolio_value, balance_qty = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                    
                    # Get breakdown for detailed message
                    base_currency = symbol.split("_")[0] if "_" in symbol else symbol
                    base_currency = base_currency.upper()
                    balance_value_usd = 0.0
                    open_buy_value_usd = 0.0
                    
                    try:
                        from app.models.portfolio import PortfolioBalance
                        from app.services.portfolio_cache import _normalize_currency_name
                        
                        normalized_currency = _normalize_currency_name(base_currency)
                        portfolio_balances = (
                            db.query(PortfolioBalance)
                            .filter(PortfolioBalance.currency == normalized_currency)
                            .all()
                        )
                        for bal in portfolio_balances:
                            balance_value_usd += float(bal.usd_value) if bal.usd_value else 0.0
                        
                        if INCLUDE_OPEN_ORDERS_IN_RISK:
                            symbol_filter = _normalized_symbol_filter(symbol)
                            pending_statuses = [
                                OrderStatusEnum.NEW,
                                OrderStatusEnum.ACTIVE,
                                OrderStatusEnum.PARTIALLY_FILLED,
                            ]
                            main_role_filter = or_(
                                ExchangeOrder.order_role.is_(None),
                                not_(ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"])),
                            )
                            open_buy_orders = (
                                db.query(ExchangeOrder)
                                .filter(
                                    symbol_filter,
                                    ExchangeOrder.side == OrderSideEnum.BUY,
                                    ExchangeOrder.status.in_(pending_statuses),
                                    main_role_filter,
                                )
                                .all()
                            )
                            for order in open_buy_orders:
                                order_price = float(order.price) if order.price else current_price
                                order_qty = float(order.cumulative_quantity or order.quantity or 0)
                                open_buy_value_usd += order_qty * order_price
                    except Exception as breakdown_err:
                        logger.debug(f"Could not get breakdown for {symbol}: {breakdown_err}")
                    
                    should_block_order_creation = portfolio_value > limit_value
                    
                    # Log risk check result
                    logger.info(
                        "[RISK_PORTFOLIO_CHECK] symbol=%s balance_qty=%.8f balance_value_usd=%.2f "
                        "open_buy_orders_value_usd=%.2f total_value_usd=%.2f trade_amount=%.2f "
                        "limit_multiple=%s order_blocked=%s alert_will_send=True",
                        symbol,
                        balance_qty,
                        balance_value_usd,
                        open_buy_value_usd,
                        portfolio_value,
                        trade_amount_usd,
                        max_position_multiple,
                        should_block_order_creation,
                    )
                    
                    if should_block_order_creation:
                        # Build detailed message with breakdown
                        if INCLUDE_OPEN_ORDERS_IN_RISK and open_buy_value_usd > 0:
                            info_msg = (
                                f"ℹ️ ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                                f"Valor en cartera: ${portfolio_value:.2f} USD = "
                                f"${balance_value_usd:.2f} balance + ${open_buy_value_usd:.2f} órdenes abiertas. "
                                f"Límite: ${limit_value:.2f} (3x trade_amount). "
                                f"ALERTA SE ENVIARÁ (solo se bloquea creación de orden)."
                            )
                        else:
                            info_msg = (
                                f"ℹ️ ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                                f"Valor en cartera: ${portfolio_value:.2f} USD (balance actual en exchange). "
                                f"Límite: ${limit_value:.2f} (3x trade_amount). "
                                f"ALERTA SE ENVIARÁ (solo se bloquea creación de orden)."
                            )
                        logger.info(info_msg)
                        # Note: We do NOT add this to monitoring messages - it's just a log
                        # The alert will still be sent to inform the user
                    else:
                        logger.debug(
                            f"✅ Portfolio value check passed for {symbol}: "
                            f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}. "
                            f"Both alert and order will proceed."
                        )
                except Exception as portfolio_check_err:
                    logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with alert and order...")
                    # On error, continue (don't block alerts or orders if we can't calculate portfolio value)
                    should_block_order_creation = False
                
                # Send Telegram alert (only if alert_enabled = true and should_send = true)
                logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY (legacy path): About to check should_send={should_send} before sending alert")
                if should_send:
                    logger.info(f"[DEBUG_ALERT_FLOW] {symbol} BUY (legacy path): should_send=True, CALLING telegram_notifier.send_buy_signal()")
                    try:
                        price_variation = self._format_price_variation(prev_buy_price, current_price)
                        ma50_text = f"{ma50:.2f}" if ma50 is not None else "N/A"
                        ema10_text = f"{ema10:.2f}" if ema10 is not None else "N/A"
                        ma200_text = f"{ma200:.2f}" if ma200 is not None else "N/A"
                        reason_text = (
                            f"{strategy_display}/{risk_display} | "
                            f"RSI={rsi:.1f}, Price={current_price:.4f}, "
                            f"MA50={ma50_text}, "
                            f"EMA10={ema10_text}, "
                            f"MA200={ma200_text}"
                        )
                        logger.info(
                            "TELEGRAM_EMIT_DEBUG | emitter=SignalMonitorService (legacy BUY path) | symbol=%s | side=%s | strategy_key=%s | price=%s",
                            symbol,
                            "BUY",
                            strategy_key,
                            current_price,
                        )
                        origin = get_runtime_origin()
                        result = telegram_notifier.send_buy_signal(
                            symbol=symbol,
                            price=current_price,
                            reason=reason_text,
                            strategy_type=strategy_display,
                            risk_approach=risk_display,
                            price_variation=price_variation,
                            source="LIVE ALERT",
                            throttle_status="SENT",
                            throttle_reason=buy_reason,
                            origin=origin,
                        )
                        # CRITICAL: Alerts should NEVER be blocked after all conditions are met.
                        # send_buy_signal() may return False due to Telegram API errors, but we still
                        # consider the alert as "attempted" and log it accordingly.
                        # Only order creation may be blocked, never alerts.
                        if result:
                            origin = get_runtime_origin()
                            logger.info(
                                f"[ALERT_EMIT_FINAL] origin={origin} symbol={symbol} | side=BUY | status=success | "
                                f"price={current_price:.4f} | strategy={strategy_display}-{risk_display}"
                            )
                            if cycle_stats:
                                cycle_stats["alerts_emitted"] += 1
                                cycle_stats["buys"] += 1
                            # Message already registered in send_buy_signal as sent
                            logger.info(f"✅ BUY alert sent for {symbol} (alert_enabled=True verified) - {reason_text}")
                        else:
                            # Telegram API may have failed, but alert was attempted - log as warning, not block
                            logger.warning(
                                f"[ALERT_EMIT_FINAL] symbol={symbol} | side=BUY | status=telegram_api_failed | price={current_price:.4f} | "
                                f"Alert was attempted but Telegram API returned False. This is NOT a block - alert conditions were met."
                            )
                        
                        # Always update alert state - alert was attempted regardless of Telegram API result
                        # CRITICAL: Update alert state ONLY after send attempt to prevent duplicate alerts
                        # This ensures that if multiple calls happen simultaneously, only the first one will update the state
                        self._update_alert_state(symbol, "BUY", current_price)
                        if not buy_state_recorded:
                            try:
                                record_signal_event(
                                    db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="BUY",
                                    price=current_price,
                                    source="alert",
                                )
                                buy_state_recorded = True
                            except Exception as state_err:
                                logger.warning(f"Failed to persist BUY throttle state for {symbol}: {state_err}")
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram BUY alert for {symbol}: {e}")
                        # If sending failed, do NOT update the state - allow retry on next cycle
                    finally:
                        # Always remove lock when done
                        if lock_key in self.alert_sending_locks:
                            del self.alert_sending_locks[lock_key]
                else:
                    logger.warning(f"[DEBUG_ALERT_FLOW] {symbol} BUY (legacy path): ⏭️  ALERT BLOCKED - should_send=False. This should NOT happen when decision=BUY and alert_enabled=True!")
                    # Remove lock when alert is blocked
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                
                # Create order automatically ONLY if trade_enabled = true AND alert_enabled = true
                # alert_enabled = true is already filtered, so we only need to check trade_enabled
                logger.info(f"🔍 Checking order creation for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}, alert_enabled={watchlist_item.alert_enabled}")
                
                # CRITICAL: Verify alert_enabled is still True before creating order
                if not watchlist_item.alert_enabled:
                    logger.warning(
                        f"🚫 ORDEN BLOQUEADA: {symbol} - alert_enabled=False. "
                        f"No se creará orden aunque se detectó señal BUY."
                    )
                    # Remove locks and exit
                    if symbol in self.order_creation_locks:
                        del self.order_creation_locks[symbol]
                    return  # Exit without creating order
                
                # CRITICAL: Final validation - MAs must be available before creating order
                if ma50 is None or ema10 is None:
                    missing_mas = []
                    if ma50 is None:
                        missing_mas.append("MA50")
                    if ema10 is None:
                        missing_mas.append("EMA10")
                    error_msg = f"❌ Cannot create BUY order for {symbol}: MAs REQUIRED but missing: {', '.join(missing_mas)}"
                    logger.error(error_msg)
                    # Bloquear silenciosamente - no enviar notificación a Telegram
                    return  # Exit - cannot create order without MAs
                
                # Log MA values for verification
                logger.info(f"✅ MA validation passed for {symbol}: MA50={ma50:.2f}, EMA10={ema10:.2f}, MA50>EMA10={ma50 > ema10}")
                
                # CRITICAL: Use should_block_order_creation from earlier check (already calculated before alert was sent)
                # This ensures portfolio risk only blocks orders, not alerts (which were already sent above)
                if should_block_order_creation:
                    logger.warning(
                        f"🚫 ORDEN BLOQUEADA POR VALOR EN CARTERA: {symbol} - "
                        f"Límite de riesgo alcanzado. "
                        f"No se creará orden aunque se detectó señal BUY y la alerta ya fue enviada."
                    )
                    # Remove locks and exit
                    if symbol in self.order_creation_locks:
                        del self.order_creation_locks[symbol]
                    return  # Exit without creating order
                
                if watchlist_item.trade_enabled:
                    if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                        logger.info(f"✅ Trade enabled for {symbol} - creating BUY order automatically")
                        try:
                            # Use asyncio.run() to execute async function from sync context
                            import asyncio
                            order_result = asyncio.run(self._create_buy_order(db, watchlist_item, current_price, res_up, res_down))
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
                                persist_price = filled_price or current_price
                                if not buy_state_recorded:
                                    try:
                                        record_signal_event(
                                            db,
                                            symbol=symbol,
                                            strategy_key=strategy_key,
                                            side="BUY",
                                            price=persist_price,
                                            source="order",
                                        )
                                        buy_state_recorded = True
                                    except Exception as state_err:
                                        logger.warning(f"Failed to persist BUY throttle state after order for {symbol}: {state_err}")
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
        
        # ========================================================================
        # ENVÍO DE ALERTAS SELL: Use canonical evaluator result (can_emit_sell_alert)
        # IMPORTANTE: Similar a las alertas BUY, pero solo alertas (no órdenes automáticas)
        # CRITICAL: This block is at the SAME level as BUY block, not nested inside it
        # ========================================================================
        # Log alert decision with all flags for clarity
        if sell_signal:
            origin = get_runtime_origin()
            logger.info(
                f"[LIVE_SELL_DECISION] symbol={symbol} decision={decision} sell_signal={sell_signal} "
                f"trade_enabled={getattr(watchlist_item, 'trade_enabled', False)} "
                f"sell_flag_allowed={sell_flag_allowed} origin={origin}"
            )
            # Log throttle decision
            logger.info(
                f"[LIVE_SELL_THROTTLE] symbol={symbol} can_emit_sell={can_emit_sell} "
                f"sell_allowed={sell_allowed} sell_flag_allowed={sell_flag_allowed} reason={sell_reason if not sell_allowed else ''}"
            )
            # Check if SELL alert can be emitted (matching debug script: can_emit_sell_alert = sell_allowed and sell_alert_enabled)
            if can_emit_sell:
                logger.info(
                    f"[LIVE_SELL_CALL] symbol={symbol} decision={decision} index={strategy_index} "
                    f"can_emit=True sell_thr={sell_throttle_status} "
                    f"sell_flag_allowed={sell_flag_allowed} sell_allowed={sell_allowed}"
                )
            else:
                # Determine skip reason
                skip_reason = []
                if not sell_allowed:
                    skip_reason.append(f"throttled ({sell_reason})")
                if not sell_flag_allowed:
                    skip_reason.append("sell_alert_enabled=False or alert_enabled=False")
                reason_text = ", ".join(skip_reason) or "flags/throttle blocked"
                logger.info(
                    f"[LIVE_SELL_SKIPPED] symbol={symbol} reason={reason_text} "
                    f"sell_signal=True sell_allowed={sell_allowed} sell_flag_allowed={sell_flag_allowed}"
                )
                self._log_signal_rejection(
                    symbol,
                    "SELL",
                    reason_text,
                    {"sell_allowed": sell_allowed, "sell_flag_allowed": sell_flag_allowed},
                )
        
        # CRITICAL: Use can_emit_sell from canonical evaluator (matches debug script exactly)
        if sell_signal and can_emit_sell:
            logger.info(f"🔴 NEW SELL signal detected for {symbol} - processing alert")
            logger.info(f"[DEBUG_ALERT_FLOW] {symbol} SELL: sell_signal=True, sell_flag_allowed=True, proceeding to alert sending logic")
            
            # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
            lock_key = f"{symbol}_SELL"
            lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
            current_time = time.time()
            
            # Check if we're already processing an alert for this symbol+side
            should_skip_alert = False
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                lock_age = current_time - lock_timestamp
                if lock_age < lock_timeout:
                    remaining_seconds = lock_timeout - lock_age
                    logger.debug(f"🔒 Alert sending already in progress for {symbol} SELL (lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s), skipping duplicate check")
                    should_skip_alert = True
                else:
                    # Lock expired, remove it
                    logger.debug(f"🔓 Expired lock removed for {symbol} SELL (age: {lock_age:.2f}s)")
                    del self.alert_sending_locks[lock_key]
            
            if not should_skip_alert:
                # Set lock IMMEDIATELY to prevent other cycles from processing the same alert
                self.alert_sending_locks[lock_key] = current_time
                logger.debug(f"🔒 Lock acquired for {symbol} SELL alert")
                
                prev_sell_price: Optional[float] = self._get_last_alert_price(symbol, "SELL")
                
                # CRITICAL: Use values from canonical evaluator (already checked throttle and flags)
                # can_emit_sell = True means both throttle and flags allow emission
                should_send = can_emit_sell  # Use canonical result
                throttle_status = sell_throttle_status  # From canonical evaluator
                throttle_reason_for_send = sell_reason if not sell_allowed else ""
                
                # Get throttle config for logging
                from app.services.config_loader import get_alert_thresholds
                min_price_change_pct = getattr(watchlist_item, "min_price_change_pct", None)
                alert_cooldown_minutes = getattr(watchlist_item, "alert_cooldown_minutes", None)
                try:
                    preset_min, preset_cooldown = get_alert_thresholds(symbol, strategy_key)
                    if min_price_change_pct is None:
                        min_price_change_pct = preset_min
                    if alert_cooldown_minutes is None:
                        alert_cooldown_minutes = preset_cooldown
                except Exception:
                    pass
                if min_price_change_pct is None:
                    min_price_change_pct = self.ALERT_MIN_PRICE_CHANGE_PCT
                if alert_cooldown_minutes is None:
                    alert_cooldown_minutes = self.ALERT_COOLDOWN_MINUTES
                
                self._log_signal_accept(
                    symbol,
                    "SELL",
                    {
                        "price": current_price,
                        "trade_enabled": getattr(watchlist_item, "trade_enabled", None),
                        "min_price_change_pct": min_price_change_pct,
                        "cooldown_minutes": alert_cooldown_minutes,
                    },
                )
                
                # CRITICAL: Final check - verify sell_alert_enabled before sending
                # Refresh flag from database to ensure we have latest value
                db.expire_all()  # Force refresh from database
                try:
                    fresh_check = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).first()
                    if fresh_check:
                        setattr(
                            watchlist_item,
                            "sell_alert_enabled",
                            getattr(fresh_check, "sell_alert_enabled", False),
                        )
                        setattr(
                            watchlist_item,
                            "alert_enabled",
                            getattr(fresh_check, "alert_enabled", watchlist_item.alert_enabled),
                        )
                        logger.debug(
                            f"🔄 Última verificación de sell_alert_enabled para {symbol}: "
                            f"{getattr(fresh_check, 'sell_alert_enabled', False)}"
                        )
                except Exception as e:
                    logger.warning(f"Error en última verificación de flags para {symbol}: {e}")
                
                final_sell_allowed, final_sell_reason, final_sell_details = self._evaluate_alert_flag(
                    watchlist_item, "SELL"
                )
                
                if not final_sell_allowed:
                    if final_sell_reason == "DISABLED_ALERT":
                        blocked_msg = (
                            f"🚫 BLOQUEADO: {symbol} SELL - alert_enabled=False en verificación final. "
                            f"No se enviará alerta SELL aunque se detectó señal SELL."
                        )
                    else:
                        blocked_msg = (
                            f"🚫 BLOQUEADO: {symbol} SELL - sell_alert_enabled=False en verificación final. "
                            f"No se enviará alerta SELL aunque se detectó señal SELL."
                        )
                    self._log_signal_rejection(
                        symbol,
                        "SELL",
                        final_sell_reason,
                        final_sell_details,
                    )
                    logger.warning(blocked_msg)
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                        logger.info(
                            f"[LIVE_SELL_MONITORING] symbol={symbol} blocked=True throttle_status=BLOCKED reason={final_sell_reason}"
                        )
                    except Exception:
                        pass  # Non-critical, continue
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                else:
                    # Send Telegram alert (early throttle already passed, sell_alert_enabled verified)
                    # should_send is always True here because early throttle check already filtered out throttled signals
                    if should_send:
                        try:
                            price_variation = self._format_price_variation(prev_sell_price, current_price)
                            ma50_text = f"{ma50:.2f}" if ma50 is not None else "N/A"
                            ema10_text = f"{ema10:.2f}" if ema10 is not None else "N/A"
                            ma200_text = f"{ma200:.2f}" if ma200 is not None else "N/A"
                            reason_text = (
                                f"{strategy_display}/{risk_display} | "
                                f"RSI={rsi:.1f}, Price={current_price:.4f}, "
                                f"MA50={ma50_text}, "
                                f"EMA10={ema10_text}, "
                                f"MA200={ma200_text}"
                            )
                            origin = get_runtime_origin()
                            logger.info(
                                f"[LIVE_SELL_CALL] symbol={symbol} can_emit={should_send} origin={origin} "
                                f"throttle_status={throttle_status} reason={throttle_reason_for_send}"
                            )
                            
                            # Use central emit_alert helper
                            context = {
                                "preset": preset_name if 'preset_name' in locals() else None,
                                "risk": risk_level if 'risk_level' in locals() else None,
                                "strategy": strategy_display,
                                "risk_approach": risk_display,
                                "throttle_status": throttle_status,
                                "throttle_reason": throttle_reason_for_send,
                            }
                            
                            result = emit_alert(
                                symbol=symbol,
                                side="SELL",
                                reason=reason_text,
                                price=current_price,
                                context=context,
                                strategy_type=strategy_display,
                                risk_approach=risk_display,
                                price_variation=price_variation,
                                throttle_status=throttle_status,
                                throttle_reason=throttle_reason_for_send,
                            )
                            # CRITICAL: Alerts should NEVER be blocked after all conditions are met.
                            # send_sell_signal() may return False due to Telegram API errors, but we still
                            # consider the alert as "attempted" and log it accordingly.
                            # Only order creation may be blocked, never alerts.
                            # Ensure monitoring registration even if Telegram fails
                            monitoring_saved = False
                            if result:
                                # Monitoring already registered in send_sell_signal
                                monitoring_saved = True
                            else:
                                # Telegram failed, but we should still register in monitoring
                                try:
                                    from app.api.routes_monitoring import add_telegram_message
                                    add_telegram_message(
                                        f"🔴 SELL SIGNAL: {symbol} - {reason_text} (Telegram send failed)",
                                        symbol=symbol,
                                        blocked=False,
                                        throttle_status=throttle_status,
                                        throttle_reason=throttle_reason_for_send,
                                    )
                                    monitoring_saved = True
                                except Exception as mon_err:
                                    logger.warning(f"Failed to register SELL alert in Monitoring after Telegram failure: {mon_err}")
                            
                            origin = get_runtime_origin()
                            if result:
                                logger.info(
                                    f"[ALERT_EMIT_FINAL] side=SELL symbol={symbol} origin={origin} "
                                    f"sent=True blocked=False throttle_status={throttle_status} throttle_reason={throttle_reason_for_send} "
                                    f"monitoring_saved={monitoring_saved}"
                                )
                                if cycle_stats:
                                    cycle_stats["alerts_emitted"] += 1
                                    cycle_stats["sells"] += 1
                                logger.info(
                                    f"✅ SELL alert SENT for {symbol}: "
                                    f"buy_alert_enabled={getattr(watchlist_item, 'buy_alert_enabled', False)}, sell_alert_enabled={sell_alert_enabled} - {reason_text}"
                                )
                            else:
                                # Telegram API may have failed, but alert was attempted - log as warning, not block
                                logger.warning(
                                    f"[ALERT_EMIT_FINAL] side=SELL symbol={symbol} origin={origin} "
                                    f"sent=False blocked=False throttle_status={throttle_status} throttle_reason={throttle_reason_for_send} "
                                    f"monitoring_saved={monitoring_saved} error=telegram_api_failed"
                                )
                            
                            # Always log signal acceptance and update state - alert was attempted regardless of Telegram API result
                            self._log_signal_accept(
                                symbol,
                                "SELL",
                                {"telegram": "sent" if result else "telegram_api_failed", "reason": reason_text},
                            )
                            # CRITICAL: Update alert state ONLY after send attempt to prevent duplicate alerts
                            self._update_alert_state(symbol, "SELL", current_price)
                            if not sell_state_recorded:
                                try:
                                    record_signal_event(
                                        db,
                                        symbol=symbol,
                                        strategy_key=strategy_key,
                                        side="SELL",
                                        price=current_price,
                                        source="alert",
                                    )
                                    sell_state_recorded = True
                                except Exception as state_err:
                                    logger.warning(f"Failed to persist SELL throttle state for {symbol}: {state_err}")
                            
                            # Log Monitoring registration
                            logger.info(
                                f"[LIVE_SELL_MONITORING] symbol={symbol} blocked=False throttle_status={throttle_status}"
                            )
                            
                            # ========================================================================
                            # CREAR ORDEN SELL AUTOMÁTICA: Si trade_enabled=True y trade_amount_usd > 0
                            # ========================================================================
                            if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                                logger.info(f"🔴 Trade enabled for {symbol} - creating SELL order automatically after alert")
                                try:
                                    # Use asyncio.run() to execute async function from sync context
                                    import asyncio
                                    order_result = asyncio.run(self._create_sell_order(db, watchlist_item, current_price, res_up, res_down))
                                    if order_result:
                                        filled_price = order_result.get("filled_price")
                                        if filled_price:
                                            logger.info(f"✅ SELL order created successfully for {symbol}: filled_price=${filled_price:.4f}")
                                        persist_price = filled_price or current_price
                                        if not sell_state_recorded:
                                            try:
                                                record_signal_event(
                                                    db,
                                                    symbol=symbol,
                                                    strategy_key=strategy_key,
                                                    side="SELL",
                                                    price=persist_price,
                                                    source="order",
                                                )
                                                sell_state_recorded = True
                                            except Exception as state_err:
                                                logger.warning(f"Failed to persist SELL throttle state after order for {symbol}: {state_err}")
                                    else:
                                        logger.warning(f"⚠️ SELL order creation returned None for {symbol}")
                                except Exception as order_err:
                                    logger.error(f"❌ SELL order creation failed for {symbol}: {order_err}", exc_info=True)
                                    # Don't raise - alert was sent, order creation is secondary
                            else:
                                logger.info(f"ℹ️ SELL alert sent for {symbol} but trade_enabled=False or trade_amount_usd not configured - no order created")
                        except Exception as e:
                            logger.warning(f"Failed to send Telegram SELL alert for {symbol}: {e}")
                            # If sending failed, do NOT update the state - allow retry on next cycle
                    else:
                        logger.debug(f"⏭️  Skipping SELL alert send for {symbol} - should_send=False")
                
                # Always remove lock when done
                if lock_key in self.alert_sending_locks:
                    del self.alert_sending_locks[lock_key]
        
        # Handle SELL signal state update (for internal tracking)
        if current_state == "SELL":
                state_entry = self.last_signal_states.get(symbol, {})
                state_entry.update({
                    "state": "SELL",
                    "timestamp": datetime.utcnow(),
                    "orders_count": state_entry.get("orders_count", 0)  # Preserve orders count
                })
                self.last_signal_states[symbol] = state_entry
    
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
                # Bloquear silenciosamente - no enviar notificación a Telegram
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
    
    async def _create_sell_order(self, db: Session, watchlist_item: WatchlistItem, 
                                 current_price: float, res_up: float, res_down: float):
        """Create a SELL order automatically based on signal"""
        symbol = watchlist_item.symbol
        
        # Validate that trade_amount_usd is configured - REQUIRED, no default
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
            logger.error(f"Cannot create SELL order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
            
            # Send error notification to Telegram
            try:
                telegram_notifier.send_message(
                    f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                    f"📊 Symbol: <b>{symbol}</b>\n"
                    f"🔴 Side: SELL\n"
                    f"❌ Error: {error_message}"
                )
            except Exception as e:
                logger.warning(f"Failed to send Telegram error notification: {e}")
            
            raise ValueError(error_message)
        
        amount_usd = watchlist_item.trade_amount_usd
        
        # For SELL orders, we need to check if we have enough balance of the base currency
        # Extract base currency from symbol (e.g., ETH from ETH_USDT)
        base_currency = symbol.split('_')[0] if '_' in symbol else symbol
        
        try:
            account_summary = trade_client.get_account_summary()
            available_balance = 0
            
            if 'accounts' in account_summary or 'data' in account_summary:
                accounts = account_summary.get('accounts') or account_summary.get('data', {}).get('accounts', [])
                for acc in accounts:
                    currency = acc.get('currency', '').upper()
                    # Check for base currency (e.g., ETH for ETH_USDT)
                    if currency == base_currency:
                        available = float(acc.get('available', '0') or '0')
                        available_balance = available
                        break
            
            # Calculate required quantity
            required_qty = amount_usd / current_price
            logger.info(f"💰 Balance check para SELL {symbol}: available={available_balance:.8f} {base_currency}, required={required_qty:.8f} {base_currency} (${amount_usd:,.2f} USD)")
            
            # If we don't have enough base currency, cannot create SELL order
            if available_balance < required_qty:
                logger.warning(
                    f"🚫 BLOQUEO POR BALANCE: {symbol} - Balance insuficiente para orden SELL. "
                    f"Available: {available_balance:.8f} {base_currency} < Required: {required_qty:.8f} {base_currency}. "
                    f"No se intentará crear la orden para evitar error 306."
                )
                try:
                    telegram_notifier.send_message(
                        f"💰 <b>BALANCE INSUFICIENTE</b>\n\n"
                        f"📊 Se detectó señal SELL para <b>{symbol}</b>\n"
                        f"💵 Amount requerido: <b>${amount_usd:,.2f}</b>\n"
                        f"📦 Quantity requerida: <b>{required_qty:.8f} {base_currency}</b>\n"
                        f"💰 Balance disponible: <b>{available_balance:.8f} {base_currency}</b>\n\n"
                        f"⚠️ <b>No se creará orden</b> - Balance insuficiente\n"
                        f"💡 Compra más {base_currency} o reduce el tamaño de las órdenes"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram balance notification: {e}")
                return None
        except Exception as balance_check_err:
            logger.warning(f"⚠️ No se pudo verificar balance para SELL {symbol}: {balance_check_err}. Continuando con creación de orden...")
        
        # Read trade_on_margin from database
        user_wants_margin = watchlist_item.trade_on_margin or False
        
        # For SELL orders, margin trading is less common, but we'll support it
        from app.services.margin_decision_helper import decide_trading_mode, log_margin_decision, DEFAULT_CONFIGURED_LEVERAGE
        
        trading_decision = decide_trading_mode(
            symbol=symbol,
            configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
            user_wants_margin=user_wants_margin
        )
        
        log_margin_decision(symbol, trading_decision, DEFAULT_CONFIGURED_LEVERAGE)
        
        use_margin = trading_decision.use_margin
        leverage_value = trading_decision.leverage
        
        logger.info(f"💰 MARGIN SETTINGS for SELL {symbol}: user_wants_margin={user_wants_margin}, use_margin={use_margin}, leverage={leverage_value}")
        
        try:
            from app.utils.live_trading import get_live_trading_status
            live_trading = get_live_trading_status(db)
            dry_run_mode = not live_trading
            
            logger.info(f"🔴 Creating automatic SELL order for {symbol}: amount_usd={amount_usd}, margin={use_margin}")
            
            # Calculate quantity for SELL order
            qty = amount_usd / current_price
            # Round quantity based on price
            if current_price >= 100:
                qty = round(qty, 4)
            elif current_price >= 1:
                qty = round(qty, 6)
            else:
                qty = round(qty, 8)
            
            # Place MARKET SELL order
            side_upper = "SELL"
            
            # SELL market order: use quantity (not notional)
            result = trade_client.place_market_order(
                symbol=symbol,
                side=side_upper,
                qty=qty,  # For SELL, use quantity
                is_margin=use_margin,
                leverage=leverage_value if use_margin else None,
                dry_run=dry_run_mode
            )
            
            if not result or "error" in result:
                error_msg = result.get("error", "Unknown error") if result else "No response"
                logger.error(f"❌ SELL order creation failed for {symbol}: {error_msg}")
                
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>AUTOMATIC SELL ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔴 Side: SELL\n"
                        f"💰 Amount: ${amount_usd:,.2f}\n"
                        f"📦 Quantity: {qty:.8f}\n"
                        f"❌ Error: {error_msg}"
                    )
                except Exception as notify_err:
                    logger.warning(f"Failed to send Telegram error notification: {notify_err}")
                
                return None
            
            # Get order_id from result
            order_id = result.get("order_id") or result.get("client_order_id")
            if not order_id:
                logger.error(f"SELL order placed but no order_id returned for {symbol}")
                return None
            
            filled_price = None
            try:
                if result.get("avg_price"):
                    filled_price = float(result.get("avg_price"))
            except (TypeError, ValueError):
                filled_price = None
            if not filled_price:
                filled_price = current_price
            
            # Send Telegram notification
            try:
                telegram_notifier.send_order_created(
                    symbol=symbol,
                    side="SELL",
                    price=filled_price,
                    quantity=qty,
                    order_id=str(order_id),
                    margin=use_margin,
                    leverage=leverage_value if use_margin else None,
                    dry_run=dry_run_mode,
                    order_type="MARKET"
                )
                logger.info(f"Sent Telegram notification for automatic SELL order: {symbol} - {order_id}")
            except Exception as telegram_err:
                logger.warning(f"Failed to send Telegram notification for SELL order creation: {telegram_err}")
            
            # Save order to database
            try:
                from app.services.order_history_db import order_history_db
                import time
                
                result_status = result.get("status", "").upper()
                cumulative_qty = float(result.get("cumulative_quantity", 0) or 0)
                
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
                
                now_utc = datetime.now(timezone.utc)
                
                # Save to order_history_db
                order_data = {
                    "order_id": str(order_id),
                    "client_oid": str(result.get("client_order_id", order_id)),
                    "instrument_name": symbol,
                    "order_type": "MARKET",
                    "side": "SELL",
                    "status": db_status_str,
                    "quantity": str(qty),
                    "price": str(result.get("avg_price", "0")) if result.get("avg_price") else "0",
                    "avg_price": str(result.get("avg_price")) if result.get("avg_price") else None,
                    "cumulative_quantity": str(result.get("cumulative_quantity")) if result.get("cumulative_quantity") else str(qty),
                    "cumulative_value": str(result.get("cumulative_value")) if result.get("cumulative_value") else None,
                    "create_time": int(time.time() * 1000),
                    "update_time": int(time.time() * 1000),
                }
                order_history_db.upsert_order(order_data)
                
                # Save to ExchangeOrder (PostgreSQL)
                try:
                    existing_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == str(order_id)
                    ).first()
                    
                    if not existing_order:
                        new_exchange_order = ExchangeOrder(
                            exchange_order_id=str(order_id),
                            client_oid=str(result.get("client_order_id", order_id)),
                            symbol=symbol,
                            side=OrderSideEnum.SELL,
                            order_type="MARKET",
                            status=db_status,
                            price=float(result.get("avg_price")) if result.get("avg_price") else None,
                            quantity=qty,
                            cumulative_quantity=float(result.get("cumulative_quantity")) if result.get("cumulative_quantity") else qty,
                            cumulative_value=float(result.get("cumulative_value")) if result.get("cumulative_value") else None,
                            avg_price=float(result.get("avg_price")) if result.get("avg_price") else None,
                            exchange_create_time=now_utc,
                            exchange_update_time=now_utc,
                            created_at=now_utc,
                            updated_at=now_utc
                        )
                        db.add(new_exchange_order)
                        db.commit()
                        logger.info(f"✅ Automatic SELL order saved to ExchangeOrder (PostgreSQL): {symbol} - {order_id}")
                    else:
                        logger.debug(f"Order {order_id} already exists in ExchangeOrder, skipping duplicate")
                except Exception as pg_err:
                    logger.error(f"Error saving automatic SELL order to ExchangeOrder: {pg_err}", exc_info=True)
                    db.rollback()
                
                logger.info(f"Automatic SELL order saved to database: {symbol} - {order_id}")
            except Exception as e:
                logger.error(f"Error saving automatic SELL order to database: {e}", exc_info=True)
            
            logger.info(f"✅ Automatic SELL order created successfully: {symbol} - {order_id}")
            
            # If order is filled, create TP/SL orders
            if result_status in ["FILLED", "filled"] or result.get("avg_price"):
                filled_qty = float(result.get("cumulative_quantity", qty))
                try:
                    from app.services.exchange_sync import ExchangeSyncService
                    exchange_sync = ExchangeSyncService()
                    
                    # Create SL/TP orders for the filled SELL order
                    # For SELL orders: TP is BUY side (buy back at profit), SL is BUY side (buy back at loss)
                    exchange_sync._create_sl_tp_for_filled_order(
                        db=db,
                        symbol=symbol,
                        side="SELL",
                        filled_price=float(filled_price),
                        filled_qty=filled_qty,
                        order_id=str(order_id)
                    )
                    logger.info(f"✅ SL/TP orders created for SELL {symbol} order {order_id}")
                except Exception as sl_tp_err:
                    logger.warning(f"⚠️ Could not create SL/TP orders immediately for SELL {symbol}: {sl_tp_err}. Exchange sync will handle this.", exc_info=True)
            
            filled_quantity = float(result.get("cumulative_quantity", qty)) if result.get("cumulative_quantity") else qty
            
            return {
                "order_id": str(order_id),
                "filled_price": filled_price,
                "filled_quantity": filled_quantity,
                "status": result_status,
                "avg_price": result.get("avg_price")
            }
        
        except Exception as e:
            logger.error(f"Error creating automatic SELL order for {symbol}: {e}", exc_info=True)
            return None
    
    async def start(self):
        """Start the signal monitoring service loop."""
        if self.is_running:
            logger.warning("⚠️ Signal monitor is already running, skipping duplicate start")
            return
        self.is_running = True
        self._persist_status("starting")
        logger.info("[SignalMonitorService] started | interval=%ss | max_orders_per_symbol=%d | min_price_change_pct=%.2f%% | alert_cooldown_minutes=%.1fm",
            self.monitor_interval,
            self.MAX_OPEN_ORDERS_PER_SYMBOL,
            self.MIN_PRICE_CHANGE_PCT,
            self.ALERT_COOLDOWN_MINUTES,
        )

        cycle_count = 0
        logger.info("[SignalMonitorService] start() called, entering main loop")
        try:
            while self.is_running:
                logger.debug("SignalMonitorService loop iteration, is_running=%s", self.is_running)
                try:
                    cycle_count += 1
                    self.last_run_at = datetime.now(timezone.utc)
                    self._persist_status("cycle_started")
                    
                    # Initialize cycle counters
                    cycle_stats = {
                        "symbols_processed": 0,
                        "alerts_emitted": 0,
                        "buys": 0,
                        "sells": 0,
                        "throttled": 0,
                    }
                    
                    logger.info("[SignalMonitorService] cycle #%s started", cycle_count)

                    db = SessionLocal()
                    try:
                        await self.monitor_signals(db, cycle_stats)
                    finally:
                        db.close()

                    logger.info(
                        "[DEBUG_SIGNAL_MONITOR] cycle=%d | symbols_processed=%d | alerts_emitted=%d | "
                        "buys=%d | sells=%d | throttled=%d | next_check_in=%ds",
                        cycle_count,
                        cycle_stats["symbols_processed"],
                        cycle_stats["alerts_emitted"],
                        cycle_stats["buys"],
                        cycle_stats["sells"],
                        cycle_stats["throttled"],
                        self.monitor_interval,
                    )
                    self._persist_status("cycle_completed")
                except Exception as e:
                    logger.error(f"❌ Error in signal monitoring cycle #{cycle_count}: {e}", exc_info=True)
                    self._persist_status("cycle_error")
                    # Continue to next cycle even if this one failed
                
                # Sleep before next cycle, with error handling
                try:
                    await asyncio.sleep(self.monitor_interval)
                except asyncio.CancelledError:
                    logger.info("SignalMonitorService sleep cancelled, exiting loop")
                    raise
                except Exception as e:
                    logger.error(f"❌ Error during sleep in signal monitoring cycle #{cycle_count}: {e}", exc_info=True)
                    # Continue anyway - don't let sleep errors stop the monitor
                    await asyncio.sleep(1)  # Short sleep before retrying
                
                # Verify we should continue
                if not self.is_running:
                    logger.warning("SignalMonitorService is_running set to False, exiting loop after %s cycles", cycle_count)
                    break
        except asyncio.CancelledError:
            logger.info("SignalMonitorService loop cancelled after %s cycles", cycle_count)
            self._persist_status("cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Fatal error in SignalMonitorService loop after {cycle_count} cycles: {e}", exc_info=True)
            self._persist_status("fatal_error")
            raise
        finally:
            self.is_running = False
            logger.info("SignalMonitorService loop exited after %s cycles (is_running=%s)", cycle_count, self.is_running)
            self._persist_status("stopped")
    
    def stop(self):
        """Stop the signal monitoring service"""
        if not self.is_running and not (self._task and not self._task.done()):
            logger.info("Signal monitoring service already stopped")
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._persist_status("stop_requested")
        logger.info("Signal monitoring service stop requested")

    def start_background(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Schedule the monitor loop on the given asyncio loop."""
        loop = loop or asyncio.get_event_loop()
        if self._task and not self._task.done():
            logger.warning("SignalMonitorService background task already running")
            return

        async def runner():
            try:
                await self.start()
            except asyncio.CancelledError:
                logger.info("SignalMonitorService background task cancelled")
                raise
            except Exception:
                logger.exception("SignalMonitorService background task crashed")
                raise
            finally:
                self._task = None

        self._task = loop.create_task(runner())
        logger.info("SignalMonitorService background task scheduled")


# Global instance
signal_monitor_service = SignalMonitorService()

