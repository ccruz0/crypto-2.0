"""Jarvis free-text routing in authorized private operator chats (Telegram poller path)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_dialog_state() -> None:
    from app.jarvis.dialog_state import reset_store_for_tests

    reset_store_for_tests()
    yield
    reset_store_for_tests()


@pytest.fixture
def _jarvis_telegram_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-placeholder")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "12345")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "12345")
    # ``telegram_control`` binds ``run_jarvis`` at import time; patch that reference.
    monkeypatch.setattr("app.services.telegram_commands.TELEGRAM_ENABLED", True, raising=False)


def _marketing_like_jarvis_result() -> dict:
    return {
        "jarvis_run_id": "run-test",
        "plan": {"action": "run_marketing_review", "args": {}, "reasoning": "t"},
        "result": {
            "analysis_status": "ok",
            "proposal_status": "ok",
            "top_findings": [],
            "proposed_actions": [],
            "summary": "stub marketing summary",
            "status": "ok",
        },
    }


def test_free_text_marketing_request_reaches_run_jarvis(
    monkeypatch: pytest.MonkeyPatch, _jarvis_telegram_env
) -> None:
    sent: list[str] = []

    def _capture_send(chat_id: str, msg: str) -> bool:
        sent.append(msg)
        return True

    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        _capture_send,
    )

    with patch("app.jarvis.telegram_control.run_jarvis", return_value=_marketing_like_jarvis_result()) as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920001,
                "message": {
                    "message_id": 1,
                    "text": "analiza mi web de la peluqueria y dime que mejorar",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )

    mock_rj.assert_called_once()
    (arg,) = mock_rj.call_args[0]
    assert "peluquer" in arg.lower()
    assert "Operator Telegram chat" in arg
    assert len(sent) == 1
    assert "Marketing Review" in sent[0] or "marketing" in sent[0].lower()


def test_free_text_plain_still_reaches_jarvis_without_hint_prefix(
    monkeypatch: pytest.MonkeyPatch, _jarvis_telegram_env
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        lambda c, m: True,
    )
    with patch("app.jarvis.telegram_control.run_jarvis", return_value=_marketing_like_jarvis_result()) as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920002,
                "message": {
                    "message_id": 2,
                    "text": "hello operator ping",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )
    mock_rj.assert_called_once()
    (arg,) = mock_rj.call_args[0]
    assert arg == "hello operator ping"
    assert "Operator Telegram chat" not in arg


def test_secret_intake_priority_over_free_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path, _jarvis_telegram_env
) -> None:
    from app.jarvis.dialog_state import reset_store_for_tests
    from app.jarvis.telegram_secret_intake import begin_marketing_setting_intake

    reset_store_for_tests()
    rt = str(tmp_path / "runtime.env")
    begin_marketing_setting_intake(
        "12345",
        "12345",
        setting_key="google_ads_developer_token",
        runtime_env_path_override=rt,
    )

    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        lambda c, m: True,
    )

    with patch("app.jarvis.telegram_control.run_jarvis") as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920003,
                "message": {
                    "message_id": 3,
                    "text": "analiza mi marketing mañana",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )

    mock_rj.assert_not_called()


def test_unauthorized_private_chat_no_free_text_jarvis(
    monkeypatch: pytest.MonkeyPatch, _jarvis_telegram_env
) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "99999")
    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        lambda c, m: True,
    )
    with patch("app.jarvis.telegram_control.run_jarvis") as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920004,
                "message": {
                    "message_id": 4,
                    "text": "review my marketing",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )
    mock_rj.assert_not_called()


def test_non_private_group_skips_free_text_jarvis(
    monkeypatch: pytest.MonkeyPatch, _jarvis_telegram_env
) -> None:
    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        lambda c, m: True,
    )
    with patch("app.jarvis.telegram_control.run_jarvis") as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920005,
                "message": {
                    "message_id": 5,
                    "text": "review my marketing in this group",
                    "chat": {"id": 12345, "type": "supergroup", "title": "X"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )
    mock_rj.assert_not_called()


def test_slash_jarvis_still_uses_existing_path(
    monkeypatch: pytest.MonkeyPatch, _jarvis_telegram_env
) -> None:
    monkeypatch.setenv("TELEGRAM_AUTH_USER_ID", "12345")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        lambda c, m: True,
    )
    with patch("app.jarvis.telegram_control.run_jarvis", return_value=_marketing_like_jarvis_result()) as mock_rj:
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 920006,
                "message": {
                    "message_id": 6,
                    "text": "/jarvis review marketing briefly",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "op"},
                },
            },
            db=None,
        )
    mock_rj.assert_called_once()
    (arg,) = mock_rj.call_args[0]
    assert arg == "review marketing briefly"
