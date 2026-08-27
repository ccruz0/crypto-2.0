"""Store for the current day's brief actions.

Backs the approval buttons. The button NEVER sends mail: it only records that
Carlos approved or discarded an action. The send still goes through a Claude
session, which reads this store and compares the draft it is about to send with
the one that was approved.

Design notes that are load-bearing, not decoration:

* Every action gets an OPAQUE id, generated here. The keyboard is built by the
  server from these ids (see telegram_send.send_action_message); no caller ever
  supplies callback_data. Two earlier designs failed here. The first put the
  action NUMBER in callback_data: re-running the brief renumbered the actions
  while old messages kept their buttons, so a stale tap could execute a
  different action. The second used opaque ids but let the caller write the
  keyboard, which fixed staleness and left mispairing wide open — a caller that
  put action 5's id under the button labelled "action 2" would have Carlos
  approve one thing and the session send another, invisibly, because the ids
  are opaque. Building the keyboard here closes both.

* `draft_sha` is a fingerprint of the draft as posted. It is NOT proof of what
  Carlos saw: he read the Telegram message, not this field, and reading the sha
  back from the same endpoint that served the draft proves nothing on its own.
  Its only real use is comparing this copy against claude/brief-acciones.md
  before sending, to catch the two drifting apart.

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
    """What the brief posts. No id and no keyboard: the server owns both."""

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
    date: str = ""  # YYYY-MM-DD, Bali. Recorded only; the server decides.
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
    """Serialise read-modify-write across workers AND threads.

    Several uvicorn workers share this file, and within a worker the store is
    touched from the threadpool, so more than one caller can be inside a
    read-modify-write at once. Each entry opens its own descriptor, which is
    what flock serialises on, so this covers both.

    Without it two taps on DIFFERENT actions can interleave: both read the whole
    file, both write it back, and the second write silently erases the first
    action's resolution. That is a lost approval, not just a lost `resolved_by`.
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
    """Atomic replace, owner-only.

    This file holds full email drafts, subjects and recipients, so it is created
    0600. Every process that touches it — all the uvicorn workers — runs as the
    same uid, so the mode is about keeping other accounts on the host out, not
    about which process opens it. That distinction is the one that broke
    brief_mailboxes.json: tightening ITS mode locked the app out of its own
    config, because that file is read by a different uid.
    """
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".actions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def replace_today(payload: BriefActionsPayload) -> list[dict[str, Any]]:
    """Store today's actions, assigning an opaque id to each. Returns them.

    Any previously stored action for the day is dropped, INCLUDING ones Carlos
    had already approved: its id disappears, so buttons from an earlier run
    answer "no longer found". That is deliberate — a second run means new
    drafts — but it means the caller must not re-post actions after Carlos has
    started tapping, or it silently revokes his approvals.
    """
    # The date is decided HERE, never by the caller. The brief runs between
    # 00:00 and 08:00 Bali, which is the previous day in UTC: a caller sending a
    # UTC date would write a store that _today_actions() rejects on the very
    # next read, leaving every button dead with no error anywhere.
    date = today_bali()
    claimed = (payload.date or "").strip()
    if claimed and claimed != date:
        logger.warning("brief_actions_date_ignored claimed=%s using=%s", claimed, date)
    actions = []
    for item in payload.actions:
        # Server-owned fields go LAST so a future field on BriefActionIn cannot
        # overwrite id/status/draft_sha by colliding with one of these names.
        actions.append(
            {
                **item.model_dump(mode="json"),
                "id": secrets.token_hex(8),
                "status": ActionStatus.PENDING.value,
                "draft_sha": draft_sha(item.draft),
                "message_id": None,
                "resolved_at": None,
                "resolved_by": None,
            }
        )
    with _locked():
        _write({"date": date, "stored_at": _now(), "actions": actions})
    logger.info("brief_actions_stored count=%s date=%s", len(actions), date)
    return actions


def attach_message(action_id: str, message_id: int) -> bool:
    """Record which Telegram message carries this action's buttons."""
    if not is_valid_action_id(action_id):
        return False
    with _locked():
        data = _read()
        actions = _today_actions(data)
        if actions is None:
            return False
        for raw in actions:
            if secrets.compare_digest(str(raw.get("id") or ""), action_id):
                raw["message_id"] = int(message_id)
                _write(data)
                return True
    return False


def is_valid_action_id(value: str) -> bool:
    return bool(value) and len(value) <= 32 and all(c in "0123456789abcdef" for c in value)


def _today_actions(data: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
    if not data or data.get("date") != today_bali():
        return None
    return data.get("actions") or []


def resolve(action_id: str, status: ActionStatus, by: str) -> Optional[dict[str, Any]]:
    """Move an action to approved/discarded. Returns the action, or None.

    Idempotent by design: approving twice is a no-op that still returns the
    action, so a double tap reads as success rather than an error.

    Only PENDING and APPROVED can be changed. Anything already sent, failed or
    DISCARDED is returned untouched — including discarded, so a mistaken
    ❌ cannot be undone from Telegram. The caller reports the real status back,
    which is what tells Carlos the tap did not take effect.
    """
    if not is_valid_action_id(action_id):
        return None
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
                return raw
            raw["status"] = status.value
            raw["resolved_at"] = _now()
            raw["resolved_by"] = by
            _write(data)
            logger.info("brief_action_resolved status=%s by=%s", status.value, by)
            return raw
    return None


def mark_sent(action_id: str, ok: bool, detail: str = "") -> bool:
    """Called by the Claude session after it actually sends (or fails).

    Refuses anything that was not APPROVED, so a 'sent' in this file always has
    a tap behind it. The converse does NOT hold: if Carlos discards an action
    after the session has read it and before the session calls this, the mail
    goes out and this refuses to record it. The store proves nothing was sent
    without approval; it does not prove everything sent was recorded.
    """
    if not is_valid_action_id(action_id):
        return False
    with _locked():
        data = _read()
        actions = _today_actions(data)
        if actions is None:
            return False
        for raw in actions:
            if not secrets.compare_digest(str(raw.get("id") or ""), action_id):
                continue
            if raw.get("status") != ActionStatus.APPROVED.value:
                logger.warning(
                    "brief_mark_sent_refused status=%s (solo se envia lo aprobado)",
                    raw.get("status"),
                )
                return False
            raw["status"] = (ActionStatus.SENT if ok else ActionStatus.FAILED).value
            raw["resolved_at"] = _now()
            if detail:
                raw["detail"] = detail[:300]
            _write(data)
            return True
    return False


def list_today() -> dict[str, Any]:
    """Today's actions.

    `stale` distinguishes "the brief proposed nothing" from "the store holds
    another day". Both return an empty list, and conflating them is how a set of
    approved actions can sit unsent with nothing anywhere reporting a problem.
    """
    data = _read()
    actions = _today_actions(data)
    if actions is None:
        return {
            "date": today_bali(),
            "stored_at": data.get("stored_at"),
            "stale": bool(data),
            "stored_date": data.get("date"),
            "actions": [],
        }
    return {
        "date": data.get("date"),
        "stored_at": data.get("stored_at"),
        "stale": False,
        "stored_date": data.get("date"),
        "actions": actions,
    }
