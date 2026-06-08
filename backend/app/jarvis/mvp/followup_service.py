"""Orchestration for Jarvis follow-up generation and alerts."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.mvp.followup_agent import detect_followups
from app.jarvis.mvp.followup_persistence import (
    get_followup,
    get_followup_summary,
    list_followups,
    update_followup,
)
from app.jarvis.mvp.telegram_followup_alerts import send_followup_daily_alert

logger = logging.getLogger(__name__)


def generate_followups(*, send_telegram: bool = True) -> dict[str, Any]:
    """
    Run follow-up detection, optionally send Telegram summary for high/critical items.
    """
    result = detect_followups()
    summary = get_followup_summary()
    open_items = list_followups(limit=500, status="open")

    telegram_sent = False
    if send_telegram and (summary.get("critical_followups") or summary.get("high_followups")):
        telegram_sent = send_followup_daily_alert(summary=summary, followups=open_items)

    return {
        **result,
        "summary": summary,
        "telegram_sent": telegram_sent,
        "read_only": True,
        "execution_performed": False,
    }


def update_followup_record(
    *,
    followup_id: str,
    status: str | None = None,
    severity: str | None = None,
    assigned_to: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Update a follow-up and return the stored record."""
    ok = update_followup(
        followup_id=followup_id,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        assigned_to=assigned_to,
        description=description,
    )
    if not ok:
        raise ValueError(f"followup not found: {followup_id}")
    stored = get_followup(followup_id)
    if stored is None:
        raise ValueError(f"followup not found: {followup_id}")
    return stored


def seed_sample_followup_data() -> dict[str, Any]:
    """
    Create sample entities that trigger follow-up rules (for validation).
    Returns IDs of seeded records.
    """
    from datetime import datetime, timedelta, timezone

    from app.jarvis.mvp.action_plan_persistence import record_action_plan
    from app.jarvis.mvp.decision_persistence import record_decision
    from app.jarvis.mvp.initiative_persistence import record_initiative

    today = datetime.now(timezone.utc).date()
    overdue_date = (today - timedelta(days=11)).isoformat()
    old_plan_created = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    old_decision_reviewed = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()

    overdue_id = record_initiative(
        title="Portfolio reconciliation",
        status="active",
        priority="high",
        target_date=overdue_date,
        owner="Carlos",
    )

    blocked_id = record_initiative(
        title="Security group remediation",
        status="blocked",
        priority="critical",
        blocked_reason="Awaiting security review",
        owner="Carlos",
    )

    plan_id = "42f2d87b-sample-plan-0001"
    record_action_plan(
        plan={
            "plan_id": plan_id,
            "source_type": "aws_audit",
            "source_id": "sample-audit",
            "severity": "high",
            "estimated_savings_usd": 50.0,
            "estimated_risk_reduction": "medium",
            "actions": [{"title": "Review SG rules", "description": "Manual review"}],
        },
        status="proposed",
    )

    from sqlalchemy import text

    from app.database import engine

    if engine is not None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE jarvis_action_plans SET created_at = :created_at WHERE plan_id = :plan_id"
                ),
                {"created_at": old_plan_created, "plan_id": plan_id},
            )

    decision_id = record_decision(
        decision_id="dec-sample-unknown-outcome",
        source_type="action_plan",
        source_id=plan_id,
        plan_id=plan_id,
        decision="approved",
        decision_reason="Approved for manual remediation",
        outcome="unknown",
        reviewed_at=old_decision_reviewed,
        reviewed_by="Carlos",
    )

    return {
        "overdue_initiative_id": overdue_id,
        "blocked_initiative_id": blocked_id,
        "proposed_plan_id": plan_id,
        "approved_decision_id": decision_id,
        "read_only": True,
        "execution_performed": False,
    }
