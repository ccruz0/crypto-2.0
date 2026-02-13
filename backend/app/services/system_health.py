"""
System Health Service
Computes overall system health status for monitoring and alerts.
Single source of truth for health checks.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.market_price import MarketPrice, MarketData
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import OrderStatusEnum
from app.services.telegram_notifier import telegram_notifier
from app.services.signal_monitor import signal_monitor_service
from app.services.order_position_service import count_total_open_positions

logger = logging.getLogger(__name__)

# Open order statuses that count toward open positions limit
OPEN_STATUSES = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]

# Module-level variable to track last Telegram send success
_last_telegram_send_ok: Optional[bool] = None
_last_telegram_send_time: Optional[datetime] = None

def record_telegram_send_result(success: bool):
    """Record the result of a Telegram send attempt"""
    global _last_telegram_send_ok, _last_telegram_send_time
    _last_telegram_send_ok = success
    _last_telegram_send_time = datetime.now(timezone.utc)

# DB connectivity timeout (ms) for /api/health/system so it never hangs on DB down
_HEALTH_DB_TIMEOUT_MS = 2000


def get_system_health(db: Session) -> Dict:
    """
    Compute system health status.
    Uses a short DB timeout so the endpoint never hangs on DB unavailability.
    
    Returns:
        Dict with global_status, timestamp, and component statuses
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Fast DB connectivity check with timeout so we never hang
    try:
        db.execute(text(f"SET statement_timeout = '{_HEALTH_DB_TIMEOUT_MS}'"))
        db.execute(text("SELECT 1"))
        db.execute(text("SET statement_timeout = '0'"))  # reset so rest of health checks are not limited
    except Exception as e:
        logger.warning(f"DB connectivity check failed (timeout or down): {e}")
        return {
            "global_status": "FAIL",
            "timestamp": timestamp,
            "db_status": "down",
            "market_data": {"status": "FAIL", "fresh_symbols": 0, "stale_symbols": 0, "max_age_minutes": None},
            "market_updater": {"status": "FAIL", "is_running": False, "last_heartbeat_age_minutes": None},
            "signal_monitor": {"status": "FAIL", "is_running": False, "last_cycle_age_minutes": None},
            "telegram": {"status": "FAIL", "enabled": False, "chat_id_set": False, "bot_token_set": False, "last_send_ok": None},
            "trade_system": {"status": "FAIL", "open_orders": 0, "max_open_orders": None, "order_intents_table_exists": False, "last_check_ok": False},
        }
    
    # Get thresholds from env (defaults)
    stale_market_minutes = float(os.getenv("HEALTH_STALE_MARKET_MINUTES", "30"))
    monitor_stale_minutes = float(os.getenv("HEALTH_MONITOR_STALE_MINUTES", "30"))
    
    # Compute component health
    market_data = _check_market_data_health(db, stale_market_minutes)
    market_updater = _check_market_updater_health(market_data, stale_market_minutes)
    signal_monitor = _check_signal_monitor_health(monitor_stale_minutes)
    telegram = _check_telegram_health()
    trade_system = _check_trade_system_health(db)
    
    # Compute global status
    global_status = "PASS"
    if any(comp["status"] == "FAIL" for comp in [market_data, market_updater, signal_monitor, telegram, trade_system]):
        global_status = "FAIL"
    elif any(comp["status"] == "WARN" for comp in [market_data, market_updater, signal_monitor, telegram, trade_system]):
        global_status = "WARN"
    
    return {
        "global_status": global_status,
        "timestamp": timestamp,
        "market_data": market_data,
        "market_updater": market_updater,
        "signal_monitor": signal_monitor,
        "telegram": telegram,
        "trade_system": trade_system,
    }

