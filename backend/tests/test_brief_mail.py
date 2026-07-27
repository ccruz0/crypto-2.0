"""Tests for GET /api/brief/mail."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.header import Header
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brief.mail import decode_mime_header, html_to_text, _extract_original_from
from app.brief.rate_limit import reset_brief_rate_limit_for_tests
from app.brief.router import router as brief_router


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_brief_rate_limit_for_tests()
    yield
    reset_brief_rate_limit_for_tests()


@pytest.fixture
def client(tmp_path):
    mailboxes = [
        {
            "id": "hilovivo",
            "label": "Hilovivo",
            "host": "imap.example.com",
            "port": 993,
            "ssl": True,
            "user": "a@example.com",
            "password": "secret-a",
            "folder": "INBOX",
            "priority": "alta",
        },
        {
            "id": "peluqueria",
            "label": "Peluqueria",
            "host": "imap.example.com",
            "port": 993,
            "ssl": True,
            "user": "b@example.com",
            "password": "secret-b",
            "folder": "INBOX",
            "priority": "media",
        },
        {
            "id": "hotmail-fw",
            "label": "Hotmail (reenviado)",
            "host": "imap.example.com",
            "port": 993,
            "ssl": True,
            "user": "fw@example.com",
            "password": "secret-fw",
            "folder": "INBOX",
            "priority": "alta",
        },
    ]
    cfg = tmp_path / "brief_mailboxes.json"
    cfg.write_text(json.dumps(mailboxes), encoding="utf-8")
    app = FastAPI()
    app.include_router(brief_router)
    with patch.dict(
        os.environ,
        {
            "BRIEF_API_KEY": "test-brief-key-123456",
            "BRIEF_MAILBOXES_PATH": str(cfg),
            "BRIEF_RATE_LIMIT_PER_MINUTE": "100",
        },
    ):
        yield TestClient(app)


def _make_raw_email(
    *,
    subject: str,
    from_addr: str,
    body: str,
    when: datetime,
    html: bool = False,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["Date"] = when.strftime("%a, %d %b %Y %H:%M:%S +0000")
    if html:
        msg.set_content(body, subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


def test_mail_unauthorized(client):
    r = client.get("/api/brief/mail")
    assert r.status_code == 401


def test_mail_wrong_key(client):
    r = client.get("/api/brief/mail", headers={"X-Brief-Key": "nope"})
    assert r.status_code == 401


def test_decode_mime_accents():
    raw = str(Header("Reunión mañana ☕", "utf-8"))
    assert "Reunión" in decode_mime_header(raw)
    assert "☕" in decode_mime_header(raw)


def test_html_to_text_strips_tags():
    assert "<" not in html_to_text("<p>Hola <b>mundo</b></p><style>x{}</style>")
    assert "Hola" in html_to_text("<p>Hola <b>mundo</b></p>")


def test_hotmail_original_from():
    preview = "---------- Forwarded message ----------\nFrom: Ana Pérez <ana@contoso.com>\nSubject: Hola"
    assert "ana@contoso.com" in (_extract_original_from(preview) or "")


def test_mail_window_and_partial_failure(client):
    now = datetime.now(timezone.utc)
    recent = _make_raw_email(
        subject=str(Header("Pedido urgente café", "utf-8")),
        from_addr="Cliente <cliente@shop.test>",
        body="Necesito confirmación del pedido.",
        when=now - timedelta(hours=2),
    )
    old = _make_raw_email(
        subject="Viejo",
        from_addr="old@test",
        body="fuera de ventana",
        when=now - timedelta(hours=48),
    )
    fwd = _make_raw_email(
        subject="FW: Hola",
        from_addr="relay@hilovivo.com",
        body="From: Ana Pérez <ana@contoso.com>\n\nHola Carlos",
        when=now - timedelta(hours=1),
    )

    def _fake_fetch(cfg, since, limit):
        if cfg.id == "peluqueria":
            raise ConnectionError("auth failed")
        if cfg.id == "hotmail-fw":
            # Use real parser path via building message list manually through internal helpers
            from app.brief import mail as mail_mod
            import email as email_lib

            msg = email_lib.message_from_bytes(fwd)
            from_name, from_addr = mail_mod._parse_from(msg)
            preview = mail_mod._body_preview(msg)
            row = {
                "from_name": from_name,
                "from": from_addr,
                "subject": mail_mod.decode_mime_header(msg.get("Subject")),
                "at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "unread": True,
                "preview": preview,
            }
            orig = mail_mod._extract_original_from(preview)
            if orig:
                row["original_from"] = orig
            return {"messages": [row]}
        # hilovivo
        import email as email_lib
        from app.brief import mail as mail_mod

        msgs = []
        for raw in (recent, old):
            msg = email_lib.message_from_bytes(raw)
            at = mail_mod._message_date_utc(msg)
            if at is None or at < since:
                continue
            name, addr = mail_mod._parse_from(msg)
            msgs.append(
                {
                    "from_name": name,
                    "from": addr,
                    "subject": mail_mod.decode_mime_header(msg.get("Subject")),
                    "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "unread": True,
                    "preview": mail_mod._body_preview(msg),
                }
            )
        return {"messages": msgs[:limit]}

    with patch("app.brief.mail._fetch_one_account", side_effect=_fake_fetch):
        # Force auth_failed classification for peluqueria
        def _job_wrap(cfg, since, limit):
            if cfg.id == "peluqueria":
                import imaplib

                raise imaplib.IMAP4.error("LOGIN failed authentication failed")
            return _fake_fetch(cfg, since, limit)

        with patch("app.brief.mail._fetch_one_account", side_effect=_job_wrap):
            r = client.get(
                "/api/brief/mail?hours=24",
                headers={"X-Brief-Key": "test-brief-key-123456"},
            )

    assert r.status_code == 200
    body = r.json()
    assert body["window_hours"] == 24
    assert body["truncated"] is False
    err_ids = {e["id"] for e in body["errors"]}
    assert "peluqueria" in err_ids
    assert any(e["error"] == "auth_failed" for e in body["errors"])
    # Passwords never leaked
    dumped = json.dumps(body)
    assert "secret-a" not in dumped
    assert "secret-b" not in dumped

    by_id = {a["id"]: a for a in body["accounts"]}
    assert by_id["hilovivo"]["count"] == 1
    assert "Pedido" in by_id["hilovivo"]["messages"][0]["subject"]
    assert by_id["hotmail-fw"]["label"] == "Hotmail (reenviado)"
    assert "original_from" in by_id["hotmail-fw"]["messages"][0]
    assert "ana@contoso.com" in by_id["hotmail-fw"]["messages"][0]["original_from"]
