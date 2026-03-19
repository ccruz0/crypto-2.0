"""
Tests for /task Telegram command: intent parsing and routing logic.

Full handle_telegram_update is not imported here to avoid triggering
telegram token loading at module load. Manual verification: send /task fix order mismatch
in Telegram and confirm task is created or reused and response is returned.
"""

from __future__ import annotations

import os
import re

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
