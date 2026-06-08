"""PostgreSQL/SQLite persistence for Jarvis strategic objectives."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from sqlalchemy import text

from app.database import (
    engine,
    ensure_jarvis_key_results_table,
    ensure_jarvis_objective_links_table,
    ensure_jarvis_objective_metrics_table,
    ensure_jarvis_objectives_table,
)

logger = logging.getLogger(__name__)

ObjectiveStatus = Literal["planned", "active", "completed", "cancelled"]
ObjectiveHealth = Literal["green", "yellow", "red"]
KrStatus = Literal["on_track", "at_risk", "behind", "achieved"]
KrDirection = Literal["max", "min"]
LinkedType = Literal[
    "initiative",
    "aws_audit",
    "crypto_audit",
    "action_plan",
    "decision",
    "executive_report",
]

VALID_OBJECTIVE_STATUSES = frozenset({"planned", "active", "completed", "cancelled"})
VALID_LINKED_TYPES = frozenset({
    "initiative",
    "aws_audit",
    "crypto_audit",
    "action_plan",
    "decision",
    "executive_report",
})
VALID_KR_STATUSES = frozenset({"on_track", "at_risk", "behind", "achieved"})


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


def is_objective_overdue(objective: dict[str, Any]) -> bool:
    status = str(objective.get("status") or "").lower()
    if status in ("completed", "cancelled"):
        return False
    target = objective.get("target_date")
    if not target:
        return False
    try:
        target_date = date.fromisoformat(str(target)[:10])
    except ValueError:
        return False
    return target_date < datetime.now(timezone.utc).date()


def calculate_kr_progress(
    *,
    target_value: float,
    current_value: float,
    direction: str = "max",
) -> float:
    """Compute key result progress 0-100."""
    target = float(target_value)
    current = float(current_value)
    direction = str(direction or "max").lower()

    if direction == "min":
        if target == 0:
            return 100.0 if current <= 0 else max(0.0, 100.0 - current * 10)
        if current <= target:
            return 100.0
        overshoot = current - target
        return max(0.0, min(100.0, 100.0 - (overshoot / max(target, 1)) * 100.0))

    if target == 0:
        return 100.0 if current >= 0 else 0.0
    return max(0.0, min(100.0, (current / target) * 100.0))


def calculate_kr_status(progress_pct: float) -> KrStatus:
    if progress_pct >= 100:
        return "achieved"
    if progress_pct >= 80:
        return "on_track"
    if progress_pct >= 50:
        return "at_risk"
    return "behind"


def calculate_objective_health(
    objective: dict[str, Any],
    *,
    progress_pct: int | None = None,
) -> ObjectiveHealth:
    """
    Health rules:
    - Green: 80%+ progress (and not overdue)
    - Yellow: 50-79%
    - Red: below 50% or overdue
    """
    status = str(objective.get("status") or "").lower()
    if status == "completed":
        return "green"
    if status == "cancelled":
        return "green"

    progress = progress_pct if progress_pct is not None else int(objective.get("progress_pct") or 0)
    if is_objective_overdue(objective):
        return "red"
    if progress >= 80:
        return "green"
    if progress >= 50:
        return "yellow"
    return "red"


def _kr_row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    target = float(mapping.get("target_value") or 0)
    current = float(mapping.get("current_value") or 0)
    direction = str(mapping.get("direction") or "max")
    progress = calculate_kr_progress(
        target_value=target,
        current_value=current,
        direction=direction,
    )
    status = calculate_kr_status(progress)
    return {
        "kr_id": mapping["kr_id"],
        "objective_id": mapping["objective_id"],
        "created_at": _isoformat(mapping.get("created_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
        "title": mapping.get("title") or "",
        "metric_name": mapping.get("metric_name"),
        "target_value": target,
        "current_value": current,
        "unit": mapping.get("unit"),
        "direction": direction,
        "status": status,
        "progress_pct": round(progress, 1),
        "metric_source": mapping.get("metric_source"),
        "last_refreshed_at": _isoformat(mapping.get("last_refreshed_at")),
    }


def list_key_results_for_objective(objective_id: str) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_key_results_table(engine):
        return []

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM jarvis_key_results WHERE objective_id = :objective_id ORDER BY created_at"),
            {"objective_id": objective_id},
        ).fetchall()
    return [_kr_row_to_detail(row) for row in rows]


def compute_objective_progress(objective_id: str) -> int:
    """Average KR progress for an objective."""
    krs = list_key_results_for_objective(objective_id)
    if not krs:
        obj = get_objective(objective_id, include_relations=False)
        return int(obj.get("progress_pct") or 0) if obj else 0
    avg = sum(float(kr.get("progress_pct") or 0) for kr in krs) / len(krs)
    return max(0, min(100, round(avg)))


def _objective_row_to_detail(row: Any, *, include_relations: bool = True) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    oid = mapping["objective_id"]
    detail: dict[str, Any] = {
        "objective_id": oid,
        "created_at": _isoformat(mapping.get("created_at")),
        "updated_at": _isoformat(mapping.get("updated_at")),
        "title": mapping.get("title") or "",
        "description": mapping.get("description") or "",
        "status": mapping.get("status") or "planned",
        "owner": mapping.get("owner"),
        "target_date": _isoformat(mapping.get("target_date")),
        "progress_pct": int(mapping.get("progress_pct") or 0),
        "health": mapping.get("health") or "green",
        "read_only": True,
        "execution_performed": False,
    }

    if include_relations:
        progress = compute_objective_progress(oid)
        detail["progress_pct"] = progress
        detail["key_results"] = list_key_results_for_objective(oid)
        detail["links"] = list_objective_links(oid)
        detail["linked_initiatives"] = _linked_initiatives(oid)
        detail["progress_trend"] = list_objective_metric_trend(objective_id=oid, days=30)
        detail["risks"] = _objective_risks(detail)

    detail["health"] = calculate_objective_health(detail, progress_pct=detail["progress_pct"])
    detail["is_overdue"] = is_objective_overdue(detail)
    detail["alignment_status"] = _alignment_status(detail)
    return detail


def _alignment_status(objective: dict[str, Any]) -> str:
    if str(objective.get("status")) == "completed":
        return "Completed"
    if objective.get("is_overdue"):
        return "At risk"
    health = str(objective.get("health") or "green")
    if health == "green":
        return "On track"
    if health == "yellow":
        return "Needs attention"
    return "At risk"


def _objective_risks(objective: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if objective.get("is_overdue"):
        risks.append("Objective is past its target date.")
    for kr in objective.get("key_results") or []:
        if str(kr.get("status")) == "behind":
            risks.append(f"Key result behind: {kr.get('title')}")
    blocked = [
        i for i in (objective.get("linked_initiatives") or [])
        if str(i.get("status")) == "blocked"
    ]
    if blocked:
        risks.append(f"{len(blocked)} linked initiative(s) blocked.")
    return risks[:5]


def _linked_initiatives(objective_id: str) -> list[dict[str, Any]]:
    from app.jarvis.mvp.initiative_persistence import list_all_initiatives

    linked_ids = {
        link["linked_id"]
        for link in list_objective_links(objective_id)
        if str(link.get("linked_type")) == "initiative"
    }
    initiatives = []
    for initiative in list_all_initiatives():
        if initiative["initiative_id"] in linked_ids:
            initiatives.append(initiative)
        elif (
            str(initiative.get("source_type")) == "objective"
            and str(initiative.get("source_id")) == objective_id
        ):
            initiatives.append(initiative)
    return initiatives


def record_objective(
    *,
    title: str,
    description: str = "",
    status: ObjectiveStatus = "planned",
    owner: str | None = None,
    target_date: str | None = None,
    progress_pct: int = 0,
    objective_id: str | None = None,
) -> str:
    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise RuntimeError("Database unavailable for Jarvis objective persistence")

    oid = objective_id or str(uuid.uuid4())
    safe_status = status if status in VALID_OBJECTIVE_STATUSES else "planned"
    safe_progress = max(0, min(100, int(progress_pct)))
    draft = {
        "status": safe_status,
        "target_date": target_date,
        "progress_pct": safe_progress,
    }
    health = calculate_objective_health(draft, progress_pct=safe_progress)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_objectives (
                    objective_id, title, description, status, owner,
                    target_date, progress_pct, health
                ) VALUES (
                    :objective_id, :title, :description, :status, :owner,
                    :target_date, :progress_pct, :health
                )
                """
            ),
            {
                "objective_id": oid,
                "title": title,
                "description": description or "",
                "status": safe_status,
                "owner": owner,
                "target_date": target_date,
                "progress_pct": safe_progress,
                "health": health,
            },
        )
    return oid


