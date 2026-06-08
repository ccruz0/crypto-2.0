"""Orchestrate Action Planner generation, persistence, and alerts."""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.jarvis.mvp.action_plan_persistence import get_action_plan, record_action_plan
from app.jarvis.mvp.action_planner import generate_action_plan
from app.jarvis.mvp.telegram_action_plan_alerts import send_action_plan_alert

logger = logging.getLogger(__name__)

SourceType = Literal["aws_audit", "crypto_audit", "executive_dashboard"]


def create_action_plan_from_audit(
    *,
    source_type: SourceType,
    source_id: str,
) -> dict[str, Any]:
    """
    Generate, persist, and optionally alert on a new action plan.
    Does not execute any remediation.
    """
    plan = generate_action_plan(source_type=source_type, source_id=source_id)
    record_action_plan(plan=plan, status="proposed")
    send_action_plan_alert(plan)

    stored = get_action_plan(plan["plan_id"])
    if stored is None:
        raise RuntimeError("Action plan persistence failed")

    logger.info(
        "action_plan created plan_id=%s source_type=%s source_id=%s severity=%s actions=%d",
        stored["plan_id"],
        source_type,
        source_id,
        stored.get("severity"),
        len(stored.get("actions") or []),
    )
    return stored
