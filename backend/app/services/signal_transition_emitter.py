"""
Signal Transition Emitter Service

Detects when signals transition from NOT-ELIGIBLE to ELIGIBLE and immediately
emits Telegram alerts and places Crypto.com orders.

This ensures alerts/orders are sent the moment the UI button turns RED/GREEN,
not waiting for the periodic monitor loop.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_monitor import signal_monitor_service
from app.services.strategy_profiles import resolve_strategy_profile
from app.services.signal_throttle import (
    fetch_signal_states,
    should_emit_signal,
    SignalThrottleConfig,
    build_strategy_key,
    record_signal_event,
)
from app.services.config_loader import get_alert_thresholds

logger = logging.getLogger(__name__)


def check_and_emit_on_transition(
    db: Session,
    symbol: str,
    current_buy_signal: bool,
    current_sell_signal: bool,
    current_price: float,
    watchlist_item: Optional[WatchlistItem] = None,
) -> Tuple[bool, Dict[str, any]]:
    """
    Check if signal transitioned from NOT-ELIGIBLE to ELIGIBLE and emit immediately.
    
    Args:
        db: Database session
        symbol: Trading symbol
        current_buy_signal: Current BUY signal state (True if eligible)
        current_sell_signal: Current SELL signal state (True if eligible)
        current_price: Current price
        watchlist_item: Optional watchlist item (will fetch if not provided)
    
    Returns:
        Tuple of (transition_detected: bool, result: dict with details)
    """
    transition_id = str(uuid.uuid4())[:8]
    result = {
        "transition_id": transition_id,
        "symbol": symbol,
        "buy_transition": False,
        "sell_transition": False,
        "telegram_sent": False,
        "order_placed": False,
        "errors": []
    }
    
    try:
        # Get watchlist item if not provided
        if not watchlist_item:
            from app.services.watchlist_selector import get_canonical_watchlist_item
            watchlist_item = get_canonical_watchlist_item(db, symbol)
        
        if not watchlist_item:
            logger.debug(f"[TRANSITION_{transition_id}] {symbol}: No watchlist item found, skipping transition check")
            return False, result
        
        # Check alert/trade enabled flags
        alert_enabled = getattr(watchlist_item, "alert_enabled", False)
        buy_alert_enabled = getattr(watchlist_item, "buy_alert_enabled", False)
        sell_alert_enabled = getattr(watchlist_item, "sell_alert_enabled", False)
        trade_enabled = getattr(watchlist_item, "trade_enabled", False)
        
        if not alert_enabled and not trade_enabled:
            logger.debug(f"[TRANSITION_{transition_id}] {symbol}: Alerts and trade disabled, skipping")
            return False, result
        
        # Get previous signal state from throttle states
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        
        signal_states = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
        last_buy_snapshot = signal_states.get("BUY")
        last_sell_snapshot = signal_states.get("SELL")
        
        # Determine previous signal states
        # If no previous state exists, previous was NOT-ELIGIBLE
        # If previous state exists with timestamp, check if signal was active
        # We consider a signal "active" if there's a recent state (within last hour)
        # This is a heuristic - the real check is if throttle allows emission
        
        # Get throttle config
        # get_alert_thresholds returns a tuple: (min_price_change_pct, cooldown_minutes)
        min_price_change_pct, cooldown_minutes = get_alert_thresholds(
            watchlist_item.symbol,
            getattr(watchlist_item, "sl_tp_mode", None)
        )
        throttle_config_obj = SignalThrottleConfig(
            min_price_change_pct=min_price_change_pct or 0.0,
            min_interval_minutes=cooldown_minutes or 1.0,
        )
        
        # Check BUY transition
        buy_transition = False
        if current_buy_signal and buy_alert_enabled:
            # Check if throttle allows emission (this handles first-time and time/price gates)
            buy_allowed, buy_reason = should_emit_signal(
                symbol=symbol,
                side="BUY",
                current_price=current_price,
                current_time=datetime.now(timezone.utc),
                config=throttle_config_obj,
                last_same_side=last_buy_snapshot,
                last_opposite_side=last_sell_snapshot,
                db=db,
                strategy_key=strategy_key,
            )
            
            # Transition detected if:
            # 1. Current signal is ELIGIBLE (current_buy_signal=True)
            # 2. Throttle allows emission (buy_allowed=True)
            # 3. Either no previous state OR previous state was old (transition from NOT-ELIGIBLE)
            if buy_allowed:
                # Check if this is a transition (no previous state or old state)
                is_transition = (
                    last_buy_snapshot is None or
                    last_buy_snapshot.timestamp is None or
                    (datetime.now(timezone.utc) - last_buy_snapshot.timestamp).total_seconds() > 3600
                )
                
                # Emit if it's a transition OR if throttle allows (meaning signal is eligible now)
                # This ensures signals are sent when they become eligible, even if recently active
                if is_transition:
                    buy_transition = True
                    transition_type = "NEW_TRANSITION"
                    logger.info(
                        f"[SIGNAL_TRANSITION] {transition_id} {symbol} BUY from=NOT-ELIGIBLE to=ELIGIBLE "
                        f"type={transition_type} alert_enabled={buy_alert_enabled} trade_enabled={trade_enabled} "
                        f"price=${current_price:.4f} reason={buy_reason}"
                    )
                else:
                    # Throttle allows emission - signal is eligible now, emit it
                    # This handles cases where signal was recently active but throttle now allows (e.g., price change, config reset)
                    buy_transition = True
                    transition_type = "THROTTLE_ALLOWED"
                    logger.info(
                        f"[SIGNAL_TRANSITION] {transition_id} {symbol} BUY signal eligible (throttle allows) "
                        f"type={transition_type} alert_enabled={buy_alert_enabled} trade_enabled={trade_enabled} "
                        f"price=${current_price:.4f} reason={buy_reason}"
                    )
        
        # Check SELL transition
        sell_transition = False
        if current_sell_signal and sell_alert_enabled:
            sell_allowed, sell_reason = should_emit_signal(
                symbol=symbol,
                side="SELL",
                current_price=current_price,
                current_time=datetime.now(timezone.utc),
                config=throttle_config_obj,
                last_same_side=last_sell_snapshot,
                last_opposite_side=last_buy_snapshot,
                db=db,
                strategy_key=strategy_key,
            )
            
            if sell_allowed:
                # Detect transition if:
                # 1. No previous state (first time)
                # 2. Previous state is old (>1 hour) - clear transition
                is_transition = (
                    last_sell_snapshot is None or
                    last_sell_snapshot.timestamp is None or
                    (datetime.now(timezone.utc) - last_sell_snapshot.timestamp).total_seconds() > 3600
                )
                
                # Emit if it's a transition OR if throttle allows (meaning signal is eligible now)
                # This ensures signals are sent when they become eligible, even if recently active
                if is_transition:
                    sell_transition = True
                    transition_type = "NEW_TRANSITION"
                    logger.info(
                        f"[SIGNAL_TRANSITION] {transition_id} {symbol} SELL from=NOT-ELIGIBLE to=ELIGIBLE "
                        f"type={transition_type} alert_enabled={sell_alert_enabled} trade_enabled={trade_enabled} "
                        f"price=${current_price:.4f} reason={sell_reason}"
                    )
                else:
                    # Throttle allows emission - signal is eligible now, emit it
                    # This handles cases where signal was recently active but throttle now allows (e.g., price change, config reset)
                    sell_transition = True
                    transition_type = "THROTTLE_ALLOWED"
                    logger.info(
                        f"[SIGNAL_TRANSITION] {transition_id} {symbol} SELL signal eligible (throttle allows) "
                        f"type={transition_type} alert_enabled={sell_alert_enabled} trade_enabled={trade_enabled} "
                        f"price=${current_price:.4f} reason={sell_reason}"
                    )
        
        # Emit on transition
        if buy_transition or sell_transition:
            result["buy_transition"] = buy_transition
            result["sell_transition"] = sell_transition
            
            # Trigger signal monitor to handle emission (it has all the logic)
            # This will send Telegram and place orders if trade_enabled
            try:
                signal_monitor_service._check_signal_for_coin_sync(db, watchlist_item)
                result["telegram_sent"] = True
                result["order_placed"] = trade_enabled  # Order placement is handled by signal_monitor
                logger.info(
                    f"[TRANSITION_{transition_id}] {symbol}: Emitted alerts/orders via signal_monitor "
                    f"(BUY={buy_transition}, SELL={sell_transition})"
                )
            except Exception as emit_err:
                error_msg = str(emit_err)
                result["errors"].append(f"Emission failed: {error_msg}")
                logger.error(
                    f"[TRANSITION_{transition_id}] {symbol}: Failed to emit on transition: {emit_err}",
                    exc_info=True
                )
            
            return True, result
        
        return False, result
        
    except Exception as e:
        error_msg = str(e)
        result["errors"].append(f"Transition check failed: {error_msg}")
        logger.error(
            f"[TRANSITION_{transition_id}] {symbol}: Error checking transition: {e}",
            exc_info=True
        )
        return False, result

