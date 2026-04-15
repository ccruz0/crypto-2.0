"""End-to-end: Telegram poller path runs secret intake and resumes marketing review."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def _jarvis_telegram_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-placeholder")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "12345")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "12345")


def test_handle_telegram_update_secret_intake_resumes_marketing_review(
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
        resume_action="run_marketing_review",
        resume_args={},
        runtime_env_path_override=rt,
    )

    sent: list[str] = []

    def _capture_send(chat_id: str, msg: str) -> bool:
        sent.append(msg)
        return True

    monkeypatch.setattr(
        "app.services.telegram_commands.send_command_response",
        _capture_send,
    )

    marketing_stub = {
        "analysis_status": "ok",
        "proposal_status": "ok",
        "top_findings": [],
        "tool": "run_marketing_review",
    }

    with patch("app.jarvis.telegram_control.execute_plan", return_value=marketing_stub):
        from app.services.telegram_commands import handle_telegram_update

        handle_telegram_update(
            {
                "update_id": 910001,
                "message": {
                    "message_id": 1,
                    "text": "telegram",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "t"},
                },
            },
            db=None,
        )
        assert len(sent) == 1
        assert "next message" in sent[0].lower()
        assert "ULTRA_SECRET_TOKEN_999" not in " ".join(sent)

        handle_telegram_update(
            {
                "update_id": 910002,
                "message": {
                    "message_id": 2,
                    "text": "ULTRA_SECRET_TOKEN_999",
                    "chat": {"id": 12345, "type": "private"},
                    "from": {"id": 12345, "username": "t"},
                },
            },
            db=None,
        )

    assert len(sent) == 3
    assert "Received and saved securely. Continuing." in sent[1]
    body2 = sent[2].lower()
    assert "ULTRA_SECRET_TOKEN_999" not in sent[1] and "ULTRA_SECRET_TOKEN_999" not in sent[2]
    assert "marketing" in body2 or "review" in body2 or "run " in body2

    content = (tmp_path / "runtime.env").read_text(encoding="utf-8")
    assert "ULTRA_SECRET_TOKEN_999" in content
