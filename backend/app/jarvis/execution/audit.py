"""Execution audit log persistence for Jarvis tasks."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_execution_log_table

logger = logging.getLogger(__name__)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value is not None else ""


def log_execution_event(
    *,
    task_id: str,
    agent: str,
    tool: str,
    input_summary: str,
    output_summary: str,
    duration_ms: int,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Append one row to jarvis_execution_log."""
    log_id = str(uuid.uuid4())
    if engine is None or not ensure_jarvis_execution_log_table(engine):
        logger.warning("jarvis_execution_log unavailable; skipping audit row task_id=%s", task_id)
        return log_id

    payload = json.dumps(metadata or {})
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_execution_log (
                    log_id, task_id, agent, tool, input_summary, output_summary,
                    duration_ms, metadata_json, created_at
                ) VALUES (
                    :log_id, :task_id, :agent, :tool, :input_summary, :output_summary,
                    :duration_ms, :metadata_json, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "log_id": log_id,
                "task_id": task_id,
                "agent": agent,
                "tool": tool,
                "input_summary": input_summary[:2000],
                "output_summary": output_summary[:4000],
                "duration_ms": int(duration_ms),
                "metadata_json": payload,
            },
        )
    return log_id


def list_execution_log(task_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_execution_log_table(engine):
        return []
    safe_limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT log_id, task_id, agent, tool, input_summary, output_summary,
                       duration_ms, metadata_json, created_at
                FROM jarvis_execution_log
                WHERE task_id = :task_id
                ORDER BY created_at ASC
                LIMIT :limit
                """
            ),
            {"task_id": task_id, "limit": safe_limit},
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        m = row._mapping if hasattr(row, "_mapping") else row
        meta_raw = m.get("metadata_json")
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        except json.JSONDecodeError:
            meta = {}
        out.append(
            {
                "log_id": m["log_id"],
                "task_id": m["task_id"],
                "agent": m["agent"],
                "tool": m["tool"],
                "input_summary": m["input_summary"],
                "output_summary": m["output_summary"],
                "duration_ms": int(m.get("duration_ms") or 0),
                "metadata": meta,
                "timestamp": _iso(m.get("created_at")),
            }
        )
    return out
