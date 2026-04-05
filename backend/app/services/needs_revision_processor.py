"""
Needs Revision processor: prevent tasks from remaining stuck in "Needs Revision".

When a task enters "Needs Revision", it must NOT remain idle. This module:
- Picks needs-revision tasks and either re-runs them or marks them Blocked
- Enforces max 3 revision attempts; after that, marks Blocked with explicit reason
- Logs revision_reason, retry_attempt, validation_result for observability

Runs at the start of each scheduler cycle (before main intake) so needs-revision
tasks are prioritized and converge to resolution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MAX_REVISION_ATTEMPTS = 3


def _get_revision_count(task: dict[str, Any]) -> int:
    """Get current revision count from task metadata. Returns 0 if missing."""
    raw = (task.get("revision_count") or task.get("Revision Count") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except (ValueError, TypeError):
        return 0


def _log_event(event_type: str, task_id: str = "", task_title: str = "", details: dict | None = None) -> None:
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(event_type, task_id=task_id or None, task_title=task_title or None, details=details or {})
    except Exception as e:
        logger.debug("needs_revision_processor: log_agent_event failed %s", e)


def _increment_revision_count_and_reason(
    task_id: str,
    revision_reason: str,
) -> bool:
    """Increment revision count and store revision reason in Notion. Best-effort."""
    try:
        from app.services.notion_task_reader import get_notion_task_by_id
        from app.services.notion_tasks import update_notion_task_metadata
        task = get_notion_task_by_id(task_id)
        if not task:
            return False
        current = _get_revision_count(task)
        new_count = current + 1
        metadata = {
            "revision_count": str(new_count),
            "revision_reason": (revision_reason or "revision")[:500],
        }
        result = update_notion_task_metadata(task_id, metadata)
        logger.info(
            "needs_revision_processor: revision_count=%d->%d task_id=%s reason=%s",
            current, new_count, task_id[:12] if task_id else "?", (revision_reason or "")[:80],
        )
        return bool(result.get("ok"))
    except Exception as e:
        logger.warning("needs_revision_processor: increment_revision_count failed task_id=%s: %s", task_id[:12] if task_id else "?", e)
        return False


def update_task_on_needs_revision(
    task_id: str,
    revision_reason: str,
) -> None:
    """
    Call when a task moves TO needs-revision. Increments revision count and
    logs revision_reason for observability.
    """
    _increment_revision_count_and_reason(task_id, revision_reason)
    _log_event(
        "task_entered_needs_revision",
        task_id=task_id,
        details={"revision_reason": (revision_reason or "")[:300]},
    )


def mark_task_blocked(
    task_id: str,
    blocker_reason: str,
) -> bool:
    """Move task to Blocked and set Blocker Reason. Returns True on success."""
    try:
        from app.services.notion_tasks import (
            TASK_STATUS_BLOCKED,
            update_notion_task_status,
            update_notion_task_metadata,
        )
        ok = update_notion_task_status(
            task_id,
            TASK_STATUS_BLOCKED,
            append_comment=(
                f"Max revision attempts ({MAX_REVISION_ATTEMPTS}) reached. "
                f"Blocked: {blocker_reason}"
            ),
        )
        if ok:
            update_notion_task_metadata(
                task_id,
                {"blocker_reason": (blocker_reason or "max revisions exceeded")[:500]},
            )
            _log_event(
                "auto_transition",
                task_id=task_id,
                details={
                    "from_status": "needs-revision",
                    "to_status": "blocked",
                    "reason": (blocker_reason or "")[:300],
                    "retryable": True,
                    "user_action_required": False,
                    "blocker_reason": (blocker_reason or "")[:300],
                },
            )
        return ok
    except Exception as e:
        logger.warning("needs_revision_processor: mark_task_blocked failed task_id=%s: %s", task_id[:12] if task_id else "?", e)
        return False


def process_needs_revision_tasks(*, max_tasks: int = 1) -> list[dict[str, Any]]:
    """
    Process tasks in "Needs Revision". For each task:
    - If revision_count >= MAX_REVISION_ATTEMPTS: mark Blocked with reason
    - Else: move to ready-for-investigation and trigger full re-execution

    Returns list of per-task result dicts. Processes at most max_tasks per call.
    """
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        from app.services.notion_tasks import (
            TASK_STATUS_READY_FOR_INVESTIGATION,
            update_notion_task_status,
        )
    except Exception as e:
        logger.warning("needs_revision_processor: import failed %s", e)
        return []

    tasks = get_tasks_by_status(
        ["needs-revision", "Needs Revision"],
        max_results=max_tasks,
    )
    if not tasks:
        return []

    logger.info(
        "needs_revision_processor: found %d needs-revision task(s), processing up to %d",
        len(tasks),
        max_tasks,
    )

    results: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        task_title = str(task.get("task") or "").strip()
        if not task_id:
            continue

        revision_count = _get_revision_count(task)
        _log_event(
            "needs_revision_processing",
            task_id=task_id,
            task_title=task_title,
            details={"revision_count": revision_count, "retry_attempt": revision_count},
        )

        if revision_count >= MAX_REVISION_ATTEMPTS:
            blocker_reason = (
                f"Failed after {revision_count} revision attempts. "
                "Last revision reason: " + (task.get("revision_reason") or task.get("Revision Reason") or "unknown")[:200]
            )
            blocked_ok = mark_task_blocked(task_id, blocker_reason)
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "action": "blocked",
                "revision_count": revision_count,
                "blocker_reason": blocker_reason,
                "ok": blocked_ok,
            })
            logger.info(
                "needs_revision_processor: task blocked task_id=%s revision_count=%d",
                task_id[:12], revision_count,
            )
            continue

        # Move to ready-for-investigation and trigger re-execution
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        move_ok = update_notion_task_status(
            task_id,
            TASK_STATUS_READY_FOR_INVESTIGATION,
            append_comment=(
                f"[{ts}] Revision attempt {revision_count + 1}/{MAX_REVISION_ATTEMPTS}: "
                "Re-queuing for re-execution. System will analyze, re-run, and validate."
            ),
            allow_status_regression=True,
        )
        if not move_ok:
            results.append({
                "task_id": task_id,
                "task_title": task_title,
                "action": "move_failed",
                "ok": False,
            })
            continue

        # Clear approval state so task can be re-investigated
        try:
            from app.database import SessionLocal
            from app.models.agent_approval_state import AgentApprovalState
            if SessionLocal:
                db = SessionLocal()
                try:
                    db.query(AgentApprovalState).filter_by(task_id=task_id).delete()
                    db.commit()
                except Exception as e:
                    logger.debug("needs_revision_processor: clear approval state failed: %s", e)
                finally:
                    try:
                        db.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("needs_revision_processor: clear approval state skipped: %s", e)

        _log_event(
            "auto_transition",
            task_id=task_id,
            task_title=task_title,
            details={
                "from_status": "needs-revision",
                "to_status": "ready-for-investigation",
                "reason": f"Revision attempt {revision_count + 1}/{MAX_REVISION_ATTEMPTS}",
                "retryable": True,
                "user_action_required": False,
                "revision_count": revision_count,
            },
        )

        results.append({
            "task_id": task_id,
            "task_title": task_title,
            "action": "requeued",
            "revision_count": revision_count,
            "ok": True,
        })
        logger.info(
            "needs_revision_processor: task requeued for re-execution task_id=%s attempt=%d",
            task_id[:12], revision_count + 1,
        )

    return results


def run_needs_revision_cycle(*, max_tasks: int = 1) -> list[dict[str, Any]]:
    """
    Run one needs-revision cycle. Processes up to max_tasks needs-revision tasks.
    Returns list of per-task results.
    """
    return process_needs_revision_tasks(max_tasks=max_tasks)
