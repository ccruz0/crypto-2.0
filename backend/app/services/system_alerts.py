"""
System Alert Service
Sends operational alerts for critical system issues (stale data, stalled scheduler).
Throttled to max once per 24 hours per alert type.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.market_price import MarketPrice
from app.services.telegram_notifier import telegram_notifier
from app.services.signal_monitor import signal_monitor_service

logger = logging.getLogger(__name__)

# Track last alert time per type (in-memory, resets on restart - acceptable for daily alerts)
_last_alert_times = {}

def _should_send_alert(alert_type: str, throttle_hours: int = 24) -> bool:
    """Check if alert should be sent (throttled to once per throttle_hours)"""
    now = datetime.now(timezone.utc)
    last_time = _last_alert_times.get(alert_type)
    
    if last_time is None:
        return True
    
    time_since_last = now - last_time
    if time_since_last >= timedelta(hours=throttle_hours):
        return True
    
    return False

def _record_alert_sent(alert_type: str):
    """Record that alert was sent"""
    _last_alert_times[alert_type] = datetime.now(timezone.utc)

def check_and_alert_stale_market_data():
    """Check if ALL market data is stale (>30min) and send alert if so"""
    if not _should_send_alert("stale_market_data", throttle_hours=24):
        return
    
    try:
        db = SessionLocal()
        try:
            stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
            total_symbols = db.query(MarketPrice).count()
            stale_symbols = db.query(MarketPrice).filter(MarketPrice.updated_at < stale_threshold).count()
            
            if total_symbols > 0 and stale_symbols == total_symbols:
                message = f"🚨 SYSTEM DOWN: All {total_symbols} symbols have stale market data (>30min old). Market updater may be failing."
                
                if telegram_notifier.enabled:
                    try:
                        telegram_notifier.send_message(message)
                        logger.warning(f"[SYSTEM_ALERT] Sent stale market data alert to Telegram")
                        _record_alert_sent("stale_market_data")
                    except Exception as send_err:
                        logger.error(f"[SYSTEM_ALERT] Failed to send Telegram alert: {send_err}")
                else:
                    reason = "missing_chat_id" if not telegram_notifier.chat_id else "missing_bot_token" if not telegram_notifier.bot_token else "environment_not_aws"
                    logger.warning(f"[SYSTEM_ALERT_SKIPPED_TELEGRAM_DISABLED] reason={reason} message={message[:100]}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error checking stale market data: {e}", exc_info=True)

def check_and_alert_stalled_scheduler():
    """Check if scheduler cycles have not advanced for >30min and send alert if so"""
    if not _should_send_alert("stalled_scheduler", throttle_hours=24):
        return
    
    try:
        if not signal_monitor_service.is_running:
            message = "🚨 SYSTEM DOWN: Signal monitor is not running. No signals will be detected."
        elif signal_monitor_service.last_run_at:
            time_since_last = datetime.now(timezone.utc) - signal_monitor_service.last_run_at
            if time_since_last > timedelta(minutes=30):
                minutes_stalled = int(time_since_last.total_seconds() / 60)
                message = f"🚨 SYSTEM DOWN: Signal monitor cycles have not advanced for {minutes_stalled} minutes. Scheduler may be stalled."
            else:
                return  # Scheduler is running normally
        else:
            message = "🚨 SYSTEM DOWN: Signal monitor has no recorded cycles. Scheduler may not have started."
        
        if telegram_notifier.enabled:
            try:
                telegram_notifier.send_message(message)
                logger.warning(f"[SYSTEM_ALERT] Sent stalled scheduler alert to Telegram")
                _record_alert_sent("stalled_scheduler")
            except Exception as send_err:
                logger.error(f"[SYSTEM_ALERT] Failed to send Telegram alert: {send_err}")
        else:
            reason = "missing_chat_id" if not telegram_notifier.chat_id else "missing_bot_token" if not telegram_notifier.bot_token else "environment_not_aws"
            logger.warning(f"[SYSTEM_ALERT_SKIPPED_TELEGRAM_DISABLED] reason={reason} message={message[:100]}")
    except Exception as e:
        logger.error(f"Error checking stalled scheduler: {e}", exc_info=True)

