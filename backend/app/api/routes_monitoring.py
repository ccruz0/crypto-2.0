"""Monitoring endpoint - returns system KPIs and alerts"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.signal_throttle import SignalThrottleState
import logging
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

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
    import asyncio
    
    start_time = time.time()
    
    try:
        # Use snapshot data instead of full dashboard state (much faster)
        # Bug 3 Fix: get_dashboard_snapshot is a blocking sync function, so we run it in a thread pool
        # to avoid blocking the async event loop
        from app.services.dashboard_snapshot import get_dashboard_snapshot
        snapshot = await asyncio.to_thread(get_dashboard_snapshot, db)
        
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

def add_telegram_message(
    message: str,
    symbol: Optional[str] = None,
    blocked: bool = False,
    db: Optional[Session] = None,
    throttle_status: Optional[str] = None,
    throttle_reason: Optional[str] = None,
):
    """Add a Telegram message to the history (blocked or sent)
    
    Messages are kept for 1 month before being removed.
    Now persists to database instead of just in-memory for multi-worker compatibility.
    """
    global _telegram_messages
    from datetime import timedelta
    from app.models.telegram_message import TelegramMessage
    from app.database import SessionLocal
    
    # E2E TEST LOGGING: Log monitoring save attempt
    log.info(f"[E2E_TEST_MONITORING_SAVE] message_preview={message[:80]}, symbol={symbol}, blocked={blocked}")
    
    # Also keep in-memory for backward compatibility
    msg = {
        "message": message,
        "symbol": symbol,
        "blocked": blocked,
        "timestamp": datetime.now().isoformat(),
        "throttle_status": throttle_status,
        "throttle_reason": throttle_reason,
    }
    _telegram_messages.append(msg)
    
    # Clean old messages (older than 1 month)
    one_month_ago = datetime.now() - timedelta(days=30)
    _telegram_messages = [
        msg for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    # CRITICAL: Also save to database for persistence across workers and restarts
    # Create session if not provided
    db_session = db
    own_session = False
    if db_session is None and SessionLocal is not None:
        try:
            db_session = SessionLocal()
            own_session = True
        except Exception as session_err:
            log.debug(f"Could not create database session for Telegram message: {session_err}")
            db_session = None
    
    if db_session is not None:
        try:
            # Log TEST alert monitoring save
            if "[TEST]" in message:
                log.info(
                    f"[TEST_ALERT_MONITORING_SAVED] symbol={symbol or 'UNKNOWN'}, "
                    f"blocked={blocked}, message_preview={message[:100]}"
                )
            # Check for duplicate messages within last 5 seconds to avoid duplicates from multiple workers
            recent_filters = [
                TelegramMessage.message == message[:500],
                TelegramMessage.symbol == symbol,
                TelegramMessage.blocked == blocked,
                TelegramMessage.timestamp >= datetime.now() - timedelta(seconds=5),
            ]
            recent_duplicate = db_session.query(TelegramMessage).filter(*recent_filters).first()
            
            if recent_duplicate:
                log.debug(f"Skipping duplicate Telegram message (within 5 seconds): {symbol or 'N/A'}")
                if own_session:
                    db_session.close()
                log.info(f"Telegram message stored (duplicate skipped): {'BLOQUEADO' if blocked else 'ENVIADO'} - {symbol or 'N/A'}")
                return
            
            telegram_msg = TelegramMessage(
                message=message,
                symbol=symbol,
                blocked=blocked,
                throttle_status=throttle_status,
                throttle_reason=throttle_reason,
            )
            db_session.add(telegram_msg)
            db_session.commit()
            log.debug(f"Telegram message saved to database: {'BLOQUEADO' if blocked else 'ENVIADO'} - {symbol or 'N/A'}")
        except Exception as db_err:
            log.warning(f"Could not save Telegram message to database: {db_err}")
            if db_session:
                try:
                    db_session.rollback()
                except:
                    pass
        finally:
            if own_session and db_session:
                try:
                    db_session.close()
                except:
                    pass
    
    status_label = throttle_status or ('BLOQUEADO' if blocked else 'ENVIADO')
    log.info(f"Telegram message stored: {status_label} - {symbol or 'N/A'}")

@router.get("/monitoring/telegram-messages")
async def get_telegram_messages(db: Session = Depends(get_db)):
    """Get Telegram messages from the last month (blocked and sent)
    
    Now reads from database for multi-worker compatibility and persistence.
    """
    from datetime import timedelta
    from app.models.telegram_message import TelegramMessage
    
    try:
        # Read from database if available
        if db is not None:
            one_month_ago = datetime.now() - timedelta(days=30)
            
            # Query from database
            db_messages = db.query(TelegramMessage).filter(
                TelegramMessage.timestamp >= one_month_ago
            ).order_by(TelegramMessage.timestamp.desc()).limit(500).all()
            
            # Convert to dict format for API response
            messages = [
                {
                    "message": msg.message,
                    "symbol": msg.symbol,
                    "blocked": msg.blocked,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
                    "throttle_status": msg.throttle_status,
                    "throttle_reason": msg.throttle_reason,
                }
                for msg in db_messages
            ]
            
            return {
                "messages": messages,
                "total": len(messages)
            }
    except Exception as e:
        log.warning(f"Could not read Telegram messages from database: {e}. Falling back to in-memory.")
        # Fallback to in-memory if database query fails
        pass
    
    # Fallback to in-memory storage (for backward compatibility)
    global _telegram_messages
    from datetime import timedelta
    
    one_month_ago = datetime.now() - timedelta(days=30)
    recent_messages = [
        {
            **msg,
            "throttle_status": msg.get("throttle_status"),
            "throttle_reason": msg.get("throttle_reason"),
        }
        for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    # Return most recent first (newest at the top)
    recent_messages.reverse()
    
    return {
        "messages": recent_messages,
        "total": len(recent_messages)
    }

@router.get("/monitoring/signal-throttle")
async def get_signal_throttle(limit: int = 200, db: Session = Depends(get_db)):
    """Expose recent signal throttle state for the Monitoring dashboard."""
    log.debug("Fetching signal throttle state (limit=%s)", limit)
    if db is None:
        return []
    
    try:
        bounded_limit = max(1, min(limit, 500))
        rows = (
            db.query(SignalThrottleState)
            .order_by(SignalThrottleState.last_time.desc())
            .limit(bounded_limit)
            .all()
        )
        now = datetime.now(timezone.utc)
        payload = []
        for row in rows:
            last_time = row.last_time
            if last_time and last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            seconds_since = (
                max(0, int((now - last_time).total_seconds()))
                if last_time
                else None
            )
            payload.append(
                {
                    "symbol": row.symbol,
                    "strategy_key": row.strategy_key,
                    "side": row.side,
                    "last_price": row.last_price,
                    "last_time": last_time.isoformat() if last_time else None,
                    "seconds_since_last": seconds_since,
                }
            )
        return payload
    except Exception as exc:
        log.warning("Failed to load signal throttle state: %s", exc, exc_info=True)
        return []


    
    one_month_ago = datetime.now() - timedelta(days=30)
    recent_messages = [
        {
            **msg,
            "throttle_status": msg.get("throttle_status"),
            "throttle_reason": msg.get("throttle_reason"),
        }
        for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    # Return most recent first (newest at the top)
    recent_messages.reverse()
    
    return {
        "messages": recent_messages,
        "total": len(recent_messages)
    }

@router.get("/monitoring/signal-throttle")
async def get_signal_throttle(limit: int = 200, db: Session = Depends(get_db)):
    """Expose recent signal throttle state for the Monitoring dashboard."""
    log.debug("Fetching signal throttle state (limit=%s)", limit)
    if db is None:
        return []
    
    try:
        bounded_limit = max(1, min(limit, 500))
        rows = (
            db.query(SignalThrottleState)
            .order_by(SignalThrottleState.last_time.desc())
            .limit(bounded_limit)
            .all()
        )
        now = datetime.now(timezone.utc)
        payload = []
        for row in rows:
            last_time = row.last_time
            if last_time and last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            seconds_since = (
                max(0, int((now - last_time).total_seconds()))
                if last_time
                else None
            )
            payload.append(
                {
                    "symbol": row.symbol,
                    "strategy_key": row.strategy_key,
                    "side": row.side,
                    "last_price": row.last_price,
                    "last_time": last_time.isoformat() if last_time else None,
                    "seconds_since_last": seconds_since,
                }
            )
        return payload
    except Exception as exc:
        log.warning("Failed to load signal throttle state: %s", exc, exc_info=True)
        return []

