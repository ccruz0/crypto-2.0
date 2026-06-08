"""PostgreSQL/SQLite persistence for Jarvis Crypto Auditor runs."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import engine, ensure_jarvis_crypto_audit_runs_table

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


def _count_findings(audit_output: dict[str, Any]) -> int:
    return (
        len(audit_output.get("wallet_findings") or [])
        + len(audit_output.get("position_findings") or [])
        + len(audit_output.get("valuation_findings") or [])
        + len(audit_output.get("price_feed_findings") or [])
    )


def _max_severity(*finding_groups: list[dict[str, Any]]) -> str:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    best = "low"
    for group in finding_groups:
        for item in group:
            sev = str(item.get("severity") or "low").lower()
            if order.get(sev, 0) > order.get(best, 0):
                best = sev
    return best


def record_crypto_audit_run(
    *,
    task_id: str,
    audit_output: dict[str, Any],
    audit_id: str | None = None,
) -> str:
    """Insert a crypto audit run row. Returns audit_id."""
    if engine is None or not ensure_jarvis_crypto_audit_runs_table(engine):
        raise RuntimeError("Database unavailable for Jarvis crypto audit persistence")

    aid = audit_id or str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_crypto_audit_runs (
                    audit_id, task_id, summary_json, wallet_findings_json,
                    position_findings_json, valuation_findings_json,
                    price_feed_findings_json, recommendations_json,
                    portfolio_difference_usd, portfolio_difference_pct
                ) VALUES (
                    :audit_id, :task_id, :summary_json, :wallet_findings_json,
                    :position_findings_json, :valuation_findings_json,
                    :price_feed_findings_json, :recommendations_json,
                    :portfolio_difference_usd, :portfolio_difference_pct
                )
                """
            ),
            {
                "audit_id": aid,
                "task_id": task_id,
                "summary_json": _json_dumps(audit_output.get("summary") or {}),
                "wallet_findings_json": _json_dumps(audit_output.get("wallet_findings") or []),
                "position_findings_json": _json_dumps(audit_output.get("position_findings") or []),
                "valuation_findings_json": _json_dumps(audit_output.get("valuation_findings") or []),
                "price_feed_findings_json": _json_dumps(audit_output.get("price_feed_findings") or []),
                "recommendations_json": _json_dumps(audit_output.get("recommendations") or []),
                "portfolio_difference_usd": float(audit_output.get("portfolio_difference_usd") or 0.0),
                "portfolio_difference_pct": float(audit_output.get("portfolio_difference_pct") or 0.0),
            },
        )
    return aid


def _row_to_detail(row: Any) -> dict[str, Any]:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    wallet = _json_loads(mapping.get("wallet_findings_json"), [])
    position = _json_loads(mapping.get("position_findings_json"), [])
    valuation = _json_loads(mapping.get("valuation_findings_json"), [])
    price_feed = _json_loads(mapping.get("price_feed_findings_json"), [])
    total = len(wallet) + len(position) + len(valuation) + len(price_feed)
    return {
        "audit_id": mapping["audit_id"],
        "task_id": mapping.get("task_id"),
        "created_at": _isoformat(mapping.get("created_at")),
        "summary": _json_loads(mapping.get("summary_json"), {}),
        "wallet_findings": wallet,
        "position_findings": position,
        "valuation_findings": valuation,
        "price_feed_findings": price_feed,
        "recommendations": _json_loads(mapping.get("recommendations_json"), []),
        "portfolio_difference_usd": float(mapping.get("portfolio_difference_usd") or 0.0),
        "portfolio_difference_pct": float(mapping.get("portfolio_difference_pct") or 0.0),
        "finding_count": total,
        "severity": _max_severity(wallet, position, valuation, price_feed),
    }


def get_crypto_audit_run(audit_id: str) -> dict[str, Any] | None:
    if engine is None or not ensure_jarvis_crypto_audit_runs_table(engine):
        return None

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jarvis_crypto_audit_runs WHERE audit_id = :audit_id"),
            {"audit_id": audit_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_detail(row)


def list_crypto_audit_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    if engine is None or not ensure_jarvis_crypto_audit_runs_table(engine):
        return []

    safe_limit = max(1, min(limit, 100))
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT audit_id, task_id, summary_json, wallet_findings_json,
                       position_findings_json, valuation_findings_json,
                       price_feed_findings_json, portfolio_difference_usd,
                       portfolio_difference_pct, created_at
                FROM jarvis_crypto_audit_runs
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": safe_limit},
        ).fetchall()

    summaries: list[dict[str, Any]] = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        wallet = _json_loads(mapping.get("wallet_findings_json"), [])
        position = _json_loads(mapping.get("position_findings_json"), [])
        valuation = _json_loads(mapping.get("valuation_findings_json"), [])
        price_feed = _json_loads(mapping.get("price_feed_findings_json"), [])
        total = len(wallet) + len(position) + len(valuation) + len(price_feed)
        summaries.append(
            {
                "audit_id": mapping["audit_id"],
                "task_id": mapping.get("task_id"),
                "created_at": _isoformat(mapping.get("created_at")),
                "portfolio_difference_usd": float(mapping.get("portfolio_difference_usd") or 0.0),
                "portfolio_difference_pct": float(mapping.get("portfolio_difference_pct") or 0.0),
                "finding_count": total,
                "severity": _max_severity(wallet, position, valuation, price_feed),
            }
        )
    return summaries


def get_latest_crypto_audit_run() -> dict[str, Any] | None:
    runs = list_crypto_audit_runs(limit=1)
    return runs[0] if runs else None
