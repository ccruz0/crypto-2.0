"""PostgreSQL/SQLite persistence for Jarvis AWS Auditor runs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_audit_runs_table

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


def record_audit_run(
    *,
    task_id: str,
    audit_output: dict[str, Any],
    audit_id: str | None = None,
) -> str:
    """Insert an AWS audit run row. Returns audit_id."""
    if engine is None or not ensure_jarvis_audit_runs_table(engine):
        raise RuntimeError("Database unavailable for Jarvis audit persistence")

    aid = audit_id or str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_audit_runs (
                    audit_id, task_id, summary_json, cost_findings_json,
                    security_findings_json, resource_findings_json,
                    recommendations_json, estimated_monthly_savings
                ) VALUES (
                    :audit_id, :task_id, :summary_json, :cost_findings_json,
                    :security_findings_json, :resource_findings_json,
                    :recommendations_json, :estimated_monthly_savings
                )
                """
            ),
            {
                "audit_id": aid,
                "task_id": task_id,
                "summary_json": _json_dumps(audit_output.get("summary") or {}),
                "cost_findings_json": _json_dumps(audit_output.get("cost_findings") or []),
                "security_findings_json": _json_dumps(audit_output.get("security_findings") or []),
                "resource_findings_json": _json_dumps(audit_output.get("resource_findings") or []),
                "recommendations_json": _json_dumps(audit_output.get("recommendations") or []),
                "estimated_monthly_savings": float(audit_output.get("estimated_monthly_savings") or 0.0),
            },
        )
    return aid


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    cost = _json_loads(mapping.get("cost_findings_json"), [])
    security = _json_loads(mapping.get("security_findings_json"), [])
    resource = _json_loads(mapping.get("resource_findings_json"), [])
    return {
        "audit_id": mapping["audit_id"],
        "task_id": mapping.get("task_id"),
        "created_at": _isoformat(mapping.get("created_at")),
        "summary": _json_loads(mapping.get("summary_json"), {}),
        "cost_findings": cost,
        "security_findings": security,
        "resource_findings": resource,
        "recommendations": _json_loads(mapping.get("recommendations_json"), []),
        "estimated_monthly_savings": float(mapping.get("estimated_monthly_savings") or 0.0),
        "finding_counts": {
            "cost": len(cost),
            "security": len(security),
            "resource": len(resource),
            "total": len(cost) + len(security) + len(resource),
        },
        "severity": _max_severity(cost, security, resource),
    }


def _max_severity(*finding_groups: list[dict[str, Any]]) -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    best = "low"
    for group in finding_groups:
        for item in group:
            sev = str(item.get("severity") or "low").lower()
            if order.get(sev, 0) > order.get(best, 0):
                best = sev
    return best


def get_audit_run(audit_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_audit_runs_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_audit_runs WHERE audit_id = :audit_id"),
            {"audit_id": audit_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_audit_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_audit_runs_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT audit_id, task_id, summary_json, cost_findings_json,
                       security_findings_json, resource_findings_json,
                       estimated_monthly_savings, created_at
                FROM jarvis_audit_runs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    summaries: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        cost = _json_loads(mapping.get("cost_findings_json"), [])
        security = _json_loads(mapping.get("security_findings_json"), [])
        resource = _json_loads(mapping.get("resource_findings_json"), [])
        summaries.append(
            {
                "audit_id": mapping["audit_id"],
                "task_id": mapping.get("task_id"),
                "created_at": _isoformat(mapping.get("created_at")),
                "estimated_monthly_savings": float(mapping.get("estimated_monthly_savings") or 0.0),
                "finding_counts": {
                    "cost": len(cost),
                    "security": len(security),
                    "resource": len(resource),
                    "total": len(cost) + len(security) + len(resource),
                },
                "severity": _max_severity(cost, security, resource),
            }
        )
    return summaries