def update_objective(
    *,
    objective_id: str,
    title: str | None = None,
    description: str | None = None,
    status: ObjectiveStatus | None = None,
    owner: str | None = None,
    target_date: str | None = None,
    progress_pct: int | None = None,
) -> bool:
    if engine is None or not ensure_jarvis_objectives_table(engine):
        return False

    existing = get_objective(objective_id, include_relations=False)
    if existing is None:
        return False

    fields: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if title is not None:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if status is not None and status in VALID_OBJECTIVE_STATUSES:
        fields["status"] = status
    if owner is not None:
        fields["owner"] = owner
    if target_date is not None:
        fields["target_date"] = target_date

    merged = dict(existing)
    merged.update(fields)
    progress = progress_pct if progress_pct is not None else compute_objective_progress(objective_id)
    fields["progress_pct"] = max(0, min(100, int(progress)))
    fields["health"] = calculate_objective_health(merged, progress_pct=fields["progress_pct"])

    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["objective_id"] = objective_id

    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE jarvis_objectives SET {set_clause} WHERE objective_id = :objective_id"),
            params,
        )
    return result.rowcount > 0  # type: ignore[union-attr]


def get_objective(objective_id: str, *, include_relations: bool = True) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_objectives_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_objectives WHERE objective_id = :objective_id"),
            {"objective_id": objective_id},
        ).fetchone()
    if row is None:
        return None
    return _objective_row_to_detail(row, include_relations=include_relations)


