"""Approval queue health metrics and stale-task lifecycle helpers."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DEFAULT_STALE_HOURS = int(os.getenv("APPROVAL_QUEUE_STALE_HOURS", "24"))
DEFAULT_EXPIRE_DAYS = int(os.getenv("APPROVAL_QUEUE_EXPIRE_DAYS", "7"))
DEFAULT_ESCALATE_DAYS = int(os.getenv("APPROVAL_QUEUE_JARVIS_ESCALATE_DAYS", "3"))
_MAX_ESCALATE_PER_RUN = int(os.getenv("APPROVAL_QUEUE_JARVIS_ESCALATE_MAX_PER_RUN", "20"))
# Comma-separated risk_level values eligible for ACW auto-expire (default: low only).
_DEFAULT_JARVIS_EXPIRE_RISKS = "low"
_DEFAULT_JARVIS_ESCALATE_RISKS = "medium,high"
JARVIS_WAITING_STATUSES = ("waiting_for_approval", "waiting_for_pr_approval")


def _jarvis_expire_risk_levels() -> tuple[str, ...]:
    raw = os.getenv("APPROVAL_QUEUE_JARVIS_EXPIRE_RISK_LEVELS", _DEFAULT_JARVIS_EXPIRE_RISKS)
    levels = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return levels or ("low",)


def _jarvis_escalate_risk_levels() -> tuple[str, ...]:
    raw = os.getenv("APPROVAL_QUEUE_JARVIS_ESCALATE_RISK_LEVELS", _DEFAULT_JARVIS_ESCALATE_RISKS)
    levels = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return levels or ("medium", "high")


def _jarvis_escalate_enabled() -> bool:
    return os.getenv("APPROVAL_QUEUE_JARVIS_ESCALATE_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _jarvis_dedup_enabled() -> bool:
    return os.getenv("APPROVAL_QUEUE_JARVIS_DEDUP_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def objective_fingerprint(objective: str | None) -> str:
    """Stable hash for Approval Center waiting-task dedup (normalized objective)."""
    normalized = re.sub(r"\s+", " ", (objective or "").strip().lower())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def _waiting_status_sql_list() -> str:
    return ", ".join(f"'{s}'" for s in JARVIS_WAITING_STATUSES)


def _cancel_jarvis_waiting_task(
    db: Session,
    *,
    task_id: str,
    msg: str,
    now: datetime | None = None,
    decision: str = "rejected",
) -> bool:
    """Cancel one waiting ACW task; best-effort audit + sandbox cleanup."""
    when = now or _utc_now()
    status_list = _waiting_status_sql_list()
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
            {"task_id": task_id, "msg": msg, "now": when},
        )
        if getattr(result, "rowcount", 1) == 0:
            return False
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
                    "decision": decision,
                    "actor_id": "approval_queue_monitor",
                    "comment": msg[:2000],
                    "created_at": when,
                },
            )
        except Exception as audit_exc:
            logger.debug(
                "[APPROVAL_QUEUE] jarvis cancel audit insert skipped for %s: %s",
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
        return True
    except Exception as exc:
        logger.warning(
            "[APPROVAL_QUEUE] failed to cancel jarvis task %s: %s",
            task_id,
            exc,
        )
        return False


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
                f"""
                SELECT status, created_at
                FROM jarvis_task_runs
                WHERE status IN ({_waiting_status_sql_list()})
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
    params: dict[str, Any] = {"cutoff": expire_cutoff}
    for i, level in enumerate(levels):
        params[f"risk_{i}"] = level

    try:
        rows = db.execute(
            text(
                f"""
                SELECT task_id, status, risk_level, created_at
                FROM jarvis_task_runs
                WHERE status IN ({_waiting_status_sql_list()})
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
        if _cancel_jarvis_waiting_task(
            db, task_id=str(task_id), msg=msg, now=now, decision="expired"
        ):
            expired += 1

    if expired:
        db.commit()
        logger.info(
            "[APPROVAL_QUEUE] Expired %s Jarvis waiting task(s) older than %s days (risk=%s)",
            expired,
            expire_days,
            list(levels),
        )
    return expired


def dedupe_jarvis_waiting_approvals(
    db: Session,
    *,
    keep_task_id: str | None = None,
) -> int:
    """Cancel duplicate ACW waiting tasks that share the same objective fingerprint.

    Keeps the newest ``created_at`` per fingerprint (or ``keep_task_id`` when set).
    Empty objectives are never deduped against each other.
    """
    if not _jarvis_dedup_enabled():
        return 0

    now = _utc_now()
    try:
        rows = db.execute(
            text(
                f"""
                SELECT task_id, objective, created_at
                FROM jarvis_task_runs
                WHERE status IN ({_waiting_status_sql_list()})
                ORDER BY created_at DESC
                """
            )
        ).fetchall()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] jarvis dedup query unavailable: %s", exc)
        return 0

    if not rows:
        return 0

    parsed: list[tuple[str, str, datetime | None]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        task_id = mapping["task_id"] if mapping is not None else row[0]
        objective = mapping["objective"] if mapping is not None else row[1]
        created_at = _as_utc(mapping["created_at"] if mapping is not None else row[2])
        if not task_id:
            continue
        parsed.append((str(task_id), str(objective or ""), created_at))

    keep_fp: str | None = None
    if keep_task_id:
        for tid, objective, _ in parsed:
            if tid == keep_task_id:
                keep_fp = objective_fingerprint(objective)
                break
        if not keep_fp:
            return 0

    groups: dict[str, list[tuple[str, datetime | None]]] = {}
    for tid, objective, created_at in parsed:
        fp = objective_fingerprint(objective)
        if not fp:
            continue
        if keep_fp is not None and fp != keep_fp:
            continue
        groups.setdefault(fp, []).append((tid, created_at))

    cancelled = 0
    for fp, members in groups.items():
        if len(members) < 2 and keep_task_id is None:
            continue
        if keep_task_id:
            keep_id = keep_task_id
        else:
            keep_id = members[0][0]
            best_ts = members[0][1]
            for tid, created_at in members[1:]:
                if created_at is None:
                    continue
                if best_ts is None or created_at > best_ts:
                    keep_id = tid
                    best_ts = created_at

        for tid, _ in members:
            if tid == keep_id:
                continue
            msg = (
                f"Deduped: superseded by waiting task {keep_id} "
                f"(same objective fingerprint {fp[:12]})."
            )
            if _cancel_jarvis_waiting_task(
                db, task_id=tid, msg=msg, now=now, decision="deduped"
            ):
                cancelled += 1

    if cancelled:
        db.commit()
        logger.info(
            "[APPROVAL_QUEUE] Deduped %s Jarvis waiting task(s)%s",
            cancelled,
            f" (kept {keep_task_id})" if keep_task_id else "",
        )
    return cancelled


def dedupe_jarvis_waiting_for_task(task_id: str) -> int:
    """Best-effort enqueue-time dedup using a short-lived DB session."""
    if not task_id or not _jarvis_dedup_enabled():
        return 0
    try:
        from app.database import SessionLocal

        db = SessionLocal()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] SessionLocal unavailable for dedup: %s", exc)
        return 0
    try:
        return dedupe_jarvis_waiting_approvals(db, keep_task_id=task_id)
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] enqueue dedup failed for %s: %s", task_id, exc)
        return 0
    finally:
        db.close()


def _already_escalated_task_ids(db: Session, task_ids: list[str]) -> set[str]:
    if not task_ids:
        return set()
    placeholders = ", ".join(f":tid_{i}" for i in range(len(task_ids)))
    params = {f"tid_{i}": tid for i, tid in enumerate(task_ids)}
    try:
        rows = db.execute(
            text(
                f"""
                SELECT DISTINCT task_id
                FROM jarvis_task_approvals
                WHERE decision = 'escalated'
                  AND task_id IN ({placeholders})
                """
            ),
            params,
        ).fetchall()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] escalated lookup unavailable: %s", exc)
        return set()
    out: set[str] = set()
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        tid = mapping["task_id"] if mapping is not None else row[0]
        if tid:
            out.add(str(tid))
    return out


def _record_escalation_audit(db: Session, *, task_id: str, msg: str, now: datetime) -> None:
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
                "decision": "escalated",
                "actor_id": "approval_queue_monitor",
                "comment": msg[:2000],
                "created_at": now,
            },
        )
    except Exception as audit_exc:
        logger.debug(
            "[APPROVAL_QUEUE] escalation audit insert skipped for %s: %s",
            task_id,
            audit_exc,
        )


def _format_escalation_telegram(
    items: list[dict[str, Any]],
    *,
    escalate_days: int,
) -> str:
    dashboard = (
        os.getenv("FRONTEND_URL")
        or os.getenv("DASHBOARD_URL")
        or "https://dashboard.hilovivo.com"
    ).rstrip("/")
    lines = [
        "⚠️ <b>Approval Center escalation</b>",
        f"{len(items)} medium/high ACW task(s) waiting ≥{escalate_days}d:",
        "",
    ]
    for item in items:
        obj = (item.get("objective") or "").strip().replace("<", "").replace(">", "")
        if len(obj) > 120:
            obj = obj[:117] + "..."
        age_d = float(item.get("age_days") or 0.0)
        lines.append(
            f"• <code>{item['task_id']}</code> risk=<b>{item.get('risk_level') or '?'}</b> "
            f"age={age_d:.1f}d"
        )
        if obj:
            lines.append(f"  {obj}")
    lines.append("")
    lines.append(f'Open: <a href="{dashboard}/jarvis/approval">{dashboard}/jarvis/approval</a>')
    return "\n".join(lines)


def escalate_stale_jarvis_waiting_approvals(
    db: Session,
    *,
    escalate_days: int = DEFAULT_ESCALATE_DAYS,
    risk_levels: tuple[str, ...] | None = None,
    send_telegram: bool = True,
) -> int:
    """Notify ops once for medium/high ACW waiters older than escalate_days.

    Does not cancel tasks (unlike expire/dedupe). Idempotent via
    ``jarvis_task_approvals.decision='escalated'``.
    """
    if not _jarvis_escalate_enabled():
        return 0

    levels = risk_levels if risk_levels is not None else _jarvis_escalate_risk_levels()
    if not levels:
        return 0

    now = _utc_now()
    cutoff = now - timedelta(days=max(escalate_days, 1))
    risk_placeholders = ", ".join(f":risk_{i}" for i in range(len(levels)))
    params: dict[str, Any] = {"cutoff": cutoff, "limit": max(_MAX_ESCALATE_PER_RUN, 1)}
    for i, level in enumerate(levels):
        params[f"risk_{i}"] = level

    try:
        rows = db.execute(
            text(
                f"""
                SELECT task_id, objective, risk_level, created_at, status
                FROM jarvis_task_runs
                WHERE status IN ({_waiting_status_sql_list()})
                  AND lower(coalesce(risk_level, '')) IN ({risk_placeholders})
                  AND created_at <= :cutoff
                ORDER BY created_at ASC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    except Exception as exc:
        logger.debug("[APPROVAL_QUEUE] jarvis escalate query unavailable: %s", exc)
        return 0

    candidates: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        task_id = mapping["task_id"] if mapping is not None else row[0]
        objective = mapping["objective"] if mapping is not None else row[1]
        risk_level = mapping["risk_level"] if mapping is not None else row[2]
        created_at = _as_utc(mapping["created_at"] if mapping is not None else row[3])
        if not task_id:
            continue
        age_days = 0.0
        if created_at is not None:
            age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
        candidates.append(
            {
                "task_id": str(task_id),
                "objective": str(objective or ""),
                "risk_level": str(risk_level or ""),
                "age_days": age_days,
            }
        )

    if not candidates:
        return 0

    already = _already_escalated_task_ids(db, [c["task_id"] for c in candidates])
    to_escalate = [c for c in candidates if c["task_id"] not in already]
    if not to_escalate:
        return 0

    if send_telegram:
        try:
            from app.services.telegram_notifier import telegram_notifier

            msg = _format_escalation_telegram(to_escalate, escalate_days=escalate_days)
            ok = telegram_notifier.send_message(
                msg,
                origin="AWS",
                chat_destination="ops",
            )
            if not ok:
                logger.warning(
                    "[APPROVAL_QUEUE] escalation Telegram send failed/blocked; will retry next run"
                )
                return 0
        except Exception as exc:
            logger.warning("[APPROVAL_QUEUE] escalation Telegram error: %s", exc)
            return 0

    audit_msg = (
        f"Escalated to ops after {escalate_days} days waiting "
        f"(risk_level in {list(levels)})."
    )
    for item in to_escalate:
        _record_escalation_audit(
            db, task_id=item["task_id"], msg=audit_msg, now=now
        )

    db.commit()
    logger.info(
        "[APPROVAL_QUEUE] Escalated %s Jarvis waiting task(s) older than %s days (risk=%s)",
        len(to_escalate),
        escalate_days,
        list(levels),
    )
    return len(to_escalate)


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
    """Refresh metrics, expire/dedupe waiting ACW tasks, escalate medium/high."""
    stats = refresh_approval_queue_metrics(db)
    expired = expire_stale_pending_approvals(db)
    jarvis_expired = expire_stale_jarvis_waiting_approvals(db)
    jarvis_deduped = dedupe_jarvis_waiting_approvals(db)
    jarvis_escalated = escalate_stale_jarvis_waiting_approvals(db)
    # Re-publish gauges after lifecycle cleanup so stale counts drop in the same run.
    if jarvis_expired or expired or jarvis_deduped:
        stats = refresh_approval_queue_metrics(db)
    return {
        **stats,
        "expired": expired,
        "jarvis_expired": jarvis_expired,
        "jarvis_deduped": jarvis_deduped,
        "jarvis_escalated": jarvis_escalated,
    }
