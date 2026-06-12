"""PostgreSQL/SQLite persistence for Jarvis Phase 3 task execution."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_task_approvals_table, ensure_jarvis_task_runs_table
from app.jarvis.execution.lifecycle import InvalidTaskTransitionError, TaskLifecycleState, validate_transition

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


def create_execution_task(
    *,
    task_id: str,
    objective: str,
    priority: str = "normal",
    dry_run: bool = True,
    approval_required: bool = False,
    approval_status: str = "not_required",
) -> None:
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise RuntimeError("Database unavailable for Jarvis task persistence")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_task_runs (
                    task_id, task, objective, status, risk_level, dry_run, priority,
                    plan_json, artifacts_json, tool_results_json, review_json,
                    approval_required, approval_status,
                    estimated_cost_usd, actual_cost_usd,
                    final_answer, error, started_at, completed_at
                ) VALUES (
                    :task_id, :task, :objective, :status, 'low', :dry_run, :priority,
                    :plan_json, :artifacts_json, :tool_results_json, :review_json,
                    :approval_required, :approval_status,
                    0, 0,
                    '', NULL, NULL, NULL
                )
                """
            ),
            {
                "task_id": task_id,
                "task": objective,
                "objective": objective,
                "status": TaskLifecycleState.QUEUED.value,
                "dry_run": dry_run,
                "priority": priority,
                "plan_json": _json_dumps({}),
                "artifacts_json": _json_dumps([]),
                "tool_results_json": _json_dumps([]),
                "review_json": _json_dumps({}),
                "approval_required": approval_required,
                "approval_status": approval_status,
            },
        )


def transition_task_status(task_id: str, target_status: str | TaskLifecycleState, **fields: Any) -> None:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError(f"task not found: {task_id}")
    current = row["status"]
    validate_transition(current, target_status)
    _update_task(task_id, status=str(getattr(target_status, "value", target_status)), **fields)


def _update_task(task_id: str, **fields: Any) -> None:
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise RuntimeError("Database unavailable")

    allowed = {
        "status",
        "plan_json",
        "artifacts_json",
        "tool_results_json",
        "review_json",
        "approval_required",
        "approval_status",
        "estimated_cost_usd",
        "actual_cost_usd",
        "final_answer",
        "error",
        "current_step",
        "started_at",
        "completed_at",
        "risk_level",
    }
    sets: list[str] = []
    params: dict[str, Any] = {"task_id": task_id}
    for key, value in fields.items():
        if key not in allowed:
            continue
        col = key
        if key.endswith("_json") and not isinstance(value, str):
            value = _json_dumps(value)
        sets.append(f"{col} = :{key}")
        params[key] = value
    if not sets:
        return
    sql = f"UPDATE jarvis_task_runs SET {', '.join(sets)} WHERE task_id = :task_id"
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def record_approval(
    *,
    task_id: str,
    decision: str,
    actor_id: str = "dashboard",
    comment: str = "",
) -> dict[str, Any]:
    if engine is None or not ensure_jarvis_task_approvals_table(engine):
        raise RuntimeError("Database unavailable for approvals")

    approval_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_task_approvals (
                    approval_id, task_id, decision, actor_id, comment, created_at
                ) VALUES (
                    :approval_id, :task_id, :decision, :actor_id, :comment, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "approval_id": approval_id,
                "task_id": task_id,
                "decision": decision,
                "actor_id": actor_id,
                "comment": comment[:2000],
            },
        )
    return {
        "approval_id": approval_id,
        "task_id": task_id,
        "decision": decision,
        "actor_id": actor_id,
        "comment": comment,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def list_approvals(task_id: str) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_task_approvals_table(engine):
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT approval_id, task_id, decision, actor_id, comment, created_at
                FROM jarvis_task_approvals
                WHERE task_id = :task_id
                ORDER BY created_at ASC
                """
            ),
            {"task_id": task_id},
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        m = row._mapping if hasattr(row, "_mapping") else row
        out.append(
            {
                "approval_id": m["approval_id"],
                "task_id": m["task_id"],
                "decision": m["decision"],
                "actor_id": m["actor_id"],
                "comment": m.get("comment") or "",
                "created_at": _isoformat(m.get("created_at")),
            }
        )
    return out


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    plan_raw = _json_loads(mapping.get("plan_json"), {})
    if isinstance(plan_raw, list):
        plan = {"steps": plan_raw, "total_estimated_cost_usd": 0.0, "overall_safety": "safe_auto"}
    else:
        plan = plan_raw if isinstance(plan_raw, dict) else {}
    return {
        "task_id": mapping["task_id"],
        "objective": mapping.get("objective") or mapping.get("task") or "",
        "task": mapping.get("task") or "",
        "status": mapping["status"],
        "priority": mapping.get("priority") or "normal",
        "risk_level": mapping.get("risk_level") or "low",
        "dry_run": bool(mapping.get("dry_run")),
        "plan": plan,
        "artifacts": _json_loads(mapping.get("artifacts_json"), []),
        "tool_results": _json_loads(mapping.get("tool_results_json"), []),
        "review": _json_loads(mapping.get("review_json"), {}),
        "approval_required": bool(mapping.get("approval_required")),
        "approval_status": mapping.get("approval_status") or "not_required",
        "estimated_cost_usd": float(mapping.get("estimated_cost_usd") or 0.0),
        "actual_cost_usd": float(mapping.get("actual_cost_usd") or 0.0),
        "final_answer": mapping.get("final_answer") or "",
        "error": mapping.get("error"),
        "current_step": mapping.get("current_step"),
        "created_at": _isoformat(mapping.get("created_at")),
        "started_at": _isoformat(mapping.get("started_at")),
        "completed_at": _isoformat(mapping.get("completed_at")),
    }


def get_execution_task(task_id: str) -> dict[str, Any] | None:
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


def list_execution_tasks(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_task_runs_table(engine):
        return []
    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT task_id, objective, task, status, priority, approval_status,
                       estimated_cost_usd, actual_cost_usd, created_at, completed_at
                FROM jarvis_task_runs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()
    summaries: list[dict[str, Any]] = []
    for row in rows:
        m = row._mapping if hasattr(row, "_mapping") else row
        summaries.append(
            {
                "task_id": m["task_id"],
                "objective": m.get("objective") or m.get("task") or "",
                "status": m["status"],
                "priority": m.get("priority") or "normal",
                "approval_status": m.get("approval_status") or "not_required",
                "estimated_cost_usd": float(m.get("estimated_cost_usd") or 0.0),
                "actual_cost_usd": float(m.get("actual_cost_usd") or 0.0),
                "created_at": _isoformat(m.get("created_at")),
                "completed_at": _isoformat(m.get("completed_at")),
            }
        )
    return summaries


__all__ = [
    "InvalidTaskTransitionError",
    "create_execution_task",
    "transition_task_status",
    "get_execution_task",
    "list_execution_tasks",
    "record_approval",
    "list_approvals",
    "_update_task",
]
