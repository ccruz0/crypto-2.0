"""Monitoring endpoint - returns system KPIs and alerts"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.signal_throttle import SignalThrottleState
import logging
import time
import asyncio
import os
import re
import requests
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta

router = APIRouter()
log = logging.getLogger("app.monitoring")

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
    # Keep it signal-focused: the throttle panel is about signal alerts.
    if "BUY SIGNAL" in upper or "🟢" in message_text:
        return "BUY"
    if "SELL SIGNAL" in upper or "🟥" in message_text or "🔴" in message_text:
        return "SELL"
    return "UNKNOWN"


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
    """Get Telegram messages from the last month (BLOCKED messages only)
    
    IMPORTANT: This endpoint only returns blocked messages (blocked=True).
    Sent messages are shown in the Signal Throttle panel instead.
    
    Now reads from database for multi-worker compatibility and persistence.
    """
    from datetime import timedelta
    from app.models.telegram_message import TelegramMessage
    
    try:
        # Read from database if available
        if db is not None:
            one_month_ago = datetime.now() - timedelta(days=30)
            
            # Query from database - ONLY blocked messages
            db_messages = db.query(TelegramMessage).filter(
                TelegramMessage.timestamp >= one_month_ago,
                TelegramMessage.blocked == True  # Only blocked messages
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
        # Only include blocked messages
        if (datetime.fromisoformat(msg["timestamp"]) >= one_month_ago and 
            msg.get("blocked") == True):
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
    """Expose recent signal throttle state for the Monitoring dashboard.
    
    IMPORTANT: Returns ALL alerts that were sent to Telegram (not blocked).
    Uses TelegramMessage table as the primary source to ensure we show ALL sent messages,
    then enriches with throttle state data when available.
    """
    log.debug("Fetching signal throttle state (limit=%s)", limit)
    if db is None:
        return []
    
    try:
        from app.models.telegram_message import TelegramMessage
        
        bounded_limit = max(1, min(limit, 500))
        now = datetime.now(timezone.utc)
        
        # PRIMARY STRATEGY: Query sent Telegram messages (blocked=False).
        # Then filter to *signal* messages only. The throttle panel is for BUY/SELL signal alerts,
        # not generic Telegram notifications (orders/workflows/etc) which cause UNKNOWN side / empty fields.
        sent_messages = (
            db.query(TelegramMessage)
            .filter(TelegramMessage.blocked == False)  # Only messages that were sent
            .order_by(TelegramMessage.timestamp.desc())
            .limit(bounded_limit * 15)  # Get more to account for filtering + dedup
            .all()
        )

        # 1) Parse & filter to signal messages, then deduplicate within minute buckets.
        # We keep the "best" message per (symbol, side, minute) to avoid duplicates caused by
        # multiple storage call paths (full Telegram body + summary row).
        best_by_bucket: Dict[tuple, Dict[str, Any]] = {}

        for msg in sent_messages:
            raw_text = msg.message or ""
            parsed_text = _strip_html(raw_text)
            upper = parsed_text.upper()

            symbol_value = (msg.symbol or "").strip().upper()
            if not symbol_value:
                sm = _SYMBOL_RE.search(upper)
                if sm:
                    symbol_value = sm.group(1).upper()
            if not symbol_value or _SYMBOL_RE.fullmatch(symbol_value) is None:
                continue

            side = _infer_side_from_message(parsed_text)

            # Only keep actual signal alerts.
            if side not in {"BUY", "SELL"}:
                continue
            if "SIGNAL" not in upper:
                continue

            msg_time = msg.timestamp
            if msg_time and msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)

            price = _extract_price_from_message(parsed_text)
            parsed_reason = _extract_reason_from_message(parsed_text)
            parsed_strategy_key = _extract_strategy_key_from_message(parsed_text)

            minute_bucket = int(msg_time.timestamp() // 60) if msg_time else int(msg.id or 0)
            bucket_key = (symbol_value, side, minute_bucket)

            # Score: prefer explicit throttle_reason, then parsed reason, then more detailed body.
            score = 0
            if getattr(msg, "throttle_reason", None):
                score += 10
            if parsed_reason:
                score += 5
            if "SIGNAL DETECTED" in upper:
                score += 3
            if parsed_strategy_key:
                score += 2
            if price:
                score += 1

            existing = best_by_bucket.get(bucket_key)
            if not existing or score > existing.get("_score", -1):
                best_by_bucket[bucket_key] = {
                    "_score": score,
                    "msg": msg,
                    "symbol": symbol_value,
                    "side": side,
                    "msg_time": msg_time,
                    "parsed_text": parsed_text,
                    "price": price,
                    "parsed_reason": parsed_reason,
                    "parsed_strategy_key": parsed_strategy_key,
                }

        events = list(best_by_bucket.values())
        # Sort newest first for output, but we'll compute price deltas in chronological order below.
        events.sort(key=lambda e: (e.get("msg_time") or datetime(1970, 1, 1, tzinfo=timezone.utc)), reverse=True)
        if not events:
            return []

        # 2) Load throttle state rows for symbols in view (enrichment source of truth).
        symbols = sorted({e["symbol"] for e in events if e.get("symbol")})
        states = (
            db.query(SignalThrottleState)
            .filter(SignalThrottleState.symbol.in_(symbols))
            .order_by(SignalThrottleState.last_time.desc())
            .limit(max(200, bounded_limit * 10))
            .all()
        )
        states_by_key: Dict[tuple, list] = {}
        for st in states:
            if not st.symbol or not st.side:
                continue
            k = (st.symbol.upper(), st.side.upper())
            states_by_key.setdefault(k, []).append(st)

        # 3) Compute message-based price change fallback (when previous_price is missing in throttle state).
        events_chrono = [e for e in events if e.get("msg_time")]
        events_chrono.sort(key=lambda e: e["msg_time"])
        prev_price_by_symbol_side: Dict[tuple, float] = {}
        prev_price_by_msg_id: Dict[int, float] = {}
        for e in events_chrono:
            msg_obj = e.get("msg")
            msg_id = int(getattr(msg_obj, "id", 0) or 0)
            key = (e["symbol"], e["side"])
            current_price = e.get("price")
            if current_price and current_price > 0:
                if key in prev_price_by_symbol_side:
                    prev_price_by_msg_id[msg_id] = prev_price_by_symbol_side[key]
                prev_price_by_symbol_side[key] = current_price

        # 4) Build final payload (reason, last_price, price_change_pct always best-effort).
        payload: list[Dict[str, Any]] = []
        for e in events[: bounded_limit * 3]:
            msg_obj = e.get("msg")
            msg_id = int(getattr(msg_obj, "id", 0) or 0)
            symbol_value = e["symbol"]
            side = e["side"]
            msg_time = e.get("msg_time")
            parsed_reason = e.get("parsed_reason")
            parsed_strategy_key = e.get("parsed_strategy_key")
            msg_throttle_reason = (getattr(msg_obj, "throttle_reason", None) or "").strip() or None

            # Choose the best matching throttle state for this event:
            # - Prefer a state close in time (<=30m) that doesn't look "blocked".
            candidate_states = states_by_key.get((symbol_value, side), []) or []
            chosen_state = None
            if msg_time and candidate_states:
                for st in candidate_states:
                    st_time = st.last_time
                    if st_time and st_time.tzinfo is None:
                        st_time = st_time.replace(tzinfo=timezone.utc)
                    if not st_time:
                        continue
                    diff = abs((msg_time - st_time).total_seconds())
                    looks_blocked = ("throttled" in (st.emit_reason or "").lower()) or ("blocked" in (st.emit_reason or "").lower())
                    if diff <= 1800 and not looks_blocked:
                        chosen_state = st
                        break
            if not chosen_state and candidate_states:
                chosen_state = candidate_states[0]

            strategy_key = (
                (chosen_state.strategy_key if chosen_state and chosen_state.strategy_key else None)
                or parsed_strategy_key
                or "unknown:unknown"
            )

            # last_price: prefer throttle-state price (source of truth), else parse from message.
            last_price = None
            if chosen_state and chosen_state.last_price and chosen_state.last_price > 0:
                last_price = float(chosen_state.last_price)
            elif e.get("price") and e["price"] > 0:
                last_price = float(e["price"])

            # Compute price change: prefer throttle-state previous_price, else use message-history previous price.
            price_change_pct = None
            previous_price = None
            if chosen_state and chosen_state.previous_price and chosen_state.previous_price > 0:
                previous_price = float(chosen_state.previous_price)
            elif msg_id in prev_price_by_msg_id:
                previous_price = float(prev_price_by_msg_id[msg_id])

            if last_price and previous_price and previous_price > 0:
                try:
                    price_change_pct = ((last_price - previous_price) / previous_price) * 100.0
                except Exception:
                    price_change_pct = None

            # Reason: never return placeholder "Sent to Telegram".
            emit_reason = (
                msg_throttle_reason
                or (chosen_state.emit_reason if chosen_state and chosen_state.emit_reason else None)
                or parsed_reason
                or "Signal sent"
            )

            event_time = msg_time
            if chosen_state and chosen_state.last_time:
                # Use throttle state's last_time when it matches closely; otherwise keep msg_time (actual send time).
                if msg_time is None:
                    event_time = chosen_state.last_time
                else:
                    st_time = chosen_state.last_time
                    if st_time and st_time.tzinfo is None:
                        st_time = st_time.replace(tzinfo=timezone.utc)
                    if st_time and abs((msg_time - st_time).total_seconds()) <= 1800:
                        event_time = st_time

            if event_time and event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            seconds_since = (
                max(0, int((now - event_time).total_seconds()))
                if event_time
                else None
            )

            payload.append(
                {
                    "symbol": symbol_value,
                    "strategy_key": strategy_key,
                    "side": side,
                    "last_price": last_price,
                    "last_time": event_time.isoformat() if event_time else None,
                    "seconds_since_last": seconds_since,
                    "price_change_pct": round(price_change_pct, 2) if price_change_pct is not None else None,
                    "emit_reason": emit_reason,
                }
            )

        payload.sort(key=lambda x: x["last_time"] or "", reverse=True)
        return payload[:bounded_limit]
        
    except Exception as exc:
        log.warning("Failed to load signal throttle state: %s", exc, exc_info=True)
        return []


# Workflow execution tracking (in-memory for now)
_workflow_executions: Dict[str, Dict[str, Any]] = {}
# Background task tracking to prevent garbage collection
_background_tasks: Dict[str, "asyncio.Task"] = {}
# Locks for atomic check-and-set operations per workflow_id
_workflow_locks: Dict[str, asyncio.Lock] = {}

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
        workflow = {
            "id": workflow_id,
            "name": registry_wf.get("name", workflow_id),
            "description": registry_wf.get("description", ""),
            "automated": registry_wf.get("automated", True),
            "schedule": registry_wf.get("schedule", ""),
            "run_endpoint": registry_wf.get("run_endpoint"),  # Include run_endpoint so frontend knows which can be run
            "last_execution": _workflow_executions.get(workflow_id, {}).get("last_execution"),
            "last_status": _workflow_executions.get(workflow_id, {}).get("status", "unknown"),
            "last_report": _workflow_executions.get(workflow_id, {}).get("report") if _is_valid_report_path(_workflow_executions.get(workflow_id, {}).get("report")) else None,
            "last_error": _workflow_executions.get(workflow_id, {}).get("error"),
        }
        workflows.append(workflow)
    
    return JSONResponse({"workflows": workflows}, headers=_NO_CACHE_HEADERS)

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
            
            async def run_sl_tp_check():
                try:
                    # Run in thread to avoid blocking
                    check_result = await asyncio.to_thread(sl_tp_checker_service.check_positions_for_sl_tp, db)
                    positions_missing = check_result.get('positions_missing_sl_tp', [])
                    
                    # Send reminder if there are positions missing SL/TP
                    if positions_missing:
                        await asyncio.to_thread(sl_tp_checker_service.send_sl_tp_reminder, db)
                    
                    record_workflow_execution(workflow_id, "success", None, error=None)
                    log.info(f"Workflow {workflow_id} completed successfully: {len(positions_missing)} positions missing SL/TP")
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
                    # Success should NOT set last_error (UI treats it as an error even if status=success)
                    record_workflow_execution(workflow_id, "success", None, error=None)
                    log.info("Workflow %s completed successfully (duplicates=%s)", workflow_id, result.get("duplicates", 0))
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
                    # Get GitHub token and repo info from environment
                    github_token = os.getenv("GITHUB_TOKEN")
                    github_repo = os.getenv("GITHUB_REPOSITORY", "ccruz0/crypto-2.0")
                    workflow_file = "dashboard-data-integrity.yml"
                    
                    if not github_token:
                        raise ValueError("GITHUB_TOKEN environment variable is not set")
                    
                    # Trigger workflow via GitHub API
                    url = f"https://api.github.com/repos/{github_repo}/actions/workflows/{workflow_file}/dispatches"
                    headers = {
                        "Authorization": f"token {github_token}",
                        "Accept": "application/vnd.github.v3+json"
                    }
                    payload = {
                        "ref": "main"  # Branch to trigger on
                    }
                    
                    # Run in thread to avoid blocking
                    response = await asyncio.to_thread(
                        requests.post, url, json=payload, headers=headers, timeout=10
                    )
                    
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
