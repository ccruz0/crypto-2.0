"""PostgreSQL/SQLite persistence for Jarvis LangGraph MVP task runs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_task_runs_table

logger = logging.getLogger(__name__)


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


def record_task_started(task_id: str, task: str, *, dry_run: bool) -> None:
    """Insert a running task row (completed_at remains null until completion)."""
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise RuntimeError("Database unavailable for Jarvis task persistence")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_task_runs (
                    task_id, task, status, risk_level, dry_run,
                    plan_json, tool_results_json, review_json,
                    estimated_cost_usd, final_answer, error, completed_at
                ) VALUES (
                    :task_id, :task, 'running', 'low', :dry_run,
                    :plan_json, :tool_results_json, :review_json,
                    0, '', NULL, NULL
                )
                """
            ),
            {
                "task_id": task_id,
                "task": task,
                "dry_run": dry_run,
                "plan_json": _json_dumps([]),
                "tool_results_json": _json_dumps([]),
                "review_json": _json_dumps({}),
            },
        )


def record_task_completed(task_id: str, result: dict[str, Any]) -> None:
    """Update a task row with final status and outputs."""
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise RuntimeError("Database unavailable for Jarvis task persistence")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_task_runs SET
                    status = :status,
                    risk_level = :risk_level,
                    plan_json = :plan_json,
                    tool_results_json = :tool_results_json,
                    review_json = :review_json,
                    estimated_cost_usd = :estimated_cost_usd,
                    final_answer = :final_answer,
                    error = :error,
                    completed_at = CURRENT_TIMESTAMP
                WHERE task_id = :task_id
                """
            ),
            {
                "task_id": task_id,
                "status": str(result.get("status") or "failed"),
                "risk_level": str(result.get("risk_level") or "low"),
                "plan_json": _json_dumps(result.get("plan") or []),
                "tool_results_json": _json_dumps(result.get("tool_results") or []),
                "review_json": _json_dumps(result.get("review") or {}),
                "estimated_cost_usd": float(result.get("estimated_cost_usd") or 0.0),
                "final_answer": str(result.get("final_answer") or ""),
                "error": result.get("error"),
            },
        )


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "task_id": mapping["task_id"],
        "task": mapping["task"],
        "status": mapping["status"],
        "risk_level": mapping["risk_level"],
        "dry_run": bool(mapping["dry_run"]),
        "plan": _json_loads(mapping.get("plan_json"), []),
        "tool_results": _json_loads(mapping.get("tool_results_json"), []),
        "review": _json_loads(mapping.get("review_json"), {}),
        "estimated_cost_usd": float(mapping.get("estimated_cost_usd") or 0.0),
        "final_answer": mapping.get("final_answer") or "",
        "error": mapping.get("error"),
        "created_at": _isoformat(mapping.get("created_at")),
        "completed_at": _isoformat(mapping.get("completed_at")),
    }


def get_task_run(task_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_task_runs WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_task_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    """Return completed task summaries, newest first."""
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT task_id, task, status, risk_level, estimated_cost_usd,
                       created_at, completed_at
                FROM jarvis_task_runs
                WHERE completed_at IS NOT NULL
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
                "task_id": mapping["task_id"],
                "task": mapping["task"],
                "status": mapping["status"],
                "risk_level": mapping["risk_level"],
                "estimated_cost_usd": float(mapping.get("estimated_cost_usd") or 0.0),
                "created_at": _isoformat(mapping.get("created_at")),
                "completed_at": _isoformat(mapping.get("completed_at")),
            }
        )
    return summaries
