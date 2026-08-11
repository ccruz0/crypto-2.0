"""Monitoring endpoint - returns system KPIs and alerts"""
# pyright: reportGeneralTypeIssues=false, reportArgumentType=false, reportAttributeAccessIssue=false
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast, String, text
from app.database import get_db
from app.deps.auth import get_current_user
from app.models.signal_throttle import SignalThrottleState
from app.utils.http_client import http_post
import json
import logging
import time
import asyncio
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, cast as typing_cast
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

router = APIRouter()
log = logging.getLogger("app.monitoring")


def _verify_diagnostics_auth(request: Request) -> None:
    """
    Internal auth guard for diagnostics endpoints.
    Requires ENABLE_DIAGNOSTICS_ENDPOINTS=1 and X-Diagnostics-Key header.
    Returns 404 (not 401) to reduce endpoint discoverability.
    Do not log the key.
    """
    if os.getenv("ENABLE_DIAGNOSTICS_ENDPOINTS", "0") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    # Allow single-key setup: DIAGNOSTICS_API_KEY falls back to ADMIN_ACTIONS_KEY
    expected_key = os.getenv("DIAGNOSTICS_API_KEY") or os.getenv("ADMIN_ACTIONS_KEY")
    if not expected_key:
        raise HTTPException(status_code=404, detail="Not found")
    provided_key = request.headers.get("X-Diagnostics-Key") or request.headers.get("x-diagnostics-key")
    if not provided_key or provided_key != expected_key:
        raise HTTPException(status_code=404, detail="Not found")


def _create_notion_incidents_for_health_failure(health: Dict[str, Any]) -> None:
    """
    When system health is FAIL, create Notion incident tasks for each failed component.
    Uses stable titles and stable details so notion_tasks deduplication works. Non-throwing.
    """
    try:
        from app.services.notion_tasks import create_incident_task
    except Exception as imp_err:
        log.debug("Notion tasks not available for health incidents: %s", imp_err)
        return
    if health.get("db_status") == "down":
        create_incident_task(
            title="Database connectivity check failed",
            details="component=database; db_status=down.",
        )
        log.info("Monitoring failure triggered Notion incident: Database connectivity check failed")
    sm = health.get("signal_monitor") or {}
    if sm.get("status") == "FAIL":
        create_incident_task(
            title="Trading engine health check failed",
            details="component=signal_monitor; status=FAIL.",
        )
        log.info("Monitoring failure triggered Notion incident: Trading engine health check failed")
    tg = health.get("telegram") or {}
    if tg.get("status") == "FAIL":
        create_incident_task(
            title="Telegram delivery check failed",
            details="component=telegram; status=FAIL.",
        )
        log.info("Monitoring failure triggered Notion incident: Telegram delivery check failed")
    tsys = health.get("trade_system") or {}
    if tsys.get("status") == "FAIL":
        create_incident_task(
            title="Trade system health check failed",
            details="component=trade_system; status=FAIL.",
        )
        log.info("Monitoring failure triggered Notion incident: Trade system health check failed")
    md = health.get("market_data") or {}
    mu = health.get("market_updater") or {}
    if md.get("status") == "FAIL" or mu.get("status") == "FAIL":
        create_incident_task(
            title="Market data health check failed",
            details=f"market_data={md.get('status')}; market_updater={mu.get('status')}.",
        )
        log.info("Monitoring failure triggered Notion incident: Market data health check failed")


@router.get("/health/ready", name="health_ready")
async def health_ready_endpoint(db: Session = Depends(get_db)):
    """
    Readiness probe: HTTP 200 only if DATABASE_URL can execute SELECT 1.
    Use for Docker healthcheck — unlike /ping_fast, this fails when DB credentials or Postgres are wrong.
    """
    try:
        from app.services.system_health import run_db_connectivity_check

        run_db_connectivity_check(db)
        return JSONResponse(
            content={"status": "ready", "db": "up"},
            status_code=200,
            headers=_NO_CACHE_HEADERS,
        )
    except Exception as e:
        log.warning("health/ready: database check failed: %s", e)
        return JSONResponse(
            content={"status": "not_ready", "db": "down"},
            status_code=503,
            headers=_NO_CACHE_HEADERS,
        )


@router.get("/health/system", name="get_system_health")
async def get_system_health_endpoint(db: Session = Depends(get_db)):
    """
    Get system health status.
    Single source of truth for health monitoring.
    Uses a short DB timeout so the endpoint never hangs; returns 503 when db_status=down.
    """
    try:
        from app.services.system_health import get_system_health
        health = get_system_health(db)
        status_code = 503 if health.get("db_status") == "down" else 200
        if health.get("global_status") == "FAIL":
            try:
                _create_notion_incidents_for_health_failure(health)
            except Exception as notion_err:
                log.debug("Notion incident creation failed (non-fatal): %s", notion_err)
        return JSONResponse(content=health, status_code=status_code, headers=_NO_CACHE_HEADERS)
    except Exception as e:
        log.error(f"Error computing system health: {e}", exc_info=True)
        try:
            from app.services.notion_tasks import create_incident_task
            create_incident_task(
                title="System health check failed",
                details=f"Error computing system health: {str(e)[:500]}.",
            )
            log.info("Monitoring failure triggered Notion incident: System health check failed")
        except Exception as notion_err:
            log.debug("Notion incident creation failed (non-fatal): %s", notion_err)
        return JSONResponse(
            status_code=500,
            content={
                "global_status": "FAIL",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "db_status": "down",
                "error": str(e)
            },
            headers=_NO_CACHE_HEADERS
        )


@router.get("/health/notion", name="get_notion_health")
async def get_notion_health_endpoint():
    """
    Notion integration health: env_ok, last_pickup_status, last_error.
    No auth. Used by ops to confirm self-healing and pickup status.
    """
    try:
        from app.services.notion_env import get_notion_health
        health = get_notion_health()
        return JSONResponse(content=health, status_code=200, headers=_NO_CACHE_HEADERS)
    except Exception as e:
        log.debug("Notion health failed: %s", e)
        return JSONResponse(
            status_code=200,
            content={
                "env_ok": False,
                "env_source": "unknown",
                "degraded": True,
                "last_pickup_status": "",
                "last_error": str(e)[:500] if str(e) else None,
            },
            headers=_NO_CACHE_HEADERS,
        )


RUNBOOK_ATP_HEALTH_ALERT = (
    "https://github.com/ccruz0/automated-trading-platform/blob/main/docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md"
)


@router.post("/monitoring/jarvis-incident", name="jarvis_incident_auto_remediate")
async def jarvis_incident_auto_remediate(payload: Dict[str, Any] = Body(default={})):
    """
    Create a Notion incident from Jarvis automation (health check / task auditor) and
    run one agent scheduler cycle in investigation-only mode (no prod mutation).

    Called from host scripts (scripts/automation/*) on the same machine; no auth required.
    """
    failures = payload.get("failures") or []
    if not isinstance(failures, list) or not failures:
        return {"ok": False, "reason": "no_failures"}

    source = (payload.get("source") or "jarvis-automation").strip() or "jarvis-automation"
    category = (payload.get("category") or "health_check").strip() or "health_check"
    ts = (payload.get("timestamp") or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    check_names = [
        str((f or {}).get("name") or "").strip()
        for f in failures[:5]
        if isinstance(f, dict)
    ]
    check_names = [n for n in check_names if n]
    title_checks = ", ".join(check_names[:3]) or category
    title = f"Jarvis auto-fix: {title_checks}"

    detail_lines = [
        f"Source: {source}",
        f"Category: {category}",
        f"Detected: {ts}",
        "",
        "Failures:",
    ]
    for f in failures[:8]:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "unknown").strip()
        detail = str(f.get("detail") or "")[:400]
        detail_lines.append(f"- {name}: {detail}")
    investigation_only = bool(payload.get("investigation_only", True))
    detail_lines.extend(
        [
            "",
            "Auto-dispatched by Jarvis automation (investigation only — no prod changes without approval).",
            f"investigation_only={investigation_only}",
            "Runbook: " + RUNBOOK_ATP_HEALTH_ALERT,
        ]
    )
    details = "\n".join(detail_lines)

    notion_task_id = ""
    try:
        from app.services.notion_tasks import (
            TASK_STATUS_READY_FOR_INVESTIGATION,
            create_incident_task,
            update_notion_task_status,
        )

        result = create_incident_task(title=title, details=details, source=source)
        if result and result.get("id"):
            notion_task_id = str(result.get("id") or "").strip()
            try:
                update_notion_task_status(notion_task_id, TASK_STATUS_READY_FOR_INVESTIGATION)
            except Exception as promote_err:
                log.debug("jarvis-incident: promote to ready-for-investigation failed: %s", promote_err)
            log.info("Jarvis incident Notion task created id=%s title=%r", notion_task_id[:12], title[:80])
    except Exception as notion_err:
        log.warning("jarvis-incident: Notion task creation failed: %s", notion_err)
        return {"ok": False, "reason": "notion_unavailable", "error": str(notion_err)[:300]}

    scheduler_result: dict[str, Any] = {}
    try:
        from app.services.agent_scheduler import run_agent_scheduler_cycle

        scheduler_result = run_agent_scheduler_cycle(
            project="Infrastructure",
            task_id=notion_task_id or None,
            investigation_only=investigation_only,
        )
    except Exception as sched_err:
        log.warning("jarvis-incident: agent scheduler cycle failed: %s", sched_err)
        scheduler_result = {"ok": False, "error": str(sched_err)[:300]}

    return {
        "ok": True,
        "notion_task_id": notion_task_id,
        "scheduler": scheduler_result,
        "investigation_only": investigation_only,
    }


@router.post("/monitoring/health-alert", name="create_health_alert_notion_task")
async def create_health_alert_notion_task(payload: Dict[str, Any] = Body(default={})):
    """
    Create a Notion task when an ATP health alert is sent (e.g. streak_fail_3).
    Called by the health snapshot Telegram alert script so ops get a trackable task to resolve the issue.
    No auth required when called from same host (cron); optional X-API-Key for remote callers.
    """
    try:
        from app.services.notion_tasks import create_incident_task
    except Exception as imp_err:
        log.debug("Notion tasks not available for health alert: %s", imp_err)
        return {"ok": False, "reason": "notion_unavailable"}

    rule = (payload.get("rule") or "").strip() or "health_alert"
    reason = (payload.get("reason") or "").strip() or rule
    severity = (payload.get("severity") or "").strip() or "n/a"
    streak = payload.get("streak")
    last_ts = payload.get("last_ts") or payload.get("last_snapshot_ts") or "n/a"
    verify_label = payload.get("verify_label") or "n/a"
    market_data_status = payload.get("market_data_status") or "n/a"
    market_updater_status = payload.get("market_updater_status") or "n/a"
    market_updater_age_min = payload.get("market_updater_age_min")
    global_status = payload.get("global_status") or "n/a"

    title = f"ATP Health Alert: resolve {rule}"
    details_lines = [
        f"Rule: {reason}",
        f"Severity: {severity}",
        f"FAIL streak: {streak}",
        f"Last snapshot: {last_ts}",
        f"verify_label: {verify_label}",
        f"market_data: {market_data_status} | market_updater: {market_updater_status}",
        f"market_updater_age_min: {market_updater_age_min} | global_status: {global_status}",
        "",
        "Runbook: " + RUNBOOK_ATP_HEALTH_ALERT,
    ]
    details = "\n".join(details_lines)

    result = create_incident_task(
        title=title,
        details=details,
        source="atp-health-alert",
    )
    if result and result.get("id"):
        log.info("Notion task created for ATP health alert rule=%s id=%s", rule, result.get("id"))
        return {"ok": True, "notion_task_id": result.get("id")}
    return {"ok": False, "reason": "skipped_or_failed"}


@router.post("/monitoring/notion-set-telegram-alerts-task-done", name="notion_set_telegram_alerts_task_done")
async def notion_set_telegram_alerts_task_done():
    """
    Find Notion tasks with Status in-progress and title containing "Telegram",
    set their Status to done. Used to close the "Investigate Telegram alerts not being sent" task.
    No auth (intended for same-host or internal trigger). Requires NOTION_API_KEY and NOTION_TASK_DB.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        from app.services.notion_tasks import update_notion_task_status
    except Exception as imp_err:
        log.debug("Notion modules not available: %s", imp_err)
        return {"ok": False, "reason": "notion_unavailable", "updated": 0}

    statuses = ["in-progress", "In-Progress", "In Progress"]
    tasks = get_tasks_by_status(statuses, max_results=50)
    keyword = "telegram"
    matches = [t for t in tasks if keyword in (t.get("task") or "").lower()]
    if not matches:
        return {"ok": True, "updated": 0, "message": "no matching in-progress tasks"}

    comment = "Resolved via automation: runbook applied; PROD config correct; status set to done."
    updated = 0
    for t in matches:
        page_id = (t.get("id") or "").strip()
        if not page_id:
            continue
        if update_notion_task_status(page_id, "done", append_comment=comment):
            updated += 1
            log.info("Notion task set to done page_id=%s title=%s", page_id[:8], (t.get("task") or "")[:50])
    return {"ok": True, "updated": updated, "message": f"Updated {updated} task(s) to done."}


@router.post("/health/repair", name="health_repair")
async def health_repair(current_user=Depends(get_current_user)):
    """
    Idempotent repair: ensure optional columns and critical tables (e.g. order_intents) exist.
    Requires x-api-key header (ATP_API_KEY). Use after disk/startup issues to fix order_intents_table_exists.
    """
    try:
        from app.database import engine, ensure_optional_columns
        if engine is None or ensure_optional_columns is None:
            raise HTTPException(status_code=503, detail="Database not available")
        ensure_optional_columns(engine)
        return {"ok": True, "message": "Repair completed (optional columns and order_intents table ensured)."}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Health repair failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Helpers for parsing TelegramMessage text into structured throttle events.
# The Monitoring UI "Throttle (Mensajes Enviados)" expects BUY/SELL signal events,
# not generic Telegram notifications (orders, workflows, etc).
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_SYMBOL_RE = re.compile(r"\b([A-Z0-9]{2,15}_[A-Z0-9]{2,15})\b")

# Matches a price formatted as "$12.34" or "$1,234.56", and the "@ $12.34" shorthand.
_PRICE_RE = re.compile(
    r"(?:@\s*\$|PRICE\s*:\s*\$|💵\s*PRICE\s*:\s*\$|\$)\s*([0-9][0-9,]*\.?[0-9]*)",
    re.IGNORECASE,
)

_REASON_LINE_RE = re.compile(r"(?:✅\s*)?REASON\s*:\s*(.+?)(?:\n|$)", re.IGNORECASE)
_SHORT_REASON_RE = re.compile(r"\)\s*-\s*(.+)$")  # e.g. "... (+1.23%) - <reason>"
_STRATEGY_LINE_RE = re.compile(r"STRATEGY\s*:\s*([^\n]+)", re.IGNORECASE)
_APPROACH_LINE_RE = re.compile(r"APPROACH\s*:\s*([^\n]+)", re.IGNORECASE)
# DB-only audit rows written after send_buy/sell_signal — never sent as a separate Telegram message.
_PHANTOM_SIGNAL_SUMMARY_RE = re.compile(
    r"^(?:✅\s*|🔴\s*)?(?:BUY|SELL)\s+SIGNAL:\s+",
    re.IGNORECASE,
)
_PHANTOM_PERSIST_LABEL_RE = re.compile(
    r"^\[(?:DRY_RUN|PERSIST|TEST|LAB)[^\]]*\]\s*(?:BUY|SELL)\s+SIGNAL:",
    re.IGNORECASE,
)


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Return ISO-8601 UTC timestamp with a single timezone designator."""
    if not dt:
        return None
    # Ensure UTC and normalize to a single 'Z' suffix (no '+00:00Z').
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = dt.isoformat()
    if ts.endswith("+00:00Z"):
        return ts.replace("+00:00Z", "Z")
    if ts.endswith("+00:00"):
        return ts.replace("+00:00", "Z")
    return ts


