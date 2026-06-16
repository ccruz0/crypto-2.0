"""Database persistence for scheduled investigation queue and schedules."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_scheduled_investigations_tables

logger = logging.getLogger(__name__)


class ScheduledTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ACTIVE_STATUSES = frozenset({ScheduledTaskStatus.PENDING.value, ScheduledTaskStatus.RUNNING.value})


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text_val = str(value).strip()
    if not text_val:
        return None
    try:
        return datetime.fromisoformat(text_val.replace("Z", "+00:00"))
    except ValueError:
        return None


def _row_to_schedule(row: Any) -> dict[str, Any]:
    return {
        "schedule_id": row.schedule_id,
        "template_id": row.template_id,
        "title": row.title,
        "objective": row.objective,
        "category": row.category,
        "enabled": bool(row.enabled),
        "next_run_at": _iso(_parse_dt(row.next_run_at)),
        "last_run_at": _iso(_parse_dt(row.last_run_at)),
        "created_at": _iso(_parse_dt(row.created_at)),
        "updated_at": _iso(_parse_dt(row.updated_at)),
    }


def _row_to_task(row: Any) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "schedule_id": row.schedule_id,
        "template_id": row.template_id,
        "objective": row.objective,
        "status": row.status,
        "investigation_id": row.investigation_id,
        "result_summary": row.result_summary,
        "error_message": row.error_message,
        "scheduled_at": _iso(_parse_dt(row.scheduled_at)),
        "started_at": _iso(_parse_dt(row.started_at)),
        "completed_at": _iso(_parse_dt(row.completed_at)),
        "duration_ms": int(row.duration_ms or 0),
        "created_at": _iso(_parse_dt(row.created_at)),
        "updated_at": _iso(_parse_dt(row.updated_at)),
    }


def ensure_tables() -> bool:
    if engine is None:
        return False
    return ensure_jarvis_scheduled_investigations_tables(engine)


def upsert_schedule(
    *,
    schedule_id: str,
    template_id: str,
    title: str,
    objective: str,
    category: str,
    enabled: bool = True,
    next_run_at: datetime | None = None,
) -> dict[str, Any]:
    if not ensure_tables():
        raise RuntimeError("scheduled investigations tables unavailable")
    now = _now_utc()
    next_at = next_run_at or now
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_investigation_schedules (
                    schedule_id, template_id, title, objective, category,
                    enabled, next_run_at, created_at, updated_at
                ) VALUES (
                    :schedule_id, :template_id, :title, :objective, :category,
                    :enabled, :next_run_at, :created_at, :updated_at
                )
                ON CONFLICT (schedule_id) DO UPDATE SET
                    template_id = excluded.template_id,
                    title = excluded.title,
                    objective = excluded.objective,
                    category = excluded.category,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """
            ),
            {
                "schedule_id": schedule_id,
                "template_id": template_id,
                "title": title,
                "objective": objective,
                "category": category,
                "enabled": enabled,
                "next_run_at": next_at,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_investigation_schedules WHERE schedule_id = :schedule_id"),
            {"schedule_id": schedule_id},
        ).fetchone()
    return _row_to_schedule(row)


def list_schedules() -> list[dict[str, Any]]:
    if not ensure_tables():
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM jarvis_investigation_schedules ORDER BY title ASC")
        ).fetchall()
    return [_row_to_schedule(row) for row in rows]


def list_due_schedules(*, now: datetime | None = None) -> list[dict[str, Any]]:
    if not ensure_tables():
        return []
    at = now or _now_utc()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM jarvis_investigation_schedules
                WHERE enabled = :enabled AND next_run_at <= :now
                ORDER BY next_run_at ASC
                """
            ),
            {"enabled": True, "now": at},
        ).fetchall()
    return [_row_to_schedule(row) for row in rows]


def update_schedule_run_times(
    schedule_id: str,
    *,
    last_run_at: datetime,
    next_run_at: datetime,
) -> None:
    if not ensure_tables():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_investigation_schedules
                SET last_run_at = :last_run_at,
                    next_run_at = :next_run_at,
                    updated_at = :updated_at
                WHERE schedule_id = :schedule_id
                """
            ),
            {
                "schedule_id": schedule_id,
                "last_run_at": last_run_at,
                "next_run_at": next_run_at,
                "updated_at": _now_utc(),
            },
        )


