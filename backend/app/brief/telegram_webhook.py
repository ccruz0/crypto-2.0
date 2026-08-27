"""Telegram callback webhook for the brief approval buttons.

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
-------------------------------------------------
Tapping a button records an approval. It does NOT send mail. The send still
happens in a Claude session, which reads the store, checks the draft still
matches what was approved, re-reads the thread, and sends.

That boundary is the whole point. An earlier version had the webhook send the
mail itself and an independent review found two ways it could reach the wrong
recipient and one way it could stall the trading backend for two minutes. With
no Graph call in this path, none of those failure modes exist: the handler does
two Telegram calls of at most ten seconds each and touches one small file.

WHY ITS OWN BOT
---------------
Telegram allows a webhook or getUpdates on a token, never both. This backend
polls @ATP_control_bot for the trading commands (RUN_TELEGRAM_POLLER=true) and
telegram_commands deletes any webhook on startup. So the brief uses its own bot,
BRIEF_TELEGRAM_BOT_TOKEN. Both are admins of the same channel; the chat id is
unchanged.

Handlers are sync on purpose: http_client exposes async_http_get but no async
POST, and every outbound request must go through it (egress guard). A sync
handler runs in FastAPI's threadpool and cannot block the event loop.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from app.brief import actions_store
from app.brief.actions_store import ActionStatus
from app.brief.telegram_send import resolve_brief_bot_token, resolve_chat_id
from app.utils.http_client import http_post

logger = logging.getLogger(__name__)

router = APIRouter()

_TIMEOUT = 10
_PREFIX = "a:"


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{resolve_brief_bot_token()}/{method}"


def _answer(callback_id: str, text: str, alert: bool = False) -> None:
    """answerCallbackQuery. Never raises: a failure here costs a spinner, nothing more."""
    if not callback_id:
        return
    try:
        http_post(
            _api("answerCallbackQuery"),
            json={"callback_query_id": callback_id, "text": text[:200], "show_alert": alert},
            timeout=_TIMEOUT,
            calling_module="brief.telegram_webhook.answer",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_callback_answer_failed error=%s", type(exc).__name__)


def _mark_message(message: dict[str, Any], suffix: str) -> None:
    """Append a line and drop the keyboard. Never raises.

    parse_mode is HTML to match how the brief sends these messages: `text` comes
    back from Telegram without entities, so re-posting it without the mode would
    strip the formatting off the whole message.
    """
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        return
    original = str(message.get("text") or "")
    body = (original + suffix)[:4096]
    try:
        resp = http_post(
            _api("editMessageText"),
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": body,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": []},
            },
            timeout=_TIMEOUT,
            calling_module="brief.telegram_webhook.edit",
        )
        if resp.status_code >= 400:
            # Most likely "message is not modified" or an HTML parse error on
            # text Telegram gave us back plain. Retry once without parse_mode so
            # the keyboard still goes away and the tap is not left ambiguous.
            http_post(
                _api("editMessageText"),
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": body,
                    "reply_markup": {"inline_keyboard": []},
                },
                timeout=_TIMEOUT,
                calling_module="brief.telegram_webhook.edit_plain",
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_callback_edit_failed error=%s", type(exc).__name__)


def _secret_ok(request: Request) -> bool:
    """The only authentication this endpoint has, and it must be public.

    Fails closed when unset. The header is compared as bytes because Starlette
    decodes headers as latin-1 and hmac.compare_digest raises TypeError on
    non-ASCII str — an unauthenticated 500 that anyone could trigger at will.
    """
    expected = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not expected:
        logger.error("brief_webhook_secret_unset rejecting=all")
        return False
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    return hmac.compare_digest(got.encode("utf-8", "replace"), expected.encode("utf-8"))


def _allowed_user() -> str:
    return (
        (os.getenv("BRIEF_TELEGRAM_APPROVER_ID") or "").strip()
        or (os.getenv("TELEGRAM_AUTH_USER_ID") or "").strip()
    )


def _parse(data: str) -> Optional[tuple[str, str]]:
    """callback_data is 'a:<opaque id>:<ok|no>'. Never a position."""
    if not data.startswith(_PREFIX):
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[2] not in ("ok", "no"):
        return None
    action_id = parts[1]
    if not action_id or len(action_id) > 32 or not all(c in "0123456789abcdef" for c in action_id):
        return None
    return action_id, parts[2]


@router.post("/telegram-webhook")
def telegram_webhook(request: Request, update: dict[str, Any]) -> dict[str, Any]:
    if not _secret_ok(request):
        raise HTTPException(status_code=401)

    callback = (update or {}).get("callback_query")
    if not callback:
        return {"ok": True}  # any other update type is ignored

    callback_id = str(callback.get("id") or "")
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    user = callback.get("from") or {}
    user_id = str(user.get("id") or "")

    # Fails closed: an unset chat id would otherwise accept callbacks from anywhere.
    expected_chat = resolve_chat_id()
    if not expected_chat or chat_id != expected_chat:
        logger.warning("brief_callback_wrong_chat chat_id=%s", chat_id)
        return {"ok": True}

    # A channel can have several members. Approving a mail that goes out over
    # Carlos's name is his call, not any reader's.
    allowed = _allowed_user()
    if not allowed:
        logger.error("brief_callback_approver_unset rejecting=all")
        _answer(callback_id, "Aprobador no configurado", alert=True)
        return {"ok": True}
    if user_id != allowed:
        logger.warning("brief_callback_wrong_user user_id=%s", user_id)
        _answer(callback_id, "Solo Carlos puede aprobar estas acciones", alert=True)
        return {"ok": True}

    parsed = _parse(str(callback.get("data") or ""))
    if not parsed:
        return {"ok": True}
    action_id, verb = parsed

    status = ActionStatus.APPROVED if verb == "ok" else ActionStatus.DISCARDED
    try:
        action = actions_store.resolve(action_id, status, by=user_id)
    except Exception:  # noqa: BLE001
        # Never let a store failure escape: a 5xx makes Telegram retry the same
        # update, and retries on a state change are how double-actions happen.
        logger.exception("brief_action_resolve_failed")
        _answer(callback_id, "No se pudo guardar, intentalo de nuevo", alert=True)
        return {"ok": True}

    if action is None:
        _answer(callback_id, "Esa accion ya no existe (brief de otro dia)", alert=True)
        return {"ok": True}

    current = action.get("status")
    if current in (ActionStatus.SENT.value, ActionStatus.FAILED.value):
        _answer(callback_id, f"Esa accion ya esta {current}", alert=True)
        return {"ok": True}

    if status == ActionStatus.DISCARDED:
        _answer(callback_id, "Descartada")
        _mark_message(message, "\n\n❌ <b>Descartada</b>")
    else:
        _answer(callback_id, "Aprobada — la enviare en cuanto la lea")
        _mark_message(message, "\n\n✅ <b>Aprobada</b> · pendiente de envio")

    return {"ok": True}
