"""Trading guardrails to enforce safety limits before order placement.

This module provides checks for:
- Live toggle (Dashboard): TradingSettings.LIVE_TRADING
- Telegram kill switch (Global): TradingSettings.TRADING_KILL_SWITCH
- Trade Yes per symbol: WatchlistItem.trade_enabled
- Optional env override: TRADING_ENABLED
- Risk limits (MAX_OPEN_ORDERS_TOTAL, MAX_ORDERS_PER_SYMBOL_PER_DAY, MAX_USD_PER_ORDER, MIN_SECONDS_BETWEEN_ORDERS)
- Optional allowlist: TRADE_ALLOWLIST (if set, restricts to listed symbols)
"""
import os
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.models.trading_settings import TradingSettings
from app.services.config_loader import get_strategy_rules
from app.services.order_position_service import count_total_open_positions
from app.services.strategy_profiles import resolve_strategy_profile
from app.utils.live_trading import get_live_trading_status

logger = logging.getLogger(__name__)


# Environment variables with defaults
MAX_OPEN_ORDERS_TOTAL = int(os.getenv("MAX_OPEN_ORDERS_TOTAL", "3"))
MAX_ORDERS_PER_SYMBOL_PER_DAY = int(os.getenv("MAX_ORDERS_PER_SYMBOL_PER_DAY", "2"))
MAX_USD_PER_ORDER = float(os.getenv("MAX_USD_PER_ORDER", "100"))
MIN_SECONDS_BETWEEN_ORDERS = int(os.getenv("MIN_SECONDS_BETWEEN_ORDERS", "600"))


def _resolve_max_orders_per_symbol_per_day(db: Session, symbol: str) -> int:
    """
    Resolve per-symbol daily order limit from strategy rules.
    Falls back to MAX_ORDERS_PER_SYMBOL_PER_DAY env default when not configured.
    """
    limit = MAX_ORDERS_PER_SYMBOL_PER_DAY
    try:
        watchlist_item = (
            db.query(WatchlistItem)
            .filter(
                WatchlistItem.symbol == symbol.upper(),
                WatchlistItem.is_deleted == False,
            )
            .first()
        )
        strategy, approach = resolve_strategy_profile(symbol, db=db, watchlist_item=watchlist_item)
        rules = get_strategy_rules(strategy.value, approach.value)
        rule_limit = rules.get("maxOrdersPerSymbolPerDay")
        if isinstance(rule_limit, (int, float)) and rule_limit >= 0:
            limit = int(rule_limit)
    except Exception as e:
        logger.debug(f"Could not resolve per-symbol daily limit from strategy rules: {e}")
    return limit


def _get_telegram_kill_switch_status(db: Session) -> bool:
    """
    Get Telegram kill switch status from TradingSettings.
    
    Returns:
        bool: True if kill switch is ON (trading disabled), False if OFF (trading allowed)
    """
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == "TRADING_KILL_SWITCH"
        ).first()
        
        if setting:
            enabled = setting.setting_value.lower() == "true"
            logger.debug(f"TRADING_KILL_SWITCH from database: {enabled}")
            return enabled
    except Exception as e:
        logger.warning(f"Error reading TRADING_KILL_SWITCH from database: {e}")
    
    # Default: kill switch OFF (trading allowed)
    return False


def _get_trade_enabled_for_symbol(db: Session, symbol: str) -> bool:
    """
    Get trade_enabled status for a symbol from WatchlistItem.
    
    Returns:
        bool: True if trade_enabled=True for this symbol, False otherwise
    """
    try:
        symbol_upper = symbol.upper()
        # Query for exact symbol match (case-insensitive via upper())
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol_upper,
            WatchlistItem.is_deleted == False
        ).first()
        
        if item:
            enabled = item.trade_enabled is True
            logger.debug(f"trade_enabled for {symbol} from database: {enabled}")
            return enabled
        
        # Symbol not in watchlist = trading disabled
        logger.debug(f"Symbol {symbol} not found in watchlist, trade_enabled=False")
        return False
    except Exception as e:
        logger.warning(f"Error reading trade_enabled for {symbol} from database: {e}")
        # Conservative: assume disabled on error
        return False


