"""Read-only log inspection tool (delegates to search_logs)."""

from __future__ import annotations

from typing import Any

from app.jarvis.execution_tools.search_logs import search_logs


def read_logs(
    *,
    lines: int = 20,
    source: str = "application",
    objective: str | None = None,
    action: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Gather recent log lines; uses search_logs for live docker/local log tail."""
    tail = max(1, min(int(lines or 20), 500))
    result = search_logs(
        service=source if source not in ("application", "backend") else None,
        tail=tail,
        max_matches=min(tail, 50),
        objective=objective,
        action=action,
        **kwargs,
    )
    entries = [
        {
            "ts": m.get("timestamp") or "",
            "level": "LOG",
            "message": m.get("message", ""),
            "source": m.get("source", source),
        }
        for m in result.get("matches", [])
    ]
    return {
        "tool": "read_logs",
        "source": source,
        "lines_requested": tail,
        "entries": entries,
        "match_count": result.get("match_count", 0),
        "read_only": True,
    }
