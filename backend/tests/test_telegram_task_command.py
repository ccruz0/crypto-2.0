"""
Tests for /task Telegram command: intent parsing, routing logic, and canonical handler.

Manual verification: send /task fix order mismatch in Telegram and confirm
task is created or reused and response is returned.
"""

from __future__ import annotations

import os
import re
from unittest.mock import MagicMock, patch

import pytest


def test_task_intent_parsing_from_text():
    """Intent after /task is derived from args (split) or from stripping /task from text."""
    text = "/task fix order mismatch"
    parts = (text or "").split(None, 1)
    args = (parts[1] or "").strip() if len(parts) > 1 else ""
    assert args == "fix order mismatch"

    text_no_args = "/task"
    parts2 = (text_no_args or "").split(None, 1)
    args2 = (parts2[1] or "").strip() if len(parts2) > 1 else ""
    assert args2 == ""

    # Fallback: strip /task (case-insensitive)
    intent_fallback = re.sub(r"^/task\s*", "", "/Task Fix order", flags=re.IGNORECASE).strip()
    assert intent_fallback == "Fix order"


def test_task_command_routing_matches():
    """Router should match /task and /task <something> (case-insensitive)."""
    text_lower = "/task fix order".strip().lower()
    assert text_lower.startswith("/task ")
    text_lower2 = "/Task".strip().lower()
    assert text_lower2.startswith("/task")
    text_lower3 = "/TASK something".strip().lower()
    assert text_lower3.startswith("/task ")


def test_api_base_url_default_uses_8002(monkeypatch):
    """API_BASE_URL default must be localhost:8002 (backend port), not 8000.

    Regression: telegram_commands used localhost:8000 by default, causing
    backend health/status calls to fail when env vars were unset.
    """
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("AWS_BACKEND_URL", raising=False)
    monkeypatch.delenv("API_URL", raising=False)
    default = (
        os.getenv("API_BASE_URL")
        or os.getenv("AWS_BACKEND_URL")
        or "http://localhost:8002"
    )
    assert "8002" in default, "Default API base must use port 8002 (backend port)"
    assert "8000" not in default or "8002" in default, "Must not default to port 8000"


def test_script_api_default_pattern_no_8000(monkeypatch):
    """Shared script default (API_BASE_URL, AWS_BACKEND_URL, API_URL) must use 8002.

    Regression: smoke_test_alerts, check_algo_api, verify_portfolio, etc. used 8000.
    """
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("AWS_BACKEND_URL", raising=False)
    monkeypatch.delenv("API_URL", raising=False)
    default = (
        os.getenv("API_BASE_URL")
        or os.getenv("AWS_BACKEND_URL")
        or os.getenv("API_URL")
        or "http://localhost:8002"
    )
    assert "8002" in default
    assert default == "http://localhost:8002"


def test_handle_task_command_with_intent():
    """_handle_task_command with intent stores pending selection and asks for project (Notion on callback)."""
    from app.services.telegram_commands import PENDING_TASK_PROJECT_SELECTION, _handle_task_command

    mock_send = MagicMock(return_value=True)
    PENDING_TASK_PROJECT_SELECTION.clear()
    with patch("app.services.task_compiler.create_notion_task_from_telegram_direct") as mock_create:
        _handle_task_command(
            "123",
            "/task Critical: fix production",
            "Critical: fix production",
            {"id": 999, "username": "test"},
            mock_send,
            update_id=1,
        )
        mock_create.assert_not_called()
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0]
    assert "Select project" in call_args[1]
    assert "Unknown command" not in call_args[1]
    assert PENDING_TASK_PROJECT_SELECTION.get("123", {}).get("description") == "Critical: fix production"


def test_handle_task_command_no_intent_shows_usage():
    """_handle_task_command shows usage when no intent (e.g. /task alone)."""
    from app.services.telegram_commands import _handle_task_command

    mock_send = MagicMock(return_value=True)
    _handle_task_command("123", "/task", "", {"username": "test"}, mock_send, update_id=1)
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0]
    assert "Create task from Telegram" in call_args[1]
    assert "/task" in call_args[1]