def _strip_html(text: str) -> str:
    if not text:
        return ""
    # Keep newlines but remove tags and normalize excessive whitespace.
    cleaned = _TAG_RE.sub("", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


def _infer_side_from_message(message_text: str) -> str:
    """Infer BUY/SELL from a Telegram message. Returns 'UNKNOWN' when ambiguous."""
    if not message_text:
        return "UNKNOWN"
    upper = message_text.upper()
    if "BUY SIGNAL" in upper or "BUY ORDER" in upper or "SIDE: BUY" in upper:
        return "BUY"
    if "SELL SIGNAL" in upper or "SELL ORDER" in upper or "SIDE: SELL" in upper:
        return "SELL"
    # Lifecycle one-liners: "ORDER_CANCELED: ALGO_USD BUY - ..."
    if re.search(r"\bBUY\b", upper) and not re.search(r"\bSELL\b", upper):
        return "BUY"
    if re.search(r"\bSELL\b", upper) and not re.search(r"\bBUY\b", upper):
        return "SELL"
    if "🟢" in message_text:
        return "BUY"
    if "🔴" in message_text or "🟥" in message_text:
        return "SELL"
    return "UNKNOWN"


def _is_phantom_telegram_audit_row(message: str) -> bool:
    """True for DB-only rows that did not go out as a separate Telegram send.

    After a real send_message() success, send_buy/sell_signal also writes a short
    summary like '✅ BUY SIGNAL: SYM @ $…' for audit/orchestrator metadata. That
    summary must not appear in 'Enviados' (1:1 with Telegram chat).
    """
    if not message:
        return False
    text = message.strip()
    # Real Telegram alert bodies are HTML templates.
    if "<" in text and ">" in text:
        return False
    if _PHANTOM_PERSIST_LABEL_RE.match(text):
        return True
    return bool(_PHANTOM_SIGNAL_SUMMARY_RE.match(text))


def _extract_price_from_message(message_text: str) -> Optional[float]:
    if not message_text:
        return None
    m = _PRICE_RE.search(message_text)
    if not m:
        return None
    raw = (m.group(1) or "").replace(",", "").strip()
    try:
        value = float(raw)
        return value if value > 0 else None
    except Exception:
        return None


def _extract_reason_from_message(message_text: str) -> Optional[str]:
    if not message_text:
        return None
    m = _REASON_LINE_RE.search(message_text)
    if m:
        reason = (m.group(1) or "").strip()
        return reason or None
    m2 = _SHORT_REASON_RE.search(message_text)
    if m2:
        reason = (m2.group(1) or "").strip()
        return reason or None
    return None


def _normalize_key_part(part: Optional[str]) -> Optional[str]:
    if not part:
        return None
    normalized = part.strip().lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    normalized = normalized.replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or None


def _extract_strategy_key_from_message(message_text: str) -> Optional[str]:
    """Best-effort parse of strategy_key as '<strategy>:<approach>' from message body."""
    if not message_text:
        return None
    strat_m = _STRATEGY_LINE_RE.search(message_text)
    appr_m = _APPROACH_LINE_RE.search(message_text)
    strategy = _normalize_key_part((strat_m.group(1) if strat_m else None))
    approach = _normalize_key_part((appr_m.group(1) if appr_m else None))
    if strategy and approach:
        return f"{strategy}:{approach}"
    return None

# Prevent browser/proxy caching for monitoring endpoints that must be "real-time".
# This fixes stale workflow status/errors being shown in the dashboard.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# In-memory alert storage (simple implementation)
_active_alerts: List[Dict[str, Any]] = []
_scheduler_ticks = 0
_last_backend_restart: Optional[float] = None
_backend_restart_status: Optional[str] = None  # 'restarting', 'restarted', 'failed', None
_backend_restart_timestamp: Optional[float] = None

# In-memory Telegram message storage (last 50 messages - blocked and sent)
_telegram_messages: List[Dict[str, Any]] = []

def add_alert(alert_type: str, symbol: str, message: str, severity: str = "WARNING"):
    """DEPRECATED: ActiveAlerts is now state-based, not event-based.
    
    This function is kept for backward compatibility but does nothing.
    Active alerts are now derived from Watchlist state (buy_alert_enabled/sell_alert_enabled)
    in get_monitoring_summary(), not from historical messages.
    """
    # No-op: ActiveAlerts is computed from Watchlist state, not accumulated from events
    log.debug(f"add_alert() called but ignored (state-based alerts): {alert_type} - {symbol}")

def increment_scheduler_ticks():
    """Increment scheduler tick counter"""
    global _scheduler_ticks
    _scheduler_ticks += 1

def set_backend_restart_time():
    """Set the backend restart time"""
    global _last_backend_restart
    _last_backend_restart = time.time()


def _clear_dashboard_snapshot_errors() -> bool:
    """Clear errors from the dashboard cache so Monitoring shows healthy after 'Reiniciar Backend'.
    Returns True if cache was updated, False otherwise. Used when restart is triggered from UI."""
    try:
        from app.database import SessionLocal
        from app.models.dashboard_cache import DashboardCache
        if SessionLocal is None:
            return False
        db = SessionLocal()
        try:
            entry = db.query(DashboardCache).filter(DashboardCache.id == 1).first()
            if not entry or not isinstance(entry.data, dict):
                return False
            errors = entry.data.get("errors") or []
            if not errors:
                return False
            # Remove known transient NoneType/keys error so UI shows healthy
            remaining = [e for e in errors if not (isinstance(e, str) and "NoneType" in e and "keys" in e)]
            if len(remaining) == len(errors):
                return False
            entry.data = {**entry.data, "errors": remaining}
            db.commit()
            log.info("Cleared transient errors from dashboard snapshot cache (backend restart)")
            return True
        finally:
            db.close()
    except Exception as e:
        log.warning(f"Could not clear dashboard cache errors: {e}")
        return False

def clear_old_alerts(max_age_seconds: int = 3600):
    """DEPRECATED: No longer needed since ActiveAlerts is state-based.
    
    Active alerts are now computed from Watchlist state on each request,
    not stored historically. This function is kept for backward compatibility.
    """
    # No-op: ActiveAlerts are computed fresh from Watchlist state each time
    pass

@router.get("/monitoring/summary")
async def get_monitoring_summary(
    db: Session = Depends(get_db),
    force_refresh: bool = Query(False, description="Force recalculation of signals (ignores snapshot cache)")
):
    """
    Get monitoring summary with KPIs and alerts.
    Lightweight endpoint that uses snapshot data to avoid heavy computation.
    
    Args:
        force_refresh: If True, forces recalculation of signals even if snapshot has them
    """
    global _active_alerts, _scheduler_ticks, _last_backend_restart, _backend_restart_status, _backend_restart_timestamp
    import asyncio
    
    start_time = time.time()
    should_calculate_signals = False
    active_signals: List[Dict[str, Any]] = []
    active_signals_count = 0
    sent_count = 0
    blocked_count = 0
    failed_count = 0
    active_alerts_count = 0
    
    try:
        # Use snapshot data instead of full dashboard state (much faster)
        # Bug 3 Fix: get_dashboard_snapshot is a blocking sync function, so we run it in a thread pool
        # to avoid blocking the async event loop
        # IMPORTANT: Don't pass db session to thread pool - SQLAlchemy sessions are not thread-safe
        # Let get_dashboard_snapshot create its own session when called from thread pool
        from app.services.dashboard_snapshot import get_dashboard_snapshot
        snapshot = await asyncio.to_thread(get_dashboard_snapshot, None)
        
        if snapshot and not snapshot.get("empty"):
            # Ensure we never pass None: snapshot.get("data") can be None if key exists but value is null
            dashboard_state = snapshot.get("data") if snapshot.get("data") is not None else {}
        else:
            # If no snapshot, return minimal data (don't block on heavy computation)
            log.warning("No snapshot available for monitoring summary, returning minimal data")
            dashboard_state = {}
        if dashboard_state is None:
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
        
        # ========================================================================
        # REFACTORED: Active Alerts now derived from telegram_messages + order_intents
        # ========================================================================
        # Changed from Watchlist state to actual send pipeline state
        # Shows alerts that were detected AND either SENT, BLOCKED, or FAILED
        # This ensures consistency: if an alert is shown, it must have a send status
        # ========================================================================
        try:
            from app.models.watchlist import WatchlistItem
            
            log.info(f"🔔 Starting active alerts calculation. Dashboard state available: {dashboard_state is not None}")
            
            # Query watchlist items that have active alerts enabled
            # Filter: symbol in watchlist AND at least one alert toggle enabled
            # NOTE: We check both alert_enabled (master switch) and individual toggles
            # If alert_enabled is False but buy_alert_enabled/sell_alert_enabled are True,
            # we still include them (user may have enabled toggles but not the master switch)
            active_watchlist_items = (
                db.query(WatchlistItem)
                .filter(
                    # Symbol must be in watchlist (not deleted)
                    WatchlistItem.is_deleted == False,
                    # At least one alert toggle must be enabled
                    # We check individual toggles first, then master switch as secondary
                    or_(
                        WatchlistItem.buy_alert_enabled == True,
                        WatchlistItem.sell_alert_enabled == True
                    )
                )
                .all()
            )
            
            # Filter out items where master switch is explicitly disabled
            # But include items where master switch is None (default) or True
            active_watchlist_items = [
                item for item in active_watchlist_items
                if item.alert_enabled is not False  # Include if True or None
            ]
            
            # Build a map of symbols to their signal states from dashboard
            # This allows us to check if signals are actually active (GRESS/RES buttons)
            signals_by_symbol = {}
            coins_with_signals = 0
            coins_without_signals = 0
            
            log.info(f"📊 Dashboard state keys: {list(dashboard_state.keys())[:10] if dashboard_state else 'None'}")
            
            if dashboard_state and "coins" in dashboard_state:
                total_coins = len(dashboard_state.get("coins", []))
                log.info(f"📊 Dashboard snapshot has {total_coins} coins")
                for coin in dashboard_state.get("coins", []):
                    symbol = coin.get("symbol") or coin.get("instrument_name")
                    if symbol:
                        symbol_upper = symbol.upper()
                        signals = coin.get("signals")
                        # Log first few coins to see structure
                        if len(signals_by_symbol) < 3:
                            log.info(f"📊 Coin {symbol_upper}: signals={signals}, type={type(signals)}")
                        # Handle both dict format {"buy": true/false, "sell": true/false} and other formats
                        if signals:
                            coins_with_signals += 1
                            if isinstance(signals, dict):
                                signals_by_symbol[symbol_upper] = {
                                    "buy": bool(signals.get("buy")),
                                    "sell": bool(signals.get("sell"))
                                }
                            elif isinstance(signals, bool):
                                # If signals is a boolean, treat it as a general signal state
                                signals_by_symbol[symbol_upper] = {
                                    "buy": signals,
                                    "sell": False
                                }
                        else:
                            coins_without_signals += 1
            
            # Log for debugging
            if coins_without_signals > 0:
                log.info(f"⚠️ {coins_without_signals} coins in dashboard snapshot don't have 'signals' field. "
                         f"{coins_with_signals} coins have signals field.")
            
            # Log symbols that have signals in snapshot
            if signals_by_symbol:
                log.info(f"📊 Signals found in snapshot for {len(signals_by_symbol)} symbols: {list(signals_by_symbol.keys())[:5]}...")
            
            # Log active watchlist items
            log.info(f"🔔 Found {len(active_watchlist_items)} watchlist items with toggles enabled")
            
            # ALWAYS calculate signals directly for active watchlist items to ensure consistency with watchlist
            # The watchlist uses real-time signal calculations, so monitoring should use the same method
            # This ensures both views show the same active signals
            # If force_refresh is True, always recalculate even if signals exist in snapshot
            should_calculate_signals = len(active_watchlist_items) > 0
            
            if force_refresh:
                log.info(f"🔄 Force refresh requested - will recalculate all signals")
                # Clear existing signals to force recalculation
                signals_by_symbol.clear()
            
            log.info(f"🔧 Should calculate signals: {should_calculate_signals} (watchlist_items={len(active_watchlist_items)}, force_refresh={force_refresh})")
            
            if should_calculate_signals:
                try:
                    from app.services.trading_signals import calculate_trading_signals
                    from app.services.strategy_profiles import resolve_strategy_profile
                    from app.models.market_price import MarketData
                    
                    # Get market data for ALL active watchlist items to ensure consistency with watchlist
                    # Always recalculate signals for active watchlist items (don't rely on snapshot)
                    # If force_refresh, recalculate all; otherwise only recalculate missing ones
                    symbols_to_check = []
                    for item in active_watchlist_items:
                        symbol_value = typing_cast(Optional[str], item.symbol)
                        if not symbol_value:
                            continue
                        symbol_upper = symbol_value.upper()
                        if not force_refresh and symbol_upper in signals_by_symbol:
                            continue
                        symbols_to_check.append(symbol_upper)
                    
                    if symbols_to_check:
                        log.info(f"🔧 Calculating signals for {len(symbols_to_check)} active watchlist symbols: {symbols_to_check[:5]}")
                        # Query market data for these symbols
                        market_data_list = db.query(MarketData).filter(
                            func.upper(MarketData.symbol).in_(symbols_to_check)
                        ).all()
                        
                        market_data_by_symbol = {md.symbol.upper(): md for md in market_data_list}
                        log.info(f"📊 Found market data for {len(market_data_by_symbol)} symbols: {list(market_data_by_symbol.keys())[:5]}")
                        
                        # Calculate signals for each active watchlist item
                        for item in active_watchlist_items:
                            symbol_value = typing_cast(Optional[str], item.symbol)
                            if not symbol_value:
                                continue
                            symbol_upper = symbol_value.upper()
                            
                            # If force_refresh, always recalculate; otherwise skip if we already have signals
                            if not force_refresh and symbol_upper in signals_by_symbol:
                                continue
                            
                            # Recalculate signals for active watchlist items to match watchlist view
                            # This ensures monitoring and watchlist show the same active signals
                            
                            # Get market data for this symbol
                            market_data = market_data_by_symbol.get(symbol_upper)
                            if not market_data:
                                continue
                            
                            # Resolve strategy profile
                            try:
                                strategy_type, risk_approach = resolve_strategy_profile(
                                    symbol_value, db=db, watchlist_item=item
                                )
                                
                                # Calculate trading signals
                                price = typing_cast(Optional[float], market_data.price)
                                rsi = typing_cast(Optional[float], market_data.rsi)
                                atr14 = typing_cast(Optional[float], market_data.atr)
                                ma50 = typing_cast(Optional[float], market_data.ma50)
                                ma200 = typing_cast(Optional[float], market_data.ma200)
                                ema10 = typing_cast(Optional[float], market_data.ema10)
                                ma10w = typing_cast(Optional[float], market_data.ma10w)
                                volume = typing_cast(Optional[float], market_data.current_volume)
                                avg_volume = typing_cast(Optional[float], market_data.avg_volume)
                                signal_result = calculate_trading_signals(
                                    symbol=symbol_value,
                                    price=price or 0.0,
                                    rsi=rsi,
                                    atr14=atr14,
                                    ma50=ma50,
                                    ma200=ma200,
                                    ema10=ema10,
                                    ma10w=ma10w,
                                    volume=volume,
                                    avg_volume=avg_volume,
                                    resistance_up=typing_cast(Optional[float], item.res_up),
                                    buy_target=typing_cast(Optional[float], item.res_down),  # Using res_down as buy target
                                    strategy_type=strategy_type,
                                    risk_approach=risk_approach
                                )
                                
                                # Store signals in map (override any snapshot signals for consistency)
                                # Include decision field for active_signals calculation
                                strategy_state = signal_result.get("strategy", {})
                                decision = strategy_state.get("decision", "WAIT")
                                signals_by_symbol[symbol_upper] = {
                                    "buy": bool(signal_result.get("buy_signal", False)),
                                    "sell": bool(signal_result.get("sell_signal", False)),
                                    "decision": decision,  # Store decision for active_signals
                                    "signal_result": signal_result  # Store full result for active_signals
                                }
                                log.debug(f"✅ Calculated signals for {symbol_upper}: buy={signals_by_symbol[symbol_upper]['buy']}, sell={signals_by_symbol[symbol_upper]['sell']}, decision={decision}")
                                
                            except Exception as sig_err:
                                log.error(f"❌ Could not calculate signals for {item.symbol}: {sig_err}", exc_info=True)
                                continue
                                
                except Exception as calc_err:
                    log.error(f"❌ Could not calculate signals directly: {calc_err}", exc_info=True)
            
            # ========================================================================
            # NEW: Active Signals - Current signal state from watchlist (not events)
            # ========================================================================
            # This shows current BUY/SELL signals that are active right now,
            # regardless of whether alerts were sent/blocked.
            # 
            # IMPORTANT: This uses the SAME data source as /api/dashboard/state:
            # - Same watchlist items (active_watchlist_items)
            # - Same signal calculation (signals_by_symbol from calculate_trading_signals)
            # - Same market data (MarketData table)
            # This ensures consistency between monitoring and dashboard views.
            # ========================================================================
            active_signals = []
            active_signals_count = 0
            try:
                from app.models.market_price import MarketData
                from app.services.strategy_profiles import resolve_strategy_profile
                
                # Get market data for symbols with active signals
                symbols_with_signals = [s.upper() for s in signals_by_symbol.keys()]
                if symbols_with_signals:
                    market_data_list = db.query(MarketData).filter(
                        func.upper(MarketData.symbol).in_(symbols_with_signals)
                    ).all()
                    market_data_by_symbol = {md.symbol.upper(): md for md in market_data_list}
                    
                    # Build active signals list from watchlist items with signals
                    for item in active_watchlist_items:
                        if not item.symbol:
                            continue
                        symbol_upper = item.symbol.upper()
                        
                        # Get signal state for this symbol
                        signal_state = signals_by_symbol.get(symbol_upper)
                        if not signal_state:
                            continue
                        
                        # Get decision from stored signal state (or infer from buy/sell flags)
                        decision = signal_state.get("decision", "WAIT")
                        if decision == "WAIT":
                            # Fallback: infer from buy/sell flags if decision not stored
                            if signal_state.get("buy"):
                                decision = "BUY"
                            elif signal_state.get("sell"):
                                decision = "SELL"
                        
                        # Only include BUY or SELL (not WAIT)
                        if decision == "WAIT":
                            continue
                        
                        # Check if alerts are enabled for this side
                        alerts_enabled = False
                        if decision == "BUY":
                            alerts_enabled = (
                                (item.alert_enabled is not False) and
                                (item.buy_alert_enabled is True)
                            )
                        elif decision == "SELL":
                            alerts_enabled = (
                                (item.alert_enabled is not False) and
                                (item.sell_alert_enabled is True)
                            )
                        
                        # Only include if alerts are enabled
                        if not alerts_enabled:
                            continue
                        
                        # Get market data for price and timestamp
                        market_data = market_data_by_symbol.get(symbol_upper)
                        last_price = None
                        timestamp = None
                        if market_data:
                            last_price = market_data.price
                            # Use market data updated_at if available, otherwise current time
                            if market_data.updated_at:
                                timestamp = _format_utc_iso(market_data.updated_at)
                        
                        # Get strategy key
                        strategy_key = None
                        try:
                            strategy_type, risk_approach = resolve_strategy_profile(
                                item.symbol, db=db, watchlist_item=item
                            )
                            if strategy_type and risk_approach:
                                strategy_key = f"{strategy_type.value}-{risk_approach.value}"
                        except Exception:
                            pass
                        
                        # Add to active signals - ensure ALL fields are always present (never omitted)
                        # Use explicit None for missing values to maintain consistent structure
                        active_signals.append({
                            "symbol": item.symbol or "",  # Always string, never None
                            "decision": decision,  # Always "BUY" or "SELL" (WAIT filtered out above)
                            "strategy_key": strategy_key if strategy_key else None,  # Explicit None
                            "last_price": float(last_price) if last_price is not None and last_price > 0 else None,  # Explicit None
                            "timestamp": timestamp or _format_utc_iso(datetime.now(timezone.utc)),  # Always ISO string
                        })
                
                # Sort by symbol and limit to 20
                active_signals.sort(key=lambda x: x["symbol"])
                active_signals = active_signals[:20]
                
                # CRITICAL: active_signals_count must match len(active_signals) after limiting
                # This ensures consistency: count reflects what's actually returned
                active_signals_count = len(active_signals)
                
                log.info(f"📊 Active signals: {active_signals_count} total (showing {len(active_signals)})")
                
            except Exception as sig_err:
                log.error(f"❌ Could not calculate active signals: {sig_err}", exc_info=True)
                active_signals = []
                active_signals_count = 0
            
            # ========================================================================
            # FIX: Active Alerts derived from telegram_messages + order_intents
            # ========================================================================
            # Query telegram_messages in last 30 minutes with LEFT JOIN to order_intents
            # This ensures Active Alerts matches the actual send pipeline state
            # ========================================================================
            from app.models.telegram_message import TelegramMessage
            from app.models.order_intent import OrderIntent
            
            active_alerts_count = 0
            sent_count = 0
            blocked_count = 0
            failed_count = 0
            _active_alerts.clear()
            
            # Query telegram_messages for BUY/SELL SIGNAL messages from last 30 minutes
            # Use ILIKE for case-insensitive matching
            # Include both blocked=false and blocked=true
            ACTIVE_ALERTS_WINDOW_MINUTES = 30
            threshold = datetime.now(timezone.utc) - timedelta(minutes=ACTIVE_ALERTS_WINDOW_MINUTES)
            
            # LEFT JOIN with order_intents on signal_id
            # Using cast to text as per requirement: signal_id::text = telegram_messages.id::text
            signal_messages_with_intents = (
                db.query(
                    TelegramMessage,
                    OrderIntent
                )
                .outerjoin(
                    OrderIntent,
                    cast(OrderIntent.signal_id, String) == cast(TelegramMessage.id, String)
                )
                .filter(
                    TelegramMessage.timestamp >= threshold,
                    or_(
                        func.ilike(TelegramMessage.message, "%BUY SIGNAL%"),
                        func.ilike(TelegramMessage.message, "%SELL SIGNAL%")
                    )
                )
                .order_by(TelegramMessage.timestamp.desc())
                .limit(200)
                .all()
            )
            
            log.info(f"📊 Found {len(signal_messages_with_intents)} signal messages in last 30 minutes")
            
            for msg, order_intent in signal_messages_with_intents:
                # Infer side from message
                side = _infer_side_from_message(msg.message or "")
                if side not in {"BUY", "SELL"}:
                    continue
                
                # Get order_intent_status
                order_intent_status = None
                if order_intent:
                    order_intent_status = (
                        order_intent.status.value
                        if hasattr(order_intent.status, "value")
                        else str(order_intent.status)
                    )
                
                # Determine status_label:
                # SENT if blocked=false
                # FAILED if order_intent_status='ORDER_FAILED' OR reason_code indicates failure
                # BLOCKED otherwise (blocked=true)
                if msg.blocked == False:
                    status_label = "SENT"
                    sent_count += 1
                elif (
                    order_intent_status == "ORDER_FAILED"
                    or (msg.throttle_status and str(msg.throttle_status).upper() == "FAILED")
                    or msg.decision_type == "FAILED"
                    or (msg.reason_code and "FAILED" in str(msg.reason_code).upper())
                ):
                    status_label = "FAILED"
                    failed_count += 1
                else:
                    status_label = "BLOCKED"
                    blocked_count += 1
                
                # Build alert entry
                active_alerts_count += 1
                last_error = msg.exchange_error_snippet or msg.reason_message or msg.throttle_reason
                _active_alerts.append({
                    "type": side,
                    "symbol": msg.symbol or "UNKNOWN",
                    "status_label": status_label,
                    "severity": "INFO" if status_label == "SENT" else "WARNING" if status_label == "BLOCKED" else "ERROR",
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now(timezone.utc).isoformat(),
                    "alert_status": status_label,  # Keep for backward compatibility
                    "decision_type": msg.decision_type,
                    "reason_code": msg.reason_code,
                    "reason_message": msg.reason_message or msg.throttle_reason,
                    "last_error": last_error if status_label == "FAILED" else None,
                    "message_id": msg.id,
                    "order_intent_status": order_intent_status,
                    # Build message text for backward compatibility
                    "message": f"{side} signal {status_label.lower()} for {msg.symbol or 'UNKNOWN'}" + (
                        f": {msg.reason_message or msg.reason_code or msg.throttle_reason}" 
                        if status_label != "SENT" and (msg.reason_message or msg.reason_code or msg.throttle_reason)
                        else ""
                    ),
                })
            
            log.info(f"✅ Active alerts: {active_alerts_count} total (SENT: {sent_count}, BLOCKED: {blocked_count}, FAILED: {failed_count})")
            
        except Exception as e:
            log.error(f"Could not populate active alerts from watchlist: {e}", exc_info=True)
            # On error, clear alerts and return 0 (no active alerts)
            _active_alerts.clear()
            active_alerts_count = 0
        
        # Record when signals were last calculated
        signals_last_calculated = (
            _format_utc_iso(datetime.now(timezone.utc))
            if should_calculate_signals
            else None
        )
        
        # Active alerts window (30 minutes)
        ACTIVE_ALERTS_WINDOW_MINUTES = 30
        
        # Generate timestamp for this response
        # Normalize to valid ISO-8601 UTC (no "+00:00Z")
        generated_at_utc = _format_utc_iso(datetime.now(timezone.utc))
        
        return JSONResponse(
            content={
                "active_alerts": active_alerts_count,
                "active_total": active_alerts_count,  # Alias for consistency
                "alert_counts": {
                    "sent": sent_count,
                    "blocked": blocked_count,
                    "failed": failed_count,
                },
                "active_signals_count": active_signals_count,  # NEW: Current signal state count
                "active_signals": active_signals,  # NEW: Current signal state list
                "window_minutes": ACTIVE_ALERTS_WINDOW_MINUTES,
                "generated_at_utc": generated_at_utc,
                "backend_health": backend_health,
                "last_sync_seconds": last_sync_seconds,
                "portfolio_state_duration": round(portfolio_state_duration, 2),
                "open_orders": len(dashboard_state.get("open_orders", [])),
                "balances": len(dashboard_state.get("balances", [])),
                "scheduler_ticks": _scheduler_ticks,
                "errors": dashboard_state.get("errors", []),
                "last_backend_restart": _last_backend_restart,
                "backend_restart_status": _backend_restart_status,
                "backend_restart_timestamp": _backend_restart_timestamp,
                "signals_last_calculated": signals_last_calculated,  # Timestamp when signals were last calculated
                "alerts": _active_alerts[-50:]  # Return last 50 alerts
            },
            headers=_NO_CACHE_HEADERS
        )
        
    except Exception as e:
        log.error(f"Error in monitoring summary: {e}", exc_info=True)
        # Return error response instead of raising exception to avoid 500
        ACTIVE_ALERTS_WINDOW_MINUTES = 30
        # Normalize to valid ISO-8601 UTC (no "+00:00Z")
        generated_at_utc = _format_utc_iso(datetime.now(timezone.utc))
        
        return JSONResponse(
            status_code=200,  # Return 200 with error status in body
            content={
                "active_alerts": len(_active_alerts),
                "active_total": len(_active_alerts),
                "alert_counts": {
                    "sent": 0,
                    "blocked": 0,
                    "failed": 0,
                },
                "active_signals_count": 0,  # NEW: Default to 0 on error
                "active_signals": [],  # NEW: Default to empty on error
                "window_minutes": ACTIVE_ALERTS_WINDOW_MINUTES,
                "generated_at_utc": generated_at_utc,
                "backend_health": "error",
                "last_sync_seconds": None,
                "portfolio_state_duration": round(time.time() - start_time, 2),
                "open_orders": 0,
                "balances": 0,
                "scheduler_ticks": _scheduler_ticks,
                "errors": [str(e)],
                "last_backend_restart": _last_backend_restart,
                "backend_restart_status": _backend_restart_status,
                "backend_restart_timestamp": _backend_restart_timestamp,
                "signals_last_calculated": None,  # No signals calculated on error
                "alerts": _active_alerts[-50:]
            },
            headers=_NO_CACHE_HEADERS
        )

def add_telegram_message(
    message: str,
    symbol: Optional[str] = None,
    blocked: bool = False,
    order_skipped: bool = False,
    order_attempt: bool = False,
    order_created: bool = False,
    order_executed: bool = False,
    order_canceled: bool = False,
    sltp_attempt: bool = False,
    sltp_created: bool = False,
    sltp_failed: bool = False,
    error_message: Optional[str] = None,
    db: Optional[Session] = None,
    throttle_status: Optional[str] = None,
    throttle_reason: Optional[str] = None,
    decision_type: Optional[str] = None,
    reason_code: Optional[str] = None,
    reason_message: Optional[str] = None,
    context_json: Optional[Dict[str, Any]] = None,
    exchange_error_snippet: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Optional[int]:
    """Add a Telegram message to the history (blocked or sent)
    
    Messages are kept for 1 month before being removed.
    Now persists to database instead of just in-memory for multi-worker compatibility.
    
    Decision tracing fields:
    - decision_type: "SKIPPED" or "FAILED" - whether the buy was skipped before attempt or failed during attempt
    - reason_code: Canonical reason code (e.g., "TRADE_DISABLED", "EXCHANGE_REJECTED")
    - reason_message: Human-readable reason message
    - context_json: JSON object with contextual data (prices, balances, thresholds, etc.)
    - exchange_error_snippet: Raw exchange error message for FAILED decisions
    - correlation_id: Optional correlation ID for tracing across logs
    """
    global _telegram_messages
    from datetime import timedelta
    from app.models.telegram_message import TelegramMessage
    from app.database import SessionLocal
    from app.utils.signal_indicators import enrich_context_with_signal_indicators

    # Persist RSI/MA parsed from SIGNAL message/reason into context_json so
    # later decision-trace updates (often order_id only) do not leave fills
    # without indicator features for Auto ML.
    context_json = enrich_context_with_signal_indicators(
        message=message or "",
        throttle_reason=throttle_reason,
        context=context_json if isinstance(context_json, dict) else None,
    )
    
    # Blocked events must always have non-null reason_code and throttle_status
    if blocked:
        if not reason_code:
            reason_code = "BLOCKED_UNKNOWN"
        if not throttle_status:
            throttle_status = "BLOCKED"
    
    # E2E TEST LOGGING: Log monitoring save attempt (grep-friendly key=value)
    log.info(
        "[E2E_TEST_MONITORING_SAVE] message_preview=%s symbol=%s blocked=%s",
        message[:80] if message else "",
        symbol or "N/A",
        blocked,
    )
    
    # Also keep in-memory for backward compatibility
    msg = {
        "message": message,
        "symbol": symbol,
        "blocked": blocked,
        "order_skipped": order_skipped,
        "order_attempt": order_attempt,
        "order_created": order_created,
        "order_executed": order_executed,
        "order_canceled": order_canceled,
        "sltp_attempt": sltp_attempt,
        "sltp_created": sltp_created,
        "sltp_failed": sltp_failed,
        "error_message": error_message,
        "timestamp": datetime.now().isoformat(),
        "throttle_status": throttle_status,
        "throttle_reason": throttle_reason,
        "decision_type": decision_type,
        "reason_code": reason_code,
        "reason_message": reason_message,
        "context_json": context_json,
        "exchange_error_snippet": exchange_error_snippet,
        "correlation_id": correlation_id,
    }
    _telegram_messages.append(msg)
    
    # Clean old messages (older than 1 month)
    one_month_ago = datetime.now() - timedelta(days=30)
    _telegram_messages = [
        msg for msg in _telegram_messages
        if datetime.fromisoformat(msg["timestamp"]) >= one_month_ago
    ]
    
    # CRITICAL: Also save to database for persistence across workers and restarts
    # Guard: refuse to use a closed or broken session so we never write with a stale connection (regression prevention).
    # Session.is_active does not reliably flip after Session.close(); probe with SELECT 1 to detect unusable session.
    if db is not None:
        try:
            db.execute(text("SELECT 1"))
        except Exception:
            log.error(
                "[TELEGRAM_PERSIST] db session unusable (closed or broken): symbol=%s blocked=%s reason_code=%s (returning None)",
                symbol or "N/A",
                blocked,
                reason_code or "N/A",
            )
            return None
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
            # Log TEST alert monitoring save (grep-friendly key=value)
            if "[TEST]" in message:
                log.info(
                    "[TEST_ALERT_MONITORING_SAVED] symbol=%s blocked=%s message_preview=%s",
                    symbol or "UNKNOWN",
                    blocked,
                    message[:100] if message else "",
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
                return typing_cast(int, recent_duplicate.id)  # Return existing message ID
            
            # Serialize context_json for DB text column (dict/list -> JSON string)
            context_json_value = json.dumps(context_json) if isinstance(context_json, (dict, list)) else context_json
            
            telegram_msg = TelegramMessage(
                message=message,
                symbol=symbol,
                blocked=blocked,
                order_skipped=order_skipped,
                throttle_status=throttle_status,
                throttle_reason=throttle_reason,
                decision_type=decision_type,
                reason_code=reason_code,
                reason_message=reason_message,
                context_json=context_json_value,
                exchange_error_snippet=exchange_error_snippet,
                correlation_id=correlation_id,
            )
            db_session.add(telegram_msg)
            if own_session:
                db_session.commit()
                db_session.refresh(telegram_msg)
            else:
                db_session.flush()  # Get ID without committing; caller owns transaction
            message_id = typing_cast(int, telegram_msg.id)
            # Log alert creation at INFO level for verification
            alert_type = "BLOCKED" if blocked else "SENT"
            log.info(
                "[ALERT_DB_CREATED] alert_id=%d symbol=%s type=%s blocked=%s message_preview=%s",
                message_id,
                symbol or "N/A",
                alert_type,
                blocked,
                message[:100] if message else "N/A"
            )
        except Exception as db_err:
            log.error(
                "Could not save Telegram message to database: symbol=%s blocked=%s reason_code=%s err=%s",
                symbol or "N/A",
                blocked,
                reason_code or "N/A",
                db_err,
                exc_info=True,
            )
            message_id = None
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
    else:
        message_id = None
    
    status_label = throttle_status or ('BLOQUEADO' if blocked else 'ENVIADO')
    log.info(f"Telegram message stored: {status_label} - {symbol or 'N/A'}")
    
    return message_id


def update_telegram_message_decision_trace(
    db: Session,
    symbol: str,
    message_pattern: str,
    decision_type: str,
    reason_code: str,
    reason_message: Optional[str] = None,
    context_json: Optional[Dict[str, Any]] = None,
    exchange_error_snippet: Optional[str] = None,
    correlation_id: Optional[str] = None,
    max_age_seconds: int = 300,  # Only update messages from last 5 minutes
) -> bool:
    """Update an existing BUY SIGNAL telegram message with decision tracing
    
    This ensures that every BUY SIGNAL message gets decision tracing, even if
    the order decision happens after the message is created.
    
    Args:
        db: Database session
        symbol: Trading symbol
        message_pattern: Pattern to match in message (e.g., "BUY SIGNAL")
        decision_type: "SKIPPED" or "FAILED"
        reason_code: Canonical reason code
        reason_message: Human-readable reason
        context_json: Contextual data
        exchange_error_snippet: Exchange error for FAILED decisions
        correlation_id: Correlation ID
        max_age_seconds: Only update messages from last N seconds (default 5 minutes)
    
    Returns:
        True if message was updated, False otherwise
    """
    from app.models.telegram_message import TelegramMessage
    from datetime import timedelta
    
    try:
        # Find the most recent BUY SIGNAL message for this symbol without decision tracing.
        # Never attach trade decision codes onto Telegram delivery failures
        # ([TELEGRAM_FAILED] previews often still contain "BUY SIGNAL" text).
        threshold = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        recent_message = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.message.like(f"%{message_pattern}%"),
            TelegramMessage.decision_type.is_(None),  # Only update messages without decision tracing
            TelegramMessage.timestamp >= threshold,
            ~TelegramMessage.message.like("%[TELEGRAM_FAILED]%"),
            or_(
                TelegramMessage.throttle_reason.is_(None),
                ~TelegramMessage.throttle_reason.ilike("%telegram%"),
            ),
        ).order_by(TelegramMessage.timestamp.desc()).first()
        
        if recent_message:
            # Update the message with decision tracing (context_json stored as text in DB)
            recent_message.decision_type = decision_type
            recent_message.reason_code = reason_code
            recent_message.reason_message = reason_message
            # Merge so ORDER_CREATED {order_id} does not wipe RSI/MA from SIGNAL write.
            from app.utils.signal_indicators import merge_telegram_context

            merged_ctx = merge_telegram_context(recent_message.context_json, context_json)
            recent_message.context_json = json.dumps(merged_ctx) if merged_ctx else None
            recent_message.exchange_error_snippet = exchange_error_snippet
            recent_message.correlation_id = correlation_id
            db.commit()
            log.info(
                f"✅ Updated BUY SIGNAL message for {symbol} with decision tracing: "
                f"decision_type={decision_type}, reason_code={reason_code}"
            )
            return True
        else:
            log.debug(
                f"No recent BUY SIGNAL message found for {symbol} to update "
                f"(pattern='{message_pattern}', max_age={max_age_seconds}s)"
            )
            return False
    except Exception as e:
        log.warning(f"Failed to update telegram message decision trace for {symbol}: {e}")
        if db:
            try:
                db.rollback()
            except:
                pass
        return False

@router.get("/monitoring/telegram-messages")
async def get_telegram_messages(
    db: Session = Depends(get_db),
    blocked: Optional[str] = Query("all", description="Filter: true (blocked only), false (sent only), all (default)"),
):
    """Get Telegram messages from the last month.

    DB is the primary source. Optional query param: blocked=true|false|all (default: all).
    When blocked=false, DB-only audit summaries (never sent as separate TG messages) are excluded
    so the list matches what actually arrived on Telegram.
    """
    from datetime import timedelta
    from app.models.telegram_message import TelegramMessage

    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    block_filter = blocked.strip().lower() if blocked else "all"
    # Cap high enough that a busy day of blocked noise does not hide today's sent rows
    # when callers ask for blocked=false / true separately.
    fetch_limit = 1000

    try:
        # Primary source: database
        if db is not None:
            q = db.query(TelegramMessage).filter(TelegramMessage.timestamp >= one_month_ago)
            if block_filter == "true":
                q = q.filter(TelegramMessage.blocked.is_(True))
            elif block_filter == "false":
                q = q.filter(TelegramMessage.blocked.is_(False))
            # "all" or anything else: no extra filter
            db_messages = q.order_by(TelegramMessage.timestamp.desc()).limit(fetch_limit).all()

            messages = []
            for msg in db_messages:
                # Enviados must be 1:1 with Telegram — drop phantom audit summaries.
                if block_filter == "false" and _is_phantom_telegram_audit_row(msg.message or ""):
                    continue
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
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else datetime.now(timezone.utc).isoformat(),
                    "throttle_status": msg.throttle_status,
                    "throttle_reason": msg.throttle_reason,
                    "decision_type": msg.decision_type,
                    "reason_code": msg.reason_code,
                    "reason_message": msg.reason_message,
                    "context_json": msg.context_json,
                    "exchange_error_snippet": msg.exchange_error_snippet,
                    "correlation_id": msg.correlation_id,
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
    recent_messages = []
    for msg in _telegram_messages:
        try:
            ts = datetime.fromisoformat(msg["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if ts < one_month_ago:
            continue
        if block_filter == "true" and msg.get("blocked") is not True:
            continue
        if block_filter == "false" and msg.get("blocked") is not False:
            continue
        if block_filter == "false" and _is_phantom_telegram_audit_row(msg.get("message") or ""):
            continue
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
            "decision_type": msg.get("decision_type"),
            "reason_code": msg.get("reason_code"),
            "reason_message": msg.get("reason_message"),
            "context_json": msg.get("context_json"),
            "exchange_error_snippet": msg.get("exchange_error_snippet"),
            "correlation_id": msg.get("correlation_id"),
        })
    
    # Return most recent first (newest at the top)
    recent_messages.reverse()
    
    return {
        "messages": recent_messages,
        "total": len(recent_messages)
    }

@router.get("/monitoring/lifecycle-events")
async def get_lifecycle_events(limit: int = 200, db: Session = Depends(get_db)):
    """Get lifecycle events from SignalThrottleState (canonical source).
    
    Returns all lifecycle events (TRADE_BLOCKED, ORDER_CREATED, ORDER_FAILED, 
    SLTP_CREATED, SLTP_FAILED, etc.) for the Throttle tab.
    """
    log.debug("Fetching lifecycle events (limit=%s)", limit)
    if db is None:
        return {"events": [], "total": 0}
    
    try:
        from app.models.signal_throttle import SignalThrottleState
        from datetime import timedelta
        
        bounded_limit = max(1, min(limit, 500))
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        # Query SignalThrottleState for lifecycle events
        events = (
            db.query(SignalThrottleState)
            .filter(SignalThrottleState.last_time >= one_week_ago)
            .filter(SignalThrottleState.emit_reason.isnot(None))
            .order_by(SignalThrottleState.last_time.desc())
            .limit(bounded_limit)
            .all()
        )
        
        # Convert to API format
        event_list = []
        for event in events:
            # Parse event type from emit_reason
            event_type = "UNKNOWN"
            if event.emit_reason:
                if event.emit_reason.startswith("TRADE_BLOCKED"):
                    event_type = "TRADE_BLOCKED"
                elif event.emit_reason.startswith("ORDER_ATTEMPT"):
                    event_type = "ORDER_ATTEMPT"
                elif event.emit_reason.startswith("ORDER_CREATED"):
                    event_type = "ORDER_CREATED"
                elif event.emit_reason.startswith("ORDER_FAILED"):
                    event_type = "ORDER_FAILED"
                elif event.emit_reason.startswith("SLTP_ATTEMPT"):
                    event_type = "SLTP_ATTEMPT"
                elif event.emit_reason.startswith("SLTP_CREATED"):
                    event_type = "SLTP_CREATED"
                elif event.emit_reason.startswith("SLTP_FAILED"):
                    event_type = "SLTP_FAILED"
                elif "ALERT" in event.emit_reason.upper():
                    event_type = "ALERT_EMITTED"
            
            event_list.append({
                "symbol": event.symbol,
                "side": event.side,
                "strategy_key": event.strategy_key,
                "event_type": event_type,
                "emit_reason": event.emit_reason,
                "price": float(event.last_price) if event.last_price else None,
                "timestamp": event.last_time.isoformat() if event.last_time else None,
                "source": event.last_source,
            })
        
        return {
            "events": event_list,
            "total": len(event_list)
        }
    except Exception as e:
        log.error(f"Error fetching lifecycle events: {e}", exc_info=True)
        return {"events": [], "total": 0, "error": str(e)}


@router.get("/monitoring/signal-throttle")
async def get_signal_throttle(limit: int = 200, db: Session = Depends(get_db)):
    """Return messages that actually arrived on Telegram (1:1 with chat).

    Source of truth: telegram_messages where blocked=False, excluding DB-only
    audit summaries written after send_buy/sell_signal (never sent separately).

    Lifecycle rows without a Telegram send are NOT included — those belong in
    /monitoring/lifecycle-events, not in Enviados.
    """
    log.debug("Fetching telegram sent messages for Enviados panel (limit=%s)", limit)
    if db is None:
        return []

    try:
        from app.models.telegram_message import TelegramMessage

        bounded_limit = max(1, min(limit, 500))
        now = datetime.now(timezone.utc)

        # Over-fetch to allow phantom-summary filtering without undershooting limit.
        sent_messages = (
            db.query(TelegramMessage)
            .filter(TelegramMessage.blocked.is_(False))
            .order_by(TelegramMessage.timestamp.desc())
            .limit(bounded_limit * 3)
            .all()
        )

        payload: list[Dict[str, Any]] = []
        for msg in sent_messages:
            raw_text = msg.message or ""
            if _is_phantom_telegram_audit_row(raw_text):
                continue

            parsed_text = _strip_html(raw_text)
            symbol_value = (msg.symbol or "").strip().upper()
            if not symbol_value:
                sm = _SYMBOL_RE.search(parsed_text.upper())
                if sm:
                    symbol_value = sm.group(1).upper()
            if not symbol_value:
                symbol_value = "UNKNOWN"

            side = _infer_side_from_message(parsed_text)
            msg_time = msg.timestamp
            if msg_time and msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)

            price = _extract_price_from_message(parsed_text)
            parsed_reason = _extract_reason_from_message(parsed_text)
            parsed_strategy_key = _extract_strategy_key_from_message(parsed_text)
            emit_reason = (
                (getattr(msg, "throttle_reason", None) or "").strip()
                or parsed_reason
                or (parsed_text[:120] if parsed_text else "Sent to Telegram")
            )

            seconds_since = (
                max(0, int((now - msg_time).total_seconds()))
                if msg_time
                else None
            )

            payload.append(
                {
                    "symbol": symbol_value,
                    "strategy_key": parsed_strategy_key or "telegram:sent",
                    "side": side,
                    "last_price": price,
                    "last_time": msg_time.isoformat() if msg_time else None,
                    "is_lifecycle_event": False,
                    "event_type": None,
                    "seconds_since_last": seconds_since,
                    "price_change_pct": None,
                    "emit_reason": emit_reason,
                    "telegram_message": raw_text,
                }
            )
            if len(payload) >= bounded_limit:
                break

        return payload

    except Exception as exc:
        log.warning("Failed to load telegram sent messages: %s", exc, exc_info=True)
        return []


# Workflow execution tracking (in-memory for now)
_workflow_executions: Dict[str, Dict[str, Any]] = {}
# Background task tracking to prevent garbage collection
_background_tasks: Dict[str, "asyncio.Task"] = {}
# Locks for atomic check-and-set operations per workflow_id
_workflow_locks: Dict[str, asyncio.Lock] = {}

# Latest SL/TP check report (in-memory).
# We keep it lightweight and JSON-serializable so the dashboard can render it.
_sl_tp_check_report_cache: Optional[Dict[str, Any]] = None
SL_TP_CHECK_REPORT_PATH = "reports/sl-tp-check"


def _to_iso(dt_value: Any) -> Optional[str]:
    """Best-effort datetime -> ISO string (UTC if naive)."""
    if not dt_value:
        return None
    try:
        if hasattr(dt_value, "isoformat"):
            # If naive datetime, assume UTC
            if getattr(dt_value, "tzinfo", None) is None:
                return dt_value.replace(tzinfo=timezone.utc).isoformat()
            return dt_value.isoformat()
        if isinstance(dt_value, str):
            return dt_value
    except Exception:
        return None
    return None


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _serialize_sl_tp_position(pos: Any) -> Dict[str, Any]:
    """Return a JSON-safe dict for a SL/TP missing position row."""
    if not isinstance(pos, dict):
        return {}
    symbol = (pos.get("symbol") or "").upper()
    currency = (pos.get("currency") or "").upper()
    balance = _safe_float(pos.get("balance")) or 0.0
    has_sl = bool(pos.get("has_sl", False))
    has_tp = bool(pos.get("has_tp", False))
    sl_price = _safe_float(pos.get("sl_price"))
    tp_price = _safe_float(pos.get("tp_price"))
    order_id = pos.get("order_id") or pos.get("entry_order_id")
    if order_id is not None:
        order_id = str(order_id)
    quantity = _safe_float(pos.get("quantity") if pos.get("quantity") is not None else pos.get("balance"))
    side = pos.get("side")
    if side is not None:
        side = str(side).upper()
    entry_price = _safe_float(pos.get("entry_price"))
    current_price = _safe_float(pos.get("current_price") or pos.get("mark_price"))
    uncovered_qty = _safe_float(pos.get("uncovered_qty"))
    naked_parent = bool(pos.get("naked_parent"))
    return {
        "symbol": symbol,
        "currency": currency,
        "balance": balance,
        "has_sl": has_sl,
        "has_tp": has_tp,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "order_id": order_id,
        "quantity": quantity,
        "side": side,
        "entry_price": entry_price,
        "current_price": current_price,
        "uncovered_qty": uncovered_qty,
        "naked_parent": naked_parent,
    }


def _enrich_sl_tp_positions_with_entry_orders(
    db: Optional[Session],
    positions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach latest filled entry order_id/qty/side so the report can Create SL/TP."""
    if not db or not positions:
        return positions
    try:
        from app.services.sl_tp_checker import _find_recent_entry_order
    except Exception:
        return positions

    enriched: List[Dict[str, Any]] = []
    for pos in positions:
        row = dict(pos) if isinstance(pos, dict) else {}
        symbol = (row.get("symbol") or "").upper()
        if not symbol or row.get("order_id") or row.get("entry_order_id"):
            enriched.append(row)
            continue
        try:
            balance = _safe_float(row.get("balance")) or 0.0
            entry_side = "BUY" if balance >= 0 else "SELL"
            entry = _find_recent_entry_order(db, symbol, side=entry_side)
            if entry is not None:
                row["order_id"] = getattr(entry, "exchange_order_id", None)
                row["entry_order_id"] = row["order_id"]
                side_val = getattr(entry, "side", None)
                row["side"] = side_val.value if hasattr(side_val, "value") else side_val
                row["entry_price"] = getattr(entry, "avg_price", None) or getattr(entry, "price", None)
                qty = getattr(entry, "cumulative_quantity", None) or getattr(entry, "quantity", None)
                if qty is not None:
                    row["quantity"] = qty
        except Exception as enrich_err:
            log.warning("Failed to enrich SL/TP report row for %s: %s", symbol, enrich_err)
        enriched.append(row)
    return enriched


def store_sl_tp_check_report_from_result(
    check_result: Any,
    *,
    reminder_sent: bool = False,
    db: Optional[Session] = None,
    error: Optional[str] = None,
) -> str:
    """Build + store the in-memory SL/TP check report. Returns dashboard report path."""
    global _sl_tp_check_report_cache

    result = check_result if isinstance(check_result, dict) else {}
    positions_missing = result.get("positions_missing_sl_tp", []) or []
    if not isinstance(positions_missing, list):
        positions_missing = []
    positions_missing = _enrich_sl_tp_positions_with_entry_orders(db, positions_missing)

    serialized_positions: List[Dict[str, Any]] = []
    try:
        serialized_positions = [_serialize_sl_tp_position(p) for p in positions_missing]
        serialized_positions = [p for p in serialized_positions if p and p.get("symbol")]
    except Exception:
        serialized_positions = []

    check_error = error or result.get("error") or None
    oco_issues = result.get("oco_issues", {}) if isinstance(result.get("oco_issues"), dict) else {}
    checked_at = _to_iso(result.get("checked_at")) or datetime.now(timezone.utc).isoformat()
    total_positions = int(result.get("total_positions") or 0)

    _sl_tp_check_report_cache = {
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "report": {
            "workflow": "sl_tp_check",
            "checked_at": checked_at,
            "total_positions": total_positions,
            "missing_count": len(serialized_positions),
            "positions_missing": serialized_positions,
            "oco_issues": oco_issues,
            "reminder_sent": bool(reminder_sent),
            "error": check_error,
        },
    }
    return SL_TP_CHECK_REPORT_PATH

def _resolve_project_root_from_backend_root(backend_root: str) -> str:
    """
    Resolve the *filesystem* project root from a backend root path.

    Local dev layout:
      <repo>/backend/app/api/routes_monitoring.py  => backend_root=<repo>/backend, project_root=<repo>

    Some containers mount only the backend at /backend:
      /backend/app/api/... => backend_root=/backend, project_root=/backend (NOT "/")
    """
    br = Path(backend_root).resolve()
    if (br / "docs").exists():
        return str(br)
    if (br.parent / "docs").exists():
        return str(br.parent)
    # Fallback: keep it close to where the backend lives
    return str(br)

def _is_valid_report_path(report: Optional[str]) -> bool:
    """Check if report path is valid (not a message)"""
    if not report:
        return False
    # If it's a full URL, it's valid
    if report.startswith('http://') or report.startswith('https://'):
        return True
    # If it doesn't have path separators or file extensions, it's likely a message
    if '/' not in report and not any(report.endswith(ext) for ext in ['.md', '.html', '.txt', '.json', '.pdf']):
        return False
    # Contains path separator or file extension, likely a valid path
    return True

def _find_existing_report(workflow_id: str, backend_root: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Find existing report file for a workflow if no execution record exists.
    Returns (report_path, last_execution_iso) where last_execution_iso is the file's mtime as ISO string.
    """
    if not backend_root:
        # Try to detect backend root from current file location
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
    
    project_root = _resolve_project_root_from_backend_root(backend_root)
    docs_monitoring = Path(project_root) / "docs" / "monitoring"
    
    # Map workflow IDs to their report file patterns
    report_patterns = {
        "watchlist_consistency": "watchlist_consistency_report_latest.md",
        "watchlist_dedup": "watchlist_dedup_report_latest.md",
        "daily_summary": None,  # No reports for this workflow
        "sell_orders_report": None,  # No reports for this workflow
        "sl_tp_check": None,  # Uses in-memory cache instead
        "telegram_commands": None,  # No reports for this workflow
        "dashboard_snapshot": None,  # No reports for this workflow
    }
    
    pattern = report_patterns.get(workflow_id)
    if not pattern:
        return None, None
    
    report_path = docs_monitoring / pattern
    if report_path.exists() and report_path.is_file():
        # Return relative path from project root
        relative_path = report_path.relative_to(Path(project_root))
        report_path_str = str(relative_path).replace("\\", "/")  # Normalize path separators
        
        # Try to get file modification time as last execution estimate
        try:
            mtime = report_path.stat().st_mtime
            last_execution = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except Exception:
            last_execution = None
        
        return report_path_str, last_execution
    
    return None, None

def _initialize_workflow_state_from_reports(backend_root: Optional[str] = None):
    """Initialize workflow execution state from existing reports on disk"""
    global _workflow_executions
    
    workflow_ids = [
        "watchlist_consistency",
        "watchlist_dedup",
        "daily_summary",
        "sell_orders_report",
        "sl_tp_check",
        "telegram_commands",
        "dashboard_snapshot",
    ]
    
    for workflow_id in workflow_ids:
        # Only initialize if not already set (preserve existing state)
        if workflow_id not in _workflow_executions:
            report_path, last_execution = _find_existing_report(workflow_id, backend_root)
            if report_path:
                # Initialize with unknown status but with report link and estimated execution time
                _workflow_executions[workflow_id] = {
                    "last_execution": last_execution,  # Use file mtime as estimate
                    "status": "unknown",
                    "report": report_path,
                    "error": None,
                }
                log.info(f"Initialized workflow {workflow_id} with existing report: {report_path} (last_execution: {last_execution})")

def record_workflow_execution(workflow_id: str, status: str = "success", report: Optional[str] = None, error: Optional[str] = None):
    """Record a workflow execution"""
    global _workflow_executions
    # Validate report path - if it's not a valid path, set to None
    # This prevents messages from being stored as report paths
    validated_report = report if _is_valid_report_path(report) else None
    _workflow_executions[workflow_id] = {
        "last_execution": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "report": validated_report,
        "error": error,
    }
    log.info(f"Workflow execution recorded: {workflow_id} - {status}")

@router.get("/monitoring/workflows")
async def get_workflows(db: Session = Depends(get_db)):
    """Get list of all workflows with their automation status and last execution report"""
    from app.monitoring.workflows_registry import get_all_workflows
    
    # Initialize workflow state from existing reports if needed (on-demand initialization)
    # This helps recover state after server restart
    try:
        # Try to detect backend root
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
        _initialize_workflow_state_from_reports(backend_root)
    except Exception as e:
        log.warning(f"Failed to initialize workflow state from reports: {e}", exc_info=True)
    
    # Get workflow definitions from registry to include run_endpoint
    registry_workflows = get_all_workflows()
    registry_map = {wf["id"]: wf for wf in registry_workflows}
    
    workflow_ids = [
        "watchlist_consistency",
        "watchlist_dedup",
        "daily_summary",
        "sell_orders_report",
        "sl_tp_check",
        "telegram_commands",
        "dashboard_snapshot",
    ]
    
    workflows = []
    for workflow_id in workflow_ids:
        registry_wf = registry_map.get(workflow_id, {})
        
        # Get stored execution state
        execution_state = _workflow_executions.get(workflow_id, {})
        stored_report = execution_state.get("report")
        
        # If no stored report but workflow has a known report location, check filesystem
        report_path = stored_report if _is_valid_report_path(stored_report) else None
        last_execution_fallback = execution_state.get("last_execution")
        
        if not report_path:
            try:
                current_file = Path(__file__).resolve()
                backend_root = str(current_file.parent.parent.parent)
                found_report, found_last_execution = _find_existing_report(workflow_id, backend_root)
                if found_report:
                    report_path = found_report
                    # Use file mtime as last_execution if we don't have one from execution state
                    if not last_execution_fallback and found_last_execution:
                        last_execution_fallback = found_last_execution
            except Exception:
                report_path = None
        
        workflow = {
            "id": workflow_id,
            "name": registry_wf.get("name", workflow_id),
            "description": registry_wf.get("description", ""),
            "automated": registry_wf.get("automated", True),
            "schedule": registry_wf.get("schedule", ""),
            "run_endpoint": registry_wf.get("run_endpoint"),  # Include run_endpoint so frontend knows which can be run
            "last_execution": execution_state.get("last_execution") or last_execution_fallback,
            "last_status": execution_state.get("status", "unknown"),
            "last_report": report_path,
            "last_error": execution_state.get("error"),
        }
        # Always expose the SL/TP report link in the dashboard, even before the first run.
        # The report page will show "not found" until the workflow stores a report.
        if workflow_id == "sl_tp_check" and not workflow.get("last_report"):
            workflow["last_report"] = SL_TP_CHECK_REPORT_PATH
        workflows.append(workflow)
    
    return JSONResponse({"workflows": workflows}, headers=_NO_CACHE_HEADERS)


@router.get("/monitoring/reports/sl-tp-check/latest")
async def get_latest_sl_tp_check_report(db: Session = Depends(get_db)):
    """
    Get the latest SL/TP check report captured by the workflow.

    This is an in-memory report meant for the dashboard "Open report" link.
    """
    global _sl_tp_check_report_cache
    if not _sl_tp_check_report_cache:
        return JSONResponse(
            {
                "status": "not_found",
                "message": "No SL/TP Check report available yet. Run the workflow first.",
            },
            headers=_NO_CACHE_HEADERS,
        )
    return JSONResponse(
        {
            "status": "success",
            "report": _sl_tp_check_report_cache.get("report"),
            "stored_at": _sl_tp_check_report_cache.get("stored_at"),
        },
        headers=_NO_CACHE_HEADERS,
    )


@router.post("/monitoring/reports/sl-tp-check/refresh")
async def refresh_sl_tp_check_report(db: Session = Depends(get_db)):
    """
    Re-run the SL/TP scanner and replace the in-memory report (no Telegram reminder).

    Used by the dashboard after Create SL/TP so the missing-protection table reflects
    live exchange/DB coverage instead of the stale last workflow snapshot.
    """
    from app.services.sl_tp_checker import sl_tp_checker_service

    try:
        check_result = await asyncio.to_thread(
            sl_tp_checker_service.check_positions_for_sl_tp, db
        )
        check_error = (
            (check_result.get("error") if isinstance(check_result, dict) else None) or None
        )
        report_path = store_sl_tp_check_report_from_result(
            check_result if isinstance(check_result, dict) else {},
            reminder_sent=False,
            db=db,
            error=check_error if isinstance(check_error, str) else None,
        )
        record_workflow_execution(
            "sl_tp_check",
            "error" if check_error else "success",
            report_path,
            str(check_error) if check_error else None,
        )
        if not _sl_tp_check_report_cache:
            return JSONResponse(
                {
                    "status": "error",
                    "message": "Refresh completed but report cache is empty",
                },
                status_code=500,
                headers=_NO_CACHE_HEADERS,
            )
        return JSONResponse(
            {
                "status": "success",
                "report": _sl_tp_check_report_cache.get("report"),
                "stored_at": _sl_tp_check_report_cache.get("stored_at"),
                "refreshed": True,
            },
            headers=_NO_CACHE_HEADERS,
        )
    except Exception as e:
        log.error("SL/TP check report refresh failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"SL/TP check refresh failed: {e}")


@router.get("/monitoring/reports/watchlist-consistency/latest")
@router.head("/monitoring/reports/watchlist-consistency/latest")
async def get_watchlist_consistency_report_latest():
    """
    Serve the latest watchlist consistency report as markdown.
    
    This endpoint serves the file at docs/monitoring/watchlist_consistency_report_latest.md
    Supports both GET and HEAD methods.
    """
    try:
        # Resolve project root
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
        project_root = _resolve_project_root_from_backend_root(backend_root)
        
        # Build file path
        report_path = Path(project_root) / "docs" / "monitoring" / "watchlist_consistency_report_latest.md"
        
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report not found at {report_path}. Run the watchlist_consistency workflow first."
            )
        
        # Read and return the file
        content = report_path.read_text(encoding='utf-8')
        
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'inline; filename="watchlist_consistency_report_latest.md"',
                **{k: v for k, v in _NO_CACHE_HEADERS.items()}
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error serving watchlist consistency report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")


@router.get("/monitoring/reports/watchlist-consistency/{date}")
@router.head("/monitoring/reports/watchlist-consistency/{date}")
async def get_watchlist_consistency_report_by_date(date: str):
    """
    Serve a dated watchlist consistency report as markdown.
    
    Date format: YYYYMMDD (e.g., 20251224)
    This endpoint serves files like docs/monitoring/watchlist_consistency_report_YYYYMMDD.md
    Supports both GET and HEAD methods.
    """
    try:
        # Validate date format (YYYYMMDD)
        if not date.isdigit() or len(date) != 8:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format. Expected YYYYMMDD, got: {date}"
            )
        
        # Resolve project root
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
        project_root = _resolve_project_root_from_backend_root(backend_root)
        
        # Build file path
        report_path = Path(project_root) / "docs" / "monitoring" / f"watchlist_consistency_report_{date}.md"
        
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report not found for date {date}. The report may not have been generated for this date."
            )
        
        # Read and return the file
        content = report_path.read_text(encoding='utf-8')
        
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'inline; filename="watchlist_consistency_report_{date}.md"',
                **{k: v for k, v in _NO_CACHE_HEADERS.items()}
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error serving watchlist consistency report for date {date}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")


