"""PostgreSQL/SQLite persistence for Jarvis Action Planner runs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import text

from app.database import engine, ensure_jarvis_action_plans_table

logger = logging.getLogger(__name__)

PlanStatus = Literal["proposed", "approved", "rejected"]


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [])


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def record_action_plan(
    *,
    plan: dict[str, Any],
    status: PlanStatus = "proposed",
) -> str:
    """Insert an action plan row. Returns plan_id."""
    if engine is None or not ensure_jarvis_action_plans_table(engine):
        raise RuntimeError("Database unavailable for Jarvis action plan persistence")

    plan_id = plan["plan_id"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_action_plans (
                    plan_id, source_type, source_id, severity,
                    estimated_savings_usd, estimated_risk_reduction,
                    actions_json, status
                ) VALUES (
                    :plan_id, :source_type, :source_id, :severity,
                    :estimated_savings_usd, :estimated_risk_reduction,
                    :actions_json, :status
                )
                """
            ),
            {
                "plan_id": plan_id,
                "source_type": plan.get("source_type"),
                "source_id": plan.get("source_id"),
                "severity": plan.get("severity"),
                "estimated_savings_usd": float(plan.get("estimated_savings_usd") or 0.0),
                "estimated_risk_reduction": plan.get("estimated_risk_reduction") or "",
                "actions_json": _json_dumps(plan.get("actions") or []),
                "status": status,
            },
        )
    return plan_id


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    actions = _json_loads(mapping.get("actions_json"), [])
    return {
        "plan_id": mapping["plan_id"],
        "created_at": _isoformat(mapping.get("created_at")),
        "source_type": mapping.get("source_type"),
        "source_id": mapping.get("source_id"),
        "severity": mapping.get("severity") or "low",
        "estimated_savings_usd": float(mapping.get("estimated_savings_usd") or 0.0),
        "estimated_risk_reduction": mapping.get("estimated_risk_reduction") or "",
        "actions": actions,
        "status": mapping.get("status") or "proposed",
        "action_count": len(actions),
        "read_only": True,
        "execution_performed": False,
    }


def get_action_plan(plan_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_action_plans_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_action_plans WHERE plan_id = :plan_id"),
            {"plan_id": plan_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_action_plans(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_action_plans_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT plan_id, source_type, source_id, severity,
                       estimated_savings_usd, status, created_at
                FROM jarvis_action_plans
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    summaries: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        summaries.append(
            {
                "plan_id": mapping["plan_id"],
                "source_type": mapping.get("source_type"),
                "source_id": mapping.get("source_id"),
                "severity": mapping.get("severity") or "low",
                "estimated_savings_usd": float(mapping.get("estimated_savings_usd") or 0.0),
                "status": mapping.get("status") or "proposed",
                "created_at": _isoformat(mapping.get("created_at")),
            }
        )
    return summaries
