"""Read-only cost inspection tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def inspect_costs(*, period: str = "last_7_days") -> dict[str, Any]:
    try:
        from app.jarvis.mvp.tools import get_aws_cost_snapshot_stub

        snapshot = get_aws_cost_snapshot_stub()
    except Exception as exc:
        snapshot = {"error": str(exc)}
    return {
        "tool": "inspect_costs",
        "period": period,
        "snapshot": snapshot,
        "read_only": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
