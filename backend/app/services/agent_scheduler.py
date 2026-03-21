"""
Minimal scheduler for the agent workflow: one task per cycle.

Orchestrates: prepare next task → if approval required send to Telegram;
if low-risk and approval not required, auto-execute. Never raises; returns
structured results and logs all outcomes to the agent activity log.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduler state (module-level, updated each cycle)
# ---------------------------------------------------------------------------

_scheduler_running: bool = False
_last_cycle_ts: str = ""

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
    True if this task already has an approval record — prevents the main
    scheduler from re-sending approval requests or re-processing tasks that
    are already tracked by the approval/execution lifecycle.

    The retry mechanism (``retry_approved_failed_tasks``) handles re-execution
    of approved-but-failed tasks separately with its own retry limit.
    """
    if not (task_id or "").strip():
        return False
    try:
        from app.services.agent_telegram_approval import get_task_approval_decision
    except Exception as e:
        logger.warning("agent_scheduler: is_task_already_in_flight import failed %s", e)
        return False
    decision = get_task_approval_decision(task_id)
    if decision:
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


def _ensure_notion_env_preflight() -> bool:
    """
    Pre-flight: ensure NOTION_API_KEY and NOTION_TASK_DB are set.
    If missing, try inline repair from SSM; set last_pickup_error on failure.
    Returns True if env is ok to run pickup.
    """
    try:
        from app.services.notion_env import (
            check_notion_env,
            try_repair_notion_env_from_ssm,
            set_last_pickup_status as _set_status,
        )
    except Exception as e:
        logger.warning("agent_scheduler: notion_env import failed %s", e)
        _set_status = None
        def check_notion_env() -> tuple[bool, str]:
            return False, "unknown"
        def try_repair_notion_env_from_ssm() -> bool:
            return False
    ok, source = check_notion_env()
    if ok:
        if _set_status:
            _set_status("ok", "")
        return True
    logger.info("notion_preflight NOTION_env=missing attempting auto_repair")
    repaired = try_repair_notion_env_from_ssm()
    if repaired:
        ok2, _ = check_notion_env()
        if ok2:
            if _set_status:
                _set_status("ok_after_repair", "")
            return True
    if _set_status:
        _set_status("env_missing", "NOTION_API_KEY or NOTION_TASK_DB missing; auto-repair failed or unavailable")
    return False


