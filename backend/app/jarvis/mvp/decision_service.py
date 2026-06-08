"""Orchestrate Jarvis decision record creation (human-controlled, no execution)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app.jarvis.mvp.decision_persistence import (
    get_decision,
    record_decision,
    update_decision_outcome,
)

logger = logging.getLogger(__name__)

DecisionType = Literal["approved", "rejected", "deferred"]
OutcomeType = Literal["unknown", "successful", "unsuccessful", "partial"]


def create_decision(
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    plan_id: str | None = None,
    decision: DecisionType,
    decision_reason: str = "",
    outcome: OutcomeType = "unknown",
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    """Record a human decision. Does not execute any remediation."""
    now = datetime.now(timezone.utc).isoformat()
    decision_id = record_decision(
        source_type=source_type,
        source_id=source_id,
        plan_id=plan_id,
        decision=decision,
        decision_reason=decision_reason,
        outcome=outcome,
        reviewed_at=now if outcome != "unknown" else None,
        reviewed_by=reviewed_by,
    )

    if plan_id and decision in ("approved", "rejected"):
        _sync_action_plan_status(plan_id=plan_id, decision=decision)

    stored = get_decision(decision_id)
    if stored is None:
        raise RuntimeError("Decision persistence failed")

    logger.info(
        "decision recorded decision_id=%s decision=%s source_type=%s plan_id=%s",
        decision_id,
        decision,
        source_type,
        plan_id,
    )
    return stored


def record_decision_outcome(
    *,
    decision_id: str,
    outcome: OutcomeType,
    reviewed_by: str | None = None,
) -> dict[str, Any]:
    """Update outcome on an existing decision after follow-up review."""
    now = datetime.now(timezone.utc).isoformat()
    updated = update_decision_outcome(
        decision_id=decision_id,
        outcome=outcome,
        reviewed_at=now,
        reviewed_by=reviewed_by,
    )
    if not updated:
        raise ValueError(f"Decision not found: {decision_id}")

    stored = get_decision(decision_id)
    if stored is None:
        raise RuntimeError("Decision retrieval failed after update")
    return stored


def _sync_action_plan_status(*, plan_id: str, decision: DecisionType) -> None:
    """Mirror human decision onto action plan status field (metadata only)."""
    try:
        from sqlalchemy import text

        from app.database import engine, ensure_jarvis_action_plans_table

        if engine is None or not ensure_jarvis_action_plans_table(engine):
            return

        status = "approved" if decision == "approved" else "rejected"
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE jarvis_action_plans SET status = :status WHERE plan_id = :plan_id"),
                {"status": status, "plan_id": plan_id},
            )
    except Exception as exc:
        logger.warning("decision action_plan status sync failed plan_id=%s: %s", plan_id, exc)