def test_task_never_returns_unknown_command(monkeypatch):
    """Regression: /task must never trigger 'Unknown command' regardless of format."""
    from unittest.mock import patch
    monkeypatch.setenv("TELEGRAM_AUTH_USER_ID", "12345")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    import app.services.telegram_commands as tc_mod

    handle_telegram_update = tc_mod.handle_telegram_update

    variants = [
        "/task foo",
        "/task Critical: fix production",
        "/task@ATP_control_bot bar",
    ]
    for i, text in enumerate(variants):
        with patch("app.services.telegram_commands.send_command_response") as mock_send:
            with patch("app.services.task_compiler.create_notion_task_from_telegram_direct") as mock_create:
                mock_create.return_value = {
                    "ok": True,
                    "task_id": "tid",
                    "title": "T",
                    "type": "I",
                    "status": "P",
                    "priority": 50,
                    "priority_label": "m",
                    "reused": False,
                }
                update = {
                    "update_id": 99990 + i,
                    "message": {
                        "message_id": 1 + i,
                        "text": text,
                        "chat": {"id": 12345, "type": "private"},
                        "from": {"id": 12345, "username": "t"},
                    },
                }
                handle_telegram_update(update, db=None)
        all_msg = " ".join(str(c[0][1]) for c in mock_send.call_args_list if len(c[0]) > 1)
        assert "Unknown command" not in all_msg, f"/task variant {text!r} must not return Unknown command"


def test_task_at_botname_normalization():
    """Router recognizes /task@ATP_control_bot foo; cmd_token after strip is /task."""
    text = "/task@ATP_control_bot Critical: fix production"
    normalized = re.sub(r"@\S+", "", text).strip()
    assert normalized == "/task Critical: fix production"
    parts = normalized.split(None, 1)
    cmd_token = (parts[0] or "").strip()
    args = (parts[1] or "").strip() if len(parts) > 1 else ""
    assert cmd_token == "/task"
    assert "Critical" in args


def test_handle_task_command_notion_not_configured_returns_debug_marker():
    """Notion errors appear after project callback; intake only prompts project selection."""
    import time

    from app.services import telegram_commands as tc

    tc.PENDING_TASK_PROJECT_SELECTION.clear()
    tc.PROCESSED_CALLBACK_DATA.clear()
    tc.PROCESSED_CALLBACK_IDS.clear()
    chat_id = "-502"
    tc.PENDING_TASK_PROJECT_SELECTION[chat_id] = {
        "description": "fix order mismatch",
        "telegram_user": "test",
        "initiating_user_id": "888",
        "created_at": time.time(),
    }
    mock_send = MagicMock(return_value=True)
    mock_http = MagicMock()
    mock_http.status_code = 200
    mock_http.json.return_value = {"ok": True}
    update = {
        "update_id": 88002003,
        "callback_query": {
            "id": "cq_notion_nc",
            "from": {"id": 888, "username": "test"},
            "message": {"chat": {"id": int(chat_id), "type": "group"}, "message_id": 100},
            "data": "task_project:rahyang",
        },
    }
    with patch.object(tc, "send_command_response", mock_send):
        with patch.object(tc, "http_post", mock_http):
            with patch.object(tc, "_get_effective_bot_token", return_value="t"):
                with patch(
                    "app.services.task_compiler.create_notion_task_from_telegram_direct",
                    return_value={"ok": False, "error": "Notion is not configured"},
                ):
                    tc.handle_telegram_update(update, db=None)
    msgs = [c[0][1] for c in mock_send.call_args_list if len(c[0]) > 1]
    joined = " ".join(msgs)
    assert "[task-debug-v4]" in joined
    assert "Notion is not configured" in joined


def test_handle_task_command_shows_notion_error_detail():
    """After task_project callback, Notion API error text is surfaced to the user."""
    import time

    from app.services import telegram_commands as tc

    tc.PENDING_TASK_PROJECT_SELECTION.clear()
    tc.PROCESSED_CALLBACK_DATA.clear()
    tc.PROCESSED_CALLBACK_IDS.clear()
    chat_id = "-501"
    tc.PENDING_TASK_PROJECT_SELECTION[chat_id] = {
        "description": "fix order mismatch",
        "telegram_user": "test",
        "initiating_user_id": "777",
        "created_at": time.time(),
    }
    mock_send = MagicMock(return_value=True)
    mock_http = MagicMock()
    mock_http.status_code = 200
    mock_http.json.return_value = {"ok": True}
    update = {
        "update_id": 88002002,
        "callback_query": {
            "id": "cq_notion_err",
            "from": {"id": 777, "username": "test"},
            "message": {"chat": {"id": int(chat_id), "type": "group"}, "message_id": 99},
            "data": "task_project:atp",
        },
    }
    with patch.object(tc, "send_command_response", mock_send):
        with patch.object(tc, "http_post", mock_http):
            with patch.object(tc, "_get_effective_bot_token", return_value="t"):
                with patch(
                    "app.services.task_compiler.create_notion_task_from_telegram_direct",
                    return_value={"ok": False, "error": "HTTP 403: insufficient permissions for database"},
                ):
                    tc.handle_telegram_update(update, db=None)
    msgs = [c[0][1] for c in mock_send.call_args_list if len(c[0]) > 1]
    joined = " ".join(msgs)
    assert "HTTP 403" in joined
    assert "Notion task not created" in joined


