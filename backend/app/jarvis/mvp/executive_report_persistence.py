"""PostgreSQL/SQLite persistence for Jarvis Chief of Staff executive reports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_executive_reports_table

logger = logging.getLogger(__name__)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [])


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def record_executive_report(*, report: dict[str, Any]) -> str:
    """Insert an executive report row. Returns report_id."""
    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        raise RuntimeError("Database unavailable for Jarvis executive report persistence")

    report_id = report["report_id"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_executive_reports (
                    report_id, generated_at, overall_health_score,
                    top_priorities_json, quick_wins_json,
                    strategic_items_json, blocked_items_json,
                    lessons_learned_json, execution_review_json, execution_status_json,
                    followup_review_json, strategic_alignment_json
                ) VALUES (
                    :report_id, :generated_at, :overall_health_score,
                    :top_priorities_json, :quick_wins_json,
                    :strategic_items_json, :blocked_items_json,
                    :lessons_learned_json, :execution_review_json, :execution_status_json,
                    :followup_review_json, :strategic_alignment_json
                )
                """
            ),
            {
                "report_id": report_id,
                "generated_at": report.get("generated_at"),
                "overall_health_score": int(report.get("overall_health_score") or 0),
                "top_priorities_json": _json_dumps(report.get("top_priorities") or []),
                "quick_wins_json": _json_dumps(report.get("quick_wins") or []),
                "strategic_items_json": _json_dumps(report.get("strategic_items") or []),
                "blocked_items_json": _json_dumps(report.get("blocked_items") or []),
                "lessons_learned_json": _json_dumps(report.get("lessons_learned") or []),
                "execution_review_json": _json_dumps(report.get("execution_review") or {}),
                "execution_status_json": _json_dumps(report.get("execution_status") or {}),
                "followup_review_json": _json_dumps(report.get("followup_review") or {}),
                "strategic_alignment_json": _json_dumps(report.get("strategic_alignment") or {}),
            },
        )
    return report_id


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    return {
        "report_id": mapping["report_id"],
        "generated_at": _isoformat(mapping.get("generated_at")),
        "overall_health_score": int(mapping.get("overall_health_score") or 0),
        "top_priorities": _json_loads(mapping.get("top_priorities_json"), []),
        "quick_wins": _json_loads(mapping.get("quick_wins_json"), []),
        "strategic_items": _json_loads(mapping.get("strategic_items_json"), []),
        "blocked_items": _json_loads(mapping.get("blocked_items_json"), []),
        "lessons_learned": _json_loads(mapping.get("lessons_learned_json"), []),
        "execution_review": _json_loads(mapping.get("execution_review_json"), {}),
        "execution_status": _json_loads(mapping.get("execution_status_json"), {}),
        "followup_review": _json_loads(mapping.get("followup_review_json"), {}),
        "strategic_alignment": _json_loads(mapping.get("strategic_alignment_json"), {}),
        "read_only": True,
        "execution_performed": False,
    }


def get_executive_report(report_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_executive_reports WHERE report_id = :report_id"),
            {"report_id": report_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_executive_reports(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT report_id, generated_at, overall_health_score,
                       top_priorities_json, quick_wins_json
                FROM jarvis_executive_reports
                ORDER BY generated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    summaries: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        top_priorities = _json_loads(mapping.get("top_priorities_json"), [])
        quick_wins = _json_loads(mapping.get("quick_wins_json"), [])
        summaries.append(
            {
                "report_id": mapping["report_id"],
                "generated_at": _isoformat(mapping.get("generated_at")),
                "overall_health_score": int(mapping.get("overall_health_score") or 0),
                "top_priority_count": len(top_priorities),
                "quick_win_count": len(quick_wins),
                "top_priority_title": top_priorities[0]["title"] if top_priorities else None,
            }
        )
    return summaries


def get_latest_executive_report() -> dict[str, Any] | None:
    reports = list_executive_reports(limit=1)
    if not reports:
        return None
    return get_executive_report(reports[0]["report_id"])


def report_generated_within_days(*, days: int = 6) -> bool:
    """Return True if a report was generated within the last N days (weekly dedup)."""
    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        return False

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT generated_at FROM jarvis_executive_reports
                ORDER BY generated_at DESC
                LIMIT 1
                """
            )
        ).fetchone()
    if row is None:
        return False

    mapping = row._mapping if hasattr(row, "_mapping") else row
    generated_at = mapping.get("generated_at")
    if generated_at is None:
        return False

    if isinstance(generated_at, str):
        try:
            generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            return False
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    age = datetime.now(timezone.utc) - generated_at
    return age.days < days
