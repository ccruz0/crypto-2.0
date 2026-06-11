"""Builder task lifecycle workflow: transitions, artifacts, approvals, timeline."""

from __future__ import annotations

from typing import Any

from app.jarvis.control import persistence as jcp

BUILDER_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"awaiting_approval"}),
    "awaiting_approval": frozenset({"approved", "rejected"}),
    "approved": frozenset(),
    "rejected": frozenset(),
}

TERMINAL_BUILDER_STATUSES = frozenset({"approved", "rejected"})


class BuilderWorkflowNotFoundError(LookupError):
    """Raised when the target builder task does not exist."""


class BuilderWorkflowConflictError(ValueError):
    """Raised when a builder workflow transition is not allowed."""


def validate_builder_transition(current_status: str, target_status: str) -> None:
    """Single source of truth for allowed builder task status transitions."""
    current = (current_status or "").strip().lower()
    target = (target_status or "").strip().lower()
    if current == target:
        raise BuilderWorkflowConflictError(f"task already {target}")
    if current in TERMINAL_BUILDER_STATUSES:
        raise BuilderWorkflowConflictError(f"task already {current}")
    allowed = BUILDER_ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise BuilderWorkflowConflictError(
            f"cannot transition builder task from {current!r} to {target!r}"
        )


def _require_builder_task(task_id: str) -> dict[str, Any]:
    task = jcp.get_control_task(task_id)
    if task is None or task.get("mode") != "builder":
        raise BuilderWorkflowNotFoundError(f"Builder task not found: {task_id}")
    return task


def transition_builder_task_status(
    task_id: str,
    target_status: str,
    *,
    actor_id: str = "system",
    actor_type: str = "system",
    audit_type: str | None = None,
    audit_payload: dict[str, Any] | None = None,
    completed: bool | None = None,
) -> dict[str, Any]:
    """Validate and apply a builder status transition; optionally emit audit event."""
    task = _require_builder_task(task_id)
    current = (task.get("status") or "").strip().lower()
    target = (target_status or "").strip().lower()
    validate_builder_transition(current, target)

    if completed is None:
        completed = target in TERMINAL_BUILDER_STATUSES

    if not jcp.transition_control_task_status(
        task_id,
        expected_status=current,
        new_status=target,
        completed=completed,
    ):
        raise BuilderWorkflowConflictError("task status changed during transition")

    if audit_type:
        jcp.append_control_audit_event(
            audit_type,
            task_id=task_id,
            session_id=task.get("session_id"),
            actor_type=actor_type,
            actor_id=actor_id,
            payload={
                **(audit_payload or {}),
                "previous_status": current,
                "new_status": target,
            },
        )

    updated = jcp.get_control_task(task_id)
    if updated is None:
        raise BuilderWorkflowNotFoundError(f"Builder task not found: {task_id}")
    return updated


def save_builder_artifact(
    task_id: str,
    artifact: dict[str, Any],
    *,
    merge: bool = False,
    actor_id: str = "dashboard",
) -> dict[str, Any]:
    """Persist artifact, emit audit, and advance queued tasks to awaiting_approval."""
    task = _require_builder_task(task_id)
    previous_status = (task.get("status") or "").strip().lower()
    previous_version = int(task.get("artifact_version") or 0)

    updated = jcp.persist_builder_artifact(task_id, artifact, merge=merge)
    if updated is None:
        raise BuilderWorkflowNotFoundError(f"Builder task not found: {task_id}")

    new_version = int(updated.get("artifact_version") or 0)
    new_status = previous_status
    if previous_status == "queued":
        validate_builder_transition(previous_status, "awaiting_approval")
        if jcp.transition_control_task_status(
            task_id,
            expected_status="queued",
            new_status="awaiting_approval",
            completed=False,
        ):
            new_status = "awaiting_approval"
            updated = jcp.get_control_task(task_id) or updated

    jcp.append_control_audit_event(
        "builder_artifact_updated",
        task_id=task_id,
        session_id=task.get("session_id"),
        actor_type="human",
        actor_id=actor_id,
        payload={
            "artifact_version": new_version,
            "previous_version": previous_version,
            "merge": merge,
            "previous_status": previous_status,
            "new_status": new_status,
        },
    )

    return {
        "task_id": task_id,
        "artifact": updated.get("builder_artifact")
        if isinstance(updated.get("builder_artifact"), dict)
        else {},
        "updated_at": updated.get("artifact_updated_at"),
        "version": new_version,
        "status": new_status,
    }


def approve_builder_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Approve a builder task in awaiting_approval status."""
    task = _require_builder_task(task_id)
    validate_builder_transition(task.get("status") or "", "approved")

    actor = (actor_id or "dashboard").strip() or "dashboard"
    comment_text = (comment or "").strip() or None
    approval = jcp.insert_builder_approval_decision(
        task_id,
        decision="approved",
        actor_id=actor,
        comment=comment_text,
        risk_level=(task.get("risk_level") or "medium"),
        expected_task_status="awaiting_approval",
    )

    jcp.append_control_audit_event(
        "builder_task_approved",
        task_id=task_id,
        session_id=task.get("session_id"),
        approval_id=approval["approval_id"],
        actor_type="human",
        actor_id=actor,
        payload={
            "approval_id": approval["approval_id"],
            "comment": comment_text,
            "previous_status": task.get("status"),
            "new_status": "approved",
        },
    )
    return approval


def reject_builder_task(
    task_id: str,
    *,
    actor_id: str,
    comment: str | None = None,
) -> dict[str, Any]:
    """Reject a builder task in awaiting_approval status."""
    task = _require_builder_task(task_id)
    validate_builder_transition(task.get("status") or "", "rejected")

    actor = (actor_id or "dashboard").strip() or "dashboard"
    comment_text = (comment or "").strip() or None
    approval = jcp.insert_builder_approval_decision(
        task_id,
        decision="rejected",
        actor_id=actor,
        comment=comment_text,
        risk_level=(task.get("risk_level") or "medium"),
        expected_task_status="awaiting_approval",
    )

    jcp.append_control_audit_event(
        "builder_task_rejected",
        task_id=task_id,
        session_id=task.get("session_id"),
        approval_id=approval["approval_id"],
        actor_type="human",
        actor_id=actor,
        payload={
            "approval_id": approval["approval_id"],
            "comment": comment_text,
            "previous_status": task.get("status"),
            "new_status": "rejected",
        },
    )
    return approval


def get_builder_timeline(task_id: str) -> list[dict[str, Any]] | None:
    """Merged audit, approval, and artifact timeline entries (newest first)."""
    context = jcp.get_builder_workflow_context(task_id)
    if context is None:
        return None
    return context["timeline_entries"]


def get_builder_task_detail(task_id: str) -> dict[str, Any] | None:
    """Builder task detail with workflow summary fields (bounded queries)."""
    context = jcp.get_builder_workflow_context(task_id)
    if context is None:
        return None

    task = context["task"]
    approvals = context["approvals"]
    timeline = context["timeline_entries"]
    latest_approval = approvals[0] if approvals else None

    detail = dict(task)
    detail["approvals_count"] = len(approvals)
    detail["latest_approval"] = latest_approval
    detail["timeline_count"] = len(timeline)
    return detail
