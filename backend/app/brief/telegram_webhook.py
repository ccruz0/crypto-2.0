"""Telegram callback_query webhook for the brief action buttons.

WHY THIS USES ITS OWN BOT, NOT @ATP_control_bot
-----------------------------------------------
Telegram allows either a webhook or getUpdates on a token, never both. This
backend runs an active poller on @ATP_control_bot for the trading commands
(RUN_TELEGRAM_POLLER=true, allowed_updates already includes callback_query), and
telegram_commands._run_startup_diagnostics deletes any webhook on startup
("always delete on startup to ensure polling works", drop_pending_updates=True).

Registering a webhook on that token would leave the trading bot without
commands, and it would be silently deleted on the next container restart. So the
brief has its own bot (BRIEF_TELEGRAM_BOT_TOKEN). Both are admins of the same
HILOVIVO channel; BRIEF_TELEGRAM_CHAT_ID is unchanged.

This module imports nothing from telegram_commands and is not registered in its
router: two independent paths over two different tokens.

Handlers are sync because http_client exposes async_http_get but no async POST,
and every outbound request must go through it (egress guard).
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from app.brief import actions_store
from app.brief.actions_store import ActionAccount, ActionStatus, BriefAction
from app.brief.graph_mail_send import SendNotAvailable, send_mail_as, thread_has_replies_since
from app.brief.telegram_send import resolve_brief_bot_token, resolve_chat_id
from app.utils.http_client import http_post

logger = logging.getLogger(__name__)

router = APIRouter()

_TIMEOUT = 10
_RAHYANG = "Carlos@rahyang.com"


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{resolve_brief_bot_token()}/{method}"


def _answer(callback_id: str, text: str, alert: bool = False) -> None:
    """answerCallbackQuery. Never propagates: a failure here only costs a spinner."""
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


def _append_suffix(message: dict[str, Any], suffix: str) -> None:
    """Append a line to the message and drop the buttons. Never propagates."""
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    if not chat_id or not message_id:
        return
    original = str(message.get("text") or "")
    try:
        http_post(
            _api("editMessageText"),
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": (original + suffix)[:4096],
                "reply_markup": {"inline_keyboard": []},
            },
            timeout=_TIMEOUT,
            calling_module="brief.telegram_webhook.edit",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_callback_edit_failed error=%s", type(exc).__name__)


def _thread_moved(action: BriefAction) -> bool:
    """True when the draft may be stale. On error returns True: when in doubt, do not send."""
    if not action.thread_ref:
        return False
    try:
        return bool(thread_has_replies_since(action.thread_ref))
    except Exception as exc:  # noqa: BLE001
        logger.warning("brief_thread_check_failed error=%s blocking=1", type(exc).__name__)
        return True


def _send_action(action: BriefAction) -> str:
    if action.has_pending:
        raise SendNotAvailable("the draft still has open questions")
    if action.account == ActionAccount.HOTMAIL_MAC:
        raise SendNotAvailable("personal hotmail needs the Mac")
    if action.account == ActionAccount.RAHYANG:
        return send_mail_as(
            mailbox=_RAHYANG,
            to=action.to,
            subject=action.subject,
            body=action.draft,
            thread_ref=action.thread_ref,
        )
    if action.account == ActionAccount.IMAP:
        try:
            from app.brief.brief_mail_send import send_via_smtp  # type: ignore
        except ImportError as exc:
            raise SendNotAvailable("brief_mail_send.py is not deployed") from exc
        return send_via_smtp(
            account=action.account_id or "",
            to=action.to,
            subject=action.subject,
            body=action.draft,
            thread_ref=action.thread_ref,
        )
    raise SendNotAvailable(f"unknown account: {action.account}")


def _secret_ok(request: Request) -> bool:
    expected = (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()
    if not expected:
        logger.error("brief_webhook_secret_unset rejecting=all")
        return False
    return hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "", expected)


def _parse(data: str) -> Optional[tuple[int, str]]:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "action" or parts[2] not in ("send", "cancel"):
        return None
    try:
        return int(parts[1]), parts[2]
    except ValueError:
        return None


@router.post("/telegram-webhook")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    # The only authentication this endpoint has, and it must be public.
    # Telegram echoes the secret set via setWebhook in this header.
    if not _secret_ok(request):
        raise HTTPException(status_code=401)

    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}

    callback = (update or {}).get("callback_query")
    if not callback:
        return {"ok": True}  # any other update type is ignored

    callback_id = str(callback.get("id") or "")
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")

    expected_chat = resolve_chat_id()
    if expected_chat and chat_id != expected_chat:
        logger.warning("brief_callback_wrong_chat chat_id=%s", chat_id)
        return {"ok": True}

    parsed = _parse(str(callback.get("data") or ""))
    if not parsed:
        return {"ok": True}
    number, verb = parsed

    action = actions_store.get_today(number)
    if action is None:
        _answer(callback_id, "No longer found — brief from another day?", alert=True)
        return {"ok": True}
    if action.status != ActionStatus.PENDING:
        _answer(callback_id, f"Already {action.status.value}", alert=True)
        return {"ok": True}

    if verb == "cancel":
        if actions_store.mark(number, ActionStatus.CANCELLED):
            _answer(callback_id, "Cancelled")
            _append_suffix(message, "\n\n❌ Cancelada")
        else:
            _answer(callback_id, "Already resolved", alert=True)
        return {"ok": True}

    if _thread_moved(action):
        _answer(callback_id, "Hold on: that thread has new messages, check it first", alert=True)
        return {"ok": True}

    # Marked BEFORE sending. If two clicks race, only one wins the lock and the
    # other sees False. A lost send beats a duplicate one.
    if not actions_store.mark(number, ActionStatus.SENT):
        _answer(callback_id, "Already being sent", alert=True)
        return {"ok": True}

    try:
        sent_at = _send_action(action)
    except SendNotAvailable as exc:
        actions_store.mark(number, ActionStatus.PENDING)
        _answer(callback_id, f"Cannot send: {exc}", alert=True)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.exception("brief_action_send_failed number=%s", number)
        _answer(callback_id, "Send failed, handle it by hand", alert=True)
        _append_suffix(message, f"\n\n⚠️ Error al enviar: {type(exc).__name__}")
        return {"ok": True}

    _answer(callback_id, "Sent")
    _append_suffix(message, f"\n\n✅ Enviado ({sent_at})")
    return {"ok": True}
