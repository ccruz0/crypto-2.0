"""Read-only log inspection tool."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def read_logs(*, lines: int = 20, source: str = "application") -> dict[str, Any]:
    limit = max(1, min(int(lines or 20), 100))
    return {
        "tool": "read_logs",
        "source": source,
        "lines_requested": limit,
        "entries": [
            {"ts": datetime.now(timezone.utc).isoformat(), "level": "INFO", "message": f"Sample log line {i}"}
            for i in range(1, min(limit, 5) + 1)
        ],
        "read_only": True,
        "note": "Stub log summary for investigation tasks; no live tail in Phase 3.",
    }
