"""IMAP multi-mailbox reader for GET /brief/mail (read-only EXAMINE)."""

from __future__ import annotations

import concurrent.futures
import email
import imaplib
import json
import logging
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ACCOUNT_TIMEOUT_S = 20
_MAX_PER_ACCOUNT = 20
_MAX_TOTAL = 80
_PREVIEW_CHARS = 400

# Outlook.com / Outlook forwarded body markers (EN + ES)
_FWD_FROM_RE = re.compile(
    r"(?im)^(?:From|De)\s*:\s*(.+?)(?:\r?\n|$)",
)


@dataclass(frozen=True)
class MailboxConfig:
    id: str
    label: str
    host: str
    port: int
    ssl: bool
    user: str
    password: str
    folder: str
    priority: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in ("script", "style"):
            self._skip = True
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html or "")
    return parser.text()


def decode_mime_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _mailboxes_path() -> Path:
    raw = (os.getenv("BRIEF_MAILBOXES_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path("/app/secrets/brief_mailboxes.json")


def load_mailboxes() -> list[MailboxConfig]:
    path = _mailboxes_path()
    if not path.is_file():
        raise FileNotFoundError(f"mailboxes_config_missing:{path.name}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("mailboxes_config_invalid")
    out: list[MailboxConfig] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        out.append(
            MailboxConfig(
                id=mid,
                label=str(item.get("label") or mid).strip(),
                host=str(item.get("host") or "").strip(),
                port=int(item.get("port") or 993),
                ssl=bool(item.get("ssl", True)),
                user=str(item.get("user") or "").strip(),
                password=str(item.get("password") or ""),
                folder=str(item.get("folder") or "INBOX").strip() or "INBOX",
                priority=str(item.get("priority") or "").strip(),
            )
        )
    return out


def _classify_imap_error(exc: BaseException) -> str:
    if isinstance(exc, concurrent.futures.TimeoutError):
        return "timeout"
    if isinstance(exc, socket.gaierror):
        return "dns_error"
    if isinstance(exc, socket.timeout):
        return "timeout"
    if isinstance(exc, imaplib.IMAP4.error):
        msg = str(exc).lower()
        if "auth" in msg or "login" in msg or "credential" in msg or "invalid" in msg:
            return "auth_failed"
        return "imap_error"
    if isinstance(exc, OSError):
        err = getattr(exc, "errno", None)
        if err in (socket.EAI_NONAME, getattr(socket, "EAI_AGAIN", -3)):
            return "dns_error"
        return "connection_error"
    if isinstance(exc, FileNotFoundError):
        return "config_missing"
    if isinstance(exc, ValueError):
        return "config_invalid"
    return "error"


def _body_preview(msg: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = str(part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            try:
                payload = part.get_payload(decode=True)
            except Exception:
                payload = None
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        ctype = (msg.get_content_type() or "").lower()
        try:
            payload = msg.get_payload(decode=True)
        except Exception:
            payload = None
        if payload is not None:
            charset = msg.get_content_charset() or "utf-8"
            try:
                text = payload.decode(charset, errors="replace")
            except Exception:
                text = payload.decode("utf-8", errors="replace")
            if ctype == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)

    if plain_parts:
        body = "\n".join(plain_parts)
    elif html_parts:
        body = html_to_text("\n".join(html_parts))
    else:
        body = ""
    body = re.sub(r"\s+", " ", body).strip()
    return body[:_PREVIEW_CHARS]


def _message_date_utc(msg: Message) -> Optional[datetime]:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_from(msg: Message) -> tuple[str, str]:
    raw = decode_mime_header(msg.get("From"))
    name, addr = parseaddr(raw)
    return (name or "").strip(), (addr or "").strip().lower()


def _extract_original_from(preview: str) -> Optional[str]:
    m = _FWD_FROM_RE.search(preview or "")
    if not m:
        return None
    value = m.group(1).strip()
    name, addr = parseaddr(value)
    if addr:
        if name:
            return f"{name} <{addr}>"
        return addr
    return value or None


def _fetch_one_account(
    cfg: MailboxConfig,
    since: datetime,
    limit: int,
) -> dict[str, Any]:
    if not cfg.host or not cfg.user:
        raise ValueError("incomplete_mailbox_config")

    if cfg.ssl:
        client: imaplib.IMAP4 = imaplib.IMAP4_SSL(cfg.host, cfg.port, timeout=_ACCOUNT_TIMEOUT_S)
    else:
        client = imaplib.IMAP4(cfg.host, cfg.port, timeout=_ACCOUNT_TIMEOUT_S)

    try:
        client.login(cfg.user, cfg.password)
        # Read-only: EXAMINE (do not SELECT — never mark messages read)
        typ, _ = client.select(cfg.folder, readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"examine_failed:{cfg.folder}")

        # IMAP SINCE uses mailbox-local date; pad by 1 day for TZ skew
        since_date = (since - timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = client.search(None, "SINCE", since_date)
        if typ != "OK" or not data or not data[0]:
            return {"messages": []}

        ids = data[0].split()
        # Newest first
        ids = list(reversed(ids))
        messages: list[dict[str, Any]] = []

        for uid in ids:
            if len(messages) >= limit:
                break
            typ, fetched = client.fetch(uid, "(FLAGS BODY.PEEK[])")
            if typ != "OK" or not fetched:
                continue
            raw_bytes: Optional[bytes] = None
            flags_blob = b""
            for item in fetched:
                if isinstance(item, tuple) and len(item) >= 2:
                    flags_blob = item[0] if isinstance(item[0], (bytes, bytearray)) else b""
                    raw_bytes = item[1] if isinstance(item[1], (bytes, bytearray)) else None
                    break
            if not raw_bytes:
                continue
            msg = email.message_from_bytes(raw_bytes)
            at = _message_date_utc(msg)
            if at is None or at < since:
                continue
            from_name, from_addr = _parse_from(msg)
            subject = decode_mime_header(msg.get("Subject"))
            unread = b"\\Seen" not in flags_blob
            preview = _body_preview(msg)
            row: dict[str, Any] = {
                "from_name": from_name,
                "from": from_addr,
                "subject": subject,
                "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "unread": unread,
                "preview": preview,
            }
            if cfg.id == "hotmail-fw":
                original = _extract_original_from(preview)
                if original:
                    row["original_from"] = original
            messages.append(row)

        return {"messages": messages}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def fetch_mail(hours: int = 24) -> dict[str, Any]:
    """Fetch recent mail from all configured mailboxes. Never logs passwords or bodies."""
    hours = max(1, min(int(hours), 72))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    errors: list[dict[str, str]] = []
    accounts_out: list[dict[str, Any]] = []
    truncated = False
    total_msgs = 0

    try:
        mailboxes = load_mailboxes()
    except Exception as exc:
        err = _classify_imap_error(exc)
        logger.warning("brief_mail config_error type=%s", err)
        return {
            "window_hours": hours,
            "generated_at": generated_at,
            "truncated": False,
            "errors": [{"id": "_config", "error": err}],
            "accounts": [],
        }

    def _job(cfg: MailboxConfig) -> tuple[MailboxConfig, dict[str, Any] | Exception]:
        try:
            return cfg, _fetch_one_account(cfg, since, _MAX_PER_ACCOUNT)
        except Exception as exc:  # noqa: BLE001 — per-account isolation
            return cfg, exc

    # Parallel connect; 20s timeout per account (IMAP socket + future.result)
    results: list[tuple[MailboxConfig, dict[str, Any] | Exception]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, len(mailboxes)))) as pool:
        futures = {pool.submit(_job, cfg): cfg for cfg in mailboxes}
        for fut, cfg in futures.items():
            try:
                results.append(fut.result(timeout=_ACCOUNT_TIMEOUT_S))
            except concurrent.futures.TimeoutError:
                results.append((cfg, concurrent.futures.TimeoutError()))
            except Exception as exc:  # noqa: BLE001
                results.append((cfg, exc))

    # Preserve config order; apply global 80-message cap after merge
    by_id = {cfg.id: (cfg, res) for cfg, res in results}
    for cfg in mailboxes:
        pair = by_id.get(cfg.id)
        if pair is None:
            errors.append({"id": cfg.id, "error": "timeout"})
            logger.warning("brief_mail account_id=%s error=timeout", cfg.id)
            continue
        _, res = pair
        if isinstance(res, Exception):
            err = _classify_imap_error(res)
            errors.append({"id": cfg.id, "error": err})
            logger.warning("brief_mail account_id=%s error=%s", cfg.id, err)
            continue
        msgs = list(res.get("messages") or [])
        fetched_n = len(msgs)
        if fetched_n >= _MAX_PER_ACCOUNT:
            truncated = True
        if total_msgs >= _MAX_TOTAL:
            truncated = True
            msgs = []
        elif total_msgs + len(msgs) > _MAX_TOTAL:
            msgs = msgs[: max(0, _MAX_TOTAL - total_msgs)]
            truncated = True
        total_msgs += len(msgs)
        accounts_out.append(
            {
                "id": cfg.id,
                "label": cfg.label,
                "priority": cfg.priority,
                "count": len(msgs),
                "messages": msgs,
            }
        )

    logger.info(
        "brief_mail window_hours=%s accounts=%s messages=%s errors=%s truncated=%s",
        hours,
        len(accounts_out),
        total_msgs,
        len(errors),
        truncated,
    )
    return {
        "window_hours": hours,
        "generated_at": generated_at,
        "truncated": truncated,
        "errors": errors,
        "accounts": accounts_out,
    }
