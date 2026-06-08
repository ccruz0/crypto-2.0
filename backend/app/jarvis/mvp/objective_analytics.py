"""Objective outcome analytics for decision intelligence integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.jarvis.mvp.objective_persistence import list_all_objectives


def get_objective_outcome_index() -> dict[str, dict[str, Any]]:
    """Index objectives by normalized title for outcome tracking."""
    from app.jarvis.mvp.decision_analytics import normalize_recommendation_key

    index: dict[str, dict[str, Any]] = {}
    for objective in list_all_objectives():
        title = str(objective.get("title") or "").strip()
        key = normalize_recommendation_key(title)
        if not key:
            continue
        entry = index.setdefault(
            key,
            {
                "label": title,
                "completed": 0,
                "cancelled": 0,
                "failed": 0,
                "active": 0,
                "total": 0,
            },
        )
        entry["total"] += 1
        status = str(objective.get("status") or "").lower()
        if status == "completed":
            entry["completed"] += 1
        elif status == "cancelled":
            entry["cancelled"] += 1
            entry["failed"] += 1
        elif status == "active":
            entry["active"] += 1
            if str(objective.get("health")) == "red" or objective.get("is_overdue"):
                entry["failed"] += 1
    return index


def get_objective_analytics() -> dict[str, Any]:
    """Compute objective intelligence metrics."""
    objectives = list_all_objectives()
    if not objectives:
        return {
            "total_objectives": 0,
            "completed_objectives": 0,
            "active_objectives": 0,
            "at_risk_objectives": 0,
            "objective_completion_rate": 0.0,
            "average_time_to_completion_days": None,
            "repeatedly_succeeding": [],
            "repeatedly_failing": [],
            "read_only": True,
        }

    completed = [o for o in objectives if str(o.get("status")) == "completed"]
    active = [o for o in objectives if str(o.get("status")) == "active"]
    at_risk = [
        o for o in objectives
        if str(o.get("alignment_status")) in ("At risk", "Needs attention")
        and str(o.get("status")) not in ("completed", "cancelled")
    ]

    terminal = [o for o in objectives if str(o.get("status")) in ("completed", "cancelled")]
    completion_rate = round(len(completed) / len(terminal) * 100, 1) if terminal else 0.0

    completion_days: list[int] = []
    for obj in completed:
        created = obj.get("created_at")
        updated = obj.get("updated_at")
        if not created or not updated:
            continue
        try:
            start = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            completion_days.append((end - start).days)
        except (TypeError, ValueError):
            continue

    avg_days = round(sum(completion_days) / len(completion_days), 1) if completion_days else None

    index = get_objective_outcome_index()
    repeatedly_succeeding = [
        e["label"]
        for e in index.values()
        if int(e.get("completed") or 0) >= 2
    ][:5]
    repeatedly_failing = [
        e["label"]
        for e in index.values()
        if int(e.get("failed") or 0) >= 2
    ][:5]

    return {
        "total_objectives": len(objectives),
        "completed_objectives": len(completed),
        "active_objectives": len(active),
        "at_risk_objectives": len(at_risk),
        "objective_completion_rate": completion_rate,
        "average_time_to_completion_days": avg_days,
        "repeatedly_succeeding": repeatedly_succeeding,
        "repeatedly_failing": repeatedly_failing,
        "read_only": True,
    }
