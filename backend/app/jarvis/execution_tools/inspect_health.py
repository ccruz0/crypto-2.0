"""Read-only health inspection tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def inspect_health(*, endpoint: str = "/api/ping_fast") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": "inspect_health",
        "endpoint": endpoint,
        "status": "unknown",
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from app.jarvis.mvp.tools import check_dashboard_health

        health = check_dashboard_health()
        payload["status"] = health.get("status", "unknown")
        payload["details"] = health.get("details", {})
    except Exception as exc:
        payload["status"] = "degraded"
        payload["error"] = str(exc)
    return payload