def has_active_task_for_schedule(schedule_id: str) -> bool:
    if not ensure_tables():
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM jarvis_scheduled_investigation_tasks
                WHERE schedule_id = :schedule_id
                  AND status IN ('pending', 'running')
                LIMIT 1
                """
            ),
            {"schedule_id": schedule_id},
        ).fetchone()
    return row is not None


def create_task(
    *,
    schedule_id: str,
    template_id: str,
    objective: str,
    scheduled_at: datetime | None = None,
) -> dict[str, Any]:
    if not ensure_tables():
        raise RuntimeError("scheduled investigations tables unavailable")
    if has_active_task_for_schedule(schedule_id):
        raise ValueError(f"duplicate active task for schedule {schedule_id}")
    now = _now_utc()
    task_id = str(uuid.uuid4())
    at = scheduled_at or now
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_scheduled_investigation_tasks (
                    task_id, schedule_id, template_id, objective, status,
                    scheduled_at, created_at, updated_at
                ) VALUES (
                    :task_id, :schedule_id, :template_id, :objective, :status,
                    :scheduled_at, :created_at, :updated_at
                )
                """
            ),
            {
                "task_id": task_id,
                "schedule_id": schedule_id,
                "template_id": template_id,
                "objective": objective,
                "status": ScheduledTaskStatus.PENDING.value,
                "scheduled_at": at,
                "created_at": now,
                "updated_at": now,
            },
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_scheduled_investigation_tasks WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()
    return _row_to_task(row)


def claim_next_pending_task() -> dict[str, Any] | None:
    """Atomically claim the oldest pending task (single-runner semantics)."""
    if not ensure_tables():
        return None
    now = _now_utc()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT task_id FROM jarvis_scheduled_investigation_tasks
                WHERE status = 'pending'
                ORDER BY scheduled_at ASC, created_at ASC
                LIMIT 1
                """
            )
        ).fetchone()
        if row is None:
            return None
        task_id = row.task_id
        updated = conn.execute(
            text(
                """
                UPDATE jarvis_scheduled_investigation_tasks
                SET status = 'running',
                    started_at = :started_at,
                    updated_at = :updated_at
                WHERE task_id = :task_id AND status = 'pending'
                """
            ),
            {"task_id": task_id, "started_at": now, "updated_at": now},
        )
        if updated.rowcount != 1:
            return None
        claimed = conn.execute(
            text("SELECT * FROM jarvis_scheduled_investigation_tasks WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()
    return _row_to_task(claimed) if claimed else None


def complete_task(
    task_id: str,
    *,
    status: ScheduledTaskStatus,
    investigation_id: str | None = None,
    result_summary: str = "",
    error_message: str = "",
    duration_ms: int = 0,
) -> dict[str, Any] | None:
    if not ensure_tables():
        return None
    now = _now_utc()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_scheduled_investigation_tasks
                SET status = :status,
                    investigation_id = :investigation_id,
                    result_summary = :result_summary,
                    error_message = :error_message,
                    completed_at = :completed_at,
                    duration_ms = :duration_ms,
                    updated_at = :updated_at
                WHERE task_id = :task_id
                """
            ),
            {
                "task_id": task_id,
                "status": status.value,
                "investigation_id": investigation_id,
                "result_summary": result_summary[:4000],
                "error_message": error_message[:2000],
                "completed_at": now,
                "duration_ms": duration_ms,
                "updated_at": now,
            },
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_scheduled_investigation_tasks WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(*, limit: int = 50, schedule_id: str | None = None) -> list[dict[str, Any]]:
    if not ensure_tables():
        return []
    params: dict[str, Any] = {"limit": max(1, min(limit, 200))}
    where = ""
    if schedule_id:
        where = "WHERE schedule_id = :schedule_id"
        params["schedule_id"] = schedule_id
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT * FROM jarvis_scheduled_investigation_tasks
                {where}
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    return [_row_to_task(row) for row in rows]


def count_tasks_by_status_since(*, since: datetime) -> dict[str, int]:
    if not ensure_tables():
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT status, COUNT(*) AS cnt
                FROM jarvis_scheduled_investigation_tasks
                WHERE created_at >= :since
                GROUP BY status
                """
            ),
            {"since": since},
        ).fetchall()
    return {str(row.status): int(row.cnt) for row in rows}


def average_runtime_ms_since(*, since: datetime) -> float:
    if not ensure_tables():
        return 0.0
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT AVG(duration_ms) AS avg_ms
                FROM jarvis_scheduled_investigation_tasks
                WHERE created_at >= :since
                  AND status IN ('completed', 'failed')
                  AND duration_ms > 0
                """
            ),
            {"since": since},
        ).fetchone()
    if row is None or row.avg_ms is None:
        return 0.0
    return float(row.avg_ms)


def stale_running_tasks(*, older_than: datetime) -> list[dict[str, Any]]:
    """Find running tasks whose lease started before older_than (failover recovery)."""
    if not ensure_tables():
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM jarvis_scheduled_investigation_tasks
                WHERE status = 'running' AND started_at < :older_than
                ORDER BY started_at ASC
                """
            ),
            {"older_than": older_than},
        ).fetchall()
    return [_row_to_task(row) for row in rows]


def mark_task_failed(task_id: str, *, error_message: str) -> None:
    complete_task(
        task_id,
        status=ScheduledTaskStatus.FAILED,
        error_message=error_message,
        duration_ms=0,
    )
