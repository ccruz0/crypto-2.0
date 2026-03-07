"""
Minimal scheduler for the agent workflow: one task per cycle.

Orchestrates: prepare next task → if approval required send to Telegram;
if low-risk and approval not required, auto-execute. Never raises; returns
structured results and logs all outcomes to the agent activity log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Keywords that disqualify auto-execution (task must not target these)
_AUTO_EXECUTE_BLOCKED_KEYWORDS = (
    "trading",
    "trade",
    "order",
    "exchange",
    "runtime",
    "config",
    "deploy",
    "nginx",
    "docker-compose",
    "telegram_commands",
)


def _task_id_from_bundle(prepared_bundle: dict[str, Any]) -> str:
    """Extract task id from prepared bundle."""
    prepared_task = (prepared_bundle or {}).get("prepared_task") or {}
    task = prepared_task.get("task") or {}
    return str(task.get("id") or "").strip()


def _task_title_from_bundle(prepared_bundle: dict[str, Any]) -> str:
    """Extract task title from prepared bundle."""
    prepared_task = (prepared_bundle or {}).get("prepared_task") or {}
    task = prepared_task.get("task") or {}
    return str(task.get("task") or "").strip()


def _task_and_area_text(prepared_bundle: dict[str, Any]) -> str:
    """Concatenate task title, details, and repo area for keyword check."""
    prepared_task = (prepared_bundle or {}).get("prepared_task") or {}
    task = prepared_task.get("task") or {}
    title = str(task.get("task") or "")
    details = str(task.get("details") or "")
    repo_area = prepared_task.get("repo_area") or {}
    area_name = str(repo_area.get("area_name") or "")
    rules = " ".join(str(r) for r in (repo_area.get("matched_rules") or []))
    return f"{title} {details} {area_name} {rules}".lower()


def is_task_already_in_flight(task_id: str) -> bool:
    """
    True if this task already has an approval record and is pending, running, or completed.
    Used to avoid sending duplicate approval requests or re-executing.
    """
    if not (task_id or "").strip():
        return False
    try:
        from app.services.agent_telegram_approval import (
            get_task_approval_decision,
            get_task_execution_state,
            EXECUTION_STATUS_RUNNING,
            EXECUTION_STATUS_COMPLETED,
        )
    except Exception as e:
        logger.warning("agent_scheduler: is_task_already_in_flight import failed %s", e)
        return False
    decision = get_task_approval_decision(task_id)
    if not decision:
        return False
    status = (decision.get("status") or "").lower()
    if status == "pending":
        return True
    exec_state = get_task_execution_state(task_id)
    if not exec_state:
        return False
    ex_status = (exec_state.get("execution_status") or "").lower()
    if ex_status == EXECUTION_STATUS_RUNNING or ex_status == EXECUTION_STATUS_COMPLETED:
        return True
    return False


def should_auto_execute(prepared_bundle: dict[str, Any]) -> bool:
    """
    True only when approval is not required, callback is documentation or monitoring triage,
    callback is not marked manual-only, and task does not target trading, runtime config,
    deploy, nginx, docker-compose, telegram_commands.
    """
    if not prepared_bundle:
        return False
    approval = (prepared_bundle.get("approval") or {})
    if approval.get("required") is True:
        return False
    callback_selection = (prepared_bundle.get("callback_selection") or {})
    if bool(callback_selection.get("manual_only")):
        return False
    reason = (callback_selection.get("selection_reason") or "").lower()
    if "documentation" not in reason and "monitoring" not in reason and "triage" not in reason:
        return False
    text = _task_and_area_text(prepared_bundle)
    if any(kw in text for kw in _AUTO_EXECUTE_BLOCKED_KEYWORDS):
        return False
    return True


def _log_event(event_type: str, task_id: str = "", task_title: str = "", details: dict | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, task_id=task_id or None, task_title=task_title or None, details=details or {})
    except Exception as e:
        logger.debug("agent_scheduler: log_agent_event failed (non-fatal) %s", e)


def run_agent_scheduler_cycle(
    *,
    project: str | None = None,
    type_filter: str | None = None,
) -> dict[str, Any]:
    """
    Run one scheduler cycle: prepare at most one task, then either request approval
    or auto-execute if low-risk. Process at most one task per cycle. Never raises.
    """
    logger.info(
        "scheduler_cycle_start project=%r type_filter=%r ts=%s",
        project,
        type_filter,
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _log_event("scheduler_cycle_started", details={"project": project, "type_filter": type_filter})
    try:
        from app.services.agent_task_executor import prepare_task_with_approval_check
    except Exception as e:
        logger.warning("agent_scheduler: prepare_task_with_approval_check import failed %s", e)
        _log_event("scheduler_cycle_failed", details={"reason": "import failed", "error": str(e)})
        return {
            "ok": False,
            "action": "none",
            "reason": "import failed",
            "error": str(e),
        }

    try:
        prepared_bundle = prepare_task_with_approval_check(project=project, type_filter=type_filter)
    except Exception as e:
        logger.exception("agent_scheduler: prepare_task_with_approval_check failed")
        _log_event("scheduler_cycle_failed", details={"reason": "prepare failed", "error": str(e)})
        return {
            "ok": False,
            "action": "none",
            "reason": "prepare failed",
            "error": str(e),
        }

    if not prepared_bundle:
        logger.info("scheduler_no_task: prepare_task_with_approval_check returned None (no pending tasks in Notion)")
        _log_event("scheduler_no_task", details={})
        return {
            "ok": True,
            "action": "none",
            "reason": "no task",
        }

    task_id = _task_id_from_bundle(prepared_bundle)
    task_title = _task_title_from_bundle(prepared_bundle)

    if is_task_already_in_flight(task_id):
        _log_event("scheduler_task_skipped", task_id=task_id, task_title=task_title, details={"reason": "already in flight or completed"})
        return {
            "ok": True,
            "action": "skipped",
            "task_id": task_id,
            "task_title": task_title,
            "reason": "already in flight or completed",
        }

    approval = (prepared_bundle.get("approval") or {})
    approval_required = bool(approval.get("required"))

    if approval_required:
        try:
            from app.services.agent_telegram_approval import send_task_approval_request
            send_result = send_task_approval_request(prepared_bundle, chat_id=None)
            _log_event("scheduler_approval_requested", task_id=task_id, task_title=task_title, details={"sent": send_result.get("sent"), "message_id": send_result.get("message_id")})
            return {
                "ok": True,
                "action": "approval_requested",
                "task_id": task_id,
                "task_title": task_title,
                "sent": send_result.get("sent"),
                "message_id": send_result.get("message_id"),
            }
        except Exception as e:
            logger.exception("agent_scheduler: send_task_approval_request failed")
            _log_event("scheduler_cycle_failed", task_id=task_id, task_title=task_title, details={"reason": "send approval failed", "error": str(e)})
            return {
                "ok": False,
                "action": "approval_requested",
                "task_id": task_id,
                "task_title": task_title,
                "reason": "send approval failed",
                "error": str(e),
            }

    if should_auto_execute(prepared_bundle):
        try:
            from app.services.agent_task_executor import execute_prepared_task_if_approved
            result = execute_prepared_task_if_approved(prepared_bundle, approved=True)
            _log_event("scheduler_auto_executed", task_id=task_id, task_title=task_title, details={"execution_result_success": result.get("execution_result", {}).get("success")})
            return {
                "ok": True,
                "action": "auto_executed",
                "task_id": task_id,
                "task_title": task_title,
                "execution_result": result.get("execution_result"),
            }
        except Exception as e:
            logger.exception("agent_scheduler: execute_prepared_task_if_approved failed")
            _log_event("scheduler_cycle_failed", task_id=task_id, task_title=task_title, details={"reason": "auto execute failed", "error": str(e)})
            return {
                "ok": False,
                "action": "auto_executed",
                "task_id": task_id,
                "task_title": task_title,
                "reason": "auto execute failed",
                "error": str(e),
            }

    # Leave a clear Notion comment so the task is not stuck without explanation
    try:
        from app.services.agent_task_executor import append_notion_page_comment
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        comment = (
            f"[{ts}] Scheduler cycle {cycle_id}\n"
            "Task prepared. Not auto-eligible for scheduler.\n"
            "Requires manual execution (approve from Telegram or run manually)."
        )
        append_notion_page_comment(task_id, comment)
    except Exception as e:
        logger.debug("agent_scheduler: append Notion comment failed (non-fatal) %s", e)

    _log_event("scheduler_task_skipped", task_id=task_id, task_title=task_title, details={"reason": "approval not required but not auto-eligible"})
    return {
        "ok": True,
        "action": "skipped",
        "task_id": task_id,
        "task_title": task_title,
        "reason": "approval not required but not auto-eligible",
    }


# ---------------------------------------------------------------------------
# Background loop: runs run_agent_scheduler_cycle() periodically
# ---------------------------------------------------------------------------

import asyncio
import os

_AGENT_SCHEDULER_DEFAULT_INTERVAL = 300  # 5 minutes


def _get_scheduler_interval() -> int:
    """Read interval from AGENT_SCHEDULER_INTERVAL_SECONDS env var (default 300)."""
    raw = (os.environ.get("AGENT_SCHEDULER_INTERVAL_SECONDS") or "").strip()
    if raw:
        try:
            return max(30, int(raw))
        except ValueError:
            pass
    return _AGENT_SCHEDULER_DEFAULT_INTERVAL


async def start_agent_scheduler_loop() -> None:
    """
    Long-running coroutine that calls run_agent_scheduler_cycle() in a thread
    every AGENT_SCHEDULER_INTERVAL_SECONDS (default 300s / 5 min).

    Designed to be launched via ``asyncio.create_task()`` inside the FastAPI
    startup event.  Logs every cycle start/end and never raises to the caller.
    """
    interval = _get_scheduler_interval()
    logger.info(
        "agent_scheduler_loop_started interval=%ds",
        interval,
    )

    loop = asyncio.get_running_loop()

    while True:
        try:
            result = await loop.run_in_executor(None, run_agent_scheduler_cycle)
            logger.info(
                "agent_scheduler_cycle_done ok=%s action=%s task=%s reason=%s",
                result.get("ok"),
                result.get("action"),
                result.get("task_title", ""),
                result.get("reason", ""),
            )
        except Exception as e:
            logger.error("agent_scheduler_loop: cycle raised %s", e, exc_info=True)

        try:
            from app.services.agent_anomaly_detector import run_anomaly_detection_cycle
            anomaly_result = await loop.run_in_executor(None, run_anomaly_detection_cycle)
            logger.info(
                "anomaly_detection_cycle_done anomalies=%d tasks=%d errors=%d",
                anomaly_result.get("anomalies_found", 0),
                anomaly_result.get("tasks_created", 0),
                len(anomaly_result.get("errors", [])),
            )
        except Exception as e:
            logger.error("agent_scheduler_loop: anomaly detection raised %s", e, exc_info=True)

        await asyncio.sleep(interval)
