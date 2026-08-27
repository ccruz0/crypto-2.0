"""Store for the current day's brief actions.

Backs the approval buttons. The button NEVER sends mail: it only records that
Carlos approved or discarded an action. The send still goes through a Claude
session, which reads this store and compares the draft it is about to send with
the one that was approved.

Design notes that are load-bearing, not decoration:

* Every action gets an OPAQUE id, generated here. `callback_data` carries that
  id, never the position. An earlier design used the action number: re-running
  the brief on the same day renumbered the actions while old messages kept their
  buttons, so tapping "send" on yesterday's message could execute a different
  action entirely — another recipient, another draft. Opaque ids make a stale
  button reference an id that no longer exists, which is a clean "no longer
  found" instead of a wrong send.

* `draft_sha` is stored so the session that finally sends can verify the draft
  is byte-identical to the one Carlos saw when he approved.

Path: BRIEF_ACTIONS_PATH (default /data/brief/actions.json). /data is a
persistent volume; it holds the Telethon session.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import secrets
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BALI = timezone(timedelta(hours=8))
_DEFAULT_PATH = "/data/brief/actions.json"


class ActionAccount(str, Enum):
    RAHYANG = "rahyang"
    IMAP = "imap"
    HOTMAIL_MAC = "hotmail_mac"


class ActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISCARDED = "discarded"
    SENT = "sent"        # set by the Claude session after it actually sends
    FAILED = "failed"


class BriefActionIn(BaseModel):
    """What the brief posts. No id: the server assigns it."""

    number: int
    label: str = ""
    account: ActionAccount
    account_id: Optional[str] = None
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    draft: str = ""
    thread_ref: Optional[str] = None
    has_pending: bool = False


class BriefActionsPayload(BaseModel):
    date: str = ""  # YYYY-MM-DD, Bali
    actions: list[BriefActionIn] = Field(default_factory=list)


def _path() -> Path:
    return Path((os.getenv("BRIEF_ACTIONS_PATH") or _DEFAULT_PATH).strip() or _DEFAULT_PATH)


def today_bali() -> str:
    return datetime.now(BALI).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def draft_sha(draft: str) -> str:
    return hashlib.sha256((draft or "").encode("utf-8")).hexdigest()


@contextmanager
def _locked() -> Iterator[None]:
    """Serialise read-modify-write across workers.

    The store is a single small file touched a handful of times a day, so a
    coarse lock is the right trade. Without it two concurrent taps could each
    read 'pending' and both write — harmless here (approval is idempotent) but
    it would silently lose the `resolved_by` of one of them.
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    fh = open(lock, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _read() -> dict[str, Any]:
    try:
        with _path().open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:  # noqa: BLE001
        logger.warning("brief_actions_read_failed error=%s", type(exc).__name__)
        return {}


def _write(data: dict[str, Any]) -> None:
    """Atomic replace. Permissions are left to the umask on create and are never
    changed on an existing file: tightening them once locked the app out of its
    own mailbox config."""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".actions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def replace_today(payload: BriefActionsPayload) -> list[dict[str, Any]]:
    """Store today's actions, assigning an opaque id to each.

    Returns [{"number": N, "id": "..."}] so the brief can build callback_data.
    Any previously stored action for the day is dropped: its id disappears, so
    buttons from an earlier run answer "no longer found" instead of resolving to
    a different action.
    """
    date = (payload.date or "").strip() or today_bali()
    actions = []
    for item in payload.actions:
        actions.append(
            {
                "id": secrets.token_hex(8),
                "status": ActionStatus.PENDING.value,
                "draft_sha": draft_sha(item.draft),
                "resolved_at": None,
                "resolved_by": None,
                **item.model_dump(mode="json"),
            }
        )
    with _locked():
        _write({"date": date, "stored_at": _now(), "actions": actions})
    logger.info("brief_actions_stored count=%s date=%s", len(actions), date)
    return [{"number": a["number"], "id": a["id"]} for a in actions]


def _today_actions(data: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    if not data or data.get("date") != today_bali():
        return None
    return data.get("actions") or []


def get_by_id(action_id: str) -> Optional[dict[str, Any]]:
    if not action_id:
        return None
    actions = _today_actions(_read())
    if actions is None:
        return None
    for raw in actions:
        if secrets.compare_digest(str(raw.get("id") or ""), action_id):
            return raw
    return None


def resolve(action_id: str, status: ActionStatus, by: str) -> Optional[dict[str, Any]]:
    """Move an action to approved/discarded. Returns the action, or None.

    Idempotent by design: approving twice is a no-op that still returns the
    action, so a double tap reads as success rather than an error.
    """
    with _locked():
        data = _read()
        actions = _today_actions(data)
        if actions is None:
            return None
        for raw in actions:
            if not secrets.compare_digest(str(raw.get("id") or ""), action_id):
                continue
            if raw.get("status") == status.value:
                return raw
            if raw.get("status") not in (ActionStatus.PENDING.value, ActionStatus.APPROVED.value):
                return raw  # already sent or failed: never walk it back
            raw["status"] = status.value
            raw["resolved_at"] = _now()
            raw["resolved_by"] = by
            _write(data)
            logger.info("brief_action_resolved status=%s by=%s", status.value, by)
            return raw
    return None


def mark_sent(action_id: str, ok: bool, detail: str = "") -> bool:
    """Called by the Claude session after it actually sends (or fails)."""
    with _locked():
        data = _read()
        actions = _today_actions(data)
        if actions is None:
            return False
        for raw in actions:
            if not secrets.compare_digest(str(raw.get("id") or ""), action_id):
                continue
            raw["status"] = (ActionStatus.SENT if ok else ActionStatus.FAILED).value
            raw["resolved_at"] = _now()
            if detail:
                raw["detail"] = detail[:300]
            _write(data)
            return True
    return False


def list_today() -> dict[str, Any]:
    data = _read()
    actions = _today_actions(data)
    if actions is None:
        return {"date": today_bali(), "actions": []}
    return {"date": data.get("date"), "stored_at": data.get("stored_at"), "actions": actions}
