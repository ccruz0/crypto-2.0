"""Store for the current day's brief actions (backs the Telegram buttons).

The backend cannot read `claude/brief-acciones.md` (that lives in the Claude
project), so the brief POSTs the same content to /api/brief/actions and this
module persists it. Actions live one day; a JSON file with a TTL is enough and
avoids adding a migration to a production trading backend.

Path: BRIEF_ACTIONS_PATH (default /data/brief/actions.json). /data is already a
persistent volume — it holds the Telethon session.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BALI = timezone(timedelta(hours=8))
TTL_HOURS = 48
_DEFAULT_PATH = "/data/brief/actions.json"


class ActionAccount(str, Enum):
    RAHYANG = "rahyang"          # Microsoft Graph, sendable from the backend
    IMAP = "imap"                # needs brief_mail_send.py deployed
    HOTMAIL_MAC = "hotmail_mac"  # never sendable from the backend


class ActionStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    CANCELLED = "cancelled"


class BriefAction(BaseModel):
    number: int
    label: str = ""
    account: ActionAccount
    account_id: Optional[str] = None
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    draft: str = ""
    thread_ref: Optional[str] = None
    has_pending: bool = False
    status: ActionStatus = ActionStatus.PENDING
    resolved_at: Optional[str] = None


class BriefActionsPayload(BaseModel):
    date: str = ""  # YYYY-MM-DD, Bali
    actions: list[BriefAction] = Field(default_factory=list)


def _path() -> Path:
    return Path((os.getenv("BRIEF_ACTIONS_PATH") or _DEFAULT_PATH).strip() or _DEFAULT_PATH)


def today_bali() -> str:
    return datetime.now(BALI).strftime("%Y-%m-%d")


def _read_raw() -> dict[str, Any]:
    path = _path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:  # noqa: BLE001
        logger.warning("brief_actions_read_failed error=%s", type(exc).__name__)
        return {}


def _write_raw(data: dict[str, Any]) -> None:
    """Atomic write: temp file in the same directory, then rename."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".actions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _expired(stored_at: str) -> bool:
    try:
        stamp = datetime.fromisoformat(stored_at)
    except (TypeError, ValueError):
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp > timedelta(hours=TTL_HOURS)


def replace_today(payload: BriefActionsPayload) -> int:
    """Overwrite today's actions. Returns how many were stored."""
    data = {
        "date": (payload.date or "").strip() or today_bali(),
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "actions": [action.model_dump(mode="json") for action in payload.actions],
    }
    _write_raw(data)
    logger.info("brief_actions_stored count=%s date=%s", len(payload.actions), data["date"])
    return len(payload.actions)


def get_today(number: int) -> Optional[BriefAction]:
    """Action N for today, or None if absent, from another day, or expired."""
    data = _read_raw()
    if not data:
        return None
    if data.get("date") != today_bali():
        logger.info("brief_actions_stale stored=%s today=%s", data.get("date"), today_bali())
        return None
    if _expired(str(data.get("stored_at") or "")):
        logger.info("brief_actions_expired ttl_hours=%s", TTL_HOURS)
        return None
    for raw in data.get("actions") or []:
        if raw.get("number") == number:
            try:
                return BriefAction.model_validate(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("brief_action_malformed number=%s error=%s", number, type(exc).__name__)
                return None
    return None


def mark(number: int, status: ActionStatus) -> bool:
    """Move an action out of PENDING. Returns True only if this call changed it.

    This is the lock against double sends: a second click sees False and must
    not send. Callers treat False as "do not proceed".
    """
    data = _read_raw()
    if not data or data.get("date") != today_bali():
        return False
    for raw in data.get("actions") or []:
        if raw.get("number") != number:
            continue
        if status != ActionStatus.PENDING and raw.get("status") != ActionStatus.PENDING.value:
            return False
        raw["status"] = status.value
        raw["resolved_at"] = datetime.now(timezone.utc).isoformat()
        _write_raw(data)
        logger.info("brief_action_marked number=%s status=%s", number, status.value)
        return True
    return False
