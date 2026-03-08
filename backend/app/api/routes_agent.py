"""Agent orchestration status endpoint.

Provides a lightweight read-only view of the scheduler and task
lifecycle for operational dashboards and quick health checks.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


def _count_tasks_by_statuses(statuses: list[str]) -> int:
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        return len(get_tasks_by_status(statuses, max_results=50))
    except Exception as exc:
        logger.debug("routes_agent: get_tasks_by_status(%s) failed: %s", statuses, exc)
        return -1


@router.get("/agent/status")
def agent_status() -> dict[str, Any]:
    """Return a snapshot of the agent orchestration state."""
    from app.services.agent_scheduler import get_scheduler_state

    state = get_scheduler_state()

    pending = _count_tasks_by_statuses(["planned", "Planned", "backlog", "Backlog"])
    investigation = _count_tasks_by_statuses([
        "investigation", "Investigation",
        "investigation-complete", "Investigation Complete",
    ])
    patch = _count_tasks_by_statuses([
        "ready-for-patch", "Ready for Patch",
        "patching", "Patching",
    ])
    awaiting_deploy = _count_tasks_by_statuses([
        "awaiting-deploy-approval", "Awaiting Deploy Approval",
    ])
    deploying = _count_tasks_by_statuses(["deploying", "Deploying"])

    pending_approvals = 0
    try:
        from app.services.agent_telegram_approval import get_pending_approvals
        pending_approvals = len(get_pending_approvals())
    except Exception as exc:
        logger.debug("routes_agent: get_pending_approvals failed: %s", exc)
        pending_approvals = -1

    return {
        "scheduler_running": state["running"],
        "automation_enabled": state["automation_enabled"],
        "last_scheduler_cycle": state["last_cycle"],
        "scheduler_interval_s": state["interval"],
        "pending_notion_tasks": pending,
        "tasks_in_investigation": investigation,
        "tasks_in_patch_phase": patch,
        "tasks_awaiting_deploy": awaiting_deploy,
        "tasks_deploying": deploying,
        "pending_approvals": pending_approvals,
    }