def _check_market_data_health(db: Session, stale_threshold_minutes: float) -> Dict:
    """Check market data freshness"""
    try:
        stale_threshold = timedelta(minutes=stale_threshold_minutes)
        now = datetime.now(timezone.utc)
        
        # Get all watchlist symbols
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not watchlist_items:
            return {
                "status": "WARN",
                "fresh_symbols": 0,
                "stale_symbols": 0,
                "max_age_minutes": None,
            }
        
        symbols = [item.symbol for item in watchlist_items]
        fresh_count = 0
        stale_count = 0
        max_age_minutes = 0.0
        
        for symbol in symbols:
            market_price = db.query(MarketPrice).filter(
                MarketPrice.symbol == symbol
            ).first()
            
            if not market_price or not market_price.updated_at:
                stale_count += 1
                continue
            
            # Check if stale
            updated_at = market_price.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            
            age = now - updated_at
            age_minutes = age.total_seconds() / 60
            max_age_minutes = max(max_age_minutes, age_minutes)
            
            if age > stale_threshold:
                stale_count += 1
            else:
                fresh_count += 1
        
        status = "FAIL" if stale_count == len(symbols) and len(symbols) > 0 else "PASS"
        if stale_count > 0 and stale_count < len(symbols):
            status = "WARN"
        
        return {
            "status": status,
            "fresh_symbols": fresh_count,
            "stale_symbols": stale_count,
            "max_age_minutes": round(max_age_minutes, 2) if max_age_minutes > 0 else None,
        }
    except Exception as e:
        logger.error(f"Error checking market data health: {e}", exc_info=True)
        return {
            "status": "FAIL",
            "fresh_symbols": 0,
            "stale_symbols": 0,
            "max_age_minutes": None,
        }

def _check_signal_monitor_health(stale_threshold_minutes: float) -> Dict:
    """Check signal monitor health"""
    try:
        is_running = signal_monitor_service.is_running
        last_cycle_age_minutes = None
        
        if signal_monitor_service.last_run_at:
            age = datetime.now(timezone.utc) - signal_monitor_service.last_run_at
            last_cycle_age_minutes = age.total_seconds() / 60
        
        # FAIL if not running OR last cycle age > threshold
        status = "PASS"
        if not is_running:
            status = "FAIL"
        elif last_cycle_age_minutes is not None and last_cycle_age_minutes > stale_threshold_minutes:
            status = "FAIL"
        elif last_cycle_age_minutes is None:
            # No recorded cycles yet
            status = "WARN"
        
        return {
            "status": status,
            "is_running": is_running,
            "last_cycle_age_minutes": round(last_cycle_age_minutes, 2) if last_cycle_age_minutes is not None else None,
        }
    except Exception as e:
        logger.error(f"Error checking signal monitor health: {e}", exc_info=True)
        return {
            "status": "FAIL",
            "is_running": False,
            "last_cycle_age_minutes": None,
        }

def _check_telegram_health() -> Dict:
    """Check Telegram notifier health by verifying configuration"""
    try:
        from app.core.runtime import is_aws_runtime
        from app.core.config import Settings
        
        runtime_env = "aws" if is_aws_runtime() else "local"
        settings = Settings()
        
        # Check if Telegram is enabled via RUN_TELEGRAM env var
        run_telegram = os.getenv("RUN_TELEGRAM", "").strip().lower()
        enabled_by_env = run_telegram in ("true", "1", "yes")
        
        # Check kill switch status
        from app.services.telegram_notifier import _get_telegram_kill_switch_status
        kill_switch_enabled = _get_telegram_kill_switch_status(runtime_env)
        
        # Check credentials based on environment
        if runtime_env == "aws":
            bot_token = (os.getenv("TELEGRAM_BOT_TOKEN_AWS") or settings.TELEGRAM_BOT_TOKEN_AWS or "").strip()
            chat_id = (os.getenv("TELEGRAM_CHAT_ID_AWS") or settings.TELEGRAM_CHAT_ID_AWS or "").strip()
        else:
            bot_token = (os.getenv("TELEGRAM_BOT_TOKEN_LOCAL") or settings.TELEGRAM_BOT_TOKEN_LOCAL or "").strip()
            if not bot_token:
                bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or settings.TELEGRAM_BOT_TOKEN or "").strip()
            chat_id = (os.getenv("TELEGRAM_CHAT_ID_LOCAL") or settings.TELEGRAM_CHAT_ID_LOCAL or "").strip()
            if not chat_id:
                chat_id = (os.getenv("TELEGRAM_CHAT_ID") or settings.TELEGRAM_CHAT_ID or "").strip()
        
        bot_token_set = bool(bot_token)
        chat_id_set = bool(chat_id)
        
        # Telegram is enabled if: RUN_TELEGRAM is true AND kill switch is enabled AND credentials are set
        enabled = enabled_by_env and kill_switch_enabled and bot_token_set and chat_id_set
        
        status = "PASS" if enabled else "FAIL"
        
        return {
            "status": status,
            "enabled": enabled,
            "chat_id_set": chat_id_set,
            "bot_token_set": bot_token_set,
            "run_telegram_env": enabled_by_env,
            "kill_switch_enabled": kill_switch_enabled,
            "last_send_ok": _last_telegram_send_ok,
        }
    except Exception as e:
        logger.error(f"Error checking Telegram health: {e}", exc_info=True)
        return {
            "status": "FAIL",
            "enabled": False,
            "chat_id_set": False,
            "bot_token_set": False,
            "last_send_ok": None,
        }

