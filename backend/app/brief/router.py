"""FastAPI routes for the brief agent (/api/brief/*)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.brief.auth import require_brief_key
from app.brief import metrics
from app.brief.calendar_ics import fetch_calendar
from app.brief.mail import fetch_mail
from app.brief.rate_limit import enforce_brief_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _brief_guards() -> None:
    enforce_brief_rate_limit()


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
