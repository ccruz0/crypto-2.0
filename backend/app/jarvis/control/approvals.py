"""Builder approval persistence and retrieval for Jarvis Control Center."""

from __future__ import annotations

from typing import Any

from app.jarvis.control import persistence as jcp
from app.jarvis.control import workflow as builder_workflow
from app.jarvis.control.workflow import (
    BuilderWorkflowConflictError,
    BuilderWorkflowNotFoundError,
)


class BuilderApprovalNotFoundError(LookupError):
    """Raised when the target builder task does not exist."""


class BuilderApprovalConflictError(ValueError):
    """Raised when an approval action conflicts with current task state."""


def get_builder_approvals(task_id: str) -> list[dict[str, Any]] | None:
    """Return approval rows for a builder task, or None if task missing/not builder."""
    task = jcp.get_control_task(task_id)
    if task is None or task.get("mode") != "builder":
        return None
    return jcp.get_control_approvals(task_id)


def approve_builder_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Approve a builder task in awaiting_approval status."""
    try:
        return builder_workflow.approve_builder_task(
            task_id,
            actor_id=actor_id,
            comment=comment,
        )
    except BuilderWorkflowNotFoundError as exc:
        raise BuilderApprovalNotFoundError(str(exc)) from exc
    except BuilderWorkflowConflictError as exc:
        raise BuilderApprovalConflictError(str(exc)) from exc


def reject_builder_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Reject a builder task in awaiting_approval status."""
    try:
        return builder_workflow.reject_builder_task(
            task_id,
            actor_id=actor_id,
            comment=comment,
        )
    except BuilderWorkflowNotFoundError as exc:
        raise BuilderApprovalNotFoundError(str(exc)) from exc
    except BuilderWorkflowConflictError as exc:
        raise BuilderApprovalConflictError(str(exc)) from exc