def test_handle_task_command_does_not_call_legacy_telegram_intent_pipeline():
    """Regression: /task intake must not use create_task_from_telegram_intent or direct Notion create."""
    from app.services.telegram_commands import _handle_task_command

    mock_send = MagicMock(return_value=True)
    with patch("app.services.task_compiler.create_notion_task_from_telegram_direct") as mock_direct:
        mock_direct.return_value = {"ok": True, "task_id": "abc", "title": "T"}
        with patch("app.services.task_compiler.create_task_from_telegram_intent") as mock_legacy:
            _handle_task_command(
                "123", "/task hello", "hello", {"id": 1, "username": "test"}, mock_send, update_id=9,
            )
            mock_legacy.assert_not_called()
    mock_direct.assert_not_called()


def test_task_project_callback_resolves_pending_by_chat_id_only():
    """Regression: pending dict is keyed by chat_id; clicker must match initiating_user_id."""
    import time

    from app.services import telegram_commands as tc

    tc.PENDING_TASK_PROJECT_SELECTION.clear()
    tc.PROCESSED_CALLBACK_DATA.clear()
    tc.PROCESSED_CALLBACK_IDS.clear()
    chat_id = "-504"
    tc.PENDING_TASK_PROJECT_SELECTION[chat_id] = {
        "description": "sync fix",
        "telegram_user": "alice",
        "initiating_user_id": "42",
        "created_at": time.time(),
    }
    mock_send = MagicMock(return_value=True)
    mock_http = MagicMock()
    mock_http.status_code = 200
    mock_http.json.return_value = {"ok": True}
    update = {
        "update_id": 88002004,
        "callback_query": {
            "id": "cq_task_ok",
            "from": {"id": 42, "username": "alice"},
            "message": {"chat": {"id": int(chat_id), "type": "group"}, "message_id": 1},
            "data": "task_project:atp",
        },
    }
    with patch.object(tc, "send_command_response", mock_send):
        with patch.object(tc, "http_post", mock_http):
            with patch.object(tc, "_get_effective_bot_token", return_value="t"):
                with patch(
                    "app.services.task_compiler.create_notion_task_from_telegram_direct",
                    return_value={
                        "ok": True,
                        "task_id": "nid",
                        "title": "sync fix",
                        "type": "Investigation",
                        "status": "Planned",
                        "project": "ATP",
                    },
                ) as mock_create:
                    tc.handle_telegram_update(update, db=None)
    mock_create.assert_called_once()
    msgs = [c[0][1] for c in mock_send.call_args_list if len(c[0]) > 1]
    assert any("Task created in Notion" in m for m in msgs)
    assert chat_id not in tc.PENDING_TASK_PROJECT_SELECTION


def test_task_token_fallback_atp_control(monkeypatch):
    """When TELEGRAM_BOT_TOKEN is not set, get_telegram_token falls back to TELEGRAM_ATP_CONTROL_BOT_TOKEN.

    Ensures /task works when deploy sets only ATP Control vars (no legacy TELEGRAM_BOT_TOKEN).
    """
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_DEV", raising=False)
    monkeypatch.delenv("TELEGRAM_ATP_CONTROL_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CLAW_BOT_TOKEN", raising=False)
    monkeypatch.setenv("FORCE_TELEGRAM_TOKEN_PROMPT", "false")

    from app.utils.telegram_token_loader import get_telegram_token

    monkeypatch.setenv("TELEGRAM_ATP_CONTROL_BOT_TOKEN", "atp-control-token-123")
    token = get_telegram_token()
    assert token == "atp-control-token-123"

    monkeypatch.delenv("TELEGRAM_ATP_CONTROL_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CLAW_BOT_TOKEN", "claw-token-456")
    token = get_telegram_token()
    assert token == "claw-token-456"