def _parse_allowlist() -> set[str]:
    """Parse TRADE_ALLOWLIST env var into a set of uppercase symbols (optional, defaults to no restriction)."""
    allowlist_str = os.getenv("TRADE_ALLOWLIST", "").strip()
    if not allowlist_str:
        return set()  # Empty allowlist = no restriction (backward compatible)
    symbols = [s.strip().upper() for s in allowlist_str.split(",") if s.strip()]
    return set(symbols)


def can_place_real_order(
    db: Session,
    symbol: str,
    order_usd_value: float,
    side: str = "BUY",
    ignore_trade_yes: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a real order can be placed based on true sources of truth.
    
    Checks in order:
    1. Live toggle must be ON (TradingSettings.LIVE_TRADING)
    2. Telegram kill switch must be OFF (TradingSettings.TRADING_KILL_SWITCH)
    3. Trade Yes for symbol must be YES (WatchlistItem.trade_enabled) - skipped if ignore_trade_yes=True
    4. TRADING_ENABLED env (optional final override - if false, always block)
    5. Optional allowlist (TRADE_ALLOWLIST, if set)
    6. Risk limits (MAX_OPEN_ORDERS_TOTAL, MAX_ORDERS_PER_SYMBOL_PER_DAY, MAX_USD_PER_ORDER, MIN_SECONDS_BETWEEN_ORDERS)
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "BTC_USDT")
        order_usd_value: USD value of the order
        side: Order side ("BUY" or "SELL")
        ignore_trade_yes: If True, skip Trade Yes check (for SL/TP orders on existing positions)
        
    Returns:
        Tuple[allowed, block_reason]
        - allowed: True if order should be placed, False if blocked
        - block_reason: Reason string if blocked, None if allowed
    """
    symbol_upper = symbol.upper()
    
    # 1. Live toggle must be ON
    try:
        live_enabled = get_live_trading_status(db)
        if not live_enabled:
            reason = "blocked: Live toggle is OFF"
            logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
            return False, reason
    except Exception as e:
        logger.error(f"Error checking Live toggle: {e}")
        # Conservative: block on error
        reason = "blocked: error checking Live toggle"
        return False, reason
    
    # 2. Telegram kill switch must be OFF
    try:
        kill_switch_on = _get_telegram_kill_switch_status(db)
        if kill_switch_on:
            reason = "blocked: Telegram kill switch is ON"
            logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
            return False, reason
    except Exception as e:
        logger.error(f"Error checking Telegram kill switch: {e}")
        # Conservative: block on error
        reason = "blocked: error checking Telegram kill switch"
        return False, reason
    
    # 3. Trade Yes for symbol must be YES (unless ignored)
    if not ignore_trade_yes:
        try:
            trade_enabled = _get_trade_enabled_for_symbol(db, symbol)
            if not trade_enabled:
                reason = f"blocked: Trade Yes is OFF for {symbol}"
                logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
                return False, reason
        except Exception as e:
            logger.error(f"Error checking Trade Yes for {symbol}: {e}")
            # Conservative: block on error
            reason = f"blocked: error checking Trade Yes for {symbol}"
            return False, reason
    
    # 4. TRADING_ENABLED env (optional final override - if false, always block)
    trading_enabled_env = os.getenv("TRADING_ENABLED", "").strip()
    if trading_enabled_env:
        if trading_enabled_env.lower() not in ("true", "1", "yes"):
            reason = "blocked: TRADING_ENABLED env is false"
            logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
            return False, reason
        # If TRADING_ENABLED=true, do NOT allow if Live is OFF or TradeYes is OFF
        # (those checks already passed above, so we continue)
    
    # 5. Optional allowlist (if set, restricts to listed symbols)
    allowlist = _parse_allowlist()
    if allowlist and symbol_upper not in allowlist:
        allowlist_str = os.getenv("TRADE_ALLOWLIST", "")
        reason = f"blocked: not in allowlist (TRADE_ALLOWLIST={allowlist_str})"
        logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
        return False, reason
    
    # 6. Risk limits (existing checks)
    return _check_risk_limits(db, symbol, order_usd_value, side)


def _check_risk_limits(
    db: Session,
    symbol: str,
    order_usd_value: float,
    side: str,
) -> Tuple[bool, Optional[str]]:
    """
    Check risk limits (MAX_OPEN_ORDERS_TOTAL, MAX_ORDERS_PER_SYMBOL_PER_DAY, MAX_USD_PER_ORDER, MIN_SECONDS_BETWEEN_ORDERS).
    
    Returns:
        Tuple[allowed, block_reason]
    """
    symbol_upper = symbol.upper()
    
    # MAX_OPEN_ORDERS_TOTAL check
    try:
        total_open = count_total_open_positions(db)
        if total_open >= MAX_OPEN_ORDERS_TOTAL:
            reason = f"blocked: MAX_OPEN_ORDERS_TOTAL limit reached ({total_open}/{MAX_OPEN_ORDERS_TOTAL})"
            logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
            return False, reason
    except Exception as e:
        logger.error(f"Error checking MAX_OPEN_ORDERS_TOTAL: {e}")
        # Conservative: block on error
        reason = "blocked: error checking open orders limit"
        return False, reason
    
    # MAX_ORDERS_PER_SYMBOL_PER_DAY check
    try:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        symbol_base = symbol_upper.split("_")[0] if "_" in symbol_upper else symbol_upper
        max_orders_per_symbol_per_day = _resolve_max_orders_per_symbol_per_day(db, symbol_upper)
        
        orders_today = db.query(func.count(ExchangeOrder.id)).filter(
            and_(
                or_(
                    ExchangeOrder.symbol == symbol_upper,
                    ExchangeOrder.symbol.like(f"{symbol_base}_%"),
                ),
                or_(
                    ExchangeOrder.exchange_create_time >= today_start,
                    ExchangeOrder.created_at >= today_start,
                ),
            )
        ).scalar() or 0
        
        if orders_today >= max_orders_per_symbol_per_day:
            reason = (
                "blocked: MAX_ORDERS_PER_SYMBOL_PER_DAY limit reached "
                f"({orders_today}/{max_orders_per_symbol_per_day})"
            )
            logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
            return False, reason
    except Exception as e:
        logger.error(f"Error checking MAX_ORDERS_PER_SYMBOL_PER_DAY: {e}")
        # Conservative: allow but log error (this is less critical than total limit)
        logger.warning(f"⚠️ Could not check per-symbol daily limit, allowing order")
    
    # MAX_USD_PER_ORDER check
    if order_usd_value > MAX_USD_PER_ORDER:
        reason = f"blocked: MAX_USD_PER_ORDER limit exceeded (${order_usd_value:.2f} > ${MAX_USD_PER_ORDER:.2f})"
        logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
        return False, reason
    
    # MIN_SECONDS_BETWEEN_ORDERS check
    try:
        symbol_base = symbol_upper.split("_")[0] if "_" in symbol_upper else symbol_upper
        
        most_recent = (
            db.query(ExchangeOrder)
            .filter(
                or_(
                    ExchangeOrder.symbol == symbol_upper,
                    ExchangeOrder.symbol.like(f"{symbol_base}_%"),
                )
            )
            .order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            )
            .first()
        )
        
        if most_recent:
            recent_time = most_recent.exchange_create_time or most_recent.created_at
            if recent_time:
                if recent_time.tzinfo is None:
                    recent_time = recent_time.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                seconds_since_last = (now_utc - recent_time).total_seconds()
                
                if seconds_since_last < MIN_SECONDS_BETWEEN_ORDERS:
                    seconds_remaining = MIN_SECONDS_BETWEEN_ORDERS - seconds_since_last
                    reason = f"blocked: MIN_SECONDS_BETWEEN_ORDERS cooldown active ({seconds_remaining:.0f}s remaining)"
                    logger.warning(f"🚫 TRADE_BLOCKED: {symbol} {side} - {reason}")
                    return False, reason
    except Exception as e:
        logger.error(f"Error checking MIN_SECONDS_BETWEEN_ORDERS: {e}")
        # Conservative: allow but log error (this is less critical than total limit)
        logger.warning(f"⚠️ Could not check cooldown, allowing order")
    
    # All risk limit checks passed
    return True, None


# Backward compatibility alias (deprecated - use can_place_real_order)
def check_trading_guardrails(
    db: Session,
    symbol: str,
    order_usd_value: float,
    side: str = "BUY",
) -> Tuple[bool, Optional[str]]:
    """Backward compatibility alias for can_place_real_order."""
    return can_place_real_order(db, symbol, order_usd_value, side)
