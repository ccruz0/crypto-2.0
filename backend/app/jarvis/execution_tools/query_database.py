"""Safe read-only database diagnostic queries for Jarvis."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_ROW_LIMIT = 50
_QUERY_TIMEOUT_SECONDS = 10

_WRITE_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|REPLACE|MERGE|CALL|EXEC)\b",
    re.IGNORECASE,
)
_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|api[_-]?secret|password|token|secret|authorization)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

_OPEN_STATUSES = ("NEW", "ACTIVE", "PARTIALLY_FILLED")

_PRESET_QUERIES: dict[str, str] = {
    "count_open_orders": (
        "SELECT COUNT(*) AS count FROM exchange_orders "
        f"WHERE status IN ({', '.join(repr(s) for s in _OPEN_STATUSES)})"
    ),
    "count_orders_by_status": (
        "SELECT status, COUNT(*) AS count FROM exchange_orders GROUP BY status ORDER BY count DESC"
    ),
    "recent_orders": (
        "SELECT id, exchange_order_id, symbol, side, status, quantity, created_at "
        "FROM exchange_orders ORDER BY created_at DESC"
    ),
    "open_positions": (
        "SELECT symbol, COUNT(*) AS open_commitments FROM exchange_orders "
        "WHERE side = 'BUY' AND status = 'FILLED' GROUP BY symbol HAVING COUNT(*) > 0"
    ),
    "recent_trade_events": (
        "SELECT id, exchange_order_id, symbol, side, status, quantity, created_at "
        "FROM exchange_orders WHERE status = 'FILLED' ORDER BY created_at DESC"
    ),
}


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=***REDACTED***", text)


def _validate_select_only(query: str) -> None:
    normalized = (query or "").strip()
    if not normalized:
        raise ValueError("Query must not be empty")
    if not re.match(r"^\s*SELECT\b", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT queries are permitted")
    if _WRITE_PATTERN.search(normalized):
        raise ValueError("Query contains forbidden write/DDL keywords")
    if ";" in normalized.rstrip(";"):
        raise ValueError("Multiple statements are not permitted")


def _ensure_limit(query: str, limit: int) -> str:
    if re.search(r"\bLIMIT\b", query, re.IGNORECASE):
        return query
    return f"{query.rstrip()} LIMIT {limit}"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "name"):
        return str(value.name)
    return value


def _serialize_row(row: Any) -> dict[str, Any]:
    if hasattr(row, "_mapping"):
        return {k: _serialize_value(v) for k, v in row._mapping.items()}
    if isinstance(row, (list, tuple)):
        return {"value": _serialize_value(row[0]) if len(row) == 1 else [_serialize_value(v) for v in row]}
    return {"value": _serialize_value(row)}


def _execute_query(query: str, *, limit: int) -> dict[str, Any]:
    from sqlalchemy import text

    from app.database import SessionLocal

    safe_query = _ensure_limit(query, limit)
    _validate_select_only(safe_query)
    redacted_query = _redact_secrets(safe_query)

    db = SessionLocal()
    rows: list[dict[str, Any]] = []
    row_count = 0
    try:
        result = db.execute(text(safe_query))
        if result.returns_rows:
            fetched = result.fetchmany(limit + 1)
            row_count = len(fetched)
            rows = [_serialize_row(row) for row in fetched[:limit]]
        else:
            row_count = result.rowcount or 0
    finally:
        db.close()

    logger.info("jarvis query_database executed rows=%s query=%s", row_count, redacted_query[:200])
    return {
        "query_executed": redacted_query,
        "row_count": row_count,
        "rows": rows,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def query_database(
    *,
    query: str | None = None,
    preset: str | None = None,
    limit: int = _DEFAULT_ROW_LIMIT,
    action: str | None = None,
    objective: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """
    Run an approved read-only SELECT query.

    Use ``preset`` for built-in diagnostics or pass a custom ``query`` (SELECT only).
    """
    row_limit = max(1, min(int(limit or _DEFAULT_ROW_LIMIT), 200))

    resolved_preset = preset
    if not resolved_preset and action:
        action_map = {
            "count_open_orders": "count_open_orders",
            "count_orders": "count_open_orders",
            "query_positions": "open_positions",
        }
        resolved_preset = action_map.get(action)

    if not resolved_preset and objective:
        obj_l = objective.lower()
        if "count" in obj_l and "open order" in obj_l:
            resolved_preset = "count_open_orders"

    if resolved_preset:
        if resolved_preset not in _PRESET_QUERIES:
            return {
                "tool": "query_database",
                "ok": False,
                "error": f"Unknown preset: {resolved_preset}",
                "available_presets": sorted(_PRESET_QUERIES.keys()),
                "read_only": True,
            }
        sql = _PRESET_QUERIES[resolved_preset]
    elif query:
        sql = query
    else:
        return {
            "tool": "query_database",
            "ok": False,
            "error": "Provide preset or SELECT query",
            "available_presets": sorted(_PRESET_QUERIES.keys()),
            "read_only": True,
        }

    try:
        result = _execute_query(sql, limit=row_limit)
    except Exception as exc:
        logger.warning("query_database failed: %s", exc)
        return {
            "tool": "query_database",
            "ok": False,
            "preset": resolved_preset,
            "error": str(exc),
            "read_only": True,
        }

    output: dict[str, Any] = {
        "tool": "query_database",
        "ok": True,
        "preset": resolved_preset,
        "read_only": True,
        **result,
    }

    if resolved_preset == "count_open_orders" and result["rows"]:
        count_val = result["rows"][0].get("count")
        if count_val is not None:
            output["count"] = int(count_val)
            output["numeric_result"] = int(count_val)

    if resolved_preset == "count_orders_by_status":
        output["status_counts"] = {
            str(row.get("status", "unknown")): int(row.get("count", 0)) for row in result["rows"]
        }

    return output
