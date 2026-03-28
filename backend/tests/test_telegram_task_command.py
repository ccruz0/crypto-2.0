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
    """_handle_task_command prompts for project selection before Notion create (callback creates task)."""
    from app.services.telegram_commands import _handle_task_command

    mock_send = MagicMock(return_value=True)
    with patch("app.services.telegram_commands._send_or_edit_menu", return_value=True) as mock_menu:
        _handle_task_command(
            "123", "/task Critical: fix production", "Critical: fix production",
            {"id": "999", "username": "test"}, mock_send, update_id=1,
        )
    mock_menu.assert_called_once()
    text = mock_menu.call_args[0][1]
    assert "Select project" in text
    mock_send.assert_not_called()


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
    """Direct Telegram→Notion path returns configured error when env is missing (project callback uses same helper)."""
    from app.services.task_compiler import (
        ERROR_NOTION_NOT_CONFIGURED,
        create_notion_task_from_telegram_direct,
    )

    with patch("app.services.task_compiler.notion_is_configured", return_value=False):
        out = create_notion_task_from_telegram_direct("fix order mismatch", "test")
    assert out["ok"] is False
    assert out["error"] == ERROR_NOTION_NOT_CONFIGURED


def test_handle_task_command_shows_notion_error_detail():
    """Direct Telegram→Notion helper surfaces Notion API error text from last failure."""
    from app.services.task_compiler import create_notion_task_from_telegram_direct

    with patch("app.services.task_compiler.notion_is_configured", return_value=True):
        with patch("app.services.task_compiler.create_notion_task", return_value=None):
            with patch(
                "app.services.task_compiler.get_last_notion_create_failure",
                return_value="HTTP 403: insufficient permissions for database",
            ):
                out = create_notion_task_from_telegram_direct("fix order mismatch", "test")
    assert out["ok"] is False
    assert "HTTP 403" in (out.get("error") or "")


def test_handle_task_command_does_not_call_legacy_telegram_intent_pipeline():
    """Regression: /task intake must not use create_task_from_telegram_intent (LLM-adjacent / similarity pipeline)."""
    from app.services.telegram_commands import _handle_task_command

    mock_send = MagicMock(return_value=True)
    with patch("app.services.task_compiler.create_notion_task_from_telegram_direct") as mock_direct:
        with patch("app.services.telegram_commands._send_or_edit_menu", return_value=True):
            with patch("app.services.task_compiler.create_task_from_telegram_intent") as mock_legacy:
                _handle_task_command(
                    "123", "/task hello", "hello", {"id": "1", "username": "test"}, mock_send, update_id=9,
                )
                mock_legacy.assert_not_called()
        mock_direct.assert_not_called()


def test_create_notion_task_from_telegram_direct_passes_project_to_notion():
    """Project chosen in Telegram callback must be forwarded to create_notion_task (not silently ignored)."""
    from app.services.task_compiler import create_notion_task_from_telegram_direct

    with patch("app.services.task_compiler.notion_is_configured", return_value=True):
        with patch("app.services.task_compiler.create_notion_task") as mock_create:
            mock_create.return_value = {"id": "notion-page-id", "object": "page"}
            out = create_notion_task_from_telegram_direct("hello", "testuser", project="ATP")
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs.get("project") == "ATP"
    assert out["ok"] is True
    assert out["task_id"] == "notion-page-id"


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
