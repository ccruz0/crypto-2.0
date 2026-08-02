"""Telethon user-session reader for GET /brief/telegram (never marks messages read)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SESSION_LOCK = threading.Lock()
_TIMEOUT_S = 30.0
_MAX_MESSAGES = 80
_TEXT_MAX = 500


class TelegramSessionMissing(Exception):
    """Session file missing or not authorized."""


def _session_path() -> Path:
    raw = (os.getenv("TELEGRAM_SESSION_PATH") or "/data/telegram/hilovivo.session").strip()
    return Path(raw)


def _api_credentials() -> tuple[int, str]:
    api_id_raw = (os.getenv("TELEGRAM_API_ID") or "").strip()
    api_hash = (os.getenv("TELEGRAM_API_HASH") or "").strip()
    if not api_id_raw or not api_hash:
        raise TelegramSessionMissing("api_credentials_missing")
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise TelegramSessionMissing("api_id_invalid") from exc
    return api_id, api_hash


def _is_broadcast_channel(entity: Any) -> bool:
    """Exclude broadcast channels; keep private chats and groups/megagroups."""
    try:
        from telethon.tl.types import Channel

        if isinstance(entity, Channel) and bool(getattr(entity, "broadcast", False)):
            # megagroup is a group, not a broadcast channel
            if bool(getattr(entity, "megagroup", False)):
                return False
            return True
    except Exception:
        return False
    return False


def _chat_type(entity: Any) -> str:
    try:
        from telethon.tl.types import User

        if isinstance(entity, User):
            return "private"
    except Exception:
        pass
    return "group"


def _entity_title(entity: Any) -> str:
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    first = getattr(entity, "first_name", None) or ""
    last = getattr(entity, "last_name", None) or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(entity, "username", None)
    if username:
        return str(username)
    return "unknown"


def _msg_text(message: Any) -> str:
    text = getattr(message, "message", None) or getattr(message, "text", None) or ""
    text = str(text)
    if len(text) > _TEXT_MAX:
        text = text[:_TEXT_MAX]
    return text


def _sender_name(message: Any, fallback: str) -> str:
    sender = getattr(message, "sender", None)
    if sender is not None:
        return _entity_title(sender)
    return fallback


async def _fetch_async(hours: int) -> dict[str, Any]:
    from telethon import TelegramClient
    from telethon.errors import AuthKeyError, SessionPasswordNeededError

    hours = max(1, min(int(hours), 72))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    path = _session_path()
    # Telethon appends .session; accept path with or without suffix
    session_file = path if path.suffix == ".session" else Path(str(path) + ".session")
    # Also check the path as Telethon session name (without forcing .session twice)
    session_name = str(path)
    if path.suffix == ".session":
        session_name = str(path.with_suffix(""))  # Telethon adds .session

    candidates = [
        Path(session_name + ".session"),
        path,
        session_file,
    ]
    if not any(c.is_file() for c in candidates):
        raise TelegramSessionMissing("session_file_missing")

    api_id, api_hash = _api_credentials()
    client = TelegramClient(session_name, api_id, api_hash)

    try:
        await asyncio.wait_for(client.connect(), timeout=_TIMEOUT_S)
        authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=_TIMEOUT_S)
        if not authorized:
            raise TelegramSessionMissing("session_not_authorized")

        chats_raw: list[dict[str, Any]] = []

        async def _collect() -> None:
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if _is_broadcast_channel(entity):
                    continue
                unread = int(getattr(dialog, "unread_count", 0) or 0)
                title = _entity_title(entity)
                ctype = _chat_type(entity)
                # Skip dialogs with no recent activity and no unread
                last_date = getattr(dialog, "date", None)
                if last_date is not None:
                    if last_date.tzinfo is None:
                        last_date = last_date.replace(tzinfo=timezone.utc)
                    if last_date < since and unread <= 0:
                        continue
                else:
                    if unread <= 0:
                        continue

                messages_out: list[dict[str, Any]] = []
                async for msg in client.iter_messages(entity, limit=40):
                    msg_date = getattr(msg, "date", None)
                    if msg_date is None:
                        continue
                    if msg_date.tzinfo is None:
                        msg_date = msg_date.replace(tzinfo=timezone.utc)
                    if msg_date < since:
                        break
                    # Incoming only
                    if getattr(msg, "out", False):
                        continue
                    text = _msg_text(msg)
                    if not text.strip():
                        continue
                    messages_out.append(
                        {
                            "from": _sender_name(msg, title),
                            "at": msg_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "text": text,
                        }
                    )

                if not messages_out and unread <= 0:
                    continue

                last_at = messages_out[0]["at"] if messages_out else (
                    last_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if last_date is not None
                    else ""
                )
                chats_raw.append(
                    {
                        "chat": title,
                        "chat_type": ctype,
                        "unread": unread,
                        "messages": messages_out,
                        "_last_at": last_at,
                    }
                )

        await asyncio.wait_for(_collect(), timeout=_TIMEOUT_S)
    except TelegramSessionMissing:
        raise
    except (AuthKeyError, SessionPasswordNeededError) as exc:
        raise TelegramSessionMissing("session_expired") from exc
    except asyncio.TimeoutError as exc:
        raise TimeoutError("telegram_timeout") from exc
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    # Most active first (unread, then last activity)
    chats_raw.sort(key=lambda c: (int(c.get("unread") or 0), c.get("_last_at") or ""), reverse=True)

    truncated = False
    total = 0
    chats: list[dict[str, Any]] = []
    for chat in chats_raw:
        msgs = list(chat.get("messages") or [])
        if total >= _MAX_MESSAGES:
            truncated = True
            break
        if total + len(msgs) > _MAX_MESSAGES:
            msgs = msgs[: _MAX_MESSAGES - total]
            truncated = True
        total += len(msgs)
        chats.append(
            {
                "chat": chat["chat"],
                "chat_type": chat["chat_type"],
                "unread": chat["unread"],
                "messages": msgs,
            }
        )
        if truncated:
            break

    # If we dropped remaining chats entirely
    if len(chats) < len(chats_raw) and not truncated:
        truncated = True
    if sum(len(c["messages"]) for c in chats_raw) > _MAX_MESSAGES:
        truncated = True

    logger.info(
        "brief_telegram window_hours=%s chats=%s messages=%s truncated=%s",
        hours,
        len(chats),
        total,
        truncated,
    )
    return {
        "window_hours": hours,
        "generated_at": generated_at,
        "truncated": truncated,
        "chats": chats,
    }


def fetch_telegram(hours: int = 24) -> dict[str, Any]:
    """Fetch recent incoming Telegram messages. Serializes session file access."""
    with _SESSION_LOCK:
        return asyncio.run(_fetch_async(hours))
