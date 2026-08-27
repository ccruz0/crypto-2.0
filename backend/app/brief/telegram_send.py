"""Bot API sender for POST /brief/send.

Prefers BRIEF_TELEGRAM_BOT_TOKEN (the brief's own bot, which owns the webhook
for the action buttons) and falls back to TELEGRAM_BOT_TOKEN so the brief keeps
going out unchanged until that bot is configured.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TELEGRAM_MAX = 4096
_TIMEOUT_S = 30.0


def resolve_bot_token() -> str:
    return (
        (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        or (os.getenv("TELEGRAM_BOT_TOKEN_AWS") or "").strip()
    )


def resolve_brief_bot_token() -> str:
    """The brief's own bot, falling back to the ATP one while it does not exist.

    They must stay separate: @ATP_control_bot is polled by telegram_commands for
    the trading commands, and Telegram forbids a webhook and getUpdates on the
    same token. The brief bot is the one that carries the callback webhook.
    """
    return (os.getenv("BRIEF_TELEGRAM_BOT_TOKEN") or "").strip() or resolve_bot_token()


def resolve_chat_id() -> str:
    """Prefer BRIEF_TELEGRAM_CHAT_ID so briefs do not share the alerts chat."""
    return (
        (os.getenv("BRIEF_TELEGRAM_CHAT_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        or (os.getenv("TELEGRAM_CHAT_ID_AWS") or "").strip()
    )


def split_telegram_text(text: str, limit: int = _TELEGRAM_MAX) -> list[str]:
    """Split on newlines so each part is <= limit; hard-split if a single line is too long."""
    text = text or ""
    if len(text) <= limit:
        return [text] if text else [""]

    parts: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            for i in range(0, len(line), limit):
                parts.append(line[i : i + limit])
            continue
        if len(buf) + len(line) <= limit:
            buf += line
        else:
            if buf:
                parts.append(buf)
            buf = line
    if buf:
        parts.append(buf)
    return parts or [""]


def send_brief_message(
    text: str,
    parse_mode: Optional[str] = "HTML",
    reply_markup: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Send text via Bot API to BRIEF_TELEGRAM_CHAT_ID (fallback TELEGRAM_CHAT_ID). Never logs token or body."""
    from app.utils.http_client import http_post

    token = resolve_brief_bot_token()
    chat_id = resolve_chat_id()
    if not token or not chat_id:
        raise RuntimeError("telegram_bot_not_configured")

    mode = parse_mode
    if mode is not None:
        mode = str(mode).strip()
        if mode == "":
            mode = None
        elif mode not in ("HTML", "Markdown", "MarkdownV2"):
            mode = "HTML"

    chunks = split_telegram_text(text, _TELEGRAM_MAX)
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    for i, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if mode:
            payload["parse_mode"] = mode
        # Buttons belong to the message as a whole, so they ride on the last
        # chunk only. Putting them on every part would show one keyboard per
        # fragment, and each would answer for the same action.
        if reply_markup is not None and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        resp = http_post(
            url,
            json=payload,
            timeout=_TIMEOUT_S,
            calling_module="brief.telegram_send",
        )
        if resp.status_code != 200:
            logger.warning(
                "brief_send part=%s/%s http_status=%s",
                i + 1,
                len(chunks),
                resp.status_code,
            )
            raise RuntimeError(f"telegram_send_failed:{resp.status_code}")

    logger.info("brief_send ok parts=%s", len(chunks))
    return {"ok": True, "parts": len(chunks)}
