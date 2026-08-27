"""FastAPI routes for the brief agent (/api/brief/*)."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.brief.auth import require_brief_key
from app.brief import metrics
from app.brief.calendar_ics import fetch_calendar
from app.brief.mail import fetch_mail
from app.brief.rate_limit import enforce_brief_rate_limit
from app.brief.telegram_read import TelegramSessionMissing, fetch_telegram
from app.brief import actions_store
from app.brief.actions_store import BriefActionsPayload
from app.brief.telegram_send import send_brief_message
from app.brief.telegram_webhook import router as brief_webhook_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _brief_guards() -> None:
    enforce_brief_rate_limit()


class InlineButton(BaseModel):
    text: str = Field(..., min_length=1, max_length=64)
    # Telegram caps callback_data at 64 BYTES. "a:<16 hex>:<ok|no>" is 22 ASCII
    # bytes, but the limit is validated on the encoded length so a non-ASCII
    # payload cannot slip past a character count.
    callback_data: str = Field(..., min_length=1)

    @field_validator("callback_data")
    @classmethod
    def _fits_telegram_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 64:
            raise ValueError("callback_data exceeds 64 bytes")
        return v


class InlineKeyboard(BaseModel):
    inline_keyboard: list[list[InlineButton]]


class MarkSentBody(BaseModel):
    ok: bool
    detail: str = ""


class BriefSendBody(BaseModel):
    text: str = Field(..., min_length=1)
    parse_mode: Optional[Literal["HTML", "Markdown", "MarkdownV2"]] = "HTML"
    reply_markup: Optional[InlineKeyboard] = None


@router.get("/mail")
def brief_mail(
    hours: int = Query(24, ge=1, le=72),
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
):
    """Read recent mail from configured IMAP mailboxes (read-only)."""
    try:
        payload = fetch_mail(hours=hours)
        total = sum(int(a.get("count") or 0) for a in payload.get("accounts") or [])
        metrics.inc_mail_messages(total)
        for err in payload.get("errors") or []:
            metrics.inc_mail_error(str(err.get("error") or "error"))
        metrics.inc_request("mail", "ok")
        return payload
    except Exception:
        metrics.inc_request("mail", "error")
        logger.exception("brief_mail_unhandled")
        raise


@router.get("/calendar")
def brief_calendar(
    days: int = Query(2, ge=1, le=7),
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
):
    """Read upcoming events from published ICS calendars (BRIEF_ICS_URLS)."""
    try:
        payload = fetch_calendar(days=days)
        metrics.inc_calendar_events(len(payload.get("events") or []))
        for err in payload.get("errors") or []:
            metrics.inc_calendar_error(str(err.get("error") or "error"))
        metrics.inc_request("calendar", "ok")
        return payload
    except Exception:
        metrics.inc_request("calendar", "error")
        logger.exception("brief_calendar_unhandled")
        raise


@router.get("/telegram")
def brief_telegram(
    hours: int = Query(24, ge=1, le=72),
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
):
    """Read recent incoming Telegram DMs/groups via Telethon user session (read-only)."""
    try:
        payload = fetch_telegram(hours=hours)
        n_msgs = sum(len(c.get("messages") or []) for c in payload.get("chats") or [])
        metrics.inc_telegram_messages(n_msgs)
        metrics.inc_telegram_chats(len(payload.get("chats") or []))
        metrics.inc_request("telegram", "ok")
        return payload
    except TelegramSessionMissing:
        metrics.inc_request("telegram", "session_missing")
        raise HTTPException(
            status_code=409,
            detail={
                "error": "telegram_session_missing",
                "hint": "run scripts/telegram_login.py",
            },
        )
    except TimeoutError:
        metrics.inc_request("telegram", "timeout")
        raise HTTPException(status_code=504, detail={"error": "telegram_timeout"})
    except Exception:
        metrics.inc_request("telegram", "error")
        logger.exception("brief_telegram_unhandled")
        raise


@router.post("/send")
def brief_send(
    body: BriefSendBody,
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
) -> dict[str, Any]:
    """Send a brief message to BRIEF_TELEGRAM_CHAT_ID (fallback TELEGRAM_CHAT_ID)."""
    try:
        result = send_brief_message(
            body.text,
            parse_mode=body.parse_mode,
            reply_markup=(
                body.reply_markup.model_dump(exclude_none=True)
                if body.reply_markup is not None
                else None
            ),
        )
        metrics.inc_send_parts(int(result.get("parts") or 0))
        metrics.inc_request("send", "ok")
        return result
    except RuntimeError as exc:
        metrics.inc_request("send", "error")
        msg = str(exc)
        if msg == "telegram_bot_not_configured":
            raise HTTPException(
                status_code=503,
                detail={"error": "telegram_bot_not_configured"},
            ) from exc
        raise HTTPException(status_code=502, detail={"error": "telegram_send_failed"}) from exc
    except Exception:
        metrics.inc_request("send", "error")
        logger.exception("brief_send_unhandled")
        raise


@router.post("/actions")
def brief_actions_store(
    body: BriefActionsPayload,
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
) -> dict[str, Any]:
    """Store today's proposed actions and return their opaque ids.

    The brief calls this right after writing claude/brief-acciones.md, which the
    backend cannot read, and uses the returned ids to build callback_data. Ids
    are assigned here rather than derived from the action number: a second run
    on the same day would renumber the actions while old messages kept their
    buttons.
    """
    try:
        ids = actions_store.replace_today(body)
        metrics.inc_request("actions", "ok")
        return {"ok": True, "stored": len(ids), "ids": ids}
    except Exception:
        metrics.inc_request("actions", "error")
        logger.exception("brief_actions_store_unhandled")
        raise


@router.get("/actions")
def brief_actions_list(
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
) -> dict[str, Any]:
    """Today's actions with their status, for the session that does the sending."""
    try:
        payload = actions_store.list_today()
        metrics.inc_request("actions_list", "ok")
        return payload
    except Exception:
        metrics.inc_request("actions_list", "error")
        logger.exception("brief_actions_list_unhandled")
        raise


@router.post("/actions/{action_id}/sent")
def brief_actions_mark_sent(
    action_id: str,
    body: MarkSentBody,
    _: None = Depends(require_brief_key),
    __: None = Depends(_brief_guards),
) -> dict[str, Any]:
    """Record the outcome after a Claude session actually sends the mail."""
    try:
        found = actions_store.mark_sent(action_id, body.ok, body.detail)
        metrics.inc_request("actions_sent", "ok" if found else "not_found")
        if not found:
            raise HTTPException(status_code=404, detail={"error": "action_not_found"})
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        metrics.inc_request("actions_sent", "error")
        logger.exception("brief_actions_mark_sent_unhandled")
        raise


# Mounted without require_brief_key on purpose: Telegram cannot send that header.
# The webhook authenticates with the secret token set via setWebhook, checked
# inside the handler before the body is read, and fails closed when unset.
#
# It DOES go through _brief_guards, unlike the first version. Being the only
# public endpoint in this router, leaving it outside the rate limit made it the
# cheapest way to put load on the process that runs the trading loop.
router.include_router(brief_webhook_router, dependencies=[Depends(_brief_guards)])
