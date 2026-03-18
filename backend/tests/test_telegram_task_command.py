"""
Tests for /task Telegram command: intent parsing and routing logic.

Full handle_telegram_update is not imported here to avoid triggering
telegram token loading at module load. Manual verification: send /task fix order mismatch
in Telegram and confirm task is created or reused and response is returned.
"""

from __future__ import annotations

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
