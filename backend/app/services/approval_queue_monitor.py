"""Approval queue health metrics and stale-task lifecycle helpers."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_STALE_HOURS = int(os.getenv("APPROVAL_QUEUE_STALE_HOURS", "24"))
DEFAULT_EXPIRE_DAYS = int(os.getenv("APPROVAL_QUEUE_EXPIRE_DAYS", "7"))
# Comma-separated risk_level values eligible for ACW auto-expire (default: low only).
_DEFAULT_JARVIS_EXPIRE_RISKS = "low"
JARVIS_WAITING_STATUSES = ("waiting_for_approval", "waiting_for_pr_approval")


def _jarvis_expire_risk_levels() -> tuple[str, ...]:
    raw = os.getenv("APPROVAL_QUEUE_JARVIS_EXPIRE_RISK_LEVELS", _DEFAULT_JARVIS_EXPIRE_RISKS)
    levels = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return levels or ("low",)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def collect_approval_queue_stats(
    db: Session,
    *,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Return pending Telegram agent approval counts and oldest pending age."""
    from app.models.agent_approval_state import AgentApprovalState

    now = _utc_now()
    stale_cutoff = now - timedelta(hours=max(stale_hours, 1))
    pending_rows = (
        db.query(AgentApprovalState)
        .filter(AgentApprovalState.status == "pending")
        .order_by(AgentApprovalState.requested_at.asc())
        .all()
    )
    pending_total = len(pending_rows)
    stale_total = 0
    oldest_age_seconds = 0.0
    for row in pending_rows:
        requested_at = _as_utc(row.requested_at)
        if requested_at is None:
            stale_total += 1
            continue
        age_seconds = max(0.0, (now - requested_at).total_seconds())
        oldest_age_seconds = max(oldest_age_seconds, age_seconds)
        if requested_at <= stale_cutoff:
            stale_total += 1
    return {
        "pending_total": pending_total,
        "stale_total": stale_total,
        "oldest_pending_age_seconds": oldest_age_seconds,
        "stale_hours": stale_hours,
    }