def run_agent_scheduler_cycle(
    *,
    project: str | None = None,
    type_filter: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Run one scheduler cycle: prepare at most one task, then either request approval
    or auto-execute if low-risk. Process at most one task per cycle. Never raises.

    If task_id is provided, runs that specific Notion task (must be planned/backlog/ready-for-investigation/blocked).
    """
    logger.info(
        "scheduler_cycle_start project=%r type_filter=%r task_id=%r ts=%s",
        project,
        type_filter,
        task_id[:12] + "…" if task_id and len(task_id) > 12 else task_id,
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _log_event("scheduler_cycle_started", details={"project": project, "type_filter": type_filter, "task_id": task_id})

    # Pre-flight: NOTION_* present or auto-repair from SSM
    if not _ensure_notion_env_preflight():
        try:
            from app.services.notion_env import set_last_pickup_status
            set_last_pickup_status("skipped", "NOTION env missing")
        except Exception:
            pass
        logger.warning("agent_scheduler: skipping cycle NOTION_env=missing")
        return {
            "ok": True,
            "action": "none",
            "reason": "notion_env_missing",
        }

    # Retry fallback tasks (Telegram-created tasks stored locally when Notion was down)
    try:
        from app.services.task_compiler import retry_failed_notion_tasks
        synced = retry_failed_notion_tasks()
        if synced:
            logger.info("agent_scheduler: retry_failed_notion_tasks synced=%d", synced)
    except Exception as e:
        logger.warning("agent_scheduler: retry_failed_notion_tasks failed (non-fatal) %s", e)

    # Auto-promote new Investigation tasks (Type=Investigation, Status=Planned, Source=Carlos) to Ready for Investigation once per cycle
    try:
        from app.services.notion_tasks import promote_planned_investigation_tasks_to_ready
        promoted_ids = promote_planned_investigation_tasks_to_ready()
        if promoted_ids:
            logger.info("agent_scheduler: auto_promoted_planned_investigation count=%d task_ids=%s", len(promoted_ids), [t[:12] for t in promoted_ids])
    except Exception as e:
        logger.warning("agent_scheduler: promote_planned_investigation_tasks_to_ready failed (non-fatal) %s", e)

    # Stuck task detection and recovery (before preparing next task)
    try:
        from app.services.task_health_monitor import check_for_stuck_tasks
        handled = check_for_stuck_tasks()
        if handled:
            logger.info("agent_scheduler: check_for_stuck_tasks handled=%d", handled)
    except Exception as e:
        logger.warning("agent_scheduler: check_for_stuck_tasks failed (non-fatal) %s", e)

    # Parent aggregation: resume parents when all children complete
    try:
        from app.services.task_health_monitor import check_parent_aggregation
        resumed = check_parent_aggregation()
        if resumed:
            logger.info("agent_scheduler: check_parent_aggregation resumed=%d", resumed)
    except Exception as e:
        logger.warning("agent_scheduler: check_parent_aggregation failed (non-fatal) %s", e)

    # Needs Revision: process before main intake so stuck tasks converge to resolution
    requeued_task_id: str | None = None
    try:
        from app.services.needs_revision_processor import run_needs_revision_cycle
        nr_results = run_needs_revision_cycle(max_tasks=1)
        if nr_results:
            r0 = nr_results[0]
            logger.info(
                "agent_scheduler: needs_revision_cycle action=%s task_id=%s ok=%s",
                r0.get("action"), (r0.get("task_id") or "")[:12], r0.get("ok"),
            )
            # If we requeued a task, prioritize it for this cycle
            if r0.get("action") == "requeued" and r0.get("ok"):
                requeued_task_id = r0.get("task_id")
                if requeued_task_id:
                    _log_event("scheduler_needs_revision_requeued", task_id=requeued_task_id, details=r0)
    except Exception as e:
        logger.warning("agent_scheduler: needs_revision_cycle failed (non-fatal) %s", e)

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

    prepared_bundle = None
    last_error = None
    # Prefer explicit task_id when provided; otherwise use requeued needs-revision task
    effective_task_id = task_id if (task_id or "").strip() else requeued_task_id
    for attempt in range(2):  # initial + one retry after repair
        try:
            prepared_bundle = prepare_task_with_approval_check(project=project, type_filter=type_filter, task_id=effective_task_id)
            break
        except Exception as e:
            last_error = e
            logger.warning("agent_scheduler: prepare_task_with_approval_check attempt=%d failed %s", attempt + 1, e)
            if attempt == 0:
                # Retry once after attempting repair
                try:
                    from app.services.notion_env import try_repair_notion_env_from_ssm
                    if try_repair_notion_env_from_ssm():
                        logger.info("agent_scheduler: auto_repair_triggered retrying prepare")
                        continue
                except Exception:
                    pass
            logger.exception("agent_scheduler: prepare_task_with_approval_check failed")
            _log_event("scheduler_cycle_failed", details={"reason": "prepare failed", "error": str(e)})
            try:
                from app.services.notion_env import set_last_pickup_status
                set_last_pickup_status("prepare_failed", str(e))
            except Exception:
                pass
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

    # No execution gate: user decides what matters. System prioritizes and schedules; never skips.
    # Low-priority tasks (backlog) are picked when higher-priority work is done.

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
    callback_selection = (prepared_bundle.get("callback_selection") or {})
    manual_only = bool(callback_selection.get("manual_only"))

    # Extended lifecycle (manual_only) and all approval_required: skip intake approval.
    # Approval is triggered ONLY when task reaches ready-for-patch (single trigger point).
    if manual_only and approval_required:
        logger.info(
            "agent_scheduler: manual_only task — running execution directly "
            "(approval only at ready-for-patch) task_id=%s",
            task_id,
        )
        try:
            from app.services.agent_task_executor import execute_prepared_task_if_approved
            result = execute_prepared_task_if_approved(prepared_bundle, approved=True)
            _log_event(
                "scheduler_extended_execution_started",
                task_id=task_id,
                task_title=task_title,
                details={
                    "execution_result_success": result.get("execution_result", {}).get("success"),
                    "final_status": result.get("execution_result", {}).get("final_status"),
                },
            )
            return {
                "ok": True,
                "action": "extended_execution_started",
                "task_id": task_id,
                "task_title": task_title,
                "execution_result": result.get("execution_result"),
                "reason": "manual_only: approval only at ready-for-patch",
            }
        except Exception as e:
            logger.exception("agent_scheduler: execute_prepared_task_if_approved failed (manual_only)")
            _log_event("scheduler_cycle_failed", task_id=task_id, task_title=task_title, details={"reason": "extended execution failed", "error": str(e)})
            return {
                "ok": False,
                "action": "extended_execution_started",
                "task_id": task_id,
                "task_title": task_title,
                "reason": "extended execution failed",
                "error": str(e),
            }

    if approval_required:
        # Approval is triggered ONLY when task reaches ready-for-patch (single trigger point).
        # Do NOT send approval at intake; run execution directly.
        logger.info(
            "agent_scheduler: approval_required — running execution directly "
            "(approval_skipped_reason=not_ready_for_patch) task_id=%s",
            task_id,
        )
        try:
            from app.services.agent_task_executor import execute_prepared_task_if_approved
            result = execute_prepared_task_if_approved(prepared_bundle, approved=True)
            _log_event(
                "scheduler_execution_started",
                task_id=task_id,
                task_title=task_title,
                details={
                    "execution_result_success": result.get("execution_result", {}).get("success"),
                    "approval_skipped_reason": "not_ready_for_patch",
                },
            )
            return {
                "ok": True,
                "action": "execution_started",
                "task_id": task_id,
                "task_title": task_title,
                "execution_result": result.get("execution_result"),
                "reason": "approval only at ready-for-patch",
            }
        except Exception as e:
            logger.exception("agent_scheduler: execute_prepared_task_if_approved failed")
            _log_event("scheduler_cycle_failed", task_id=task_id, task_title=task_title, details={"reason": "execution failed", "error": str(e)})
            return {
                "ok": False,
                "action": "execution_started",
                "task_id": task_id,
                "task_title": task_title,
                "reason": "execution failed",
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


def retry_approved_failed_tasks() -> list[dict[str, Any]]:
    """
    Find tasks that were approved but whose execution failed or never started,
    and retry execution for each. Returns a list of per-task results.
    """
    try:
        from app.services.agent_telegram_approval import (
            get_approved_retryable_task_ids,
            execute_prepared_task_from_telegram_decision,
        )
    except Exception as e:
        logger.warning("retry_approved_failed_tasks: import failed %s", e)
        return []

    task_ids = get_approved_retryable_task_ids(max_results=3)
    if not task_ids:
        return []

    results: list[dict[str, Any]] = []
    for tid in task_ids:
        logger.info("retry_approved_failed_tasks: retrying task_id=%s", tid)
        _log_event("scheduler_retry_execution", task_id=tid, details={})
        try:
            result = execute_prepared_task_from_telegram_decision(tid)
            executed = result.get("executed", False)
            reason = result.get("reason", "")
            logger.info(
                "retry_approved_failed_tasks: task_id=%s executed=%s reason=%s",
                tid, executed, reason,
            )
            results.append({"task_id": tid, "executed": executed, "reason": reason})
        except Exception as e:
            logger.error("retry_approved_failed_tasks: task_id=%s raised %s", tid, e, exc_info=True)
            results.append({"task_id": tid, "executed": False, "reason": str(e)})
    return results


# ---------------------------------------------------------------------------
# Extended lifecycle continuation: ready-for-patch → patching → validation
# ---------------------------------------------------------------------------


def continue_ready_for_patch_tasks(*, max_tasks: int = 3) -> list[dict[str, Any]]:
    """Pick up tasks in ``ready-for-patch`` and advance them through validation.

    Called once per scheduler loop iteration, after the main intake cycle.
    Queries Notion for tasks whose status is ``ready-for-patch`` and runs
    :func:`advance_ready_for_patch_task` for each (up to *max_tasks*).

    Returns a list of per-task result dicts.  Never raises.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        from app.services.agent_task_executor import advance_ready_for_patch_task
    except Exception as e:
        logger.warning("continue_ready_for_patch_tasks: import failed %s", e)
        return []

    tasks = get_tasks_by_status(
        ["ready-for-patch", "Ready for Patch", "patching", "Patching"],
        max_results=max_tasks,
    )
    if not tasks:
        return []

    logger.info("continue_ready_for_patch_tasks: found %d task(s) in ready-for-patch/patching", len(tasks))

    results: list[dict[str, Any]] = []
    for task in tasks:
        tid = str(task.get("id") or "").strip()
        title = str(task.get("task") or "").strip()
        if not tid:
            continue
        logger.info("continue_ready_for_patch_tasks: advancing task_id=%s title=%r", tid, title)
        _log_event("scheduler_patch_continuation", task_id=tid, task_title=title, details={})
        try:
            r = advance_ready_for_patch_task(tid)
            logger.info(
                "continue_ready_for_patch_tasks: task_id=%s ok=%s stage=%s final_status=%s",
                tid, r.get("ok"), r.get("stage"), r.get("final_status"),
            )
            results.append(r)
        except Exception as exc:
            logger.error(
                "continue_ready_for_patch_tasks: task_id=%s raised %s", tid, exc, exc_info=True,
            )
            results.append({"task_id": tid, "ok": False, "stage": "error", "summary": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Scheduler state helpers
# ---------------------------------------------------------------------------


def _is_automation_enabled() -> bool:
    """Check AGENT_AUTOMATION_ENABLED env var (default true).

    Re-read every cycle so it can be toggled without a restart.
    """
    raw = (os.environ.get("AGENT_AUTOMATION_ENABLED") or "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    return True


def get_scheduler_state() -> dict[str, Any]:
    """Return a snapshot of the scheduler's runtime state."""
    return {
        "running": _scheduler_running,
        "last_cycle": _last_cycle_ts,
        "interval": _get_scheduler_interval(),
        "automation_enabled": _is_automation_enabled(),
    }


# ---------------------------------------------------------------------------
# Background loop: runs run_agent_scheduler_cycle() periodically
# ---------------------------------------------------------------------------

import asyncio

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
    global _scheduler_running, _last_cycle_ts

    interval = _get_scheduler_interval()
    _scheduler_running = True
    logger.info(
        "agent_scheduler_loop_started interval=%ds",
        interval,
    )
    _log_event("scheduler_loop_started", details={"interval_seconds": interval})

    loop = asyncio.get_running_loop()

    while True:
        if not _is_automation_enabled():
            logger.warning("agent_scheduler_loop: AGENT_AUTOMATION_ENABLED=false — skipping cycle")
            await asyncio.sleep(interval)
            continue

        try:
            result = await loop.run_in_executor(None, run_agent_scheduler_cycle)
            _last_cycle_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _log_event(
                "scheduler_cycle_completed",
                details={
                    "ok": result.get("ok"),
                    "action": result.get("action"),
                    "reason": result.get("reason"),
                },
            )
            _log_event("scheduler_heartbeat_updated", details={})
            try:
                from app.services.notion_env import set_last_pickup_status, check_notion_health_transition_and_alert
                set_last_pickup_status(
                    result.get("action") or result.get("reason") or "done",
                    result.get("error") or "",
                )
                check_notion_health_transition_and_alert()
            except Exception:
                pass
            logger.info(
                "agent_scheduler_cycle_done ok=%s action=%s task=%s reason=%s",
                result.get("ok"),
                result.get("action"),
                result.get("task_title", ""),
                result.get("reason", ""),
            )
        except Exception as e:
            logger.error("agent_scheduler_loop: cycle raised %s", e, exc_info=True)
            _log_event("scheduler_cycle_failed", details={"reason": "cycle raised", "error": str(e)})
            try:
                from app.services.notion_env import set_last_pickup_status
                set_last_pickup_status("error", str(e))
            except Exception:
                pass

        try:
            retry_results = await loop.run_in_executor(None, retry_approved_failed_tasks)
            if retry_results:
                logger.info(
                    "scheduler_retry_done count=%d executed=%d",
                    len(retry_results),
                    sum(1 for r in retry_results if r.get("executed")),
                )
        except Exception as e:
            logger.error("agent_scheduler_loop: retry_approved_failed_tasks raised %s", e, exc_info=True)

        try:
            patch_results = await loop.run_in_executor(None, continue_ready_for_patch_tasks)
            if patch_results:
                logger.info(
                    "scheduler_patch_continuation_done count=%d advanced=%d",
                    len(patch_results),
                    sum(1 for r in patch_results if r.get("ok")),
                )
        except Exception as e:
            logger.error("agent_scheduler_loop: continue_ready_for_patch_tasks raised %s", e, exc_info=True)

        try:
            from app.services.agent_recovery import run_recovery_cycle
            recovery_results = await loop.run_in_executor(None, run_recovery_cycle)
            if recovery_results:
                logger.info(
                    "recovery_cycle_done count=%d advanced=%d blocked=%d reset=%d",
                    len(recovery_results),
                    sum(1 for r in recovery_results if r.get("advanced")),
                    sum(1 for r in recovery_results if r.get("blocked")),
                    sum(1 for r in recovery_results if r.get("reset_ok")),
                )
        except Exception as e:
            logger.error("agent_scheduler_loop: run_recovery_cycle raised %s", e, exc_info=True)

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
