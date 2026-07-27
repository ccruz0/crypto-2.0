"""Tests for GET /api/brief/telegram and POST /api/brief/send."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brief.rate_limit import reset_brief_rate_limit_for_tests
from app.brief.router import router as brief_router
from app.brief.telegram_read import TelegramSessionMissing, _is_broadcast_channel
from app.brief.telegram_send import split_telegram_text


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_brief_rate_limit_for_tests()
    yield
    reset_brief_rate_limit_for_tests()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(brief_router)
    with patch.dict(
        os.environ,
        {
            "BRIEF_API_KEY": "test-brief-key-123456",
            "BRIEF_RATE_LIMIT_PER_MINUTE": "100",
            "TELEGRAM_BOT_TOKEN": "bot-token-test",
            "TELEGRAM_CHAT_ID": "12345",
            "TELEGRAM_API_ID": "111",
            "TELEGRAM_API_HASH": "hash-test",
            "TELEGRAM_SESSION_PATH": "/tmp/brief-test.session",
        },
    ):
        yield TestClient(app)


def test_telegram_unauthorized(client):
    r = client.get("/api/brief/telegram")
    assert r.status_code == 401


def test_telegram_session_missing_409(client):
    with patch(
        "app.brief.router.fetch_telegram",
        side_effect=TelegramSessionMissing("session_file_missing"),
    ):
        r = client.get(
            "/api/brief/telegram",
            headers={"X-Brief-Key": "test-brief-key-123456"},
        )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "telegram_session_missing"
    assert "telegram_login.py" in detail["hint"]


def test_telegram_ok(client):
    payload = {
        "window_hours": 24,
        "generated_at": "2026-07-28T01:00:00Z",
        "truncated": False,
        "chats": [
            {
                "chat": "Ana",
                "chat_type": "private",
                "unread": 1,
                "messages": [{"from": "Ana", "at": "2026-07-27T18:22:00Z", "text": "hola"}],
            }
        ],
    }
    with patch("app.brief.router.fetch_telegram", return_value=payload):
        r = client.get(
            "/api/brief/telegram?hours=24",
            headers={"X-Brief-Key": "test-brief-key-123456"},
        )
    assert r.status_code == 200
    assert r.json()["chats"][0]["chat_type"] == "private"


def test_exclude_broadcast_channels():
    class FakeChannel:
        pass

    broadcast = FakeChannel()
    broadcast.broadcast = True
    broadcast.megagroup = False

    group = FakeChannel()
    group.broadcast = True
    group.megagroup = True  # megagroup counts as group, not broadcast feed

    with patch("telethon.tl.types.Channel", FakeChannel):
        assert _is_broadcast_channel(broadcast) is True
        assert _is_broadcast_channel(group) is False


def test_split_over_4096():
    line = "x" * 1000
    text = "\n".join([line] * 5)
    parts = split_telegram_text(text, limit=4096)
    assert len(parts) >= 2
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(parts) == text


def test_send_unauthorized(client):
    r = client.post("/api/brief/send", json={"text": "hi"})
    assert r.status_code == 401


def test_send_splits_and_posts(client):
    calls = []

    class _Resp:
        status_code = 200

    def _http_post(url, json=None, timeout=None, calling_module=None):
        assert "api.telegram.org/bot" in url
        assert "bot-token-test" in url
        calls.append(json)
        return _Resp()

    big = "hola\n" * 900
    with patch("app.utils.http_client.http_post", _http_post):
        r = client.post(
            "/api/brief/send",
            headers={"X-Brief-Key": "test-brief-key-123456"},
            json={"text": big, "parse_mode": "HTML"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["parts"] >= 2
    assert len(calls) == body["parts"]
    assert all(c["chat_id"] == "12345" for c in calls)
    assert all(c.get("parse_mode") == "HTML" for c in calls)
