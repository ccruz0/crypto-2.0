"""Scheduler orchestration: queue, execute, and recover stale tasks."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.jarvis.investigations.scheduler import config as sched_config
from app.jarvis.investigations.scheduler.leader import try_acquire_leader
from app.jarvis.investigations.scheduler.persistence import (
    ScheduledTaskStatus,
    claim_next_pending_task,
    complete_task,
    create_task,
    ensure_tables,
    has_active_task_for_schedule,
    list_due_schedules,
    stale_running_tasks,
    update_schedule_run_times,
    upsert_schedule,
)
from app.jarvis.investigations.scheduler.templates import RECURRING_INVESTIGATION_TEMPLATES
from app.jarvis.investigations.submit import InvestigationBlockedError, submit_investigation_readonly

logger = logging.getLogger(__name__)

_instance_id: str | None = None
_last_cycle_at: str = ""
_last_cycle_result: dict[str, Any] = {}


def _get_instance_id() -> str:
    global _instance_id
    if _instance_id is None:
        _instance_id = sched_config.scheduler_instance_id()
    return _instance_id


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def seed_default_schedules() -> int:
    """Ensure all recurring templates exist in the schedules table."""
    created = 0
    for template in RECURRING_INVESTIGATION_TEMPLATES:
        upsert_schedule(
            schedule_id=template.schedule_id,
            template_id=template.template_id,
            title=template.title,
            objective=template.objective,
            category=template.category,
            enabled=template.enabled,
        )
        created += 1
    return created


def queue_due_investigations(*, interval_seconds: int) -> list[dict[str, Any]]:
    """Enqueue pending tasks for schedules that are due, skipping duplicates."""
    queued: list[dict[str, Any]] = []
    for schedule in list_due_schedules():
        schedule_id = schedule["schedule_id"]
        if has_active_task_for_schedule(schedule_id):
            logger.debug("scheduler: skip duplicate queue for %s", schedule_id)
            continue
        try:
            task = create_task(
                schedule_id=schedule_id,
                template_id=schedule["template_id"],
                objective=schedule["objective"],
            )
            queued.append(task)
            now = _now_utc()
            update_schedule_run_times(
                schedule_id,
                last_run_at=now,
                next_run_at=now + timedelta(seconds=interval_seconds),
            )
        except ValueError as exc:
            logger.info("scheduler: queue skipped %s: %s", schedule_id, exc)
        except Exception as exc:
            logger.warning("scheduler: queue failed %s: %s", schedule_id, exc)
    return queued


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Run one queued investigation through the human-equivalent read-only path."""
    task_id = task["task_id"]
    objective = task["objective"]
    started = time.monotonic()
    try:
        report = submit_investigation_readonly(objective)
        duration_ms = int((time.monotonic() - started) * 1000)
        inv_status = str(report.status.value if hasattr(report.status, "value") else report.status)
        terminal = (
            ScheduledTaskStatus.COMPLETED
            if inv_status in {"completed", "insufficient_evidence", "partial_failure"}
            else ScheduledTaskStatus.FAILED
        )
        summary = (report.summary or report.root_cause or inv_status)[:4000]
        updated = complete_task(
            task_id,
            status=terminal,
            investigation_id=report.investigation_id,
            result_summary=summary,
            duration_ms=duration_ms,
        )
        _maybe_emit_investigation_alert(report, task)
        return {
            "ok": True,
            "task_id": task_id,
            "investigation_id": report.investigation_id,
            "status": terminal.value,
            "duration_ms": duration_ms,
            "task": updated,
        }
    except InvestigationBlockedError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        updated = complete_task(
            task_id,
            status=ScheduledTaskStatus.FAILED,
            error_message=str(exc),
            duration_ms=duration_ms,
        )
        _maybe_emit_task_failure_alert(task, str(exc))
        return {"ok": False, "task_id": task_id, "error": str(exc), "task": updated}
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.exception("scheduler: task %s failed: %s", task_id, exc)
        updated = complete_task(
            task_id,
            status=ScheduledTaskStatus.FAILED,
            error_message=str(exc),
            duration_ms=duration_ms,
        )
        _maybe_emit_task_failure_alert(task, str(exc))
        return {"ok": False, "task_id": task_id, "error": str(exc), "task": updated}


def _maybe_emit_investigation_alert(report: Any, task: dict[str, Any]) -> None:
    """Phase 6B: read-only alert emission after scheduled investigation."""
    try:
        from app.jarvis.investigations.alerting.engine import process_investigation_alert

        source = str(task.get("schedule_id") or task.get("template_id") or "scheduler")
        process_investigation_alert(
            report,
            source=source,
            investigation_type=str(task.get("template_id") or source),
        )
    except Exception as exc:
        logger.warning("scheduler: alert emission skipped: %s", exc)


def _maybe_emit_task_failure_alert(task: dict[str, Any], error_message: str) -> None:
    """Phase 6B: CRITICAL alert when scheduled task fails."""
    try:
        from app.jarvis.investigations.alerting.engine import process_task_failure_alert

        source = str(task.get("schedule_id") or task.get("template_id") or "scheduler")
        process_task_failure_alert(
            source=source,
            objective=str(task.get("objective") or ""),
            error_message=error_message,
            investigation_type=str(task.get("template_id") or source),
        )
    except Exception as exc:
        logger.warning("scheduler: failure alert emission skipped: %s", exc)


def recover_stale_running_tasks(*, lease_seconds: int) -> int:
    """Fail over tasks stuck in running state beyond the leader lease window."""
    cutoff = _now_utc() - timedelta(seconds=lease_seconds * 2)
    recovered = 0
    for task in stale_running_tasks(older_than=cutoff):
        complete_task(
            task["task_id"],
            status=ScheduledTaskStatus.FAILED,
            error_message="failover: stale running task recovered by new leader",
            duration_ms=task.get("duration_ms") or 0,
        )
        recovered += 1
    return recovered


def run_investigation_scheduler_cycle() -> dict[str, Any]:
    """
    One scheduler cycle: leader check → seed → queue due → execute one task.

    Never raises; returns structured result for logging and tests.
    """
    global _last_cycle_at, _last_cycle_result

    if not sched_config.investigation_scheduler_enabled():
        result = {"ok": True, "action": "disabled", "reason": "scheduler_disabled"}
        _last_cycle_result = result
        return result

    if not ensure_tables():
        result = {"ok": False, "action": "error", "reason": "database_unavailable"}
        _last_cycle_result = result
        return result

    holder_id = _get_instance_id()
    if not try_acquire_leader(holder_id):
        result = {"ok": True, "action": "standby", "reason": "not_leader", "holder_id": holder_id}
        _last_cycle_result = result
        return result

    interval = sched_config.investigation_scheduler_interval_seconds()
    lease = sched_config.investigation_scheduler_leader_lease_seconds()
    recover_stale_running_tasks(lease_seconds=lease)
    seed_default_schedules()
    queued = queue_due_investigations(interval_seconds=interval)

    executed: dict[str, Any] | None = None
    claimed = claim_next_pending_task()
    if claimed:
        executed = execute_task(claimed)

    _last_cycle_at = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "ok": True,
        "action": "cycle_complete",
        "holder_id": holder_id,
        "queued_count": len(queued),
        "executed": executed,
        "last_cycle_at": _last_cycle_at,
    }
    _last_cycle_result = result
    return result


def get_last_cycle_snapshot() -> dict[str, Any]:
    return {
        "last_cycle_at": _last_cycle_at,
        "last_cycle_result": dict(_last_cycle_result),
        "instance_id": _get_instance_id(),
    }
