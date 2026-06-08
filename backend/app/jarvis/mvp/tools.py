"""Read-only stub tools for Jarvis LangGraph MVP."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from app.jarvis.mvp.config import bedrock_model_id, bedrock_region, jarvis_dry_run_only, jarvis_enabled

logger = logging.getLogger(__name__)

READONLY_TOOLS: frozenset[str] = frozenset(
    {
        "check_dashboard_health",
        "get_runtime_status",
        "get_aws_cost_snapshot_stub",
        "get_recent_logs_stub",
    }
)


def check_dashboard_health() -> dict[str, Any]:
    """Return a lightweight dashboard health snapshot (read-only)."""
    payload: dict[str, Any] = {
        "tool": "check_dashboard_health",
        "status": "ok",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "details": {"source": "jarvis_mvp_stub"},
    }
    try:
        from app.services.system_health import get_system_health
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            if db is not None:
                health = get_system_health(db)
                payload["status"] = str(health.get("global_status") or "unknown").lower()
                payload["details"] = {
                    "global_status": health.get("global_status"),
                    "checks": list((health.get("checks") or {}).keys())[:10],
                    "source": "system_health",
                }
        finally:
            if db is not None:
                db.close()
    except Exception as exc:
        logger.warning("check_dashboard_health fallback: %s", exc)
        payload["status"] = "degraded"
        payload["details"]["error"] = str(exc)
    return payload


def get_runtime_status() -> dict[str, Any]:
    """Return runtime environment status (read-only)."""
    return {
        "tool": "get_runtime_status",
        "environment": os.environ.get("ENVIRONMENT", "unknown"),
        "runtime_origin": os.environ.get("RUNTIME_ORIGIN", "unknown"),
        "jarvis_enabled": jarvis_enabled(),
        "jarvis_dry_run_only": jarvis_dry_run_only(),
        "bedrock_region": bedrock_region(),
        "bedrock_model_id": bedrock_model_id(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def get_aws_cost_snapshot_stub() -> dict[str, Any]:
    """Stub AWS cost snapshot — no live Cost Explorer calls in MVP."""
    return {
        "tool": "get_aws_cost_snapshot_stub",
        "period": "last_7_days",
        "currency": "USD",
        "estimated_total_usd": 42.50,
        "note": "Stub data for MVP; wire Cost Explorer in a later iteration.",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def get_recent_logs_stub(*, lines: int = 20) -> dict[str, Any]:
    """Stub recent logs — no live log tail in MVP."""
    limit = max(1, min(int(lines or 20), 100))
    return {
        "tool": "get_recent_logs_stub",
        "lines_requested": limit,
        "entries": [
            {"level": "INFO", "message": "jarvis.mvp stub log entry", "timestamp": datetime.now(timezone.utc).isoformat()},
        ],
        "note": "Stub data for MVP; wire CloudWatch or app logs in a later iteration.",
    }


_TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "check_dashboard_health": lambda **_kwargs: check_dashboard_health(),
    "get_runtime_status": lambda **_kwargs: get_runtime_status(),
    "get_aws_cost_snapshot_stub": lambda **_kwargs: get_aws_cost_snapshot_stub(),
    "get_recent_logs_stub": lambda **kwargs: get_recent_logs_stub(lines=int(kwargs.get("lines") or 20)),
}


def run_readonly_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute an approved read-only tool or return a safe error."""
    tool = (name or "").strip()
    if tool not in READONLY_TOOLS:
        return {
            "tool": tool,
            "success": False,
            "error": f"Tool '{tool}' is not in the MVP read-only allowlist.",
        }
    handler = _TOOL_HANDLERS[tool]
    try:
        result = handler(**(args or {}))
        return {"success": True, **result}
    except Exception as exc:
        logger.exception("jarvis.mvp tool_failed tool=%s", tool)
        return {"tool": tool, "success": False, "error": str(exc)}