def collect_jarvis_approval_queue_stats(
    db: Session,
    *,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Return Approval Center (ACW) waiting-task counts and oldest waiting age.

    Age is measured from ``created_at`` (no dedicated entered-waiting timestamp).
    """
    now = _utc_now()
    stale_cutoff = now - timedelta(hours=max(stale_hours, 1))
    waiting_total = 0
    stale_total = 0
    oldest_age_seconds = 0.0
    empty = {
        "waiting_total": 0,
        "stale_total": 0,
        "oldest_waiting_age_seconds": 0.0,
        "stale_hours": stale_hours,
    }
    # Statuses are fixed constants (not user input).
    try:
        rows = db.execute(
            text(
                """
                SELECT status, created_at
                FROM jarvis_task_runs
                WHERE status IN ('waiting_for_approval', 'waiting_for_pr_approval')
                ORDER BY created_at ASC
                """
            )
        ).fetchall()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] jarvis_task_runs stats unavailable: %s", exc)
        return empty

    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        raw_created = mapping["created_at"] if mapping is not None else row[1]
        waiting_total += 1
        created_at = _as_utc(raw_created)
        if created_at is None:
            stale_total += 1
            continue
        age_seconds = max(0.0, (now - created_at).total_seconds())
        oldest_age_seconds = max(oldest_age_seconds, age_seconds)
        if created_at <= stale_cutoff:
            stale_total += 1

    return {
        "waiting_total": waiting_total,
        "stale_total": stale_total,
        "oldest_waiting_age_seconds": oldest_age_seconds,
        "stale_hours": stale_hours,
    }


def expire_stale_pending_approvals(
    db: Session,
    *,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
) -> int:
    """Mark very old pending approvals as expired (dedupe-friendly lifecycle cleanup)."""
    from app.models.agent_approval_state import AgentApprovalState

    now = _utc_now()
    expire_cutoff = now - timedelta(days=max(expire_days, 1))
    rows = (
        db.query(AgentApprovalState)
        .filter(
            AgentApprovalState.status == "pending",
            AgentApprovalState.requested_at <= expire_cutoff,
        )
        .all()
    )
    if not rows:
        return 0
    for row in rows:
        row.status = "expired"
        row.decision_at = now
        row.execution_summary = (
            (row.execution_summary or "").strip()
            or f"Auto-expired after {expire_days} days pending (approval queue lifecycle)."
        )
    db.commit()
    logger.info(
        "[APPROVAL_QUEUE] Expired %s pending approval(s) older than %s days",
        len(rows),
        expire_days,
    )
    return len(rows)


def expire_stale_jarvis_waiting_approvals(
    db: Session,
    *,
    expire_days: int = DEFAULT_EXPIRE_DAYS,
    risk_levels: tuple[str, ...] | None = None,
) -> int:
    """Cancel stale low-risk ACW waiting tasks (Approval Center lifecycle cleanup).

    Mirrors ``expire_stale_pending_approvals`` for Telegram agent approvals.
    Age is measured from ``created_at`` (same as Jarvis stale metrics). Only
    ``risk_level`` values in ``risk_levels`` (default: low) are expired so
    medium/high waiting tasks stay visible for human review.
    """
    levels = risk_levels if risk_levels is not None else _jarvis_expire_risk_levels()
    if not levels:
        return 0

    now = _utc_now()
    expire_cutoff = now - timedelta(days=max(expire_days, 1))
    # Bound risk placeholders; values come from env/defaults, not request input.
    risk_placeholders = ", ".join(f":risk_{i}" for i in range(len(levels)))
    status_list = ", ".join(f"'{s}'" for s in JARVIS_WAITING_STATUSES)
    params: dict[str, Any] = {"cutoff": expire_cutoff}
    for i, level in enumerate(levels):
        params[f"risk_{i}"] = level

    try:
        rows = db.execute(
            text(
                f"""
                SELECT task_id, status, risk_level, created_at
                FROM jarvis_task_runs
                WHERE status IN ({status_list})
                  AND lower(coalesce(risk_level, '')) IN ({risk_placeholders})
                  AND created_at <= :cutoff
                ORDER BY created_at ASC
                """
            ),
            params,
        ).fetchall()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] jarvis expire query unavailable: %s", exc)
        return 0

    if not rows:
        return 0

    expired = 0
    msg = (
        f"Auto-expired after {expire_days} days waiting "
        f"(Approval Center lifecycle; risk_level in {list(levels)})."
    )
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        task_id = mapping["task_id"] if mapping is not None else row[0]
        if not task_id:
            continue
        try:
            result = db.execute(
                text(
                    f"""
                    UPDATE jarvis_task_runs
                    SET status = 'cancelled',
                        approval_status = 'rejected',
                        final_answer = :msg,
                        completed_at = :now,
                        current_step = 'auto_expired'
                    WHERE task_id = :task_id
                      AND status IN ({status_list})
                    """
                ),
                {"task_id": task_id, "msg": msg, "now": now},
            )
            if getattr(result, "rowcount", 1) == 0:
                continue
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO jarvis_task_approvals (
                            approval_id, task_id, decision, actor_id, comment, created_at
                        ) VALUES (
                            :approval_id, :task_id, :decision, :actor_id, :comment, :created_at
                        )
                        """
                    ),
                    {
                        "approval_id": str(uuid.uuid4()),
                        "task_id": task_id,
                        "decision": "expired",
                        "actor_id": "approval_queue_monitor",
                        "comment": msg[:2000],
                        "created_at": now,
                    },
                )
            except Exception as audit_exc:
                # Task cancel still counts; audit table may be absent on older schemas.
                logger.debug(
                    "[APPROVAL_QUEUE] jarvis expire audit insert skipped for %s: %s",
                    task_id,
                    audit_exc,
                )
            try:
                from app.jarvis.change_execution.sandbox import cleanup_sandbox

                cleanup_sandbox(str(task_id))
            except Exception as sandbox_exc:
                logger.debug(
                    "[APPROVAL_QUEUE] sandbox cleanup skipped for %s: %s",
                    task_id,
                    sandbox_exc,
                )
            expired += 1
        except Exception as exc:
            logger.warning(
                "[APPROVAL_QUEUE] failed to expire jarvis task %s: %s",
                task_id,
                exc,
            )

    if expired:
        db.commit()
        logger.info(
            "[APPROVAL_QUEUE] Expired %s Jarvis waiting task(s) older than %s days (risk=%s)",
            expired,
            expire_days,
            list(levels),
        )
    return expired


