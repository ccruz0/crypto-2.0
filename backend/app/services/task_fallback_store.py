"""
Local fallback store for tasks when Notion is unavailable.

Stores tasks in a JSON file so they are not lost. retry_failed_notion_tasks()
(invoked from the scheduler) pushes them to Notion and removes on success.

Logging: fallback_task_created, fallback_task_synced (in retry).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATUS_PENDING_SYNC = "pending_notion_sync"

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data"
_ENV_KEY = "TASK_FALLBACK_STORE_PATH"
_lock = threading.Lock()


def _get_store_path() -> Path:
    raw = (os.environ.get(_ENV_KEY) or "").strip()
    if raw:
        return Path(raw)
    _DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_DIR / "task_fallback.json"


def _load_store() -> dict[str, Any]:
    path = _get_store_path()
    if not path.exists():
        return {"tasks": [], "version": 1}
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) and "tasks" in data else {"tasks": [], "version": 1}
        except Exception as e:
            logger.warning("task_fallback_store: load failed path=%s err=%s", path, e)
            return {"tasks": [], "version": 1}


def _save_store(data: dict[str, Any]) -> bool:
    path = _get_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error("task_fallback_store: save failed path=%s err=%s", path, e)
            return False


def store_fallback_task(task: dict[str, Any]) -> Optional[str]:
    """
    Store a compiled task locally when Notion creation failed.
    Marks as pending_notion_sync. Returns fallback_id or None on storage failure.
    """
    if not task or not isinstance(task, dict):
        logger.error("fallback_task_created failure: task empty or not dict")
        return None
    fallback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "id": fallback_id,
        "task": dict(task),
        "created_at": now,
        "status": STATUS_PENDING_SYNC,
    }
    data = _load_store()
    data["tasks"] = data.get("tasks") or []
    data["tasks"].append(entry)
    if not _save_store(data):
        return None
    logger.info("fallback_task_created fallback_id=%s title=%r", fallback_id, (task.get("title") or "")[:50])
    return fallback_id


def get_pending_fallback_tasks() -> list[dict[str, Any]]:
    """Return list of stored entries with status pending_notion_sync."""
    data = _load_store()
    tasks = data.get("tasks") or []
    return [t for t in tasks if isinstance(t, dict) and (t.get("status") or "") == STATUS_PENDING_SYNC]


def remove_fallback_task(fallback_id: str) -> bool:
    """Remove an entry by id. Returns True if removed."""
    if not (fallback_id or "").strip():
        return False
    data = _load_store()
    tasks = data.get("tasks") or []
    new_tasks = [t for t in tasks if isinstance(t, dict) and str(t.get("id") or "") != str(fallback_id)]
    if len(new_tasks) == len(tasks):
        return False
    data["tasks"] = new_tasks
    return _save_store(data)
