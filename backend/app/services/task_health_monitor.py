"""
Task health monitor: detect and recover tasks stuck in In Progress, Patching, or Testing.

Runs at the start of each scheduler cycle. Applies stuck thresholds, attempts
automatic recovery (comment + status move or re-trigger Cursor bridge), sends
at most one Telegram alert per stuck incident with cooldown, and after max
retries moves to needs-revision and sends a single "Task requires manual attention" alert.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stuck rules (minutes since last_edited_time)
# ---------------------------------------------------------------------------

STUCK_THRESHOLD_MINUTES = {
    "in-progress": 15,
    "investigating": 15,
    "patching": 10,
    "testing": 10,
}

# Statuses we consider for stuck detection
STUCK_CHECK_STATUSES = list(STUCK_THRESHOLD_MINUTES.keys())

# Alert cooldown: do not send another "stuck" alert for the same task within this many minutes
ALERT_COOLDOWN_MINUTES = 30

# Max recovery attempts per task; after this we move to needs-revision and send manual-attention alert
MAX_RETRIES = 3

# In-memory state (per process). Key: task_id, value: timestamp (alert) or retry count
_last_alert_sent: dict[str, float] = {}
_retry_count: dict[str, int] = {}


def _parse_notion_ts(ts: str) -> datetime | None:
    """Parse Notion ISO timestamp to datetime (UTC). Returns None if missing or invalid."""
    s = (ts or "").strip()
    if not s:
        return None
    try:
        # Notion format: 2025-03-18T12:00:00.000Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def is_task_stuck(task: dict[str, Any], now: datetime | None = None) -> bool:
    """
    True if the task is in a monitored status and has exceeded the threshold
    since last_edited_time (or created_time as fallback).

    Rules:
        In Progress / Investigating > 15 minutes → stuck
        Patching > 10 minutes → stuck
        Testing > 10 minutes → stuck
    """
    if not task:
        return False
    now = now or datetime.now(timezone.utc)
    status = (task.get("status") or "").strip().lower()
    if status not in STUCK_THRESHOLD_MINUTES:
        return False
    threshold_minutes = STUCK_THRESHOLD_MINUTES[status]
    ts = _parse_notion_ts(task.get("last_edited_time") or "")
    if ts is None:
        ts = _parse_notion_ts(task.get("created_time") or "")
    if ts is None:
        return False
    # Notion timestamps are UTC; ensure we compare in UTC
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = (now - ts).total_seconds() / 60.0
    return delta >= threshold_minutes


def _minutes_stuck(task: dict[str, Any], now: datetime | None = None) -> float:
    """Minutes since last_edited_time (or created_time). Returns 0 if no valid timestamp."""
    now = now or datetime.now(timezone.utc)
    ts = _parse_notion_ts(task.get("last_edited_time") or "")
    if ts is None:
        ts = _parse_notion_ts(task.get("created_time") or "")
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 60.0


def _send_stuck_alert(task: dict[str, Any], minutes_stuck: float) -> None:
    """Send a single Telegram alert for stuck task (ops channel). Suppressed in quiet mode (INFO/IMPORTANT)."""
    try:
        from app.services.agent_telegram_policy import should_send_agent_telegram, AGENT_MSG_IMPORTANT
        if not should_send_agent_telegram(AGENT_MSG_IMPORTANT):
            logger.info("task_health_monitor: stuck alert suppressed (quiet mode) task_id=%s", (task.get("id") or "")[:12])
            return
    except Exception:
        pass
    try:
        from app.services.telegram_notifier import telegram_notifier
    except Exception as e:
        logger.debug("task_health_monitor: telegram_notifier import failed %s", e)
        return
    task_id = (task.get("id") or "").strip()
    title = (task.get("task") or "(untitled)")[:80]
    status = (task.get("status") or "?")[:30]
    message = (
        "Task appears stuck.\n\n"
        f"Title: {title}\n"
        f"Status: {status}\n"
        f"Time stuck: {minutes_stuck:.0f} min\n\n"
        "Attempting automatic recovery."
    )
    if getattr(telegram_notifier, "send_message", None):
        telegram_notifier.send_message(message, chat_destination="ops")


def _send_manual_attention_alert(task: dict[str, Any]) -> None:
    """Send a single Telegram alert that task requires attention (CRITICAL: after max retries)."""
    try:
        from app.services.agent_telegram_policy import should_send_agent_telegram, AGENT_MSG_CRITICAL
        if not should_send_agent_telegram(AGENT_MSG_CRITICAL):
            return
    except Exception:
        pass
    try:
        from app.services.telegram_notifier import telegram_notifier
    except Exception as e:
        logger.debug("task_health_monitor: telegram_notifier import failed %s", e)
        return
    title = (task.get("task") or "(untitled)")[:80]
    status = (task.get("status") or "?")[:30]
    message = (
        "Task requires attention.\n\n"
        f"Title: {title}\n"
        f"Status: {status}\n\n"
        "Max automatic retries reached; moved to Needs Revision."
    )
    if getattr(telegram_notifier, "send_message", None):
        telegram_notifier.send_message(message, chat_destination="ops")


def _log_event(event_type: str, task_id: str = "", task_title: str = "", details: dict | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, task_id=task_id or None, task_title=task_title or None, details=details or {})
    except Exception as e:
        logger.debug("task_health_monitor: log_agent_event failed %s", e)


def handle_stuck_task(task: dict[str, Any], now: datetime | None = None) -> None:
    """
    Handle a single stuck task: recovery action by status, or after max retries
    move to needs-revision and send manual-attention alert. Sends at most one
    stuck alert per incident (cooldown 30 min). Never raises.
    """
    if not task:
        return
    now = now or datetime.now(timezone.utc)
    task_id = (task.get("id") or "").strip()
    task_title = (task.get("task") or "(untitled)")[:200]
    status = (task.get("status") or "").strip().lower()

    retries = _retry_count.get(task_id, 0)
    if retries >= MAX_RETRIES:
        # Move to needs-revision and send manual attention (once per incident)
        try:
            from app.services.notion_tasks import update_notion_task_status, TASK_STATUS_NEEDS_REVISION
            update_notion_task_status(
                task_id,
                TASK_STATUS_NEEDS_REVISION,
                append_comment="Task stuck: max automatic retries reached. Moved to Needs Revision for manual attention.",
            )
        except Exception as e:
            logger.warning("task_health_monitor: move to needs-revision failed task_id=%s %s", task_id[:12], e)
        _send_manual_attention_alert(task)
        _log_event("stuck_task_retry_failed", task_id=task_id, task_title=task_title, details={"retries": retries})
        # Reset retry count so we don't keep updating the same task
        _retry_count.pop(task_id, None)
        _last_alert_sent.pop(task_id, None)
        return

    # Cooldown: send at most one "stuck" alert per task per ALERT_COOLDOWN_MINUTES
    last_alert = _last_alert_sent.get(task_id)
    send_alert = last_alert is None or (now.timestamp() - last_alert) >= (ALERT_COOLDOWN_MINUTES * 60)
    minutes_stuck = _minutes_stuck(task, now)

    _log_event("stuck_task_detected", task_id=task_id, task_title=task_title, details={"status": status, "minutes_stuck": round(minutes_stuck, 1)})

    if status in ("in-progress", "investigating"):
        # Case 1: Investigation stuck — add comment and move to needs-revision
        try:
            from app.services.notion_tasks import update_notion_task_status, TASK_STATUS_NEEDS_REVISION
            update_notion_task_status(
                task_id,
                TASK_STATUS_NEEDS_REVISION,
                append_comment="Task stuck during investigation. Moved to Needs Revision.",
            )
        except Exception as e:
            logger.warning("task_health_monitor: investigation recovery failed task_id=%s %s", task_id[:12], e)
        if send_alert:
            _send_stuck_alert(task, minutes_stuck)
            _last_alert_sent[task_id] = now.timestamp()
        _retry_count[task_id] = retries + 1
        _log_event("stuck_task_recovered", task_id=task_id, task_title=task_title, details={"action": "move_to_needs_revision"})

    elif status == "patching":
        # Case 2: Patching stuck — re-trigger Cursor execution bridge
        try:
            from app.services.cursor_execution_bridge import run_bridge_phase2
            result = run_bridge_phase2(task_id, prompt=None, ingest=True, create_pr=False, current_status="patching")
            if result.get("ok"):
                _log_event("stuck_task_recovered", task_id=task_id, task_title=task_title, details={"action": "cursor_bridge_retriggered"})
            else:
                _log_event("stuck_task_retry_failed", task_id=task_id, task_title=task_title, details={"action": "cursor_bridge", "error": str(result.get("error", ""))[:200]})
        except Exception as e:
            logger.warning("task_health_monitor: cursor bridge re-trigger failed task_id=%s %s", task_id[:12], e)
            _log_event("stuck_task_retry_failed", task_id=task_id, task_title=task_title, details={"action": "cursor_bridge", "error": str(e)[:200]})
        try:
            from app.services.notion_tasks import update_notion_task_status
            update_notion_task_status(
                task_id,
                "patching",
                append_comment="Stuck recovery: Cursor bridge re-triggered.",
            )
        except Exception:
            pass
        if send_alert:
            _send_stuck_alert(task, minutes_stuck)
            _last_alert_sent[task_id] = now.timestamp()
        _retry_count[task_id] = retries + 1

    elif status == "testing":
        # Case 3: Testing stuck — add comment; no direct "re-run validation" API, so just comment and retry count
        try:
            from app.services.notion_tasks import update_notion_task_status
            update_notion_task_status(
                task_id,
                "testing",
                append_comment="Task stuck during testing. Consider re-running validation or moving to Needs Revision.",
            )
        except Exception as e:
            logger.warning("task_health_monitor: testing comment failed task_id=%s %s", task_id[:12], e)
        if send_alert:
            _send_stuck_alert(task, minutes_stuck)
            _last_alert_sent[task_id] = now.timestamp()
        _retry_count[task_id] = retries + 1
        _log_event("stuck_task_recovered", task_id=task_id, task_title=task_title, details={"action": "comment_only_testing"})


def check_for_stuck_tasks() -> int:
    """
    Fetch tasks in in-progress, investigating, patching, testing; filter by is_task_stuck;
    call handle_stuck_task for each. Returns number of stuck tasks handled. Never raises.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
    except Exception as e:
        logger.warning("task_health_monitor: get_tasks_by_status import failed %s", e)
        return 0
    tasks = get_tasks_by_status(STUCK_CHECK_STATUSES, max_results=50)
    now = datetime.now(timezone.utc)
    stuck = [t for t in tasks if is_task_stuck(t, now)]
    for task in stuck:
        try:
            handle_stuck_task(task, now)
        except Exception as e:
            logger.warning("task_health_monitor: handle_stuck_task failed task_id=%s %s", (task.get("id") or "")[:12], e)
    return len(stuck)
