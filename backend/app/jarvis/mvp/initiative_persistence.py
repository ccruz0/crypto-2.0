"""PostgreSQL/SQLite persistence for Jarvis initiatives (Operating System layer)."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from sqlalchemy import text

from app.database import engine, ensure_jarvis_initiatives_table

logger = logging.getLogger(__name__)

InitiativeStatus = Literal["planned", "active", "blocked", "completed", "cancelled"]
InitiativeHealth = Literal["green", "yellow", "red"]
InitiativePriority = Literal["critical", "high", "medium", "low"]

STALE_DAYS = 14
VALID_STATUSES = frozenset({"planned", "active", "blocked", "completed", "cancelled"})
VALID_PRIORITIES = frozenset({"critical", "high", "medium", "low"})
VALID_SOURCE_TYPES = frozenset({
    "manual",
    "aws_audit",
    "crypto_audit",
    "action_plan",
    "decision",
    "executive_report",
    "objective",
})


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


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _days_since(value: str | datetime | None) -> int | None:
    dt = value if isinstance(value, datetime) else _parse_iso(value)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def is_initiative_overdue(initiative: dict[str, Any]) -> bool:
    """True when target_date has passed and initiative is still open."""
    status = str(initiative.get("status") or "").lower()
    if status in ("completed", "cancelled"):
        return False
    target = initiative.get("target_date")
    if not target:
        return False
    try:
        if isinstance(target, str):
            target_date = date.fromisoformat(target[:10])
        elif isinstance(target, date):
            target_date = target
        else:
            return False
    except ValueError:
        return False
    return target_date < datetime.now(timezone.utc).date()


def is_initiative_stalled(initiative: dict[str, Any]) -> bool:
    """Active initiative with no update in 14+ days."""
    status = str(initiative.get("status") or "").lower()
    if status != "active":
        return False
    days = _days_since(initiative.get("updated_at"))
    return days is not None and days >= STALE_DAYS


def calculate_initiative_health(initiative: dict[str, Any]) -> InitiativeHealth:
    """
    Health rules:
    - Red: blocked or overdue
    - Yellow: no update in 14+ days
    - Green: progress moving and no blockers
    """
    status = str(initiative.get("status") or "").lower()
    if status == "blocked":
        return "red"
    if is_initiative_overdue(initiative):
        return "red"
    days = _days_since(initiative.get("updated_at"))
    if days is not None and days >= STALE_DAYS:
        return "yellow"
    if status in ("completed", "cancelled"):
        return "green"
    return "green"


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    detail = {
        "initiative_id": mapping["initiative_id"],
        "created_at": _isoformat(mapping.get("created_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
        "title": mapping.get("title") or "",
        "description": mapping.get("description") or "",
        "status": mapping.get("status") or "planned",
        "priority": mapping.get("priority") or "medium",
        "owner": mapping.get("owner"),
        "target_date": _isoformat(mapping.get("target_date")),
        "source_type": mapping.get("source_type"),
        "source_id": mapping.get("source_id"),
        "progress_pct": int(mapping.get("progress_pct") or 0),
        "health": mapping.get("health") or "green",
        "blocked_reason": mapping.get("blocked_reason"),
        "read_only": True,
        "execution_performed": False,
    }
    detail["health"] = calculate_initiative_health(detail)
    detail["is_overdue"] = is_initiative_overdue(detail)
    detail["is_stalled"] = is_initiative_stalled(detail)
    days_overdue = 0
    if detail["is_overdue"] and detail.get("target_date"):
        try:
            target_date = date.fromisoformat(str(detail["target_date"])[:10])
            days_overdue = (datetime.now(timezone.utc).date() - target_date).days
        except ValueError:
            days_overdue = 0
    detail["days_overdue"] = days_overdue
    return detail


def record_initiative(
    *,
    title: str,
    description: str = "",
    status: InitiativeStatus = "planned",
    priority: InitiativePriority = "medium",
    owner: str | None = None,
    target_date: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    progress_pct: int = 0,
    blocked_reason: str | None = None,
    initiative_id: str | None = None,
) -> str:
    """Insert an initiative row. Returns initiative_id."""
    if engine is None or not ensure_jarvis_initiatives_table(engine):
        raise RuntimeError("Database unavailable for Jarvis initiative persistence")

    iid = initiative_id or str(uuid.uuid4())
    safe_status = status if status in VALID_STATUSES else "planned"
    safe_priority = priority if priority in VALID_PRIORITIES else "medium"
    safe_progress = max(0, min(100, int(progress_pct)))
    safe_source = source_type if source_type in VALID_SOURCE_TYPES else (source_type or "manual")

    draft = {
        "status": safe_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "target_date": target_date,
        "blocked_reason": blocked_reason,
    }
    health = calculate_initiative_health(draft)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_initiatives (
                    initiative_id, title, description, status, priority, owner,
                    target_date, source_type, source_id, progress_pct,
                    health, blocked_reason
                ) VALUES (
                    :initiative_id, :title, :description, :status, :priority, :owner,
                    :target_date, :source_type, :source_id, :progress_pct,
                    :health, :blocked_reason
                )
                """
            ),
            {
                "initiative_id": iid,
                "title": title,
                "description": description or "",
                "status": safe_status,
                "priority": safe_priority,
                "owner": owner,
                "target_date": target_date,
                "source_type": safe_source,
                "source_id": source_id,
                "progress_pct": safe_progress,
                "health": health,
                "blocked_reason": blocked_reason,
            },
        )
    return iid


