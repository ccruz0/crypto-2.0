"""Database persistence for Jarvis alerts and daily reports."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_alerting_tables
from app.jarvis.investigations.alerting.types import AlertInput, AlertRecord, AlertStatus

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


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


def ensure_tables() -> bool:
    if engine is None:
        return False
    return ensure_jarvis_alerting_tables(engine)


def _row_to_alert(row: Any) -> AlertRecord:
    evidence_raw = row.evidence or "[]"
    try:
        evidence = json.loads(evidence_raw) if isinstance(evidence_raw, str) else list(evidence_raw or [])
    except (json.JSONDecodeError, TypeError):
        evidence = []
    return AlertRecord(
        alert_id=row.alert_id,
        created_at=_iso(_parse_dt(row.created_at)) or "",
        updated_at=_iso(_parse_dt(row.updated_at)) or "",
        severity=str(row.severity),
        source=str(row.source),
        investigation_id=row.investigation_id,
        title=str(row.title),
        summary=str(row.summary or ""),
        evidence=evidence,
        status=str(row.status),
        fingerprint=str(row.fingerprint),
        occurrence_count=int(row.occurrence_count or 1),
        first_seen=_iso(_parse_dt(row.first_seen)) or "",
        last_seen=_iso(_parse_dt(row.last_seen)) or "",
    )


def upsert_alert(
    alert_input: AlertInput,
    *,
    fingerprint: str,
    suppression_window_hours: int,
) -> AlertRecord:
    """Create or deduplicate an alert within the suppression window."""
    if not ensure_tables():
        raise RuntimeError("jarvis alerting tables unavailable")

    now = _now_utc()
    cutoff = now - timedelta(hours=max(1, suppression_window_hours))
    evidence_json = json.dumps(alert_input.evidence or [])

    with engine.begin() as conn:
        existing = conn.execute(
            text(
                """
                SELECT * FROM jarvis_alerts
                WHERE fingerprint = :fingerprint
                  AND status IN ('open', 'acknowledged')
                  AND last_seen >= :cutoff
                ORDER BY last_seen DESC
                LIMIT 1
                """
            ),
            {"fingerprint": fingerprint, "cutoff": cutoff},
        ).fetchone()

        if existing:
            conn.execute(
                text(
                    """
                    UPDATE jarvis_alerts
                    SET occurrence_count = occurrence_count + 1,
                        last_seen = :last_seen,
                        updated_at = :updated_at,
                        summary = :summary,
                        evidence = :evidence,
                        investigation_id = COALESCE(:investigation_id, investigation_id)
                    WHERE alert_id = :alert_id
                    """
                ),
                {
                    "alert_id": existing.alert_id,
                    "last_seen": now,
                    "updated_at": now,
                    "summary": alert_input.summary,
                    "evidence": evidence_json,
                    "investigation_id": alert_input.investigation_id,
                },
            )
            updated = conn.execute(
                text("SELECT * FROM jarvis_alerts WHERE alert_id = :alert_id"),
                {"alert_id": existing.alert_id},
            ).fetchone()
            record = _row_to_alert(updated)
            record.deduplicated = True
            return record

        alert_id = f"alert-{uuid.uuid4().hex[:12]}"
        conn.execute(
            text(
                """
                INSERT INTO jarvis_alerts (
                    alert_id, created_at, updated_at, severity, source, fingerprint,
                    title, summary, evidence, investigation_id, occurrence_count,
                    status, first_seen, last_seen
                ) VALUES (
                    :alert_id, :created_at, :updated_at, :severity, :source, :fingerprint,
                    :title, :summary, :evidence, :investigation_id, 1,
                    :status, :first_seen, :last_seen
                )
                """
            ),
            {
                "alert_id": alert_id,
                "created_at": now,
                "updated_at": now,
                "severity": alert_input.severity.value,
                "source": alert_input.source,
                "fingerprint": fingerprint,
                "title": alert_input.title,
                "summary": alert_input.summary,
                "evidence": evidence_json,
                "investigation_id": alert_input.investigation_id,
                "status": AlertStatus.OPEN.value,
                "first_seen": now,
                "last_seen": now,
            },
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_alerts WHERE alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).fetchone()
        return _row_to_alert(row)


def list_alerts(
    *,
    limit: int = 100,
    status: str | None = None,
    severity: str | None = None,
) -> list[AlertRecord]:
    if not ensure_tables():
        return []
    clauses = ["1=1"]
    params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if severity:
        clauses.append("severity = :severity")
        params["severity"] = severity
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT * FROM jarvis_alerts
                WHERE {where}
                ORDER BY last_seen DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    return [_row_to_alert(row) for row in rows]


def get_alert(alert_id: str) -> AlertRecord | None:
    if not ensure_tables():
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_alerts WHERE alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).fetchone()
    return _row_to_alert(row) if row else None


def update_alert_status(alert_id: str, status: AlertStatus) -> AlertRecord | None:
    if not ensure_tables():
        return None
    now = _now_utc()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE jarvis_alerts
                SET status = :status, updated_at = :updated_at
                WHERE alert_id = :alert_id
                """
            ),
            {"alert_id": alert_id, "status": status.value, "updated_at": now},
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_alerts WHERE alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).fetchone()
    return _row_to_alert(row) if row else None