try:
    from prometheus_client import Gauge  # pyright: ignore[reportMissingImports]

    _approval_queue_pending_total = Gauge(
        "approval_queue_pending_total",
        "Count of agent approval tasks in pending status",
    )
    _approval_queue_stale_total = Gauge(
        "approval_queue_stale_total",
        "Count of pending agent approvals older than the stale threshold",
    )
    _approval_queue_oldest_pending_age_seconds = Gauge(
        "approval_queue_oldest_pending_age_seconds",
        "Age in seconds of the oldest pending agent approval",
    )
    _jarvis_approval_queue_waiting_total = Gauge(
        "jarvis_approval_queue_waiting_total",
        "Count of ACW tasks waiting for approval or PR approval",
    )
    _jarvis_approval_queue_stale_total = Gauge(
        "jarvis_approval_queue_stale_total",
        "Count of ACW waiting tasks older than the stale threshold",
    )
    _jarvis_approval_queue_oldest_waiting_age_seconds = Gauge(
        "jarvis_approval_queue_oldest_waiting_age_seconds",
        "Age in seconds of the oldest ACW task waiting for approval",
    )
    _PROMETHEUS_AVAILABLE = True
except Exception:
    _approval_queue_pending_total = None
    _approval_queue_stale_total = None
    _approval_queue_oldest_pending_age_seconds = None
    _jarvis_approval_queue_waiting_total = None
    _jarvis_approval_queue_stale_total = None
    _jarvis_approval_queue_oldest_waiting_age_seconds = None
    _PROMETHEUS_AVAILABLE = False


def refresh_approval_queue_metrics(db: Session) -> dict[str, Any]:
    """Update Prometheus gauges and return current approval queue stats."""
    agent_stats = collect_approval_queue_stats(db)
    jarvis_stats = collect_jarvis_approval_queue_stats(db)
    if _PROMETHEUS_AVAILABLE:
        if _approval_queue_pending_total is not None:
            _approval_queue_pending_total.set(agent_stats["pending_total"])
        if _approval_queue_stale_total is not None:
            _approval_queue_stale_total.set(agent_stats["stale_total"])
        if _approval_queue_oldest_pending_age_seconds is not None:
            _approval_queue_oldest_pending_age_seconds.set(agent_stats["oldest_pending_age_seconds"])
        if _jarvis_approval_queue_waiting_total is not None:
            _jarvis_approval_queue_waiting_total.set(jarvis_stats["waiting_total"])
        if _jarvis_approval_queue_stale_total is not None:
            _jarvis_approval_queue_stale_total.set(jarvis_stats["stale_total"])
        if _jarvis_approval_queue_oldest_waiting_age_seconds is not None:
            _jarvis_approval_queue_oldest_waiting_age_seconds.set(
                jarvis_stats["oldest_waiting_age_seconds"]
            )
    return {
        **agent_stats,
        "jarvis_waiting_total": jarvis_stats["waiting_total"],
        "jarvis_stale_total": jarvis_stats["stale_total"],
        "jarvis_oldest_waiting_age_seconds": jarvis_stats["oldest_waiting_age_seconds"],
    }


def run_approval_queue_maintenance(db: Session) -> dict[str, Any]:
    """Refresh metrics and expire very old pending / waiting approvals."""
    stats = refresh_approval_queue_metrics(db)
    expired = expire_stale_pending_approvals(db)
    jarvis_expired = expire_stale_jarvis_waiting_approvals(db)
    # Re-publish gauges after expire so stale counts drop in the same run.
    if jarvis_expired or expired:
        stats = refresh_approval_queue_metrics(db)
    return {**stats, "expired": expired, "jarvis_expired": jarvis_expired}
