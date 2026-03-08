"""
Lightweight structured activity log for the agent workflow.

Records major agent events (task prepared, approval requested, execution started/completed/failed, etc.)
to a JSONL file. Logging failures are never allowed to break execution.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Log file relative to repo root
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "agent_activity.jsonl"

_WRITE_LOCK = threading.Lock()


def _repo_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def _log_path() -> Path:
    return _repo_root() / LOG_DIR_NAME / LOG_FILE_NAME


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def log_agent_event(
    event_type: str,
    *,
    task_id: str | None = None,
    task_title: str | None = None,
    details: dict | None = None,
) -> None:
    """
    Append one event to the agent activity log (JSONL). Never raises; logs and swallows errors.
    """
    entry = {
        "timestamp": _utc_now_iso(),
        "event_type": str(event_type or "").strip() or "unknown",
        "task_id": (task_id or "").strip() or None,
        "task_title": (task_title or "").strip() or None,
        "details": dict(details) if details else {},
    }
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        logger.debug("agent_activity_log: write failed (non-fatal): %s", e)


def get_recent_agent_events(limit: int = 50) -> list[dict[str, Any]]:
    """
    Read the last N events from the activity log. Newest first.
    Returns empty list if file missing or on read error.
    """
    if limit <= 0:
        return []
    try:
        path = _log_path()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        # Last N lines, then reverse so newest first
        recent = lines[-limit:] if len(lines) > limit else lines
        out: list[dict[str, Any]] = []
        for line in reversed(recent):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except Exception as e:
        logger.debug("agent_activity_log: read failed: %s", e)
        return []