def _check_market_updater_health(market_data: Dict, stale_threshold_minutes: float) -> Dict:
    """Check market updater health using market data freshness as heartbeat proxy"""
    try:
        max_age_minutes = market_data.get("max_age_minutes")
        
        # If max_age_minutes is below threshold, updater is running
        # Otherwise, it's likely stopped or stalled
        if max_age_minutes is None:
            # No market data at all
            is_running = False
            last_heartbeat_age_minutes = None
        elif max_age_minutes < stale_threshold_minutes:
            # Fresh data indicates updater is running
            is_running = True
            last_heartbeat_age_minutes = max_age_minutes
        else:
            # Stale data indicates updater may be stopped
            is_running = False
            last_heartbeat_age_minutes = max_age_minutes
        
        status = "PASS" if is_running else "FAIL"
        
        return {
            "status": status,
            "is_running": is_running,
            "last_heartbeat_age_minutes": round(last_heartbeat_age_minutes, 2) if last_heartbeat_age_minutes is not None else None,
        }
    except Exception as e:
        logger.error(f"Error checking market updater health: {e}", exc_info=True)
        return {
            "status": "FAIL",
            "is_running": False,
            "last_heartbeat_age_minutes": None,
        }

def _check_trade_system_health(db: Session) -> Dict:
    """Check trade system health"""
    try:
        # Count open positions
        open_orders = count_total_open_positions(db)
        
        # Get max open orders from config (if available)
        max_open_orders = None
        try:
            from app.services.config_loader import get_trading_config
            config = get_trading_config()
            if config and "max_open_orders" in config:
                max_open_orders = config.get("max_open_orders")
        except Exception:
            pass
        
        # Check if order_intents table exists (critical for orchestrator)
        order_intents_table_exists = False
        try:
            from app.database import engine, table_exists
            from app.models.order_intent import OrderIntent
            order_intents_table = getattr(getattr(OrderIntent, "__table__", None), "name", None) or getattr(
                OrderIntent, "__tablename__", "order_intents"
            )
            order_intents_table_exists = table_exists(engine, order_intents_table)
        except Exception as table_check_err:
            logger.warning(f"Error checking order_intents table: {table_check_err}")
        
        status = "PASS"
        if not order_intents_table_exists:
            status = "FAIL"  # Critical table missing
        elif max_open_orders is not None and open_orders > max_open_orders:
            status = "WARN"
        
        return {
            "status": status,
            "open_orders": open_orders,
            "max_open_orders": max_open_orders,
            "order_intents_table_exists": order_intents_table_exists,
            "last_check_ok": True,
        }
    except Exception as e:
        logger.error(f"Error checking trade system health: {e}", exc_info=True)
        return {
            "status": "FAIL",
            "open_orders": 0,
            "max_open_orders": None,
            "order_intents_table_exists": False,
            "last_check_ok": False,
        }