def list_objectives(*, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_objectives_table(engine):
        return []

    safe_limit = max(1, min(limit, 200))
    query = """
        SELECT objective_id, created_at, updated_at, title, description,
               status, owner, target_date, progress_pct, health
        FROM jarvis_objectives
    """
    params: dict[str, Any] = {"limit": safe_limit}
    if status and status in VALID_OBJECTIVE_STATUSES:
        query += " WHERE status = :status"
        params["status"] = status
    query += " ORDER BY updated_at DESC LIMIT :limit"

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [_objective_row_to_detail(row, include_relations=False) for row in rows]


def list_all_objectives() -> list[dict[str, Any]]:
    items = list_objectives(limit=500)
    return [
        {
            **obj,
            "progress_pct": compute_objective_progress(obj["objective_id"]),
            "health": calculate_objective_health(
                obj,
                progress_pct=compute_objective_progress(obj["objective_id"]),
            ),
            "is_overdue": is_objective_overdue(obj),
            "alignment_status": _alignment_status({
                **obj,
                "progress_pct": compute_objective_progress(obj["objective_id"]),
                "health": calculate_objective_health(
                    obj,
                    progress_pct=compute_objective_progress(obj["objective_id"]),
                ),
                "is_overdue": is_objective_overdue(obj),
            }),
        }
        for obj in items
    ]


def record_key_result(
    *,
    objective_id: str,
    title: str,
    metric_name: str | None = None,
    target_value: float = 0,
    current_value: float = 0,
    unit: str | None = None,
    direction: KrDirection = "max",
    kr_id: str | None = None,
) -> str:
    if engine is None or not ensure_jarvis_key_results_table(engine):
        raise RuntimeError("Database unavailable for Jarvis key result persistence")

    kid = kr_id or str(uuid.uuid4())
    progress = calculate_kr_progress(
        target_value=target_value,
        current_value=current_value,
        direction=direction,
    )
    status = calculate_kr_status(progress)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_key_results (
                    kr_id, objective_id, title, metric_name,
                    target_value, current_value, unit, direction, status
                ) VALUES (
                    :kr_id, :objective_id, :title, :metric_name,
                    :target_value, :current_value, :unit, :direction, :status
                )
                """
            ),
            {
                "kr_id": kid,
                "objective_id": objective_id,
                "title": title,
                "metric_name": metric_name,
                "target_value": float(target_value),
                "current_value": float(current_value),
                "unit": unit,
                "direction": direction,
                "status": status,
            },
        )

    update_objective(objective_id=objective_id)
    return kid


def update_key_result(
    *,
    kr_id: str,
    title: str | None = None,
    current_value: float | None = None,
    target_value: float | None = None,
) -> bool:
    if engine is None or not ensure_jarvis_key_results_table(engine):
        return False

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_key_results WHERE kr_id = :kr_id"),
            {"kr_id": kr_id},
        ).fetchone()
    if row is None:
        return False

    mapping = row._mapping if hasattr(row, "_mapping") else row
    objective_id = mapping["objective_id"]
    fields: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if title is not None:
        fields["title"] = title
    if current_value is not None:
        fields["current_value"] = float(current_value)
    if target_value is not None:
        fields["target_value"] = float(target_value)

    target = float(fields.get("target_value", mapping.get("target_value") or 0))
    current = float(fields.get("current_value", mapping.get("current_value") or 0))
    direction = str(mapping.get("direction") or "max")
    progress = calculate_kr_progress(target_value=target, current_value=current, direction=direction)
    fields["status"] = calculate_kr_status(progress)

    set_clause = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["kr_id"] = kr_id

    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE jarvis_key_results SET {set_clause} WHERE kr_id = :kr_id"),
            params,
        )

    update_objective(objective_id=objective_id)
    return result.rowcount > 0  # type: ignore[union-attr]


def record_objective_link(
    *,
    objective_id: str,
    linked_type: LinkedType,
    linked_id: str,
    link_id: str | None = None,
) -> str:
    if engine is None or not ensure_jarvis_objective_links_table(engine):
        raise RuntimeError("Database unavailable for Jarvis objective link persistence")

    if linked_type not in VALID_LINKED_TYPES:
        raise ValueError(f"invalid linked_type: {linked_type}")

    lid = link_id or str(uuid.uuid4())
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                """
                SELECT link_id FROM jarvis_objective_links
                WHERE objective_id = :objective_id
                  AND linked_type = :linked_type
                  AND linked_id = :linked_id
                """
            ),
            {
                "objective_id": objective_id,
                "linked_type": linked_type,
                "linked_id": linked_id,
            },
        ).fetchone()
        if existing:
            return existing._mapping["link_id"]  # type: ignore[union-attr]

        conn.execute(
            text(
                """
                INSERT INTO jarvis_objective_links (
                    link_id, objective_id, linked_type, linked_id
                ) VALUES (
                    :link_id, :objective_id, :linked_type, :linked_id
                )
                """
            ),
            {
                "link_id": lid,
                "objective_id": objective_id,
                "linked_type": linked_type,
                "linked_id": linked_id,
            },
        )
    return lid


def list_objective_links(objective_id: str) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_objective_links_table(engine):
        return []

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT link_id, objective_id, linked_type, linked_id, created_at
                FROM jarvis_objective_links
                WHERE objective_id = :objective_id
                ORDER BY created_at
                """
            ),
            {"objective_id": objective_id},
        ).fetchall()

    return [
        {
            "link_id": r._mapping["link_id"],
            "objective_id": r._mapping["objective_id"],
            "linked_type": r._mapping["linked_type"],
            "linked_id": r._mapping["linked_id"],
            "created_at": _isoformat(r._mapping.get("created_at")),
        }
        for r in rows
    ]


