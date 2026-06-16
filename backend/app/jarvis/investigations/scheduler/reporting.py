"""Reporting aggregates for scheduled investigations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.jarvis.investigations.scheduler.persistence import (
    average_runtime_ms_since,
    count_tasks_by_status_since,
    list_schedules,
    list_tasks,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def build_daily_health_summary(*, hours: int = 24) -> dict[str, Any]:
    since = _now_utc() - timedelta(hours=max(1, hours))
    counts = count_tasks_by_status_since(since=since)
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    cancelled = counts.get("cancelled", 0)
    pending = counts.get("pending", 0)
    running = counts.get("running", 0)
    terminal = completed + failed
    success_rate = (completed / terminal * 100.0) if terminal else 0.0
    failure_rate = (failed / terminal * 100.0) if terminal else 0.0
    avg_runtime_ms = average_runtime_ms_since(since=since)

    schedules = list_schedules()
    recent_tasks = list_tasks(limit=20)

    return {
        "period_hours": hours,
        "since": since.isoformat(),
        "generated_at": _now_utc().isoformat(),
        "task_counts": {
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "pending": pending,
            "running": running,
            "total": sum(counts.values()),
        },
        "success_rate_pct": round(success_rate, 2),
        "failure_rate_pct": round(failure_rate, 2),
        "average_runtime_ms": round(avg_runtime_ms, 2),
        "schedules": schedules,
        "recent_tasks": recent_tasks,
    }
