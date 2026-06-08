"""PostgreSQL/SQLite persistence for Jarvis follow-up reminders."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text

from app.database import engine, ensure_jarvis_followups_table

logger = logging.getLogger(__name__)

FollowupStatus = Literal["open", "acknowledged", "resolved", "dismissed"]
FollowupSeverity = Literal["low", "medium", "high", "critical"]

VALID_STATUSES = frozenset({"open", "acknowledged", "resolved", "dismissed"})
VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_iso(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    detail = {
        "followup_id": mapping["followup_id"],
        "created_at": _isoformat(mapping.get("created_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
        "source_type": mapping.get("source_type") or "",
        "source_id": mapping.get("source_id"),
        "title": mapping.get("title") or "",
        "description": mapping.get("description") or "",
        "severity": mapping.get("severity") or "medium",
        "status": mapping.get("status") or "open",
        "due_date": _isoformat(mapping.get("due_date")),
        "assigned_to": mapping.get("assigned_to"),
        "reminder_count": int(mapping.get("reminder_count") or 0),
        "last_reminded_at": _isoformat(mapping.get("last_reminded_at")),
        "read_only": True,
        "execution_performed": False,
    }
    detail["is_overdue"] = _is_overdue(detail)
    return detail


def _is_overdue(followup: dict[str, Any]) -> bool:
    if str(followup.get("status")) != "open":
        return False
    due = followup.get("due_date")
    if not due:
        return False
    try:
        due_date = date.fromisoformat(str(due)[:10])
    except ValueError:
        return False
    return due_date < datetime.now(timezone.utc).date()


def find_open_followup(
    *,
    source_type: str,
    source_id: str | None,
    title: str,
) -> dict[str, Any] | None:
    """Find an existing open follow-up for deduplication."""
    if engine is None or not ensure_jarvis_followups_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT * FROM jarvis_followups
                WHERE status = 'open'
                  AND source_type = :source_type
                  AND title = :title
                  AND COALESCE(source_id, '') = COALESCE(:source_id, '')
                LIMIT 1
                """
            ),
            {
                "source_type": source_type,
                "source_id": source_id,
                "title": title,
            },
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def upsert_followup(
    *,
    source_type: str,
    source_id: str | None,
    title: str,
    description: str = "",
    severity: FollowupSeverity = "medium",
    due_date: str | None = None,
    assigned_to: str | None = None,
    followup_id: str | None = None,
) -> str:
    """
    Insert a new follow-up or bump reminder_count on an existing open match.

    Deduplication key: source_type + source_id + title (open status only).
    """
    if engine is None or not ensure_jarvis_followups_table(engine):
        raise RuntimeError("Database unavailable for Jarvis follow-up persistence")

    existing = find_open_followup(source_type=source_type, source_id=source_id, title=title)
    now = datetime.now(timezone.utc).isoformat()
    safe_severity = severity if severity in VALID_SEVERITIES else "medium"

    if existing:
        fid = existing["followup_id"]
        new_count = int(existing.get("reminder_count") or 0) + 1
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE jarvis_followups
                    SET updated_at = :updated_at,
                        reminder_count = :reminder_count,
                        last_reminded_at = :last_reminded_at,
                        severity = :severity,
                        description = :description,
                        due_date = COALESCE(:due_date, due_date),
                        assigned_to = COALESCE(:assigned_to, assigned_to)
                    WHERE followup_id = :followup_id
                    """
                ),
                {
                    "followup_id": fid,
                    "updated_at": now,
                    "reminder_count": new_count,
                    "last_reminded_at": now,
                    "severity": safe_severity,
                    "description": description or existing.get("description") or "",
                    "due_date": due_date,
                    "assigned_to": assigned_to,
                },
            )
        return fid

    fid = followup_id or str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_followups (
                    followup_id, source_type, source_id, title, description,
                    severity, status, due_date, assigned_to,
                    reminder_count, last_reminded_at
                ) VALUES (
                    :followup_id, :source_type, :source_id, :title, :description,
                    :severity, 'open', :due_date, :assigned_to,
                    1, :last_reminded_at
                )
                """
            ),
            {
                "followup_id": fid,
                "source_type": source_type,
                "source_id": source_id,
                "title": title,
                "description": description or "",
                "severity": safe_severity,
                "due_date": due_date,
                "assigned_to": assigned_to,
                "last_reminded_at": now,
            },
        )
    return fid


