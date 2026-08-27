"""Bot API sender for the brief.

Two senders, on purpose:

* send_brief_message() posts the brief itself, under TELEGRAM_BOT_TOKEN, exactly
  as it did before the buttons existed. It never carries a keyboard.
* send_action_message() posts ONE action with ONE keyboard, under
  BRIEF_TELEGRAM_BOT_TOKEN. Only this function writes callback_data.

Keeping them apart means configuring the brief bot cannot break the brief: if
that bot is missing or cannot post to the channel, the actions fail and the
brief still arrives.
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


class ButtonsUnavailable(RuntimeError):
    """The approval buttons cannot be posted with the current configuration."""


def resolve_brief_bot_token() -> str:
    """The brief's own bot. Raises when it cannot be used — never falls back.

    Two ways to get this wrong, both checked here:

    * Unset. An earlier version fell back to the ATP token: the buttons went out
      under @ATP_control_bot and did nothing, and registering a webhook on that
      token to "fix" it would have killed the trading command poller (Telegram
      forbids webhook and getUpdates on one token, and telegram_commands deletes
      webhooks on startup anyway).
    * Set to the ATP token by a copy-paste. Same outcome, harder to spot, so it
      is refused rather than documented.
    """
    token = (os.getenv("BRIEF_TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise ButtonsUnavailable("BRIEF_TELEGRAM_BOT_TOKEN unset")
    if token == (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
        raise ButtonsUnavailable("BRIEF_TELEGRAM_BOT_TOKEN equals the trading bot token")
    return token


def resolve_brief_chat_id() -> str:
    """Numeric chat id for action messages. No fallback, no @username.

    The webhook only accepts a callback whose chat id equals
    BRIEF_TELEGRAM_CHAT_ID, and Telegram reports chat ids as numbers. Posting to
    "@canal" would produce live buttons whose every tap the webhook drops in
    silence, so that is refused here instead.
    """
    raw = (os.getenv("BRIEF_TELEGRAM_CHAT_ID") or "").strip()
    if not raw:
        raise ButtonsUnavailable("BRIEF_TELEGRAM_CHAT_ID unset")
    if not raw.lstrip("-").isdigit():
        raise ButtonsUnavailable("BRIEF_TELEGRAM_CHAT_ID is not numeric")
    return raw


def render_action_text(action: dict[str, Any]) -> str:
    """Plain text for one action message. Composed HERE, not by the caller.

    No parse_mode anywhere in this path: a subject line with '<' or '&' would
    otherwise fail the send, and the edit that retires the keyboard re-posts
    this same text as plain, so there is nothing to lose.
    """
    to = ", ".join(str(x) for x in (action.get("to") or [])) or "(sin destinatario)"
    account = str(action.get("account_id") or action.get("account") or "?")
    lines = [
        f"Accion {action.get('number')} - {action.get('label') or 'correo'}",
        f"Cuenta: {account}",
        f"Para: {to}",
        f"Asunto: {action.get('subject') or '(sin asunto)'}",
    ]
    if action.get("has_pending"):
        lines.append("AVISO: el borrador tiene huecos por rellenar.")
    lines.append("")
    lines.append(str(action.get("draft") or ""))
    return "\n".join(lines)


def send_action_message(action: dict[str, Any]) -> int:
    """Post one action with its own keyboard. Returns the Telegram message_id.

    One action per message is what makes the keyboard safe to clear on the first
    tap. The earlier design hung every action's buttons off a single message, so
    approving one retired all of them.

    callback_data is built here from the id the store just generated. No caller
    supplies it, which is what stops a button labelled "action 2" from carrying
    action 5's id.
    """
    from app.utils.http_client import http_post

    action_id = str(action.get("id") or "")
    if not action_id or len(action_id) > 32 or not all(c in "0123456789abcdef" for c in action_id):
        raise ButtonsUnavailable("action id is not an opaque hex id")

    token = resolve_brief_bot_token()
    chat_id = resolve_brief_chat_id()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Aprobar", "callback_data": f"a:{action_id}:ok"},
                {"text": "Descartar", "callback_data": f"a:{action_id}:no"},
            ]
        ]
    }

    chunks = split_telegram_text(render_action_text(action))
    message_id = 0
    for i, chunk in enumerate(chunks):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
        # Keyboard on the LAST chunk only: it answers for the whole action, and
        # this message holds exactly one action.
        if i == len(chunks) - 1:
            payload["reply_markup"] = keyboard
        resp = http_post(
            url,
            json=payload,
            timeout=20.0,
            calling_module="brief.telegram_send.action",
        )
        if resp.status_code >= 400:
            raise ButtonsUnavailable(f"telegram sendMessage {resp.status_code}")
        if i == len(chunks) - 1:
            message_id = int(((resp.json() or {}).get("result") or {}).get("message_id") or 0)
    return message_id


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


def send_brief_message(text: str, parse_mode: Optional[str] = "HTML") -> dict[str, Any]:
    """Send the brief itself. Never carries a keyboard — see send_action_message.

    Deliberately unchanged by the buttons work: same token, same chat, same
    behaviour as before. Nothing about configuring the brief bot can stop the
    brief from arriving.
    """
    from app.utils.http_client import http_post

    token = resolve_bot_token()
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
