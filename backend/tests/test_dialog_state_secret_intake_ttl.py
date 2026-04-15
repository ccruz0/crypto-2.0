"""Secret marketing intake TTL: long default + sliding last-activity deadline."""

from __future__ import annotations

import pytest

from app.jarvis import dialog_state as ds
from app.jarvis.dialog_state import DialogState, get_state, reset_store_for_tests, set_state


def test_secret_intake_expires_after_idle_past_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_for_tests()
    # Minimum clamp in dialog_state is 300s; use floor TTL for a deterministic expiry.
    monkeypatch.setenv("JARVIS_TELEGRAM_INTAKE_TTL_SECONDS", "300")

    chat_id, user_id = "c-ttl", "u-ttl"
    st = DialogState()
    st.pending_secret_key = "google_search_console_site"
    st.pending_secret_phase = "await_value"
    st.secret_intake_started_at = 1000.0
    st.secret_intake_last_activity_at = 1000.0
    set_state(chat_id, user_id, st)

    monkeypatch.setattr(ds.time, "time", lambda: 1301.0)
    assert get_state(chat_id, user_id) is None


def test_secret_intake_sliding_activity_extends_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_store_for_tests()
    monkeypatch.setenv("JARVIS_TELEGRAM_INTAKE_TTL_SECONDS", "300")

    chat_id, user_id = "c-slide", "u-slide"
    st = DialogState()
    st.pending_secret_key = "google_search_console_site"
    st.pending_secret_phase = "await_value"
    st.secret_intake_started_at = 1000.0
    st.secret_intake_last_activity_at = 1000.0
    set_state(chat_id, user_id, st)

    # Near expiry from initial activity (deadline 1300).
    monkeypatch.setattr(ds.time, "time", lambda: 1290.0)
    assert get_state(chat_id, user_id) is not None

    st2 = get_state(chat_id, user_id)
    assert st2 is not None
    st2.secret_intake_last_activity_at = 1290.0
    set_state(chat_id, user_id, st2)

    # Would be past 1300 without sliding; with last_activity 1290, deadline is 1590.
    monkeypatch.setattr(ds.time, "time", lambda: 1350.0)
    assert get_state(chat_id, user_id) is not None
