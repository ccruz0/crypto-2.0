"""Monitoring endpoint - returns system KPIs and alerts"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
import logging
import time
from typing import List, Dict, Optional, Any
from datetime import datetime

router = APIRouter()
log = logging.getLogger("app.monitoring")

# In-memory alert storage (simple implementation)
_active_alerts: List[Dict[str, Any]] = []
_scheduler_ticks = 0
_last_backend_restart: Optional[float] = None

# In-memory Telegram message storage (last 50 messages - blocked and sent)
_telegram_messages: List[Dict[str, Any]] = []

def add_alert(alert_type: str, symbol: str, message: str, severity: str = "WARNING"):
    """Add an alert to the active alerts list"""
    global _active_alerts
    alert = {
        "type": alert_type,
        "symbol": symbol,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "severity": severity
    }
    _active_alerts.append(alert)
    # Keep only last 100 alerts
    if len(_active_alerts) > 100:
        _active_alerts = _active_alerts[-100:]
    log.info(f"Alert added: {alert_type} - {symbol} - {message}")

def increment_scheduler_ticks():
    """Increment scheduler tick counter"""
    global _scheduler_ticks
    _scheduler_ticks += 1

def set_backend_restart_time():
    """Set the backend restart time"""
    global _last_backend_restart
    _last_backend_restart = time.time()

def clear_old_alerts(max_age_seconds: int = 3600):
    """Clear alerts older than max_age_seconds"""
    global _active_alerts
    now = time.time()
    _active_alerts = [
        alert for alert in _active_alerts
        if (now - datetime.fromisoformat(alert["timestamp"]).timestamp()) < max_age_seconds
    ]

@router.get("/monitoring/summary")
async def get_monitoring_summary(db: Session = Depends(get_db)):
    """
    Get monitoring summary with KPIs and alerts.
    Lightweight endpoint that uses snapshot data to avoid heavy computation.
    """
    start_time = time.time()
    
    try:
        # Use snapshot data instead of full dashboard state (much faster)
        from app.services.dashboard_snapshot import get_dashboard_snapshot
        snapshot = get_dashboard_snapshot(db)
        
        if snapshot and not snapshot.get("empty"):
            dashboard_state = snapshot.get("data", {})
        else:
            # If no snapshot, return minimal data (don't block on heavy computation)
            log.warning("No snapshot available for monitoring summary, returning minimal data")
            dashboard_state = {}
        
        # Calculate durations
        portfolio_state_duration = time.time() - start_time
        
        # Get last sync time
        last_sync = dashboard_state.get("last_sync") or dashboard_state.get("portfolio_last_updated")
        last_sync_seconds = None
        if last_sync:
            try:
                if isinstance(last_sync, (int, float)):
                    # Assume it's a Unix timestamp
                    if last_sync > 1000000000:  # Likely Unix timestamp in seconds
                        last_sync_seconds = int(time.time() - last_sync)
                    else:  # Likely milliseconds
                        last_sync_seconds = int((time.time() * 1000 - last_sync) / 1000)
                elif isinstance(last_sync, str):
                    # Parse ISO format
                    sync_str = last_sync.replace('Z', '+00:00')
                    sync_time = datetime.fromisoformat(sync_str)
                    now = datetime.now(sync_time.tzinfo) if sync_time.tzinfo else datetime.now()
                    last_sync_seconds = int((now - sync_time).total_seconds())
            except Exception as e:
                log.debug(f"Could not parse last_sync: {e}")
                pass
        
        # Determine backend health
        backend_health = "healthy"
        if dashboard_state.get("partial"):
            backend_health = "degraded"
        if dashboard_state.get("errors"):
            backend_health = "unhealthy"
        
        # Clean old alerts
        clear_old_alerts()
        
        # Get active alerts count
        active_alerts_count = len(_active_alerts)
        
        return {
            "active_alerts": active_alerts_count,
            "backend_health": backend_health,
            "last_sync_seconds": last_sync_seconds,
            "portfolio_state_duration": round(portfolio_state_duration, 2),
            "open_orders": len(dashboard_state.get("open_orders", [])),
            "balances": len(dashboard_state.get("balances", [])),
            "scheduler_ticks": _scheduler_ticks,
            "errors": dashboard_state.get("errors", []),
            "last_backend_restart": _last_backend_restart,
            "alerts": _active_alerts[-50:]  # Return last 50 alerts
        }
        
    except Exception as e:
        log.error(f"Error in monitoring summary: {e}", exc_info=True)
        return {
            "active_alerts": len(_active_alerts),
            "backend_health": "error",
            "last_sync_seconds": None,
            "portfolio_state_duration": round(time.time() - start_time, 2),
            "open_orders": 0,
            "balances": 0,
            "scheduler_ticks": _scheduler_ticks,
            "errors": [str(e)],
            "last_backend_restart": _last_backend_restart,
            "alerts": _active_alerts[-50:]
        }

def add_telegram_message(message: str, symbol: Optional[str] = None, blocked: bool = False):
    """Add a Telegram message to the history (blocked or sent)
    
    Messages are kept for 1 month before being removed.
    """
    global _telegram_messages
    from datetime import timedelta
    
    msg = {
        "message": message,
        "symbol": symbol,
        "blocked": blocked,
        "timestamp": datetime.now().isoformat()
    }
    _telegram_messages.append(msg)
    
    # Clean old messages (older than 1 month)
    # Keep messages from the last 30 days
    one_month_ago = datetime.now() - timedelta(days=30)
    _telegram_messages = [
        msg for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    log.info(f"Telegram message stored: {'BLOQUEADO' if blocked else 'ENVIADO'} - {symbol or 'N/A'}")

@router.get("/monitoring/telegram-messages")
async def get_telegram_messages():
    """Get Telegram messages from the last month (blocked and sent)"""
    global _telegram_messages
    from datetime import timedelta
    
    # Filter messages from the last month
    one_month_ago = datetime.now() - timedelta(days=30)
    recent_messages = [
        msg for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    # Return most recent first (newest at the top)
    recent_messages.reverse()
    
    return {
        "messages": recent_messages,
        "total": len(recent_messages)
        }

