"""PostgreSQL/SQLite persistence for Jarvis decision records."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import text

from app.database import engine, ensure_jarvis_decisions_table

logger = logging.getLogger(__name__)

DecisionType = Literal["approved", "rejected", "deferred"]
OutcomeType = Literal["unknown", "successful", "unsuccessful", "partial"]


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def record_decision(
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    plan_id: str | None = None,
    decision: DecisionType,
    decision_reason: str = "",
    outcome: OutcomeType = "unknown",
    reviewed_at: str | None = None,
    reviewed_by: str | None = None,
    decision_id: str | None = None,
) -> str:
    """Insert a decision record. Returns decision_id."""
    if engine is None or not ensure_jarvis_decisions_table(engine):
        raise RuntimeError("Database unavailable for Jarvis decision persistence")

    did = decision_id or str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_decisions (
                    decision_id, source_type, source_id, plan_id,
                    decision, decision_reason, outcome,
                    reviewed_at, reviewed_by
                ) VALUES (
                    :decision_id, :source_type, :source_id, :plan_id,
                    :decision, :decision_reason, :outcome,
                    :reviewed_at, :reviewed_by
                )
                """
            ),
            {
                "decision_id": did,
                "source_type": source_type,
                "source_id": source_id,
                "plan_id": plan_id,
                "decision": decision,
                "decision_reason": decision_reason or "",
                "outcome": outcome,
                "reviewed_at": reviewed_at,
                "reviewed_by": reviewed_by,
            },
        )
    return did


def update_decision_outcome(
    *,
    decision_id: str,
    outcome: OutcomeType,
    reviewed_at: str | None = None,
    reviewed_by: str | None = None,
) -> bool:
    """Update outcome on an existing decision record."""
    if engine is None or not ensure_jarvis_decisions_table(engine):
        return False

    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE jarvis_decisions
                SET outcome = :outcome,
                    reviewed_at = COALESCE(:reviewed_at, reviewed_at),
                    reviewed_by = COALESCE(:reviewed_by, reviewed_by)
                WHERE decision_id = :decision_id
                """
            ),
            {
                "decision_id": decision_id,
                "outcome": outcome,
                "reviewed_at": reviewed_at,
                "reviewed_by": reviewed_by,
            },
        )
    return result.rowcount > 0  # type: ignore[union-attr]


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "decision_id": mapping["decision_id"],
        "created_at": _isoformat(mapping.get("created_at")),
        "source_type": mapping.get("source_type"),
        "source_id": mapping.get("source_id"),
        "plan_id": mapping.get("plan_id"),
        "decision": mapping.get("decision") or "deferred",
        "decision_reason": mapping.get("decision_reason") or "",
        "outcome": mapping.get("outcome") or "unknown",
        "reviewed_at": _isoformat(mapping.get("reviewed_at")),
        "reviewed_by": mapping.get("reviewed_by"),
        "read_only": True,
        "execution_performed": False,
    }


def get_decision(decision_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_decisions_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_decisions WHERE decision_id = :decision_id"),
            {"decision_id": decision_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_decisions(*, limit: int = 50) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_decisions_table(engine):
        return []

    safe_limit = max(1, min(limit, 200))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT decision_id, created_at, source_type, source_id, plan_id,
                       decision, decision_reason, outcome, reviewed_at, reviewed_by
                FROM jarvis_decisions
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    return [_row_to_detail(row) for row in rows]


def list_all_decisions() -> list[dict[str, Any]]:
    """Load all decisions for analytics (capped at 500)."""
    return list_decisions(limit=500)