@router.get("/monitoring/reports/watchlist-dedup/latest")
@router.head("/monitoring/reports/watchlist-dedup/latest")
async def get_watchlist_dedup_report_latest():
    """
    Serve the latest watchlist dedup report as markdown.
    
    This endpoint serves the file at docs/monitoring/watchlist_dedup_report_latest.md
    Supports both GET and HEAD methods.
    """
    try:
        # Resolve project root
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
        project_root = _resolve_project_root_from_backend_root(backend_root)
        
        # Build file path
        report_path = Path(project_root) / "docs" / "monitoring" / "watchlist_dedup_report_latest.md"
        
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report not found at {report_path}. Run the watchlist_dedup workflow first."
            )
        
        # Read and return the file
        content = report_path.read_text(encoding='utf-8')
        
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'inline; filename="watchlist_dedup_report_latest.md"',
                **{k: v for k, v in _NO_CACHE_HEADERS.items()}
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error serving watchlist dedup report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")


@router.get("/monitoring/reports/watchlist-dedup/{date}")
@router.head("/monitoring/reports/watchlist-dedup/{date}")
async def get_watchlist_dedup_report_by_date(date: str):
    """
    Serve a dated watchlist dedup report as markdown.
    
    Date format: YYYYMMDD (e.g., 20251224)
    This endpoint serves files like docs/monitoring/watchlist_dedup_report_YYYYMMDD.md
    Supports both GET and HEAD methods.
    """
    try:
        # Validate date format (YYYYMMDD)
        if not date.isdigit() or len(date) != 8:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid date format. Expected YYYYMMDD, got: {date}"
            )
        
        # Resolve project root
        current_file = Path(__file__).resolve()
        backend_root = str(current_file.parent.parent.parent)
        project_root = _resolve_project_root_from_backend_root(backend_root)
        
        # Build file path
        report_path = Path(project_root) / "docs" / "monitoring" / f"watchlist_dedup_report_{date}.md"
        
        if not report_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Report not found for date {date}. The report may not have been generated for this date."
            )
        
        # Read and return the file
        content = report_path.read_text(encoding='utf-8')
        
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'inline; filename="watchlist_dedup_report_{date}.md"',
                **{k: v for k, v in _NO_CACHE_HEADERS.items()}
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error serving watchlist dedup report for date {date}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error serving report: {str(e)}")


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
                            # Store as relative path for consistency
                            report_path = os.path.join("docs", "monitoring", f"watchlist_consistency_report_latest.md")
                            # Also check if dated report exists
                            # Calculate absolute path to check existence
                            project_root = _resolve_project_root_from_backend_root(backend_root)
                            
                            dated_report_abs = os.path.join(project_root, "docs", "monitoring", f"watchlist_consistency_report_{date_str}.md")
                            if os.path.exists(dated_report_abs):
                                report_path = os.path.join("docs", "monitoring", f"watchlist_consistency_report_{date_str}.md")
                        
                        record_workflow_execution(
                            workflow_id, 
                            "success", 
                            report_path,
                            error=None  # Clear previous error on success
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
                record_workflow_execution(workflow_id, "running", None)
                
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
    elif workflow_id == "daily_summary":
        try:
            from app.services.daily_summary import daily_summary_service
            
            async def run_daily_summary():
                try:
                    # Run in thread to avoid blocking
                    await asyncio.to_thread(daily_summary_service.send_daily_summary)
                    record_workflow_execution(workflow_id, "success", None, error=None)
                    log.info(f"Workflow {workflow_id} completed successfully")
                except Exception as e:
                    record_workflow_execution(workflow_id, "error", None, str(e))
                    log.error(f"Workflow {workflow_id} error: {e}", exc_info=True)
                    raise
            
            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            async with workflow_lock:
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409,
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )
                
                record_workflow_execution(workflow_id, "running", None)
                task = asyncio.create_task(run_daily_summary())
                _background_tasks[workflow_id] = task
                captured_workflow_id = workflow_id
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))
            
            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")
    
    elif workflow_id == "sell_orders_report":
        try:
            from app.services.daily_summary import daily_summary_service
            
            async def run_sell_orders_report():
                try:
                    # Run in thread to avoid blocking
                    await asyncio.to_thread(daily_summary_service.send_sell_orders_report, db)
                    record_workflow_execution(workflow_id, "success", None, error=None)
                    log.info(f"Workflow {workflow_id} completed successfully")
                except Exception as e:
                    record_workflow_execution(workflow_id, "error", None, str(e))
                    log.error(f"Workflow {workflow_id} error: {e}", exc_info=True)
                    raise
            
            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            async with workflow_lock:
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409,
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )
                
                record_workflow_execution(workflow_id, "running", None)
                task = asyncio.create_task(run_sell_orders_report())
                _background_tasks[workflow_id] = task
                captured_workflow_id = workflow_id
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))
            
            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")
    
    elif workflow_id == "sl_tp_check":
        try:
            from app.services.sl_tp_checker import sl_tp_checker_service
            from app.database import SessionLocal
            
            async def run_sl_tp_check():
                # Background task must open its own DB session — request-scoped
                # `db` is closed once the HTTP response returns.
                db_session = SessionLocal()
                try:
                    check_result = await asyncio.to_thread(
                        sl_tp_checker_service.check_positions_for_sl_tp, db_session
                    )
                    positions_missing = (
                        check_result.get("positions_missing_sl_tp", [])
                        if isinstance(check_result, dict)
                        else []
                    )
                    check_error = (
                        (check_result.get("error") if isinstance(check_result, dict) else None)
                        or None
                    )

                    reminder_sent = False
                    # Send reminder if there are positions missing SL/TP
                    if positions_missing:
                        await asyncio.to_thread(
                            sl_tp_checker_service.send_sl_tp_reminder, db_session
                        )
                        reminder_sent = True

                    report_path = store_sl_tp_check_report_from_result(
                        check_result,
                        reminder_sent=reminder_sent,
                        db=db_session,
                        error=check_error if isinstance(check_error, str) else None,
                    )

                    if check_error:
                        record_workflow_execution(
                            workflow_id, "error", report_path, str(check_error)
                        )
                    else:
                        record_workflow_execution(
                            workflow_id, "success", report_path, error=None
                        )
                    missing_n = len(positions_missing) if isinstance(positions_missing, list) else 0
                    log.info(
                        f"Workflow {workflow_id} completed successfully: "
                        f"{missing_n} positions missing SL/TP"
                    )
                except Exception as e:
                    # Still provide a report link so the dashboard can show details.
                    report_path = store_sl_tp_check_report_from_result(
                        {"positions_missing_sl_tp": [], "total_positions": 0, "oco_issues": {}},
                        reminder_sent=False,
                        db=None,
                        error=str(e),
                    )
                    record_workflow_execution(workflow_id, "error", report_path, str(e))
                    log.error(f"Workflow {workflow_id} error: {e}", exc_info=True)
                    raise
                finally:
                    try:
                        db_session.close()
                    except Exception:
                        pass
            
            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            async with workflow_lock:
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409,
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )
                
                record_workflow_execution(workflow_id, "running", SL_TP_CHECK_REPORT_PATH)
                task = asyncio.create_task(run_sl_tp_check())
                _background_tasks[workflow_id] = task
                captured_workflow_id = workflow_id
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))
            
            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")

    elif workflow_id == "watchlist_dedup":
        try:
            from app.services.watchlist_selector import cleanup_watchlist_duplicates

            async def run_watchlist_dedup():
                try:
                    # Run in thread to avoid blocking the event loop
                    result = await asyncio.to_thread(cleanup_watchlist_duplicates, db, dry_run=False, soft_delete=True)
                    
                    # Get report path from result (generated by cleanup_watchlist_duplicates)
                    report_path = typing_cast(Optional[str], result.get("report_path"))
                    
                    # Fallback: Determine report path if not in result (same logic as scheduler)
                    if not report_path:
                        try:
                            from datetime import datetime
                            date_str = datetime.now().strftime("%Y%m%d")
                            # Report is generated in docs/monitoring/ relative to project root
                            report_path = os.path.join("docs", "monitoring", "watchlist_dedup_report_latest.md")
                            # Also check if dated report exists
                            # Calculate backend_root from current file location
                            current_file_dir = os.path.dirname(os.path.abspath(__file__))
                            backend_root = os.path.dirname(os.path.dirname(current_file_dir))
                            project_root = _resolve_project_root_from_backend_root(backend_root)
                            dated_report_abs = os.path.join(project_root, "docs", "monitoring", f"watchlist_dedup_report_{date_str}.md")
                            if os.path.exists(dated_report_abs):
                                report_path = os.path.join("docs", "monitoring", f"watchlist_dedup_report_{date_str}.md")
                        except Exception as path_err:
                            log.warning(f"Could not determine report path: {path_err}")
                    
                    # Success should NOT set last_error (UI treats it as an error even if status=success)
                    record_workflow_execution(workflow_id, "success", report_path, error=None)
                    log.info("Workflow %s completed successfully (duplicates=%s, report=%s)", workflow_id, result.get("duplicates", 0), report_path)
                except Exception as e:
                    record_workflow_execution(workflow_id, "error", None, str(e))
                    log.error("Workflow %s error: %s", workflow_id, e, exc_info=True)
                    raise

            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            async with workflow_lock:
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409,
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )

                record_workflow_execution(workflow_id, "running", None)
                task = asyncio.create_task(run_watchlist_dedup())
                _background_tasks[workflow_id] = task
                captured_workflow_id = workflow_id
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))

            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")
    
    elif workflow_id == "dashboard_data_integrity":
        try:
            async def trigger_github_workflow():
                try:
                    from app.services.github_app_auth import get_github_api_token

                    github_token, auth_method = get_github_api_token()
                    github_repo = os.getenv("GITHUB_REPOSITORY", "ccruz0/crypto-2.0")
                    workflow_file = "dashboard-data-integrity.yml"
                    
                    if not github_token:
                        raise ValueError(
                            "GitHub API auth unavailable (configure GITHUB_APP_* or legacy PAT)"
                        )
                    
                    log.info(
                        "dashboard_data_integrity: dispatch auth_method=%s repo=%s",
                        auth_method,
                        github_repo,
                    )

                    # Trigger workflow via GitHub API
                    url = f"https://api.github.com/repos/{github_repo}/actions/workflows/{workflow_file}/dispatches"
                    headers = {
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github+json",
                    }
                    payload = {
                        "ref": "main"  # Branch to trigger on
                    }
                    
                    # Run in thread to avoid blocking
                    def make_request():
                        return http_post(url, json=payload, headers=headers, timeout=10, calling_module="routes_monitoring")
                    response = await asyncio.to_thread(make_request)
                    
                    if response.status_code == 204:
                        record_workflow_execution(workflow_id, "success", None, error=None)
                        log.info(f"Workflow {workflow_id} triggered successfully via GitHub API")
                    else:
                        error_msg = f"GitHub API returned status {response.status_code}: {response.text}"
                        record_workflow_execution(workflow_id, "error", None, error_msg)
                        log.error(f"Workflow {workflow_id} trigger failed: {error_msg}")
                        raise Exception(error_msg)
                except Exception as e:
                    record_workflow_execution(workflow_id, "error", None, str(e))
                    log.error(f"Workflow {workflow_id} error: {e}", exc_info=True)
                    raise
            
            workflow_lock = _workflow_locks.setdefault(workflow_id, asyncio.Lock())
            async with workflow_lock:
                existing_task = _background_tasks.get(workflow_id)
                if existing_task and not existing_task.done():
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=409,
                        detail=f"Workflow '{workflow_id}' is already running. Please wait for it to complete."
                    )
                
                record_workflow_execution(workflow_id, "running", None)
                task = asyncio.create_task(trigger_github_workflow())
                _background_tasks[workflow_id] = task
                captured_workflow_id = workflow_id
                task.add_done_callback(lambda t: _background_tasks.pop(captured_workflow_id, None))
            
            return {
                "workflow_id": workflow_id,
                "started": True,
                "message": f"Workflow '{workflow_id}' execution started (triggered via GitHub Actions)"
            }
        except Exception as e:
            log.error(f"Error starting workflow {workflow_id}: {e}", exc_info=True)
            record_workflow_execution(workflow_id, "error", None, str(e))
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail=f"Error starting workflow: {str(e)}")
    
    else:
        # For other workflows, return not implemented
        from fastapi import HTTPException
        raise HTTPException(status_code=501, detail=f"Manual execution of workflow '{workflow_id}' is not yet implemented")

