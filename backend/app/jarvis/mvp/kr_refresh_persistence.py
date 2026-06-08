"""Persistence for KR metric refresh runs and KR metric metadata."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import (
    engine,
    ensure_jarvis_key_results_metric_columns,
    ensure_jarvis_key_results_table,
    ensure_jarvis_kr_refresh_runs_table,
)

logger = logging.getLogger(__name__)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def list_key_results_with_metrics() -> list[dict[str, Any]]:
    """Return all KRs that have a metric_name configured."""
    if engine is None or not ensure_jarvis_key_results_table(engine):
        return []

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT kr_id, objective_id, title, metric_name,
                       target_value, current_value, unit, direction, status
                FROM jarvis_key_results
                WHERE metric_name IS NOT NULL AND TRIM(metric_name) != ''
                ORDER BY objective_id, created_at
                """
            ),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        results.append({key: mapping[key] for key in mapping.keys()})
    return results


def update_kr_from_metric(
    *,
    kr_id: str,
    current_value: float,
    metric_source: str,
    status: str,
) -> bool:
    """Update KR current value and refresh metadata after metric resolution."""
    if engine is None or not ensure_jarvis_key_results_table(engine):
        return False
    ensure_jarvis_key_results_metric_columns(engine)

    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE jarvis_key_results
                SET current_value = :current_value,
                    metric_source = :metric_source,
                    last_refreshed_at = :last_refreshed_at,
                    status = :status,
                    updated_at = :updated_at
                WHERE kr_id = :kr_id
                """
            ),
            {
                "kr_id": kr_id,
                "current_value": float(current_value),
                "metric_source": metric_source,
                "last_refreshed_at": now,
                "updated_at": now,
                "status": status,
            },
        )
    return result.rowcount > 0  # type: ignore[union-attr]


def record_kr_refresh_run(
    *,
    kr_count: int,
    updated_count: int,
    failed_count: int,
    errors: list[dict[str, Any]] | None = None,
    refresh_id: str | None = None,
) -> str:
    """Store a KR refresh run summary."""
    if engine is None or not ensure_jarvis_kr_refresh_runs_table(engine):
        raise RuntimeError("Database unavailable for KR refresh run persistence")

    rid = refresh_id or str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_kr_refresh_runs (
                    refresh_id, kr_count, updated_count, failed_count, errors_json
                ) VALUES (
                    :refresh_id, :kr_count, :updated_count, :failed_count, :errors_json
                )
                """
            ),
            {
                "refresh_id": rid,
                "kr_count": int(kr_count),
                "updated_count": int(updated_count),
                "failed_count": int(failed_count),
                "errors_json": json.dumps(errors or []),
            },
        )
    return rid


def list_kr_refresh_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent KR refresh runs (newest first)."""
    if engine is None or not ensure_jarvis_kr_refresh_runs_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT refresh_id, created_at, kr_count, updated_count,
                       failed_count, errors_json
                FROM jarvis_kr_refresh_runs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        errors_raw = mapping.get("errors_json")
        try:
            errors = json.loads(errors_raw) if errors_raw else []
        except (TypeError, json.JSONDecodeError):
            errors = []
        results.append({
            "refresh_id": mapping["refresh_id"],
            "created_at": _isoformat(mapping.get("created_at")),
            "kr_count": int(mapping.get("kr_count") or 0),
            "updated_count": int(mapping.get("updated_count") or 0),
            "failed_count": int(mapping.get("failed_count") or 0),
            "errors": errors,
        })
    return results


def get_latest_kr_refresh_run() -> dict[str, Any] | None:
    runs = list_kr_refresh_runs(limit=1)
    return runs[0] if runs else None
