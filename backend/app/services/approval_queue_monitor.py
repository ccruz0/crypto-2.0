"""Approval queue health metrics and stale-task lifecycle helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_STALE_HOURS = int(os.getenv("APPROVAL_QUEUE_STALE_HOURS", "24"))
DEFAULT_EXPIRE_DAYS = int(os.getenv("APPROVAL_QUEUE_EXPIRE_DAYS", "7"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def collect_approval_queue_stats(
    db: Session,
    *,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Return pending approval counts and oldest pending age."""
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
        requested_at = row.requested_at
        if requested_at is None:
            stale_total += 1
            continue
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=timezone.utc)
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
    _PROMETHEUS_AVAILABLE = True
except Exception:
    _approval_queue_pending_total = None
    _approval_queue_stale_total = None
    _approval_queue_oldest_pending_age_seconds = None
    _PROMETHEUS_AVAILABLE = False


def refresh_approval_queue_metrics(db: Session) -> dict[str, Any]:
    """Update Prometheus gauges and return current approval queue stats."""
    stats = collect_approval_queue_stats(db)
    if _PROMETHEUS_AVAILABLE:
        if _approval_queue_pending_total is not None:
            _approval_queue_pending_total.set(stats["pending_total"])
        if _approval_queue_stale_total is not None:
            _approval_queue_stale_total.set(stats["stale_total"])
        if _approval_queue_oldest_pending_age_seconds is not None:
            _approval_queue_oldest_pending_age_seconds.set(stats["oldest_pending_age_seconds"])
    return stats


def run_approval_queue_maintenance(db: Session) -> dict[str, Any]:
    """Refresh metrics and expire very old pending approvals."""
    stats = refresh_approval_queue_metrics(db)
    expired = expire_stale_pending_approvals(db)
    return {**stats, "expired": expired}