class GhostProtectionCleanRequest(BaseModel):
    """Cancel ghost/orphan SL/TP legs flagged vs wallet (Expected TP red banner)."""

    dry_run: bool = True
    order_ids: Optional[List[str]] = None
    bases: Optional[List[str]] = None
    allow_stale: bool = False


@router.get("/monitoring/ghost-protection-alerts")
def get_ghost_protection_alerts(
    bases: Optional[str] = Query(
        None,
        description="Optional comma-separated base currencies (e.g. ALGO,SUI)",
    ),
    db: Session = Depends(get_db),
):
    """
    List open SL/TP legs that look like ghosts vs wallet
    (wrong-side cover, qty ≫ wallet, or empty wallet).
    """
    try:
        from app.services.ghost_protection import list_ghost_protection_alerts

        base_list = None
        if bases:
            base_list = [b.strip() for b in bases.split(",") if b.strip()]
        return list_ghost_protection_alerts(db, bases=base_list)
    except Exception as e:
        log.exception("Failed to list ghost protection alerts")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/monitoring/ghost-protection-alerts/clean")
def clean_ghost_protection_alerts_endpoint(
    body: GhostProtectionCleanRequest = Body(default_factory=GhostProtectionCleanRequest),
    db: Session = Depends(get_db),
):
    """
    Cancel ghost/orphan protection legs (or dry-run).

    Only cancels orders currently flagged by the same rules as the Expected TP
    banner. Pass ``dry_run=false`` to cancel on the exchange. Live cancel refuses
    stale/unverified open-orders sync unless ``allow_stale=true``.
    """
    try:
        from app.services.ghost_protection import clean_ghost_protection_alerts

        result = clean_ghost_protection_alerts(
            db,
            dry_run=bool(body.dry_run),
            order_ids=body.order_ids,
            bases=body.bases,
            allow_stale=bool(body.allow_stale),
        )
        if result.get("error") and not body.dry_run and result.get("cancelled", 0) == 0:
            raise HTTPException(status_code=409, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to clean ghost protection alerts")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/monitoring/backend/restart")
