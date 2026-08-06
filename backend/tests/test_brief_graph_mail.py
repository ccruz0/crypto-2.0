"""Tests for Microsoft Graph brief mailbox reader."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.brief.graph_mail import fetch_graph_mailbox
from app.brief.mail import fetch_mail
from app.utils.egress_guard import is_domain_allowed


def test_microsoft_graph_domains_allowlisted():
    assert is_domain_allowed("login.microsoftonline.com")
    assert is_domain_allowed("graph.microsoft.com")


def test_fetch_graph_mailbox_maps_messages(monkeypatch):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "tok-test"}
    msg_resp = MagicMock()
    msg_resp.status_code = 200
    msg_resp.json.return_value = {
        "value": [
            {
                "subject": "Hello Bumi",
                "receivedDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "isRead": False,
                "bodyPreview": "preview text",
                "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
            }
        ]
    }

    monkeypatch.setenv("BRIEF_GRAPH_TENANT_ID", "tenant-1")
    monkeypatch.setenv("BRIEF_GRAPH_CLIENT_ID", "client-1")
    monkeypatch.setenv("BRIEF_GRAPH_CLIENT_SECRET", "secret-1")

    with patch("app.brief.graph_mail.http_post", return_value=token_resp) as post, patch(
        "app.brief.graph_mail.http_get", return_value=msg_resp
    ) as get:
        out = fetch_graph_mailbox(user="carlos.cruz@bumibeans.com", since=since, limit=10)

    assert post.called
    assert get.called
    assert len(out["messages"]) == 1
    assert out["messages"][0]["subject"] == "Hello Bumi"
    assert out["messages"][0]["from"] == "alice@example.com"
    assert out["messages"][0]["unread"] is True


def test_fetch_mail_routes_graph_provider(tmp_path, monkeypatch):
    cfg = [
        {
            "id": "bumibeans",
            "label": "Bumi Beans",
            "provider": "graph",
            "user": "carlos.cruz@bumibeans.com",
            "enabled": True,
            "priority": "alta",
        }
    ]
    path = tmp_path / "mailboxes.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("BRIEF_MAILBOXES_PATH", str(path))
    monkeypatch.setenv("BRIEF_GRAPH_TENANT_ID", "t")
    monkeypatch.setenv("BRIEF_GRAPH_CLIENT_ID", "c")
    monkeypatch.setenv("BRIEF_GRAPH_CLIENT_SECRET", "s")

    fake = {
        "messages": [
            {
                "from_name": "Bob",
                "from": "bob@x.com",
                "subject": "Hi",
                "at": "2026-08-06T12:00:00Z",
                "unread": True,
                "preview": "p",
            }
        ]
    }
    with patch("app.brief.graph_mail.fetch_graph_mailbox", return_value=fake) as mocked:
        out = fetch_mail(hours=24)
    assert mocked.called
    assert [a["id"] for a in out["accounts"]] == ["bumibeans"]
    assert out["accounts"][0]["count"] == 1
    assert out["errors"] == []


def test_classify_graph_error_preserves_http_detail():
    from app.brief.graph_mail import GraphAuthError, GraphConfigMissing, classify_graph_error

    assert classify_graph_error(GraphConfigMissing("x")) == "graph_config_missing"
    assert (
        classify_graph_error(GraphAuthError("graph_messages_http_403:Authorization_RequestDenied"))
        == "graph_messages_http_403:Authorization_RequestDenied"
    )
    assert classify_graph_error(GraphAuthError("other")) == "auth_failed"


def test_graph_http_error_parses_aad_and_graph_codes():
    from app.brief.graph_mail import _graph_http_error

    aad = MagicMock()
    aad.status_code = 401
    aad.json.return_value = {"error": "invalid_client", "error_description": "secret expired"}
    assert _graph_http_error("graph_token", aad) == "graph_token_http_401:invalid_client"

    graph = MagicMock()
    graph.status_code = 403
    graph.json.return_value = {"error": {"code": "Authorization_RequestDenied", "message": "x"}}
    assert (
        _graph_http_error("graph_messages", graph)
        == "graph_messages_http_403:Authorization_RequestDenied"
    )
