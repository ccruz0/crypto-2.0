"""Monitoring endpoint - returns system KPIs and alerts"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.signal_throttle import SignalThrottleState
import logging
import time
import asyncio
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
    order_skipped: bool = False,
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
        "order_skipped": order_skipped,
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
            # IMPORTANT: Include order_skipped in duplicate check since it's a distinct monitoring state
            # Two messages with same content but different order_skipped values are NOT duplicates
            recent_filters = [
                TelegramMessage.message == message[:500],
                TelegramMessage.symbol == symbol,
                TelegramMessage.blocked == blocked,
                TelegramMessage.order_skipped == order_skipped,
                TelegramMessage.timestamp >= datetime.now() - timedelta(seconds=5),
            ]
            recent_duplicate = db_session.query(TelegramMessage).filter(*recent_filters).first()
            
            if recent_duplicate:
                log.debug(f"Skipping duplicate Telegram message (within 5 seconds): {symbol or 'N/A'}, blocked={blocked}, order_skipped={order_skipped}")
                if own_session:
                    db_session.close()
                status_label = 'BLOQUEADO' if blocked else ('ORDEN SKIPPED' if order_skipped else 'ENVIADO')
                log.info(f"Telegram message stored (duplicate skipped): {status_label} - {symbol or 'N/A'}")
                return
            
            telegram_msg = TelegramMessage(
                message=message,
                symbol=symbol,
                blocked=blocked,
                order_skipped=order_skipped,
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
            messages = []
            for msg in db_messages:
                # Ensure order_skipped is always a boolean (handle None from old rows)
                order_skipped_val = getattr(msg, 'order_skipped', None)
                if order_skipped_val is None:
                    order_skipped_val = False
                else:
                    order_skipped_val = bool(order_skipped_val)
                
                messages.append({
                    "message": msg.message,
                    "symbol": msg.symbol,
                    "blocked": msg.blocked,
                    "order_skipped": order_skipped_val,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now().isoformat(),
                    "throttle_status": msg.throttle_status,
                    "throttle_reason": msg.throttle_reason,
                })
            
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
    recent_messages = []
    for msg in _telegram_messages:
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago:
            # Ensure order_skipped is always a boolean
            order_skipped_val = msg.get("order_skipped")
            if order_skipped_val is None:
                order_skipped_val = False
            else:
                order_skipped_val = bool(order_skipped_val)
            
            recent_messages.append({
                **msg,
                "order_skipped": order_skipped_val,
                "throttle_status": msg.get("throttle_status"),
                "throttle_reason": msg.get("throttle_reason"),
            })
    
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
        from app.models.telegram_message import TelegramMessage
        import re
        
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
            
            # Calculate price difference percentage using previous_price field
            price_change_pct = None
            if row.last_price and row.previous_price and row.last_price > 0 and row.previous_price > 0:
                try:
                    # Calculate percentage change from previous_price to last_price
                    calculated_pct = ((row.last_price - row.previous_price) / row.previous_price * 100)
                    # Only use if it's a reasonable price change (within 100% change to handle large moves)
                    if abs(calculated_pct) <= 100:
                        price_change_pct = calculated_pct
                    else:
                        log.debug(
                            f"Price change {calculated_pct:.2f}% for {row.symbol} {row.side} "
                            f"exceeds reasonable range, skipping"
                        )
                except Exception as price_err:
                    log.debug(f"Could not calculate price change for {row.symbol} {row.side}: {price_err}")
            
            payload.append(
                {
                    "symbol": row.symbol,
                    "strategy_key": row.strategy_key,
                    "side": row.side,
                    "last_price": row.last_price,
                    "last_time": last_time.isoformat() if last_time else None,
                    "seconds_since_last": seconds_since,
                    "price_change_pct": round(price_change_pct, 2) if price_change_pct is not None else None,
                }
            )
        return payload
    except Exception as exc:
        log.warning("Failed to load signal throttle state: %s", exc, exc_info=True)
        return []


# Workflow execution tracking (in-memory for now)
_workflow_executions: Dict[str, Dict[str, Any]] = {}
# Background task tracking to prevent garbage collection
_background_tasks: Dict[str, "asyncio.Task"] = {}
# Locks for atomic check-and-set operations per workflow_id
_workflow_locks: Dict[str, asyncio.Lock] = {}

def record_workflow_execution(workflow_id: str, status: str = "success", report: Optional[str] = None, error: Optional[str] = None):
    """Record a workflow execution"""
    global _workflow_executions
    _workflow_executions[workflow_id] = {
        "last_execution": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "report": report,
        "error": error,
    }
    log.info(f"Workflow execution recorded: {workflow_id} - {status}")

@router.get("/monitoring/workflows")
async def get_workflows(db: Session = Depends(get_db)):
    """Get list of all workflows with their automation status and last execution report"""
    from app.monitoring.workflows_registry import get_all_workflows
    
    # Get workflow definitions from registry to include run_endpoint
    registry_workflows = get_all_workflows()
    registry_map = {wf["id"]: wf for wf in registry_workflows}
    
    workflow_ids = [
        "watchlist_consistency",
        "daily_summary",
        "sell_orders_report",
        "sl_tp_check",
        "telegram_commands",
        "dashboard_snapshot",
    ]
    
    workflows = []
    for workflow_id in workflow_ids:
        registry_wf = registry_map.get(workflow_id, {})
        workflow = {
            "id": workflow_id,
            "name": registry_wf.get("name", workflow_id),
            "description": registry_wf.get("description", ""),
            "automated": registry_wf.get("automated", True),
            "schedule": registry_wf.get("schedule", ""),
            "run_endpoint": registry_wf.get("run_endpoint"),  # Include run_endpoint so frontend knows which can be run
            "last_execution": _workflow_executions.get(workflow_id, {}).get("last_execution"),
            "last_status": _workflow_executions.get(workflow_id, {}).get("status", "unknown"),
            "last_report": _workflow_executions.get(workflow_id, {}).get("report"),
            "last_error": _workflow_executions.get(workflow_id, {}).get("error"),
        }
        workflows.append(workflow)
    
    return {"workflows": workflows}

@router.post("/monitoring/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """Run a workflow manually by its ID"""
    from app.monitoring.workflows_registry import get_workflow_by_id
    import subprocess
    import sys
    import os
    import asyncio
    
    # Get workflow definition
    workflow = get_workflow_by_id(workflow_id)
    if not workflow:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    
    # Check if workflow has a run endpoint
    run_endpoint = workflow.get("run_endpoint")
    if not run_endpoint:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Workflow '{workflow_id}' cannot be run manually (no run_endpoint)")
    
    # For watchlist_consistency, run the script
    if workflow_id == "watchlist_consistency":
        try:
            # Calculate absolute path to the consistency check script
            # In Docker: WORKDIR is /app, backend contents are copied to /app/
            # So structure is: /app/api/routes_monitoring.py and /app/scripts/watchlist_consistency_check.py
            # In local dev: .../backend/app/api/routes_monitoring.py and .../backend/scripts/watchlist_consistency_check.py
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            # current_file_dir is /app/api/ in Docker, or .../backend/app/api/ locally
            # Go up 2 levels to get backend root: /app/ in Docker, or .../backend/ locally
            backend_root = os.path.dirname(os.path.dirname(current_file_dir))
            # In Docker: backend_root = /app/, scripts are at /app/scripts/
            # In local: backend_root = .../backend/, scripts are at .../backend/scripts/
            script_path = os.path.join(backend_root, "scripts", "watchlist_consistency_check.py")
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"Script not found at {script_path}")
            
            # Run the script asynchronously and handle completion
            async def run_script():
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        [sys.executable, script_path],
                        capture_output=True,
                        text=True,
                        timeout=600  # 10 minute timeout
                    )
                    
                    # Record completion status based on return code
                    if result.returncode == 0:
                        # Determine report path for watchlist_consistency workflow
                        report_path = None
                        if workflow_id == "watchlist_consistency":
                            from datetime import datetime
                            date_str = datetime.now().strftime("%Y%m%d")
                            # Report is generated in docs/monitoring/ relative to project root
                            # In Docker: /app/docs/monitoring/
                            # In local: .../backend/../docs/monitoring/
                            project_root = os.path.dirname(os.path.dirname(backend_root))
                            report_path = os.path.join("docs", "monitoring", f"watchlist_consistency_report_latest.md")
                            # Also check if dated report exists
                            dated_report = os.path.join("docs", "monitoring", f"watchlist_consistency_report_{date_str}.md")
                            if os.path.exists(os.path.join(project_root, dated_report)):
                                report_path = dated_report
                        
                        record_workflow_execution(
                            workflow_id, 
                            "success", 
                            report_path
                        )
                        log.info(f"Workflow {workflow_id} completed successfully")
                    else:
                        error_msg = f"Return code: {result.returncode}"
                        if result.stderr:
                            error_msg += f". STDERR: {result.stderr[:500]}"
                        record_workflow_execution(workflow_id, "error", None, error_msg)
                        log.error(f"Workflow {workflow_id} failed: {error_msg}")
                    
                    return result
                except subprocess.TimeoutExpired:
                    record_workflow_execution(workflow_id, "error", None, "Timeout after 10 minutes")
                    log.error(f"Workflow {workflow_id} timed out after 10 minutes")
                    raise
                except Exception as e:
                    record_workflow_execution(workflow_id, "error", None, str(e))
                    log.error(f"Workflow {workflow_id} error: {e}", exc_info=True)
                    raise
            
            # Use a lock per workflow_id to make check-and-set atomic
            # This prevents race conditions where two concurrent requests both pass the check
            # Use setdefault() to atomically get or create the lock for this workflow_id
            # This ensures only one lock object exists per workflow_id, even with concurrent requests
            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            
            # Acquire lock to make check-and-set atomic
            # Only one request per workflow_id can execute this block at a time
            async with workflow_lock:
                # Check if workflow is already running to prevent race conditions
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409, 
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )
                
                # Record that we started the workflow BEFORE creating the task
                # This prevents race condition where task completes and records final status
                # before we record "running" status, causing incorrect status overwrite
                record_workflow_execution(workflow_id, "running", "Workflow execution started")
                
                # Start the workflow execution (don't wait for completion)
                # Store task reference to prevent garbage collection before completion
                task = asyncio.create_task(run_script())
                _background_tasks[workflow_id] = task
                
                # Add callback to clean up task reference when done
                # IMPORTANT: Register callback while holding the lock to prevent race condition
                # where task completes before callback is registered, leaving orphaned references
                # Capture workflow_id by value (not reference) to avoid closure issues with concurrent requests
                # Using lambda with explicit capture ensures each callback has its own workflow_id value
                captured_workflow_id = workflow_id  # Capture by value
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))
            
            # Return immediately
            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            # Record error with correct workflow_id
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")
    else:
        # For other workflows, return not implemented
        from fastapi import HTTPException
        raise HTTPException(status_code=501, detail=f"Manual execution of workflow '{workflow_id}' is not yet implemented")
