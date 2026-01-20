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
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist_signal_state import WatchlistSignalState
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.services.alert_emitter import emit_alert
from app.core.runtime import get_runtime_origin
from app.utils.symbols import normalize_symbol_for_exchange
from app.api.routes_signals import get_signals
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import (
    resolve_strategy_profile,
    StrategyType,
    RiskApproach,
)
from app.api.routes_signals import calculate_stop_loss_and_take_profit
from app.services.config_loader import get_alert_thresholds, load_config
from app.services.order_position_service import calculate_portfolio_value_for_symbol
from app.services.signal_throttle import (
    LastSignalSnapshot,
    SignalThrottleConfig,
    build_strategy_key,
    fetch_signal_states,
    record_signal_event,
    should_emit_signal,
    compute_config_hash,
)

logger = logging.getLogger(__name__)


def _emit_lifecycle_event(
    db: Session,
    symbol: str,
    strategy_key: str,
    side: str,
    price: Optional[float],
    event_type: str,
    event_reason: str,
    order_id: Optional[str] = None,
    error_message: Optional[str] = None,
    sl_order_id: Optional[str] = None,
    tp_order_id: Optional[str] = None,
    decision_reason: Optional[Any] = None,  # DecisionReason object (optional for backward compatibility)
) -> None:
    """
    Emit a lifecycle event to both throttle (SignalThrottleState) and monitoring (TelegramMessage).
    
    This ensures all lifecycle events are consistently recorded for audit and UI display.
    
    Args:
        db: Database session
        symbol: Trading symbol
        strategy_key: Strategy key (e.g., "swing:conservative")
        side: Order side ("BUY" or "SELL")
        price: Current price
        event_type: Event type (e.g., "TRADE_BLOCKED", "ORDER_CREATED", "ORDER_FAILED", "SLTP_CREATED", "SLTP_FAILED")
        event_reason: Reason for the event (e.g., "SKIP_DISABLED_TRADE", "order_id=12345")
        order_id: Optional order ID (for order-related events)
        error_message: Optional error message (for failure events)
        sl_order_id: Optional SL order ID (for SLTP events)
        tp_order_id: Optional TP order ID (for SLTP events)
        decision_reason: Optional DecisionReason object with structured decision information
    """
    from app.utils.decision_reason import DecisionReason as DecisionReasonType
    try:
        # Record to SignalThrottleState (canonical source)
        record_signal_event(
            db=db,
            symbol=symbol,
            strategy_key=strategy_key,
            side=side,
            price=price,
            source=f"lifecycle_{event_type.lower()}",
            emit_reason=f"{event_type}: {event_reason}",
        )
        
        # Also add to monitoring/telegram message system (for UI display)
        from app.api.routes_monitoring import add_telegram_message
        
        # Extract decision reason fields if provided
        decision_type = None
        reason_code = None
        reason_message = None
        context_json = None
        exchange_error_snippet = None
        correlation_id = None
        
        if decision_reason and hasattr(decision_reason, 'to_dict'):
            reason_dict = decision_reason.to_dict()
            decision_type = reason_dict.get('decision_type')
            reason_code = reason_dict.get('reason_code')
            reason_message = reason_dict.get('reason_message')
            context_json = reason_dict.get('context')
            exchange_error_snippet = reason_dict.get('exchange_error')
            correlation_id = reason_dict.get('correlation_id')
        
        # Build message based on event type
        if event_type == "TRADE_BLOCKED":
            message = f"🚫 TRADE BLOCKED: {symbol} {side} - {event_reason}"
            if error_message:
                message += f"\nError: {error_message}"
            if reason_message:
                message += f"\nReason: {reason_message}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=True,
                throttle_status="TRADE_BLOCKED",
                throttle_reason=event_reason,
                decision_type=decision_type,
                reason_code=reason_code,
                reason_message=reason_message,
                context_json=context_json,
                exchange_error_snippet=exchange_error_snippet,
                correlation_id=correlation_id,
                db=db,
            )
        elif event_type == "ORDER_ATTEMPT":
            message = f"🔄 ORDER_ATTEMPT: {symbol} {side} - {event_reason}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                order_attempt=True,
                db=db,
            )
        elif event_type == "ORDER_CREATED":
            message = f"✅ ORDER_CREATED: {symbol} {side} - order_id={order_id}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                order_created=True,
                db=db,
            )
        elif event_type == "ORDER_FAILED":
            message = f"❌ ORDER_FAILED: {symbol} {side} - {event_reason}"
            if error_message:
                message += f"\nError: {error_message}"
            if reason_message:
                message += f"\nReason: {reason_message}"
            # For ORDER_FAILED, decision_type should be FAILED
            if not decision_type:
                decision_type = "FAILED"
            # If we have error_message but no exchange_error_snippet, use error_message
            if error_message and not exchange_error_snippet:
                exchange_error_snippet = error_message
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=True,  # Mark as blocked since order failed
                order_skipped=False,  # Order was attempted, not skipped
                throttle_status="ORDER_FAILED",
                throttle_reason=event_reason,
                decision_type=decision_type,
                reason_code=reason_code,
                reason_message=reason_message,
                context_json=context_json,
                exchange_error_snippet=exchange_error_snippet,
                correlation_id=correlation_id,
                db=db,
            )
        elif event_type == "SLTP_ATTEMPT":
            message = f"🔄 SLTP_ATTEMPT: {symbol} {side} - {event_reason}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                sltp_attempt=True,
                db=db,
            )
        elif event_type == "SLTP_CREATED":
            message = f"✅ SLTP_CREATED: {symbol} {side} - SL={sl_order_id or 'N/A'}, TP={tp_order_id or 'N/A'}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                sltp_created=True,
                db=db,
            )
        elif event_type == "SLTP_FAILED":
            message = f"🚨 SLTP_FAILED: {symbol} {side} - {event_reason}"
            if error_message:
                message += f"\nError: {error_message}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                sltp_failed=True,
                error_message=error_message or event_reason,
                db=db,
            )
        elif event_type == "SLTP_BLOCKED":
            message = f"🚫 SLTP_BLOCKED: {symbol} {side} - {event_reason}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=True,
                throttle_status="SLTP_BLOCKED",
                throttle_reason=event_reason,
                db=db,
            )
        elif event_type == "ORDER_EXECUTED":
            message = f"✅ ORDER_EXECUTED: {symbol} {side} - {event_reason}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                order_executed=True,
                db=db,
            )
        elif event_type == "ORDER_CANCELED":
            message = f"❌ ORDER_CANCELED: {symbol} {side} - {event_reason}"
            add_telegram_message(
                message=message,
                symbol=symbol,
                blocked=False,
                order_canceled=True,
                db=db,
            )
    except Exception as e:
        logger.warning(f"Failed to emit lifecycle event {event_type} for {symbol}: {e}", exc_info=True)


# Force diagnostic flags (env-gated, default OFF)
FORCE_SELL_DIAGNOSTIC = os.getenv("FORCE_SELL_DIAGNOSTIC", "0").lower() in ("1", "true", "yes")
FORCE_SELL_DIAGNOSTIC_SYMBOL = os.getenv("FORCE_SELL_DIAGNOSTIC_SYMBOL", "").upper()

# Single symbol diagnostic mode (for throttle reset investigation)
DIAG_SYMBOL = os.getenv("DIAG_SYMBOL", "").upper()
DIAG_FORCE_SIGNAL_BUY = os.getenv("DIAG_FORCE_SIGNAL_BUY", "").strip() == "1"

# Price move alert configuration
PRICE_MOVE_ALERT_PCT = float(os.getenv("PRICE_MOVE_ALERT_PCT", "0.50"))  # Default 0.50%
PRICE_MOVE_ALERT_COOLDOWN_SECONDS = float(os.getenv("PRICE_MOVE_ALERT_COOLDOWN_SECONDS", "300"))  # Default 5 minutes

# SL/TP creation configuration
# Failsafe behavior when SL/TP creation fails: if True, send CRITICAL alerts (default: True for safety)
FAILSAFE_ON_SLTP_ERROR = os.getenv("FAILSAFE_ON_SLTP_ERROR", "true").lower() in ("1", "true", "yes")
# Order fill confirmation polling configuration
ORDER_FILL_POLL_MAX_ATTEMPTS = int(os.getenv("ORDER_FILL_POLL_MAX_ATTEMPTS", "10"))  # Max attempts to poll for fill
ORDER_FILL_POLL_INTERVAL_SECONDS = float(os.getenv("ORDER_FILL_POLL_INTERVAL_SECONDS", "1.0"))  # Seconds between polls

# Debug logging flag for trading flow
DEBUG_TRADING = os.getenv("DEBUG_TRADING", "0") == "1"  # Enable detailed trading flow logging

if FORCE_SELL_DIAGNOSTIC or FORCE_SELL_DIAGNOSTIC_SYMBOL:
    target_symbol = FORCE_SELL_DIAGNOSTIC_SYMBOL or "TRX_USDT"
    logger.info(
        f"🔧 [DIAGNOSTIC] Force sell diagnostics enabled for SYMBOL={target_symbol} | "
        f"FORCE_SELL_DIAGNOSTIC={FORCE_SELL_DIAGNOSTIC} | "
        f"FORCE_SELL_DIAGNOSTIC_SYMBOL={FORCE_SELL_DIAGNOSTIC_SYMBOL or 'TRX_USDT'} | "
        f"DRY_RUN=True (no orders will be placed)"
    )

if DIAG_SYMBOL:
    logger.info(
        f"🔧 [DIAG_MODE] Single symbol diagnostic mode enabled for SYMBOL={DIAG_SYMBOL} | "
        f"Only this symbol will be evaluated with detailed decision trace"
    )