def record_objective_metric_snapshot(*, objective_id: str) -> str | None:
    """Upsert today's progress snapshot for trend charts."""
    if engine is None or not ensure_jarvis_objective_metrics_table(engine):
        return None

    objective = get_objective(objective_id, include_relations=True)
    if objective is None:
        return None

    today = datetime.now(timezone.utc).date().isoformat()
    krs = objective.get("key_results") or []
    on_track = sum(1 for kr in krs if str(kr.get("status")) == "on_track")
    at_risk = sum(1 for kr in krs if str(kr.get("status")) == "at_risk")
    behind = sum(1 for kr in krs if str(kr.get("status")) == "behind")
    achieved = sum(1 for kr in krs if str(kr.get("status")) == "achieved")
    on_track += achieved

    metric_id = str(uuid.uuid4())
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                """
                SELECT metric_id FROM jarvis_objective_metrics
                WHERE objective_id = :objective_id AND metric_date = :metric_date
                """
            ),
            {"objective_id": objective_id, "metric_date": today},
        ).fetchone()

        if existing:
            metric_id = existing._mapping["metric_id"]  # type: ignore[union-attr]
            conn.execute(
                text(
                    """
                    UPDATE jarvis_objective_metrics
                    SET progress_pct = :progress_pct,
                        health = :health,
                        on_track_krs = :on_track_krs,
                        at_risk_krs = :at_risk_krs,
                        behind_krs = :behind_krs
                    WHERE metric_id = :metric_id
                    """
                ),
                {
                    "metric_id": metric_id,
                    "progress_pct": int(objective.get("progress_pct") or 0),
                    "health": objective.get("health") or "green",
                    "on_track_krs": on_track,
                    "at_risk_krs": at_risk,
                    "behind_krs": behind,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO jarvis_objective_metrics (
                        metric_id, objective_id, metric_date,
                        progress_pct, health,
                        on_track_krs, at_risk_krs, behind_krs
                    ) VALUES (
                        :metric_id, :objective_id, :metric_date,
                        :progress_pct, :health,
                        :on_track_krs, :at_risk_krs, :behind_krs
                    )
                    """
                ),
                {
                    "metric_id": metric_id,
                    "objective_id": objective_id,
                    "metric_date": today,
                    "progress_pct": int(objective.get("progress_pct") or 0),
                    "health": objective.get("health") or "green",
                    "on_track_krs": on_track,
                    "at_risk_krs": at_risk,
                    "behind_krs": behind,
                },
            )
    return metric_id


def list_objective_metric_trend(*, objective_id: str, days: int = 30) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_objective_metrics_table(engine):
        return []

    safe_days = max(1, min(days, 90))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT metric_date, progress_pct, health,
                       on_track_krs, at_risk_krs, behind_krs
                FROM jarvis_objective_metrics
                WHERE objective_id = :objective_id
                ORDER BY metric_date DESC
                LIMIT :limit
                """
            ),
            {"objective_id": objective_id, "limit": safe_days},
        ).fetchall()

    trend = [
        {
            "date": _isoformat(r._mapping.get("metric_date")),
            "progress_pct": int(r._mapping.get("progress_pct") or 0),
            "health": r._mapping.get("health") or "green",
            "on_track_krs": int(r._mapping.get("on_track_krs") or 0),
            "at_risk_krs": int(r._mapping.get("at_risk_krs") or 0),
            "behind_krs": int(r._mapping.get("behind_krs") or 0),
        }
        for r in rows
    ]
    return list(reversed(trend))