def update_followup(
    *,
    followup_id: str,
    status: FollowupStatus | None = None,
    severity: FollowupSeverity | None = None,
    assigned_to: str | None = None,
    description: str | None = None,
) -> bool:
    """Update follow-up status or metadata (human-controlled)."""
    if engine is None or not ensure_jarvis_followups_table(engine):
        return False

    existing = get_followup(followup_id)
    if existing is None:
        return False

    fields: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if status is not None and status in VALID_STATUSES:
        fields["status"] = status
    if severity is not None and severity in VALID_SEVERITIES:
        fields["severity"] = severity
    if assigned_to is not None:
        fields["assigned_to"] = assigned_to
    if description is not None:
        fields["description"] = description

    if len(fields) <= 1:
        return True

    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["followup_id"] = followup_id

    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE jarvis_followups SET {set_clause} WHERE followup_id = :followup_id"),
            params,
        )
    return result.rowcount > 0  # type: ignore[union-attr]


def get_followup(followup_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_followups_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_followups WHERE followup_id = :followup_id"),
            {"followup_id": followup_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_followups(
    *,
    limit: int = 50,
    status: str | None = None,
    severity: str | None = None,
) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_followups_table(engine):
        return []

    safe_limit = max(1, min(limit, 200))
    query = """
        SELECT followup_id, created_at, updated_at, source_type, source_id,
               title, description, severity, status, due_date, assigned_to,
               reminder_count, last_reminded_at
        FROM jarvis_followups
    """
    params: dict[str, Any] = {"limit": safe_limit}
    clauses: list[str] = []
    if status and status in VALID_STATUSES:
        clauses.append("status = :status")
        params["status"] = status
    if severity and severity in VALID_SEVERITIES:
        clauses.append("severity = :severity")
        params["severity"] = severity
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY updated_at DESC LIMIT :limit"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [_row_to_detail(row) for row in rows]


def list_open_followups() -> list[dict[str, Any]]:
    """All open follow-ups for agent and dashboard summaries."""
    return list_followups(limit=500, status="open")


def get_followup_summary() -> dict[str, Any]:
    """Aggregate follow-up counts for executive dashboard."""
    if engine is None or not ensure_jarvis_followups_table(engine):
        return {
            "open_followups": 0,
            "critical_followups": 0,
            "high_followups": 0,
            "overdue_followups": 0,
            "acknowledged_followups": 0,
            "resolved_this_week": 0,
        }

    today = datetime.now(timezone.utc).date()
    week_start = datetime.now(timezone.utc) - timedelta(days=7)

    open_items = list_open_followups()
    acknowledged = list_followups(limit=500, status="acknowledged")

    overdue = sum(1 for f in open_items if _is_overdue(f))
    critical = sum(1 for f in open_items if str(f.get("severity")) == "critical")
    high = sum(1 for f in open_items if str(f.get("severity")) == "high")

    resolved_this_week = 0
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT updated_at FROM jarvis_followups
                WHERE status = 'resolved'
                ORDER BY updated_at DESC
                LIMIT 200
                """
            ),
        ).fetchall()
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        updated = _parse_iso(mapping.get("updated_at"))
        if updated and updated >= week_start:
            resolved_this_week += 1

    return {
        "open_followups": len(open_items),
        "critical_followups": critical,
        "high_followups": high,
        "overdue_followups": overdue,
        "acknowledged_followups": len(acknowledged),
        "resolved_this_week": resolved_this_week,
    }


def get_followup_review(*, followups: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build follow-up review section for Chief of Staff reports."""
    items = followups if followups is not None else list_open_followups()
    summary = get_followup_summary()

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_items = sorted(
        items,
        key=lambda f: (
            severity_order.get(str(f.get("severity") or "medium"), 2),
            -int(f.get("reminder_count") or 0),
        ),
    )

    top_items = [
        {
            "followup_id": f["followup_id"],
            "title": f["title"],
            "severity": f.get("severity"),
            "source_type": f.get("source_type"),
            "source_id": f.get("source_id"),
            "reminder_count": f.get("reminder_count"),
            "is_overdue": f.get("is_overdue"),
        }
        for f in sorted_items[:10]
    ]

    return {
        "summary": summary,
        "top_followups": top_items,
        "has_high_severity": any(
            str(f.get("severity")) in ("high", "critical") for f in items
        ),
    }