# Decision reason codes (canonical constants)
SKIP_DISABLED_ALERT = "SKIP_DISABLED_ALERT"
SKIP_DISABLED_TRADE = "SKIP_DISABLED_TRADE"
SKIP_COOLDOWN_ACTIVE = "SKIP_COOLDOWN_ACTIVE"
SKIP_NO_SIGNAL = "SKIP_NO_SIGNAL"
SKIP_NO_PRICE = "SKIP_NO_PRICE"
SKIP_NO_STRATEGY = "SKIP_NO_STRATEGY"
SKIP_DB_MISMATCH = "SKIP_DB_MISMATCH"
EXEC_ALERT_SENT = "EXEC_ALERT_SENT"
EXEC_ORDER_PLACED = "EXEC_ORDER_PLACED"
EXEC_ORDER_BLOCKED_BY_THROTTLE = "EXEC_ORDER_BLOCKED_BY_THROTTLE"


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
        self.ALERT_COOLDOWN_MINUTES = 0.1667  # 10 seconds cooldown between same-side alerts
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

    def _schedule_missing_intent_check(self, signal_id: Optional[int], symbol: str, side: str) -> None:
        """Schedule a delayed check to ensure a sent signal has an order_intent."""
        if not signal_id:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning(
                f"[INVARIANT] No running loop for missing intent check (signal_id={signal_id}, symbol={symbol}, side={side})"
            )
            return
        loop.create_task(self._check_missing_order_intent_after_delay(signal_id, symbol, side))

    async def _check_missing_order_intent_after_delay(self, signal_id: int, symbol: str, side: str) -> None:
        """Record a FAILED decision if no order_intent appears within the grace window."""
        from app.database import SessionLocal
        from app.models.order_intent import OrderIntent
        from app.api.routes_monitoring import update_telegram_message_decision_trace
        from app.utils.decision_reason import ReasonCode
        import uuid as uuid_module

        grace_seconds = int(os.getenv("MISSING_ORDER_INTENT_GRACE_SECONDS", "60"))
        await asyncio.sleep(grace_seconds)

        if SessionLocal is None:
            return
        db = SessionLocal()
        try:
            intent = db.query(OrderIntent).filter(OrderIntent.signal_id == signal_id).first()
            if intent:
                return
            update_telegram_message_decision_trace(
                db=db,
                symbol=symbol,
                message_pattern=f"{side} SIGNAL",
                decision_type="FAILED",
                reason_code=ReasonCode.MISSING_ORDER_INTENT.value,
                reason_message=(
                    f"Signal was sent but no order_intent was created within {grace_seconds}s."
                ),
                context_json={"signal_id": signal_id, "symbol": symbol, "side": side},
                correlation_id=str(uuid_module.uuid4()),
            )
            logger.warning(
                f"[INVARIANT] Missing order_intent recorded for signal_id={signal_id} symbol={symbol} side={side}"
            )
        except Exception as e:
            logger.warning(
                f"[INVARIANT] Failed missing order_intent check for signal_id={signal_id}: {e}"
            )
        finally:
            try:
                db.close()
            except Exception:
                pass

    def clear_order_creation_limitations(self, symbol: str) -> None:
        """Clear order creation limitations for a symbol (e.g., when strategy changes).
        
        This clears:
        - last_signal_states (last_order_price, orders_count tracking)
        - order_creation_locks (prevents duplicate orders)
        - last_alert_states (alert throttling)
        - alert_sending_locks (alert sending locks)
        
        This allows immediate order creation and alerts when strategy changes.
        """
        # Clear order creation state
        if symbol in self.last_signal_states:
            del self.last_signal_states[symbol]
            logger.info(f"🔄 [STRATEGY] Cleared last_signal_states for {symbol}")
        
        # Clear order creation locks
        if symbol in self.order_creation_locks:
            del self.order_creation_locks[symbol]
            logger.info(f"🔄 [STRATEGY] Cleared order_creation_locks for {symbol}")
        
        # NOTE: last_alert_states is deprecated - throttling now uses only signal_throttle_states (BD)
        # Clearing it here for backward compatibility, but it's no longer used for throttling decisions
        
        # Clear alert sending locks for both BUY and SELL
        for side in ["BUY", "SELL"]:
            lock_key = f"{symbol}_{side}"
            if lock_key in self.alert_sending_locks:
                del self.alert_sending_locks[lock_key]
        logger.info(f"🔄 [STRATEGY] Cleared alert_sending_locks for {symbol} BUY/SELL")
    
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

    def _log_pipeline_stage(
        self,
        stage: str,
        symbol: str,
        strategy_key: str,
        decision: str,
        last_price: Optional[float],
        timestamp: str,
        correlation_id: str,
        signal_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Structured stage log for signal→alert→order pipeline."""
        logger.info(
            "[%s] symbol=%s strategy_key=%s decision=%s last_price=%s timestamp=%s signal_id=%s correlation_id=%s reason=%s",
            stage,
            normalize_symbol_for_exchange(symbol),
            strategy_key,
            decision,
            f"{last_price:.4f}" if last_price is not None else "N/A",
            timestamp,
            signal_id or "N/A",
            correlation_id,
            reason or "N/A",
        )

    _UNSET = object()

    def _map_alert_block_reason(self, reason: Optional[str]) -> str:
        if not reason:
            return "UNKNOWN"
        reason_upper = reason.upper()
        if "THROTTLED_TIME_GATE" in reason_upper or "THROTTLE_TIME_GATE" in reason_upper:
            return "THROTTLED_TIME_GATE"
        if "THROTTLED_PRICE_GATE" in reason_upper or "THROTTLE_PRICE_GATE" in reason_upper:
            return "THROTTLED_PRICE_GATE"
        if "ALERT_ENABLED" in reason_upper or "ALERT_DISABLED" in reason_upper:
            return "ALERT_DISABLED"
        if "BUY_ALERT_ENABLED" in reason_upper or "SELL_ALERT_ENABLED" in reason_upper or "SIDE_DISABLED" in reason_upper:
            return "SIDE_DISABLED"
        if "TELEGRAM_DISABLED" in reason_upper:
            return "TELEGRAM_DISABLED"
        if "TELEGRAM" in reason_upper and "ERROR" in reason_upper:
            return "TELEGRAM_ERROR"
        return "UNKNOWN"

    def _map_trade_block_reason(self, reason: Optional[str]) -> str:
        if not reason:
            return "UNKNOWN"
        reason_upper = reason.upper()
        if "KILL_SWITCH" in reason_upper:
            return "KILL_SWITCH"
        if "PORTFOLIO" in reason_upper:
            return "PORTFOLIO_LIMIT"
        if "OPEN_ORDER" in reason_upper or "OPEN_ORDERS" in reason_upper:
            return "OPEN_ORDERS_LIMIT"
        if "COOLDOWN" in reason_upper or "THROTTLED" in reason_upper:
            return "COOLDOWN"
        if "EXCHANGE" in reason_upper:
            return "EXCHANGE_ERROR"
        if "LIVE_TRADING" in reason_upper or "TRADE_DISABLED" in reason_upper or "TRADE_ENABLED" in reason_upper:
            return "TRADE_DISABLED"
        return "UNKNOWN"

    def _upsert_watchlist_signal_state(
        self,
        db: Session,
        *,
        symbol: str,
        strategy_key: Optional[str] = _UNSET,
        signal_side: Optional[str] = _UNSET,
        last_price: Optional[float] = _UNSET,
        evaluated_at_utc: Optional[datetime] = _UNSET,
        alert_status: Optional[str] = _UNSET,
        alert_block_reason: Optional[str] = _UNSET,
        trade_status: Optional[str] = _UNSET,
        trade_block_reason: Optional[str] = _UNSET,
        last_alert_at_utc: Optional[datetime] = _UNSET,
        last_trade_at_utc: Optional[datetime] = _UNSET,
        correlation_id: Optional[str] = _UNSET,
    ) -> None:
        try:
            symbol_norm = normalize_symbol_for_exchange(symbol)
            state = (
                db.query(WatchlistSignalState)
                .filter(WatchlistSignalState.symbol == symbol_norm)
                .one_or_none()
            )
            if state is None:
                state = WatchlistSignalState(symbol=symbol_norm)
                db.add(state)
            if strategy_key is not self._UNSET:
                state.strategy_key = strategy_key
            if signal_side is not self._UNSET:
                normalized_side = (signal_side or "NONE").upper()
                if normalized_side == "WAIT":
                    normalized_side = "NONE"
                state.signal_side = normalized_side
            if last_price is not self._UNSET:
                state.last_price = last_price
            if evaluated_at_utc is not self._UNSET:
                state.evaluated_at_utc = evaluated_at_utc
            if alert_status is not self._UNSET:
                state.alert_status = (alert_status or "NONE").upper()
            if alert_block_reason is not self._UNSET:
                state.alert_block_reason = alert_block_reason
            if trade_status is not self._UNSET:
                state.trade_status = (trade_status or "NONE").upper()
            if trade_block_reason is not self._UNSET:
                state.trade_block_reason = trade_block_reason
            if last_alert_at_utc is not self._UNSET:
                state.last_alert_at_utc = last_alert_at_utc
            if last_trade_at_utc is not self._UNSET:
                state.last_trade_at_utc = last_trade_at_utc
            if correlation_id is not self._UNSET:
                state.correlation_id = correlation_id
            db.flush()
            logger.info(
                "[SIGNAL_STATE] symbol=%s side=%s alert_status=%s trade_status=%s correlation_id=%s",
                symbol_norm,
                state.signal_side,
                state.alert_status,
                state.trade_status,
                state.correlation_id,
            )
        except Exception as err:
            logger.warning(f"Failed to upsert watchlist_signal_state for {symbol}: {err}")

    def _print_trade_decision_trace(
        self,
        symbol: str,
        strategy_key: str,
        side: str,
        current_price: float,
        signal_exists: bool,
        trade_enabled: bool,
        trade_amount_usd: Optional[float],
        should_create_order: bool,
        guard_reason: Optional[str],
        evaluation_id: str
    ) -> None:
        """Print TRADE decision trace for diagnostic mode"""
        if not DIAG_SYMBOL or symbol.upper() != DIAG_SYMBOL:
            return
        
        # Determine decision and reason code
        decision = "SKIP"
        reason_code = SKIP_NO_SIGNAL
        
        if not signal_exists:
            reason_code = SKIP_NO_SIGNAL
        elif not trade_enabled:
            reason_code = SKIP_DISABLED_TRADE
        elif not trade_amount_usd or trade_amount_usd <= 0:
            reason_code = SKIP_DISABLED_TRADE  # Invalid trade amount
        elif guard_reason:
            # Guard blocked execution
            decision = "SKIP"
            reason_code = EXEC_ORDER_BLOCKED_BY_THROTTLE
        elif should_create_order:
            decision = "EXEC"
            reason_code = EXEC_ORDER_PLACED
        else:
            decision = "SKIP"
            reason_code = EXEC_ORDER_BLOCKED_BY_THROTTLE
        
        # In diagnostic mode, print to stdout for snippet extraction
        # Format as single-line summary for easy parsing
        # blocked_by should match reason when decision is SKIP
        blocked_by_value = guard_reason if guard_reason else (reason_code if decision == "SKIP" else "none")
        trade_amount_str = f"${trade_amount_usd:.2f}" if trade_amount_usd else "None"
        
        print(f"TRADE decision={decision} reason={reason_code} blocked_by={blocked_by_value} "
              f"trade_enabled={trade_enabled} signal_exists={signal_exists} "
              f"should_create_order={should_create_order} symbol={symbol} side={side} "
              f"current_price=${current_price:.4f} trade_amount_usd={trade_amount_str}")
        
        # Also log normally for production logs
        logger.info(f"🔍 [TRADE_DECISION_TRACE] {symbol} {side} (eval_id={evaluation_id})")
        logger.info(f"  symbol: {symbol}")
        logger.info(f"  strategy: {strategy_key}")
        logger.info(f"  side: {side}")
        logger.info(f"  current_price: ${current_price:.4f}")
        logger.info(f"  signal_exists: {signal_exists}")
        logger.info(f"  trade_enabled: {trade_enabled}")
        logger.info(f"  trade_amount_usd: ${trade_amount_usd:.2f}" if trade_amount_usd else "  trade_amount_usd: None")
        logger.info(f"  should_create_order: {should_create_order}")
        logger.info(f"  guard_reason: {guard_reason or 'none'}")
        logger.info(f"  final_decision: {decision}")
        logger.info(f"  reason_code: {reason_code}")
        if guard_reason:
            logger.info(f"  blocked_by: {guard_reason}")

    def _print_decision_trace(
        self,
        symbol: str,
        strategy_key: str,
        side: str,
        current_price: float,
        signal_exists: bool,
        alert_enabled: bool,
        trade_enabled: bool,
        snapshot: Optional[LastSignalSnapshot],
        throttle_config: SignalThrottleConfig,
        now_utc: datetime,
        evaluation_id: str
    ) -> None:
        """Print detailed decision trace for diagnostic mode"""
        if not DIAG_SYMBOL or symbol.upper() != DIAG_SYMBOL:
            return
        
        # Build throttle key
        throttle_key = f"{symbol}:{strategy_key}:{side}"
        
        # Get reference price and timestamp
        reference_price = snapshot.price if snapshot and snapshot.price else None
        last_sent = snapshot.timestamp if snapshot and snapshot.timestamp else None
        
        # Calculate price change
        price_change_pct = None
        if reference_price and reference_price > 0:
            price_change_pct = abs((current_price - reference_price) / reference_price * 100)
        
        # Calculate time diff
        elapsed_seconds = None
        if last_sent:
            if last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            elapsed_seconds = (now_utc - last_sent).total_seconds()
        
        # Determine decision and reason code
        decision = "SKIP"
        reason_code = SKIP_NO_SIGNAL
        
        if not signal_exists:
            reason_code = SKIP_NO_SIGNAL
        elif not alert_enabled:
            reason_code = SKIP_DISABLED_ALERT
        elif not trade_enabled and side == "BUY":
            # For BUY, if trade is disabled, we still send alert if alert_enabled
            # So this is not a skip reason for alerts
            pass
        elif snapshot and snapshot.force_next_signal:
            decision = "EXEC"
            reason_code = EXEC_ALERT_SENT  # Will be sent
        elif snapshot and snapshot.timestamp:
            # Check throttle
            if elapsed_seconds and elapsed_seconds < 60.0:
                reason_code = SKIP_COOLDOWN_ACTIVE
            elif price_change_pct and price_change_pct < throttle_config.min_price_change_pct:
                reason_code = SKIP_COOLDOWN_ACTIVE  # Price gate not met
            else:
                decision = "EXEC"
                reason_code = EXEC_ALERT_SENT
        else:
            # No previous signal - should allow
            decision = "EXEC"
            reason_code = EXEC_ALERT_SENT
        
        # Format timestamps
        last_sent_str = last_sent.isoformat() if last_sent else "None"
        now_str = now_utc.isoformat()
        diff_str = f"{elapsed_seconds:.1f}s" if elapsed_seconds is not None else "N/A"
        cooldown_threshold = "60.0s"
        
        # In diagnostic mode, print to stdout for snippet extraction
        # Format as single-line summary for easy parsing
        if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
            reference_price_str = f"${reference_price:.4f}" if reference_price else "None"
            price_change_str = f"{price_change_pct:.2f}%" if price_change_pct else "N/A"
            force_next_str = str(snapshot.force_next_signal) if snapshot else "False"
            print(f"ALERT decision={decision} reason={reason_code} symbol={symbol} side={side} "
                  f"current_price=${current_price:.4f} reference_price={reference_price_str} "
                  f"price_change_pct={price_change_str} alert_enabled={alert_enabled} "
                  f"trade_enabled={trade_enabled} throttle_key={throttle_key} "
                  f"last_sent={last_sent_str} now={now_str} elapsed={diff_str} "
                  f"cooldown_threshold={cooldown_threshold} price_threshold={throttle_config.min_price_change_pct}% "
                  f"force_next_signal={force_next_str} eval_id={evaluation_id}")
        
        # Also log normally for production logs
        logger.info("=" * 80)
        logger.info(f"🔍 [DECISION_TRACE] {symbol} {side} (eval_id={evaluation_id})")
        logger.info(f"  symbol: {symbol}")
        logger.info(f"  strategy: {strategy_key}")
        logger.info(f"  side: {side}")
        logger.info(f"  current_price: ${current_price:.4f}")
        logger.info(f"  reference_price: ${reference_price:.4f}" if reference_price else "  reference_price: None")
        logger.info(f"  price_change%: {price_change_pct:.2f}%" if price_change_pct else "  price_change%: N/A")
        logger.info(f"  alert_enabled: {alert_enabled}")
        logger.info(f"  trade_enabled: {trade_enabled}")
        logger.info(f"  throttle_key: {throttle_key}")
        logger.info(f"  throttle_key_alert: {throttle_key} (shared with trade)")
        logger.info(f"  throttle_key_trade: {throttle_key} (shared with alert)")
        logger.info(f"  cooldown_checked_for_alert: True (shared throttle)")
        logger.info(f"  cooldown_checked_for_trade: True (shared throttle)")
        logger.info(f"  last_sent: {last_sent_str}")
        logger.info(f"  now: {now_str}")
        logger.info(f"  elapsed: {diff_str}")
        logger.info(f"  cooldown_threshold: {cooldown_threshold}")
        logger.info(f"  price_threshold: {throttle_config.min_price_change_pct}%")
        logger.info(f"  force_next_signal: {snapshot.force_next_signal if snapshot else False}")
        logger.info(f"  final_decision: {decision}")
        logger.info(f"  reason_code: {reason_code}")
        logger.info("=" * 80)

    @staticmethod
    def _compute_config_hash(watchlist_item: WatchlistItem) -> str:
        """Build config hash from whitelisted fields for throttle resets."""
        config_snapshot = {
            "alert_enabled": getattr(watchlist_item, "alert_enabled", False),
            "buy_alert_enabled": getattr(watchlist_item, "buy_alert_enabled", False),
            "sell_alert_enabled": getattr(watchlist_item, "sell_alert_enabled", False),
            "trade_enabled": getattr(watchlist_item, "trade_enabled", False),
            "strategy_id": getattr(watchlist_item, "strategy_id", None),
            "strategy_name": getattr(watchlist_item, "sl_tp_mode", None),
            "min_price_change_pct": getattr(watchlist_item, "min_price_change_pct", None),
            "trade_amount_usd": getattr(watchlist_item, "trade_amount_usd", None),
        }
        return compute_config_hash(config_snapshot)

    @staticmethod
    def _classify_throttle_reason(reason: Optional[str]) -> str:
        """Classify throttle reason to canonical codes (ALERTAS_Y_ORDENES_NORMAS.md)"""
        if not reason:
            return "THROTTLED"
        normalized = reason.lower()
        # Canonical codes: THROTTLED_TIME_GATE, THROTTLED_PRICE_GATE
        if "throttled_time_gate" in normalized or "cooldown" in normalized or "minutes" in normalized or "throttled_min_time" in normalized:
            return "THROTTLED_TIME_GATE"
        if "throttled_price_gate" in normalized or "price change" in normalized or "%" in normalized or "throttled_min_change" in normalized:
            return "THROTTLED_PRICE_GATE"
        if "immediate_alert_after_config_change" in normalized or "forced" in normalized:
            return "IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE"
        return "THROTTLED"

    @staticmethod
    def _map_throttle_reason_code(reason: Optional[str]) -> str:
        """Map throttle reason into DecisionReason codes for blocked alerts."""
        from app.utils.decision_reason import ReasonCode
        if not reason:
            return ReasonCode.THROTTLED_DUPLICATE_ALERT.value
        normalized = reason.lower()
        if "cooldown" in normalized or "time" in normalized or "throttled_time_gate" in normalized:
            return ReasonCode.COOLDOWN_ACTIVE.value
        if "price" in normalized or "throttled_price_gate" in normalized:
            return ReasonCode.THROTTLED_DUPLICATE_ALERT.value
        return ReasonCode.THROTTLED_DUPLICATE_ALERT.value
    
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

    def _resolve_alert_thresholds(
        self, watchlist_item: WatchlistItem
    ) -> Tuple[Optional[float], Optional[float], Dict[str, Optional[float]]]:
        """
        Determine which alert thresholds apply to this coin.
        Priority order:
            1. Explicit per-coin override (min_price_change_pct column in database)
            2. Strategy/preset defaults from trading_config.json
            3. Global defaults from trading_config.json
            4. Service-wide defaults (self.ALERT_* constants)
        
        NOTE: alert_cooldown_minutes is DEPRECATED - throttling is now fixed at 60 seconds.
        This function still returns cooldown for backward compatibility but it's not used.
        """
        # Get values from database first (highest priority)
        item_min_pct = getattr(watchlist_item, "min_price_change_pct", None)
        # DEPRECATED: alert_cooldown_minutes is no longer used (throttling is fixed at 60s)
        cooldown = None  # Not used anymore - kept for backward compatibility
        preset_min = None
        default_min = None
        min_pct = item_min_pct
        risk_mode = getattr(watchlist_item, "sl_tp_mode", None)
        
        try:
            cfg = load_config()
            default_min = cfg.get("defaults", {}).get("alert_min_price_change_pct")
        except Exception as e:
            logger.warning(
                f"Failed to load global defaults for {getattr(watchlist_item, 'symbol', '?')}: {e}"
            )
        
        # Always load preset thresholds for logging, but do not override DB value
        try:
            symbol = (watchlist_item.symbol or "").upper()
            preset_min, preset_cooldown = get_alert_thresholds(symbol, risk_mode)
            if cooldown is None:
                cooldown = preset_cooldown
            if min_pct is None:
                min_pct = preset_min
        except Exception as e:
            logger.warning(f"Failed to load alert thresholds for {getattr(watchlist_item, 'symbol', '?')}: {e}")
        
        # Fallback to service-wide defaults
        if min_pct is None:
            min_pct = default_min if default_min is not None else self.ALERT_MIN_PRICE_CHANGE_PCT
        # Cooldown is deprecated (fixed throttling) but returned for backward compatibility
        
        return min_pct, cooldown, {
            "item_min_pct": item_min_pct,
            "preset_min_pct": preset_min,
            "default_min_pct": default_min,
        }
    
    def should_send_alert(
        self,
        symbol: str,
        side: str,
        current_price: float,
        trade_enabled: bool = True,
        min_price_change_pct: Optional[float] = None,
        cooldown_minutes: Optional[float] = None,
        skip_lock_check: bool = False,
    ) -> tuple[bool, str]:
        """
        DEPRECATED: This function is no longer used for throttling decisions.
        
        Throttling is now handled entirely by should_emit_signal() which uses signal_throttle_states
        in the database as the single source of truth. This eliminates the dual throttling system
        that caused inconsistencies.
        
        This function is kept for backward compatibility but should not be called.
        If called, it will return (True, "DEPRECATED") to allow alerts to proceed.
        
        Args:
            symbol: Trading symbol (e.g., "BTC_USDT")
            side: Alert side ("BUY" or "SELL")
            current_price: Current price for the symbol
            trade_enabled: Whether trading is enabled for this symbol
            min_price_change_pct: Minimum price change % required
            cooldown_minutes: Cooldown in minutes
            skip_lock_check: Whether to skip lock check
            
        Returns:
            tuple[bool, str]: (True, "DEPRECATED - throttling handled by should_emit_signal")
        """
        logger.warning(
            f"should_send_alert() is deprecated and should not be called. "
            f"Throttling is now handled by should_emit_signal() using signal_throttle_states (BD). "
            f"Returning True for {symbol} {side} to allow alert to proceed."
        )
        return True, "DEPRECATED - throttling handled by should_emit_signal"
        import time
        
        # Get last alert state for this symbol and side (needed for detailed messages)
        symbol_alerts = self.last_alert_states.get(symbol, {})
        last_alert = symbol_alerts.get(side)
        last_alert_time = last_alert.get("last_alert_time") if last_alert else None
        last_alert_price = last_alert.get("last_alert_price", 0.0) if last_alert else 0.0
        
        # Calculate time and price change info for detailed messages
        time_info = ""
        price_info = ""
        if last_alert_time and last_alert_price > 0:
            try:
                # Normalize timezone
                if last_alert_time.tzinfo is None:
                    last_alert_time_normalized = last_alert_time.replace(tzinfo=timezone.utc)
                elif last_alert_time.tzinfo != timezone.utc:
                    last_alert_time_normalized = last_alert_time.astimezone(timezone.utc)
                else:
                    last_alert_time_normalized = last_alert_time
                
                now_utc = datetime.now(timezone.utc)
                time_diff_minutes = (now_utc - last_alert_time_normalized).total_seconds() / 60.0
                time_info = f", time since last alert: {time_diff_minutes:.2f} min"
                
                if current_price > 0:
                    price_change_pct = abs((current_price - last_alert_price) / last_alert_price * 100)
                    direction = "↑" if current_price > last_alert_price else "↓"
                    price_info = f", price change: {direction} {price_change_pct:.2f}% (abs) (${last_alert_price:.4f} → ${current_price:.4f})"
            except Exception:
                pass  # If calculation fails, just omit the info
        
        # CRITICAL: Check if another thread is already processing this alert
        # This prevents race conditions when multiple cycles run simultaneously
        # Skip lock check if we've already acquired the lock (skip_lock_check=True)
        lock_key = f"{symbol}_{side}"  # Define lock_key for use in later code
        if not skip_lock_check:
            current_time_check = time.time()
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                lock_age = current_time_check - lock_timestamp
                if lock_age < self.ALERT_SENDING_LOCK_SECONDS:
                    remaining_seconds = self.ALERT_SENDING_LOCK_SECONDS - lock_age
                    return False, (
                        f"Another thread is already processing {symbol} {side} alert "
                        f"(lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s{time_info}{price_info})"
                    )
                else:
                    # Lock expired, remove it
                    logger.debug(f"🔓 Expired lock removed for {symbol} {side} alert (age: {lock_age:.2f}s)")
                    del self.alert_sending_locks[lock_key]
        
        # If no previous alert for this symbol+side, check lock first to prevent duplicates
        if not last_alert:
            # Double-check lock to ensure we're the first to process this
            if not skip_lock_check:
                current_time_check = time.time()
                if lock_key in self.alert_sending_locks:
                    lock_timestamp = self.alert_sending_locks[lock_key]
                    lock_age = current_time_check - lock_timestamp
                    if lock_age < self.ALERT_SENDING_LOCK_SECONDS:
                        remaining_seconds = self.ALERT_SENDING_LOCK_SECONDS - lock_age
                        return False, (
                            f"Another thread is already processing first {symbol} {side} alert "
                            f"(lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s{time_info}{price_info})"
                        )
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
        
        # CRITICAL: Both conditions must be met (AND logic, not OR)
        # Alert should only be sent if BOTH cooldown AND price change thresholds are satisfied
        if not cooldown_met:
            minutes_remaining = max(0.0, cooldown_limit - time_diff)
            return False, (
                f"Throttled: cooldown {time_diff:.1f} min < {cooldown_limit} min "
                f"(remaining {minutes_remaining:.1f} min). "
                f"Requires BOTH cooldown >= {cooldown_limit} min AND price change >= {alert_min_price_change:.2f}%"
            )
        
        if not price_change_met:
            direction = "↑" if current_price > last_alert_price else "↓"
            return False, (
                f"Throttled: price change {direction} {price_change_pct:.2f}% (abs) < {alert_min_price_change:.2f}%. "
                f"(last price: ${last_alert_price:.4f}, current: ${current_price:.4f}). "
                f"Requires BOTH cooldown >= {cooldown_limit} min AND absolute price change >= {alert_min_price_change:.2f}%"
            )

        # Both conditions met - allow alert
        direction = "↑" if current_price > last_alert_price else "↓"
        reason_text = (
            f"cooldown met ({time_diff:.1f} min >= {cooldown_limit} min) AND "
            f"absolute price change met ({direction} {price_change_pct:.2f}% >= {alert_min_price_change:.2f}%)"
        )

        return True, reason_text
    
    def _update_alert_state(self, symbol: str, side: str, price: float):
        """Update the last alert state for a symbol and side"""
        if symbol not in self.last_alert_states:
            self.last_alert_states[symbol] = {}
        
        self.last_alert_states[symbol][side] = {
            "last_alert_time": datetime.now(timezone.utc),
            "last_alert_price": price
        }
    
    def _get_last_alert_price(self, symbol: str, side: str, db: Optional[Session] = None) -> Optional[float]:
        """
        Get the last alert price for a symbol and side from database.
        
        Looks up the most recent alert in signal_throttle_states without filtering by strategy_key.
        This ensures that when strategy changes, we can still find previous alerts for the same 
        symbol/side to show price change instead of "Primera alerta".
        
        NOTE: This now uses only the database as the source of truth, eliminating the dual
        throttling system that caused inconsistencies.
        """
        if db is not None:
            try:
                from app.models.signal_throttle import SignalThrottleState
                
                # Find the most recent alert for this symbol/side (any strategy)
                last_record = (
                    db.query(SignalThrottleState)
                    .filter(
                        SignalThrottleState.symbol == symbol.upper(),
                        SignalThrottleState.side == side.upper(),
                        SignalThrottleState.last_price.isnot(None),
                        SignalThrottleState.last_price > 0,
                    )
                    .order_by(SignalThrottleState.last_time.desc())
                    .first()
                )
                
                if last_record and last_record.last_price:
                    return last_record.last_price
            except Exception as e:
                logger.debug(f"Failed to fetch last alert price from DB for {symbol} {side}: {e}")
        
        return None

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
        
        # Get all watchlist items with alert_enabled = true (for alerts)
        # Note: This includes coins that may have trade_enabled = false
        # IMPORTANT: Use SQL directly to check which columns exist to avoid SQLAlchemy errors
        try:
            from sqlalchemy import text, inspect
            
            # Check which columns exist by querying the database schema
            inspector = inspect(db.bind) if hasattr(db, 'bind') and db.bind else None
            available_columns = []
            if inspector:
                try:
                    columns = inspector.get_columns('watchlist_items')
                    available_columns = [col['name'] for col in columns]
                    logger.debug(f"Available columns in watchlist_items: {available_columns}")
                except Exception as e:
                    logger.warning(f"Could not inspect table columns: {e}")
            
            has_alert_enabled = 'alert_enabled' in available_columns
            has_trade_enabled = 'trade_enabled' in available_columns
            has_is_deleted = 'is_deleted' in available_columns
            
            # Try querying with SQL directly to avoid SQLAlchemy column issues
            # Build WHERE clause based on available columns
            where_parts = []
            if has_alert_enabled:
                where_parts.append("alert_enabled = true")
            elif has_trade_enabled:
                logger.warning("⚠️ alert_enabled column not found, using trade_enabled as fallback")
                where_parts.append("trade_enabled = true")
            else:
                logger.error("❌ Neither alert_enabled nor trade_enabled columns found!")
                return []
            
            if has_is_deleted:
                where_parts.append("is_deleted = false")
            
            where_clause = " AND ".join(where_parts)
            sql = f"SELECT * FROM watchlist_items WHERE {where_clause}"
            
            # Execute raw SQL and map to WatchlistItem objects
            result = db.execute(text(sql))
            rows = result.fetchall()
            
            # Get column names from the result
            if not rows:
                logger.warning("⚠️ No watchlist items found matching criteria!")
                return []
            
            # Get column names from first row  
            column_names = list(rows[0]._mapping.keys()) if hasattr(rows[0], '_mapping') else list(rows[0].keys())
            
            watchlist_items = []
            for row in rows:
                # Create WatchlistItem and set attributes from row
                item = WatchlistItem()
                row_dict = dict(row._mapping) if hasattr(row, '_mapping') else dict(zip(column_names, row))
                
                for key, value in row_dict.items():
                    if hasattr(WatchlistItem, key):
                        try:
                            setattr(item, key, value)
                        except Exception as e:
                            logger.debug(f"Could not set {key}={value} on WatchlistItem: {e}")
                
                # If alert_enabled column doesn't exist, infer it from trade_enabled (legacy databases)
                # This allows the system to work with older database schemas
                if not has_alert_enabled and has_trade_enabled:
                    item.alert_enabled = bool(getattr(item, 'trade_enabled', False))
                    logger.debug(f"Inferred alert_enabled={item.alert_enabled} from trade_enabled for {getattr(item, 'symbol', 'unknown')}")
                # If alert_enabled column exists, ensure it's a boolean
                elif has_alert_enabled:
                    item.alert_enabled = bool(getattr(item, 'alert_enabled', False))
                
                watchlist_items.append(item)
            
            if not watchlist_items:
                logger.warning("⚠️ No watchlist items with alert_enabled = true (or trade_enabled = true as fallback) found in database!")
                return []
            
            logger.info(f"📊 Monitoring {len(watchlist_items)} coins with {'alert_enabled' if has_alert_enabled else 'trade_enabled'} = true:")
            for item in watchlist_items:
                # Log item details
                symbol = getattr(item, 'symbol', 'unknown')
                alert_enabled = getattr(item, 'alert_enabled', False)
                trade_enabled = getattr(item, 'trade_enabled', False)
                trade_amount = getattr(item, 'trade_amount_usd', None) or 0
                is_deleted = getattr(item, 'is_deleted', None)
                
                logger.info(
                    f"   - {symbol}: alert_enabled={alert_enabled}, trade_enabled={trade_enabled}, "
                    f"trade_amount=${trade_amount}, is_deleted={is_deleted}"
                )
            
            return watchlist_items
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
    
    async def monitor_signals(self, db: Session):
        """Monitor signals for all coins with alert_enabled = true (for alerts)
        Orders are only created if trade_enabled = true in addition to alert_enabled = true
        """
        try:
            # Check Telegram health before processing
            telegram_notifier.resolve_send_config()
            if not telegram_notifier.enabled:
                logger.warning(
                    "[GLOBAL_BLOCKER] Telegram notifier is disabled - alerts will not be sent. "
                    "Check ENVIRONMENT=aws and TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID_AWS"
                )
            
            # Fetch watchlist items in a thread pool to avoid blocking the event loop
            watchlist_items = await asyncio.to_thread(self._fetch_watchlist_items_sync, db)

            logger.info(
                "[SIGNAL_MONITOR_TICK] tick_ts=%s items=%d",
                datetime.now(timezone.utc).isoformat(),
                len(watchlist_items) if watchlist_items else 0,
            )
            
            if not watchlist_items:
                logger.warning(
                    "[GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found - no alerts will be sent"
                )
                return
            
            # DIAG_MODE: Filter to only diagnostic symbol if set
            if DIAG_SYMBOL:
                watchlist_items = [item for item in watchlist_items if getattr(item, 'symbol', '').upper() == DIAG_SYMBOL]
                if not watchlist_items:
                    logger.info(f"🔧 [DIAG_MODE] No watchlist items found for {DIAG_SYMBOL}")
                    return
                logger.info(f"🔧 [DIAG_MODE] Filtered to {len(watchlist_items)} item(s) for {DIAG_SYMBOL}")
            
            for item in watchlist_items:
                try:
                    await self._check_signal_for_coin(db, item)
                except Exception as e:
                    logger.error(f"Error monitoring signal for {item.symbol}: {e}", exc_info=True)
                    continue  # Continue with next coin even if one fails
        except Exception as e:
            logger.error(f"Error in monitor_signals: {e}", exc_info=True)
    
    async def _check_signal_for_coin(self, db: Session, watchlist_item: WatchlistItem):
        """Async wrapper to run the synchronous signal check in a thread"""
        await asyncio.to_thread(self._check_signal_for_coin_sync, db, watchlist_item)

    def _check_signal_for_coin_sync(self, db: Session, watchlist_item: WatchlistItem):
        """Check signal for a specific coin and take action if needed"""
        import uuid
        symbol = watchlist_item.symbol
        normalized_symbol = normalize_symbol_for_exchange(symbol)
        exchange = watchlist_item.exchange or "CRYPTO_COM"
        
        # Generate unique evaluation_id for this symbol evaluation run
        evaluation_id = str(uuid.uuid4())[:8]
        
        # EARLY CHECK: Kill switch - if ON, skip all signal processing
        try:
            from app.utils.trading_guardrails import _get_telegram_kill_switch_status
            kill_switch_on = _get_telegram_kill_switch_status(db)
            if kill_switch_on:
                logger.debug(f"🚫 [KILL_SWITCH] Skipping signal check for {symbol} - kill switch is ON")
                return  # Exit early - no signal processing when kill switch is on
        except Exception as e:
            logger.warning(f"Error checking kill switch for {symbol}: {e}")
            # Continue processing if kill switch check fails (fail-safe: allow signals)
        
        try:
            # IMPORTANT: Query fresh from database to get latest trade_amount_usd
            # This ensures we have the most recent value even if it was just updated from the dashboard
            # Using a fresh query instead of refresh() to avoid any session caching issues
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
                old_alert = watchlist_item.alert_enabled
                old_margin = watchlist_item.trade_on_margin if hasattr(watchlist_item, 'trade_on_margin') else None
                old_min_pct = getattr(watchlist_item, "min_price_change_pct", None)
                old_cooldown = getattr(watchlist_item, "alert_cooldown_minutes", None)
                old_buy_alert = getattr(watchlist_item, "buy_alert_enabled", None)
                old_sell_alert = getattr(watchlist_item, "sell_alert_enabled", None)
                # Update the watchlist_item object with fresh values
                # CRITICAL: Preserve user-set trade_amount_usd - only update if it was None/0 in DB
                # This prevents overwriting user's manual settings during refresh
                if fresh_item.trade_amount_usd is not None and fresh_item.trade_amount_usd != 0:
                    # Only update if current value is None/0 (user hasn't set it yet)
                    if watchlist_item.trade_amount_usd is None or watchlist_item.trade_amount_usd == 0:
                        watchlist_item.trade_amount_usd = fresh_item.trade_amount_usd
                    # Otherwise preserve user's value
                watchlist_item.trade_enabled = fresh_item.trade_enabled
                watchlist_item.alert_enabled = fresh_item.alert_enabled
                # CRITICAL: Also refresh trade_on_margin from database
                if hasattr(fresh_item, 'trade_on_margin'):
                    watchlist_item.trade_on_margin = fresh_item.trade_on_margin
                # CRITICAL: Refresh alert toggle flags (controls per-side alert emission)
                if hasattr(fresh_item, 'buy_alert_enabled'):
                    watchlist_item.buy_alert_enabled = fresh_item.buy_alert_enabled
                if hasattr(fresh_item, 'sell_alert_enabled'):
                    watchlist_item.sell_alert_enabled = fresh_item.sell_alert_enabled
                # CRITICAL: Refresh throttle thresholds from database
                if hasattr(fresh_item, "min_price_change_pct"):
                    watchlist_item.min_price_change_pct = fresh_item.min_price_change_pct
                if hasattr(fresh_item, "alert_cooldown_minutes"):
                    watchlist_item.alert_cooldown_minutes = fresh_item.alert_cooldown_minutes
                
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
                    f"buy_alert_enabled={old_buy_alert} -> {getattr(watchlist_item, 'buy_alert_enabled', None)}, "
                    f"sell_alert_enabled={old_sell_alert} -> {getattr(watchlist_item, 'sell_alert_enabled', None)}, "
                    f"trade_on_margin={old_margin} -> {getattr(watchlist_item, 'trade_on_margin', None)}, "
                    f"min_price_change_pct={old_min_pct} -> {getattr(watchlist_item, 'min_price_change_pct', None)}, "
                    f"alert_cooldown_minutes={old_cooldown} -> {getattr(watchlist_item, 'alert_cooldown_minutes', None)}"
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
                            if hasattr(latest, "buy_alert_enabled"):
                                watchlist_item.buy_alert_enabled = latest.buy_alert_enabled
                            if hasattr(latest, "sell_alert_enabled"):
                                watchlist_item.sell_alert_enabled = latest.sell_alert_enabled
                            if hasattr(latest, "min_price_change_pct"):
                                watchlist_item.min_price_change_pct = latest.min_price_change_pct
                            if hasattr(latest, "alert_cooldown_minutes"):
                                watchlist_item.alert_cooldown_minutes = latest.alert_cooldown_minutes
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
        config_hash_current = self._compute_config_hash(watchlist_item)

        # PHASE 0: Structured logging with evaluation_id
        min_price_change_pct, alert_cooldown_minutes, threshold_sources = self._resolve_alert_thresholds(watchlist_item)
        threshold_context = {
            "min_price_change_pct": min_price_change_pct,
            "alert_cooldown_minutes": alert_cooldown_minutes,
            "item_min_pct": threshold_sources.get("item_min_pct"),
            "preset_min_pct": threshold_sources.get("preset_min_pct"),
            "default_min_pct": threshold_sources.get("default_min_pct"),
        }
        telegram_config = telegram_notifier.resolve_send_config()
        logger.info(
            f"[EVAL_{evaluation_id}] {symbol} evaluation started | "
            f"strategy={strategy_display}/{risk_display} | "
            f"min_price_change_pct={min_price_change_pct}% | "
            f"alert_cooldown_minutes={alert_cooldown_minutes} | "
            f"buy_alert_enabled={getattr(watchlist_item, 'buy_alert_enabled', False)} | "
            f"sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)} | "
            f"alert_enabled={watchlist_item.alert_enabled} | "
            f"environment={get_runtime_origin()}"
        )

        self._log_symbol_context(symbol, "BUY", watchlist_item, strategy_display, risk_display)
        self._log_symbol_context(symbol, "SELL", watchlist_item, strategy_display, risk_display)

        # ========================================================================
        # CRITICAL: alert_enabled controls alerts/trades, but must NOT hide signals
        # ========================================================================
        # We still evaluate signals to avoid "ghost" states, but we will block
        # alert/trade actions if alert_enabled is False.
        alerts_globally_disabled = not watchlist_item.alert_enabled
        if alerts_globally_disabled:
            blocked_msg = (
                f"🚫 BLOQUEADO: {symbol} - Las alertas están deshabilitadas para este símbolo "
                f"(alert_enabled=False). No se procesará señal ni se enviarán alertas. "
                f"Para habilitar alertas, active 'alert_enabled' en la configuración del símbolo."
            )
            logger.info(
                "[GATE] symbol=%s gate=alert_enabled decision=BLOCK reason=alert_disabled evaluation_id=%s",
                symbol,
                evaluation_id,
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
        
        try:
            # CRITICAL: Use the SAME data source as the dashboard (MarketData/MarketPrice)
            # This ensures consistency between dashboard display and alert sending
            # Priority: MarketData/MarketPrice → watchlist_items → API (fallback)
            from app.models.market_price import MarketPrice, MarketData
            from price_fetcher import get_price_with_fallback
            
            # First, try to get data from MarketPrice and MarketData (same as dashboard)
            mp = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
            md = db.query(MarketData).filter(MarketData.symbol == symbol).first()
            
            # Get price from MarketPrice if available (same priority as dashboard)
            if mp and mp.price and mp.price > 0:
                current_price = mp.price
                volume_24h = mp.volume_24h or 0.0
                price_source = "MarketPrice"
            else:
                # Fallback to API if MarketPrice not available
                logger.debug(f"⚠️ {symbol}: No MarketPrice data, falling back to API")
                result = get_price_with_fallback(symbol, "15m")
                current_price = result.get('price', 0)
                volume_24h = result.get('volume_24h', 0)
                price_source = "API (fallback)"
            
            if not current_price or current_price <= 0:
                logger.warning(f"⚠️ {symbol}: No price data available (tried MarketPrice and API), skipping signal check")
                return
            
            # Get indicators - use MarketData if available (same priority as dashboard)
            # This ensures RSI/MA values match what the dashboard shows
            if md and md.rsi is not None:
                rsi = md.rsi
                rsi_source = "MarketData"
            elif watchlist_item and hasattr(watchlist_item, 'rsi') and watchlist_item.rsi is not None:
                rsi = watchlist_item.rsi
                rsi_source = "watchlist_items"
            else:
                # Fallback to API if neither MarketData nor watchlist_items has RSI
                if 'result' not in locals():
                    result = get_price_with_fallback(symbol, "15m")
                rsi = result.get('rsi', 50)
                rsi_source = "API (fallback)"
            
            # Get other indicators with same priority as dashboard
            if md and md.ma50 is not None:
                ma50 = md.ma50
            elif watchlist_item and hasattr(watchlist_item, 'ma50') and watchlist_item.ma50 is not None:
                ma50 = watchlist_item.ma50
            else:
                ma50 = None  # Will be validated later
            
            if md and md.ma200 is not None:
                ma200 = md.ma200
            elif watchlist_item and hasattr(watchlist_item, 'ma200') and watchlist_item.ma200 is not None:
                ma200 = watchlist_item.ma200
            else:
                ma200 = current_price  # Fallback
            
            if md and md.ema10 is not None:
                ema10 = md.ema10
            elif watchlist_item and hasattr(watchlist_item, 'ema10') and watchlist_item.ema10 is not None:
                ema10 = watchlist_item.ema10
            else:
                ema10 = None  # Will be validated later
            
            if md and md.atr is not None:
                atr = md.atr
            elif watchlist_item and hasattr(watchlist_item, 'atr') and watchlist_item.atr is not None:
                atr = watchlist_item.atr
            else:
                atr = current_price * 0.02  # Fallback
            
            # Get ma10w (same as dashboard)
            if md and md.ma10w is not None and md.ma10w > 0:
                ma10w = md.ma10w
            elif ma200 and ma200 > 0:
                ma10w = ma200
            elif ma50 and ma50 > 0:
                ma10w = ma50
            else:
                ma10w = current_price
            
            # Get volume data
            # CRITICAL: Use current_volume (hourly) for ratio calculation, not volume_24h
            # This ensures accurate volume ratio comparison (current volume vs average volume)
            current_volume = None
            if md and md.current_volume is not None and md.current_volume > 0:
                current_volume = md.current_volume
            elif volume_24h > 0:
                # Fallback: approximate current_volume as volume_24h / 24 (hourly average)
                current_volume = volume_24h / 24.0
                logger.debug(f"⚠️ {symbol}: Using approximated current_volume from volume_24h: {current_volume:.2f} (volume_24h={volume_24h:.2f} / 24)")
            
            if md and md.avg_volume is not None and md.avg_volume > 0:
                avg_volume = md.avg_volume
            else:
                # Fallback: if no avg_volume, approximate as volume_24h / 24 (hourly average)
                avg_volume = (volume_24h / 24.0) if volume_24h > 0 else None
                if avg_volume:
                    logger.debug(f"⚠️ {symbol}: Using approximated avg_volume from volume_24h: {avg_volume:.2f} (volume_24h={volume_24h:.2f} / 24)")
            
            # Validate MAs are available before proceeding with buy signal checks
            if ma50 is None or ema10 is None:
                missing_mas = []
                if ma50 is None:
                    missing_mas.append("MA50")
                if ema10 is None:
                    missing_mas.append("EMA10")
                logger.warning(
                    f"⚠️ {symbol}: MAs REQUIRED but missing: {', '.join(missing_mas)}. "
                    f"Cannot create buy orders without MA validation. Skipping signal check."
                )
                return  # Exit early - cannot validate buy conditions without MAs
            
            logger.debug(f"📊 {symbol}: Using data from {price_source}, RSI from {rsi_source}")
            if current_volume and avg_volume:
                volume_ratio_debug = current_volume / avg_volume if avg_volume > 0 else 0
                logger.debug(f"📊 {symbol}: Volume data - current={current_volume:.2f}, avg={avg_volume:.2f}, ratio={volume_ratio_debug:.2f}x")
            
            # Calculate resistance levels
            price_precision = 2 if current_price >= 100 else 4
            res_up = round(current_price * 1.02, price_precision)
            res_down = round(current_price * 0.98, price_precision)
            
        except Exception as e:
            logger.warning(f"Error fetching price data for {symbol}: {e}", exc_info=True)
            return
        
        # Calculate trading signals (moved outside try/except block)
        try:
            # Log input values for UNI_USD debugging
            if symbol == "UNI_USD":
                logger.info(
                    f"🔍 {symbol} calling calculate_trading_signals with: "
                    f"price={current_price}, rsi={rsi}, ma50={ma50}, ema10={ema10}, "
                    f"ma10w={ma10w}, volume={current_volume}, avg_volume={avg_volume}, "
                    f"rsi_sell_threshold=70"
                )
            
            signals = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ma200=ma200,
                ema10=ema10,
                ma10w=ma10w,
                volume=current_volume,  # CRITICAL: Use current_volume (hourly) instead of volume_24h
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
            
            # Check if manual signals are set in dashboard (watchlist_item.signals)
            # If manual signals exist, use them instead of calculated signals
            manual_signals = watchlist_item.signals if hasattr(watchlist_item, 'signals') and watchlist_item.signals else None
            
            # CRITICAL FIX: Use strategy.decision as primary source (same as dashboard)
            # This ensures signal_monitor matches what the dashboard displays
            # strategy.decision is the canonical source of truth from calculate_trading_signals
            strategy_decision = None
            if signals and "strategy" in signals and isinstance(signals.get("strategy"), dict):
                strategy_decision = signals["strategy"].get("decision")
            
            if manual_signals and isinstance(manual_signals, dict):
                # Use manual signals from dashboard if they exist
                buy_signal = manual_signals.get("buy", False) if "buy" in manual_signals else signals.get("buy_signal", False)
                sell_signal = manual_signals.get("sell", False) if "sell" in manual_signals else signals.get("sell_signal", False)
                logger.info(f"🔧 {symbol} using MANUAL signals from dashboard: buy={buy_signal}, sell={sell_signal}")
            elif strategy_decision:
                # CRITICAL: Use strategy.decision as primary source (matches dashboard)
                # This ensures alerts are sent when dashboard shows BUY
                buy_signal = (strategy_decision == "BUY")
                sell_signal = (strategy_decision == "SELL")
                logger.info(
                    f"✅ {symbol} using strategy.decision={strategy_decision} (matches dashboard): "
                    f"buy_signal={buy_signal}, sell_signal={sell_signal}"
                )
            else:
                # Fallback to calculated signals (normal behavior)
                buy_signal = signals.get("buy_signal", False)
                sell_signal = signals.get("sell_signal", False)
                logger.debug(
                    f"⚠️ {symbol} strategy.decision not available, using buy_signal={buy_signal}, "
                    f"sell_signal={sell_signal} from calculate_trading_signals"
                )
            
            # DIAG_MODE: Force buy_signal if DIAG_FORCE_SIGNAL_BUY is set
            if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL and DIAG_FORCE_SIGNAL_BUY:
                buy_signal = True
                logger.info(f"🔧 [DIAG_MODE] Forcing buy_signal=True for {symbol} (DIAG_FORCE_SIGNAL_BUY=1)")
            
            # Log result for UNI_USD debugging
            if symbol == "UNI_USD":
                logger.info(f"🔍 {symbol} calculate_trading_signals returned: sell_signal={sell_signal}")
            sl_price = signals.get("sl")
            tp_price = signals.get("tp")
            
            # Log signal detection for debugging (include MA values if available)
            ma_info = f", MA50={ma50:.2f}, EMA10={ema10:.2f}" if ma50 is not None and ema10 is not None else ", MAs=N/A"
            logger.info(f"🔍 {symbol} signal check: buy_signal={buy_signal}, sell_signal={sell_signal}, price=${current_price:.4f}, RSI={rsi:.1f}{ma_info}")
            
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

            logger.info(
                "[SIGNAL_EVAL] symbol=%s decision=%s strategy=%s evaluation_id=%s thresholds=%s "
                "telegram_enabled=%s chat_id=%s",
                symbol,
                current_state,
                f"{strategy_display}/{risk_display}",
                evaluation_id,
                threshold_context,
                telegram_config.get("enabled"),
                telegram_config.get("chat_id"),
            )

            self._log_pipeline_stage(
                stage="SIGNAL_EVALUATED",
                symbol=normalized_symbol,
                strategy_key=strategy_key,
                decision=current_state,
                last_price=current_price,
                timestamp=now_utc.isoformat(),
                correlation_id=evaluation_id,
            )
            # Persist per-symbol signal state (always, even if alerts/trades blocked)
            strategy_summary = None
            if signals and isinstance(signals.get("strategy"), dict):
                strategy_summary = signals.get("strategy", {}).get("summary")
            if not strategy_summary and signals and isinstance(signals.get("rationale"), list):
                strategy_summary = " | ".join(signals.get("rationale", [])[:2]) or None
            evaluated_at = now_utc if "now_utc" in locals() else datetime.now(timezone.utc)
            self._upsert_watchlist_signal_state(
                db,
                symbol=normalized_symbol,
                strategy_key=strategy_key,
                signal_side="NONE" if current_state == "WAIT" else current_state,
                last_price=current_price,
                evaluated_at_utc=evaluated_at,
                alert_status="NONE" if current_state == "WAIT" else self._UNSET,
                alert_block_reason=None if current_state == "WAIT" else self._UNSET,
                last_alert_at_utc=None if current_state == "WAIT" else self._UNSET,
                trade_status="NONE" if current_state == "WAIT" else self._UNSET,
                trade_block_reason=None if current_state == "WAIT" else self._UNSET,
                last_trade_at_utc=None if current_state == "WAIT" else self._UNSET,
                correlation_id=evaluation_id,
            )
            if current_state != "WAIT":
                if not watchlist_item.alert_enabled:
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="ALERT_DISABLED",
                        last_alert_at_utc=evaluated_at,
                        correlation_id=evaluation_id,
                    )
                elif current_state == "BUY" and not getattr(watchlist_item, "buy_alert_enabled", False):
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="SIDE_DISABLED",
                        last_alert_at_utc=evaluated_at,
                        correlation_id=evaluation_id,
                    )
                elif current_state == "SELL" and not getattr(watchlist_item, "sell_alert_enabled", False):
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="SIDE_DISABLED",
                        last_alert_at_utc=evaluated_at,
                        correlation_id=evaluation_id,
                    )
                if not watchlist_item.trade_enabled:
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        trade_status="BLOCKED",
                        trade_block_reason="TRADE_DISABLED",
                        last_trade_at_utc=evaluated_at,
                        correlation_id=evaluation_id,
                    )
        except Exception as e:
            logger.error(f"Error calculating trading signals for {symbol}: {e}", exc_info=True)
            return

        # CANONICAL: Fixed 60 seconds (1.0 minute) throttling - not configurable
        # Per canonical documentation: ALERTAS_Y_ORDENES_NORMAS.md
        FIXED_THROTTLE_MINUTES = 1.0  # 60 seconds - fixed by canonical logic
        
        resolved_min_pct = (
            min_price_change_pct
            if min_price_change_pct is not None
            else self.ALERT_MIN_PRICE_CHANGE_PCT
        )
        throttle_config = SignalThrottleConfig(
            min_price_change_pct=resolved_min_pct,
            min_interval_minutes=FIXED_THROTTLE_MINUTES,  # Fixed 60 seconds - not configurable
        )
        logger.debug(
            f"[THROTTLE_CONFIG] symbol={symbol} resolved_min_pct={resolved_min_pct}% "
            f"item_min_pct={threshold_sources.get('item_min_pct')} "
            f"preset_min_pct={threshold_sources.get('preset_min_pct')} "
            f"default_min_pct={threshold_sources.get('default_min_pct')} "
            f"eval_id={evaluation_id}"
        )
        
        # CRITICAL: Always load snapshots to check for config changes, even if no signals are active
        # This ensures that changes to trade_amount_usd, alert_enabled, etc. reset the throttle immediately
        signal_snapshots: Dict[str, LastSignalSnapshot] = {}
        try:
            signal_snapshots = fetch_signal_states(
                db, symbol=symbol, strategy_key=strategy_key
            )
        except Exception as snapshot_err:
            logger.warning(f"Failed to load throttle state for {symbol}: {snapshot_err}")
            # CRITICAL: Rollback the transaction to allow subsequent operations to proceed
            # This prevents "current transaction is aborted" errors
            try:
                db.rollback()
            except Exception as rollback_err:
                logger.warning(f"Failed to rollback transaction after throttle state error: {rollback_err}")
            signal_snapshots = {}
        
        last_buy_snapshot = signal_snapshots.get("BUY")
        last_sell_snapshot = signal_snapshots.get("SELL")
        
        # CRITICAL: Check for config changes and reset throttle immediately
        # This ensures that changes to trade_amount_usd, alert_enabled, etc. reset the throttle immediately
        from app.services.signal_throttle import reset_throttle_state
        config_changed = False
        logger.info(f"[CONFIG_CHECK] {symbol}: Checking config_hash. Current={config_hash_current[:16] if config_hash_current else None}..., Snapshots={len(signal_snapshots)}")
        for side, snapshot in signal_snapshots.items():
            logger.info(f"[CONFIG_CHECK] {symbol} {side}: snapshot={snapshot is not None}, stored_hash={snapshot.config_hash[:16] if snapshot and snapshot.config_hash else None}...")
            if snapshot:
                # Detect change if: stored hash is None (first time) OR stored hash differs from current
                stored_hash = snapshot.config_hash
                hash_changed = (
                    stored_hash is None or  # First time - no hash stored yet
                    stored_hash != config_hash_current  # Hash changed
                )
                
                if hash_changed and config_hash_current:
                    config_changed = True
                    stored_preview = stored_hash[:16] + "..." if stored_hash else "None"
                    logger.info(
                        f"🔄 [CONFIG_CHANGE] {symbol} {side}: Config hash changed "
                        f"(stored={stored_preview} current={config_hash_current[:16]}...). "
                        f"Resetting throttle immediately."
                    )
                    reset_throttle_state(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side=side,
                        current_price=current_price,
                        parameter_change_reason=f"Config hash changed (trade_amount_usd, alert flags, etc.)",
                        config_hash=config_hash_current,
                    )
                    # Refresh snapshots after reset
                    try:
                        signal_snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
                        last_buy_snapshot = signal_snapshots.get("BUY")
                        last_sell_snapshot = signal_snapshots.get("SELL")
                    except Exception as refresh_err:
                        logger.warning(f"Failed to refresh throttle state after reset for {symbol}: {refresh_err}")
        
        if config_changed:
            logger.info(
                f"✅ [CONFIG_CHANGE] {symbol}: Throttle reset complete. "
                f"Next signal will bypass throttle (force_next_signal=True)."
            )

        now_utc = datetime.now(timezone.utc)
        buy_state_recorded = False
        buy_alert_sent_successfully = False  # Track if BUY alert was sent successfully
        sell_state_recorded = False
        # Store throttle reasons for use in alert messages
        throttle_buy_reason: Optional[str] = None
        throttle_sell_reason: Optional[str] = None

        # DIAG_MODE: Print decision trace for diagnostic symbol
        if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
            # Print markers to stdout for snippet extraction
            print("=" * 80)
            print(f"===== TRACE START {symbol} =====")
            # Also log normally
            logger.info("=" * 80)
            logger.info(f"===== TRACE START {symbol} =====")
            
            # Print signal explainability inside trace block
            # Extract buy_flags from strategy.reasons (where they're stored)
            buy_flags = {}
            if signals and "strategy" in signals:
                strategy_dict = signals.get("strategy", {})
                if isinstance(strategy_dict, dict) and "reasons" in strategy_dict:
                    reasons = strategy_dict.get("reasons", {})
                    buy_flags = {
                        "buy_rsi_ok": reasons.get("buy_rsi_ok"),
                        "buy_ma_ok": reasons.get("buy_ma_ok"),
                        "buy_volume_ok": reasons.get("buy_volume_ok"),
                        "buy_target_ok": reasons.get("buy_target_ok"),
                        "buy_price_ok": reasons.get("buy_price_ok"),
                    }
            
            # Print signal inputs
            rsi_str = f"{rsi:.1f}" if rsi else "None"
            ma50_str = f"{ma50:.2f}" if ma50 else "None"
            ma200_str = f"{ma200:.2f}" if ma200 else "None"
            ema10_str = f"{ema10:.2f}" if ema10 else "None"
            buy_target_str = f"{watchlist_item.buy_target}" if watchlist_item.buy_target else "None"
            volume_str = f"{current_volume:.2f}" if current_volume else "None"
            avg_volume_str = f"{avg_volume:.2f}" if avg_volume else "None"
            
            print(f"signal_inputs: price=${current_price:.4f} rsi={rsi_str} "
                  f"ma50={ma50_str} ma200={ma200_str} ema10={ema10_str} buy_target={buy_target_str} "
                  f"resistance_up=${res_up:.2f} resistance_down=${res_down:.2f} "
                  f"volume={volume_str} avg_volume={avg_volume_str} "
                  f"strategy_id={strategy_type.value}/{risk_approach.value}")
            
            # Print signal conditions (from buy_flags)
            rsi_ok = buy_flags.get("buy_rsi_ok")
            ma_ok = buy_flags.get("buy_ma_ok")
            vol_ok = buy_flags.get("buy_volume_ok")
            target_ok = buy_flags.get("buy_target_ok")
            price_ok = buy_flags.get("buy_price_ok")
            
            print(f"signal_conditions: rsi_ok={rsi_ok} ma_ok={ma_ok} vol_ok={vol_ok} target_ok={target_ok} price_ok={price_ok} "
                  f"strategy_decision={strategy_decision} buy_signal={buy_signal} sell_signal={sell_signal}")
            
            # Print active strategy params from DB
            print(f"strategy_params: sl_tp_mode={watchlist_item.sl_tp_mode} "
                  f"min_price_change_pct={watchlist_item.min_price_change_pct} "
                  f"trade_amount_usd={watchlist_item.trade_amount_usd} "
                  f"rsi_buy_threshold=40 rsi_sell_threshold=70")
            
            self._print_decision_trace(
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                current_price=current_price,
                signal_exists=buy_signal,
                alert_enabled=getattr(watchlist_item, 'buy_alert_enabled', False) or watchlist_item.alert_enabled,
                trade_enabled=watchlist_item.trade_enabled,
                snapshot=signal_snapshots.get("BUY"),
                throttle_config=throttle_config,
                now_utc=now_utc,
                evaluation_id=evaluation_id
            )

        if buy_signal:
            self._log_signal_candidate(
                symbol,
                "BUY",
                {
                    "price": current_price,
                    "rsi": rsi,
                    "strategy_key": strategy_key,
                    "min_price_change_pct": throttle_config.min_price_change_pct,
                    "min_interval_minutes": throttle_config.min_interval_minutes,
                    "last_signal_at": last_buy_snapshot.timestamp.isoformat()
                    if last_buy_snapshot and last_buy_snapshot.timestamp
                    else None,
                    "last_signal_price": last_buy_snapshot.price if last_buy_snapshot else None,
                },
            )
            buy_allowed, buy_reason = should_emit_signal(
                symbol=symbol,
                side="BUY",
                current_price=current_price,
                current_time=now_utc,
                config=throttle_config,
                last_same_side=signal_snapshots.get("BUY"),
                last_opposite_side=signal_snapshots.get("SELL"),
                db=db,
                strategy_key=strategy_key,
            )
            logger.info(
                "[GATE] symbol=%s gate=throttle decision=%s reason=%s evaluation_id=%s thresholds=%s",
                symbol,
                "PASS" if buy_allowed else "BLOCK",
                buy_reason,
                evaluation_id,
                threshold_context,
            )
            logger.info(
                f"[THROTTLE_EVAL] symbol={symbol} side=BUY decision={'ACCEPT' if buy_allowed else 'BLOCK'} "
                f"resolved_min_pct={throttle_config.min_price_change_pct} "
                f"item_min_pct={threshold_sources.get('item_min_pct')} "
                f"preset_min_pct={threshold_sources.get('preset_min_pct')} "
                f"default_min_pct={threshold_sources.get('default_min_pct')} "
                f"eval_id={evaluation_id}"
            )
            # CRITICAL: Save previous price from snapshot BEFORE recording the signal event
            # This ensures we use the same price that was used in the throttle check for consistency
            last_buy_snapshot = signal_snapshots.get("BUY")
            prev_buy_price_from_snapshot: Optional[float] = last_buy_snapshot.price if last_buy_snapshot and last_buy_snapshot.price else None
            
            # PHASE 0: Structured logging for signal evaluation decision
            time_since_last = None
            if last_buy_snapshot and last_buy_snapshot.timestamp:
                elapsed = (now_utc - last_buy_snapshot.timestamp).total_seconds()
                time_since_last = elapsed
            price_change_usd = None
            price_change_pct = None
            if prev_buy_price_from_snapshot and prev_buy_price_from_snapshot > 0:
                price_change_usd = abs(current_price - prev_buy_price_from_snapshot)
                price_change_pct = abs((current_price - prev_buy_price_from_snapshot) / prev_buy_price_from_snapshot * 100)
            
            price_change_usd_str = f"${price_change_usd:.2f}" if price_change_usd else "N/A"
            price_change_pct_str = f"{price_change_pct:.2f}%" if price_change_pct else "N/A"
            time_since_last_str = f"{time_since_last:.1f}s" if time_since_last else "N/A"
            
            logger.info(
                f"[EVAL_{evaluation_id}] {symbol} BUY signal evaluation | "
                f"decision={'ACCEPT' if buy_allowed else 'BLOCK'} | "
                f"current_price=${current_price:.4f} | "
                f"price_change_usd={price_change_usd_str} | "
                f"price_change_pct={price_change_pct_str} | "
                f"time_since_last={time_since_last_str} | "
                f"threshold={throttle_config.min_price_change_pct}% | "
                f"reason={buy_reason}"
            )
            
            # Store throttle reason for use in alert message
            if buy_allowed:
                throttle_buy_reason = buy_reason
            if not buy_allowed:
                # CRITICAL: Only block if there's a valid price reference
                # If no price reference exists, the signal should be allowed (should_emit_signal already handles this,
                # but we add an extra safety check here)
                has_valid_reference = (
                    last_buy_snapshot is not None 
                    and last_buy_snapshot.price is not None 
                    and last_buy_snapshot.price > 0
                )
                
                # If no valid reference, allow the signal (should not be blocked)
                if not has_valid_reference:
                    logger.warning(
                        f"⚠️ {symbol} BUY: Throttle check returned False but no valid price reference exists. "
                        f"Allowing signal anyway. Reason: {buy_reason}"
                    )
                    # Override the throttle decision - allow the signal
                    buy_allowed = True
                    throttle_buy_reason = "No previous same-side signal recorded - allowing first signal"
                    # Record the signal event
                    try:
                        emit_reason = "First signal for this side/strategy (no previous reference)"
                        record_signal_event(
                            db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=current_price,
                            source="signal_check",
                            emit_reason=emit_reason,
                        )
                        logger.debug(f"📝 Recorded BUY signal event for {symbol} at {current_price} (strategy: {strategy_key}) - first signal")
                    except Exception as record_err:
                        logger.warning(f"Failed to record BUY signal event for {symbol} (non-blocking): {record_err}")
                else:
                    # Build blocked message with reference price and timestamp (only if we have a valid reference)
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason=self._map_alert_block_reason(buy_reason),
                        last_alert_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
                    )
                    blocked_msg_parts = [f"🚫 BLOQUEADO: {symbol} BUY - {buy_reason}"]
                    
                    # Add reference price and timestamp (we know they exist from the check above)
                    ref_price = last_buy_snapshot.price
                    ref_timestamp = last_buy_snapshot.timestamp
                    # Format timestamp in a readable format
                    if ref_timestamp:
                        if ref_timestamp.tzinfo is None:
                            ref_timestamp = ref_timestamp.replace(tzinfo=timezone.utc)
                        ref_time_str = ref_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
                        # Format price with appropriate decimals based on value
                        if ref_price >= 1000:
                            price_str = f"${ref_price:,.2f}"
                        elif ref_price >= 1:
                            price_str = f"${ref_price:.2f}"
                        elif ref_price >= 0.01:
                            price_str = f"${ref_price:.4f}"
                        else:
                            price_str = f"${ref_price:.8f}"
                        blocked_msg_parts.append(f"Precio de referencia: {price_str} (último mensaje exitoso: {ref_time_str})")
                    else:
                        # Format price with appropriate decimals based on value
                        if ref_price >= 1000:
                            price_str = f"${ref_price:,.2f}"
                        elif ref_price >= 1:
                            price_str = f"${ref_price:.2f}"
                        elif ref_price >= 0.01:
                            price_str = f"${ref_price:.4f}"
                        else:
                            price_str = f"${ref_price:.8f}"
                        blocked_msg_parts.append(f"Precio de referencia: {price_str}")
                    
                    blocked_msg = " | ".join(blocked_msg_parts)
                    logger.info(blocked_msg)
                    self._log_signal_rejection(
                        symbol,
                        "BUY",
                        self._classify_throttle_reason(buy_reason),
                        {"throttle_reason": buy_reason},
                    )
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        from app.utils.decision_reason import make_skip, ReasonCode
                        import uuid
                        
                        # Create DecisionReason for SKIP (alert was blocked)
                        correlation_id = str(uuid.uuid4())
                        reason_code = self._map_throttle_reason_code(buy_reason)
                        
                        decision_reason = make_skip(
                            reason_code=reason_code,
                            message=f"Alert blocked for {symbol} BUY: {buy_reason}",
                            context={
                                "symbol": symbol,
                                "price": current_price,
                                "reference_price": ref_price if ref_price else None,
                                "reference_timestamp": ref_timestamp.isoformat() if ref_timestamp else None,
                                "throttle_reason": buy_reason,
                                "strategy_key": strategy_key,
                            },
                            source="throttle",
                            correlation_id=correlation_id,
                        )
                        logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")

                        add_telegram_message(
                            blocked_msg,
                            symbol=symbol,
                            blocked=True,
                            throttle_status="BLOCKED",
                            throttle_reason=buy_reason,
                            decision_type=decision_reason.decision_type.value,
                            reason_code=decision_reason.reason_code,
                            reason_message=decision_reason.reason_message,
                            context_json=decision_reason.context,
                            correlation_id=decision_reason.correlation_id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to add blocked alert message with DecisionReason: {e}", exc_info=True)
                    # CRITICAL: Do NOT update reference price when blocked - it must remain the last successful (non-blocked) message price
                    # The price reference should only be updated when a message is actually sent successfully
                    buy_signal = False
                    if current_state == "BUY":
                        current_state = "WAIT"
        
        # DIAG_MODE: Print decision trace for diagnostic symbol (SELL)
        if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
            self._print_decision_trace(
                symbol=symbol,
                strategy_key=strategy_key,
                side="SELL",
                current_price=current_price,
                signal_exists=sell_signal,
                alert_enabled=getattr(watchlist_item, 'sell_alert_enabled', False) or watchlist_item.alert_enabled,
                trade_enabled=watchlist_item.trade_enabled,
                snapshot=signal_snapshots.get("SELL"),
                throttle_config=throttle_config,
                now_utc=now_utc,
                evaluation_id=evaluation_id
            )
        
        # DIAG_MODE: Print signal detection summary and TRADE decision trace at end of trace
        if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
            # Print signal_detected to stdout
            print(f"signal_detected: buy={buy_signal}, sell={sell_signal}")
            logger.info(f"  signal_detected: buy={buy_signal}, sell={sell_signal}")
            
            # Always print TRADE decision trace in DIAG mode, even if no signal
            # This ensures the snippet always includes TRADE decision information
            trade_guard_reason = None
            trade_should_create = False
            
            if not watchlist_item.trade_enabled:
                trade_guard_reason = "TRADE_DISABLED"
            elif not buy_signal:
                trade_guard_reason = "NO_SIGNAL"
            else:
                # If there's a signal, check common guards (but NOT alert sending)
                # Trade execution is independent of alert sending
                if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                    trade_guard_reason = "INVALID_TRADE_AMOUNT"
                else:
                    # Signal exists, trade enabled, amount valid
                    # Note: Alert sending is NOT a gate for trade execution
                    # Check if we would create order (this is evaluated in the order creation path)
                    # For now, assume it would be allowed if all conditions are met
                    trade_should_create = True
            
            # Print TRADE decision trace
            self._print_trade_decision_trace(
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",  # Focus on BUY for now
                current_price=current_price,
                signal_exists=buy_signal,
                trade_enabled=watchlist_item.trade_enabled,
                trade_amount_usd=watchlist_item.trade_amount_usd,
                should_create_order=trade_should_create,
                guard_reason=trade_guard_reason,
                evaluation_id=evaluation_id
            )
            
            # Price Move Alert Channel (independent of buy/sell signals)
            # Alert on significant price changes even without buy/sell signal
            if watchlist_item.alert_enabled:
                # Calculate price change from most recent snapshot (BUY or SELL, whichever is more recent)
                most_recent_snapshot = None
                most_recent_time = None
                if last_buy_snapshot and last_buy_snapshot.timestamp:
                    most_recent_snapshot = last_buy_snapshot
                    most_recent_time = last_buy_snapshot.timestamp
                if last_sell_snapshot and last_sell_snapshot.timestamp:
                    if most_recent_time is None or last_sell_snapshot.timestamp > most_recent_time:
                        most_recent_snapshot = last_sell_snapshot
                        most_recent_time = last_sell_snapshot.timestamp
                
                price_move_pct = None
                if most_recent_snapshot and most_recent_snapshot.price and most_recent_snapshot.price > 0:
                    price_move_pct = abs((current_price - most_recent_snapshot.price) / most_recent_snapshot.price * 100)
                
                # Check if price move exceeds threshold
                if price_move_pct is not None and price_move_pct >= PRICE_MOVE_ALERT_PCT:
                    # Check throttle for PRICE_MOVE_ALERT channel (separate from SIGNAL_ALERT)
                    # Use a separate strategy_key for price move alerts to create independent throttle bucket
                    price_move_strategy_key = f"{strategy_key}:PRICE_MOVE"
                    
                    # Fetch price move throttle state (using separate strategy_key)
                    price_move_snapshots = fetch_signal_states(
                        db, symbol=symbol, strategy_key=price_move_strategy_key
                    )
                    price_move_snapshot = price_move_snapshots.get("PRICE_MOVE")
                    
                    # Check cooldown
                    price_move_allowed = True
                    price_move_reason = "Price move threshold met"
                    if price_move_snapshot and price_move_snapshot.timestamp:
                        elapsed_seconds = (now_utc - price_move_snapshot.timestamp).total_seconds()
                        if elapsed_seconds < PRICE_MOVE_ALERT_COOLDOWN_SECONDS:
                            price_move_allowed = False
                            price_move_reason = f"THROTTLED (elapsed {elapsed_seconds:.1f}s < {PRICE_MOVE_ALERT_COOLDOWN_SECONDS:.0f}s)"
                    
                    # DIAG_MODE: Print price move decision trace
                    if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
                        direction = "↑" if current_price > most_recent_snapshot.price else "↓"
                        print(f"PRICE_MOVE decision={'EXEC' if price_move_allowed else 'SKIP'} reason={price_move_reason} "
                              f"symbol={symbol} current_price=${current_price:.4f} reference_price=${most_recent_snapshot.price:.4f} "
                              f"price_change_pct={direction} {price_move_pct:.2f}% threshold={PRICE_MOVE_ALERT_PCT:.2f}% "
                              f"cooldown={PRICE_MOVE_ALERT_COOLDOWN_SECONDS:.0f}s")
                    
                    if price_move_allowed:
                        # Send price move alert
                        direction = "↑" if current_price > most_recent_snapshot.price else "↓"
                        message = (
                            f"📊 <b>Price Move Alert: {symbol}</b>\n\n"
                            f"Price: ${current_price:.4f} ({direction} {price_move_pct:.2f}%)\n"
                            f"From: ${most_recent_snapshot.price:.4f}\n"
                            f"Time: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                            f"<i>Price move alert (independent of buy/sell signals)</i>"
                        )
                        try:
                            telegram_notifier.send_message(message)
                            # Production log line (single line, easy to grep)
                            logger.info(
                                f"PRICE_MOVE_ALERT_SENT symbol={symbol} change_pct={price_move_pct:.2f} "
                                f"price=${current_price:.4f} threshold={PRICE_MOVE_ALERT_PCT:.2f} "
                                f"cooldown_s={int(PRICE_MOVE_ALERT_COOLDOWN_SECONDS)}"
                            )
                            
                            # Record price move alert event (separate throttle bucket)
                            record_signal_event(
                                db=db,
                                symbol=symbol,
                                strategy_key=price_move_strategy_key,
                                side="PRICE_MOVE",
                                price=current_price,
                                emit_reason=f"Price move {direction} {price_move_pct:.2f}% >= {PRICE_MOVE_ALERT_PCT:.2f}%",
                                config_hash=None,  # Price move alerts don't use config hash
                            )
                        except Exception as e:
                            logger.error(f"Failed to send price move alert for {symbol}: {e}", exc_info=True)
                    else:
                        logger.debug(f"📊 Price move alert throttled for {symbol}: {price_move_reason}")
            
            # Print TRACE END markers
            print(f"===== TRACE END {symbol} =====")
            print("=" * 80)
            logger.info(f"===== TRACE END {symbol} =====")
            logger.info("=" * 80)
        
        # FIX: Initialize sell_allowed and sell_reason before throttle check to ensure they're always defined
        sell_allowed = True  # Default to True if no throttle check is performed
        sell_reason = "No throttle check performed"
        
        if sell_signal:
            # PHASE 0: Structured logging for SELL condition detection
            import uuid as uuid_module
            evaluation_trace_id = str(uuid_module.uuid4())
            logger.info(
                f"[SELL_CONDITION_TRUE] symbol={symbol} side=SELL strategy={strategy_key} "
                f"trace_id={evaluation_trace_id} price=${current_price:.4f} rsi={rsi:.1f if rsi else 'N/A'}"
            )
            
            self._log_signal_candidate(
                symbol,
                "SELL",
                {
                    "price": current_price,
                    "rsi": rsi,
                    "strategy_key": strategy_key,
                    "min_price_change_pct": throttle_config.min_price_change_pct,
                    "min_interval_minutes": throttle_config.min_interval_minutes,
                    "last_signal_at": last_sell_snapshot.timestamp.isoformat()
                    if last_sell_snapshot and last_sell_snapshot.timestamp
                    else None,
                    "last_signal_price": last_sell_snapshot.price if last_sell_snapshot else None,
                },
            )
            sell_allowed, sell_reason = should_emit_signal(
                symbol=symbol,
                side="SELL",
                current_price=current_price,
                current_time=now_utc,
                config=throttle_config,
                last_same_side=signal_snapshots.get("SELL"),
                last_opposite_side=signal_snapshots.get("BUY"),
                db=db,
                strategy_key=strategy_key,
            )
            logger.info(
                "[GATE] symbol=%s gate=throttle decision=%s reason=%s evaluation_id=%s thresholds=%s",
                symbol,
                "PASS" if sell_allowed else "BLOCK",
                sell_reason,
                evaluation_id,
                threshold_context,
            )
            logger.info(
                f"[THROTTLE_EVAL] symbol={symbol} side=SELL decision={'ACCEPT' if sell_allowed else 'BLOCK'} "
                f"resolved_min_pct={throttle_config.min_price_change_pct} "
                f"item_min_pct={threshold_sources.get('item_min_pct')} "
                f"preset_min_pct={threshold_sources.get('preset_min_pct')} "
                f"default_min_pct={threshold_sources.get('default_min_pct')} "
                f"eval_id={evaluation_id}"
            )
            # CRITICAL: Save previous price from snapshot BEFORE recording the signal event
            # This ensures we use the same price that was used in the throttle check for consistency
            last_sell_snapshot = signal_snapshots.get("SELL")
            prev_sell_price_from_snapshot: Optional[float] = last_sell_snapshot.price if last_sell_snapshot and last_sell_snapshot.price else None
            
            # PHASE 0: Structured logging for SELL signal evaluation decision
            time_since_last_sell = None
            if last_sell_snapshot and last_sell_snapshot.timestamp:
                elapsed = (now_utc - last_sell_snapshot.timestamp).total_seconds()
                time_since_last_sell = elapsed
            price_change_usd_sell = None
            price_change_pct_sell = None
            if prev_sell_price_from_snapshot and prev_sell_price_from_snapshot > 0:
                price_change_usd_sell = abs(current_price - prev_sell_price_from_snapshot)
                price_change_pct_sell = abs((current_price - prev_sell_price_from_snapshot) / prev_sell_price_from_snapshot * 100)
            
            price_change_usd_str_sell = f"${price_change_usd_sell:.2f}" if price_change_usd_sell else "N/A"
            price_change_pct_str_sell = f"{price_change_pct_sell:.2f}%" if price_change_pct_sell else "N/A"
            time_since_last_str_sell = f"{time_since_last_sell:.1f}s" if time_since_last_sell else "N/A"
            
            logger.info(
                f"[EVAL_{evaluation_id}] {symbol} SELL signal evaluation | "
                f"decision={'ACCEPT' if sell_allowed else 'BLOCK'} | "
                f"current_price=${current_price:.4f} | "
                f"price_change_usd={price_change_usd_str_sell} | "
                f"price_change_pct={price_change_pct_str_sell} | "
                f"time_since_last={time_since_last_str_sell} | "
                f"threshold={throttle_config.min_price_change_pct}% | "
                f"reason={sell_reason}"
            )
            
            # Store throttle reason for use in alert message
            # FIX: Always store throttle_reason, even when throttled, so alert section can use it
            throttle_sell_reason = sell_reason if sell_allowed else sell_reason
            # DEBUG: Log throttle check result for DOT_USD
            if symbol == "DOT_USD":
                logger.info(
                    f"🔍 [DEBUG] {symbol} SELL throttle check: sell_allowed={sell_allowed}, "
                    f"sell_reason={sell_reason}, sell_signal={sell_signal}"
                )
            # CRITICAL: If throttle check blocks the signal, set sell_signal = False to prevent alert sending
            # This ensures SELL alerts respect the same throttling rules as BUY (cooldown and price change %)
            if not sell_allowed:
                # CRITICAL: Only block if there's a valid price reference
                # If no price reference exists, the signal should be allowed (should_emit_signal already handles this,
                # but we add an extra safety check here)
                has_valid_reference = (
                    last_sell_snapshot is not None 
                    and last_sell_snapshot.price is not None 
                    and last_sell_snapshot.price > 0
                )
                
                # DIAGNOSTIC: Log why SELL signal is being blocked for TRX_USDT
                if symbol == "TRX_USDT" or symbol == "TRX_USD":
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} SELL signal BLOCKED by throttling: "
                        f"sell_allowed={sell_allowed}, sell_reason={sell_reason}, "
                        f"has_valid_reference={has_valid_reference}, "
                        f"last_sell_snapshot={last_sell_snapshot}, "
                        f"current_price={current_price}, "
                        f"sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)}, "
                        f"alert_enabled={watchlist_item.alert_enabled}"
                    )
                
                # If no valid reference, allow the signal (should not be blocked)
                if not has_valid_reference:
                    logger.warning(
                        f"⚠️ {symbol} SELL: Throttle check returned False but no valid price reference exists. "
                        f"Allowing signal anyway. Reason: {sell_reason}"
                    )
                    # Override the throttle decision - allow the signal
                    sell_allowed = True
                    throttle_sell_reason = "No previous same-side signal recorded - allowing first signal"
                    # Record the signal event
                    try:
                        emit_reason = "First signal for this side/strategy (no previous reference)"
                        record_signal_event(
                            db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="SELL",
                            price=current_price,
                            source="signal_check",
                            emit_reason=emit_reason,
                        )
                        logger.debug(f"📝 Recorded SELL signal event for {symbol} at {current_price} (strategy: {strategy_key}) - first signal")
                    except Exception as record_err:
                        logger.warning(f"Failed to record SELL signal event for {symbol} (non-blocking): {record_err}")
                else:
                    # Build blocked message with reference price and timestamp (only if we have a valid reference)
                    # FIX: Include "SELL SIGNAL" text so blocked messages match monitoring filter
                    blocked_msg_parts = [f"🚫 BLOQUEADO: SELL SIGNAL {symbol} - {sell_reason}"]
                    
                    # Add reference price and timestamp (we know they exist from the check above)
                    ref_price = last_sell_snapshot.price
                    ref_timestamp = last_sell_snapshot.timestamp
                    # Format timestamp in a readable format
                    if ref_timestamp:
                        if ref_timestamp.tzinfo is None:
                            ref_timestamp = ref_timestamp.replace(tzinfo=timezone.utc)
                        ref_time_str = ref_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
                        # Format price with appropriate decimals based on value
                        if ref_price >= 1000:
                            price_str = f"${ref_price:,.2f}"
                        elif ref_price >= 1:
                            price_str = f"${ref_price:.2f}"
                        elif ref_price >= 0.01:
                            price_str = f"${ref_price:.4f}"
                        else:
                            price_str = f"${ref_price:.8f}"
                        blocked_msg_parts.append(f"Precio de referencia: {price_str} (último mensaje exitoso: {ref_time_str})")
                    else:
                        # Format price with appropriate decimals based on value
                        if ref_price >= 1000:
                            price_str = f"${ref_price:,.2f}"
                        elif ref_price >= 1:
                            price_str = f"${ref_price:.2f}"
                        elif ref_price >= 0.01:
                            price_str = f"${ref_price:.4f}"
                        else:
                            price_str = f"${ref_price:.8f}"
                        blocked_msg_parts.append(f"Precio de referencia: {price_str}")
                    
                    blocked_msg = " | ".join(blocked_msg_parts)
                    logger.info(blocked_msg)
                    self._log_signal_rejection(
                        symbol,
                        "SELL",
                        self._classify_throttle_reason(sell_reason),
                        {"throttle_reason": sell_reason},
                    )
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        from app.utils.decision_reason import make_skip
                        import uuid

                        correlation_id = str(uuid.uuid4())
                        reason_code = self._map_throttle_reason_code(sell_reason)
                        decision_reason = make_skip(
                            reason_code=reason_code,
                            message=f"Alert blocked for {symbol} SELL: {sell_reason}",
                            context={
                                "symbol": symbol,
                                "price": current_price,
                                "reference_price": ref_price if ref_price else None,
                                "reference_timestamp": ref_timestamp.isoformat() if ref_timestamp else None,
                                "throttle_reason": sell_reason,
                                "strategy_key": strategy_key,
                            },
                            source="throttle",
                            correlation_id=correlation_id,
                        )

                        add_telegram_message(
                            blocked_msg,
                            symbol=symbol,
                            blocked=True,
                            throttle_status="BLOCKED",
                            throttle_reason=sell_reason,
                            decision_type=decision_reason.decision_type.value,
                            reason_code=decision_reason.reason_code,
                            reason_message=decision_reason.reason_message,
                            context_json=decision_reason.context,
                            correlation_id=decision_reason.correlation_id,
                        )
                    except Exception:
                        pass
                    # CRITICAL: Do NOT update reference price when blocked - it must remain the last successful (non-blocked) message price
                    # The price reference should only be updated when a message is actually sent successfully
                # NOTE: Do NOT record signal event when blocked - last_price should only update when alert is actually sent
                # FIX: Do NOT set sell_signal = False when throttled - allow alert to be created with blocked status
                # This ensures SELL alerts are always created/persisted (same as BUY), only duplicates are prevented
                # The alert section will check sell_allowed and pass throttle_status to send_sell_signal()
                # send_sell_signal() will handle duplicate detection and mark as blocked if needed
                if current_state == "SELL":
                    current_state = "WAIT"
        
        # ========================================================================
        # ENVÍO DE ALERTAS: Enviar alerta SIEMPRE que buy_signal=True, alert_enabled=True, y buy_alert_enabled=True
        # IMPORTANTE: Hacer esto ANTES de toda la lógica de órdenes para garantizar que las alertas
        # se envíen incluso si hay algún return temprano en la lógica de órdenes
        # CRITICAL: Check both alert_enabled (master switch) AND buy_alert_enabled (BUY-specific flag)
        # ========================================================================
        # CRITICAL: Always read flags from DB (watchlist_item is already refreshed from DB)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', False)
        
        # Log alert decision with all flags for clarity
        if buy_signal:
            alert_enabled = watchlist_item.alert_enabled
            if alert_enabled and buy_alert_enabled:
                logger.info(
                    f"🔍 {symbol} BUY alert decision: buy_signal=True, "
                    f"alert_enabled={alert_enabled}, buy_alert_enabled={buy_alert_enabled}, sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)} → "
                    f"DECISION: SENT (both flags enabled)"
                )
            else:
                skip_reason = []
                if not alert_enabled:
                    skip_reason.append("alert_enabled=False")
                if not buy_alert_enabled:
                    skip_reason.append("buy_alert_enabled=False")
                logger.info(
                    "[GATE] symbol=%s gate=buy_alert_enabled decision=BLOCK reason=%s evaluation_id=%s",
                    symbol,
                    ",".join(skip_reason),
                    evaluation_id,
                )
                block_reason = "ALERT_DISABLED" if not alert_enabled else "SIDE_DISABLED"
                self._upsert_watchlist_signal_state(
                    db,
                    symbol=normalized_symbol,
                    alert_status="BLOCKED",
                    alert_block_reason=block_reason,
                    last_alert_at_utc=datetime.now(timezone.utc),
                    correlation_id=evaluation_id,
                )
                logger.info(
                    f"🔍 {symbol} BUY alert decision: buy_signal=True, "
                    f"alert_enabled={alert_enabled}, buy_alert_enabled={buy_alert_enabled}, sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)} → "
                    f"DECISION: SKIPPED ({', '.join(skip_reason)})"
                )
                self._log_signal_rejection(
                    symbol,
                    "BUY",
                    "DISABLED_BUY_SELL_FLAG",
                    {"alert_enabled": alert_enabled, "buy_alert_enabled": buy_alert_enabled},
                )
        
        # CRITICAL: Verify BOTH alert_enabled (master switch) AND buy_alert_enabled (BUY-specific) before processing
        if buy_signal and watchlist_item.alert_enabled and buy_alert_enabled:
            logger.info(f"🟢 NEW BUY signal detected for {symbol} - processing alert (alert_enabled=True, buy_alert_enabled=True)")
            
            # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
            # This ensures only one thread can check and send an alert at a time
            # IMPORTANT: Set lock FIRST, before any checks, to prevent race conditions
            lock_key = f"{symbol}_BUY"
            lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
            # Use time module (already imported at top of file)
            current_time = time.time()
            
            # Check if we're already processing an alert for this symbol+side
            should_skip_alert = False
            if lock_key in self.alert_sending_locks:
                lock_timestamp = self.alert_sending_locks[lock_key]
                lock_age = current_time - lock_timestamp
                if lock_age < lock_timeout:
                    remaining_seconds = lock_timeout - lock_age
                    logger.debug(f"🔒 Alert sending already in progress for {symbol} BUY (lock age: {lock_age:.2f}s, remaining: {remaining_seconds:.2f}s), skipping duplicate check")
                    should_skip_alert = True
                else:
                    # Lock expired, remove it
                    logger.debug(f"🔓 Expired lock removed for {symbol} BUY (age: {lock_age:.2f}s)")
                    del self.alert_sending_locks[lock_key]
            
            if not should_skip_alert:
                # Set lock IMMEDIATELY to prevent other cycles from processing the same alert
                self.alert_sending_locks[lock_key] = current_time
                logger.debug(f"🔒 Lock acquired for {symbol} BUY alert")
                
                # Use the price from snapshot (saved before record_signal_event) for consistent price change calculation
                # This ensures "Cambio desde última alerta" matches the price change shown in the trigger reason
                # Fallback to database query if snapshot price not available (shouldn't happen, but safe fallback)
                prev_buy_price: Optional[float] = prev_buy_price_from_snapshot if prev_buy_price_from_snapshot is not None else self._get_last_alert_price(symbol, "BUY", db)
                
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
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        trade_status="BLOCKED",
                        trade_block_reason="OPEN_ORDERS_LIMIT",
                        last_trade_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
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
                        buy_alert_enabled = getattr(fresh_check, 'buy_alert_enabled', False)
                        logger.debug(f"🔄 Última verificación para {symbol}: alert_enabled={fresh_check.alert_enabled}, buy_alert_enabled={buy_alert_enabled}")
                except Exception as e:
                    logger.warning(f"Error en última verificación de flags para {symbol}: {e}")
                
                if not watchlist_item.alert_enabled:
                    blocked_msg = (
                        f"🚫 BLOQUEADO: {symbol} - Las alertas están deshabilitadas para este símbolo "
                        f"(alert_enabled=False). No se enviará alerta aunque se detectó señal BUY. "
                        f"Para habilitar alertas, active 'alert_enabled' en la configuración del símbolo."
                    )
                    logger.error(blocked_msg)
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="ALERT_DISABLED",
                        last_alert_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
                    )
                    # Register blocked message
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    # Remove locks and continue (don't return - continue with order logic)
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                elif not buy_alert_enabled:
                    blocked_msg = (
                        f"🚫 BLOQUEADO: {symbol} - Las alertas de compra (BUY) están deshabilitadas "
                        f"para este símbolo (buy_alert_enabled=False). No se enviará alerta BUY aunque "
                        f"se detectó señal BUY y alert_enabled=True. Para habilitar alertas de compra, "
                        f"active 'buy_alert_enabled' en la configuración del símbolo."
                    )
                    logger.warning(blocked_msg)
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="SIDE_DISABLED",
                        last_alert_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
                    )
                    # Register blocked message
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    # Remove locks and continue (don't return - continue with order logic)
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                elif watchlist_item.trade_enabled and (not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0):
                    # CRITICAL: Validate trade_amount_usd BEFORE sending signal if trade_enabled=True
                    # If trade is enabled, we must have a valid trade_amount_usd configured
                    # Otherwise, the signal should NOT be sent (it would fail to create order)
                    blocked_msg = (
                        f"🚫 BLOQUEADO: {symbol} - El campo 'Amount USD' no está configurado para este símbolo "
                        f"(trade_enabled=True pero trade_amount_usd no está configurado). "
                        f"No se enviará alerta BUY porque la orden no puede ser creada sin 'Amount USD'. "
                        f"Para habilitar alertas y órdenes automáticas, configure el campo 'Amount USD' "
                        f"en la Watchlist del Dashboard."
                    )
                    logger.warning(blocked_msg)
                    # Register blocked message
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    # Remove locks and continue (don't return - continue with order logic)
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                else:
                    # Check portfolio value limit: Skip orders if portfolio_value > 3x trade_amount_usd
                    # IMPORTANT: Alerts are ALWAYS sent, but orders are skipped when limit is exceeded
                    # NOTE: We only log here - monitoring entry is created in order creation path to avoid duplicates
                    trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                    limit_value = 3 * trade_amount_usd
                    order_skipped_due_to_limit = False
                    try:
                        portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                        if portfolio_value > limit_value:
                            order_skipped_due_to_limit = True
                            logger.warning(
                                f"⚠️ Portfolio limit exceeded for {symbol}: "
                                f"portfolio_value=${portfolio_value:.2f} > limit=${limit_value:.2f}. "
                                f"Alert will be sent, but order will be skipped. "
                                f"Monitoring entry will be created in order creation path."
                            )
                            self._upsert_watchlist_signal_state(
                                db,
                                symbol=normalized_symbol,
                                trade_status="BLOCKED",
                                trade_block_reason="PORTFOLIO_LIMIT",
                                last_trade_at_utc=datetime.now(timezone.utc),
                                correlation_id=evaluation_id,
                            )
                            # Continue to send alert - don't set should_send = False
                            # The order creation logic will check this flag and skip order creation
                            # Monitoring entry will be created there to avoid duplicates
                        else:
                            logger.debug(
                                f"✅ Portfolio value check passed for {symbol}: "
                                f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}"
                            )
                    except Exception as portfolio_check_err:
                        logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with alert...")
                        # On error, continue (don't block alerts if we can't calculate portfolio value)
                    
                    # NOTE: Throttling already checked by should_emit_signal (passed if we reached here)
                    # Since buy_allowed was True, we proceed directly to send the alert
                    logger.info(
                        f"🔍 {symbol} BUY alert ready to send (throttling already verified by should_emit_signal)"
                    )
                    self._log_signal_accept(
                        symbol,
                        "BUY",
                        {
                            "price": current_price,
                            "trade_enabled": getattr(watchlist_item, "trade_enabled", None),
                        },
                    )
                    
                    # Send Telegram alert (throttling already verified by should_emit_signal)
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
                        alert_origin = get_runtime_origin()
                        # Explicitly pass origin to ensure alerts are sent
                        # Use get_runtime_origin() to get current runtime (should be "AWS" in production)
                        alert_origin = get_runtime_origin()
                        result = emit_alert(
                            db=db,
                            symbol=symbol,
                            side="BUY",
                            reason=reason_text,
                            price=current_price,
                            context={
                                "price": current_price,
                                "previous_price": prev_buy_price,
                                "strategy": strategy_display,
                                "risk": risk_display,
                            },
                            strategy_type=strategy_display,
                            risk_approach=risk_display,
                            price_variation=price_variation,
                            throttle_status="SENT",
                            throttle_reason=throttle_buy_reason or buy_reason,
                            evaluation_id=evaluation_id,
                            strategy_key=strategy_key,
                            thresholds=threshold_context,
                        )
                        # PHASE 0: Structured logging for Telegram send attempt
                        message_id = None
                        signal_id = None  # Telegram message ID for orchestrator
                        if isinstance(result, dict):
                            message_id = result.get("message_id")
                            signal_id = result.get("message_id")  # Use message_id as signal_id
                        elif hasattr(result, 'message_id'):
                            message_id = result.message_id
                            signal_id = result.message_id
                        elif result is True:
                            # Fallback: query for most recent TelegramMessage
                            try:
                                from app.models.telegram_message import TelegramMessage
                                recent_msg = db.query(TelegramMessage).filter(
                                    TelegramMessage.symbol == symbol,
                                    TelegramMessage.message.like("%BUY SIGNAL%"),
                                    TelegramMessage.blocked == False,
                                ).order_by(TelegramMessage.timestamp.desc()).first()
                                if recent_msg:
                                    signal_id = recent_msg.id
                            except Exception as query_err:
                                logger.warning(f"Could not query for signal_id: {query_err}")
                        
                        # Alerts must never be blocked after conditions are met (guardrail compliance)
                        # If send_buy_signal returns False, log as error but do not treat as block
                        if result is False:
                            logger.error(
                                f"[EVAL_{evaluation_id}] {symbol} BUY Telegram send FAILED | "
                                f"result=False | "
                                f"reason={reason_text}"
                            )
                            logger.error(
                                f"❌ Failed to send BUY alert for {symbol} (send_buy_signal returned False). "
                                f"This should not happen when conditions are met. Check telegram_notifier."
                            )
                            self._upsert_watchlist_signal_state(
                                db,
                                symbol=normalized_symbol,
                                alert_status="BLOCKED",
                                alert_block_reason="TELEGRAM_ERROR",
                                last_alert_at_utc=now_utc,
                                correlation_id=evaluation_id,
                            )
                        else:
                            # Message already registered in send_buy_signal as sent
                            logger.info(
                                f"[EVAL_{evaluation_id}] {symbol} BUY Telegram send SUCCESS | "
                                f"message_id={message_id or 'N/A'} | "
                                f"signal_id={signal_id or 'N/A'} | "
                                f"price=${current_price:.4f} | "
                                f"reason={reason_text}"
                            )
                            # E) Deep decision-grade logging
                            logger.info(
                                f"[TELEGRAM_SEND] {symbol} BUY status=SUCCESS message_id={message_id or 'N/A'} "
                                f"channel={telegram_notifier.chat_id} origin={alert_origin}"
                            )
                            logger.info(
                                f"✅ BUY alert SENT for {symbol}: alert_enabled={watchlist_item.alert_enabled}, "
                                f"buy_alert_enabled={buy_alert_enabled}, sell_alert_enabled={getattr(watchlist_item, 'sell_alert_enabled', False)} - {reason_text}"
                            )
                            buy_alert_sent_successfully = True  # Mark alert as sent successfully
                            self._upsert_watchlist_signal_state(
                                db,
                                symbol=normalized_symbol,
                                alert_status="SENT",
                                alert_block_reason=None,
                                last_alert_at_utc=now_utc,
                                correlation_id=evaluation_id,
                            )
                            self._log_pipeline_stage(
                                stage="ALERT_CREATED",
                                symbol=normalized_symbol,
                                strategy_key=strategy_key,
                                decision="BUY",
                                last_price=current_price,
                                timestamp=now_utc.isoformat(),
                                correlation_id=evaluation_id,
                                signal_id=str(signal_id) if signal_id is not None else None,
                            )
                            self._log_signal_accept(
                                symbol,
                                "BUY",
                                {"telegram": "sent", "reason": reason_text},
                            )
                            
                            # ========================================================================
                            # INVARIANT ENFORCEMENT: Call orchestrator immediately after signal sent
                            # ========================================================================
                            # If signal is sent, order MUST be attempted immediately (only dedup can block)
                            try:
                                from app.services.signal_order_orchestrator import create_order_intent, update_order_intent_status
                                from app.api.routes_monitoring import update_telegram_message_decision_trace
                                from app.utils.decision_reason import make_skip, make_fail, make_execute, ReasonCode
                                import uuid as uuid_module
                                order_intent = None
                                intent_status = None

                                # Create order intent (atomic deduplication)
                                # Use the sent message content for fallback idempotency key
                                sent_message_content = f"BUY SIGNAL {symbol} {current_price} {reason_text}"

                                if not signal_id:
                                    logger.warning(
                                        f"[ORCHESTRATOR] {symbol} BUY Signal missing signal_id; proceeding with content-based idempotency"
                                    )
                                else:
                                    logger.info(f"[ORCHESTRATOR] {symbol} BUY Signal sent - triggering orchestrator (signal_id={signal_id})")
                                    self._schedule_missing_intent_check(signal_id, symbol, "BUY")

                                order_intent, intent_status = create_order_intent(
                                    db=db,
                                    signal_id=signal_id,
                                    symbol=normalized_symbol,
                                    side="BUY",
                                    message_content=sent_message_content,
                                    strategy_key=strategy_key,
                                )
                                
                                if intent_status == "DEDUP_SKIPPED":
                                    # Duplicate signal - skip order
                                    logger.warning(f"[ORCHESTRATOR] {symbol} BUY DEDUP_SKIPPED - Duplicate signal detected")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="BLOCKED",
                                        trade_block_reason="DUPLICATE",
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                    self._log_pipeline_stage(
                                        stage="BUY_BLOCKED",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        signal_id=str(signal_id) if signal_id is not None else None,
                                        reason="IDEMPOTENCY_BLOCKED",
                                    )
                                    decision_reason = make_skip(
                                        reason_code=ReasonCode.IDEMPOTENCY_BLOCKED.value,
                                        message=f"Duplicate signal detected for {symbol} BUY. Order was already attempted (idempotency_key already exists).",
                                        context={"symbol": symbol, "signal_id": signal_id},
                                        source="orchestrator",
                                    )
                                    update_telegram_message_decision_trace(
                                        db=db,
                                        symbol=symbol,
                                        message_pattern="BUY SIGNAL",
                                        decision_type="SKIPPED",
                                        reason_code=decision_reason.reason_code,
                                        reason_message=decision_reason.reason_message,
                                        context_json=decision_reason.context,
                                        correlation_id=str(uuid_module.uuid4()),
                                    )
                                elif intent_status == "ORDER_BLOCKED_LIVE_TRADING":
                                    # LIVE_TRADING=false - order blocked
                                    logger.info(f"[ORCHESTRATOR] {symbol} BUY ORDER_BLOCKED_LIVE_TRADING - Signal sent but order blocked")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="BLOCKED",
                                        trade_block_reason="TRADE_DISABLED",
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                    self._log_pipeline_stage(
                                        stage="BUY_BLOCKED",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        signal_id=str(signal_id) if signal_id is not None else None,
                                        reason="ORDER_BLOCKED_LIVE_TRADING",
                                    )
                                    decision_reason = make_skip(
                                        reason_code="ORDER_BLOCKED_LIVE_TRADING",
                                        message=f"Order blocked: LIVE_TRADING is disabled. Signal was sent but no order will be placed.",
                                        context={"symbol": symbol, "live_trading": False},
                                        source="orchestrator",
                                    )
                                    update_telegram_message_decision_trace(
                                        db=db,
                                        symbol=symbol,
                                        message_pattern="BUY SIGNAL",
                                        decision_type="SKIPPED",
                                        reason_code=decision_reason.reason_code,
                                        reason_message=decision_reason.reason_message,
                                        context_json=decision_reason.context,
                                        correlation_id=str(uuid_module.uuid4()),
                                    )
                                elif intent_status == "PENDING" and order_intent:
                                    # Order intent created - attempt order placement (bypassing eligibility checks)
                                    logger.info(f"[ORCHESTRATOR] {symbol} BUY Order intent created (id={order_intent.id}) - Attempting order placement")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="SUBMITTED",
                                        trade_block_reason=None,
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                    self._log_pipeline_stage(
                                        stage="BUY_ELIGIBLE_CHECK",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        signal_id=str(signal_id) if signal_id is not None else None,
                                        reason="OK",
                                    )
                                    self._log_pipeline_stage(
                                        stage="BUY_ORDER_SUBMITTED",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        signal_id=str(signal_id) if signal_id is not None else None,
                                    )
                                
                                    # Call minimal order placement function (NO eligibility checks)
                                    # Note: Running async function from sync context using new event loop
                                    try:
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        try:
                                            order_result = loop.run_until_complete(
                                                self._place_order_from_signal(
                                                    db=db,
                                                    symbol=normalized_symbol,
                                                    side="BUY",
                                                    watchlist_item=watchlist_item,
                                                    current_price=current_price,
                                                    source="orchestrator",
                                                )
                                            )
                                        finally:
                                            loop.close()
                                        
                                        if "error" in order_result:
                                            # Order creation failed - strict failure reporting (Step 4)
                                            error_msg = order_result.get("message") or order_result.get("error", "Unknown error")
                                            logger.error(f"[ORCHESTRATOR] {symbol} BUY Order creation failed: {error_msg}")
                                            self._upsert_watchlist_signal_state(
                                                db,
                                                symbol=normalized_symbol,
                                                trade_status="BLOCKED",
                                                trade_block_reason="EXCHANGE_ERROR",
                                                last_trade_at_utc=now_utc,
                                                correlation_id=evaluation_id,
                                            )
                                            self._log_pipeline_stage(
                                                stage="BUY_ORDER_RESPONSE",
                                                symbol=normalized_symbol,
                                                strategy_key=strategy_key,
                                                decision="BUY",
                                                last_price=current_price,
                                                timestamp=now_utc.isoformat(),
                                                correlation_id=evaluation_id,
                                                signal_id=str(signal_id) if signal_id is not None else None,
                                                reason=f"FAILED:{error_msg}",
                                            )
                                            update_order_intent_status(
                                                db=db,
                                                order_intent_id=order_intent.id,
                                                status="ORDER_FAILED",
                                                error_message=error_msg,
                                            )
                                            
                                            # Classify error for strict reporting (Step 4)
                                            from app.utils.decision_reason import classify_exchange_error
                                            reason_code = classify_exchange_error(error_msg)
                                            
                                            decision_reason = make_fail(
                                                reason_code=reason_code,
                                                message=f"Order creation failed for {symbol} BUY: {error_msg}",
                                                context={
                                                    "symbol": symbol,
                                                    "error": error_msg,
                                                    "error_type": order_result.get("error_type", "exchange_rejected"),
                                                },
                                                source="orchestrator",
                                                exchange_error=error_msg,
                                            )
                                            update_telegram_message_decision_trace(
                                                db=db,
                                                symbol=symbol,
                                                message_pattern="BUY SIGNAL",
                                                decision_type="FAILED",
                                                reason_code=decision_reason.reason_code,
                                                reason_message=decision_reason.reason_message,
                                                context_json=decision_reason.context,
                                                exchange_error_snippet=decision_reason.exchange_error,
                                                correlation_id=str(uuid_module.uuid4()),
                                            )
                                            
                                            # Send Telegram failure message (required - Step 4)
                                            try:
                                                from app.services.telegram_notifier import telegram_notifier
                                                telegram_notifier.send_message(
                                                    f"❌ <b>ORDER FAILED</b>\n\n"
                                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                                    f"🔄 Side: BUY\n"
                                                    f"❌ Error: {error_msg}\n"
                                                    f"📋 Reason Code: {reason_code}\n\n"
                                                    f"<i>Signal was sent but order creation failed.</i>"
                                                )
                                            except Exception as telegram_err:
                                                logger.warning(f"Failed to send Telegram failure message: {telegram_err}")
                                            try:
                                                from app.api.routes_monitoring import add_telegram_message
                                                add_telegram_message(
                                                    f"❌ ORDER FAILED | {symbol} BUY | {error_msg} | reason_code={reason_code}",
                                                    symbol=symbol,
                                                    blocked=False,
                                                    decision_type="FAILED",
                                                    reason_code=reason_code,
                                                    reason_message=error_msg,
                                                )
                                            except Exception as store_err:
                                                logger.debug(f"Failed to store ORDER FAILED message: {store_err}")
                                        else:
                                            # Order created successfully
                                            order_id = order_result.get("order_id")
                                            exchange_order_id = order_result.get("exchange_order_id")
                                            self._upsert_watchlist_signal_state(
                                                db,
                                                symbol=normalized_symbol,
                                                trade_status="SUBMITTED",
                                                trade_block_reason=None,
                                                last_trade_at_utc=now_utc,
                                                correlation_id=evaluation_id,
                                            )
                                            logger.info(f"[ORCHESTRATOR] {symbol} BUY Order created successfully: order_id={order_id}, exchange_order_id={exchange_order_id}")
                                            self._log_pipeline_stage(
                                                stage="BUY_ORDER_RESPONSE",
                                                symbol=normalized_symbol,
                                                strategy_key=strategy_key,
                                                decision="BUY",
                                                last_price=current_price,
                                                timestamp=now_utc.isoformat(),
                                                correlation_id=evaluation_id,
                                                signal_id=str(signal_id) if signal_id is not None else None,
                                                reason="SUCCESS",
                                            )
                                            update_order_intent_status(
                                                db=db,
                                                order_intent_id=order_intent.id,
                                                status="ORDER_PLACED",
                                                order_id=exchange_order_id or order_id,
                                            )
                                            decision_reason = make_execute(
                                                reason_code=ReasonCode.EXEC_ORDER_PLACED.value,
                                                message=f"Order created successfully for {symbol}. order_id={exchange_order_id or order_id}",
                                                context={
                                                    "symbol": symbol,
                                                    "order_id": order_id,
                                                    "exchange_order_id": exchange_order_id,
                                                },
                                                source="orchestrator",
                                            )
                                            update_telegram_message_decision_trace(
                                                db=db,
                                                symbol=symbol,
                                                message_pattern="BUY SIGNAL",
                                                decision_type="EXECUTED",
                                                reason_code=decision_reason.reason_code,
                                                reason_message=decision_reason.reason_message,
                                                context_json=decision_reason.context,
                                                correlation_id=str(uuid_module.uuid4()),
                                            )
                                    except Exception as order_err:
                                        # Order creation exception - strict failure reporting (Step 4)
                                        error_msg = str(order_err)[:500]
                                        logger.error(f"[ORCHESTRATOR] {symbol} BUY Order creation exception: {order_err}", exc_info=True)
                                        self._upsert_watchlist_signal_state(
                                            db,
                                            symbol=normalized_symbol,
                                            trade_status="BLOCKED",
                                            trade_block_reason="EXCHANGE_ERROR",
                                            last_trade_at_utc=now_utc,
                                            correlation_id=evaluation_id,
                                        )
                                        self._log_pipeline_stage(
                                            stage="BUY_ORDER_RESPONSE",
                                            symbol=normalized_symbol,
                                            strategy_key=strategy_key,
                                            decision="BUY",
                                            last_price=current_price,
                                            timestamp=now_utc.isoformat(),
                                            correlation_id=evaluation_id,
                                            signal_id=str(signal_id) if signal_id is not None else None,
                                            reason=f"FAILED:{error_msg}",
                                        )
                                        update_order_intent_status(
                                            db=db,
                                            order_intent_id=order_intent.id,
                                            status="ORDER_FAILED",
                                            error_message=error_msg,
                                        )
                                        
                                        # Classify error for strict reporting (Step 4)
                                        from app.utils.decision_reason import classify_exchange_error
                                        reason_code = classify_exchange_error(error_msg)
                                        
                                        decision_reason = make_fail(
                                            reason_code=reason_code,
                                            message=f"Order creation failed for {symbol} BUY: {error_msg}",
                                            context={
                                                "symbol": symbol,
                                                "error": error_msg,
                                                "error_type": "exception",
                                            },
                                            source="orchestrator",
                                            exchange_error=error_msg,
                                        )
                                        update_telegram_message_decision_trace(
                                            db=db,
                                            symbol=symbol,
                                            message_pattern="BUY SIGNAL",
                                            decision_type="FAILED",
                                            reason_code=decision_reason.reason_code,
                                            reason_message=decision_reason.reason_message,
                                            context_json=decision_reason.context,
                                            exchange_error_snippet=decision_reason.exchange_error,
                                            correlation_id=str(uuid_module.uuid4()),
                                        )
                                        
                                        # Send Telegram failure message (required - Step 4)
                                        try:
                                            from app.services.telegram_notifier import telegram_notifier
                                            telegram_notifier.send_message(
                                                f"❌ <b>ORDER FAILED</b>\n\n"
                                                f"📊 Symbol: <b>{symbol}</b>\n"
                                                f"🔄 Side: BUY\n"
                                                f"❌ Error: {error_msg}\n"
                                                f"📋 Reason Code: {reason_code}\n\n"
                                                f"<i>Signal was sent but order creation failed.</i>"
                                            )
                                        except Exception as telegram_err:
                                            logger.warning(f"Failed to send Telegram failure message: {telegram_err}")
                                        try:
                                            from app.api.routes_monitoring import add_telegram_message
                                            add_telegram_message(
                                                f"❌ ORDER FAILED | {symbol} BUY | {error_msg} | reason_code={reason_code}",
                                                symbol=symbol,
                                                blocked=False,
                                                decision_type="FAILED",
                                                reason_code=reason_code,
                                                reason_message=error_msg,
                                            )
                                        except Exception as store_err:
                                            logger.debug(f"Failed to store ORDER FAILED message: {store_err}")
                            except Exception as orchestrator_err:
                                # Orchestrator error - log but don't fail the signal
                                logger.error(f"[ORCHESTRATOR] {symbol} BUY Orchestrator error: {orchestrator_err}", exc_info=True)
                            # CRITICAL: Record signal event in BD ONLY after successful send to prevent duplicate alerts
                            # This ensures that if multiple calls happen simultaneously, only the first one will update the state
                            try:
                                logger.info(f"📝 Recording signal event for {symbol} BUY at {current_price} (strategy: {strategy_key})")
                                # Build comprehensive reason
                                # CRITICAL: Do NOT include buy_reason if it contains "THROTTLED" or "BLOCKED"
                                # because this message was successfully sent, so it should not have throttled reasons
                                emit_reason_parts = []
                                if buy_reason and 'throttled' not in buy_reason.lower() and 'blocked' not in buy_reason.lower():
                                    emit_reason_parts.append(buy_reason)
                                # CANONICAL: BUY and SELL are independent - no side change reset logic
                                if last_buy_snapshot is None or last_buy_snapshot.timestamp is None:
                                    emit_reason_parts.append("First signal for this side/strategy")
                                emit_reason = " | ".join(emit_reason_parts) if emit_reason_parts else "ALERT_SENT"
                                record_signal_event(
                                    db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="BUY",
                                    price=current_price,
                                    source="alert",
                                    emit_reason=emit_reason,
                                    config_hash=config_hash_current,
                                )
                                logger.info(f"✅ Signal event recorded successfully for {symbol} BUY")
                                buy_state_recorded = True
                            except Exception as state_err:
                                logger.error(f"❌ Failed to persist BUY throttle state for {symbol}: {state_err}", exc_info=True)
                    except Exception as e:
                        logger.error(f"❌ Failed to send Telegram BUY alert for {symbol}: {e}", exc_info=True)
                        # If sending failed, do NOT update the state - allow retry on next cycle
                        # Remove lock to allow retry
                        if lock_key in self.alert_sending_locks:
                            del self.alert_sending_locks[lock_key]
                    
                    # Always remove lock when done (if not already removed)
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
            from sqlalchemy import or_, func
            COOLDOWN_SECONDS = 300  # 5 minutes cooldown (persistent, DB-based)
            recent_orders_threshold = datetime.now(timezone.utc) - timedelta(seconds=COOLDOWN_SECONDS)
            
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
            
            # CRITICAL FIX: Only use price from OPEN orders for price change check
            # If there are no open orders, we should allow new orders without price change check
            # Do NOT use last_order_price from memory (which may be from closed orders)
            effective_last_price = db_last_order_price  # Only use price from open orders
            
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
                f"effective_last_price=${effective_last_price:.4f} (only from open orders)"
            )
            
            # Check if we're currently creating an order for this symbol (lock check) - BEFORE any order creation logic
            # Use time module (already imported at top of file)
            current_time = time.time()
            if symbol in self.order_creation_locks:
                lock_time = self.order_creation_locks[symbol]
                if current_time - lock_time < self.ORDER_CREATION_LOCK_SECONDS:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} has active order creation lock "
                        f"({current_time - lock_time:.1f}s ago). Skipping to prevent duplicate orders."
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.ORDER_CREATION_LOCK.value,
                        message=f"Order creation lock active for {symbol}. Lock set {current_time - lock_time:.1f}s ago.",
                        context={
                            "symbol": symbol,
                            "lock_age_seconds": current_time - lock_time,
                            "lock_timeout_seconds": self.ORDER_CREATION_LOCK_SECONDS,
                            "price": current_price,
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="ORDER_CREATION_LOCK",
                        decision_reason=decision_reason,
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
            blocked_by_limits = False
            
            # FIRST CHECK: Block if max open orders limit reached (most restrictive).
            # Use the UNIFIED count so that per-symbol logic matches global protection.
            if unified_open_positions >= self.MAX_OPEN_ORDERS_PER_SYMBOL:
                logger.warning(
                    f"🚫 BLOCKED: {symbol} has reached maximum open orders limit "
                    f"({unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}). Skipping new order."
                )
                # Create DecisionReason for SKIP
                from app.utils.decision_reason import make_skip, ReasonCode
                import uuid
                correlation_id = str(uuid.uuid4())
                decision_reason = make_skip(
                    reason_code=ReasonCode.MAX_OPEN_TRADES_REACHED.value,
                    message=f"Maximum open orders reached for {symbol}. {unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}.",
                    context={
                        "symbol": symbol,
                        "open_positions": unified_open_positions,
                        "max_open_orders": self.MAX_OPEN_ORDERS_PER_SYMBOL,
                        "price": current_price,
                    },
                    source="guardrail",
                    correlation_id=correlation_id,
                )
                logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                # Emit TRADE_BLOCKED event with DecisionReason
                _emit_lifecycle_event(
                    db=db,
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side="BUY",
                    price=current_price,
                    event_type="TRADE_BLOCKED",
                    event_reason="MAX_OPEN_ORDERS_REACHED",
                    decision_reason=decision_reason,
                )
                # CRITICAL: Update the original BUY SIGNAL message with decision tracing
                if buy_alert_sent_successfully:
                    try:
                        from app.api.routes_monitoring import update_telegram_message_decision_trace
                        update_telegram_message_decision_trace(
                            db=db,
                            symbol=symbol,
                            message_pattern="BUY SIGNAL",
                            decision_type="SKIPPED",
                            reason_code=decision_reason.reason_code,
                            reason_message=decision_reason.reason_message,
                            context_json=decision_reason.context,
                            correlation_id=decision_reason.correlation_id,
                        )
                    except Exception as update_err:
                        logger.warning(f"Failed to update original BUY SIGNAL message for {symbol}: {update_err}")
                blocked_by_limits = True
            # SECOND CHECK: Block if there are recent orders (within 5 minutes) - prevents consecutive orders
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
                    if DEBUG_TRADING:
                        logger.info(f"[DEBUG_TRADING] {symbol} BUY: COOLDOWN BLOCKED - {time_since_last:.1f} minutes since last order (threshold: 5 minutes)")
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                        message=f"Recent orders cooldown active for {symbol}. Found {len(recent_buy_orders)} recent BUY order(s) within 5 minutes (most recent: {time_since_last:.1f} minutes ago).",
                        context={
                            "symbol": symbol,
                            "recent_orders_count": len(recent_buy_orders),
                            "time_since_last_minutes": time_since_last,
                            "cooldown_minutes": 5,
                            "most_recent_order_id": most_recent_order.exchange_order_id,
                            "price": current_price,
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="RECENT_ORDERS_COOLDOWN",
                        decision_reason=decision_reason,
                    )
                    # CRITICAL: Update the original BUY SIGNAL message with decision tracing
                    if buy_alert_sent_successfully:
                        try:
                            from app.api.routes_monitoring import update_telegram_message_decision_trace
                            update_telegram_message_decision_trace(
                                db=db,
                                symbol=symbol,
                                message_pattern="BUY SIGNAL",
                                decision_type="SKIPPED",
                                reason_code=decision_reason.reason_code,
                                reason_message=decision_reason.reason_message,
                                context_json=decision_reason.context,
                                correlation_id=decision_reason.correlation_id,
                            )
                        except Exception as update_err:
                            logger.warning(f"Failed to update original BUY SIGNAL message for {symbol}: {update_err}")
                else:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} has {len(recent_buy_orders)} recent BUY order(s) "
                        f"(order_id: {most_recent_order.exchange_order_id}, but timestamp is None). "
                        f"Cooldown period active - skipping new order to prevent consecutive orders."
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                        message=f"Recent orders cooldown active for {symbol}. Found {len(recent_buy_orders)} recent BUY order(s) (timestamp unknown).",
                        context={
                            "symbol": symbol,
                            "recent_orders_count": len(recent_buy_orders),
                            "most_recent_order_id": most_recent_order.exchange_order_id,
                            "cooldown_minutes": 5,
                            "price": current_price,
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="RECENT_ORDERS_COOLDOWN",
                        decision_reason=decision_reason,
                    )
                blocked_by_limits = True

            # ORDERS: Trade execution is independent of alert sending
            # Trade should NOT be blocked by alert throttle/cooldown
            # Only block by order limits and cooldown (MAX_OPEN_ORDERS, RECENT_ORDERS_COOLDOWN)
            guard_reason = None
            if blocked_by_limits:
                should_create_order = False
                guard_reason = "MAX_OPEN_ORDERS" if unified_open_positions >= self.MAX_OPEN_ORDERS_PER_SYMBOL else "RECENT_ORDERS_COOLDOWN"
                self._log_pipeline_stage(
                    stage="BUY_BLOCKED",
                    symbol=normalized_symbol,
                    strategy_key=strategy_key,
                    decision="BUY",
                    last_price=current_price,
                    timestamp=now_utc.isoformat(),
                    correlation_id=evaluation_id,
                    reason=guard_reason,
                )
            else:
                # Trade execution is independent - proceed if signal exists and trade_enabled
                # Alert sending is informational only, not a gate for trade execution
                should_create_order = True
                self._log_pipeline_stage(
                    stage="BUY_ELIGIBLE_CHECK",
                    symbol=normalized_symbol,
                    strategy_key=strategy_key,
                    decision="BUY",
                    last_price=current_price,
                    timestamp=now_utc.isoformat(),
                    correlation_id=evaluation_id,
                    reason="OK",
                )
                if buy_alert_sent_successfully:
                    logger.info(
                        f"🟢 BUY alert was sent successfully for {symbol}. "
                        f"Proceeding to order creation (trade_enabled, limits, cooldown)."
                    )
                else:
                    logger.info(
                        f"ℹ️ {symbol}: BUY alert not sent (may be throttled/disabled), "
                        f"but proceeding with trade execution (trade is independent of alert)."
                    )
            
            # DIAG_MODE: Print TRADE decision trace for diagnostic symbol (BUY)
            if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
                self._print_trade_decision_trace(
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side="BUY",
                    current_price=current_price,
                    signal_exists=buy_signal,
                    trade_enabled=watchlist_item.trade_enabled,
                    trade_amount_usd=watchlist_item.trade_amount_usd,
                    should_create_order=should_create_order,
                    guard_reason=guard_reason,
                    evaluation_id=evaluation_id
                )
            
            # ========================================================================
            # NOTA: El bloque de alertas ahora se ejecuta ANTES de la lógica de órdenes
            # (líneas 765-965) para garantizar que las alertas se envíen incluso si hay
            # algún return temprano en la lógica de órdenes
            # BLOQUE DUPLICADO REMOVIDO - Las alertas se procesan arriba (líneas 765-965)
            # ========================================================================
            
            if should_create_order:
                # CRITICAL: Double-check for recent orders AND total open positions just before creating (race condition protection)
                # Refresh the query to catch any orders that might have been created between checks
                # FIX: Count by base currency to match the main check above
                db.expire_all()  # Force refresh from database
                symbol_base_final = symbol.split('_')[0] if '_' in symbol else symbol
                
                # Check 1: Recent orders (within 5 minutes) - prevents consecutive orders
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
                
                # Check 2: Total open positions count (unified) - prevents exceeding limit
                # CRITICAL: This check is essential because the limit check at line 2058 might have passed
                # but new orders could have been created between then and now, or the count might be stale
                try:
                    from app.services.order_position_service import count_open_positions_for_symbol
                    final_unified_open_positions = count_open_positions_for_symbol(db, symbol_base_final)
                except Exception as e:
                    logger.error(f"Could not compute unified open position count in final check for {symbol_base_final}: {e}")
                    # Conservative fallback: if we can't count, assume we're at limit to prevent over-ordering
                    logger.warning(f"🚫 BLOCKED: {symbol} - Cannot verify open positions count, blocking order for safety")
                    should_create_order = False
                    return  # Exit early - be conservative when count fails
                
                if final_recent_check > 0:
                    # Get most recent order time for logging
                    most_recent = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol.like(f"{symbol_base_final}_%"),
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        or_(
                            ExchangeOrder.exchange_create_time >= recent_orders_threshold,
                            ExchangeOrder.created_at >= recent_orders_threshold
                        )
                    ).order_by(
                        func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
                    ).first()
                    
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    
                    if most_recent:
                        recent_time = most_recent.exchange_create_time or most_recent.created_at
                        if recent_time:
                            now_utc = datetime.now(timezone.utc)
                            if recent_time.tzinfo is None:
                                recent_time = recent_time.replace(tzinfo=timezone.utc)
                            seconds_remaining = COOLDOWN_SECONDS - (now_utc - recent_time).total_seconds()
                            if DEBUG_TRADING:
                                logger.info(f"[DEBUG_TRADING] GUARD cooldown_blocked symbol={symbol} seconds_remaining={seconds_remaining:.1f}")
                            logger.warning(
                                f"🚫 BLOCKED: {symbol} - Found {final_recent_check} recent order(s) in final check. "
                                f"Order creation cancelled to prevent duplicate. "
                                f"GUARD cooldown_blocked symbol={symbol} seconds_remaining={seconds_remaining:.1f}"
                            )
                            decision_reason = make_skip(
                                reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                                message=f"Recent orders cooldown active for {symbol} (final check). Found {final_recent_check} recent order(s) within 5 minutes. {seconds_remaining:.1f} seconds remaining.",
                                context={
                                    "symbol": symbol,
                                    "base_symbol": symbol_base_final,
                                    "recent_orders_count": final_recent_check,
                                    "seconds_remaining": seconds_remaining,
                                    "cooldown_seconds": COOLDOWN_SECONDS,
                                    "most_recent_order_id": most_recent.exchange_order_id if most_recent else None,
                                    "price": current_price,
                                    "check_type": "final_check",
                                },
                                source="guardrail",
                                correlation_id=correlation_id,
                            )
                        else:
                            decision_reason = make_skip(
                                reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                                message=f"Recent orders cooldown active for {symbol} (final check). Found {final_recent_check} recent order(s) (timestamp unknown).",
                                context={
                                    "symbol": symbol,
                                    "base_symbol": symbol_base_final,
                                    "recent_orders_count": final_recent_check,
                                    "cooldown_seconds": COOLDOWN_SECONDS,
                                    "price": current_price,
                                    "check_type": "final_check",
                                },
                                source="guardrail",
                                correlation_id=correlation_id,
                            )
                    else:
                        if DEBUG_TRADING:
                            logger.info(f"[DEBUG_TRADING] GUARD cooldown_blocked symbol={symbol} seconds_remaining=unknown")
                        logger.warning(
                            f"🚫 BLOCKED: {symbol} - Found {final_recent_check} recent order(s) in final check. "
                            f"Order creation cancelled to prevent duplicate."
                        )
                        decision_reason = make_skip(
                            reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                            message=f"Recent orders cooldown active for {symbol} (final check). Found {final_recent_check} recent order(s).",
                            context={
                                "symbol": symbol,
                                "base_symbol": symbol_base_final,
                                "recent_orders_count": final_recent_check,
                                "cooldown_seconds": COOLDOWN_SECONDS,
                                "price": current_price,
                                "check_type": "final_check",
                            },
                            source="guardrail",
                            correlation_id=correlation_id,
                        )
                    
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="RECENT_ORDERS_COOLDOWN_FINAL_CHECK",
                        decision_reason=decision_reason,
                        )
                    should_create_order = False
                    return  # Exit early
                
                # IDEMPOTENCY GUARD: Check if order already exists for this signal
                # signal_key = symbol + side + time_bucket (minute-level bucket)
                signal_time_bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                signal_key = f"{symbol}:BUY:{signal_time_bucket.isoformat()}"
                
                # Check if order was already created for this signal_key in the last 24 hours
                idempotency_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
                existing_order_for_signal = db.query(ExchangeOrder).filter(
                    ExchangeOrder.symbol == symbol,
                    ExchangeOrder.side == OrderSideEnum.BUY,
                    or_(
                        ExchangeOrder.exchange_create_time >= idempotency_threshold,
                        ExchangeOrder.created_at >= idempotency_threshold
                    )
                ).filter(
                    # Check if order was created in the same minute bucket
                    or_(
                        func.date_trunc('minute', func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at)) == signal_time_bucket,
                        func.date_trunc('minute', ExchangeOrder.created_at) == signal_time_bucket
                    )
                ).first()
                
                if existing_order_for_signal:
                    if DEBUG_TRADING:
                        logger.info(f"[DEBUG_TRADING] GUARD idempotency_blocked signal_key={signal_key} existing_order_id={existing_order_for_signal.exchange_order_id}")
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} - Order already exists for signal_key={signal_key}. "
                        f"GUARD idempotency_blocked signal_key={signal_key} existing_order_id={existing_order_for_signal.exchange_order_id}"
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.IDEMPOTENCY_BLOCKED.value,
                        message=f"Order already exists for signal_key={signal_key}. Idempotency check blocked duplicate order creation.",
                        context={
                            "symbol": symbol,
                            "signal_key": signal_key,
                            "existing_order_id": existing_order_for_signal.exchange_order_id,
                            "price": current_price,
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="IDEMPOTENCY_BLOCKED",
                        decision_reason=decision_reason,
                    )
                    should_create_order = False
                    return  # Exit early
                
                if DEBUG_TRADING:
                    logger.info(f"[DEBUG_TRADING] GUARD cooldown_passed symbol={symbol}")
                    logger.info(f"[DEBUG_TRADING] GUARD idempotency_passed signal_key={signal_key}")
                
                # CRITICAL FIX: Also check total open positions in final check, not just recent orders
                if final_unified_open_positions >= self.MAX_OPEN_ORDERS_PER_SYMBOL:
                    logger.warning(
                        f"🚫 BLOCKED: {symbol} (base: {symbol_base_final}) - Final check: exceeded max open orders limit "
                        f"({final_unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}). "
                        f"Order creation cancelled. This may indicate a race condition was detected."
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.MAX_OPEN_TRADES_REACHED.value,
                        message=f"Maximum open orders reached for {symbol} (final check). {final_unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}. Race condition detected.",
                        context={
                            "symbol": symbol,
                            "base_symbol": symbol_base_final,
                            "open_positions": final_unified_open_positions,
                            "max_open_orders": self.MAX_OPEN_ORDERS_PER_SYMBOL,
                            "price": current_price,
                            "check_type": "final_check",
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="MAX_OPEN_ORDERS_REACHED_FINAL_CHECK",
                        decision_reason=decision_reason,
                    )
                    should_create_order = False
                    return  # Exit early
                
                logger.info(
                    f"✅ Final check passed for {symbol}: recent={final_recent_check}, "
                    f"unified_open={final_unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}"
                )
                
                # Set lock BEFORE creating order to prevent concurrent creation
                # Use time module (already imported at top of file)
                self.order_creation_locks[symbol] = time.time()
                logger.info(f"🔒 Lock set for {symbol} order creation")
                
                logger.info(f"🟢 NEW BUY signal detected for {symbol}")
                
                # NOTE: Alerts are already sent in the first path (line 1198-1492)
                # This path should only handle order creation, not alert sending
                # See comment at line 1760-1763: "BLOQUE DUPLICADO REMOVIDO - Las alertas se procesan arriba"
                
                # Create order automatically ONLY if trade_enabled = true AND alert_enabled = true
                # alert_enabled = true is already filtered, so we only need to check trade_enabled
                logger.info(f"🔍 Checking order creation for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}, alert_enabled={watchlist_item.alert_enabled}")
                
                # CRITICAL: Verify alert_enabled is still True before creating order
                if not watchlist_item.alert_enabled:
                    logger.warning(
                        f"🚫 ORDEN BLOQUEADA: {symbol} - alert_enabled=False. "
                        f"No se creará orden aunque se detectó señal BUY."
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.ALERT_DISABLED.value,
                        message=f"Alerts are disabled for {symbol}. alert_enabled=False. Order creation blocked.",
                        context={
                            "symbol": symbol,
                            "alert_enabled": False,
                            "trade_enabled": getattr(watchlist_item, 'trade_enabled', None),
                            "price": current_price,
                        },
                        source="precheck",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="ALERTS_DISABLED",
                        decision_reason=decision_reason,
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
                    error_msg = (
                        f"❌ ORDEN NO EJECUTADA: {symbol} - MAs REQUIRED but missing: {', '.join(missing_mas)}. "
                        f"La alerta ya fue enviada, pero la orden de compra no se creará sin los indicadores técnicos necesarios."
                    )
                    logger.error(error_msg)
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.DATA_MISSING.value,
                        message=f"Required technical indicators missing for {symbol}: {', '.join(missing_mas)}. Cannot create order without MAs.",
                        context={
                            "symbol": symbol,
                            "missing_indicators": missing_mas,
                            "ma50": ma50,
                            "ema10": ema10,
                            "price": current_price,
                        },
                        source="precheck",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="DATA_MISSING",
                        decision_reason=decision_reason,
                    )
                    # Note: _emit_lifecycle_event already creates the message with decision tracing, no need for duplicate
                    # Remove locks and exit
                    if symbol in self.order_creation_locks:
                        del self.order_creation_locks[symbol]
                    return  # Exit - cannot create order without MAs
                
                # Log MA values for verification
                logger.info(f"✅ MA validation passed for {symbol}: MA50={ma50:.2f}, EMA10={ema10:.2f}, MA50>EMA10={ma50 > ema10}")
                
                # Check portfolio value limit: Skip BUY orders if portfolio_value > 3x trade_amount_usd
                # NOTE: Alert was already sent above, this check only affects order creation
                trade_amount_usd = watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0
                limit_value = 3 * trade_amount_usd
                try:
                    portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                    if portfolio_value > limit_value:
                        skipped_msg = (
                            f"🚫 BUY ORDER BLOCKED: {symbol} - "
                            f"Portfolio value (${portfolio_value:.2f}) exceeds limit (3x trade_amount = ${limit_value:.2f}). "
                            f"Current position: {net_quantity:.4f} {symbol.split('_')[0]}, Price: ${current_price:.4f}. "
                            f"The BUY alert was sent, but the BUY order was blocked to prevent over-concentration."
                        )
                        logger.warning(skipped_msg)
                        # Create DecisionReason for SKIP
                        from app.utils.decision_reason import make_skip, ReasonCode
                        import uuid
                        correlation_id = str(uuid.uuid4())
                        decision_reason = make_skip(
                            reason_code=ReasonCode.GUARDRAIL_BLOCKED.value,
                            message=f"Portfolio value limit exceeded for {symbol}. Portfolio value ${portfolio_value:.2f} > limit ${limit_value:.2f} (3x trade_amount).",
                            context={
                                "symbol": symbol,
                                "portfolio_value": portfolio_value,
                                "limit_value": limit_value,
                                "trade_amount_usd": trade_amount_usd,
                                "net_quantity": net_quantity,
                                "price": current_price,
                            },
                            source="guardrail",
                            correlation_id=correlation_id,
                        )
                        logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                        # Emit TRADE_BLOCKED event with DecisionReason
                        _emit_lifecycle_event(
                            db=db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=current_price,
                            event_type="TRADE_BLOCKED",
                            event_reason="PORTFOLIO_VALUE_LIMIT",
                            decision_reason=decision_reason,
                        )
                        # Note: _emit_lifecycle_event already creates the message with decision tracing, no need for duplicate
                        # Remove locks and exit
                        if symbol in self.order_creation_locks:
                            del self.order_creation_locks[symbol]
                        return  # Exit without creating order
                    else:
                        logger.debug(
                            f"✅ Portfolio value check passed for {symbol}: "
                            f"portfolio_value=${portfolio_value:.2f} <= limit=${limit_value:.2f}"
                        )
                except Exception as portfolio_check_err:
                    logger.warning(f"⚠️ Error checking portfolio value for {symbol}: {portfolio_check_err}. Continuing with order creation...")
                    # On error, continue (don't block orders if we can't calculate portfolio value)
                
                # CRITICAL: Refresh trade_enabled and trade_amount_usd from database before checking
                # This ensures we use the latest values even if they were just changed in the dashboard
                db.expire_all()  # Force refresh from database
                try:
                    fresh_trade_check = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol == symbol
                    ).first()
                    if fresh_trade_check:
                        trade_enabled = getattr(fresh_trade_check, 'trade_enabled', False)
                        trade_amount_usd = getattr(fresh_trade_check, 'trade_amount_usd', None)
                        logger.info(
                            f"🔄 [ORDER_CREATION_CHECK] {symbol} - Fresh DB values: "
                            f"trade_enabled={trade_enabled}, trade_amount_usd={trade_amount_usd}"
                        )
                        # Update watchlist_item with fresh values
                        # CRITICAL: Preserve user-set trade_amount_usd - only update if it was None/0 in DB
                        watchlist_item.trade_enabled = trade_enabled
                        if trade_amount_usd is not None and trade_amount_usd != 0:
                            # Only update if current value is None/0 (user hasn't set it yet)
                            if watchlist_item.trade_amount_usd is None or watchlist_item.trade_amount_usd == 0:
                                watchlist_item.trade_amount_usd = trade_amount_usd
                            # Otherwise preserve user's value
                    else:
                        logger.warning(f"⚠️ [ORDER_CREATION_CHECK] {symbol} - No watchlist item found in database!")
                except Exception as e:
                    logger.warning(f"Error en última verificación de trade_enabled para {symbol} (BUY): {e}")
                    # Use existing values if refresh fails
                
                if watchlist_item.trade_enabled:
                    logger.info(f"✅ [ORDER_CREATION_CHECK] {symbol} - trade_enabled=True confirmed, proceeding with order creation")
                    if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                        logger.info(f"✅ Trade enabled for {symbol} - creating BUY order automatically")
                        # PHASE 0: Structured logging for order creation attempt
                        logger.info(
                            f"[EVAL_{evaluation_id}] {symbol} BUY order creation attempt | "
                            f"trade_enabled=True | "
                            f"trade_amount_usd=${watchlist_item.trade_amount_usd:.2f} | "
                            f"price=${current_price:.4f}"
                        )
                        self._log_pipeline_stage(
                            stage="BUY_ORDER_SUBMITTED",
                            symbol=normalized_symbol,
                            strategy_key=strategy_key,
                            decision="BUY",
                            last_price=current_price,
                            timestamp=now_utc.isoformat(),
                            correlation_id=evaluation_id,
                        )
                        try:
                            # E) Deep decision-grade logging for order attempt
                            logger.info(
                                f"[CRYPTO_ORDER_ATTEMPT] {symbol} BUY price=${current_price:.4f} "
                                f"qty_usd=${watchlist_item.trade_amount_usd:.2f} trade_enabled={watchlist_item.trade_enabled}"
                            )
                            # Use asyncio.run() to execute async function from sync context
                            import asyncio
                            order_result = asyncio.run(self._create_buy_order(db, watchlist_item, current_price, res_up, res_down))
                            # Check for errors first (error dicts are truthy but have "error" key)
                            if order_result and isinstance(order_result, dict) and "error" in order_result:
                                # Order creation failed, remove lock immediately
                                if symbol in self.order_creation_locks:
                                    del self.order_creation_locks[symbol]
                                
                                # Handle error cases
                                error_type = order_result.get("error_type")
                                error_msg = order_result.get("message")
                                
                                if error_type == "balance":
                                    logger.warning(f"⚠️ BUY order creation blocked for {symbol}: Insufficient balance - {error_msg}")
                                elif error_type == "trade_disabled":
                                    logger.warning(f"🚫 BUY order creation blocked for {symbol}: Trade is disabled - {error_msg}")
                                elif error_type == "authentication":
                                    logger.error(f"❌ BUY order creation failed for {symbol}: Authentication error - {error_msg}")
                                elif error_type == "order_placement":
                                    logger.error(f"❌ BUY order creation failed for {symbol}: Order placement error - {error_msg}")
                                elif error_type == "no_order_id":
                                    logger.error(f"❌ BUY order creation failed for {symbol}: No order ID returned - {error_msg}")
                                elif error_type == "exception":
                                    logger.error(f"❌ BUY order creation failed for {symbol}: Exception - {error_msg}")
                                else:
                                    # PHASE 0: Structured logging for order creation failure
                                    logger.error(
                                        f"[EVAL_{evaluation_id}] {symbol} BUY order creation FAILED | "
                                        f"error_type={error_type} | "
                                        f"error_msg={error_msg} | "
                                        f"price=${current_price:.4f}"
                                    )
                                    self._log_pipeline_stage(
                                        stage="BUY_ORDER_RESPONSE",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        reason=f"FAILED:{error_msg or error_type or 'unknown'}",
                                    )
                                    # E) Deep decision-grade logging for order result
                                    logger.error(
                                        f"[CRYPTO_ORDER_RESULT] {symbol} BUY success=False order_id=None "
                                        f"price=${current_price:.4f} qty=0 error={error_type or 'unknown'}"
                                    )
                                    logger.warning(f"⚠️ BUY order creation failed for {symbol} (error_type: {error_type}, reason: {error_msg or 'unknown'})")
                                if error_type and error_type != "unknown":
                                    self._log_pipeline_stage(
                                        stage="BUY_ORDER_RESPONSE",
                                        symbol=normalized_symbol,
                                        strategy_key=strategy_key,
                                        decision="BUY",
                                        last_price=current_price,
                                        timestamp=now_utc.isoformat(),
                                        correlation_id=evaluation_id,
                                        reason=f"FAILED:{error_msg or error_type}",
                                    )
                            elif order_result:
                                # Success case - order was created
                                # PHASE 0: Structured logging for order creation success
                                order_id = order_result.get("order_id") or order_result.get("client_oid") or "N/A"
                                exchange_order_id = order_result.get("exchange_order_id") or "N/A"
                                filled_price = order_result.get("filled_price") or current_price
                                quantity = order_result.get("quantity") or 0
                                
                                # CRITICAL: Log ORDER_PLACED for verification
                                if DEBUG_TRADING:
                                    logger.info(f"[DEBUG_TRADING] ORDER_PLACED side=BUY symbol={symbol} order_id={order_id}")
                                logger.info(f"ORDER_PLACED side=BUY symbol={symbol} order_id={order_id}")
                                
                                logger.info(
                                    f"[EVAL_{evaluation_id}] {symbol} BUY order creation SUCCESS | "
                                    f"order_id={order_id} | "
                                    f"exchange_order_id={exchange_order_id} | "
                                    f"price=${filled_price:.4f} | "
                                    f"quantity={quantity:.4f}"
                                )
                                self._log_pipeline_stage(
                                    stage="BUY_ORDER_RESPONSE",
                                    symbol=normalized_symbol,
                                    strategy_key=strategy_key,
                                    decision="BUY",
                                    last_price=current_price,
                                    timestamp=now_utc.isoformat(),
                                    correlation_id=evaluation_id,
                                    reason="SUCCESS",
                                )
                                
                                # DIAG_MODE: Update TRADE decision trace to show EXEC_ORDER_PLACED
                                if DIAG_SYMBOL and symbol.upper() == DIAG_SYMBOL:
                                    self._print_trade_decision_trace(
                                        symbol=symbol,
                                        strategy_key=strategy_key,
                                        side="BUY",
                                        current_price=current_price,
                                        signal_exists=buy_signal,
                                        trade_enabled=watchlist_item.trade_enabled,
                                        trade_amount_usd=watchlist_item.trade_amount_usd,
                                        should_create_order=True,
                                        guard_reason=None,  # No guard - order was placed
                                        evaluation_id=evaluation_id
                                    )
                                # E) Deep decision-grade logging for order result
                                logger.info(
                                    f"[CRYPTO_ORDER_RESULT] {symbol} BUY success=True order_id={exchange_order_id} "
                                    f"price=${filled_price:.4f} qty={quantity:.4f} error=None"
                                )
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
                                            emit_reason="Order created",
                                        )
                                        buy_state_recorded = True
                                    except Exception as state_err:
                                        logger.warning(f"Failed to persist BUY throttle state after order for {symbol}: {state_err}")
                            else:
                                # order_result is None or falsy
                                # Order creation failed, remove lock immediately
                                if symbol in self.order_creation_locks:
                                    del self.order_creation_locks[symbol]
                                
                                # PHASE 0: Structured logging for order creation failure
                                logger.error(
                                    f"[EVAL_{evaluation_id}] {symbol} BUY order creation FAILED | "
                                    f"order_result=None or empty | "
                                    f"price=${current_price:.4f}"
                                )
                                # E) Deep decision-grade logging for order result
                                logger.error(
                                    f"[CRYPTO_ORDER_RESULT] {symbol} BUY success=False order_id=None "
                                    f"price=${current_price:.4f} qty=0 error=order_result_empty"
                                )
                                logger.info(f"🔓 Lock removed for {symbol} (order creation returned None)")
                        except Exception as order_err:
                            # Order creation failed, remove lock immediately
                            if symbol in self.order_creation_locks:
                                del self.order_creation_locks[symbol]
                            # PHASE 0: Structured logging for order creation exception
                            error_str = str(order_err)[:200]  # Limit error message length
                            logger.error(
                                f"[EVAL_{evaluation_id}] {symbol} BUY order creation EXCEPTION | "
                                f"error={error_str} | "
                                f"price=${current_price:.4f}"
                            )
                            # E) Deep decision-grade logging for order result
                            logger.error(
                                f"[CRYPTO_ORDER_RESULT] {symbol} BUY success=False order_id=None "
                                f"price=${current_price:.4f} qty=0 error={error_str}"
                            )
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
                    logger.info(
                        f"ℹ️ [ORDER_CREATION_CHECK] {symbol} - trade_enabled=False, "
                        f"alert was sent but order will NOT be created (trading disabled for this symbol)"
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.TRADE_DISABLED.value,
                        message=f"Trade disabled for {symbol}. Alert was sent but order will not be created because trade_enabled=False for this symbol.",
                        context={
                            "symbol": symbol,
                            "trade_enabled": False,
                            "alert_sent": buy_alert_sent_successfully,
                            "price": current_price,
                        },
                        source="guardrail",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="TRADE_DISABLED",
                        decision_reason=decision_reason,
                    )
                    # Note: _emit_lifecycle_event already creates the message with decision tracing, no need for duplicate
            
            # Handle case when should_create_order=False (alert was sent but order was blocked)
            # This else is at the same level as if should_create_order: (line 2971)
            if not should_create_order:
                # should_create_order=False - alert was sent but order was blocked
                # Decision tracing should have been emitted in guard clauses (MAX_OPEN_TRADES_REACHED, RECENT_ORDERS_COOLDOWN)
                # But if for some reason it wasn't (e.g., guard_reason is None), log it for debugging
                if buy_alert_sent_successfully:
                    logger.debug(
                        f"ℹ️ {symbol}: BUY alert was sent but should_create_order=False. "
                        f"guard_reason={guard_reason}. Decision tracing should already be recorded in guard clauses."
                    )
                    # FALLBACK: If guard_reason is set but decision tracing wasn't emitted (e.g., _emit_lifecycle_event failed silently),
                    # emit a fallback decision tracing event to ensure we always have a record
                    if guard_reason:
                        try:
                            from app.utils.decision_reason import make_skip, ReasonCode
                            import uuid
                            correlation_id = str(uuid.uuid4())
                            fallback_reason_code = ReasonCode.MAX_OPEN_TRADES_REACHED.value if guard_reason == "MAX_OPEN_ORDERS" else ReasonCode.RECENT_ORDERS_COOLDOWN.value
                            fallback_decision = make_skip(
                                reason_code=fallback_reason_code,
                                message=f"Order blocked for {symbol} after alert was sent. Guard reason: {guard_reason}",
                                context={
                                    "symbol": symbol,
                                    "guard_reason": guard_reason,
                                    "price": current_price,
                                    "fallback": True,  # Mark as fallback decision
                                },
                                source="guardrail_fallback",
                                correlation_id=correlation_id,
                            )
                            logger.warning(
                                f"⚠️ {symbol}: BUY alert sent but emitting fallback decision tracing. "
                                f"Guard reason: {guard_reason}, Reason code: {fallback_decision.reason_code}"
                            )
                            _emit_lifecycle_event(
                                db=db,
                                symbol=symbol,
                                strategy_key=strategy_key,
                                side="BUY",
                                price=current_price,
                                event_type="TRADE_BLOCKED",
                                event_reason=f"FALLBACK_{guard_reason}",
                                decision_reason=fallback_decision,
                            )
                        except Exception as fallback_err:
                            logger.warning(f"Failed to emit fallback decision tracing for {symbol}: {fallback_err}")
                    # Note: Decision tracing is normally emitted in the guard clauses above (lines 2803-2925)
                    # This fallback ensures we always have a record even if guard clauses fail silently
            
        # ========================================================================
        # ENVÍO DE ALERTAS SELL: Enviar alerta SIEMPRE que sell_signal=True y sell_alert_enabled=True
        # IMPORTANTE: Similar a las alertas BUY, pero solo alertas (no órdenes automáticas)
        # ========================================================================
        # DEBUG: Log before SELL alert section for DOT_USD
        if symbol == "DOT_USD":
            logger.info(
                f"🔍 [DEBUG] {symbol} entering SELL alert section: "
                f"sell_signal={sell_signal}, current_state={current_state}"
            )
        # CRITICAL: Always read flags from DB (watchlist_item is already refreshed from DB)
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', False)
        
        # Log alert decision with all flags for clarity
        if sell_signal:
            alert_enabled = watchlist_item.alert_enabled
            if alert_enabled and sell_alert_enabled:
                logger.info(
                    f"🔍 {symbol} SELL alert decision: sell_signal=True, "
                    f"alert_enabled={alert_enabled}, buy_alert_enabled={getattr(watchlist_item, 'buy_alert_enabled', False)}, sell_alert_enabled={sell_alert_enabled} → "
                    f"DECISION: SENT (both flags enabled)"
                )
            else:
                skip_reason = []
                if not alert_enabled:
                    skip_reason.append("alert_enabled=False")
                if not sell_alert_enabled:
                    skip_reason.append("sell_alert_enabled=False")
                logger.info(
                    "[GATE] symbol=%s gate=sell_alert_enabled decision=BLOCK reason=%s evaluation_id=%s",
                    symbol,
                    ",".join(skip_reason),
                    evaluation_id,
                )
                block_reason = "ALERT_DISABLED" if not alert_enabled else "SIDE_DISABLED"
                self._upsert_watchlist_signal_state(
                    db,
                    symbol=normalized_symbol,
                    alert_status="BLOCKED",
                    alert_block_reason=block_reason,
                    last_alert_at_utc=datetime.now(timezone.utc),
                    correlation_id=evaluation_id,
                )
                logger.info(
                    f"🔍 {symbol} SELL alert decision: sell_signal=True, "
                    f"alert_enabled={alert_enabled}, buy_alert_enabled={getattr(watchlist_item, 'buy_alert_enabled', False)}, sell_alert_enabled={sell_alert_enabled} → "
                    f"DECISION: SKIPPED ({', '.join(skip_reason)})"
                )
                self._log_signal_rejection(
                    symbol,
                    "SELL",
                    "DISABLED_BUY_SELL_FLAG",
                    {"alert_enabled": alert_enabled, "sell_alert_enabled": sell_alert_enabled},
                )
        
        # DEBUG: Log before final SELL alert check for DOT_USD
        if symbol == "DOT_USD":
            logger.info(
                f"🔍 [DEBUG] {symbol} final SELL alert check: "
                f"sell_signal={sell_signal}, sell_alert_enabled={sell_alert_enabled}"
            )
        # CRITICAL: Verify BOTH alert_enabled (master switch) AND sell_alert_enabled (SELL-specific) before processing
        # DIAGNOSTIC: Log why SELL alert might not be sent for TRX_USDT
        if symbol == "TRX_USDT" or symbol == "TRX_USD":
            logger.info(
                f"🔍 [DIAGNOSTIC] {symbol} SELL alert check: "
                f"sell_signal={sell_signal}, alert_enabled={watchlist_item.alert_enabled}, "
                f"sell_alert_enabled={sell_alert_enabled}, "
                f"will_send={'YES' if (sell_signal and watchlist_item.alert_enabled and sell_alert_enabled) else 'NO'}"
            )
        
        if sell_signal and watchlist_item.alert_enabled and sell_alert_enabled:
            logger.info(f"🔴 NEW SELL signal detected for {symbol} - processing alert (alert_enabled=True, sell_alert_enabled=True)")
            
            # CRITICAL: Use a lock to prevent race conditions when multiple cycles run simultaneously
            lock_key = f"{symbol}_SELL"
            lock_timeout = self.ALERT_SENDING_LOCK_SECONDS
            # Use time module (already imported at top of file)
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
                
                # Use the price from snapshot (saved before record_signal_event) for consistent price change calculation
                # This ensures "Cambio desde última alerta" matches the price change shown in the trigger reason
                # Fallback to database query if snapshot price not available (shouldn't happen, but safe fallback)
                prev_sell_price: Optional[float] = prev_sell_price_from_snapshot if prev_sell_price_from_snapshot is not None else self._get_last_alert_price(symbol, "SELL", db)
                
                # FIX: Check sell_allowed status - if throttled, still create alert but mark as blocked
                # This ensures SELL alerts are always created/persisted (same as BUY), only duplicates are prevented
                import uuid as uuid_module
                trace_id = str(uuid_module.uuid4())
                dedup_key = f"{symbol}:SELL:{strategy_key}"
                
                # PHASE 0: Structured logging for SELL alert attempt
                logger.info(
                    f"[SELL_ALERT_ATTEMPT] symbol={symbol} side=SELL dedup_key={dedup_key} "
                    f"trace_id={trace_id} sell_allowed={sell_allowed} throttle_reason={sell_reason if not sell_allowed else 'N/A'}"
                )
                
                # NOTE: Even if throttled (sell_allowed=False), we still proceed to send the alert
                # send_sell_signal() will handle duplicate detection and mark as blocked if needed
                # This ensures alerts are always created/persisted for monitoring, only duplicates are prevented
                if sell_allowed:
                    logger.info(
                        f"🔍 {symbol} SELL alert ready to send (throttling already verified by should_emit_signal)"
                    )
                else:
                    logger.info(
                        f"🔍 {symbol} SELL alert will be sent with BLOCKED status (throttled: {sell_reason})"
                    )
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason=self._map_alert_block_reason(sell_reason),
                        last_alert_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
                    )
                self._log_signal_accept(
                    symbol,
                    "SELL",
                    {
                        "price": current_price,
                        "trade_enabled": getattr(watchlist_item, "trade_enabled", None),
                    },
                )
                
                # CRITICAL: Final check - verify sell_alert_enabled before sending
                # Refresh flag from database to ensure we have latest value
                # Use get_canonical_watchlist_item to get the correct item (same logic as transition emitter)
                db.expire_all()  # Force refresh from database
                try:
                    from app.services.watchlist_selector import get_canonical_watchlist_item
                    fresh_check = get_canonical_watchlist_item(db, symbol)
                    if fresh_check:
                        sell_alert_enabled = getattr(fresh_check, 'sell_alert_enabled', False)
                        logger.debug(f"🔄 Última verificación de sell_alert_enabled para {symbol}: {sell_alert_enabled}")
                except Exception as e:
                    logger.warning(f"Error en última verificación de flags para {symbol}: {e}")
                
                if not sell_alert_enabled:
                    blocked_msg = (
                        f"🚫 BLOQUEADO: {symbol} SELL - Las alertas de venta (SELL) están deshabilitadas "
                        f"para este símbolo (sell_alert_enabled=False). No se enviará alerta SELL aunque "
                        f"se detectó señal SELL. Para habilitar alertas de venta, active 'sell_alert_enabled' "
                        f"en la configuración del símbolo."
                    )
                    self._upsert_watchlist_signal_state(
                        db,
                        symbol=normalized_symbol,
                        alert_status="BLOCKED",
                        alert_block_reason="SIDE_DISABLED",
                        last_alert_at_utc=datetime.now(timezone.utc),
                        correlation_id=evaluation_id,
                    )
                    self._log_signal_rejection(
                        symbol,
                        "SELL",
                        "DISABLED_BUY_SELL_FLAG",
                        {"sell_alert_enabled": False},
                    )
                    logger.warning(blocked_msg)
                    try:
                        from app.api.routes_monitoring import add_telegram_message
                        add_telegram_message(blocked_msg, symbol=symbol, blocked=True)
                    except Exception:
                        pass  # Non-critical, continue
                    # CRITICAL: Do NOT record signal event when blocked - price reference must remain the last successful (non-blocked) message price
                    # The price reference should only be updated when a message is actually sent successfully
                    # Remove lock since we're not sending
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
                else:
                    # sell_alert_enabled is True - proceed to send alert (throttling already verified by should_emit_signal)
                    try:
                        # ========================================================================
                        # EARLY BALANCE CHECK: Check balance before sending alert if trade is enabled
                        # This allows us to inform users in the alert if trade will fail
                        # ========================================================================
                        balance_check_warning = None
                        trade_enabled_check = getattr(watchlist_item, 'trade_enabled', False)
                        trade_amount_usd_check = getattr(watchlist_item, 'trade_amount_usd', None)
                        
                        # Only check balance if trade is enabled and amount is configured
                        if trade_enabled_check and trade_amount_usd_check and trade_amount_usd_check > 0:
                            # Read trade_on_margin from database
                            user_wants_margin_check = getattr(watchlist_item, 'trade_on_margin', False)
                            
                            # For SELL orders, we need to check if we have enough balance of the base currency
                            base_currency = symbol.split('_')[0] if '_' in symbol else symbol
                            
                            if not user_wants_margin_check:
                                try:
                                    account_summary = trade_client.get_account_summary()
                                    available_balance = 0
                                    
                                    if 'accounts' in account_summary or 'data' in account_summary:
                                        accounts = account_summary.get('accounts') or account_summary.get('data', {}).get('accounts', [])
                                        for acc in accounts:
                                            currency = acc.get('currency', '').upper()
                                            if currency == base_currency:
                                                available = float(acc.get('available', '0') or '0')
                                                available_balance = available
                                                break
                                    
                                    # Calculate required quantity
                                    required_qty = trade_amount_usd_check / current_price
                                    
                                    # If we don't have enough base currency, prepare warning
                                    if available_balance < required_qty:
                                        balance_check_warning = (
                                            f"⚠️ <b>TRADE NO EJECUTADO</b> - Balance insuficiente: "
                                            f"Disponible: {available_balance:.8f} {base_currency}, "
                                            f"Requerido: {required_qty:.8f} {base_currency}"
                                        )
                                        logger.info(
                                            f"💰 Early balance check for {symbol} SELL: Insufficient balance "
                                            f"(available={available_balance:.8f} {base_currency} < "
                                            f"required={required_qty:.8f} {base_currency}). "
                                            f"Including warning in alert message."
                                        )
                                        
                                        # DIAGNOSTIC: Log balance issue for TRX_USDT
                                        if symbol == "TRX_USDT" or symbol == "TRX_USD":
                                            logger.warning(
                                                f"🔍 [DIAGNOSTIC] {symbol} SELL order will be SKIPPED due to insufficient balance: "
                                                f"available={available_balance:.8f} {base_currency}, "
                                                f"required={required_qty:.8f} {base_currency}, "
                                                f"trade_amount_usd={trade_amount_usd_check}, "
                                                f"current_price={current_price}"
                                            )
                                    else:
                                        # DIAGNOSTIC: Log successful balance check for TRX_USDT
                                        if symbol == "TRX_USDT" or symbol == "TRX_USD":
                                            logger.info(
                                                f"🔍 [DIAGNOSTIC] {symbol} SELL balance check PASSED: "
                                                f"available={available_balance:.8f} {base_currency}, "
                                                f"required={required_qty:.8f} {base_currency}"
                                            )
                                except Exception as balance_check_err:
                                    logger.warning(
                                        f"⚠️ Early balance check failed for {symbol} SELL: {balance_check_err}. "
                                        f"Continuing with alert..."
                                    )
                        
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
                        # FIX: Pass throttle_status based on sell_allowed - if throttled, mark as BLOCKED
                        # This ensures alerts are created/persisted even when throttled (for monitoring)
                        throttle_status_to_send = "SENT" if sell_allowed else "BLOCKED"
                        # Use throttle_sell_reason if available, otherwise use sell_reason from throttle check
                        throttle_reason_to_send = throttle_sell_reason if throttle_sell_reason else sell_reason
                        
                        result = emit_alert(
                            db=db,
                            symbol=symbol,
                            side="SELL",
                            reason=reason_text,
                            price=current_price,
                            context={
                                "price": current_price,
                                "previous_price": prev_sell_price,
                                "strategy": strategy_display,
                                "risk": risk_display,
                                "balance_warning": balance_check_warning,
                            },
                            strategy_type=strategy_display,
                            risk_approach=risk_display,
                            price_variation=price_variation,
                            throttle_status=throttle_status_to_send,
                            throttle_reason=throttle_reason_to_send,
                            evaluation_id=evaluation_id,
                            strategy_key=strategy_key,
                            thresholds=threshold_context,
                        )
                        # PHASE 0: Structured logging for SELL Telegram send attempt
                        message_id_sell = None
                        if isinstance(result, dict):
                            message_id_sell = result.get("message_id")
                        elif hasattr(result, 'message_id'):
                            message_id_sell = result.message_id
                        
                        # PHASE 0: Structured logging for alert decision and enqueue
                        logger.info(
                            f"[ALERT_DECISION] symbol={symbol} side=SELL reason={reason_text} "
                            f"trace_id={trace_id} dedup_key={dedup_key} sell_allowed={sell_allowed} "
                            f"throttle_status={throttle_status_to_send}"
                        )
                        
                        # Alerts must never be blocked after conditions are met (guardrail compliance)
                        # If send_sell_signal returns False, log as error but do not treat as block
                        if result is False:
                            logger.error(
                                f"[EVAL_{evaluation_id}] {symbol} SELL Telegram send FAILED | "
                                f"result=False | trace_id={trace_id} | reason={reason_text}"
                            )
                            logger.error(
                                f"[ALERT_ENQUEUED] symbol={symbol} side=SELL sent=False trace_id={trace_id} "
                                f"error=send_sell_signal_returned_False"
                            )
                            logger.error(
                                f"❌ Failed to send SELL alert for {symbol} (send_sell_signal returned False). "
                                f"This should not happen when conditions are met. Check telegram_notifier."
                            )
                            self._upsert_watchlist_signal_state(
                                db,
                                symbol=normalized_symbol,
                                alert_status="BLOCKED",
                                alert_block_reason="TELEGRAM_ERROR",
                                last_alert_at_utc=now_utc,
                                correlation_id=evaluation_id,
                            )
                        else:
                            # PHASE 0: Structured logging for successful alert enqueue
                            logger.info(
                                f"[ALERT_ENQUEUED] symbol={symbol} side=SELL sent=True trace_id={trace_id} "
                                f"message_id={message_id_sell or 'N/A'} dedup_key={dedup_key} "
                                f"throttle_status={throttle_status_to_send}"
                            )
                            logger.info(
                                f"[EVAL_{evaluation_id}] {symbol} SELL Telegram send SUCCESS | "
                                f"message_id={message_id_sell or 'N/A'} | trace_id={trace_id} | "
                                f"price=${current_price:.4f} | reason={reason_text}"
                            )
                            logger.info(
                                f"[TELEGRAM_SEND] {symbol} SELL status=SUCCESS message_id={message_id_sell or 'N/A'} "
                                f"trace_id={trace_id} channel={telegram_notifier.chat_id} origin={alert_origin}"
                            )
                            logger.info(
                                f"✅ SELL alert SENT for {symbol}: "
                                f"buy_alert_enabled={getattr(watchlist_item, 'buy_alert_enabled', False)}, sell_alert_enabled={sell_alert_enabled} - {reason_text}"
                            )
                            sell_alert_sent_successfully = True  # Mark alert as sent successfully
                            self._upsert_watchlist_signal_state(
                                db,
                                symbol=normalized_symbol,
                                alert_status="SENT" if throttle_status_to_send == "SENT" else "BLOCKED",
                                alert_block_reason=None if throttle_status_to_send == "SENT" else self._map_alert_block_reason(throttle_reason_to_send),
                                last_alert_at_utc=now_utc,
                                correlation_id=evaluation_id,
                            )
                            self._log_signal_accept(
                                symbol,
                                "SELL",
                                {"telegram": "sent", "reason": reason_text},
                            )
                            
                            # ========================================================================
                            # INVARIANT ENFORCEMENT: Call orchestrator immediately after signal sent
                            # ========================================================================
                            # If signal is sent, order MUST be attempted immediately (only dedup can block)
                            try:
                                from app.services.signal_order_orchestrator import create_order_intent, update_order_intent_status
                                from app.api.routes_monitoring import update_telegram_message_decision_trace
                                from app.utils.decision_reason import make_skip, make_fail, make_execute, ReasonCode
                                import uuid as uuid_module
                                
                                # Extract signal_id from result
                                signal_id = None
                                if isinstance(result, dict):
                                    signal_id = result.get("message_id")
                                elif hasattr(result, 'message_id'):
                                    signal_id = result.message_id
                                elif result is True:
                                    # Fallback: query for most recent TelegramMessage
                                    try:
                                        from app.models.telegram_message import TelegramMessage
                                        recent_msg = db.query(TelegramMessage).filter(
                                            TelegramMessage.symbol == symbol,
                                            TelegramMessage.message.like("%SELL SIGNAL%"),
                                            TelegramMessage.blocked == False,
                                        ).order_by(TelegramMessage.timestamp.desc()).first()
                                        if recent_msg:
                                            signal_id = recent_msg.id
                                    except Exception as query_err:
                                        logger.warning(f"Could not query for SELL signal_id: {query_err}")
                                order_intent = None
                                intent_status = None

                                if not signal_id:
                                    decision_reason = make_fail(
                                        reason_code=ReasonCode.SIGNAL_ID_MISSING.value,
                                        message=f"Signal sent for {symbol} SELL but no signal_id was available.",
                                        context={"symbol": symbol, "side": "SELL"},
                                        source="orchestrator",
                                    )
                                    update_telegram_message_decision_trace(
                                        db=db,
                                        symbol=symbol,
                                        message_pattern="SELL SIGNAL",
                                        decision_type="FAILED",
                                        reason_code=decision_reason.reason_code,
                                        reason_message=decision_reason.reason_message,
                                        context_json=decision_reason.context,
                                        correlation_id=str(uuid_module.uuid4()),
                                    )
                                    logger.warning(
                                        f"[ORCHESTRATOR] {symbol} SELL Signal missing signal_id; skipping order_intent"
                                    )
                                else:
                                    logger.info(f"[ORCHESTRATOR] {symbol} SELL Signal sent - triggering orchestrator (signal_id={signal_id})")
                                    self._schedule_missing_intent_check(signal_id, symbol, "SELL")

                                    # Create order intent (atomic deduplication)
                                    sent_message_content = f"SELL SIGNAL {symbol} {current_price} {reason_text}"
                                    order_intent, intent_status = create_order_intent(
                                        db=db,
                                        signal_id=signal_id,
                                        symbol=normalize_symbol_for_exchange(symbol),
                                        side="SELL",
                                        message_content=sent_message_content,
                                        strategy_key=strategy_key,
                                    )
                                
                                if intent_status == "DEDUP_SKIPPED":
                                    # Duplicate signal - skip order
                                    logger.warning(f"[ORCHESTRATOR] {symbol} SELL DEDUP_SKIPPED - Duplicate signal detected")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="BLOCKED",
                                        trade_block_reason="DUPLICATE",
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                    decision_reason = make_skip(
                                        reason_code=ReasonCode.IDEMPOTENCY_BLOCKED.value,
                                        message=f"Duplicate signal detected for {symbol} SELL. Order was already attempted (idempotency_key already exists).",
                                        context={"symbol": symbol, "signal_id": signal_id},
                                        source="orchestrator",
                                    )
                                    update_telegram_message_decision_trace(
                                        db=db,
                                        symbol=symbol,
                                        message_pattern="SELL SIGNAL",
                                        decision_type="SKIPPED",
                                        reason_code=decision_reason.reason_code,
                                        reason_message=decision_reason.reason_message,
                                        context_json=decision_reason.context,
                                        correlation_id=str(uuid_module.uuid4()),
                                    )
                                elif intent_status == "ORDER_BLOCKED_LIVE_TRADING":
                                    # LIVE_TRADING=false - order blocked
                                    logger.info(f"[ORCHESTRATOR] {symbol} SELL ORDER_BLOCKED_LIVE_TRADING - Signal sent but order blocked")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="BLOCKED",
                                        trade_block_reason="TRADE_DISABLED",
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                    decision_reason = make_skip(
                                        reason_code="ORDER_BLOCKED_LIVE_TRADING",
                                        message=f"Order blocked: LIVE_TRADING is disabled. Signal was sent but no order will be placed.",
                                        context={"symbol": symbol, "live_trading": False},
                                        source="orchestrator",
                                    )
                                    update_telegram_message_decision_trace(
                                        db=db,
                                        symbol=symbol,
                                        message_pattern="SELL SIGNAL",
                                        decision_type="SKIPPED",
                                        reason_code=decision_reason.reason_code,
                                        reason_message=decision_reason.reason_message,
                                        context_json=decision_reason.context,
                                        correlation_id=str(uuid_module.uuid4()),
                                    )
                                elif intent_status == "PENDING" and order_intent:
                                    # Order intent created - attempt order placement (bypassing eligibility checks)
                                    logger.info(f"[ORCHESTRATOR] {symbol} SELL Order intent created (id={order_intent.id}) - Attempting order placement")
                                    self._upsert_watchlist_signal_state(
                                        db,
                                        symbol=normalized_symbol,
                                        trade_status="SUBMITTED",
                                        trade_block_reason=None,
                                        last_trade_at_utc=now_utc,
                                        correlation_id=evaluation_id,
                                    )
                                
                                    # Call minimal order placement function (NO eligibility checks)
                                    # Note: Running async function from sync context using new event loop
                                    try:
                                        loop = asyncio.new_event_loop()
                                        asyncio.set_event_loop(loop)
                                        try:
                                            order_result = loop.run_until_complete(
                                                self._place_order_from_signal(
                                                    db=db,
                                                    symbol=symbol,
                                                    side="SELL",
                                                    watchlist_item=watchlist_item,
                                                    current_price=current_price,
                                                    source="orchestrator",
                                                )
                                            )
                                        finally:
                                            loop.close()
                                        
                                        if "error" in order_result:
                                            # Order creation failed
                                            error_msg = order_result.get("message") or order_result.get("error", "Unknown error")
                                            logger.error(f"[ORCHESTRATOR] {symbol} SELL Order creation failed: {error_msg}")
                                            self._upsert_watchlist_signal_state(
                                                db,
                                                symbol=normalized_symbol,
                                                trade_status="BLOCKED",
                                                trade_block_reason="EXCHANGE_ERROR",
                                                last_trade_at_utc=now_utc,
                                                correlation_id=evaluation_id,
                                            )
                                            update_order_intent_status(
                                                db=db,
                                                order_intent_id=order_intent.id,
                                                status="ORDER_FAILED",
                                                error_message=error_msg,
                                            )
                                            
                                            # Classify error for strict reporting
                                            from app.utils.decision_reason import classify_exchange_error
                                            reason_code = classify_exchange_error(error_msg)
                                            
                                            decision_reason = make_fail(
                                                reason_code=reason_code,
                                                message=f"Order creation failed for {symbol} SELL: {error_msg}",
                                                context={"symbol": symbol, "error": error_msg},
                                                source="orchestrator",
                                                exchange_error=error_msg,
                                            )
                                            update_telegram_message_decision_trace(
                                                db=db,
                                                symbol=symbol,
                                                message_pattern="SELL SIGNAL",
                                                decision_type="FAILED",
                                                reason_code=decision_reason.reason_code,
                                                reason_message=decision_reason.reason_message,
                                                context_json=decision_reason.context,
                                                exchange_error_snippet=decision_reason.exchange_error,
                                                correlation_id=str(uuid_module.uuid4()),
                                            )
                                            
                                            # Send Telegram failure message (required)
                                            try:
                                                from app.services.telegram_notifier import telegram_notifier
                                                telegram_notifier.send_message(
                                                    f"❌ <b>ORDER FAILED</b>\n\n"
                                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                                    f"🔄 Side: SELL\n"
                                                    f"❌ Error: {error_msg}\n\n"
                                                    f"<i>Signal was sent but order creation failed.</i>"
                                                )
                                            except Exception as telegram_err:
                                                logger.warning(f"Failed to send Telegram failure message: {telegram_err}")
                                            try:
                                                from app.api.routes_monitoring import add_telegram_message
                                                add_telegram_message(
                                                    f"❌ ORDER FAILED | {symbol} SELL | {error_msg}",
                                                    symbol=symbol,
                                                    blocked=False,
                                                    decision_type="FAILED",
                                                    reason_code=reason_code,
                                                    reason_message=error_msg,
                                                )
                                            except Exception as store_err:
                                                logger.debug(f"Failed to store ORDER FAILED message: {store_err}")
                                        else:
                                            # Order created successfully
                                            order_id = order_result.get("order_id")
                                            exchange_order_id = order_result.get("exchange_order_id")
                                            self._upsert_watchlist_signal_state(
                                                db,
                                                symbol=normalized_symbol,
                                                trade_status="SUBMITTED",
                                                trade_block_reason=None,
                                                last_trade_at_utc=now_utc,
                                                correlation_id=evaluation_id,
                                            )
                                            logger.info(f"[ORCHESTRATOR] {symbol} SELL Order created successfully: order_id={order_id}, exchange_order_id={exchange_order_id}")
                                            update_order_intent_status(
                                                db=db,
                                                order_intent_id=order_intent.id,
                                                status="ORDER_PLACED",
                                                order_id=exchange_order_id or order_id,
                                            )
                                            decision_reason = make_execute(
                                                reason_code=ReasonCode.EXEC_ORDER_PLACED.value,
                                                message=f"Order created successfully for {symbol}. order_id={exchange_order_id or order_id}",
                                                context={
                                                    "symbol": symbol,
                                                    "order_id": order_id,
                                                    "exchange_order_id": exchange_order_id,
                                                },
                                                source="orchestrator",
                                            )
                                            update_telegram_message_decision_trace(
                                                db=db,
                                                symbol=symbol,
                                                message_pattern="SELL SIGNAL",
                                                decision_type="EXECUTED",
                                                reason_code=decision_reason.reason_code,
                                                reason_message=decision_reason.reason_message,
                                                context_json=decision_reason.context,
                                                correlation_id=str(uuid_module.uuid4()),
                                            )
                                    except Exception as order_err:
                                        # Order creation exception
                                        error_msg = str(order_err)[:500]
                                        logger.error(f"[ORCHESTRATOR] {symbol} SELL Order creation exception: {order_err}", exc_info=True)
                                        self._upsert_watchlist_signal_state(
                                            db,
                                            symbol=normalized_symbol,
                                            trade_status="BLOCKED",
                                            trade_block_reason="EXCHANGE_ERROR",
                                            last_trade_at_utc=now_utc,
                                            correlation_id=evaluation_id,
                                        )
                                        update_order_intent_status(
                                            db=db,
                                            order_intent_id=order_intent.id,
                                            status="ORDER_FAILED",
                                            error_message=error_msg,
                                        )
                                        
                                        # Classify error for strict reporting
                                        from app.utils.decision_reason import classify_exchange_error
                                        reason_code = classify_exchange_error(error_msg)
                                        
                                        decision_reason = make_fail(
                                            reason_code=reason_code,
                                            message=f"Order creation failed for {symbol} SELL: {error_msg}",
                                            context={"symbol": symbol, "error": error_msg},
                                            source="orchestrator",
                                            exchange_error=error_msg,
                                        )
                                        update_telegram_message_decision_trace(
                                            db=db,
                                            symbol=symbol,
                                            message_pattern="SELL SIGNAL",
                                            decision_type="FAILED",
                                            reason_code=decision_reason.reason_code,
                                            reason_message=decision_reason.reason_message,
                                            context_json=decision_reason.context,
                                            exchange_error_snippet=decision_reason.exchange_error,
                                            correlation_id=str(uuid_module.uuid4()),
                                        )
                                        
                                        # Send Telegram failure message (required)
                                        try:
                                            from app.services.telegram_notifier import telegram_notifier
                                            telegram_notifier.send_message(
                                                f"❌ <b>ORDER FAILED</b>\n\n"
                                                f"📊 Symbol: <b>{symbol}</b>\n"
                                                f"🔄 Side: SELL\n"
                                                f"❌ Error: {error_msg}\n\n"
                                                f"<i>Signal was sent but order creation failed.</i>"
                                            )
                                        except Exception as telegram_err:
                                            logger.warning(f"Failed to send Telegram failure message: {telegram_err}")
                                        try:
                                            from app.api.routes_monitoring import add_telegram_message
                                            add_telegram_message(
                                                f"❌ ORDER FAILED | {symbol} SELL | {error_msg}",
                                                symbol=symbol,
                                                blocked=False,
                                                decision_type="FAILED",
                                                reason_code=reason_code,
                                                reason_message=error_msg,
                                            )
                                        except Exception as store_err:
                                            logger.debug(f"Failed to store ORDER FAILED message: {store_err}")
                            except Exception as orchestrator_err:
                                # Orchestrator error - log but don't fail the signal
                                logger.error(f"[ORCHESTRATOR] {symbol} SELL Orchestrator error: {orchestrator_err}", exc_info=True)
                            
                            # CRITICAL: Record signal event in BD ONLY after successful send to prevent duplicate alerts
                            try:
                                # Build comprehensive reason
                                emit_reason_parts = []
                                if sell_reason:
                                    emit_reason_parts.append(sell_reason)
                                # CANONICAL: BUY and SELL are independent - no side change reset logic
                                if last_sell_snapshot is None or last_sell_snapshot.timestamp is None:
                                    emit_reason_parts.append("First signal for this side/strategy")
                                emit_reason = " | ".join(emit_reason_parts) if emit_reason_parts else "ALERT_SENT"
                                record_signal_event(
                                    db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="SELL",
                                    price=current_price,
                                    source="alert",
                                    emit_reason=emit_reason,
                                    config_hash=config_hash_current,
                                )
                                sell_state_recorded = True
                            except Exception as state_err:
                                logger.warning(f"Failed to persist SELL throttle state for {symbol}: {state_err}")
                        
                        # ========================================================================
                        # CREAR ORDEN SELL AUTOMÁTICA: Si trade_enabled=True y trade_amount_usd > 0
                        # ========================================================================
                        # CRITICAL: Refresh trade_enabled and trade_amount_usd from database before checking
                        # This ensures we use the latest values even if they were just changed in the dashboard
                        db.expire_all()  # Force refresh from database
                        try:
                            fresh_trade_check = db.query(WatchlistItem).filter(
                                WatchlistItem.symbol == symbol
                            ).first()
                            if fresh_trade_check:
                                trade_enabled = getattr(fresh_trade_check, 'trade_enabled', False)
                                trade_amount_usd = getattr(fresh_trade_check, 'trade_amount_usd', None)
                                logger.debug(f"🔄 Última verificación de trade_enabled para {symbol}: trade_enabled={trade_enabled}, trade_amount_usd={trade_amount_usd}")
                                # Update watchlist_item with fresh values
                                watchlist_item.trade_enabled = trade_enabled
                                watchlist_item.trade_amount_usd = trade_amount_usd
                        except Exception as e:
                            logger.warning(f"Error en última verificación de trade_enabled para {symbol}: {e}")
                            # Use existing values if refresh fails
                            trade_enabled = getattr(watchlist_item, 'trade_enabled', False)
                            trade_amount_usd = getattr(watchlist_item, 'trade_amount_usd', None)
                        
                        # DIAGNOSTIC: Log order creation check for TRX_USDT
                        if symbol == "TRX_USDT" or symbol == "TRX_USD":
                            logger.info(
                                f"🔍 [DIAGNOSTIC] {symbol} SELL order creation check: "
                                f"trade_enabled={watchlist_item.trade_enabled}, "
                                f"trade_amount_usd={watchlist_item.trade_amount_usd}, "
                                f"balance_check_warning={balance_check_warning is not None}, "
                                f"will_create_order={'YES' if (watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 and not balance_check_warning) else 'NO'}"
                            )
                        
                        if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                            # Skip order creation if early balance check already detected insufficient balance
                            # We already warned in the alert, so don't try to create order and send duplicate message
                            if balance_check_warning:
                                logger.info(
                                    f"🚫 Trade enabled for {symbol} but skipping SELL order creation - "
                                    f"insufficient balance already detected and warned in alert"
                                )
                            else:
                                logger.info(f"🔴 Trade enabled for {symbol} - creating SELL order automatically after alert")
                                
                                # DIAGNOSTIC: Log before calling _create_sell_order for TRX_USDT
                                if symbol == "TRX_USDT" or symbol == "TRX_USD":
                                    logger.info(
                                        f"🔍 [DIAGNOSTIC] {symbol} Calling _create_sell_order: "
                                        f"current_price={current_price}, "
                                        f"trade_amount_usd={watchlist_item.trade_amount_usd}, "
                                        f"trade_on_margin={getattr(watchlist_item, 'trade_on_margin', False)}"
                                    )
                                
                                try:
                                    # Use asyncio.run() to execute async function from sync context
                                    import asyncio
                                    order_result = asyncio.run(self._create_sell_order(db, watchlist_item, current_price, res_up, res_down))
                                    
                                    # DIAGNOSTIC: Log result for TRX_USDT
                                    if symbol == "TRX_USDT" or symbol == "TRX_USD":
                                        logger.info(
                                            f"🔍 [DIAGNOSTIC] {symbol} _create_sell_order result: "
                                            f"result_type={type(order_result).__name__}, "
                                            f"has_error={'error' in order_result if isinstance(order_result, dict) else 'N/A'}, "
                                            f"result={order_result}"
                                        )
                                    # Check for errors first (error dicts are truthy but have "error" key)
                                    if order_result and isinstance(order_result, dict) and "error" in order_result:
                                        # Handle error cases
                                        error_type = order_result.get("error_type")
                                        error_msg = order_result.get("message")
                                        if error_type == "balance":
                                            logger.warning(f"⚠️ SELL order creation blocked for {symbol}: Insufficient balance - {error_msg}")
                                        elif error_type == "trade_disabled":
                                            logger.warning(f"🚫 SELL order creation blocked for {symbol}: Trade is disabled - {error_msg}")
                                        elif error_type == "authentication":
                                            logger.error(f"❌ SELL order creation failed for {symbol}: Authentication error - {error_msg}")
                                        elif error_type == "order_placement":
                                            logger.error(f"❌ SELL order creation failed for {symbol}: Order placement error - {error_msg}")
                                        elif error_type == "no_order_id":
                                            logger.error(f"❌ SELL order creation failed for {symbol}: No order ID returned - {error_msg}")
                                        elif error_type == "exception":
                                            logger.error(f"❌ SELL order creation failed for {symbol}: Exception - {error_msg}")
                                        else:
                                            logger.warning(f"⚠️ SELL order creation failed for {symbol} (error_type: {error_type}, reason: {error_msg or 'unknown'})")
                                    elif order_result:
                                        # Success case - order was created
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
                                                    emit_reason="Order created",
                                                )
                                                sell_state_recorded = True
                                            except Exception as state_err:
                                                logger.warning(f"Failed to persist SELL throttle state after order for {symbol}: {state_err}")
                                    else:
                                        # order_result is None or falsy
                                        logger.warning(f"⚠️ SELL order creation returned None for {symbol} (unknown reason)")
                                except Exception as order_err:
                                    logger.error(f"❌ SELL order creation failed for {symbol}: {order_err}", exc_info=True)
                                    # Don't raise - alert was sent, order creation is secondary
                        else:
                            # Log specific reason why order wasn't created
                            reasons = []
                            if not watchlist_item.trade_enabled:
                                reasons.append("trade_enabled=False")
                            if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                                reasons.append(f"trade_amount_usd={'not configured' if not watchlist_item.trade_amount_usd else f'{watchlist_item.trade_amount_usd} (invalid)'}")
                            
                            # DIAGNOSTIC: Enhanced logging for TRX_USDT
                            if symbol == "TRX_USDT" or symbol == "TRX_USD":
                                logger.warning(
                                    f"🔍 [DIAGNOSTIC] {symbol} SELL order NOT created - "
                                    f"trade_enabled={watchlist_item.trade_enabled}, "
                                    f"trade_amount_usd={watchlist_item.trade_amount_usd}, "
                                    f"reasons: {', '.join(reasons)}"
                                )
                            
                            logger.warning(
                                f"🚫 SELL alert sent for {symbol} but order NOT created - "
                                f"Reasons: {', '.join(reasons)}. "
                                f"To enable automatic SELL orders, set trade_enabled=True and trade_amount_usd > 0 in watchlist configuration."
                            )
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram SELL alert for {symbol}: {e}")
                        # If sending failed, do NOT update the state - allow retry on next cycle
                        # Remove lock to allow retry
                        if lock_key in self.alert_sending_locks:
                            del self.alert_sending_locks[lock_key]
                    
                    # Always remove lock when done (if not already removed)
                    if lock_key in self.alert_sending_locks:
                        del self.alert_sending_locks[lock_key]
        
        # ========================================================================
        # FORCE DIAGNOSTIC PATH: Run SELL order creation checks even when signal is WAIT
        # This allows testing diagnostics without waiting for a real SELL signal
        # ========================================================================
        should_force_diagnostic = (
            (FORCE_SELL_DIAGNOSTIC and symbol == "TRX_USDT") or
            (FORCE_SELL_DIAGNOSTIC_SYMBOL and symbol.upper() == FORCE_SELL_DIAGNOSTIC_SYMBOL.upper())
        )
        
        if should_force_diagnostic and not sell_signal:
            logger.info(
                f"🔧 [FORCE_DIAGNOSTIC] Running SELL order creation diagnostics for {symbol} "
                f"(signal=WAIT, but diagnostics forced via env flag) | DRY_RUN=True (no order will be placed)"
            )
            
            try:
                # ========================================================================
                # PREFLIGHT CHECK 1: Refresh trade flags from database
                # ========================================================================
                db.expire_all()
                fresh_trade_check = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
                if fresh_trade_check:
                    trade_enabled = getattr(fresh_trade_check, 'trade_enabled', False)
                    trade_amount_usd = getattr(fresh_trade_check, 'trade_amount_usd', None)
                    watchlist_item.trade_enabled = trade_enabled
                    watchlist_item.trade_amount_usd = trade_amount_usd
                
                logger.info(
                    f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 1 - Trade flags: "
                    f"trade_enabled={watchlist_item.trade_enabled}, "
                    f"trade_amount_usd={watchlist_item.trade_amount_usd}, "
                    f"trade_on_margin={getattr(watchlist_item, 'trade_on_margin', False)}"
                )
                
                # ========================================================================
                # PREFLIGHT CHECK 2: Validate trade_enabled and trade_amount_usd
                # ========================================================================
                if not watchlist_item.trade_enabled:
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 2 - BLOCKED: trade_enabled=False"
                    )
                elif not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 2 - BLOCKED: trade_amount_usd={watchlist_item.trade_amount_usd} (invalid or not set)"
                    )
                else:
                    logger.info(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 2 - PASSED: trade_enabled=True, trade_amount_usd=${watchlist_item.trade_amount_usd:,.2f}"
                    )
                
                # ========================================================================
                # PREFLIGHT CHECK 3: Balance check (base currency for SELL orders)
                # ========================================================================
                balance_check_passed = False
                balance_check_warning = None
                available_balance = 0
                required_qty = 0
                base_currency = symbol.split('_')[0] if '_' in symbol else symbol
                
                if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                    user_wants_margin_check = getattr(watchlist_item, 'trade_on_margin', False)
                    
                    if user_wants_margin_check:
                        logger.info(
                            f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 3 - SKIPPED: Margin trading enabled "
                            f"(balance check not performed for margin orders)"
                        )
                        balance_check_passed = True  # Margin orders skip balance check
                    else:
                        try:
                            account_summary = trade_client.get_account_summary()
                            
                            if 'accounts' in account_summary or 'data' in account_summary:
                                accounts = account_summary.get('accounts') or account_summary.get('data', {}).get('accounts', [])
                                for acc in accounts:
                                    currency = acc.get('currency', '').upper()
                                    if currency == base_currency:
                                        available = float(acc.get('available', '0') or '0')
                                        available_balance = available
                                        break
                            
                            required_qty = watchlist_item.trade_amount_usd / current_price
                            
                            logger.info(
                                f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 3 - Balance check: "
                                f"base_currency={base_currency}, "
                                f"available={available_balance:.8f} {base_currency}, "
                                f"required={required_qty:.8f} {base_currency} "
                                f"(from trade_amount_usd=${watchlist_item.trade_amount_usd:,.2f} / current_price=${current_price:.8f})"
                            )
                            
                            if available_balance < required_qty:
                                balance_check_warning = (
                                    f"Insufficient balance: Available={available_balance:.8f} {base_currency} < "
                                    f"Required={required_qty:.8f} {base_currency}"
                                )
                                logger.warning(
                                    f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 3 - BLOCKED: {balance_check_warning}"
                                )
                                balance_check_passed = False
                            else:
                                logger.info(
                                    f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 3 - PASSED: "
                                    f"Sufficient balance ({available_balance:.8f} >= {required_qty:.8f} {base_currency})"
                                )
                                balance_check_passed = True
                        except Exception as balance_check_err:
                            logger.warning(
                                f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 3 - ERROR: Balance check failed: {balance_check_err}"
                            )
                            balance_check_passed = False
                
                # ========================================================================
                # PREFLIGHT CHECK 4: Live trading status
                # ========================================================================
                try:
                    from app.utils.live_trading import get_live_trading_status
                    live_trading = get_live_trading_status(db)
                    dry_run_mode = not live_trading
                    logger.info(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 4 - Live trading: "
                        f"live_trading={live_trading}, dry_run_mode={dry_run_mode}"
                    )
                except Exception as live_check_err:
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 4 - ERROR: Could not check live trading status: {live_check_err}"
                    )
                    dry_run_mode = True  # Default to dry run on error
                
                # ========================================================================
                # PREFLIGHT CHECK 5: Open orders constraints
                # ========================================================================
                open_orders_status = "unknown"
                base_symbol = symbol.split('_')[0] if '_' in symbol else symbol
                try:
                    from app.services.order_position_service import count_open_positions_for_symbol
                    base_open = count_open_positions_for_symbol(db, base_symbol)
                    MAX_OPEN_ORDERS_PER_SYMBOL = self.MAX_OPEN_ORDERS_PER_SYMBOL
                    
                    if base_open >= MAX_OPEN_ORDERS_PER_SYMBOL:
                        open_orders_status = f"BLOCKED ({base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} limit reached)"
                        logger.warning(
                            f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 5 - BLOCKED: "
                            f"Open orders limit reached: {base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} for {base_symbol}"
                        )
                    else:
                        open_orders_status = f"OK ({base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL})"
                        logger.info(
                            f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 5 - PASSED: "
                            f"Open orders: {base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} for {base_symbol}"
                        )
                except Exception as open_orders_err:
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 5 - ERROR: Could not check open orders: {open_orders_err}"
                    )
                    open_orders_status = "check_failed"
                
                # ========================================================================
                # PREFLIGHT CHECK 6: Margin settings (if margin trading)
                # ========================================================================
                margin_settings = "N/A"
                if getattr(watchlist_item, 'trade_on_margin', False):
                    try:
                        from app.services.margin_decision_helper import decide_trading_mode, log_margin_decision, DEFAULT_CONFIGURED_LEVERAGE
                        trading_decision = decide_trading_mode(
                            symbol=symbol,
                            configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
                            user_wants_margin=getattr(watchlist_item, 'trade_on_margin', False)
                        )
                        margin_settings = f"margin={trading_decision.use_margin}, leverage={trading_decision.leverage}"
                        logger.info(
                            f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 6 - Margin settings: "
                            f"use_margin={trading_decision.use_margin}, "
                            f"leverage={trading_decision.leverage}"
                        )
                    except Exception as margin_check_err:
                        logger.warning(
                            f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 6 - ERROR: Margin check failed: {margin_check_err}"
                        )
                        margin_settings = "check_failed"
                else:
                    margin_settings = "spot_trading"
                    logger.info(
                        f"🔍 [DIAGNOSTIC] {symbol} PREFLIGHT CHECK 6 - Margin settings: spot_trading (margin disabled)"
                    )
                
                # ========================================================================
                # FINAL DECISION: Would order be created?
                # ========================================================================
                # CRITICAL: In forced diagnostic mode, NEVER create real orders
                # This guard ensures even if code path changes, no order is placed
                FORCE_DIAGNOSTIC_DRY_RUN = True  # Explicit guard - cannot be overridden
                
                would_create_order = (
                    watchlist_item.trade_enabled and
                    watchlist_item.trade_amount_usd and
                    watchlist_item.trade_amount_usd > 0 and
                    balance_check_passed
                )
                
                # Build blocking reasons list
                blocking_reasons = []
                if not watchlist_item.trade_enabled:
                    blocking_reasons.append("trade_enabled=False")
                if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                    blocking_reasons.append(f"trade_amount_usd invalid ({watchlist_item.trade_amount_usd})")
                if not balance_check_passed:
                    if balance_check_warning:
                        blocking_reasons.append(balance_check_warning)
                    else:
                        blocking_reasons.append("balance check failed")
                
                # Get live trading status for summary
                live_trading_status = False
                try:
                    from app.utils.live_trading import get_live_trading_status
                    live_trading_status = get_live_trading_status(db)
                except Exception:
                    pass
                
                # Check if open orders would block (add to blocking reasons if applicable)
                if open_orders_status.startswith("BLOCKED"):
                    blocking_reasons.append(f"open_orders_limit ({open_orders_status})")
                    would_create_order = False  # Override decision if open orders limit reached
                
                # Structured summary log (single line with all key info)
                final_decision = "WOULD_CREATE" if would_create_order else "BLOCKED"
                blocking_reasons_str = ", ".join(blocking_reasons) if blocking_reasons else "none"
                
                logger.info(
                    f"🔍 [DIAGNOSTIC] FINAL symbol={symbol} "
                    f"decision={final_decision} "
                    f"reasons=[{blocking_reasons_str}] "
                    f"required_qty={required_qty:.8f} "
                    f"avail_base={available_balance:.8f} "
                    f"open_orders={open_orders_status} "
                    f"live_trading={live_trading_status} "
                    f"trade_enabled={watchlist_item.trade_enabled} "
                    f"DRY_RUN=True"
                )
                
                if would_create_order:
                    calculated_qty = watchlist_item.trade_amount_usd / current_price
                    logger.info(
                        f"🔍 [DIAGNOSTIC] {symbol} Order details (DRY_RUN): "
                        f"symbol={symbol}, "
                        f"side=SELL, "
                        f"amount_usd=${watchlist_item.trade_amount_usd:,.2f}, "
                        f"current_price=${current_price:.8f}, "
                        f"calculated_qty={calculated_qty:.8f} {base_currency}, "
                        f"margin={getattr(watchlist_item, 'trade_on_margin', False)}"
                    )
                    # CRITICAL: Explicit guard - log that order is suppressed
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} DRY_RUN – order suppressed | "
                        f"Would call _create_sell_order but FORCE_DIAGNOSTIC_DRY_RUN=True prevents execution"
                    )
                else:
                    logger.warning(
                        f"🔍 [DIAGNOSTIC] {symbol} Order would NOT be created (DRY_RUN): "
                        f"blocking_reasons=[{blocking_reasons_str}]"
                    )
            except Exception as diag_err:
                logger.error(
                    f"🔍 [DIAGNOSTIC] {symbol} Force diagnostic failed: {diag_err}",
                    exc_info=True
                )
        
        # Handle SELL signal state update (for internal tracking) - same level as BUY block (line 1554)
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
        symbol = normalize_symbol_for_exchange(watchlist_item.symbol)
        
        # Resolve strategy for event emission
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        
        # CRITICAL: Double-check trade_enabled flag before proceeding
        # This prevents order creation attempts when trade_enabled is False
        if not getattr(watchlist_item, 'trade_enabled', False):
            logger.warning(
                f"🚫 Blocked BUY order creation for {symbol}: trade_enabled=False. "
                f"This function should not be called when trade is disabled."
            )
            # Create DecisionReason for SKIP
            from app.utils.decision_reason import make_skip, ReasonCode
            import uuid
            correlation_id = str(uuid.uuid4())
            decision_reason = make_skip(
                reason_code=ReasonCode.TRADE_DISABLED.value,
                message=f"Trade is disabled for {symbol}. trade_enabled=False.",
                context={
                    "symbol": symbol,
                    "trade_enabled": False,
                    "trade_amount_usd": getattr(watchlist_item, 'trade_amount_usd', None),
                    "price": current_price,
                },
                source="precheck",
                correlation_id=correlation_id,
            )
            self._log_pipeline_stage(
                stage="BUY_BLOCKED",
                symbol=normalize_symbol_for_exchange(symbol),
                strategy_key=strategy_key,
                decision="BUY",
                last_price=current_price,
                timestamp=datetime.now(timezone.utc).isoformat(),
                correlation_id=correlation_id,
                reason="TRADE_DISABLED",
            )
            logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
            # Emit TRADE_BLOCKED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                price=current_price,
                event_type="TRADE_BLOCKED",
                event_reason="SKIP_DISABLED_TRADE",
                decision_reason=decision_reason,
            )
            return {"error": "trade_disabled", "error_type": "trade_disabled", "message": f"Trade is disabled for {symbol}"}
        
        # Validate that trade_amount_usd is configured - REQUIRED, no default
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
            logger.error(f"Cannot create BUY order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
            
            # Create DecisionReason for SKIP
            from app.utils.decision_reason import make_skip, ReasonCode
            import uuid
            correlation_id = str(uuid.uuid4())
            decision_reason = make_skip(
                reason_code=ReasonCode.INVALID_TRADE_AMOUNT.value,
                message=f"Invalid trade amount for {symbol}. trade_amount_usd={watchlist_item.trade_amount_usd}.",
                context={
                    "symbol": symbol,
                    "trade_enabled": getattr(watchlist_item, 'trade_enabled', False),
                    "trade_amount_usd": watchlist_item.trade_amount_usd,
                    "price": current_price,
                },
                source="precheck",
                correlation_id=correlation_id,
            )
            logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
            # Emit TRADE_BLOCKED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                price=current_price,
                event_type="TRADE_BLOCKED",
                event_reason="SKIP_INVALID_TRADE_AMOUNT",
                error_message=f"trade_amount_usd={watchlist_item.trade_amount_usd}",
                decision_reason=decision_reason,
            )
            
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
        
        # Read trade_on_margin from database FIRST - CRITICAL for margin trading
        # This must be read BEFORE balance check to avoid blocking margin orders
        user_wants_margin = watchlist_item.trade_on_margin or False
        
        # ========================================================================
        # VERIFICACIÓN PREVIA: Balance disponible antes de crear orden
        # ========================================================================
        # Verificar balance disponible ANTES de intentar crear la orden
        # Esto previene errores 306 (INSUFFICIENT_AVAILABLE_BALANCE) para SPOT
        # IMPORTANTE: Solo verificar balance SPOT si NO se está usando margen
        # Para órdenes con margen, el margen disponible se calcula de manera diferente
        # y no podemos verificar aquí (el exchange lo manejará)
        if not user_wants_margin:
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
                logger.info(f"💰 Balance check para {symbol} (SPOT): available=${available_balance:,.2f}, required=${spot_required:,.2f} para ${amount_usd:,.2f} orden SPOT")
                
                # Si no hay suficiente balance para SPOT, no intentar crear la orden
                if available_balance < spot_required:
                    logger.warning(
                        f"🚫 BLOQUEO POR BALANCE: {symbol} - Balance insuficiente para orden SPOT. "
                        f"Available: ${available_balance:,.2f} < Required: ${spot_required:,.2f}. "
                        f"No se intentará crear la orden para evitar error 306."
                    )
                    # Create DecisionReason for SKIP
                    from app.utils.decision_reason import make_skip, ReasonCode
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    decision_reason = make_skip(
                        reason_code=ReasonCode.INSUFFICIENT_AVAILABLE_BALANCE.value,
                        message=f"Insufficient balance for SPOT order for {symbol}. Available: ${available_balance:,.2f} < Required: ${spot_required:,.2f}.",
                        context={
                            "symbol": symbol,
                            "available_balance": available_balance,
                            "required_balance": spot_required,
                            "amount_usd": amount_usd,
                            "price": current_price,
                            "order_type": "SPOT",
                        },
                        source="precheck",
                        correlation_id=correlation_id,
                    )
                    logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                    # Emit TRADE_BLOCKED event with DecisionReason
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="TRADE_BLOCKED",
                        event_reason="INSUFFICIENT_BALANCE",
                        decision_reason=decision_reason,
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
        else:
            logger.info(f"💰 MARGIN TRADING activado para {symbol} - Saltando verificación de balance SPOT (el margen disponible se calcula de manera diferente)")
        
        # ========================================================================
        # VERIFICACIÓN: Bloqueo temporal por error 609 (INSUFFICIENT_MARGIN)
        # ========================================================================
        # Si este símbolo tuvo un error 609 recientemente, forzar SPOT en lugar de MARGIN
        # para evitar reintentos innecesarios que seguirán fallando
        # Use time module (already imported at top of file)
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
                # Create DecisionReason for SKIP
                from app.utils.decision_reason import make_skip, ReasonCode
                import uuid
                correlation_id = str(uuid.uuid4())
                decision_reason = make_skip(
                    reason_code=ReasonCode.MAX_OPEN_TRADES_REACHED.value,
                    message=f"Maximum open orders reached for {symbol}. {base_symbol}={base_open}/{MAX_OPEN_ORDERS_PER_SYMBOL} (global={total_open_buy_orders_final}).",
                    context={
                        "symbol": symbol,
                        "base_symbol": base_symbol,
                        "open_positions": base_open,
                        "max_open_orders": MAX_OPEN_ORDERS_PER_SYMBOL,
                        "global_open": total_open_buy_orders_final,
                        "price": current_price,
                    },
                    source="guardrail",
                    correlation_id=correlation_id,
                )
                logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                # Emit TRADE_BLOCKED event with DecisionReason
                _emit_lifecycle_event(
                    db=db,
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side="BUY",
                    price=current_price,
                    event_type="TRADE_BLOCKED",
                    event_reason="MAX_OPEN_ORDERS_REACHED",
                    decision_reason=decision_reason,
                )
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
            # Create DecisionReason for SKIP
            from app.utils.decision_reason import make_skip, ReasonCode
            import uuid
            correlation_id = str(uuid.uuid4())
            decision_reason = make_skip(
                reason_code=ReasonCode.RECENT_ORDERS_COOLDOWN.value,
                message=f"Recent orders cooldown active for {symbol}. Found {final_recent_orders} recent BUY order(s) within 5 minutes.",
                context={
                    "symbol": symbol,
                    "recent_orders_count": final_recent_orders,
                    "cooldown_minutes": 5,
                    "price": current_price,
                },
                source="guardrail",
                correlation_id=correlation_id,
            )
            logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
            # Emit TRADE_BLOCKED event with DecisionReason
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                price=current_price,
                event_type="TRADE_BLOCKED",
                event_reason="RECENT_ORDERS_COOLDOWN",
                decision_reason=decision_reason,
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
            
            # Check trading guardrails before order placement
            from app.utils.trading_guardrails import can_place_real_order
            allowed, block_reason = can_place_real_order(
                db=db,
                symbol=symbol,
                order_usd_value=amount_usd,
                side="BUY",
            )
            if not allowed:
                # Create DecisionReason for SKIP
                from app.utils.decision_reason import make_skip, ReasonCode
                import uuid
                correlation_id = str(uuid.uuid4())
                decision_reason = make_skip(
                    reason_code=ReasonCode.GUARDRAIL_BLOCKED.value,
                    message=f"Trading guardrail blocked order for {symbol}: {block_reason}",
                    context={
                        "symbol": symbol,
                        "price": current_price,
                        "amount_usd": amount_usd,
                        "guardrail_reason": block_reason,
                    },
                    source="guardrail",
                    correlation_id=correlation_id,
                )
                logger.info(f"[DECISION] symbol={symbol} decision=SKIPPED reason={decision_reason.reason_code} context={decision_reason.context}")
                # Emit TRADE_BLOCKED lifecycle event
                _emit_lifecycle_event(
                    db=db,
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side="BUY",
                    price=current_price,
                    event_type="TRADE_BLOCKED",
                    event_reason=block_reason,
                    decision_reason=decision_reason,
                )
                # Send Telegram alert
                try:
                    telegram_notifier.send_message(
                        f"🚫 <b>TRADE BLOCKED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔄 Side: BUY\n"
                        f"💵 Value: ${amount_usd:.2f}\n\n"
                        f"🚫 <b>Reason:</b> {block_reason}",
                        symbol=symbol,
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram alert for blocked order: {e}")
                
                logger.warning(f"🚫 TRADE_BLOCKED: {symbol} BUY - {block_reason}")
                return None  # Block order
            
            # Emit ORDER_ATTEMPT event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                price=current_price,
                event_type="ORDER_ATTEMPT",
                event_reason=f"notional={amount_usd}, margin={use_margin}, leverage={leverage_value}",
            )
            
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
                # AUTHENTICATION ERROR HANDLING: Do NOT attempt fallbacks for auth errors
                # ========================================================================
                # Authentication errors (401, 40101, 40103) indicate API credential or IP whitelist issues
                # These cannot be fixed by trying SPOT instead of MARGIN or reducing leverage
                # We should fail immediately with a clear error message
                error_msg_str = str(error_msg).upper() if error_msg else ""
                is_auth_error = (
                    "401" in error_msg_str or
                    "40101" in error_msg_str or
                    "40103" in error_msg_str or
                    "AUTHENTICATION FAILED" in error_msg_str or
                    "AUTHENTICATION FAILURE" in error_msg_str
                )
                
                if is_auth_error:
                    logger.error(
                        f"🔐 AUTHENTICATION ERROR detected for {symbol}: {error_msg}. "
                        f"This is a configuration issue (API keys, IP whitelist) and cannot be fixed by fallbacks."
                    )
                    # Send specific authentication error notification
                    try:
                        telegram_notifier.send_message(
                            f"🔐 <b>AUTOMATIC ORDER CREATION FAILED: AUTHENTICATION ERROR</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🟢 Side: BUY\n"
                            f"💰 Amount: ${amount_usd:,.2f}\n"
                            f"📊 Type: {'MARGIN' if use_margin else 'SPOT'}\n"
                            f"❌ Error: <b>Authentication failed: {error_msg}</b>\n\n"
                            f"⚠️ <b>This is a configuration issue:</b>\n"
                            f"• Check API credentials (API key and secret)\n"
                            f"• Verify IP address is whitelisted in Crypto.com Exchange\n"
                            f"• Ensure API key has trading permissions\n"
                            f"• Check if API key is expired or revoked\n\n"
                            f"📊 Trade enabled status: True (order was attempted because trade_enabled=True at that time)\n\n"
                            f"⚠️ The symbol remains in your watchlist. Please fix the authentication configuration and try again."
                        )
                    except Exception as notify_err:
                        logger.warning(f"Failed to send Telegram authentication error notification: {notify_err}")
                    
                    # Return error details instead of None so callers can detect authentication errors
                    # and skip sending redundant generic error messages
                    return {"error": "authentication", "error_type": "authentication", "message": error_msg}
                
                # ========================================================================
                # FALLBACK 1: Error 609 (INSUFFICIENT_MARGIN) - No hay suficiente margen disponible
                # ========================================================================
                # Si falla con error 609, significa que la cuenta no tiene suficiente margen
                # En este caso, intentar automáticamente con SPOT en lugar de MARGIN
                if use_margin and error_msg and ("609" in error_msg or "INSUFFICIENT_MARGIN" in error_msg.upper()):
                    # Activar bloqueo temporal inmediatamente para evitar reintentos con margen
                    # Use time module (already imported at top of file)
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
                            # Use time module (already imported at top of file)
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
                        # Use time module (already imported at top of file)
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
                    
                    # CRITICAL: Verify trade_enabled state from database to ensure accuracy in error message
                    # This helps debug cases where dashboard shows different value than when order was attempted
                    db.expire_all()  # Force refresh from database
                    current_trade_enabled = None
                    try:
                        fresh_trade_verification = db.query(WatchlistItem).filter(
                            WatchlistItem.symbol == symbol
                        ).first()
                        if fresh_trade_verification:
                            current_trade_enabled = getattr(fresh_trade_verification, 'trade_enabled', False)
                            logger.info(
                                f"🔍 [ORDER_FAILURE] {symbol} - Verifying trade_enabled state: "
                                f"current_db_value={current_trade_enabled}, "
                                f"watchlist_item_value={getattr(watchlist_item, 'trade_enabled', None)}"
                            )
                    except Exception as verify_err:
                        logger.warning(f"⚠️ Could not verify trade_enabled state for {symbol} after order failure: {verify_err}")
                    
                    # Create DecisionReason for FAIL
                    from app.utils.decision_reason import make_fail, classify_exchange_error
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    reason_code = classify_exchange_error(error_msg)
                    decision_reason = make_fail(
                        reason_code=reason_code,
                        message=f"Buy order failed for {symbol}: {error_msg}",
                        context={
                            "symbol": symbol,
                            "price": current_price,
                            "amount_usd": amount_usd,
                            "use_margin": use_margin,
                            "leverage": leverage_value,
                            "dry_run": dry_run_mode,
                            "trade_enabled": current_trade_enabled if current_trade_enabled is not None else getattr(watchlist_item, 'trade_enabled', None),
                        },
                        exchange_error=error_msg,
                        source="exchange",
                        correlation_id=correlation_id,
                    )
                    logger.error(f"[DECISION] symbol={symbol} decision=FAILED reason={decision_reason.reason_code} exchange_error={error_msg[:200]}")
                    # Emit ORDER_FAILED event
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="BUY",
                        price=current_price,
                        event_type="ORDER_FAILED",
                        event_reason="order_placement_failed",
                        error_message=error_msg,
                        decision_reason=decision_reason,
                    )
                    
                    # CRITICAL: Update the original BUY SIGNAL message with decision tracing (BR-4)
                    try:
                        from app.api.routes_monitoring import update_telegram_message_decision_trace
                        update_telegram_message_decision_trace(
                            db=db,
                            symbol=symbol,
                            message_pattern="BUY SIGNAL",
                            decision_type="FAILED",
                            reason_code=decision_reason.reason_code,
                            reason_message=decision_reason.reason_message,
                            context_json=decision_reason.context,
                            exchange_error_snippet=decision_reason.exchange_error_snippet,
                            correlation_id=decision_reason.correlation_id,
                        )
                    except Exception as update_err:
                        logger.warning(f"Failed to update original BUY SIGNAL message for {symbol} on ORDER_FAILED: {update_err}")
                    
                    # Send Telegram notification about the error
                    try:
                        error_details = error_msg
                        if use_margin:
                            error_details += "\n\n⚠️ <b>MARGIN ORDER FAILED</b> - Insufficient margin balance available.\nThe account may be over-leveraged or margin trading may not be enabled."
                        
                        # Include trade_enabled state in error message for debugging
                        trade_status_note = ""
                        if current_trade_enabled is not None:
                            trade_status_note = f"\n📊 Trade enabled status: {current_trade_enabled} (order was attempted because trade_enabled=True at that time)"
                        
                        telegram_notifier.send_message(
                            f"❌ <b>AUTOMATIC ORDER CREATION FAILED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🟢 Side: BUY\n"
                            f"💰 Amount: ${amount_usd:,.2f}\n"
                            f"📊 Type: {'MARGIN' if use_margin else 'SPOT'}\n"
                            f"❌ Error: {error_details}{trade_status_note}\n\n"
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
            buy_alert_sent_successfully = False
            if DEBUG_TRADING:
                logger.info(f"[DEBUG_TRADING] {symbol} BUY: About to send Telegram notification for order {order_id}")
            try:
                # CRITICAL: Explicitly pass origin to ensure notifications are sent
                alert_origin = get_runtime_origin()
                if DEBUG_TRADING:
                    logger.info(f"[DEBUG_TRADING] {symbol} BUY: Calling send_order_created with origin={alert_origin}")
                telegram_notifier.send_order_created(
                    symbol=symbol,
                    side="BUY",
                    price=0,  # Market price will be determined at execution
                    quantity=amount_usd,  # For BUY, this is the amount in USD
                    order_id=str(order_id),
                    margin=use_margin,
                    leverage=10 if use_margin else None,
                    dry_run=dry_run_mode,
                    order_type="MARKET",
                    origin=alert_origin  # CRITICAL: Explicitly pass origin to ensure notifications are sent
                )
                buy_alert_sent_successfully = True
                logger.info(f"✅ Sent Telegram notification for automatic BUY order: {symbol} - {order_id} (origin={alert_origin})")
                if DEBUG_TRADING:
                    logger.info(f"[DEBUG_TRADING] {symbol} BUY: Telegram notification sent successfully")
            except Exception as telegram_err:
                buy_alert_sent_successfully = False
                logger.error(f"❌ Failed to send Telegram notification for BUY order creation: {telegram_err}", exc_info=True)
                if DEBUG_TRADING:
                    logger.error(f"[DEBUG_TRADING] {symbol} BUY: Telegram notification FAILED - {telegram_err}", exc_info=True)
            
            # Emit ORDER_CREATED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="BUY",
                price=filled_price or current_price,
                event_type="ORDER_CREATED",
                event_reason=f"order_id={order_id}",
                order_id=str(order_id),
            )
            
            # Save order to database (BOTH order_history_db AND ExchangeOrder for immediate visibility)
            try:
                from app.services.order_history_db import order_history_db
                # Use time module (already imported at top of file)
                
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
                
                # CRITICAL: Update the original BUY SIGNAL message with decision tracing (BR-4)
                if buy_alert_sent_successfully:
                    try:
                        from app.api.routes_monitoring import update_telegram_message_decision_trace
                        from app.utils.decision_reason import make_execute, ReasonCode
                        decision_reason = make_execute(
                            reason_code=ReasonCode.EXEC_ORDER_PLACED.value,
                            message=f"Order successfully placed: order_id={order_id}",
                            context={
                                "symbol": symbol,
                                "order_id": str(order_id),
                                "price": filled_price or current_price,
                                "quantity": estimated_qty,
                            },
                            source="exchange",
                        )
                        update_telegram_message_decision_trace(
                            db=db,
                            symbol=symbol,
                            message_pattern="BUY SIGNAL",
                            decision_type="EXECUTED",
                            reason_code=decision_reason.reason_code,
                            reason_message=decision_reason.reason_message,
                            context_json=decision_reason.context,
                            correlation_id=decision_reason.correlation_id if hasattr(decision_reason, 'correlation_id') else None,
                        )
                    except Exception as update_err:
                        logger.warning(f"Failed to update original BUY SIGNAL message for {symbol} on ORDER_CREATED: {update_err}")
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

                        # CRITICAL FIX: Create TradeSignal record and assign trade_signal_id to link automatic order
                        # This prevents automatic orders from being marked as "Manual" in Telegram notifications
                        trade_signal_id = None
                        try:
                            from app.services.signal_writer import upsert_trade_signal
                            from app.models.trade_signal import PresetEnum, RiskProfileEnum, SignalStatusEnum

                            # Create TradeSignal record for automatic order
                            trade_signal = upsert_trade_signal(
                                db=db,
                                symbol=symbol,
                                preset_enum=PresetEnum.SWING,  # Default preset for automatic orders
                                risk_profile_enum=RiskProfileEnum.CONSERVATIVE,  # Default risk profile
                                rsi=None,  # Technical indicators not available at order creation time
                                ma50=None,
                                ma200=None,
                                ema10=None,
                                ma10w=None,
                                atr=None,
                                resistance_up=None,
                                resistance_down=None,
                                entry_price=filled_price or current_price,  # Price when order was placed
                                current_price=filled_price or current_price,
                                volume_24h=None,  # Volume data not available
                                volume_ratio=None,
                                should_trade=True,  # Automatic order was created, so should_trade=True
                                status_enum=SignalStatusEnum.ORDER_PLACED,  # Status: order has been placed
                                exchange_order_id=str(order_id),  # Link to the exchange order
                                notes=f"Automatic BUY order created by signal monitor at ${filled_price or current_price:.4f}"
                            )
                            trade_signal_id = trade_signal.id
                            logger.info(f"✅ Created TradeSignal record (ID: {trade_signal_id}) for automatic BUY order: {symbol}")
                        except Exception as signal_err:
                            logger.warning(f"⚠️ Failed to create TradeSignal record for automatic order {symbol}: {signal_err}")
                            # Continue with order creation even if signal creation fails

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
                            updated_at=now_utc,
                            trade_signal_id=trade_signal_id  # CRITICAL: Link to TradeSignal to mark as automatic
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
        
        # ========================================================================
        # CRITICAL FIX: Create SL/TP orders immediately after BUY order is placed/filled
        # This restores the previous working flow where protection orders were created
        # right after buy orders, similar to how SELL orders work.
        # ========================================================================
        if DEBUG_TRADING:
            logger.info(f"[DEBUG_TRADING] {symbol} BUY: Starting SL/TP creation flow for order {order_id}")
        result_status = result.get("status", "").upper()
        is_filled_immediately = result_status in ["FILLED", "filled"]
        has_cumulative_qty = result.get("cumulative_quantity") and float(result.get("cumulative_quantity", 0) or 0) > 0
        
        filled_confirmation = None
        
        if is_filled_immediately and has_cumulative_qty:
            # Order is already filled, use data from response
            from decimal import Decimal, InvalidOperation
            cumulative_qty_raw = result.get("cumulative_quantity")
            try:
                cumulative_qty_decimal = Decimal(str(cumulative_qty_raw)) if cumulative_qty_raw else None
                avg_price_raw = result.get("avg_price")
                avg_price_value = float(avg_price_raw) if avg_price_raw else filled_price
            except (ValueError, TypeError, Exception) as e:
                logger.warning(f"⚠️ [SL/TP] Failed to parse immediate fill quantities for BUY order: {e}")
                cumulative_qty_decimal = None
                avg_price_value = filled_price
            
            if cumulative_qty_decimal and cumulative_qty_decimal > 0:
                logger.info(f"✅ [SL/TP] BUY order {order_id} already FILLED in initial response (qty={cumulative_qty_decimal})")
                filled_confirmation = {
                    "status": "FILLED",
                    "cumulative_quantity": cumulative_qty_decimal,
                    "avg_price": avg_price_value,
                    "filled_price": avg_price_value
                }
            else:
                logger.warning(f"⚠️ [SL/TP] BUY order {order_id} marked FILLED but cumulative_quantity invalid. Will poll for confirmation.")
                filled_confirmation = None
        else:
            # Order may not be filled yet - poll for confirmation
            logger.info(
                f"🔄 [SL/TP] BUY order {order_id} not immediately FILLED (status={result_status}, "
                f"has_cumulative_qty={has_cumulative_qty}). Polling for fill confirmation..."
            )
            filled_confirmation = self._poll_order_fill_confirmation(
                symbol=symbol,
                order_id=str(order_id),
                max_attempts=ORDER_FILL_POLL_MAX_ATTEMPTS,
                poll_interval=ORDER_FILL_POLL_INTERVAL_SECONDS
            )
        
        # Attempt SL/TP creation only if order is confirmed FILLED
        if filled_confirmation and filled_confirmation.get("status") == "FILLED":
            from decimal import Decimal, InvalidOperation
            
            executed_qty_raw_decimal = filled_confirmation.get("cumulative_quantity")
            executed_avg_price = filled_confirmation.get("filled_price") or filled_price
            
            if not executed_qty_raw_decimal or not isinstance(executed_qty_raw_decimal, Decimal) or executed_qty_raw_decimal <= 0:
                executed_qty_str = str(executed_qty_raw_decimal) if executed_qty_raw_decimal else "None"
                error_msg = (
                    f"BUY order {order_id} confirmed FILLED but executed quantity is invalid: {executed_qty_str}. "
                    f"Must be Decimal > 0. Cannot create SL/TP with invalid quantity."
                )
                logger.error(f"❌ [SL/TP] {error_msg}")
                
                try:
                    telegram_notifier.send_message(
                        f"🚨 <b>CRITICAL: SL/TP CREATION BLOCKED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"📋 BUY Order ID: {order_id}\n"
                        f"🟢 Side: BUY\n"
                        f"❌ Error: {error_msg}\n\n"
                        f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                        f"Please manually create protection orders or close the position."
                    )
                except Exception as alert_err:
                    logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                
                filled_quantity = float(executed_qty_raw_decimal) if executed_qty_raw_decimal and isinstance(executed_qty_raw_decimal, Decimal) else filled_quantity
            else:
                executed_qty_raw_float = float(executed_qty_raw_decimal)
                
                logger.info(
                    f"🔄 [SL/TP] Normalizing executed quantity for BUY order: raw={executed_qty_raw_decimal} (Decimal) -> {executed_qty_raw_float} (float), symbol={symbol}"
                )
                
                normalized_qty_str = trade_client.normalize_quantity(symbol, executed_qty_raw_float)
                
                if not normalized_qty_str:
                    error_msg = (
                        f"BUY order {order_id} executed quantity {executed_qty_raw_decimal} failed normalization for {symbol}. "
                        f"Cannot create SL/TP - quantity may be below minQty/stepSize or instrument rules unavailable."
                    )
                    logger.error(f"❌ [SL/TP] {error_msg}")
                    
                    try:
                        telegram_notifier.send_message(
                            f"🚨 <b>CRITICAL: SL/TP CREATION BLOCKED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"📋 BUY Order ID: {order_id}\n"
                            f"🟢 Side: BUY\n"
                            f"📦 Executed Quantity (raw): {executed_qty_raw_decimal}\n"
                            f"❌ Error: {error_msg}\n\n"
                            f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                            f"Please manually create protection orders or close the position."
                        )
                    except Exception as alert_err:
                        logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                    
                    filled_quantity = executed_qty_raw_float
                else:
                    normalized_qty = float(normalized_qty_str)
                    logger.info(
                        f"✅ [SL/TP] Quantity normalized for BUY order: raw={executed_qty_raw_decimal} (Decimal) -> normalized={normalized_qty} (string: {normalized_qty_str}) "
                        f"(symbol={symbol})"
                    )
                    
                    # IDEMPOTENCY GUARD: Check if SL/TP already exist for this order
                    from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
                    existing_sl_tp = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == str(order_id),
                        ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                    ).all()
                    
                    if existing_sl_tp:
                        existing_order_ids = [str(o.exchange_order_id) for o in existing_sl_tp]
                        logger.info(
                            f"⚠️ [SL/TP] Idempotency guard: SL/TP orders already exist for BUY order {order_id} ({symbol}): {existing_order_ids}. "
                            f"Skipping duplicate creation."
                        )
                        filled_quantity = normalized_qty
                    else:
                        # Create SL/TP orders with normalized executed quantity
                        try:
                            from app.services.exchange_sync import ExchangeSyncService
                            exchange_sync = ExchangeSyncService()
                            
                            logger.info(
                                f"🔒 [SL/TP] Creating protection orders for BUY {symbol} order {order_id}: "
                                f"filled_price={executed_avg_price}, executed_qty={normalized_qty} "
                                f"(normalized from {executed_qty_raw_decimal})"
                            )
                            
                            # Emit SLTP_ATTEMPT event
                            _emit_lifecycle_event(
                                db=db,
                                symbol=symbol,
                                strategy_key=strategy_key,
                                side="BUY",
                                price=executed_avg_price,
                                event_type="SLTP_ATTEMPT",
                                event_reason=f"primary_order_id={order_id}, filled_price={executed_avg_price}, qty={normalized_qty}",
                                order_id=str(order_id),
                            )
                            
                            # Create SL/TP orders for the filled BUY order
                            # For BUY orders: TP is SELL side (sell at profit), SL is SELL side (sell at loss)
                            if DEBUG_TRADING:
                                logger.info(f"[DEBUG_TRADING] {symbol} BUY: Calling _create_sl_tp_for_filled_order with side=BUY, price={executed_avg_price}, qty={normalized_qty}")
                            sl_tp_result = exchange_sync._create_sl_tp_for_filled_order(
                                db=db,
                                symbol=symbol,
                                side="BUY",
                                filled_price=float(executed_avg_price),
                                filled_qty=normalized_qty,
                                order_id=str(order_id)
                            )
                            
                            # Extract SL/TP order IDs from result
                            sl_order_id = None
                            tp_order_id = None
                            if isinstance(sl_tp_result, dict):
                                sl_result = sl_tp_result.get("sl_result", {})
                                tp_result = sl_tp_result.get("tp_result", {})
                                if isinstance(sl_result, dict):
                                    sl_order_id = sl_result.get("order_id")
                                if isinstance(tp_result, dict):
                                    tp_order_id = tp_result.get("order_id")
                            
                            logger.info(
                                f"✅ [SL/TP] Protection orders created for BUY {symbol} order {order_id}: "
                                f"SL={sl_order_id}, TP={tp_order_id}"
                            )
                            if DEBUG_TRADING:
                                logger.info(f"[DEBUG_TRADING] {symbol} BUY: SL/TP creation SUCCESS - SL={sl_order_id}, TP={tp_order_id}")
                            
                            # Emit SLTP_CREATED event
                            _emit_lifecycle_event(
                                db=db,
                                symbol=symbol,
                                strategy_key=strategy_key,
                                side="BUY",
                                price=executed_avg_price,
                                event_type="SLTP_CREATED",
                                event_reason=f"primary_order_id={order_id}",
                                order_id=str(order_id),
                                sl_order_id=str(sl_order_id) if sl_order_id else None,
                                tp_order_id=str(tp_order_id) if tp_order_id else None,
                            )
                            
                            # Send Telegram notification with order IDs
                            try:
                                telegram_notifier.send_message(
                                    f"✅ <b>SL/TP ORDERS CREATED</b>\n\n"
                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                    f"📋 BUY Order ID: {order_id}\n"
                                    f"🛡️ SL Order ID: {sl_order_id or 'Failed'}\n"
                                    f"🎯 TP Order ID: {tp_order_id or 'Failed'}\n"
                                    f"📦 Quantity: {normalized_qty} (normalized)\n"
                                    f"💵 Filled Price: ${executed_avg_price:.8f}\n\n"
                                    f"Protection orders created successfully."
                                )
                            except Exception as notify_err:
                                logger.warning(f"Failed to send SL/TP success notification: {notify_err}")
                            
                            filled_quantity = normalized_qty
                        
                        except Exception as sl_tp_err:
                            error_details = str(sl_tp_err)
                            logger.error(
                                f"❌ [SL/TP] CRITICAL: Failed to create SL/TP orders for BUY {symbol} order {order_id}: {error_details}",
                                exc_info=True
                            )
                            if DEBUG_TRADING:
                                logger.error(f"[DEBUG_TRADING] {symbol} BUY: SL/TP creation FAILED - {error_details}", exc_info=True)
                            
                            # Emit SLTP_FAILED event
                            _emit_lifecycle_event(
                                db=db,
                                symbol=symbol,
                                strategy_key=strategy_key,
                                side="BUY",
                                price=executed_avg_price,
                                event_type="SLTP_FAILED",
                                event_reason="sltp_creation_failed",
                                order_id=str(order_id),
                                error_message=error_details,
                            )
                            
                            try:
                                telegram_notifier.send_message(
                                    f"🚨 <b>CRITICAL: SL/TP CREATION FAILED</b>\n\n"
                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                    f"📋 BUY Order ID: {order_id}\n"
                                    f"🟢 Side: BUY\n"
                                    f"💵 Filled Price: ${executed_avg_price:.8f}\n"
                                    f"📦 Executed Quantity: {normalized_qty} (normalized from {executed_qty_raw_decimal})\n"
                                    f"❌ Error: {error_details}\n\n"
                                    f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                                    f"Please manually create protection orders or close the position immediately."
                                )
                            except Exception as alert_err:
                                logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                            
                            filled_quantity = normalized_qty
        else:
            # Order not confirmed FILLED after polling - do NOT create SL/TP
            logger.warning(
                f"⚠️ [SL/TP] BUY order {order_id} not confirmed FILLED after polling. "
                f"SL/TP creation skipped. Exchange sync will handle SL/TP when order becomes FILLED."
            )
        
        return {
            "order_id": str(order_id),
            "filled_price": filled_price,
            "filled_quantity": filled_quantity,
            "status": order_status,
            "avg_price": result.get("avg_price")
        }
    
    async def _place_order_from_signal(
        self,
        db: Session,
        symbol: str,
        side: str,
        watchlist_item: WatchlistItem,
        current_price: float,
        source: str = "orchestrator",
    ) -> Dict[str, Any]:
        """
        Place order immediately from signal (NO eligibility checks).
        
        This function bypasses ALL eligibility checks and places the order directly.
        It should ONLY be called from the orchestrator after a signal is sent.
        
        Args:
            db: Database session
            symbol: Trading symbol
            side: Order side ("BUY" or "SELL")
            watchlist_item: WatchlistItem (for trade_amount_usd, trade_on_margin)
            current_price: Current price (for SELL quantity calculation)
            source: Source identifier (default: "orchestrator")
        
        Returns:
            Dict with:
            - On success: order_id, exchange_order_id, status, avg_price, quantity, etc.
            - On failure: error, error_type, error_message
        """
        from app.utils.live_trading import get_live_trading_status
        from app.services.margin_decision_helper import decide_trading_mode, DEFAULT_CONFIGURED_LEVERAGE
        
        # Normalize symbol once for exchange compatibility
        symbol = normalize_symbol_for_exchange(symbol)

        # Get trade amount and margin settings (NO validation - signal was already sent)
        amount_usd = getattr(watchlist_item, 'trade_amount_usd', None) or 100.0  # Default fallback
        user_wants_margin = getattr(watchlist_item, 'trade_on_margin', False) or False
        
        # Get live trading status (for dry_run)
        live_trading = get_live_trading_status(db)
        dry_run_mode = not live_trading
        
        # Decide trading mode (margin vs spot)
        trading_decision = decide_trading_mode(
            symbol=symbol,
            configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
            user_wants_margin=user_wants_margin
        )
        use_margin = trading_decision.use_margin
        leverage_value = trading_decision.leverage if use_margin else None
        
        logger.info(f"[{source}] {symbol} {side} Placing order: amount=${amount_usd}, margin={use_margin}, leverage={leverage_value}")
        
        # Place order (single attempt, no retries, no fallbacks)
        try:
            if side.upper() == "BUY":
                result = trade_client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    notional=amount_usd,
                    is_margin=use_margin,
                    leverage=leverage_value,
                    dry_run=dry_run_mode,
                    source=source.upper()
                )
            else:  # SELL
                # For SELL, calculate quantity from amount_usd and current_price
                quantity = amount_usd / current_price if current_price > 0 else 0
                if quantity <= 0:
                    return {
                        "error": "invalid_quantity",
                        "error_type": "invalid_quantity",
                        "message": f"Cannot calculate SELL quantity: amount_usd={amount_usd}, current_price={current_price}"
                    }
                result = trade_client.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    qty=quantity,
                    is_margin=use_margin,
                    leverage=leverage_value,
                    dry_run=dry_run_mode,
                    source=source.upper()
                )
            
            # Check for errors
            if result and "error" in result:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"[{source}] {symbol} {side} Order failed: {error_msg}")
                return {
                    "error": error_msg,
                    "error_type": "exchange_rejected",
                    "message": error_msg,
                }
            
            # Success - extract order details
            order_id = result.get("order_id") or result.get("client_order_id")
            exchange_order_id = result.get("exchange_order_id") or order_id
            logger.info(f"[{source}] {symbol} {side} Order placed successfully: order_id={order_id}")
            
            return {
                "order_id": str(order_id) if order_id else None,
                "exchange_order_id": str(exchange_order_id) if exchange_order_id else None,
                "status": result.get("status", "NEW"),
                "avg_price": result.get("avg_price"),
                "quantity": result.get("quantity") or result.get("cumulative_quantity"),
                "filled_price": result.get("avg_price") or current_price,
            }
        except Exception as e:
            error_msg = str(e)[:500]
            logger.error(f"[{source}] {symbol} {side} Order placement exception: {e}", exc_info=True)
            return {
                "error": error_msg,
                "error_type": "exception",
                "message": error_msg,
            }
    
    def _poll_order_fill_confirmation(
        self,
        symbol: str,
        order_id: str,
        max_attempts: int = ORDER_FILL_POLL_MAX_ATTEMPTS,
        poll_interval: float = ORDER_FILL_POLL_INTERVAL_SECONDS
    ) -> Optional[Dict[str, Any]]:
        """
        Poll the exchange to confirm an order is FILLED and retrieve executed quantity.
        
        ROOT CAUSE FIX: MARKET orders may settle asynchronously. This function polls until:
        - Order status == FILLED
        - Executed quantity (cumulative_quantity) > 0 (strict validation)
        
        Reference: Crypto.com Exchange API - orders may not be immediately FILLED
        after placement, especially for MARKET orders during high volatility.
        
        Endpoints used:
        - get_open_orders(): Check if order is still open/pending
        - get_order_history(): Check if order was filled and moved to history
        
        Args:
            symbol: Trading pair symbol (e.g., "ETH_USDT")
            order_id: Exchange order ID to poll
            max_attempts: Maximum number of polling attempts (default: 10)
            poll_interval: Seconds to wait between attempts (default: 1.0)
        
        Returns:
            Dict with keys: status, cumulative_quantity (Decimal), avg_price, filled_price
            Returns None if order not filled after max_attempts or not found
        """
        from decimal import Decimal, InvalidOperation
        
        logger.info(
            f"🔄 [FILL_CONFIRMATION] Polling for order fill: {symbol} order_id={order_id} "
            f"(max_attempts={max_attempts}, interval={poll_interval}s)"
        )
        
        order_seen_in_any_source = False  # Track if we've ever seen this order
        
        for attempt in range(1, max_attempts + 1):
            try:
                # Check open orders first (order might still be open/pending)
                open_orders_result = trade_client.get_open_orders(page=0, page_size=200)
                open_orders_data = open_orders_result.get("data", [])
                
                # Search for our order in open orders
                order_found_in_open = False
                for order in open_orders_data:
                    if str(order.get("order_id") or order.get("client_order_id") or "") == str(order_id):
                        order_seen_in_any_source = True
                        order_found_in_open = True
                        status = (order.get("status") or "NEW").upper()
                        
                        if status == "FILLED":
                            # Order is filled, get details - use Decimal for precision
                            cumulative_qty_raw = order.get("cumulative_quantity", 0) or 0
                            try:
                                cumulative_qty_decimal = Decimal(str(cumulative_qty_raw))
                                avg_price_raw = order.get("avg_price")
                                avg_price_decimal = Decimal(str(avg_price_raw)) if avg_price_raw else None
                            except (ValueError, TypeError, InvalidOperation) as e:
                                logger.warning(
                                    f"⚠️ [FILL_CONFIRMATION] Order {order_id} FILLED but failed to parse quantities: {e} "
                                    f"(attempt {attempt}/{max_attempts})"
                                )
                                break
                            
                            # STRICT VALIDATION: Must have cumulative_quantity > 0
                            if cumulative_qty_decimal > 0:
                                logger.info(
                                    f"✅ [FILL_CONFIRMATION] Order {order_id} confirmed FILLED on attempt {attempt}: "
                                    f"qty={cumulative_qty_decimal}, avg_price={avg_price_decimal}"
                                )
                                return {
                                    "status": "FILLED",
                                    "cumulative_quantity": cumulative_qty_decimal,  # Return as Decimal
                                    "avg_price": float(avg_price_decimal) if avg_price_decimal else None,
                                    "filled_price": float(avg_price_decimal) if avg_price_decimal else None
                                }
                            else:
                                logger.warning(
                                    f"⚠️ [FILL_CONFIRMATION] Order {order_id} status is FILLED but cumulative_quantity <= 0 "
                                    f"(value: {cumulative_qty_decimal}, attempt {attempt}/{max_attempts})"
                                )
                        else:
                            logger.debug(
                                f"🔄 [FILL_CONFIRMATION] Order {order_id} status={status} (not FILLED yet, attempt {attempt}/{max_attempts})"
                            )
                        break
                
                # If order not in open orders, check order history (it might have been filled and closed)
                if not order_found_in_open:
                    logger.debug(f"🔄 [FILL_CONFIRMATION] Order {order_id} not found in open orders, checking history (attempt {attempt}/{max_attempts})")
                    
                    # Get recent order history (last 5 minutes)
                    end_time_ms = int(time.time() * 1000)
                    start_time_ms = int((time.time() - 300) * 1000)  # Last 5 minutes
                    history_result = trade_client.get_order_history(
                        start_time=start_time_ms,
                        end_time=end_time_ms,
                        page_size=200,
                        page=0
                    )
                    history_data = history_result.get("data", [])
                    
                    order_found_in_history = False
                    for order in history_data:
                        if str(order.get("order_id") or order.get("client_order_id") or "") == str(order_id):
                            order_seen_in_any_source = True
                            order_found_in_history = True
                            status = (order.get("status") or "NEW").upper()
                            cumulative_qty_raw = order.get("cumulative_quantity", 0) or 0
                            
                            try:
                                cumulative_qty_decimal = Decimal(str(cumulative_qty_raw))
                                avg_price_raw = order.get("avg_price")
                                avg_price_decimal = Decimal(str(avg_price_raw)) if avg_price_raw else None
                            except (ValueError, TypeError, InvalidOperation) as e:
                                logger.warning(
                                    f"⚠️ [FILL_CONFIRMATION] Order {order_id} found in history but failed to parse quantities: {e} "
                                    f"(attempt {attempt}/{max_attempts})"
                                )
                                break
                            
                            # STRICT VALIDATION: Must be FILLED AND cumulative_quantity > 0
                            if status == "FILLED" and cumulative_qty_decimal > 0:
                                logger.info(
                                    f"✅ [FILL_CONFIRMATION] Order {order_id} found FILLED in history (attempt {attempt}): "
                                    f"qty={cumulative_qty_decimal}, avg_price={avg_price_decimal}"
                                )
                                return {
                                    "status": "FILLED",
                                    "cumulative_quantity": cumulative_qty_decimal,  # Return as Decimal
                                    "avg_price": float(avg_price_decimal) if avg_price_decimal else None,
                                    "filled_price": float(avg_price_decimal) if avg_price_decimal else None
                                }
                            break
                
                # If we haven't found the order filled yet, wait before next attempt
                if attempt < max_attempts:
                    logger.debug(f"⏳ [FILL_CONFIRMATION] Waiting {poll_interval}s before next poll attempt...")
                    time.sleep(poll_interval)
                    
            except Exception as poll_err:
                logger.warning(
                    f"⚠️ [FILL_CONFIRMATION] Error polling order {order_id} (attempt {attempt}/{max_attempts}): {poll_err}",
                    exc_info=True
                )
                if attempt < max_attempts:
                    time.sleep(poll_interval)
        
        # Order not filled after max attempts - provide detailed error message
        if not order_seen_in_any_source:
            logger.error(
                f"❌ [FILL_CONFIRMATION] Order {order_id} ({symbol}) NOT FOUND in open orders or history after {max_attempts} attempts. "
                f"Order may have been cancelled, or order_id is incorrect. SL/TP creation will be skipped."
            )
        else:
            logger.error(
                f"❌ [FILL_CONFIRMATION] Order {order_id} ({symbol}) NOT confirmed FILLED after {max_attempts} attempts. "
                f"Order was seen but status is not FILLED or cumulative_quantity is invalid. SL/TP creation will be skipped."
            )
        return None
    
    async def _create_sell_order(self, db: Session, watchlist_item: WatchlistItem, 
                                 current_price: float, res_up: float, res_down: float):
        """Create a SELL order automatically based on signal"""
        symbol = watchlist_item.symbol
        
        # Resolve strategy for event emission
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        
        # CRITICAL SAFETY GUARD: Block execution if forced diagnostics are enabled for this symbol
        # This prevents any accidental order placement during diagnostic mode
        should_force_diagnostic = (
            (FORCE_SELL_DIAGNOSTIC and symbol == "TRX_USDT") or
            (FORCE_SELL_DIAGNOSTIC_SYMBOL and symbol.upper() == FORCE_SELL_DIAGNOSTIC_SYMBOL.upper())
        )
        if should_force_diagnostic:
            logger.error(
                f"🚫 [DIAGNOSTIC] DRY_RUN – order suppressed | "
                f"_create_sell_order called for {symbol} but FORCE_SELL_DIAGNOSTIC is enabled. "
                f"This should never happen - forced diagnostic mode should not call real order functions. "
                f"Returning error to prevent order placement."
            )
            return {
                "error": "diagnostic_mode",
                "error_type": "diagnostic_mode",
                "message": f"Order creation blocked: FORCE_SELL_DIAGNOSTIC is enabled for {symbol}"
            }
        
        # CRITICAL: Double-check trade_enabled flag before proceeding
        # This prevents order creation attempts when trade_enabled is False
        if not getattr(watchlist_item, 'trade_enabled', False):
            logger.warning(
                f"🚫 Blocked SELL order creation for {symbol}: trade_enabled=False. "
                f"This function should not be called when trade is disabled."
            )
            # Emit TRADE_BLOCKED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="SELL",
                price=current_price,
                event_type="TRADE_BLOCKED",
                event_reason="SKIP_DISABLED_TRADE",
            )
            return {"error": "trade_disabled", "error_type": "trade_disabled", "message": f"Trade is disabled for {symbol}"}
        
        # Validate that trade_amount_usd is configured - REQUIRED, no default
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
            logger.error(f"Cannot create SELL order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
            
            # Emit TRADE_BLOCKED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="SELL",
                price=current_price,
                event_type="TRADE_BLOCKED",
                event_reason="SKIP_INVALID_TRADE_AMOUNT",
                error_message=f"trade_amount_usd={watchlist_item.trade_amount_usd}",
            )
            
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
        
        # Read trade_on_margin from database FIRST - CRITICAL for margin trading
        # This must be read BEFORE balance check to avoid blocking margin orders
        user_wants_margin = watchlist_item.trade_on_margin or False
        
        # For SELL orders, we need to check if we have enough balance of the base currency
        # Extract base currency from symbol (e.g., ETH from ETH_USDT)
        # IMPORTANTE: Solo verificar balance SPOT si NO se está usando margen
        # Para órdenes con margen, el margen disponible se calcula de manera diferente
        base_currency = symbol.split('_')[0] if '_' in symbol else symbol
        
        if not user_wants_margin:
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
                logger.info(f"💰 Balance check para SELL {symbol} (SPOT): available={available_balance:.8f} {base_currency}, required={required_qty:.8f} {base_currency} (${amount_usd:,.2f} USD)")
                
                # If we don't have enough base currency, cannot create SELL order
                if available_balance < required_qty:
                    error_msg = (
                        f"Balance insuficiente: Available={available_balance:.8f} {base_currency} < "
                        f"Required={required_qty:.8f} {base_currency} (${amount_usd:,.2f} USD)"
                    )
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
                    return {"error": "balance", "error_type": "balance", "message": error_msg}
            except Exception as balance_check_err:
                logger.warning(f"⚠️ No se pudo verificar balance para SELL {symbol}: {balance_check_err}. Continuando con creación de orden...")
        else:
            logger.info(f"💰 MARGIN TRADING activado para SELL {symbol} - Saltando verificación de balance SPOT (el margen disponible se calcula de manera diferente)")
        
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
            # CRITICAL: Don't round here - let place_market_order handle formatting based on exchange requirements
            # The exchange has specific precision requirements per symbol that we can't predict here
            qty = amount_usd / current_price
            
            # Place MARKET SELL order
            side_upper = "SELL"
            
            # SELL market order: use quantity (exchange will format it according to symbol precision)
            # place_market_order has logic to fetch instrument info and format quantity correctly
            
            # Emit ORDER_ATTEMPT event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="SELL",
                price=current_price,
                event_type="ORDER_ATTEMPT",
                event_reason=f"qty={qty}, margin={use_margin}, leverage={leverage_value}",
            )
            
            result = trade_client.place_market_order(
                symbol=symbol,
                side=side_upper,
                qty=qty,  # Pass unrounded quantity - place_market_order will format it correctly
                is_margin=use_margin,
                leverage=leverage_value if use_margin else None,
                dry_run=dry_run_mode
            )
            
            if not result or "error" in result:
                error_msg = result.get("error", "Unknown error") if result else "No response"
                last_error = error_msg
                logger.error(f"❌ SELL order creation failed for {symbol}: {error_msg}")
                
                # ========================================================================
                # AUTHENTICATION ERROR HANDLING: Do NOT attempt fallbacks for auth errors
                # ========================================================================
                error_msg_str = str(error_msg).upper() if error_msg else ""
                is_auth_error = (
                    "401" in error_msg_str or
                    "40101" in error_msg_str or
                    "40103" in error_msg_str or
                    "AUTHENTICATION FAILED" in error_msg_str or
                    "AUTHENTICATION FAILURE" in error_msg_str
                )
                
                if is_auth_error:
                    logger.error(
                        f"🔐 AUTHENTICATION ERROR detected for SELL {symbol}: {error_msg}. "
                        f"This is a configuration issue (API keys, IP whitelist) and cannot be fixed by fallbacks."
                    )
                    # Emit ORDER_FAILED event with decision tracing
                    from app.utils.decision_reason import make_fail, ReasonCode, classify_exchange_error
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    reason_code = ReasonCode.AUTHENTICATION_ERROR.value
                    fail_reason = make_fail(
                        reason_code=reason_code,
                        message=f"Authentication error for SELL order: {error_msg}",
                        context={
                            "symbol": symbol,
                            "side": "SELL",
                            "amount_usd": amount_usd,
                            "quantity": qty,
                            "is_margin": use_margin,
                            "leverage": leverage_value if use_margin else None,
                        },
                        exchange_error=str(error_msg),
                        source="exchange",
                        correlation_id=correlation_id,
                    )
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="SELL",
                        price=current_price,
                        event_type="ORDER_FAILED",
                        event_reason="AUTHENTICATION_ERROR",
                        error_message=str(error_msg),
                        decision_reason=fail_reason,
                    )
                    # Send specific authentication error notification
                    try:
                        telegram_notifier.send_message(
                            f"🔐 <b>AUTOMATIC SELL ORDER CREATION FAILED: AUTHENTICATION ERROR</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"🔴 Side: SELL\n"
                            f"💰 Amount: ${amount_usd:,.2f}\n"
                            f"📦 Quantity: {qty:.8f}\n"
                            f"📊 Type: {'MARGIN' if use_margin else 'SPOT'}\n"
                            f"❌ Error: <b>Authentication failed: {error_msg}</b>\n\n"
                            f"⚠️ <b>This is a configuration issue:</b>\n"
                            f"• Check API credentials (API key and secret)\n"
                            f"• Verify IP address is whitelisted in Crypto.com Exchange\n"
                            f"• Ensure API key has trading permissions\n"
                            f"• Check if API key is expired or revoked\n\n"
                            f"⚠️ The symbol remains in your watchlist. Please fix the authentication configuration and try again."
                        )
                    except Exception as notify_err:
                        logger.warning(f"Failed to send Telegram authentication error notification: {notify_err}")
                    
                    return {"error": "authentication", "error_type": "authentication", "message": error_msg}
                
                # ========================================================================
                # FALLBACK 1: Error 306 (INSUFFICIENT_AVAILABLE_BALANCE) - Leverage demasiado alto
                # ========================================================================
                # Si falla con error 306, significa que el leverage fue demasiado alto para este par
                # Recordar el fallo e intentar con leverage reducido
                if use_margin and error_msg and "306" in error_msg and "INSUFFICIENT_AVAILABLE_BALANCE" in error_msg:
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
                        logger.info(
                            f"🔄 SELL {symbol}: Retrying with reduced leverage {next_leverage}x "
                            f"(down from {leverage_value}x) after error 306"
                        )
                        try:
                            retry_result = trade_client.place_market_order(
                                symbol=symbol,
                                side=side_upper,
                                qty=qty,
                                is_margin=True,  # Still margin, just lower leverage
                                leverage=next_leverage,
                                dry_run=dry_run_mode
                            )
                            
                            if retry_result and "error" not in retry_result:
                                logger.info(f"✅ SELL {symbol}: Success with reduced leverage {next_leverage}x (learned from error 306)")
                                result = retry_result  # Use successful retry result
                                leverage_value = next_leverage  # Update leverage for logging
                            else:
                                retry_error = retry_result.get("error", "Unknown error") if retry_result else "No response"
                                logger.warning(f"⚠️ SELL {symbol}: Retry with leverage {next_leverage}x failed: {retry_error}")
                                
                                # If retry also failed with 306, try even lower leverage
                                if retry_error and "306" in retry_error and "INSUFFICIENT_AVAILABLE_BALANCE" in retry_error:
                                    leverage_cache.record_leverage_failure(
                                        symbol=symbol,
                                        attempted_leverage=next_leverage,
                                        error_code=306
                                    )
                                    
                                    next_next_leverage = leverage_cache.get_next_try_leverage(
                                        symbol=symbol,
                                        failed_leverage=next_leverage,
                                        min_leverage=1.0
                                    )
                                    
                                    if next_next_leverage and next_next_leverage >= 1.0:
                                        logger.info(f"🔄 SELL {symbol}: Retrying with even lower leverage {next_next_leverage}x")
                                        try:
                                            retry_retry_result = trade_client.place_market_order(
                                                symbol=symbol,
                                                side=side_upper,
                                                qty=qty,
                                                is_margin=True,
                                                leverage=next_next_leverage,
                                                dry_run=dry_run_mode
                                            )
                                            
                                            if retry_retry_result and "error" not in retry_retry_result:
                                                logger.info(f"✅ SELL {symbol}: Success with leverage {next_next_leverage}x")
                                                result = retry_retry_result
                                                leverage_value = next_next_leverage
                                            else:
                                                error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error} | Margin {next_next_leverage}x failed: {retry_retry_result.get('error', 'Unknown') if retry_retry_result else 'No response'}"
                                        except Exception as retry_retry_err:
                                            logger.error(f"❌ Exception during second leverage retry for SELL {symbol}: {retry_retry_err}")
                                            error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error} | Second retry exception: {str(retry_retry_err)}"
                                    else:
                                        error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error}"
                                else:
                                    # Different error (not 306), don't continue trying leverage
                                    logger.warning(
                                        f"⚠️ Retry with leverage {next_leverage}x failed for SELL {symbol}: {retry_error} (not error 306, stopping leverage reduction)"
                                    )
                                    error_msg = f"Margin {leverage_value}x failed: {error_msg} | Margin {next_leverage}x failed: {retry_error}"
                        except Exception as retry_err:
                            logger.error(f"❌ Exception during leverage retry for SELL {symbol}: {retry_err}")
                            error_msg = f"Margin {leverage_value}x failed: {error_msg} | Leverage retry exception: {str(retry_err)}"
                    
                    # If reduced leverage didn't work or we're at minimum, try SPOT fallback
                    # Only try SPOT if we haven't already succeeded with a lower leverage
                    if (not result or "error" in result) and error_msg:
                        logger.warning(f"⚠️ SELL Margin order failed with error 306. Checking if SPOT fallback is possible for {symbol}...")
                        
                        # Check available balance for SPOT order (SELL needs base currency)
                        try:
                            account_summary = trade_client.get_account_summary()
                            available_balance = 0
                            
                            if 'accounts' in account_summary:
                                for acc in account_summary['accounts']:
                                    currency = acc.get('currency', '').upper()
                                    # For SELL orders, we need base currency (e.g., FIL for FIL_USDT)
                                    if currency == base_currency:
                                        available = float(acc.get('available', '0') or '0')
                                        available_balance = available
                                        break
                            
                            required_qty = amount_usd / current_price
                            
                            if available_balance >= required_qty:
                                logger.info(f"🔄 SELL {symbol}: SPOT fallback available. Balance: {available_balance:.8f} {base_currency} >= Required: {required_qty:.8f} {base_currency}")
                                try:
                                    spot_result = trade_client.place_market_order(
                                        symbol=symbol,
                                        side=side_upper,
                                        qty=qty,
                                        is_margin=False,  # SPOT fallback
                                        leverage=None,
                                        dry_run=dry_run_mode
                                    )
                                    
                                    if spot_result and "error" not in spot_result:
                                        logger.info(f"✅ SELL {symbol}: SPOT fallback succeeded")
                                        result = spot_result
                                        use_margin = False  # Update for logging
                                        leverage_value = None
                                    else:
                                        spot_error = spot_result.get("error", "Unknown error") if spot_result else "No response"
                                        logger.warning(f"⚠️ SELL {symbol}: SPOT fallback also failed: {spot_error}")
                                        error_msg = f"Margin {leverage_value}x failed: {error_msg} | SPOT fallback failed: {spot_error}"
                                except Exception as spot_err:
                                    logger.error(f"❌ Exception during SPOT fallback for SELL {symbol}: {spot_err}")
                                    error_msg = f"Margin {leverage_value}x failed: {error_msg} | SPOT fallback exception: {str(spot_err)}"
                            else:
                                logger.warning(f"⚠️ SELL {symbol}: SPOT fallback not possible. Balance: {available_balance:.8f} {base_currency} < Required: {required_qty:.8f} {base_currency}")
                                error_msg = f"Margin {leverage_value}x failed: {error_msg} | SPOT fallback not possible (insufficient balance)"
                        except Exception as balance_check_err:
                            logger.warning(f"⚠️ Could not check balance for SPOT fallback for SELL {symbol}: {balance_check_err}")
                            error_msg = f"Margin {leverage_value}x failed: {error_msg} | SPOT fallback check failed: {str(balance_check_err)}"
                
                # If we still have an error after all retries, emit ORDER_FAILED event with decision tracing
                if not result or "error" in result:
                    from app.utils.decision_reason import make_fail, ReasonCode, classify_exchange_error
                    import uuid
                    correlation_id = str(uuid.uuid4())
                    reason_code = classify_exchange_error(str(error_msg))
                    fail_reason = make_fail(
                        reason_code=reason_code.value,
                        message=f"SELL order placement failed: {error_msg}",
                        context={
                            "symbol": symbol,
                            "side": "SELL",
                            "amount_usd": amount_usd,
                            "quantity": qty,
                            "is_margin": use_margin,
                            "leverage": leverage_value if use_margin else None,
                            "dry_run": dry_run_mode,
                        },
                        exchange_error=str(error_msg),
                        source="exchange",
                        correlation_id=correlation_id,
                    )
                    _emit_lifecycle_event(
                        db=db,
                        symbol=symbol,
                        strategy_key=strategy_key,
                        side="SELL",
                        price=current_price,
                        event_type="ORDER_FAILED",
                        event_reason=fail_reason.reason_message,
                        error_message=fail_reason.exchange_error_snippet,
                        decision_reason=fail_reason,
                    )
                    
                    # Send Telegram notification about the error
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>AUTOMATIC SELL ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔴 Side: SELL\n"
                        f"💰 Amount: ${amount_usd:,.2f}\n"
                        f"📦 Quantity: {qty:.8f}\n"
                            f"❌ Error: {error_msg}\n\n"
                            f"🔍 Reason Code: {fail_reason.reason_code}\n"
                            f"📝 Reason: {fail_reason.reason_message}"
                    )
                except Exception as notify_err:
                    logger.warning(f"Failed to send Telegram error notification: {notify_err}")
                
                return {"error": "order_placement", "error_type": "order_placement", "message": str(error_msg)}
            
            # Get order_id from result
            order_id = result.get("order_id") or result.get("client_order_id")
            if not order_id:
                error_msg = f"Order placed but no order_id returned in response"
                logger.error(f"SELL order placed but no order_id returned for {symbol}")
                return {"error": "no_order_id", "error_type": "no_order_id", "message": error_msg}
            
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
                # CRITICAL: Explicitly pass origin to ensure notifications are sent
                alert_origin = get_runtime_origin()
                telegram_notifier.send_order_created(
                    symbol=symbol,
                    side="SELL",
                    price=filled_price,
                    quantity=qty,
                    order_id=str(order_id),
                    margin=use_margin,
                    leverage=leverage_value if use_margin else None,
                    dry_run=dry_run_mode,
                    order_type="MARKET",
                    origin=alert_origin  # CRITICAL: Explicitly pass origin to ensure notifications are sent
                )
                logger.info(f"✅ Sent Telegram notification for automatic SELL order: {symbol} - {order_id} (origin={alert_origin})")
            except Exception as telegram_err:
                logger.error(f"❌ Failed to send Telegram notification for SELL order creation: {telegram_err}", exc_info=True)
            
            # Emit ORDER_CREATED event
            _emit_lifecycle_event(
                db=db,
                symbol=symbol,
                strategy_key=strategy_key,
                side="SELL",
                price=filled_price or current_price,
                event_type="ORDER_CREATED",
                event_reason=f"order_id={order_id}",
                order_id=str(order_id),
            )
            
            # Save order to database
            try:
                from app.services.order_history_db import order_history_db
                # Use time module (already imported at top of file)
                
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
                        # CRITICAL FIX: Create TradeSignal record and assign trade_signal_id to link automatic order
                        # This prevents automatic orders from being marked as "Manual" in Telegram notifications
                        trade_signal_id = None
                        try:
                            from app.services.signal_writer import upsert_trade_signal
                            from app.models.trade_signal import PresetEnum, RiskProfileEnum, SignalStatusEnum

                            # Create TradeSignal record for automatic order
                            trade_signal = upsert_trade_signal(
                                db=db,
                                symbol=symbol,
                                preset_enum=PresetEnum.SWING,  # Default preset for automatic orders
                                risk_profile_enum=RiskProfileEnum.CONSERVATIVE,  # Default risk profile
                                rsi=None,  # Technical indicators not available at order creation time
                                ma50=None,
                                ma200=None,
                                ema10=None,
                                ma10w=None,
                                atr=None,
                                resistance_up=None,
                                resistance_down=None,
                                entry_price=filled_price or current_price,  # Price when order was placed
                                current_price=filled_price or current_price,
                                volume_24h=None,  # Volume data not available
                                volume_ratio=None,
                                should_trade=True,  # Automatic order was created, so should_trade=True
                                status_enum=SignalStatusEnum.ORDER_PLACED,  # Status: order has been placed
                                exchange_order_id=str(order_id),  # Link to the exchange order
                                notes=f"Automatic SELL order created by signal monitor at ${filled_price or current_price:.4f}"
                            )
                            trade_signal_id = trade_signal.id
                            logger.info(f"✅ Created TradeSignal record (ID: {trade_signal_id}) for automatic SELL order: {symbol}")
                        except Exception as signal_err:
                            logger.warning(f"⚠️ Failed to create TradeSignal record for automatic order {symbol}: {signal_err}")
                            # Continue with order creation even if signal creation fails

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
                            updated_at=now_utc,
                            trade_signal_id=trade_signal_id  # CRITICAL: Link to TradeSignal to mark as automatic
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
            
            # ========================================================================
            # CURRENT ORDER LIFECYCLE LOGIC (Documented Flow)
            # ========================================================================
            # 
            # FLOW FOR SELL ORDERS WITH SL/TP:
            #   1. Place SELL MARKET order -> exchange returns order_id
            #   2. Check initial response: if status=FILLED and cumulative_quantity available, use it
            #   3. If not immediately filled, poll exchange (get_open_orders + get_order_history)
            #      until status=FILLED with cumulative_quantity (up to N attempts with sleep)
            #   4. Extract EXECUTED quantity (cumulative_quantity) from filled order response
            #      - NEVER use requested quantity (qty) - only use executed quantity
            #   5. Normalize executed quantity using normalize_quantity() helper:
            #      - Rounds DOWN to stepSize (qty_tick_size)
            #      - Enforces minQty (minimum quantity)
            #      - Formats to exact quantity_decimals decimal places
            #   6. Create SL/TP orders with normalized executed quantity
            #   7. If SL/TP creation fails, send CRITICAL Telegram alert and log error
            #
            # KEY ASSUMPTIONS:
            #   - MARKET orders may settle asynchronously (not immediately FILLED)
            #   - Exchange returns cumulative_quantity only when order is FILLED
            #   - Requested quantity (qty) may differ from executed quantity
            #   - Quantity must match exchange precision rules (stepSize, minQty, decimals)
            #
            # EXCHANGE DOCUMENTATION:
            #   - Crypto.com Exchange API: private/create-order (MARKET orders)
            #   - Order status lifecycle: NEW -> ACTIVE -> FILLED (or CANCELLED)
            #   - cumulative_quantity only available when order is FILLED
            #   - See: docs/trading/crypto_com_order_formatting.md for precision rules
            #
            # ROOT CAUSE OF PREVIOUS FAILURE:
            #   - Code assumed immediate fills: checked is_filled || has_avg_price
            #   - Used requested qty as fallback when cumulative_quantity not available
            #   - Did not poll for fill confirmation
            #   - Did not normalize quantity to exchange rules
            #   - Silent failures: only logged warnings, no CRITICAL alerts
            #
            # ========================================================================
            # ROOT CAUSE FIX: Guaranteed fill confirmation before SL/TP placement
            # ========================================================================
            # PROBLEM: MARKET orders may settle asynchronously. The initial response
            # may not have status=FILLED or cumulative_quantity yet.
            # 
            # SOLUTION: Poll the exchange until order is confirmed FILLED with
            # executed quantity, then use that EXECUTED quantity (not requested) for SL/TP.
            # ========================================================================
            
            # Check if order is already filled in initial response
            is_filled_immediately = result_status in ["FILLED", "filled"]
            has_cumulative_qty = result.get("cumulative_quantity") and float(result.get("cumulative_quantity", 0) or 0) > 0
            
            filled_confirmation = None
            
            if is_filled_immediately and has_cumulative_qty:
                # Order is already filled, use data from response
                # Convert to Decimal for consistency with polling path
                from decimal import Decimal, InvalidOperation
                cumulative_qty_raw = result.get("cumulative_quantity")
                try:
                    cumulative_qty_decimal = Decimal(str(cumulative_qty_raw)) if cumulative_qty_raw else None
                    avg_price_raw = result.get("avg_price")
                    avg_price_value = float(avg_price_raw) if avg_price_raw else filled_price
                except (ValueError, TypeError, Exception) as e:
                    logger.warning(f"⚠️ [SL/TP] Failed to parse immediate fill quantities: {e}")
                    cumulative_qty_decimal = None
                    avg_price_value = filled_price
                
                if cumulative_qty_decimal and cumulative_qty_decimal > 0:
                    logger.info(f"✅ [SL/TP] Order {order_id} already FILLED in initial response (qty={cumulative_qty_decimal})")
                    filled_confirmation = {
                        "status": "FILLED",
                        "cumulative_quantity": cumulative_qty_decimal,  # Use Decimal for consistency
                        "avg_price": avg_price_value,
                        "filled_price": avg_price_value
                    }
                else:
                    logger.warning(f"⚠️ [SL/TP] Order {order_id} marked FILLED but cumulative_quantity invalid. Will poll for confirmation.")
                    filled_confirmation = None  # Force polling
            else:
                # Order may not be filled yet - poll for confirmation
                logger.info(
                    f"🔄 [SL/TP] Order {order_id} not immediately FILLED (status={result_status}, "
                    f"has_cumulative_qty={has_cumulative_qty}). Polling for fill confirmation..."
                )
                filled_confirmation = self._poll_order_fill_confirmation(
                    symbol=symbol,
                    order_id=str(order_id),
                    max_attempts=ORDER_FILL_POLL_MAX_ATTEMPTS,
                    poll_interval=ORDER_FILL_POLL_INTERVAL_SECONDS
                )
            
            # Attempt SL/TP creation only if order is confirmed FILLED
            if filled_confirmation and filled_confirmation.get("status") == "FILLED":
                from decimal import Decimal, InvalidOperation
                
                # CRITICAL: Use EXECUTED quantity (cumulative_quantity), never requested quantity
                # cumulative_quantity is returned as Decimal from _poll_order_fill_confirmation
                executed_qty_raw_decimal = filled_confirmation.get("cumulative_quantity")
                executed_avg_price = filled_confirmation.get("filled_price") or filled_price
                
                # STRICT VALIDATION: Must be Decimal and > 0
                if not executed_qty_raw_decimal or not isinstance(executed_qty_raw_decimal, Decimal) or executed_qty_raw_decimal <= 0:
                    executed_qty_str = str(executed_qty_raw_decimal) if executed_qty_raw_decimal else "None"
                    error_msg = (
                        f"Order {order_id} confirmed FILLED but executed quantity is invalid: {executed_qty_str}. "
                        f"Must be Decimal > 0. Cannot create SL/TP with invalid quantity."
                    )
                    logger.error(f"❌ [SL/TP] {error_msg}")
                    
                    # Send CRITICAL alert
                    try:
                        telegram_notifier.send_message(
                            f"🚨 <b>CRITICAL: SL/TP CREATION BLOCKED</b>\n\n"
                            f"📊 Symbol: <b>{symbol}</b>\n"
                            f"📋 SELL Order ID: {order_id}\n"
                            f"🔴 Side: SELL\n"
                            f"❌ Error: {error_msg}\n\n"
                            f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                            f"Please manually create protection orders or close the position."
                        )
                    except Exception as alert_err:
                        logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                    
                    # Use requested qty for return value only (order was filled but quantity invalid)
                    filled_quantity = float(executed_qty_raw_decimal) if executed_qty_raw_decimal and isinstance(executed_qty_raw_decimal, Decimal) else qty
                else:
                    # Convert Decimal to float for normalize_quantity (it expects float)
                    executed_qty_raw_float = float(executed_qty_raw_decimal)
                    
                    # Normalize executed quantity to exchange rules (stepSize, minQty)
                    # CRITICAL: Use normalize_quantity to ensure quantity matches exchange requirements
                    # normalize_quantity enforces: stepSize (round DOWN), minQty, returns string
                    logger.info(
                        f"🔄 [SL/TP] Normalizing executed quantity: raw={executed_qty_raw_decimal} (Decimal) -> {executed_qty_raw_float} (float), symbol={symbol}"
                    )
                    
                    normalized_qty_str = trade_client.normalize_quantity(symbol, executed_qty_raw_float)
                    
                    if not normalized_qty_str:
                        error_msg = (
                            f"Order {order_id} executed quantity {executed_qty_raw_decimal} failed normalization for {symbol}. "
                            f"Cannot create SL/TP - quantity may be below minQty/stepSize or instrument rules unavailable."
                        )
                        logger.error(f"❌ [SL/TP] {error_msg}")
                        
                        # Send CRITICAL alert
                        try:
                            telegram_notifier.send_message(
                                f"🚨 <b>CRITICAL: SL/TP CREATION BLOCKED</b>\n\n"
                                f"📊 Symbol: <b>{symbol}</b>\n"
                                f"📋 SELL Order ID: {order_id}\n"
                                f"🔴 Side: SELL\n"
                                f"📦 Executed Quantity (raw): {executed_qty_raw_decimal}\n"
                                f"❌ Error: {error_msg}\n\n"
                                f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                                f"Please manually create protection orders or close the position."
                            )
                        except Exception as alert_err:
                            logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                        
                        filled_quantity = executed_qty_raw_float  # Use raw float for return value
                    else:
                        normalized_qty = float(normalized_qty_str)
                        logger.info(
                            f"✅ [SL/TP] Quantity normalized: raw={executed_qty_raw_decimal} (Decimal) -> normalized={normalized_qty} (string: {normalized_qty_str}) "
                            f"(symbol={symbol})"
                        )
                        
                        # IDEMPOTENCY GUARD: Check if SL/TP already exist for this order before creating
                        # This prevents duplicate creation if this function is called multiple times
                        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
                        existing_sl_tp = db.query(ExchangeOrder).filter(
                            ExchangeOrder.parent_order_id == str(order_id),
                            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
                        ).all()
                        
                        if existing_sl_tp:
                            existing_order_ids = [str(o.exchange_order_id) for o in existing_sl_tp]
                            logger.info(
                                f"⚠️ [SL/TP] Idempotency guard: SL/TP orders already exist for SELL order {order_id} ({symbol}): {existing_order_ids}. "
                                f"Skipping duplicate creation."
                            )
                            # SL/TP already exist, use normalized quantity for return value
                            filled_quantity = normalized_qty
                        else:
                            # Create SL/TP orders with normalized executed quantity
                            try:
                                from app.services.exchange_sync import ExchangeSyncService
                                exchange_sync = ExchangeSyncService()
                                
                                logger.info(
                                    f"🔒 [SL/TP] Creating protection orders for SELL {symbol} order {order_id}: "
                                    f"filled_price={executed_avg_price}, executed_qty={normalized_qty} "
                                    f"(normalized from {executed_qty_raw_decimal})"
                                )
                                
                                # Emit SLTP_ATTEMPT event
                                _emit_lifecycle_event(
                                    db=db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="SELL",
                                    price=executed_avg_price,
                                    event_type="SLTP_ATTEMPT",
                                    event_reason=f"primary_order_id={order_id}, filled_price={executed_avg_price}, qty={normalized_qty}",
                                    order_id=str(order_id),
                                )
                                
                                # Create SL/TP orders for the filled SELL order
                                # For SELL orders: TP is BUY side (buy back at profit), SL is BUY side (buy back at loss)
                                sl_tp_result = exchange_sync._create_sl_tp_for_filled_order(
                                    db=db,
                                    symbol=symbol,
                                    side="SELL",
                                    filled_price=float(executed_avg_price),
                                    filled_qty=normalized_qty,  # CRITICAL: Use normalized executed quantity
                                    order_id=str(order_id)
                                )
                                
                                # Extract SL/TP order IDs from result for logging
                                # _create_sl_tp_for_filled_order returns dict with sl_result and tp_result keys
                                sl_order_id = None
                                tp_order_id = None
                                if isinstance(sl_tp_result, dict):
                                    sl_result = sl_tp_result.get("sl_result", {})
                                    tp_result = sl_tp_result.get("tp_result", {})
                                    if isinstance(sl_result, dict):
                                        sl_order_id = sl_result.get("order_id")
                                    if isinstance(tp_result, dict):
                                        tp_order_id = tp_result.get("order_id")
                                
                                logger.info(
                                    f"✅ [SL/TP] Protection orders created for SELL {symbol} order {order_id}: "
                                    f"SL={sl_order_id}, TP={tp_order_id}"
                                )
                                
                                # Emit SLTP_CREATED event
                                _emit_lifecycle_event(
                                    db=db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="SELL",
                                    price=executed_avg_price,
                                    event_type="SLTP_CREATED",
                                    event_reason=f"primary_order_id={order_id}",
                                    order_id=str(order_id),
                                    sl_order_id=str(sl_order_id) if sl_order_id else None,
                                    tp_order_id=str(tp_order_id) if tp_order_id else None,
                                )
                                
                                # Send Telegram notification with order IDs
                                try:
                                    telegram_notifier.send_message(
                                        f"✅ <b>SL/TP ORDERS CREATED</b>\n\n"
                                        f"📊 Symbol: <b>{symbol}</b>\n"
                                        f"📋 SELL Order ID: {order_id}\n"
                                        f"🛡️ SL Order ID: {sl_order_id or 'Failed'}\n"
                                        f"🎯 TP Order ID: {tp_order_id or 'Failed'}\n"
                                        f"📦 Quantity: {normalized_qty} (normalized)\n"
                                        f"💵 Filled Price: ${executed_avg_price:.8f}\n\n"
                                        f"Protection orders created successfully."
                                    )
                                except Exception as notify_err:
                                    logger.warning(f"Failed to send SL/TP success notification: {notify_err}")
                                
                                filled_quantity = normalized_qty
                            
                            except Exception as sl_tp_err:
                                # SL/TP creation failed - send CRITICAL alert and trigger failsafe
                                error_details = str(sl_tp_err)
                                logger.error(
                                    f"❌ [SL/TP] CRITICAL: Failed to create SL/TP orders for SELL {symbol} order {order_id}: {error_details}",
                                    exc_info=True
                                )
                                
                                # Emit SLTP_FAILED event
                                _emit_lifecycle_event(
                                    db=db,
                                    symbol=symbol,
                                    strategy_key=strategy_key,
                                    side="SELL",
                                    price=executed_avg_price,
                                    event_type="SLTP_FAILED",
                                    event_reason="sltp_creation_failed",
                                    order_id=str(order_id),
                                    error_message=error_details,
                                )
                                
                                # Send CRITICAL Telegram alert with full details including SELL order ID
                                try:
                                    telegram_notifier.send_message(
                                        f"🚨 <b>CRITICAL: SL/TP CREATION FAILED</b>\n\n"
                                        f"📊 Symbol: <b>{symbol}</b>\n"
                                        f"📋 SELL Order ID: {order_id}\n"
                                        f"🔴 Side: SELL\n"
                                        f"💵 Filled Price: ${executed_avg_price:.8f}\n"
                                        f"📦 Executed Quantity: {normalized_qty} (normalized from {executed_qty_raw_decimal})\n"
                                        f"❌ Error: {error_details}\n\n"
                                        f"⚠️ <b>Position is UNPROTECTED</b> - No SL/TP orders created.\n"
                                        f"Please manually create protection orders or close the position immediately."
                                    )
                                except Exception as alert_err:
                                    logger.error(f"Failed to send CRITICAL Telegram alert: {alert_err}", exc_info=True)
                                
                                # FAILSAFE: Trigger real actions when SL/TP creation fails
                                # For SELL orders: This typically closes a long position (reduces exposure)
                                # We should send additional alerts and optionally disable trading for this symbol
                                if FAILSAFE_ON_SLTP_ERROR:
                                    logger.error(
                                        f"🚨 [FAILSAFE] SL/TP creation failed for {symbol} SELL order {order_id}. "
                                        f"Position is unprotected. FAILSAFE actions triggered."
                                    )
                                    
                                    # Send additional failsafe alert
                                    try:
                                        telegram_notifier.send_message(
                                            f"🚨 <b>FAILSAFE ALERT: UNPROTECTED POSITION</b>\n\n"
                                            f"📊 Symbol: <b>{symbol}</b>\n"
                                            f"📋 SELL Order ID: {order_id}\n"
                                            f"🔴 Side: SELL (likely closed long position)\n"
                                            f"⚠️ <b>NO PROTECTION ORDERS</b> - SL/TP creation failed.\n\n"
                                            f"💡 <b>Recommended Actions:</b>\n"
                                            f"• Manually create SL/TP orders\n"
                                            f"• Close the position if desired\n"
                                            f"• Review logs for error details\n\n"
                                            f"🔒 Trading for this symbol should be reviewed before next order."
                                        )
                                    except Exception as failsafe_alert_err:
                                        logger.error(f"Failed to send FAILSAFE alert: {failsafe_alert_err}", exc_info=True)
                                    
                                    # TODO: Could implement circuit breaker here (disable trading for symbol temporarily)
                                    # This would require adding a flag to watchlist_item or a separate circuit breaker service
                                    logger.warning(
                                        f"⚠️ [FAILSAFE] Consider implementing circuit breaker to disable trading for {symbol} "
                                        f"until SL/TP protection is manually verified/created."
                                    )
                                
                                # Use normalized quantity for return value
                                filled_quantity = normalized_qty
            else:
                # Order not confirmed FILLED after polling - do NOT create SL/TP
                error_msg = (
                    f"Order {order_id} not confirmed FILLED after polling. "
                    f"SL/TP creation skipped to prevent using incorrect quantity. "
                    f"Exchange sync will handle SL/TP when order becomes FILLED."
                )
                logger.warning(f"⚠️ [SL/TP] {error_msg}")
                
                # Send alert that order is pending and SL/TP will be created later
                try:
                    telegram_notifier.send_message(
                        f"⏳ <b>SL/TP PENDING</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"📋 Order ID: {order_id}\n"
                        f"🔴 Side: SELL\n"
                        f"ℹ️ Order fill confirmation pending. SL/TP will be created automatically when order is filled.\n\n"
                        f"The exchange sync service will create protection orders when the order status becomes FILLED."
                    )
                except Exception as alert_err:
                    logger.warning(f"Failed to send pending alert: {alert_err}")
                
                # Use requested quantity for return value (order not filled yet)
                filled_quantity = qty
            
            return {
                "order_id": str(order_id),
                "filled_price": filled_price,
                "filled_quantity": filled_quantity,
                "status": result_status,
                "avg_price": result.get("avg_price")
            }
        
        except Exception as e:
            error_msg = f"Exception during order creation: {str(e)}"
            logger.error(f"Error creating automatic SELL order for {symbol}: {e}", exc_info=True)
            return {"error": "exception", "error_type": "exception", "message": error_msg}
    
    async def start(self):
        """Start the signal monitoring service loop."""
        if self.is_running:
            logger.warning("⚠️ Signal monitor is already running, skipping duplicate start")
            return
        self.is_running = True
        self._persist_status("starting")
        logger.info("=" * 60)
        logger.info("🚀 SIGNAL MONITORING SERVICE STARTED (interval=%ss)", self.monitor_interval)
        logger.info(f"   - Max orders per symbol: {self.MAX_OPEN_ORDERS_PER_SYMBOL}")
        logger.info(f"   - Min price change: {self.MIN_PRICE_CHANGE_PCT}%")
        logger.info("=" * 60)

        cycle_count = 0
        logger.info("SignalMonitorService.start() called, entering main loop (is_running=%s)", self.is_running)
        try:
            while self.is_running:
                logger.debug("SignalMonitorService loop iteration, is_running=%s", self.is_running)
                try:
                    cycle_count += 1
                    self.last_run_at = datetime.now(timezone.utc)
                    self._persist_status("cycle_started")
                    logger.info("SignalMonitorService cycle #%s started (is_running=%s)", cycle_count, self.is_running)
                    
                    # Heartbeat log every 10 cycles (every ~5 minutes with 30s interval)
                    if cycle_count % 10 == 0:
                        logger.info(
                            "[HEARTBEAT] SignalMonitorService alive - cycle=%d last_run=%s",
                            cycle_count,
                            self.last_run_at.isoformat() if self.last_run_at else "None"
                        )
                        
                        # Watchdog: Check if cycles are advancing (if last_run_at is old, alert)
                        if self.last_run_at:
                            time_since_last = datetime.now(timezone.utc) - self.last_run_at
                            # If no cycle in > 2 intervals (60s with 30s interval), log warning
                            if time_since_last > timedelta(seconds=self.monitor_interval * 2):
                                logger.error(
                                    f"[SIGNAL_MONITOR_WATCHDOG] ⚠️ No cycle recorded in {time_since_last.total_seconds():.0f}s "
                                    f"(threshold: {self.monitor_interval * 2}s). Scheduler may be stalled."
                                )
                                # Send system alert using health-based evaluation (throttled to once per 24h)
                                try:
                                    from app.services.system_alerts import evaluate_and_maybe_send_system_alert
                                    evaluate_and_maybe_send_system_alert(db=db)
                                except Exception:
                                    pass  # Don't fail monitor if alert fails

                    # CRITICAL: Use Postgres advisory lock to prevent duplicate runners
                    # Lock ID: 123456 (arbitrary but unique for signal monitor)
                    db = SessionLocal()
                    run_id = f"{os.getpid()}_{int(time.time())}"
                    host = os.getenv("HOSTNAME", "unknown")
                    
                    try:
                        # Try to acquire advisory lock (non-blocking)
                        from sqlalchemy import text
                        lock_result = db.execute(text("SELECT pg_try_advisory_lock(123456)")).scalar()
                        
                        if not lock_result:
                            # Lock is held by another process
                            if DEBUG_TRADING:
                                logger.warning(f"[DEBUG_TRADING] RUN_LOCKED run_id={run_id} pid={os.getpid()} host={host}")
                            logger.warning(f"RUN_LOCKED: Signal monitor lock held by another process. Skipping cycle #{cycle_count}")
                            db.close()
                            await asyncio.sleep(self.monitor_interval)
                            continue
                        
                        # Lock acquired - log RUN_START
                        if DEBUG_TRADING:
                            logger.info(f"[DEBUG_TRADING] RUN_START run_id={run_id} pid={os.getpid()} host={host} cycle={cycle_count}")
                        logger.info(f"RUN_START run_id={run_id} pid={os.getpid()} host={host} cycle={cycle_count}")
                        
                        try:
                            await self.monitor_signals(db)
                            # Commit changes if monitor_signals made any database modifications
                            try:
                                db.commit()
                                logger.debug("SignalMonitorService: Committed database changes")
                            except Exception as commit_err:
                                logger.error(f"SignalMonitorService: Error committing changes: {commit_err}", exc_info=True)
                                db.rollback()
                        except Exception as monitor_err:
                            logger.error(f"SignalMonitorService: Error in monitor_signals: {monitor_err}", exc_info=True)
                            db.rollback()
                            raise
                        finally:
                            # Release lock and log RUN_END
                            try:
                                db.execute(text("SELECT pg_advisory_unlock(123456)"))
                                if DEBUG_TRADING:
                                    logger.info(f"[DEBUG_TRADING] RUN_END run_id={run_id} pid={os.getpid()} host={host} cycle={cycle_count}")
                                logger.info(f"RUN_END run_id={run_id} pid={os.getpid()} host={host} cycle={cycle_count}")
                            except Exception as unlock_err:
                                logger.error(f"Error releasing advisory lock: {unlock_err}", exc_info=True)
                            db.close()
                    except Exception as lock_err:
                        logger.error(f"Error acquiring advisory lock: {lock_err}", exc_info=True)
                        db.close()
                        # Continue to next cycle even if lock fails
                        await asyncio.sleep(self.monitor_interval)
                        continue

                    logger.info(
                        "SignalMonitorService cycle #%s completed. Next check in %ss",
                        cycle_count,
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
