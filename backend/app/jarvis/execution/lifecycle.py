"""Task lifecycle state machine for Jarvis execution framework."""

from __future__ import annotations

from enum import Enum


class TaskLifecycleState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    # Phase 4 change workflow states
    INVESTIGATING = "investigating"
    PATCH_READY = "patch_ready"
    REVIEWING = "reviewing"
    TESTING = "testing"
    APPROVED = "approved"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Legacy MVP statuses mapped to Phase 3 states.
LEGACY_STATUS_MAP: dict[str, TaskLifecycleState] = {
    "running": TaskLifecycleState.EXECUTING,
    "requires_approval": TaskLifecycleState.WAITING_FOR_APPROVAL,
    "completed": TaskLifecycleState.COMPLETED,
    "failed": TaskLifecycleState.FAILED,
}


TERMINAL_STATES: frozenset[TaskLifecycleState] = frozenset(
    {
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[TaskLifecycleState, frozenset[TaskLifecycleState]] = {
    TaskLifecycleState.QUEUED: frozenset({TaskLifecycleState.PLANNING, TaskLifecycleState.CANCELLED}),
    TaskLifecycleState.PLANNING: frozenset(
        {
            TaskLifecycleState.EXECUTING,
            TaskLifecycleState.INVESTIGATING,
            TaskLifecycleState.WAITING_FOR_APPROVAL,
            TaskLifecycleState.FAILED,
            TaskLifecycleState.CANCELLED,
        }
    ),
    # Phase 4 change pipeline
    TaskLifecycleState.INVESTIGATING: frozenset(
        {TaskLifecycleState.PATCH_READY, TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED}
    ),
    TaskLifecycleState.PATCH_READY: frozenset(
        {TaskLifecycleState.REVIEWING, TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED}
    ),
    TaskLifecycleState.REVIEWING: frozenset(
        {
            TaskLifecycleState.TESTING,
            TaskLifecycleState.WAITING_FOR_APPROVAL,
            TaskLifecycleState.FAILED,
            TaskLifecycleState.CANCELLED,
        }
    ),
    TaskLifecycleState.TESTING: frozenset(
        {TaskLifecycleState.WAITING_FOR_APPROVAL, TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED}
    ),
    TaskLifecycleState.APPROVED: frozenset(
        {TaskLifecycleState.COMPLETED, TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED}
    ),
    TaskLifecycleState.WAITING_FOR_APPROVAL: frozenset(
        {
            TaskLifecycleState.EXECUTING,
            TaskLifecycleState.APPROVED,
            TaskLifecycleState.CANCELLED,
            TaskLifecycleState.FAILED,
        }
    ),
    TaskLifecycleState.EXECUTING: frozenset(
        {TaskLifecycleState.COMPLETED, TaskLifecycleState.FAILED, TaskLifecycleState.CANCELLED}
    ),
    TaskLifecycleState.COMPLETED: frozenset(),
    TaskLifecycleState.FAILED: frozenset(),
    TaskLifecycleState.CANCELLED: frozenset(),
}

# Phase 4 ordered pipeline (for progress reporting).
CHANGE_WORKFLOW_PIPELINE: tuple[TaskLifecycleState, ...] = (
    TaskLifecycleState.QUEUED,
    TaskLifecycleState.PLANNING,
    TaskLifecycleState.INVESTIGATING,
    TaskLifecycleState.PATCH_READY,
    TaskLifecycleState.REVIEWING,
    TaskLifecycleState.TESTING,
    TaskLifecycleState.WAITING_FOR_APPROVAL,
    TaskLifecycleState.APPROVED,
    TaskLifecycleState.COMPLETED,
)


class InvalidTaskTransitionError(ValueError):
    """Raised when a lifecycle transition is not permitted."""


def normalize_status(raw: str | None) -> TaskLifecycleState:
    value = (raw or "").strip().lower()
    if not value:
        return TaskLifecycleState.QUEUED
    try:
        return TaskLifecycleState(value)
    except ValueError:
        mapped = LEGACY_STATUS_MAP.get(value)
        if mapped is not None:
            return mapped
        raise InvalidTaskTransitionError(f"unknown task status: {raw}")


def validate_transition(current: str | TaskLifecycleState, target: str | TaskLifecycleState) -> TaskLifecycleState:
    cur = current if isinstance(current, TaskLifecycleState) else normalize_status(str(current))
    nxt = target if isinstance(target, TaskLifecycleState) else normalize_status(str(target))
    allowed = ALLOWED_TRANSITIONS.get(cur, frozenset())
    if nxt not in allowed:
        raise InvalidTaskTransitionError(f"invalid transition: {cur.value} -> {nxt.value}")
    return nxt


def is_terminal(state: str | TaskLifecycleState) -> bool:
    st = state if isinstance(state, TaskLifecycleState) else normalize_status(str(state))
    return st in TERMINAL_STATES
