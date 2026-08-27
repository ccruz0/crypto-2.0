"""Microsoft Graph sender for brief actions (app-only Mail.Send).

Reuses the app registration that already reads mail (`graph_mail`): rahyang.com
and bumibeans.com are the same tenant (6b90171f-...), verified 2026-08-27.
Mail.Send was granted the same day and scoped with an ApplicationAccessPolicy to
Carlos's two mailboxes.

All egress goes through app.utils.http_client, the only allowed entry point.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from app.brief.graph_mail import (
    GraphAuthError,
    GraphConfigMissing,
    _access_token,
    _graph_http_error,
)
from app.utils.http_client import http_get, http_post

logger = logging.getLogger(__name__)

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT = 30
_RAHYANG = "Carlos@rahyang.com"


class SendNotAvailable(Exception):
    """This account cannot be sent from with the current credentials."""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _user(mailbox: str) -> str:
    return quote(mailbox, safe="@.")


def _find_by_internet_id(mailbox: str, internet_message_id: str, token: str) -> Optional[dict[str, Any]]:
    """Locate a message by its RFC Message-ID so replies thread correctly."""
    safe = internet_message_id.replace("'", "''")
    url = (
        f"{_GRAPH}/users/{_user(mailbox)}/messages"
        f"?$filter=internetMessageId eq '{quote(safe)}'"
        f"&$select=id,conversationId,receivedDateTime&$top=1"
    )
    resp = http_get(url, headers=_headers(token), timeout=_TIMEOUT, calling_module="brief.graph_mail_send.find")
    if resp.status_code >= 400:
        logger.warning("brief_graph_find_failed %s", _graph_http_error("graph_find", resp))
        return None
    try:
        items = resp.json().get("value") or []
    except Exception:  # noqa: BLE001
        return None
    return items[0] if items else None


def thread_has_replies_since(thread_ref: str, mailbox: str = _RAHYANG) -> bool:
    """Has the other party written since the message the draft answers?

    Cheap brake before sending: if the thread moved after Claude wrote the
    draft, that draft may be stale. Returns False when it cannot be determined
    and there is no sign of movement; raises nothing — callers treat exceptions
    as "block".
    """
    if not thread_ref:
        return False
    token = _access_token()
    original = _find_by_internet_id(mailbox, thread_ref, token)
    if not original:
        return False

    conversation_id = str(original.get("conversationId") or "")
    received = str(original.get("receivedDateTime") or "")
    if not conversation_id or not received:
        return False

    safe = conversation_id.replace("'", "''")
    url = (
        f"{_GRAPH}/users/{_user(mailbox)}/messages"
        f"?$filter=conversationId eq '{quote(safe)}' and receivedDateTime gt {received}"
        f"&$select=id,from,receivedDateTime&$top=10"
    )
    resp = http_get(url, headers=_headers(token), timeout=_TIMEOUT, calling_module="brief.graph_mail_send.thread")
    if resp.status_code >= 400:
        logger.warning("brief_graph_thread_failed %s", _graph_http_error("graph_thread", resp))
        return False
    try:
        values = resp.json().get("value") or []
    except Exception:  # noqa: BLE001
        return False

    mailbox_lower = mailbox.lower()
    for message in values:
        sender = str(
            ((message.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        ).lower()
        if sender and sender != mailbox_lower:
            logger.info("brief_thread_moved mailbox=%s", mailbox)
            return True
    return False


def send_mail_as(
    mailbox: str,
    to: list[str],
    subject: str,
    body: str,
    thread_ref: Optional[str] = None,
) -> str:
    """Send as `mailbox`. Returns an ISO timestamp.

    With a resolvable thread_ref it replies in-thread (createReply) so the
    recipient sees it attached to the conversation; otherwise it sends standalone.
    """
    if not to:
        raise SendNotAvailable("action has no recipients")

    try:
        token = _access_token()
    except (GraphConfigMissing, GraphAuthError) as exc:
        raise SendNotAvailable(f"graph unavailable: {type(exc).__name__}") from exc

    headers = _headers(token)
    user = _user(mailbox)

    if thread_ref:
        original = _find_by_internet_id(mailbox, thread_ref, token)
        if original:
            # /reply creates and sends in one call. The draft+PATCH+send dance
            # needs a real PATCH, and http_client only exposes GET and POST.
            replied = http_post(
                f"{_GRAPH}/users/{user}/messages/{original['id']}/reply",
                json={"comment": body},
                headers=headers,
                timeout=_TIMEOUT,
                calling_module="brief.graph_mail_send.reply",
            )
            if replied.status_code == 403:
                raise SendNotAvailable(
                    "graph 403: missing Mail.Send, or the ApplicationAccessPolicy excludes this mailbox"
                )
            if replied.status_code < 400:
                logger.info("brief_action_sent mode=reply mailbox=%s", mailbox)
                return datetime.now(timezone.utc).isoformat(timespec="seconds")
            logger.info(
                "brief_reply_fallback mailbox=%s %s",
                mailbox,
                _graph_http_error("graph_reply", replied),
            )

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        },
        "saveToSentItems": True,
    }
    resp = http_post(
        f"{_GRAPH}/users/{user}/sendMail",
        json=payload,
        headers=headers,
        timeout=_TIMEOUT,
        calling_module="brief.graph_mail_send.sendmail",
    )
    if resp.status_code == 403:
        raise SendNotAvailable(
            "graph 403: missing Mail.Send, or the ApplicationAccessPolicy excludes this mailbox"
        )
    if resp.status_code >= 400:
        raise RuntimeError(_graph_http_error("graph_send", resp))
    logger.info("brief_action_sent mode=standalone mailbox=%s", mailbox)
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
