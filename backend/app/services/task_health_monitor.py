"""
Task health monitor: detect and recover tasks stuck in In Progress, Patching, or Testing.

Runs at the start of each scheduler cycle. Applies stuck thresholds, attempts
automatic recovery (comment + status move or re-trigger Cursor bridge), sends
at most one Telegram alert per stuck incident with cooldown.

Investigation stuck: moves to ready-for-investigation (retryable) — never to Needs Revision.
Operational failures (timeout, no progress) are retried automatically. After max retries,
task is moved to Blocked with explicit blocker_reason — not Needs Revision.

Needs Revision is reserved for explicit user-action cases (e.g. solution verification failed).
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

# Max automatic re-investigate attempts before decompose or block
MAX_AUTO_REINVESTIGATE = 2
# Max recovery attempts (legacy name); after this we move to Blocked
MAX_RETRIES = 3

# In-memory state (per process). Key: task_id, value: timestamp (alert) or retry count
_last_alert_sent: dict[str, float] = {}
_retry_count: dict[str, int] = {}
# When user clicks Re-investigate but Notion write fails: suppress stuck-alert spam
_reinvestigate_failed_at: dict[str, float] = {}
REINVESTIGATE_FAILED_SUPPRESS_MINUTES = 90
# Parents already decomposed this run (avoid duplicate decomposition)
_decomposed_parents: set[str] = set()
# Parent -> child task ids (for aggregation when children complete)
_parent_child_map: dict[str, list[str]] = {}


def record_reinvestigate_failed(task_id: str) -> None:
    """Record that user attempted Re-investigate but Notion write failed. Suppresses stuck-alert spam."""
    tid = (task_id or "").strip()
    if tid:
        import time
        _reinvestigate_failed_at[tid] = time.time()


def _recently_failed_reinvestigate(task_id: str, now_ts: float) -> bool:
    """True if user attempted Re-investigate for this task and it failed within suppress window."""
    ts = _reinvestigate_failed_at.get((task_id or "").strip())
    if ts is None:
        return False
    return (now_ts - ts) < (REINVESTIGATE_FAILED_SUPPRESS_MINUTES * 60)


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


def _send_stuck_alert(task: dict[str, Any], minutes_stuck: float, *, retry_attempt: int = 1) -> None:
    """Send to Claw (task-system). Stuck task alert. Suppressed in quiet mode (INFO/IMPORTANT).
    Includes retry attempt count. Re-investigate button when in investigation phase."""
    try:
        from app.services.agent_telegram_policy import should_send_agent_telegram, AGENT_MSG_IMPORTANT
        if not should_send_agent_telegram(AGENT_MSG_IMPORTANT):
            logger.info("task_health_monitor: stuck alert suppressed (quiet mode) task_id=%s", (task.get("id") or "")[:12])
            return
    except Exception:
        pass
    try:
        from app.services.claw_telegram import send_claw_message
        from app.services.agent_telegram_approval import PREFIX_REINVESTIGATE, PREFIX_VIEW_REPORT
        task_id = (task.get("id") or "").strip()
        title = (task.get("task") or "(untitled)")[:80]
        status = (task.get("status") or "?")[:30]
        message = (
            "Task appears stuck.\n\n"
            f"Title: {title}\n"
            f"Status: {status}\n"
            f"Time stuck: {minutes_stuck:.0f} min\n"
            f"Retry attempt: {retry_attempt}/{MAX_AUTO_REINVESTIGATE}\n\n"
            "Attempting automatic recovery."
        )
        reply_markup = None
        # Add Re-investigate when task was moved to needs-revision (investigation stuck case)
        if task_id and (status or "").lower() in ("in-progress", "investigating"):
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "🔁 Re-investigate", "callback_data": f"{PREFIX_REINVESTIGATE}{task_id}"},
                        {"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"},
                    ],
                ]
            }
        send_claw_message(
            message,
            message_type="TASK",
            source_module="task_health_monitor",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.debug("task_health_monitor: claw_telegram import/send failed %s", e)


def _send_decomposition_alert(task: dict[str, Any], *, child_count: int) -> None:
    """Send to Claw: task was decomposed into subtasks."""
    try:
        from app.services.agent_telegram_policy import should_send_agent_telegram, AGENT_MSG_IMPORTANT
        if not should_send_agent_telegram(AGENT_MSG_IMPORTANT):
            return
    except Exception:
        pass
    try:
        from app.services.claw_telegram import send_claw_message
        from app.services.agent_telegram_approval import PREFIX_VIEW_REPORT
        task_id = (task.get("id") or "").strip()
        title = (task.get("task") or "(untitled)")[:80]
        message = (
            "Task decomposed into subtasks.\n\n"
            f"Title: {title}\n"
            f"Parent task ID: {task_id[:12]}…\n"
            f"Created {child_count} child tasks.\n\n"
            "Scheduler will pick up subtasks. Parent will resume when all complete."
        )
        reply_markup = {"inline_keyboard": [[{"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"}]]} if task_id else None
        send_claw_message(message, message_type="TASK", source_module="task_health_monitor", reply_markup=reply_markup)
    except Exception as e:
        logger.debug("task_health_monitor: decomposition alert failed %s", e)


def _send_manual_attention_alert(task: dict[str, Any], *, blocked_reason: str = "") -> None:
    """Send to Claw (task-system). Task requires attention (CRITICAL: after max retries).
    Task was moved to Blocked — operational failure, no user revision required."""
    try:
        from app.services.agent_telegram_policy import should_send_agent_telegram, AGENT_MSG_CRITICAL
        if not should_send_agent_telegram(AGENT_MSG_CRITICAL):
            return
    except Exception:
        pass
    try:
        from app.services.claw_telegram import send_claw_message
        from app.services.agent_telegram_approval import PREFIX_REINVESTIGATE, PREFIX_VIEW_REPORT
        task_id = (task.get("id") or "").strip()
        title = (task.get("task") or "(untitled)")[:80]
        status = (task.get("status") or "?")[:30]
        reason = (blocked_reason or "Max automatic retries reached.")[:200]
        message = (
            "Task blocked (operational failure).\n\n"
            f"Title: {title}\n"
            f"Status: {status}\n\n"
            f"Reason: {reason}\n\n"
            "No user revision required. Re-queue manually when ready."
        )
        reply_markup = None
        if task_id:
            reply_markup = {
                "inline_keyboard": [
                    [
                        {"text": "🔁 Re-investigate", "callback_data": f"{PREFIX_REINVESTIGATE}{task_id}"},
                        {"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"},
                    ],
                ]
            }
        send_claw_message(
            message,
            message_type="ERROR",
            source_module="task_health_monitor",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.debug("task_health_monitor: claw_telegram import/send failed %s", e)


def _log_event(event_type: str, task_id: str = "", task_title: str = "", details: dict | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, task_id=task_id or None, task_title=task_title or None, details=details or {})
    except Exception as e:
        logger.debug("task_health_monitor: log_agent_event failed %s", e)


def handle_stuck_task(task: dict[str, Any], now: datetime | None = None) -> None:
    """
    Handle a single stuck task: recovery action by status, or after max retries
    move to Blocked (never Needs Revision for operational failures). Sends at most
    one stuck alert per incident (cooldown 30 min). Never raises.

    Investigation stuck: moves to ready-for-investigation (retryable). Never uses
    Needs Revision for operational timeouts — only explicit user-action cases.
    """
    if not task:
        return
    now = now or datetime.now(timezone.utc)
    task_id = (task.get("id") or "").strip()
    task_title = (task.get("task") or "(untitled)")[:200]
    status = (task.get("status") or "").strip().lower()

    retries = _retry_count.get(task_id, 0)
    already_decomposed = task_id in _decomposed_parents

    # At retry limit: decompose if eligible, else block
    if retries >= MAX_AUTO_REINVESTIGATE:
        try:
            from app.services.task_decomposition import (
                should_decompose_task,
                execute_decomposition,
            )
            if should_decompose_task(task, retries, already_decomposed=already_decomposed):
                result = execute_decomposition(task)
                if result.get("ok") and result.get("child_ids"):
                    _decomposed_parents.add(task_id)
                    _parent_child_map[task_id] = list(result.get("child_ids", []))
                    _log_event(
                        "task_decomposed",
                        task_id=task_id,
                        task_title=task_title,
                        details={
                            "parent_id": task_id,
                            "child_count": result.get("child_count", 0),
                            "child_ids": result.get("child_ids", []),
                            "reason": "retry_limit_reached",
                        },
                    )
                    if result.get("child_count"):
                        _send_decomposition_alert(task, child_count=result["child_count"])
                    _retry_count.pop(task_id, None)
                    _last_alert_sent.pop(task_id, None)
                    return
        except Exception as e:
            logger.warning("task_health_monitor: decomposition failed task_id=%s %s", task_id[:12], e)
            _log_event("task_decomposition_failed", task_id=task_id, task_title=task_title, details={"error": str(e)[:200]})

        # Decompose failed or not eligible — move to Blocked
        blocker_reason = (
            f"Task stuck after {MAX_AUTO_REINVESTIGATE} automatic retries. "
            "Decomposition not applicable or failed. Re-queue manually when ready."
        )
        try:
            from app.services.notion_tasks import (
                TASK_STATUS_BLOCKED,
                update_notion_task_status,
                update_notion_task_metadata,
            )
            update_notion_task_status(
                task_id,
                TASK_STATUS_BLOCKED,
                append_comment=(
                    f"Auto-transition: {status} → blocked.\n"
                    f"Reason: {blocker_reason}\n"
                    "Retryable: yes (re-queue manually). User action required: no."
                ),
            )
            update_notion_task_metadata(task_id, {"blocker_reason": blocker_reason[:500]})
        except Exception as e:
            logger.warning("task_health_monitor: move to blocked failed task_id=%s %s", task_id[:12], e)
        _send_manual_attention_alert(task, blocked_reason=blocker_reason)
        _log_event(
            "auto_transition",
            task_id=task_id,
            task_title=task_title,
            details={
                "from_status": status,
                "to_status": "blocked",
                "reason": "retry_limit_or_decompose_failed",
                "user_action_required": False,
                "retryable": True,
            },
        )
        # Reset retry count so we don't keep updating the same task
        _retry_count.pop(task_id, None)
        _last_alert_sent.pop(task_id, None)
        return

    # Cooldown: send at most one "stuck" alert per task per ALERT_COOLDOWN_MINUTES
    # Suppress if user recently clicked Re-investigate but Notion write failed (avoid spam)
    last_alert = _last_alert_sent.get(task_id)
    now_ts = now.timestamp()
    send_alert = (
        (last_alert is None or (now_ts - last_alert) >= (ALERT_COOLDOWN_MINUTES * 60))
        and not _recently_failed_reinvestigate(task_id, now_ts)
    )
    minutes_stuck = _minutes_stuck(task, now)

    _log_event(
        "stuck_task_detected",
        task_id=task_id,
        task_title=task_title,
        details={"status": status, "minutes_stuck": round(minutes_stuck, 1)},
    )

    if status in ("in-progress", "investigating"):
        # Case 1: Investigation stuck — move to ready-for-investigation (retryable)
        # Never use Needs Revision for operational timeouts.
        failure_reason = "Investigation timed out (no progress within threshold). Retrying automatically."
        try:
            from app.services.notion_tasks import (
                TASK_STATUS_READY_FOR_INVESTIGATION,
                update_notion_task_status,
                update_notion_task_metadata,
            )
            update_notion_task_status(
                task_id,
                TASK_STATUS_READY_FOR_INVESTIGATION,
                append_comment=(
                    f"Auto-transition: {status} → ready-for-investigation.\n"
                    f"Reason: {failure_reason}\n"
                    f"Attempt {retries + 1}/{MAX_RETRIES}. Retryable: yes. User action required: no."
                ),
            )
            update_notion_task_metadata(
                task_id,
                {"revision_reason": f"[operational] {failure_reason}"[:500]},
            )
        except Exception as e:
            logger.warning("task_health_monitor: investigation recovery failed task_id=%s %s", task_id[:12], e)
        if send_alert:
            _send_stuck_alert(task, minutes_stuck, retry_attempt=retries + 1)
            _last_alert_sent[task_id] = now_ts
        _retry_count[task_id] = retries + 1
        _log_event(
            "auto_transition",
            task_id=task_id,
            task_title=task_title,
            details={
                "from_status": status,
                "to_status": "ready-for-investigation",
                "reason": failure_reason,
                "retryable": True,
                "user_action_required": False,
                "retry_attempt": retries + 1,
            },
        )

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
            _send_stuck_alert(task, minutes_stuck, retry_attempt=retries + 1)
            _last_alert_sent[task_id] = now_ts
        _retry_count[task_id] = retries + 1

    elif status == "testing":
        # Case 3: Testing stuck — add comment; no direct "re-run validation" API, so just comment and retry count
        try:
            from app.services.notion_tasks import update_notion_task_status
            update_notion_task_status(
                task_id,
                "testing",
                append_comment="Task stuck during testing. Consider re-running validation or re-queuing manually.",
            )
        except Exception as e:
            logger.warning("task_health_monitor: testing comment failed task_id=%s %s", task_id[:12], e)
        if send_alert:
            _send_stuck_alert(task, minutes_stuck, retry_attempt=retries + 1)
            _last_alert_sent[task_id] = now_ts
        _retry_count[task_id] = retries + 1
        _log_event("stuck_task_recovered", task_id=task_id, task_title=task_title, details={"action": "comment_only_testing"})


TERMINAL_OR_DONE_STATUSES = ("done", "deployed", "rejected", "blocked", "investigation-complete")


def check_parent_aggregation() -> int:
    """
    For parents in waiting-on-subtasks, check if all children are done/blocked.
    If so, move parent to ready-for-investigation for final aggregation.
    Returns number of parents resumed.
    """
    count = 0
    for parent_id, child_ids in list(_parent_child_map.items()):
        if not child_ids:
            continue
        try:
            from app.services.notion_task_reader import get_notion_task_by_id
            from app.services.notion_tasks import (
                TASK_STATUS_READY_FOR_INVESTIGATION,
                update_notion_task_status,
            )
            parent = get_notion_task_by_id(parent_id)
            if not parent:
                continue
            if (parent.get("status") or "").strip().lower() != "waiting-on-subtasks":
                continue
            all_terminal = True
            for cid in child_ids:
                child = get_notion_task_by_id(cid)
                if not child:
                    all_terminal = False
                    break
                cs = (child.get("status") or "").strip().lower()
                if cs not in TERMINAL_OR_DONE_STATUSES:
                    all_terminal = False
                    break
            if all_terminal:
                ok = update_notion_task_status(
                    parent_id,
                    TASK_STATUS_READY_FOR_INVESTIGATION,
                    append_comment="All subtasks complete. Resuming parent for final aggregation.",
                )
                if ok:
                    _parent_child_map.pop(parent_id, None)
                    _decomposed_parents.discard(parent_id)
                    _log_event(
                        "parent_aggregation_resumed",
                        task_id=parent_id,
                        task_title=(parent.get("task") or "")[:200],
                        details={"child_count": len(child_ids), "reason": "all_children_terminal"},
                    )
                    count += 1
        except Exception as e:
            logger.debug("check_parent_aggregation failed parent_id=%s %s", parent_id[:12], e)
    return count


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
