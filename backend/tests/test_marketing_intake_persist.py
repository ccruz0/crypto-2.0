"""DB-backed rehydration for Jarvis marketing Telegram intake."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.database import ensure_jarvis_marketing_intake_table
from app.jarvis.dialog_state import get_state, reset_store_for_tests
from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake, handle_secret_intake_turn


def test_intake_rehydrates_from_db_after_memory_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dbfile = tmp_path / "intake.sqlite"
    eng = create_engine(f"sqlite:///{dbfile}")
    assert ensure_jarvis_marketing_intake_table(eng)
    monkeypatch.setattr("app.database.engine", eng)
    monkeypatch.setenv("RUNTIME_ENV_PATH", str(tmp_path / "runtime.env"))

    reset_store_for_tests()
    begin_marketing_setting_intake(
        "chat-h",
        "user-h",
        setting_key="search_console_site_url",
        resume_args={"days_back": 30},
    )
    assert get_state("chat-h", "user-h") is not None

    reset_store_for_tests()
    assert get_state("chat-h", "user-h") is None

    out = handle_secret_intake_turn("https://example.com/foo", chat_id="chat-h", user_id="user-h")
    assert out is not None
    assert "resume_plan" in out