def count_alerts_since(*, since: datetime, severity: str | None = None) -> int:
    if not ensure_tables():
        return 0
    params: dict[str, Any] = {"since": since}
    clause = ""
    if severity:
        clause = "AND severity = :severity"
        params["severity"] = severity
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT COUNT(*) AS cnt FROM jarvis_alerts
                WHERE created_at >= :since {clause}
                """
            ),
            params,
        ).fetchone()
    return int(row.cnt if row else 0)


def top_recurring_issues(*, since: datetime, limit: int = 5) -> list[dict[str, Any]]:
    if not ensure_tables():
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT title, fingerprint, SUM(occurrence_count) AS total_occurrences,
                       MAX(severity) AS max_severity
                FROM jarvis_alerts
                WHERE created_at >= :since
                GROUP BY fingerprint, title
                ORDER BY total_occurrences DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": max(1, limit)},
        ).fetchall()
    return [
        {
            "title": row.title,
            "fingerprint": row.fingerprint,
            "occurrence_count": int(row.total_occurrences or 0),
            "severity": row.max_severity,
        }
        for row in rows
    ]


def save_daily_report(*, report_date: date, summary: dict[str, Any]) -> dict[str, Any]:
    if not ensure_tables():
        raise RuntimeError("jarvis alerting tables unavailable")
    report_id = f"report-{report_date.isoformat()}-{uuid.uuid4().hex[:8]}"
    now = _now_utc()
    summary_json = json.dumps(summary)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_daily_reports (report_id, report_date, generated_at, summary_json)
                VALUES (:report_id, :report_date, :generated_at, :summary_json)
                ON CONFLICT (report_date) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    summary_json = excluded.summary_json
                """
            ),
            {
                "report_id": report_id,
                "report_date": report_date,
                "generated_at": now,
                "summary_json": summary_json,
            },
        )
        row = conn.execute(
            text("SELECT * FROM jarvis_daily_reports WHERE report_date = :report_date"),
            {"report_date": report_date},
        ).fetchone()
    return _row_to_daily_report(row)


def list_daily_reports(*, limit: int = 30) -> list[dict[str, Any]]:
    if not ensure_tables():
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM jarvis_daily_reports
                ORDER BY report_date DESC
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(limit, 200))},
        ).fetchall()
    return [_row_to_daily_report(row) for row in rows]


def get_daily_report(report_id: str) -> dict[str, Any] | None:
    if not ensure_tables():
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_daily_reports WHERE report_id = :report_id"),
            {"report_id": report_id},
        ).fetchone()
    return _row_to_daily_report(row) if row else None


def get_daily_report_for_date(report_date: date) -> dict[str, Any] | None:
    if not ensure_tables():
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_daily_reports WHERE report_date = :report_date"),
            {"report_date": report_date},
        ).fetchone()
    return _row_to_daily_report(row) if row else None


def _row_to_daily_report(row: Any) -> dict[str, Any]:
    try:
        summary = json.loads(row.summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    return {
        "id": int(row.id),
        "report_id": row.report_id,
        "report_date": str(row.report_date),
        "generated_at": _iso(_parse_dt(row.generated_at)) or "",
        "summary": summary,
        "summary_json": row.summary_json,
    }
