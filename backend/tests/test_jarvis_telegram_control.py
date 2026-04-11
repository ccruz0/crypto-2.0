"""Tests for Jarvis Telegram control (allowlists, routing, formatters)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.jarvis import telegram_control as tc


@pytest.fixture
def clear_jarvis_env(monkeypatch):
    """Isolate env for each test."""
    for k in (
        "JARVIS_TELEGRAM_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_CHAT_IDS",
        "TELEGRAM_ALLOWED_USER_IDS",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_allowlisted_chat_and_user_accepted(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "-1001, -1002")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42; 99")
    assert tc.jarvis_telegram_allowed("-1001", "42") is True


def test_non_allowlisted_rejected(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "-1001")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    assert tc.jarvis_telegram_allowed("-9999", "42") is False
    assert tc.jarvis_telegram_allowed("-1001", "43") is False


def test_jarvis_command_classify_routes():
    assert tc.classify_jarvis_command("/jarvis hello") == ("jarvis", "hello")
    assert tc.classify_jarvis_command("/pending") == ("pending", "")
    rid = "550e8400-e29b-41d4-a716-446655440000"
    assert tc.classify_jarvis_command(f"/status {rid}") == ("approval_status", rid)
    assert tc.classify_jarvis_command("/status") is None
    assert tc.classify_jarvis_command("/approve abc note here") == (
        "approve",
        "abc\nnote here",
    )
    assert tc.classify_jarvis_command(f"/approve {rid} my reason") == (
        "approve",
        f"{rid}\nmy reason",
    )


def test_maybe_handle_disabled_does_not_dispatch(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "false")
    sent: list[str] = []

    def send(msg: str) -> None:
        sent.append(msg)

    ok = tc.maybe_handle_jarvis_telegram_message(
        raw_text="/jarvis hi",
        chat_id="1",
        actor_user_id="2",
        from_user={"id": 2, "username": "op"},
        send=send,
    )
    assert ok is True
    assert sent and "disabled" in sent[0].lower()


def test_maybe_handle_routes_jarvis_with_mocks(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "10")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "20")

    sent: list[str] = []

    def send(msg: str) -> None:
        sent.append(msg)

    with patch("app.jarvis.telegram_control.run_jarvis") as rj:
        rj.return_value = {
            "input": "hi",
            "plan": {"action": "get_unix_time", "args": {}, "reasoning": "t"},
            "result": {"unix": 1},
            "jarvis_run_id": "rid-1",
        }
        ok = tc.maybe_handle_jarvis_telegram_message(
            raw_text="/jarvis hi",
            chat_id="10",
            actor_user_id="20",
            from_user={"id": 20, "username": "alice"},
            send=send,
        )
    assert ok is True
    rj.assert_called_once_with("hi")
    assert sent
    assert "rid-1" in sent[0]
    assert "get_unix_time" in sent[0] or "plan=" in sent[0]


def test_approve_passes_actor(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "1")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "2")
    rid = "550e8400-e29b-41d4-a716-446655440000"

    sent: list[str] = []

    def send(msg: str) -> None:
        sent.append(msg)

    with patch(
        "app.jarvis.telegram_control.dispatch_jarvis_command",
        return_value=("approve", {"status": "ok", "jarvis_run_id": rid}),
    ) as disp:
        ok = tc.maybe_handle_jarvis_telegram_message(
            raw_text=f"/approve {rid} because",
            chat_id="1",
            actor_user_id="2",
            from_user={"id": 2, "username": "bob"},
            send=send,
        )
    assert ok is True
    disp.assert_called_once()
    pos = disp.call_args[0]
    kwargs = disp.call_args[1]
    assert pos[0] == "approve"
    assert rid in (pos[1] or "")
    assert "because" in (pos[1] or "")
    assert kwargs.get("actor") == "@bob"


def test_actor_string_username_vs_name():
    assert tc.actor_from_telegram_user({"id": 5, "username": "ops"}) == "@ops"
    assert "id:7" in tc.actor_from_telegram_user({"id": 7, "first_name": "Pat"})


def test_compact_formatter_truncation():
    long_payload = {"status": "ok", "approvals": [{"jarvis_run_id": "x" * 200}]}
    out = tc.format_compact_jarvis_reply("pending", long_payload)
    assert len(out) <= 4000


def test_empty_allowlists_reject(clear_jarvis_env, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    sent: list[str] = []

    def send(msg: str) -> None:
        sent.append(msg)

    ok = tc.maybe_handle_jarvis_telegram_message(
        raw_text="/pending",
        chat_id="1",
        actor_user_id="2",
        from_user={"id": 2},
        send=send,
    )
    assert ok is True
    assert "allowlist" in sent[0].lower() or "configure" in sent[0].lower()
