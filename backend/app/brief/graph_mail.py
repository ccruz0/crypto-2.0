"""Microsoft Graph mailbox reader for M365 accounts (app-only Mail.Read)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.utils.http_client import http_get, http_post

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_MESSAGES_URL = (
    "https://graph.microsoft.com/v1.0/users/{user}/mailFolders/Inbox/messages"
)
_PREVIEW_CHARS = 400


class GraphConfigMissing(Exception):
    """Tenant/client credentials not configured."""


class GraphAuthError(Exception):
    """Token request failed."""


def _graph_credentials() -> tuple[str, str, str]:
    tenant = (os.getenv("BRIEF_GRAPH_TENANT_ID") or "").strip()
    client_id = (os.getenv("BRIEF_GRAPH_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("BRIEF_GRAPH_CLIENT_SECRET") or "").strip()
    if not tenant or not client_id or not client_secret:
        raise GraphConfigMissing("graph_credentials_missing")
    return tenant, client_id, client_secret


def _access_token() -> str:
    tenant, client_id, client_secret = _graph_credentials()
    url = _TOKEN_URL.format(tenant=quote(tenant, safe=""))
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    resp = http_post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
        calling_module="brief.graph_mail.token",
    )
    if resp.status_code >= 400:
        raise GraphAuthError(f"graph_token_http_{resp.status_code}")
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise GraphAuthError("graph_token_invalid_json") from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise GraphAuthError("graph_token_missing")
    return token


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preview_from_graph_item(item: dict[str, Any]) -> str:
    preview = str(item.get("bodyPreview") or "").strip()
    text = " ".join(preview.split()).strip()
    return text[:_PREVIEW_CHARS]


def fetch_graph_mailbox(
    *,
    user: str,
    since: datetime,
    limit: int,
) -> dict[str, Any]:
    """Fetch Inbox messages for ``user`` (UPN) since ``since``. Never logs tokens/bodies."""
    user = (user or "").strip()
    if not user:
        raise ValueError("incomplete_mailbox_config")
    token = _access_token()
    since_s = _iso_z(since)
    filt = f"receivedDateTime ge {since_s}"
    params = {
        "$top": str(max(1, min(int(limit), 50))),
        "$orderby": "receivedDateTime desc",
        "$filter": filt,
        # bodyPreview only — avoid pulling full HTML bodies over the wire
        "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview",
    }
    url = _MESSAGES_URL.format(user=quote(user, safe="@."))
    resp = http_get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params=params,
        timeout=15,
        calling_module="brief.graph_mail.messages",
    )
    if resp.status_code >= 400:
        # Map common Graph auth/permission failures
        if resp.status_code in (401, 403):
            raise GraphAuthError(f"graph_messages_http_{resp.status_code}")
        raise RuntimeError(f"graph_messages_http_{resp.status_code}")
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("graph_messages_invalid_json") from exc

    messages: list[dict[str, Any]] = []
    for item in payload.get("value") or []:
        if not isinstance(item, dict):
            continue
        received_raw = str(item.get("receivedDateTime") or "").strip()
        try:
            at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        at = at.astimezone(timezone.utc)
        if at < since.astimezone(timezone.utc):
            continue
        from_obj = ((item.get("from") or {}).get("emailAddress") or {})
        from_name = str(from_obj.get("name") or "").strip()
        from_addr = str(from_obj.get("address") or "").strip().lower()
        messages.append(
            {
                "from_name": from_name,
                "from": from_addr,
                "subject": str(item.get("subject") or ""),
                "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "unread": not bool(item.get("isRead")),
                "preview": _preview_from_graph_item(item),
            }
        )
        if len(messages) >= limit:
            break
    return {"messages": messages}


def classify_graph_error(exc: BaseException) -> str:
    if isinstance(exc, GraphConfigMissing):
        return "graph_config_missing"
    if isinstance(exc, GraphAuthError):
        return "auth_failed"
    if isinstance(exc, ValueError):
        return "config_invalid"
    return "error"
