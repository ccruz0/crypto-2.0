"""
Centralized task status transitions with invariant enforcement and structured logging.

CRITICAL INVARIANT: A task MUST NOT transition to "needs-revision" unless at least one of:
- revision_reason
- verify_summary
- missing_inputs
- decision_required

If invariant is violated: log error, fallback to ready-for-investigation (retryable) or
blocked (not retryable). Never allow ambiguous needs-revision.

Every automatic transition writes structured activity log:
- from_status, to_status, reason, retryable, user_action_required
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Keys that justify a needs-revision transition (at least one required)
NEEDS_REVISION_REQUIRED_KEYS = ("revision_reason", "verify_summary", "missing_inputs", "decision_required")


def _has_valid_needs_revision_metadata(metadata: dict | None) -> bool:
    """True if metadata contains at least one of the required keys with non-empty value."""
    if not metadata or not isinstance(metadata, dict):
        return False
    for key in NEEDS_REVISION_REQUIRED_KEYS:
        val = metadata.get(key)
        if val is not None and str(val).strip():
            return True
    return False


def transition_task_status(
    task_id: str,
    new_status: str,
    *,
    from_status: str | None = None,
    task_title: str | None = None,
    reason: str | None = None,
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    append_comment: str | None = None,
    needs_revision_metadata: dict | None = None,
) -> bool:
    """
    Centralized status transition with invariant enforcement and structured logging.

    For needs-revision: requires needs_revision_metadata with at least one of
    revision_reason, verify_summary, missing_inputs, decision_required.
    If missing: logs invalid_needs_revision_transition, fallbacks to ready-for-investigation
    (retryable=True) or blocked (retryable=False), returns False.

    Always writes structured activity log for automatic transitions.
    """
    task_id = (task_id or "").strip()
    new_status = (new_status or "").strip().lower()
    if not task_id:
        logger.warning("transition_task_status: empty task_id")
        return False

    # Invariant: needs-revision requires explicit metadata
    if new_status == "needs-revision":
        if not _has_valid_needs_revision_metadata(needs_revision_metadata):
            logger.error(
                "invalid_needs_revision_transition task_id=%s from=%s missing required metadata (revision_reason/verify_summary/missing_inputs/decision_required)",
                task_id[:12],
                from_status or "?",
            )
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "invalid_needs_revision_transition",
                    task_id=task_id,
                    task_title=(task_title or "")[:200],
                    details={
                        "from_status": from_status,
                        "attempted_status": "needs-revision",
                        "fallback_reason": "missing_required_metadata",
                        "retryable": retryable if retryable is not None else True,
                    },
                )
            except Exception as e:
                logger.debug("transition_task_status: log_agent_event failed %s", e)

            # Fallback
            fallback_status = "ready-for-investigation" if (retryable is None or retryable) else "blocked"
            try:
                from app.services.notion_tasks import update_notion_task_status
                ok = update_notion_task_status(
                    task_id,
                    fallback_status,
                    append_comment=(
                        f"Invalid needs-revision attempt (missing metadata). Fallback to {fallback_status}. "
                        "Original reason: " + (reason or "unknown")[:200]
                    ),
                    allow_status_regression=True,
                )
                if ok:
                    _log_transition(
                        task_id, from_status or "?", fallback_status,
                        reason=(reason or "invalid_needs_revision_fallback"),
                        retryable=True,
                        user_action_required=False,
                        task_title=task_title,
                    )
                return False
            except Exception as e:
                logger.warning("transition_task_status: fallback failed task_id=%s %s", task_id[:12], e)
                return False

    # Proceed with normal update
    try:
        from app.services.notion_tasks import update_notion_task_status
        kwargs: dict[str, Any] = {"append_comment": append_comment}
        if new_status == "needs-revision" and needs_revision_metadata:
            kwargs["needs_revision_metadata"] = needs_revision_metadata
        ok = update_notion_task_status(task_id, new_status, **kwargs)
        if ok:
            _log_transition(
                task_id, from_status or "?", new_status,
                reason=reason,
                retryable=retryable,
                user_action_required=user_action_required,
                task_title=task_title,
            )
        return ok
    except Exception as e:
        logger.warning("transition_task_status: update failed task_id=%s %s", task_id[:12], e)
        return False


def _log_transition(
    task_id: str,
    from_status: str,
    to_status: str,
    *,
    reason: str | None = None,
    retryable: bool | None = None,
    user_action_required: bool | None = None,
    task_title: str | None = None,
) -> None:
    """Write structured activity log for status transition."""
    try:
        from app.services.agent_activity_log import log_agent_event
        details: dict[str, Any] = {
            "from_status": from_status,
            "to_status": to_status,
            "reason": (reason or "")[:300],
        }
        if retryable is not None:
            details["retryable"] = retryable
        if user_action_required is not None:
            details["user_action_required"] = user_action_required
        log_agent_event(
            "auto_transition",
            task_id=task_id,
            task_title=(task_title or "")[:200],
            details=details,
        )
    except Exception as e:
        logger.debug("transition_task_status: _log_transition failed %s", e)


def safe_transition_to_needs_revision(
    task_id: str,
    *,
    revision_reason: str | None = None,
    verify_summary: str | None = None,
    missing_inputs: str | None = None,
    decision_required: str | None = None,
    from_status: str | None = None,
    task_title: str | None = None,
    append_comment: str | None = None,
) -> bool:
    """
    Safe transition to needs-revision. Requires at least one of the four metadata fields.
    Use this instead of update_notion_task_status when moving to needs-revision.
    """
    metadata: dict[str, str] = {}
    if revision_reason:
        metadata["revision_reason"] = str(revision_reason)[:500]
    if verify_summary:
        metadata["verify_summary"] = str(verify_summary)[:500]
    if missing_inputs:
        metadata["missing_inputs"] = str(missing_inputs)[:500]
    if decision_required:
        metadata["decision_required"] = str(decision_required)[:500]

    if not metadata:
        logger.error(
            "safe_transition_to_needs_revision: no metadata provided task_id=%s",
            (task_id or "")[:12],
        )
        return False

    reason = metadata.get("revision_reason") or metadata.get("verify_summary") or list(metadata.values())[0]
    return transition_task_status(
        task_id,
        "needs-revision",
        from_status=from_status or "ready-for-patch",
        task_title=task_title,
        reason=reason,
        retryable=False,  # needs-revision implies user must act
        user_action_required=True,
        append_comment=append_comment,
        needs_revision_metadata=metadata,
    )