def update_initiative(
    *,
    initiative_id: str,
    title: str | None = None,
    description: str | None = None,
    status: InitiativeStatus | None = None,
    priority: InitiativePriority | None = None,
    owner: str | None = None,
    target_date: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    progress_pct: int | None = None,
    blocked_reason: str | None = None,
    clear_blocked_reason: bool = False,
) -> bool:
    """Update an initiative. Recalculates health on save."""
    if engine is None or not ensure_jarvis_initiatives_table(engine):
        return False

    existing = get_initiative(initiative_id)
    if existing is None:
        return False

    fields: dict[str, Any] = {}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None and status in VALID_STATUSES:
        fields["status"] = status
    if priority is not None and priority in VALID_PRIORITIES:
        fields["priority"] = priority
    if owner is not None:
        fields["owner"] = owner
    if target_date is not None:
        fields["target_date"] = target_date
    if source_type is not None:
        fields["source_type"] = source_type
    if source_id is not None:
        fields["source_id"] = source_id
    if progress_pct is not None:
        fields["progress_pct"] = max(0, min(100, int(progress_pct)))
    if clear_blocked_reason:
        fields["blocked_reason"] = None
    elif blocked_reason is not None:
        fields["blocked_reason"] = blocked_reason

    if not fields:
        return True

    merged = dict(existing)
    merged.update(fields)
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    fields["health"] = calculate_initiative_health(merged)
    fields["updated_at"] = merged["updated_at"]

    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["initiative_id"] = initiative_id

    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE jarvis_initiatives SET {set_clause} WHERE initiative_id = :initiative_id"),
            params,
        )
    return result.rowcount > 0  # type: ignore[union-attr]


def get_initiative(initiative_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_initiatives_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_initiatives WHERE initiative_id = :initiative_id"),
            {"initiative_id": initiative_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_initiatives(*, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_initiatives_table(engine):
        return []

    safe_limit = max(1, min(limit, 200))
    query = """
        SELECT initiative_id, created_at, updated_at, title, description, status,
               priority, owner, target_date, source_type, source_id,
               progress_pct, health, blocked_reason
        FROM jarvis_initiatives
    """
    params: dict[str, Any] = {"limit": safe_limit}
    if status and status in VALID_STATUSES:
        query += " WHERE status = :status"
        params["status"] = status
    query += " ORDER BY updated_at DESC LIMIT :limit"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [_row_to_detail(row) for row in rows]


def list_all_initiatives() -> list[dict[str, Any]]:
    """Load all initiatives for analytics (capped at 500)."""
    return list_initiatives(limit=500)


def get_execution_review(*, initiatives: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build execution review summary for Chief of Staff and weekly reports."""
    items = initiatives if initiatives is not None else list_all_initiatives()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    active = sum(1 for i in items if str(i.get("status")) == "active")
    blocked = sum(1 for i in items if str(i.get("status")) == "blocked")
    overdue = sum(1 for i in items if is_initiative_overdue(i))
    stalled = sum(1 for i in items if is_initiative_stalled(i))
    completed_this_month = 0
    for i in items:
        if str(i.get("status")) != "completed":
            continue
        updated = _parse_iso(i.get("updated_at"))
        if updated and updated >= month_start:
            completed_this_month += 1

    top_risk: str | None = None
    risk_candidates: list[tuple[int, str]] = []
    for i in items:
        if is_initiative_overdue(i):
            days = int(i.get("days_overdue") or 0)
            risk_candidates.append((days, f"{i.get('title')} initiative is overdue by {days} day(s)."))
        elif str(i.get("status")) == "blocked":
            reason = i.get("blocked_reason") or "blocked"
            risk_candidates.append((1000, f"{i.get('title')} initiative is blocked: {reason}."))
        elif is_initiative_stalled(i):
            risk_candidates.append((100, f"{i.get('title')} initiative has stalled (no update in {STALE_DAYS}+ days)."))

    if risk_candidates:
        risk_candidates.sort(key=lambda x: x[0], reverse=True)
        top_risk = risk_candidates[0][1]

    return {
        "active": active,
        "blocked": blocked,
        "overdue": overdue,
        "stalled": stalled,
        "completed_this_month": completed_this_month,
        "top_risk": top_risk,
    }


def get_execution_status(*, initiatives: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Detailed execution status for Chief of Staff report section."""
    items = initiatives if initiatives is not None else list_all_initiatives()
    review = get_execution_review(initiatives=items)

    def _filter_status(status: str) -> list[dict[str, Any]]:
        return [
            {
                "initiative_id": i["initiative_id"],
                "title": i["title"],
                "priority": i.get("priority"),
                "owner": i.get("owner"),
                "progress_pct": i.get("progress_pct"),
                "health": i.get("health"),
                "target_date": i.get("target_date"),
                "days_overdue": i.get("days_overdue"),
                "blocked_reason": i.get("blocked_reason"),
            }
            for i in items
            if (
                (status == "active" and str(i.get("status")) == "active")
                or (status == "blocked" and str(i.get("status")) == "blocked")
                or (status == "overdue" and is_initiative_overdue(i))
                or (status == "stalled" and is_initiative_stalled(i))
            )
        ]

    return {
        "summary": {
            "active": review["active"],
            "blocked": review["blocked"],
            "overdue": review["overdue"],
            "stalled": review["stalled"],
        },
        "active_initiatives": _filter_status("active")[:10],
        "blocked_initiatives": _filter_status("blocked")[:10],
        "overdue_initiatives": _filter_status("overdue")[:10],
        "stalled_initiatives": _filter_status("stalled")[:10],
        "top_risk": review.get("top_risk"),
    }
