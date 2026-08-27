"""Telegram callback webhook for the brief approval buttons.

WHAT THIS DOES
--------------
Tapping a button records an approval. It does NOT send mail. The send still
happens in a Claude session that reads the store afterwards.

WHAT THIS DOES **NOT** SOLVE — read this before assuming it is safe
-------------------------------------------------------------------
Moving the send out of this path removes the failure modes that *this code*
could cause. It does not remove them from the system. Two findings from the
review of the first attempt (#577) now live in the sending session and remain
OPEN there:

  * Graph's /reply answers the original sender and honours Reply-To, so it can
    reach an address that is not `action.to`. Nothing in this backend compares
    the address actually written to against the one that was approved.
  * /reply returns 202; treating a later 5xx as "not sent" and falling back to
    sendMail duplicates the mail.

And one that this module creates by being asynchronous: between the session
reading an approved action and calling /sent, Carlos can still discard it. The
mail goes out and mark_sent refuses to record it. Whoever writes the sending
side must handle all three. This module cannot.

WHY ITS OWN BOT
---------------
Telegram allows a webhook or getUpdates on a token, never both. This backend
polls @ATP_control_bot for the trading commands and telegram_commands deletes
any webhook on startup. So the brief needs its own bot. There is deliberately no
fallback here: if BRIEF_TELEGRAM_BOT_TOKEN is unset this module refuses to act
rather than reaching for the trading bot's token.

CONCURRENCY
-----------
The handler is async so it can authenticate BEFORE the body is read — a typed
body parameter would make FastAPI parse an unauthenticated request first. Every
blocking call (the store, the Telegram POSTs) is pushed to the threadpool, so
the event loop the trading backend runs on is never held.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.brief import actions_store
from app.brief.actions_store import ActionStatus, is_valid_action_id

logger = logging.getLogger(__name__)

router = APIRouter()

_TIMEOUT = 10
_PREFIX = "a:"
_MAX_BODY = 64 * 1024  # a callback_query update is ~1 KB; 64 KB is generous


class BriefBotNotConfigured(RuntimeError):
    """BRIEF_TELEGRAM_BOT_TOKEN is not set. We do not fall back to the ATP bot."""


def _brief_token() -> str:
    token = (os.getenv("BRIEF_TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise BriefBotNotConfigured("BRIEF_TELEGRAM_BOT_TOKEN unset")
    return token


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{_brief_token()}/{method}"


def _answer_sync(callback_id: str, text: str, alert: bool = False) -> None:
    """answerCallbackQuery. Never raises: a failure here costs a spinner."""
    if not callback_id:
        return
    from app.utils.http_client import http_post

    try:
        http_post(
            _api("answerCallbackQuery"),
            json={"callback_query_id": callback_id, "text": text[:200], "show_alert": alert},
            timeout=_TIMEOUT,
            calling_module="brief.telegram_webhook.answer",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_callback_answer_failed error=%s", type(exc).__name__)


def _utf16_len(value: str) -> int:
    """Telegram counts message length in UTF-16 code units, not characters."""
    return len(value.encode("utf-16-le")) // 2


def _mark_message_sync(message: dict[str, Any], suffix: str) -> None:
    """Append a line and drop the keyboard. Never raises.

    Sent WITHOUT parse_mode, and nothing is lost by that: the message being
    edited is an action message composed by send_action_message, which posts
    plain text with no parse_mode either. Re-posting it as plain text is exactly
    what it already was.

    Each action has its own message, so clearing this keyboard retires only this
    action's buttons. The earlier design put every action's buttons on one
    message, where the first tap disarmed all of them.

    "Never raises" is the contract; it is not the same as "always retires the
    keyboard". If the edit call fails, the buttons stay live and Carlos can tap
    again — resolve() is idempotent, so the second tap is harmless.
    """
    from app.utils.http_client import http_post

    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        return
    original = str(message.get("text") or "")
    # Trim the ORIGINAL, not the result: truncating the tail would drop the
    # suffix on a message near the 4096 limit, so the text would come back
    # byte-identical while the markup still changed. The edit would apply and
    # the keyboard would go, but Carlos would get no visible confirmation.
    room = 4096 - _utf16_len(suffix)
    body = original if room > 0 else ""
    while _utf16_len(body) > room:
        body = body[:-1]  # each step drops at least one code unit
    body += suffix
    try:
        http_post(
            _api("editMessageText"),
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": body,
                "reply_markup": {"inline_keyboard": []},
            },
            timeout=_TIMEOUT,
            calling_module="brief.telegram_webhook.edit",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_callback_edit_failed error=%s", type(exc).__name__)


def _secret_ok(request: Request) -> bool:
    """The only authentication this endpoint has, and it must be public.

    Fails closed when unset. Compared as bytes: Starlette decodes headers as
    latin-1 and hmac.compare_digest raises TypeError on non-ASCII str, which
    would be an unauthenticated 500 anyone could trigger at will.
    """
    expected = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return False
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    return hmac.compare_digest(got.encode("utf-8", "replace"), expected.encode("utf-8"))


def _allowed_users() -> set[str]:
    """Who may approve. Comma-separated is accepted: TELEGRAM_AUTH_USER_ID is a
    list in some deployments and a single id in others."""
    raw = (
        (os.getenv("BRIEF_TELEGRAM_APPROVER_ID") or "").strip()
        or (os.getenv("TELEGRAM_AUTH_USER_ID") or "").strip()
    )
    return {p.strip() for p in raw.split(",") if p.strip()}


def _parse(data: str) -> Optional[tuple[str, str]]:
    """callback_data is 'a:<opaque hex id>:<ok|no>', written only by the server."""
    if not data.startswith(_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[2] not in ("ok", "no"):
        return None
    if not is_valid_action_id(parts[1]):
        return None
    return parts[1], parts[2]


@router.post("/telegram-webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    # Authenticate BEFORE touching the body. A typed body parameter would make
    # FastAPI read and parse an unauthenticated request first, which on a public
    # endpoint sharing a process with the trading backend is a memory exhaustion
    # vector.
    if not _secret_ok(request):
        raise HTTPException(status_code=401)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY:
        raise HTTPException(status_code=413)
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise HTTPException(status_code=413)
    try:
        update = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {"ok": True}
    if not isinstance(update, dict):
        return {"ok": True}

    callback = update.get("callback_query")
    if not callback:
        return {"ok": True}  # any other update type is ignored

    try:
        _brief_token()
    except BriefBotNotConfigured:
        logger.error("brief_callback_no_bot_token: refusing (will not use the ATP token)")
        return {"ok": True}

    callback_id = str(callback.get("id") or "")
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    user_id = str((callback.get("from") or {}).get("id") or "")

    # Silent on purpose: a callback from another chat is not ours to answer, and
    # answering would confirm the endpoint to whoever sent it. The buttons can
    # only exist in the brief chat, because send_action_message refuses to post
    # them without a numeric BRIEF_TELEGRAM_CHAT_ID.
    expected_chat = (os.getenv("BRIEF_TELEGRAM_CHAT_ID") or "").strip()
    if not expected_chat or chat_id != expected_chat:
        logger.warning("brief_callback_wrong_chat chat_id=%s", chat_id)
        return {"ok": True}

    allowed = _allowed_users()
    if not allowed:
        logger.error("brief_callback_approver_unset rejecting=all")
        await run_in_threadpool(_answer_sync, callback_id, "Aprobador no configurado", True)
        return {"ok": True}
    if user_id not in allowed:
        logger.warning("brief_callback_wrong_user user_id=%s", user_id)
        await run_in_threadpool(
            _answer_sync, callback_id, "Solo Carlos puede aprobar estas acciones", True
        )
        return {"ok": True}

    parsed = _parse(str(callback.get("data") or ""))
    if not parsed:
        # Always answer: an unanswered callback leaves the spinner turning and
        # Carlos with no idea whether the tap registered.
        await run_in_threadpool(_answer_sync, callback_id, "Boton no reconocido", True)
        return {"ok": True}
    action_id, verb = parsed

    wanted = ActionStatus.APPROVED if verb == "ok" else ActionStatus.DISCARDED
    try:
        action = await run_in_threadpool(actions_store.resolve, action_id, wanted, user_id)
    except Exception:  # noqa: BLE001
        # Never let a store failure escape: a 5xx makes Telegram retry the same
        # update, and retries on a state change are how double-actions happen.
        logger.exception("brief_action_resolve_failed")
        await run_in_threadpool(
            _answer_sync, callback_id, "No se pudo guardar, intentalo de nuevo", True
        )
        return {"ok": True}

    if action is None:
        await run_in_threadpool(
            _answer_sync, callback_id, "Esa accion ya no existe (brief de otro dia)", True
        )
        return {"ok": True}

    # Report what the store ACTUALLY holds, not what was asked for. resolve()
    # refuses to walk back a sent/failed/discarded action and returns it
    # unchanged; announcing "approved" over that would tell Carlos a mail is
    # going out when it is not.
    final = str(action.get("status") or "")
    if final != wanted.value:
        await run_in_threadpool(
            _answer_sync, callback_id, f"No se pudo cambiar: sigue como '{final}'", True
        )
        return {"ok": True}

    if wanted == ActionStatus.DISCARDED:
        await run_in_threadpool(_answer_sync, callback_id, "Descartada")
        await run_in_threadpool(_mark_message_sync, message, "\n\n[X] Descartada")
    else:
        await run_in_threadpool(_answer_sync, callback_id, "Aprobada - la enviare en cuanto la lea")
        await run_in_threadpool(_mark_message_sync, message, "\n\n[OK] Aprobada - pendiente de envio")

    return {"ok": True}