def get_strategic_summary() -> dict[str, Any]:
    """Aggregate objective counts for executive dashboard."""
    objectives = list_all_objectives()
    on_track = sum(
        1 for o in objectives
        if str(o.get("alignment_status")) == "On track" and str(o.get("status")) != "completed"
    )
    at_risk = sum(
        1 for o in objectives
        if str(o.get("alignment_status")) in ("At risk", "Needs attention")
        and str(o.get("status")) not in ("completed", "cancelled")
    )
    completed = sum(1 for o in objectives if str(o.get("status")) == "completed")
    active = sum(1 for o in objectives if str(o.get("status")) == "active")
    avg_progress = 0
    open_objs = [o for o in objectives if str(o.get("status")) not in ("completed", "cancelled")]
    if open_objs:
        avg_progress = round(
            sum(int(o.get("progress_pct") or 0) for o in open_objs) / len(open_objs)
        )

    return {
        "objectives_on_track": on_track,
        "objectives_at_risk": at_risk,
        "objectives_completed": completed,
        "objectives_active": active,
        "average_progress_pct": avg_progress,
        "total_objectives": len(objectives),
    }


def get_strategic_alignment() -> dict[str, Any]:
    """Build strategic alignment section for Chief of Staff weekly reports."""
    objectives = list_all_objectives()
    summary = get_strategic_summary()

    items = []
    for obj in objectives:
        if str(obj.get("status")) in ("cancelled",):
            continue
        oid = obj["objective_id"]
        linked = _linked_initiatives(oid)
        items.append({
            "objective_id": oid,
            "title": obj.get("title"),
            "progress_pct": int(obj.get("progress_pct") or 0),
            "status": obj.get("alignment_status"),
            "health": obj.get("health"),
            "owner": obj.get("owner"),
            "target_date": obj.get("target_date"),
            "supporting_initiatives": len(linked),
            "is_blocked": any(str(i.get("status")) == "blocked" for i in linked),
            "is_overdue": obj.get("is_overdue"),
            "key_results_count": len(list_key_results_for_objective(oid)),
        })

    severity_order = {"At risk": 0, "Needs attention": 1, "On track": 2, "Completed": 3}
    items.sort(
        key=lambda x: (
            severity_order.get(str(x.get("status")), 1),
            -int(x.get("progress_pct") or 0),
        ),
    )

    blocked_objectives = [
        {
            "objective_id": i["objective_id"],
            "title": i["title"],
            "reason": "Linked initiative(s) blocked or objective overdue",
        }
        for i in items
        if i.get("is_blocked") or (i.get("is_overdue") and str(i.get("status")) != "Completed")
    ]

    return {
        "summary": summary,
        "objectives": items[:10],
        "blocked_objectives": blocked_objectives[:5],
        "on_track_objectives": [i for i in items if str(i.get("status")) == "On track"][:5],
        "at_risk_objectives": [i for i in items if str(i.get("status")) in ("At risk", "Needs attention")][:5],
    }