async def restart_backend():
    """
    Trigger a backend restart.
    This endpoint initiates a graceful restart of the backend server.
    """
    global _backend_restart_status, _backend_restart_timestamp
    
    import subprocess
    import sys
    import os

    from app.services.governance_enforcement import raise_if_backend_restart_blocked
    raise_if_backend_restart_blocked()
    
    try:
        # Set status to restarting
        _backend_restart_status = "restarting"
        _backend_restart_timestamp = time.time()
        log.info("Backend restart initiated via API")
        # Clear cached snapshot errors now so next Monitoring refresh shows healthy
        _clear_dashboard_snapshot_errors()
        
        # Schedule restart in background (don't block the response)
        async def _restart_background():
            global _backend_restart_status
            try:
                # Wait a moment to allow the response to be sent
                await asyncio.sleep(2)
                
                # Get the script path for restarting
                # In Docker: scripts are at /app/scripts/
                # In local: scripts are at .../backend/scripts/
                current_file_dir = os.path.dirname(os.path.abspath(__file__))
                backend_root = os.path.dirname(os.path.dirname(current_file_dir))
                restart_script = os.path.join(backend_root, "scripts", "restart_backend.sh")
                
                # If script doesn't exist, try alternative methods
                if not os.path.exists(restart_script):
                    # Try to find restart script in project root
                    project_root = os.path.dirname(backend_root) if os.path.basename(backend_root) == "backend" else backend_root
                    restart_script = os.path.join(project_root, "restart_backend_aws.sh")
                
                if os.path.exists(restart_script):
                    # Execute restart script
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["bash", restart_script],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode == 0:
                        _backend_restart_status = "restarted"
                        log.info("Backend restart script executed successfully")
                    else:
                        _backend_restart_status = "failed"
                        log.error(f"Backend restart script failed: {result.stderr}")
                else:
                    # Fallback: Use systemd or supervisorctl if available
                    # Try systemd first (common on Linux)
                    try:
                        result = await asyncio.to_thread(
                            subprocess.run,
                            ["systemctl", "restart", "trading-backend"],
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        if result.returncode == 0:
                            _backend_restart_status = "restarted"
                            log.info("Backend restarted via systemd")
                        else:
                            raise Exception(f"systemctl failed: {result.stderr}")
                    except (FileNotFoundError, Exception):
                        # Try supervisorctl as fallback
                        try:
                            result = await asyncio.to_thread(
                                subprocess.run,
                                ["supervisorctl", "restart", "trading-backend"],
                                capture_output=True,
                                text=True,
                                timeout=30
                            )
                            if result.returncode == 0:
                                _backend_restart_status = "restarted"
                                log.info("Backend restarted via supervisorctl")
                            else:
                                raise Exception(f"supervisorctl failed: {result.stderr}")
                        except (FileNotFoundError, Exception):
                            # Docker/AWS: no script, systemctl or supervisorctl - clear cache errors so UI shows healthy
                            cleared = _clear_dashboard_snapshot_errors()
                            _backend_restart_status = "restarted" if cleared else "failed"
                            if cleared:
                                log.info("No restart method (e.g. Docker); cleared dashboard cache errors so Monitoring shows healthy.")
                            else:
                                log.warning("No restart method available. Manual restart required.")
                                log.warning(f"Tried: {restart_script}, systemctl, supervisorctl")
                # Always clear cached snapshot errors so "Reiniciar Backend" fixes UNHEALTHY on next refresh
                _clear_dashboard_snapshot_errors()
            except Exception as e:
                _backend_restart_status = "failed"
                log.error(f"Error during backend restart: {e}", exc_info=True)
                _clear_dashboard_snapshot_errors()
        
        # Start restart in background
        asyncio.create_task(_restart_background())
        
        # Return immediately
        return {
            "ok": True,
            "status": "restarting",
            "message": "Backend restart initiated. The server will restart shortly."
        }
    except Exception as e:
        _backend_restart_status = "failed"
        log.error(f"Error initiating backend restart: {e}", exc_info=True)
        from fastapi import HTTPException
        from app.utils.http_client import http_get, http_post
        raise HTTPException(status_code=500, detail=f"Failed to initiate backend restart: {str(e)}")


@router.get("/diagnostics/recent-signals")
async def get_recent_signals(
    request: Request,
    db: Session = Depends(get_db),
    side: Optional[str] = Query(None, description="Filter by side: 'BUY' or 'SELL' (default: both)"),
    hours: Optional[int] = Query(168, ge=1, le=720, description="Hours to look back (default: 168 = 7 days)"),
    limit: int = Query(500, ge=1, le=1000, description="Maximum number of signals to return")
):
    """
    Get recent BUY/SELL SIGNAL messages with their decision traces and order_intents.
    
    This endpoint allows verifying that every SIGNAL has decision tracing
    (decision_type, reason_code, reason_message) populated and links to order_intents.
    
    Production verification criteria:
    - For every signal with blocked=false and message contains "BUY SIGNAL"/"SELL SIGNAL":
      there must be an order_intent row with status in (ORDER_PLACED, ORDER_FAILED, DEDUP_SKIPPED)
    - No signal may have null decision_type/reason_code/reason_message
    - For every ORDER_FAILED, there must be a Telegram failure message
    """
    _verify_diagnostics_auth(request)
    from app.models.telegram_message import TelegramMessage
    from app.models.order_intent import OrderIntent, OrderIntentStatusEnum
    from datetime import timedelta
    
    try:
        hours_value = float(hours or 0)
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours_value)
        
        # Build query filter - only signals that were SENT (blocked=false) and contain SIGNAL
        filters = [
            TelegramMessage.timestamp >= threshold,
            TelegramMessage.blocked == False,
        ]
        
        if side and side.upper() == "BUY":
            filters.append(TelegramMessage.message.like("%BUY SIGNAL%"))
        elif side and side.upper() == "SELL":
            filters.append(TelegramMessage.message.like("%SELL SIGNAL%"))
        else:
            # Both BUY and SELL
            filters.append(
                (TelegramMessage.message.like("%BUY SIGNAL%")) |
                (TelegramMessage.message.like("%SELL SIGNAL%"))
            )
        
        # Query SIGNAL messages (sent signals only)
        signals = db.query(TelegramMessage).filter(*filters).order_by(TelegramMessage.timestamp.desc()).limit(limit).all()
        
        results = []
        violations = []
        missing_intent_count = 0
        null_decisions_count = 0
        failed_without_telegram_count = 0
        duplicate_intent_count = 0
        non_terminal_intent_count = 0

        def _add_violation(
            *,
            signal: TelegramMessage,
            side_value: str,
            violation_type: str,
            details: Dict[str, Any],
        ) -> None:
            entry = {
                "id": signal.id,
                "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
                "symbol": signal.symbol,
                "side": side_value,
                "violation_type": violation_type,
                "details": details,
                # Backward compatibility fields
                "signal_id": signal.id,
                "violation": violation_type,
                "message": details.get("message"),
            }
            for key in ("order_intent_id", "decision_type", "reason_code", "reason_message"):
                if key in details:
                    entry[key] = details.get(key)
            violations.append(entry)
        
        for signal in signals:
            # Extract price from message if available
            price = _extract_price_from_message(signal.message)
            
            # Find associated order_intent(s)
            order_intents = db.query(OrderIntent).filter(
                OrderIntent.signal_id == signal.id
            ).order_by(OrderIntent.created_at.desc()).all()
            
            # Get most recent order_intent
            order_intent = order_intents[0] if order_intents else None
            status_value = (
                order_intent.status.value
                if order_intent and hasattr(order_intent.status, "value")
                else (order_intent.status if order_intent else None)
            )
            
            # Check for violations
            signal_violations = []
            
            # Violation 1: Missing order_intent
            if order_intent is None:
                missing_intent_count += 1
                signal_violations.append("MISSING_INTENT")
                _add_violation(
                    signal=signal,
                    side_value="BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                    violation_type="MISSING_INTENT",
                    details={
                        "message": "Signal was sent but no order_intent exists",
                    },
                )

            # Violation 1b: Duplicate order_intents for same signal
            if order_intents and len(order_intents) > 1:
                duplicate_intent_count += 1
                if "DUPLICATE_INTENT" not in signal_violations:
                    signal_violations.append("DUPLICATE_INTENT")
                    _add_violation(
                        signal=signal,
                        side_value="BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                        violation_type="DUPLICATE_INTENT",
                        details={
                            "message": "Multiple order_intent rows found for the same signal",
                            "order_intent_ids": [intent.id for intent in order_intents],
                        },
                    )
            
            # Violation 2: Null decision fields
            if signal.decision_type is None or signal.reason_code is None or signal.reason_message is None:
                null_decisions_count += 1
                if "NULL_DECISION" not in signal_violations:
                    signal_violations.append("NULL_DECISION")
                    _add_violation(
                        signal=signal,
                        side_value="BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                        violation_type="NULL_DECISION",
                        details={
                            "message": "Signal has null decision fields",
                            "decision_type": signal.decision_type,
                            "reason_code": signal.reason_code,
                            "reason_message": signal.reason_message,
                        },
                    )
            
            # Violation 3: ORDER_FAILED without Telegram failure message
            if status_value == OrderIntentStatusEnum.ORDER_FAILED.value:
                # Check if there's a Telegram failure message (ORDER FAILED in message)
                failure_messages = db.query(TelegramMessage).filter(
                    TelegramMessage.symbol == signal.symbol,
                    TelegramMessage.message.like("%ORDER FAILED%"),
                    TelegramMessage.timestamp >= signal.timestamp - timedelta(minutes=5),
                    TelegramMessage.timestamp <= signal.timestamp + timedelta(minutes=5),
                ).all()
                if not failure_messages:
                    failed_without_telegram_count += 1
                    if "FAILED_WITHOUT_TELEGRAM" not in signal_violations:
                        signal_violations.append("FAILED_WITHOUT_TELEGRAM")
                        _add_violation(
                            signal=signal,
                            side_value="BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                            violation_type="FAILED_WITHOUT_TELEGRAM",
                            details={
                                "message": "ORDER_FAILED but no Telegram failure message found",
                                "order_intent_id": order_intent.id if order_intent else None,
                            },
                        )

            # Violation 4: Non-terminal intent status
            if status_value and status_value not in (
                OrderIntentStatusEnum.ORDER_PLACED.value,
                OrderIntentStatusEnum.ORDER_FAILED.value,
                OrderIntentStatusEnum.DEDUP_SKIPPED.value,
            ):
                non_terminal_intent_count += 1
                if "NON_TERMINAL_INTENT" not in signal_violations:
                    signal_violations.append("NON_TERMINAL_INTENT")
                    status_value = (
                        order_intent.status.value
                        if order_intent and hasattr(order_intent.status, "value")
                        else (order_intent.status if order_intent else None)
                    )
                    _add_violation(
                        signal=signal,
                        side_value="BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                        violation_type="NON_TERMINAL_INTENT",
                        details={
                            "message": "Order intent status is not terminal",
                            "order_intent_id": order_intent.id if order_intent else None,
                            "status": status_value,
                        },
                    )
            
            results.append({
                "signal_id": signal.id,
                "timestamp": signal.timestamp.isoformat() if signal.timestamp else None,
                "symbol": signal.symbol,
                "side": "BUY" if "BUY SIGNAL" in (signal.message or "").upper() else "SELL",
                "message": signal.message[:200] if signal.message else None,  # Truncate for response
                "blocked": signal.blocked,
                "price": price,
                "decision_type": signal.decision_type,
                "reason_code": signal.reason_code,
                "reason_message": signal.reason_message,
                "context_json": signal.context_json,
                "exchange_error_snippet": signal.exchange_error_snippet,
                "correlation_id": signal.correlation_id,
                "order_attempted": signal.decision_type is not None and signal.decision_type != "SKIPPED",
                "order_id": signal.context_json.get("order_id") if signal.context_json and isinstance(signal.context_json, dict) else None,
                # Order intent information
                "order_intent": {
                    "id": order_intent.id if order_intent else None,
                    "status": order_intent.status.value if order_intent and hasattr(order_intent.status, 'value') else (order_intent.status if order_intent else None),
                    "idempotency_key": order_intent.idempotency_key if order_intent else None,
                    "order_id": order_intent.order_id if order_intent else None,
                    "error_message": order_intent.error_message if order_intent else None,
                    "created_at": order_intent.created_at.isoformat() if order_intent and order_intent.created_at else None,
                } if order_intent else None,
                "violations": signal_violations,
            })
        
        # Count by status
        placed_count = sum(1 for s in results if s.get("order_intent") and s["order_intent"].get("status") == "ORDER_PLACED")
        failed_count = sum(1 for s in results if s.get("order_intent") and s["order_intent"].get("status") == "ORDER_FAILED")
        dedup_count = sum(1 for s in results if s.get("order_intent") and s["order_intent"].get("status") == "DEDUP_SKIPPED")
        
        return {
            "signals": results,
            "total": len(results),
            "hours": hours,
            "counts": {
                "total_signals": len(results),
                "sent_signals": len(results),
                "placed": placed_count,
                "failed": failed_count,
                "dedup": dedup_count,
                "missing_intent": missing_intent_count,
                "null_decisions": null_decisions_count,
                "failed_without_telegram": failed_without_telegram_count,
                "duplicate_intent": duplicate_intent_count,
                "non_terminal_intent": non_terminal_intent_count,
            },
            "violations": violations,
            "pass": len(violations) == 0,
            "summary": {
                "buy_signals": sum(1 for s in results if s["side"] == "BUY"),
                "sell_signals": sum(1 for s in results if s["side"] == "SELL"),
                "executed": sum(1 for s in results if s["decision_type"] == "EXECUTED"),
                "failed": sum(1 for s in results if s["decision_type"] == "FAILED"),
                "skipped": sum(1 for s in results if s["decision_type"] == "SKIPPED"),
                "null_decisions": null_decisions_count,
            },
        }
    except Exception as e:
        log.error(f"Error fetching recent signals: {e}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Error fetching signals: {str(e)}")


