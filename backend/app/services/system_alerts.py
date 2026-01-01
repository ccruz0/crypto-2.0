"""
System Alert Service
Sends operational alerts for critical system issues (stale data, stalled scheduler).
Throttled to max once per 24 hours per alert type.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.market_price import MarketPrice
from app.services.telegram_notifier import telegram_notifier
from app.services.signal_monitor import signal_monitor_service
from app.services.system_health import get_system_health, record_telegram_send_result

logger = logging.getLogger(__name__)

# Track last alert time per type (in-memory, resets on restart - acceptable for daily alerts)
_last_alert_times = {}

def _should_send_alert(alert_type: str, throttle_hours: Optional[int] = None) -> bool:
    """Check if alert should be sent (throttled to once per throttle_hours)"""
    if throttle_hours is None:
        throttle_hours = int(os.getenv("SYSTEM_ALERT_COOLDOWN_HOURS", "24"))
    
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
    if not _should_send_alert("stale_market_data"):
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
    if not _should_send_alert("stalled_scheduler"):
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
                record_telegram_send_result(True)
                logger.warning(f"[SYSTEM_ALERT] Sent stalled scheduler alert to Telegram")
                _record_alert_sent("stalled_scheduler")
            except Exception as send_err:
                record_telegram_send_result(False)
                logger.error(f"[SYSTEM_ALERT] Failed to send Telegram alert: {send_err}")
        else:
            reason = "missing_chat_id" if not telegram_notifier.chat_id else "missing_bot_token" if not telegram_notifier.bot_token else "environment_not_aws"
            logger.warning(f"[SYSTEM_ALERT_SKIPPED_TELEGRAM_DISABLED] reason={reason} message={message[:100]}")
    except Exception as e:
        logger.error(f"Error checking stalled scheduler: {e}", exc_info=True)

def evaluate_and_maybe_send_system_alert(health: Optional[Dict] = None, db: Optional[Session] = None):
    """
    Evaluate system health and send throttled SYSTEM DOWN alerts if needed.
    
    Args:
        health: Optional pre-computed health dict. If None, computes it.
        db: Optional database session. If None, creates one.
    """
    try:
        # Get health status
        if health is None:
            if db is None:
                db = SessionLocal()
                own_session = True
            else:
                own_session = False
            try:
                health = get_system_health(db)
            finally:
                if own_session:
                    db.close()
        
        if not health:
            return
        
        # Check MARKET_DATA
        market_data = health.get("market_data", {})
        if market_data.get("status") == "FAIL":
            stale_count = market_data.get("stale_symbols", 0)
            total_symbols = market_data.get("fresh_symbols", 0) + stale_count
            max_age = market_data.get("max_age_minutes")
            
            if stale_count == total_symbols and total_symbols > 0:
                alert_type = "MARKET_DATA_DOWN"
                if _should_send_alert(alert_type):
                    max_age_str = f"{max_age:.1f} min" if max_age else "unknown"
                    message = (
                        f"🚨 <b>SYSTEM DOWN</b>\n\n"
                        f"<b>Component:</b> Market Data\n"
                        f"<b>Issue:</b> All {total_symbols} symbols have stale data (max age: {max_age_str})\n"
                        f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                        f"💡 <b>Action:</b> Check market-updater-aws logs"
                    )
                    _send_system_alert(alert_type, message)
        
        # Check SIGNAL_MONITOR
        signal_monitor = health.get("signal_monitor", {})
        if signal_monitor.get("status") == "FAIL":
            alert_type = "SIGNAL_MONITOR_DOWN"
            if _should_send_alert(alert_type):
                is_running = signal_monitor.get("is_running", False)
                last_cycle_age = signal_monitor.get("last_cycle_age_minutes")
                
                if not is_running:
                    issue_text = "Signal monitor is not running"
                elif last_cycle_age:
                    issue_text = f"Last cycle was {last_cycle_age:.1f} minutes ago"
                else:
                    issue_text = "No recorded cycles"
                
                message = (
                    f"🚨 <b>SYSTEM DOWN</b>\n\n"
                    f"<b>Component:</b> Signal Monitor\n"
                    f"<b>Issue:</b> {issue_text}\n"
                    f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    f"💡 <b>Action:</b> Restart backend-aws"
                )
                _send_system_alert(alert_type, message)
        
        # TELEGRAM FAIL should NOT attempt sending (would fail anyway)
        telegram = health.get("telegram", {})
        if telegram.get("status") == "FAIL":
            logger.warning(
                f"[SYSTEM_ALERT_SKIPPED_TELEGRAM_DISABLED] "
                f"Telegram is disabled, cannot send SYSTEM DOWN alerts. "
                f"enabled={telegram.get('enabled')}, chat_id_set={telegram.get('chat_id_set')}"
            )
    
    except Exception as e:
        logger.error(f"Error evaluating system alerts: {e}", exc_info=True)

def _send_system_alert(alert_type: str, message: str):
    """Send a system alert via Telegram (if enabled)"""
    if telegram_notifier.enabled:
        try:
            telegram_notifier.send_message(message, origin="AWS")
            record_telegram_send_result(True)
            logger.warning(f"[SYSTEM_ALERT] Sent {alert_type} alert to Telegram")
            _record_alert_sent(alert_type)
        except Exception as send_err:
            record_telegram_send_result(False)
            logger.error(f"[SYSTEM_ALERT] Failed to send {alert_type} alert: {send_err}")
    else:
        reason = "missing_chat_id" if not telegram_notifier.chat_id else "missing_bot_token" if not telegram_notifier.bot_token else "environment_not_aws"
        logger.warning(f"[SYSTEM_ALERT_SKIPPED_TELEGRAM_DISABLED] reason={reason} alert_type={alert_type}")

