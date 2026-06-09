"""
Unit tests for Telegram environment prefix functionality.

Tests verify that:
1. APP_ENV=aws resolves to AppEnv.AWS
2. APP_ENV=local resolves to AppEnv.LOCAL
3. Missing APP_ENV defaults to AppEnv.LOCAL
4. send_message() tags outbound messages with source=AWS or source=LOCAL
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.telegram_notifier import TelegramNotifier, get_app_env, AppEnv


def _enabled_config(runtime_env: str) -> dict:
    return {
        "enabled": True,
        "runtime_env": runtime_env,
        "run_telegram": True,
        "kill_switch_enabled": True,
        "token_set": True,
        "chat_id_set": True,
        "block_reasons": [],
    }


def _http_success_response() -> MagicMock:
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "ok"
    mock_response.json.return_value = {"result": {"message_id": 1}}
    mock_response.raise_for_status = Mock()
    return mock_response


class TestAppEnvHelper:
    """Tests for get_app_env() helper function."""

    def test_get_app_env_aws(self):
        """Test that APP_ENV=aws returns AppEnv.AWS"""
        with patch.dict(os.environ, {"APP_ENV": "aws"}):
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.AWS

    def test_get_app_env_local(self):
        """Test that APP_ENV=local returns AppEnv.LOCAL"""
        with patch.dict(os.environ, {"APP_ENV": "local"}):
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.LOCAL

    def test_get_app_env_defaults_to_local(self):
        """Test that missing APP_ENV defaults to AppEnv.LOCAL"""
        env_backup = os.environ.pop("APP_ENV", None)
        try:
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.LOCAL
        finally:
            if env_backup:
                os.environ["APP_ENV"] = env_backup


class TestTelegramNotifierEnvPrefix:
    """Tests for TelegramNotifier source tagging in send_message()."""

    @pytest.fixture
    def mock_http_post(self):
        with patch("app.services.telegram_notifier.http_post") as mock_post:
            mock_post.return_value = _http_success_response()
            yield mock_post

    def test_send_message_adds_aws_source_tag(self, mock_http_post):
        """send_message() tags AWS sends with source=AWS when guard allows."""
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "aws",
                "TELEGRAM_BOT_TOKEN": "test_token",
                "TELEGRAM_CHAT_ID": "test_chat_id",
            },
        ), patch("app.api.routes_monitoring.add_telegram_message"), patch.object(
            TelegramNotifier, "refresh_config", return_value=_enabled_config("aws")
        ), patch(
            "app.services.telegram_notifier.get_runtime_origin", return_value="AWS"
        ):
            notifier = TelegramNotifier()
            notifier.bot_token = "test_token"
            notifier.chat_id = "test_chat_id"
            notifier._chat_id_trading = "test_chat_id"

            result = notifier.send_message("Test alert message", origin="AWS")

            assert result is True
            assert mock_http_post.called
            sent_text = mock_http_post.call_args[1]["json"]["text"]
            assert "source=AWS" in sent_text
            assert "Test alert message" in sent_text

    def test_send_message_adds_local_source_tag(self, mock_http_post):
        """send_message() tags LOCAL sends with source=LOCAL when guard allows."""
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "local",
                "TELEGRAM_BOT_TOKEN": "test_token",
                "TELEGRAM_CHAT_ID": "test_chat_id",
            },
        ), patch("app.api.routes_monitoring.add_telegram_message"), patch.object(
            TelegramNotifier, "refresh_config", return_value=_enabled_config("local")
        ), patch(
            "app.services.telegram_notifier.get_runtime_origin", return_value="LOCAL"
        ):
            notifier = TelegramNotifier()
            notifier.bot_token = "test_token"
            notifier.chat_id = "test_chat_id"
            notifier._chat_id_trading = "test_chat_id"

            result = notifier.send_message("Test alert message", origin="LOCAL")

            assert result is True
            assert mock_http_post.called
            sent_text = mock_http_post.call_args[1]["json"]["text"]
            assert "source=LOCAL" in sent_text
            assert "Test alert message" in sent_text

    def test_send_message_preserves_existing_source_tag(self, mock_http_post):
        """send_message() preserves an existing source footer in the message body."""
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "aws",
                "TELEGRAM_BOT_TOKEN": "test_token",
                "TELEGRAM_CHAT_ID": "test_chat_id",
            },
        ), patch("app.api.routes_monitoring.add_telegram_message"), patch.object(
            TelegramNotifier, "refresh_config", return_value=_enabled_config("aws")
        ), patch(
            "app.services.telegram_notifier.get_runtime_origin", return_value="AWS"
        ):
            notifier = TelegramNotifier()
            notifier.bot_token = "test_token"
            notifier.chat_id = "test_chat_id"
            notifier._chat_id_trading = "test_chat_id"

            message = "Test alert message\n\n— source=AWS host=test-host"
            result = notifier.send_message(message, origin="AWS")

            assert result is True
            sent_text = mock_http_post.call_args[1]["json"]["text"]
            assert "source=AWS host=test-host" in sent_text
            assert "Test alert message" in sent_text

    def test_send_buy_signal_includes_source_tag(self, mock_http_post):
        """send_buy_signal() routes through send_message() and includes source tag."""
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "aws",
                "TELEGRAM_BOT_TOKEN": "test_token",
                "TELEGRAM_CHAT_ID": "test_chat_id",
            },
        ), patch("app.api.routes_monitoring.add_telegram_message"), patch.object(
            TelegramNotifier, "refresh_config", return_value=_enabled_config("aws")
        ), patch(
            "app.services.telegram_notifier.get_runtime_origin", return_value="AWS"
        ):
            notifier = TelegramNotifier()
            notifier.bot_token = "test_token"
            notifier.chat_id = "test_chat_id"
            notifier._chat_id_trading = "test_chat_id"

            result = notifier.send_buy_signal(
                symbol="BTC_USDT",
                price=50000.0,
                reason="RSI=30",
                strategy_type="Swing",
                risk_approach="Conservative",
                price_variation="+1.23%",
                origin="AWS",
            )

            assert result is True or (isinstance(result, dict) and result.get("sent") is True)
            assert mock_http_post.called
            sent_text = mock_http_post.call_args[1]["json"]["text"]
            assert "source=AWS" in sent_text
            assert "BUY SIGNAL DETECTED" in sent_text
            assert "🎯 Strategy: <b>Swing</b>" in sent_text
            assert "⚖️ Approach: <b>Conservative</b>" in sent_text
            assert "+1.23%" in sent_text