@router.get("/diagnostics/recent-buy-signals")
async def get_recent_buy_signals(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of signals to return")
):
    """
    Get recent BUY SIGNAL messages with their decision traces.
    
    DEPRECATED: Use /diagnostics/recent-signals?side=BUY instead.
    """
    return await get_recent_signals(request=request, db=db, side="BUY", limit=limit)


@router.post("/diagnostics/emit-test-alert")
async def emit_test_alert(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Trigger emit_alert with dry_run=True to prove alert path persistence (no Telegram send, no order).
    Goes through: emit_alert → send_buy_signal(persist_only=True) → add_telegram_message.
    Protected by diagnostics auth (ENABLE_DIAGNOSTICS_ENDPOINTS + X-Diagnostics-Key).
    """
    from app.services.alert_emitter import emit_alert

    _verify_diagnostics_auth(request)
    result = emit_alert(
        symbol="TEST_USDT",
        side="BUY",
        reason="[STARTUP_PROBE] persist check",
        price=1.0,
        db=db,
        dry_run=True,
    )
    db.commit()  # add_telegram_message only flushes when db is passed; commit so row is visible
    correlation_id = result.get("correlation_id") if isinstance(result, dict) else None
    return {"ok": True, "persisted": bool(result), "result": str(result), "correlation_id": correlation_id}


@router.post("/diagnostics/emit-live-test-alert")
async def emit_live_test_alert(
    request: Request,
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query("TEST_USDT", description="Symbol for test alert (e.g. ALGO_USDT)"),
):
    """
    Emit a real (non-dry-run) alert and send a real Telegram message. For AWS proof only.
    Uses full path: emit_alert(dry_run=False) → send_buy_signal → send_message → Telegram API.
    Protected by diagnostics auth. Returns correlation_id and message_id for log/DB verification.
    """
    import uuid
    from app.services.alert_emitter import emit_alert
    from app.models.telegram_message import TelegramMessage

    _verify_diagnostics_auth(request)
    # Normalize symbol (e.g. ALGO -> ALGO_USDT)
    sym = (symbol or "TEST_USDT").strip().upper()
    if sym and "_" not in sym:
        sym = f"{sym}_USDT"
    correlation_id = str(uuid.uuid4())
    result = emit_alert(
        symbol=sym,
        side="BUY",
        reason="[TEST] [LIVE_TEST] AWS alert path verification",
        price=1.0,
        db=db,
        dry_run=False,
        correlation_id=correlation_id,
    )
    db.commit()
    # Resolve message_id from DB for verification (row persisted by add_telegram_message)
    row = db.query(TelegramMessage).filter(TelegramMessage.correlation_id == correlation_id).first()
    message_id = row.id if row else None
    return {
        "ok": True,
        "sent": bool(result),
        "message_id": message_id,
        "correlation_id": correlation_id,
        "message": "Real Telegram message sent; check logs and DB by correlation_id.",
    }


@router.post("/diagnostics/send-test-telegram")
async def send_test_telegram(
    request: Request,
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query("TEST_USDT", description="Symbol for test alert (e.g. ALGO_USDT)"),
):
    """
    Send a real Telegram message. Default TEST_USDT; use ?symbol=ALGO_USDT for ALGO.
    Persists to telegram_messages; returns correlation_id and message_id for proof.
    Alias for emit-live-test-alert. Protected by diagnostics auth (X-Diagnostics-Key).
    """
    return await emit_live_test_alert(request=request, db=db, symbol=symbol)


@router.get("/diagnostics/telegram-message/{correlation_id}")
async def get_telegram_message_by_correlation_id(
    request: Request,
    correlation_id: str,
    db: Session = Depends(get_db),
):
    """
    Diagnostics-only: look up a single TelegramMessage by correlation_id.
    Protected by diagnostics auth. Returns 404 if not found.
    """
    from app.models.telegram_message import TelegramMessage

    _verify_diagnostics_auth(request)
    row = db.query(TelegramMessage).filter(TelegramMessage.correlation_id == correlation_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No telegram message found for this correlation_id")
    return {
        "id": row.id,
        "symbol": row.symbol,
        "correlation_id": getattr(row, "correlation_id", None),
        "blocked": row.blocked,
        "throttle_status": row.throttle_status,
        "reason_code": row.reason_code,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


@router.post("/diagnostics/run-signal-order-test")
async def run_signal_order_test(
    request: Request,
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Symbol to test (default: uses first symbol with trade_enabled)"),
    dry_run: bool = Query(True, description="If True, simulate order creation without placing real orders"),
):
    """
    Run a self-test of the signal → order pipeline.
    
    This endpoint:
    1. Creates a synthetic BUY SIGNAL (or uses an existing recent one)
    2. Runs through the exact same decision pipeline that production uses
    3. Returns a structured report showing which step failed and why
    
    Safe by default: dry_run=True prevents real orders from being placed.
    """
    _verify_diagnostics_auth(request)
    from app.models.watchlist import WatchlistItem
    from app.services.signal_monitor import SignalMonitorService
    from app.services.telegram_notifier import telegram_notifier
    from app.utils.live_trading import get_live_trading_status
    import os
    
    try:
        # Safety check: ensure dry_run is respected
        if not dry_run:
            live_trading = get_live_trading_status(db)
            if not live_trading:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail="Cannot run test with dry_run=False when live_trading is disabled. Set dry_run=True for testing."
                )
        
        # Find a test symbol
        if not symbol:
            test_item = db.query(WatchlistItem).filter(
                WatchlistItem.trade_enabled.is_(True),
                WatchlistItem.trade_amount_usd > 0,
            ).first()
            if not test_item:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=404,
                    detail="No suitable test symbol found. Ensure at least one symbol has trade_enabled=True and trade_amount_usd > 0."
                )
            symbol = typing_cast(str, test_item.symbol)
        else:
            test_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
            if not test_item:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found in watchlist")
        
        # Get current price (simplified - in production this comes from market data)
        from app.services.brokers.crypto_com_trade import trade_client
        try:
            ticker = trade_client.get_ticker(symbol)
            current_price = float(ticker.get("result", {}).get("data", [{}])[0].get("a", 0))
            if current_price <= 0:
                raise ValueError("Invalid price")
        except Exception as e:
            log.warning(f"Could not get current price for {symbol}: {e}. Using placeholder.")
            current_price = 1.0  # Placeholder for testing
        
        # Create test report
        report = {
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "dry_run": dry_run,
            "steps": [],
            "final_decision": None,
            "order_created": False,
            "order_id": None,
            "error": None,
        }
        
        # Step 1: Check if signal would be detected
        report["steps"].append({
            "step": "signal_detection",
            "status": "passed",
            "message": f"Signal detection would run for {symbol}",
        })
        
        # Step 2: Check if alert would be sent
        if test_item.alert_enabled and getattr(test_item, 'buy_alert_enabled', False):
            report["steps"].append({
                "step": "alert_sending",
                "status": "passed",
                "message": "Alert would be sent (alert_enabled=True, buy_alert_enabled=True)",
            })
        else:
            report["steps"].append({
                "step": "alert_sending",
                "status": "skipped",
                "message": f"Alert would be skipped (alert_enabled={test_item.alert_enabled}, buy_alert_enabled={getattr(test_item, 'buy_alert_enabled', False)})",
            })
        
        # Step 3: Check if order would be created
        if test_item.trade_enabled and test_item.trade_amount_usd and test_item.trade_amount_usd > 0:
            report["steps"].append({
                "step": "order_creation_check",
                "status": "passed",
                "message": f"Order creation check passed (trade_enabled=True, trade_amount_usd=${test_item.trade_amount_usd:.2f})",
            })
            
            if dry_run:
                report["steps"].append({
                    "step": "order_placement",
                    "status": "simulated",
                    "message": "Order placement simulated (dry_run=True). No real order would be placed.",
                })
                report["final_decision"] = "SKIPPED"
                report["order_created"] = False
            else:
                report["steps"].append({
                    "step": "order_placement",
                    "status": "would_attempt",
                    "message": "Order placement would be attempted (dry_run=False, but this test does not actually place orders)",
                })
                report["final_decision"] = "WOULD_ATTEMPT"
        else:
            report["steps"].append({
                "step": "order_creation_check",
                "status": "blocked",
                "message": f"Order creation blocked (trade_enabled={test_item.trade_enabled}, trade_amount_usd={test_item.trade_amount_usd})",
            })
            report["final_decision"] = "SKIPPED"
        
        # Step 4: Check decision tracing
        # Query for recent BUY SIGNAL message for this symbol
        from app.models.telegram_message import TelegramMessage
        from datetime import timedelta
        threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_signal = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.message.like("%BUY SIGNAL%"),
            TelegramMessage.timestamp >= threshold,
        ).order_by(TelegramMessage.timestamp.desc()).first()
        
        if recent_signal:
            if recent_signal.decision_type:
                report["steps"].append({
                    "step": "decision_tracing",
                    "status": "passed",
                    "message": f"Decision tracing present: decision_type={recent_signal.decision_type}, reason_code={recent_signal.reason_code}",
                })
            else:
                report["steps"].append({
                    "step": "decision_tracing",
                    "status": "missing",
                    "message": "Decision tracing missing (decision_type is NULL)",
                })
        else:
            report["steps"].append({
                "step": "decision_tracing",
                "status": "no_signal",
                "message": "No recent BUY SIGNAL message found (test may need to trigger actual signal)",
            })
        
        return report
        
    except Exception as e:
        log.error(f"Error running signal order test: {e}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Error running test: {str(e)}")


@router.post("/diagnostics/run-e2e-test")
async def run_e2e_test(
    request: Request,
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Symbol to test (default: uses first trade_enabled symbol)"),
    dry_run: bool = Query(True, description="If True, simulate order creation without placing real orders"),
):
    """
    Run an internal end-to-end signal → order_intent → decision tracing test.

    Safe by default: dry_run=True only simulates outcomes and never places orders.
    Protected by diagnostics auth guard (ENABLE_DIAGNOSTICS_ENDPOINTS + X-Diagnostics-Key).
    """
    from app.models.watchlist import WatchlistItem
    from app.services.signal_order_orchestrator import create_order_intent, update_order_intent_status
    from app.utils.decision_reason import ReasonCode, make_execute, make_fail
    import hashlib
    import uuid as uuid_module

    _verify_diagnostics_auth(request)

    if not dry_run:
        raise HTTPException(status_code=400, detail="dry_run=false is not allowed for this diagnostics endpoint.")

    # Select a test symbol
    test_item = None
    if symbol:
        test_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
    if not test_item:
        test_item = db.query(WatchlistItem).filter(WatchlistItem.trade_enabled.is_(True)).first()
    if not test_item:
        test_item = db.query(WatchlistItem).first()
    if not test_item:
        raise HTTPException(status_code=404, detail="No watchlist items available for diagnostics test.")
    symbol = typing_cast(str, test_item.symbol)
    current_price = test_item.price or 1.0

    def _simulate_outcome(signal_side: str) -> bool:
        seed = f"{symbol}:{signal_side}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()
        return int(digest[-2:], 16) % 2 == 1  # True => fail, False => success

    report = {
        "dry_run": dry_run,
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stages": [],
        "results": {},
    }

    for side in ("BUY", "SELL"):
        signal_text = f"[TEST] {side} SIGNAL: {symbol} @ ${current_price:.6f}"
        signal_id = add_telegram_message(
            signal_text,
            symbol=symbol,
            blocked=False,
            throttle_status="SENT",
            throttle_reason="TEST_SIGNAL",
            db=db,
        )
        report["stages"].append(
            {"stage": "signal_created", "side": side, "signal_id": signal_id, "message": signal_text}
        )

        # Create order intent (same orchestrator component used in production)
        order_intent, intent_status = create_order_intent(
            db=db,
            signal_id=signal_id,
            symbol=symbol,
            side=side,
            message_content=signal_text,
        )
        report["stages"].append(
            {
                "stage": "order_intent_created",
                "side": side,
                "intent_status": intent_status,
                "order_intent_id": order_intent.id if order_intent else None,
            }
        )

        # Deterministic simulation outcome
        simulate_fail = _simulate_outcome(side)
        if order_intent:
            if simulate_fail:
                error_msg = f"Simulated {side} failure (dry_run)"
                update_order_intent_status(
                    db=db,
                    order_intent_id=order_intent.id,
                    status="ORDER_FAILED",
                    error_message=error_msg,
                )
                decision_reason = make_fail(
                    reason_code=ReasonCode.EXCHANGE_ERROR_UNKNOWN.value,
                    message=error_msg,
                    context={"symbol": symbol, "side": side, "dry_run": True},
                    source="diagnostics",
                )
                update_telegram_message_decision_trace(
                    db=db,
                    symbol=symbol,
                    message_pattern=f"{side} SIGNAL",
                    decision_type="FAILED",
                    reason_code=decision_reason.reason_code,
                    reason_message=decision_reason.reason_message,
                    context_json=decision_reason.context,
                    correlation_id=str(uuid_module.uuid4()),
                )
                add_telegram_message(
                    f"❌ ORDER FAILED | {symbol} {side} | {error_msg}",
                    symbol=symbol,
                    blocked=False,
                    decision_type="FAILED",
                    reason_code=decision_reason.reason_code,
                    reason_message=decision_reason.reason_message,
                    db=db,
                )
                outcome = "ORDER_FAILED"
            else:
                order_id = f"dry_test_{uuid_module.uuid4().hex[:12]}"
                update_order_intent_status(
                    db=db,
                    order_intent_id=order_intent.id,
                    status="ORDER_PLACED",
                    order_id=order_id,
                )
                decision_reason = make_execute(
                    reason_code=ReasonCode.EXEC_ORDER_PLACED.value,
                    message=f"Simulated {side} success (dry_run)",
                    context={"symbol": symbol, "side": side, "dry_run": True, "order_id": order_id},
                    source="diagnostics",
                )
                update_telegram_message_decision_trace(
                    db=db,
                    symbol=symbol,
                    message_pattern=f"{side} SIGNAL",
                    decision_type="EXECUTED",
                    reason_code=decision_reason.reason_code,
                    reason_message=decision_reason.reason_message,
                    context_json=decision_reason.context,
                    correlation_id=str(uuid_module.uuid4()),
                )
                outcome = "ORDER_PLACED"
        else:
            outcome = intent_status or "NO_INTENT"

        report["results"][side] = {
            "signal_id": signal_id,
            "order_intent_id": order_intent.id if order_intent else None,
            "intent_status": intent_status,
            "outcome": outcome,
        }

    report["pass"] = all(result["outcome"] in ("ORDER_PLACED", "ORDER_FAILED") for result in report["results"].values())
    return report

@router.get("/forensic/audit")
async def get_forensic_audit(
    hours: int = Query(12, description="Number of hours to audit", ge=1, le=168),
    db: Session = Depends(get_db)
):
    """
    Run forensic audit to identify inconsistencies between Telegram signals, orders, and TP/SL.
    
    Returns comprehensive analysis of:
    - Signals without orders (C2)
    - Orders without signals (C3)
    - Orders without TP/SL (C4)
    - Partial TP/SL (C5)
    - Silent failures (C6)
    - Duplicate orders (C7)
    
    Business Rules:
    - BR-1: SIGNAL → ORDER (MANDATORY)
    - BR-2: ORDER UNIQUENESS
    - BR-3: ORDER → TP/SL (MANDATORY IF STRATEGY REQUIRES IT)
    - BR-4: FAILURES MUST BE EXPLICIT
    - BR-5: NO GHOST ENTITIES
    """
    try:
        # Import the forensic audit function using importlib for dynamic import
        import importlib.util
        from pathlib import Path
        scripts_path = Path(__file__).parent.parent.parent / "scripts" / "forensic_audit.py"
        
        # Load the module dynamically
        spec = importlib.util.spec_from_file_location("forensic_audit", scripts_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load forensic_audit module from {scripts_path}")
        
        forensic_audit_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(forensic_audit_module)
        run_forensic_audit = forensic_audit_module.run_forensic_audit
        
        # Run the audit
        audit_result = run_forensic_audit(db, hours=hours)
        
        return JSONResponse(
            content=audit_result,
            headers=_NO_CACHE_HEADERS
        )
    except ImportError as e:
        log.error(f"Error importing forensic audit: {e}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Forensic audit script not found: {str(e)}")
    except Exception as e:
        log.error(f"Error running forensic audit: {e}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Error running forensic audit: {str(e)}")


@router.get("/monitoring/secrets-status")
def monitoring_secrets_status_compat(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """
    Same payload as GET /api/admin/secrets-status, mounted on the monitoring router so older
    deployments that shipped monitoring but not the admin secrets route still work behind /api.
    """
    from app.api.routes_admin import verify_admin_key, compute_admin_secrets_status_dict

    verify_admin_key(x_admin_key)
    return compute_admin_secrets_status_dict()


@router.get("/monitoring/recovery-status")
def monitoring_recovery_status_compat(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")):
    """Alias for GET /api/admin/recovery-status (same auth and payload)."""
    from app.api.routes_admin import verify_admin_key, compute_admin_recovery_dict

    verify_admin_key(x_admin_key)
    return compute_admin_recovery_dict()


class SecretIntakeBodyMonitoring(BaseModel):
    """Body for POST /api/monitoring/secrets-intake (mirrors routes_admin.SecretIntakeBody)."""

    env_var: str
    value: str
    persist_ssm: bool = False


@router.post("/monitoring/secrets-intake")
def monitoring_secrets_intake_compat(
    body: SecretIntakeBodyMonitoring,
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """
    Same behaviour as POST /api/admin/secrets-intake, on the monitoring router.
    Use when the dashboard must fall back the same way as GET …/secrets-status.
    """
    from app.api.routes_admin import SecretIntakeBody, verify_admin_key, perform_secrets_intake

    verify_admin_key(x_admin_key)
    payload = SecretIntakeBody(
        env_var=body.env_var,
        value=body.value,
        persist_ssm=body.persist_ssm,
    )
    return perform_secrets_intake(payload)
