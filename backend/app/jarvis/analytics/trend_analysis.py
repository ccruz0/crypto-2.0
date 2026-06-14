"""Trend analysis for Jarvis investigation quality analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.jarvis.analytics.aggregation import (
    _TERMINAL_STATUSES,
    aggregate_investigation_metrics,
    compute_quality_score,
    is_false_positive,
    is_resolved_investigation,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _day_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date().isoformat()


def build_daily_investigation_trends(
    rows: list[dict[str, Any]],
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return daily investigation counts and outcome rates."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        key = _day_key(row.get("created_at"))
        if not key:
            continue
        if datetime.fromisoformat(key).date() < cutoff:
            continue
        buckets[key].append(row)

    trends: list[dict[str, Any]] = []
    for offset in range(days):
        day = (datetime.now(timezone.utc).date() - timedelta(days=days - 1 - offset)).isoformat()
        day_rows = buckets.get(day, [])
        metrics = aggregate_investigation_metrics(day_rows)
        trends.append(
            {
                "date": day,
                "total": metrics["total_investigations"],
                "completed": metrics["completed"],
                "failed": metrics["failed"] + metrics["partial_failure"],
                "insufficient_evidence": metrics["insufficient_evidence"],
                "resolved": metrics["resolved"],
                "false_positives": metrics["false_positives"],
                "success_rate_pct": metrics["success_rate_pct"],
            }
        )
    return trends


def build_quality_score_trends(
    rows: list[dict[str, Any]],
    tool_error_count: int,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        key = _day_key(row.get("created_at"))
        if not key:
            continue
        if datetime.fromisoformat(key).date() < cutoff:
            continue
        buckets[key].append(row)

    per_day_errors = max(1, tool_error_count // max(len(rows), 1)) if rows else 0
    trends: list[dict[str, Any]] = []
    for offset in range(days):
        day = (datetime.now(timezone.utc).date() - timedelta(days=days - 1 - offset)).isoformat()
        day_rows = buckets.get(day, [])
        score = compute_quality_score(day_rows, tool_errors=per_day_errors if day_rows else 0)
        trends.append({"date": day, "quality_score": score})
    return trends


def compute_period_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    terminal = [r for r in rows if r.get("status") in _TERMINAL_STATUSES]
    if not terminal:
        return {
            "completion_rate_pct": 0.0,
            "resolution_rate_pct": 0.0,
            "false_positive_rate_pct": 0.0,
        }
    completed = sum(1 for r in terminal if r.get("status") == InvestigationStatus.COMPLETED.value)
    resolved = sum(1 for r in terminal if is_resolved_investigation(r))
    false_pos = sum(1 for r in terminal if is_false_positive(r))
    total = len(terminal)
    return {
        "completion_rate_pct": round(completed / total * 100, 1),
        "resolution_rate_pct": round(resolved / total * 100, 1),
        "false_positive_rate_pct": round(false_pos / total * 100, 1),
    }
