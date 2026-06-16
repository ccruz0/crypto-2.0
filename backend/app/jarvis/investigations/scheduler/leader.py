"""Single-leader lease for the investigation scheduler."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_scheduled_investigations_tables
from app.jarvis.investigations.scheduler.config import investigation_scheduler_leader_lease_seconds

logger = logging.getLogger(__name__)

_LOCK_KEY = "investigation_scheduler"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def try_acquire_leader(holder_id: str) -> bool:
    """
    Attempt to become scheduler leader using a DB-backed lease.

    Returns True when this instance holds (or renewed) the lease.
    """
    if engine is None or not ensure_jarvis_scheduled_investigations_tables(engine):
        return False
    lease_seconds = investigation_scheduler_leader_lease_seconds()
    now = _now_utc()
    expires = now + timedelta(seconds=lease_seconds)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT holder_id, lease_expires_at FROM jarvis_investigation_scheduler_leader WHERE lock_key = :lock_key"),
            {"lock_key": _LOCK_KEY},
        ).fetchone()
        if row is None:
            conn.execute(
                text(
                    """
                    INSERT INTO jarvis_investigation_scheduler_leader (
                        lock_key, holder_id, acquired_at, lease_expires_at, updated_at
                    ) VALUES (
                        :lock_key, :holder_id, :acquired_at, :lease_expires_at, :updated_at
                    )
                    """
                ),
                {
                    "lock_key": _LOCK_KEY,
                    "holder_id": holder_id,
                    "acquired_at": now,
                    "lease_expires_at": expires,
                    "updated_at": now,
                },
            )
            return True
        current_holder = str(row.holder_id or "")
        lease_expires = _parse_dt(row.lease_expires_at)
        lease_expired = lease_expires is None or lease_expires <= now
        if current_holder == holder_id or lease_expired:
            updated = conn.execute(
                text(
                    """
                    UPDATE jarvis_investigation_scheduler_leader
                    SET holder_id = :holder_id,
                        acquired_at = CASE WHEN holder_id = :holder_id THEN acquired_at ELSE :acquired_at END,
                        lease_expires_at = :lease_expires_at,
                        updated_at = :updated_at
                    WHERE lock_key = :lock_key
                      AND (holder_id = :holder_id OR lease_expires_at <= :now)
                    """
                ),
                {
                    "lock_key": _LOCK_KEY,
                    "holder_id": holder_id,
                    "acquired_at": now,
                    "lease_expires_at": expires,
                    "updated_at": now,
                    "now": now,
                },
            )
            return updated.rowcount == 1
    return False


def release_leader(holder_id: str) -> None:
    if engine is None or not ensure_jarvis_scheduled_investigations_tables(engine):
        return
    now = _now_utc()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_investigation_scheduler_leader
                SET lease_expires_at = :now, updated_at = :now
                WHERE lock_key = :lock_key AND holder_id = :holder_id
                """
            ),
            {"lock_key": _LOCK_KEY, "holder_id": holder_id, "now": now},
        )


def get_leader_state() -> dict[str, Any]:
    if engine is None or not ensure_jarvis_scheduled_investigations_tables(engine):
        return {"holder_id": None, "lease_expires_at": None, "is_leader": False}
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT holder_id, lease_expires_at FROM jarvis_investigation_scheduler_leader WHERE lock_key = :lock_key"),
            {"lock_key": _LOCK_KEY},
        ).fetchone()
    if row is None:
        return {"holder_id": None, "lease_expires_at": None, "is_leader": False}
    expires = _parse_dt(row.lease_expires_at)
    return {
        "holder_id": row.holder_id,
        "lease_expires_at": expires.isoformat() if expires else None,
    }
