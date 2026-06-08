"""
Tests for Telegram alert origin gatekeeper

These tests verify that:
- AWS origin sends alerts to Telegram when refresh_config allows
- TEST origin sends alerts to Telegram when refresh_config allows
- LOCAL/DEBUG origins do not send when refresh_config blocks
- Origin parameter is properly passed through the call chain
"""
import pytest
from unittest.mock import patch, MagicMock
from app.services.telegram_notifier import TelegramNotifier


def _enabled_config(runtime_env: str = "aws") -> dict:
    return {
        "enabled": True,
        "runtime_env": runtime_env,
        "run_telegram": True,
        "kill_switch_enabled": True,
        "token_set": True,
        "chat_id_set": True,
        "block_reasons": [],
    }


def _disabled_config(runtime_env: str = "local") -> dict:
    return {
        "enabled": False,
        "runtime_env": runtime_env,
        "run_telegram": False,
        "kill_switch_enabled": False,
        "token_set": False,
        "chat_id_set": False,
        "block_reasons": ["run_telegram_disabled"],
    }


def _http_success_response() -> MagicMock:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "ok"
    mock_response.json.return_value = {"result": {"message_id": 123}}
    mock_response.raise_for_status = MagicMock()
    return mock_response


def _ready_notifier() -> TelegramNotifier:
    notifier = TelegramNotifier()
    notifier.bot_token = "test_token"
    notifier.chat_id = "test_chat_id"
    notifier._chat_id_trading = "test_chat_id"
    notifier.enabled = True
    return notifier


class TestTelegramAlertsOrigin:
    """Test origin-based alert blocking via refresh_config guard."""

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_aws_origin_sends_telegram_message(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """AWS origin should send message to Telegram when guard allows."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_message("Test message", origin="AWS")

        assert result is True
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "Test message" in sent_text
        assert "source=AWS" in sent_text
        assert mock_post.call_args[1]["json"]["chat_id"] == "test_chat_id"

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_local_origin_does_not_send_telegram_message(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """LOCAL origin should NOT send when refresh_config blocks."""
        mock_refresh.return_value = _disabled_config("local")
        mock_get_origin.return_value = "LOCAL"

        notifier = _ready_notifier()
        result = notifier.send_message("Test message", origin="LOCAL")

        assert result is False
        mock_post.assert_not_called()

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_send_buy_signal_with_aws_origin(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """send_buy_signal with AWS origin should send to Telegram."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="RSI < 40",
            origin="AWS",
        )

        assert result is True or (isinstance(result, dict) and result.get("sent") is True)
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "BTC_USDT" in sent_text
        assert "BUY SIGNAL" in sent_text
        assert "source=AWS" in sent_text

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_send_buy_signal_with_local_origin(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """send_buy_signal with LOCAL origin should NOT send when guard blocks."""
        mock_refresh.return_value = _disabled_config("local")
        mock_get_origin.return_value = "LOCAL"

        notifier = _ready_notifier()
        result = notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="RSI < 40",
            origin="LOCAL",
        )

        assert result is False
        mock_post.assert_not_called()

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_send_sell_signal_with_aws_origin(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """send_sell_signal with AWS origin should send to Telegram."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="RSI > 70",
            origin="AWS",
        )

        assert result is True or (isinstance(result, dict) and result.get("sent") is True)
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "ETH_USDT" in sent_text
        assert "SELL SIGNAL" in sent_text
        assert "source=AWS" in sent_text

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_send_sell_signal_with_local_origin(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """send_sell_signal with LOCAL origin should NOT send when guard blocks."""
        mock_refresh.return_value = _disabled_config("local")
        mock_get_origin.return_value = "LOCAL"

        notifier = _ready_notifier()
        result = notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="RSI > 70",
            origin="LOCAL",
        )

        assert result is False
        mock_post.assert_not_called()

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_default_origin_falls_back_to_runtime(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """If origin not provided, should use runtime origin and respect guard."""
        mock_refresh.return_value = _disabled_config("local")
        mock_get_origin.return_value = "LOCAL"

        notifier = _ready_notifier()
        result = notifier.send_message("Test message")

        assert result is False
        mock_post.assert_not_called()

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_debug_origin_blocks_telegram(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """DEBUG origin should not send when refresh_config blocks."""
        mock_refresh.return_value = _disabled_config("local")
        mock_get_origin.return_value = "AWS"

        notifier = _ready_notifier()
        result = notifier.send_message("Test message", origin="DEBUG")

        assert result is False
        mock_post.assert_not_called()

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_test_origin_sends_telegram_message(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """TEST origin should send message to Telegram when guard allows."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_message("Test alert message", origin="TEST")

        assert result is True
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "Test alert message" in sent_text
        assert "source=TEST" in sent_text
        assert mock_post.call_args[1]["json"]["chat_id"] == "test_chat_id"

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_test_origin_recorded_in_monitoring(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """TEST origin messages should be recorded in monitoring with blocked=False."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_message("Test alert for BTC_USDT", origin="TEST")

        assert result is True
        mock_add_message.assert_called()
        success_calls = [
            c for c in mock_add_message.call_args_list if c[1].get("blocked") is False
        ]
        assert success_calls, "Expected at least one non-blocked monitoring record"
        assert "source=TEST" in success_calls[-1][0][0]

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_test_origin_flows_through_to_send_message(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """TEST origin flows from send_buy_signal through to send_message."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="Test reason",
            origin="TEST",
        )

        assert result is True or (isinstance(result, dict) and result.get("sent") is True)
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "source=TEST" in sent_text
        assert "BUY SIGNAL" in sent_text
        assert "BTC_USDT" in sent_text

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_test_origin_allows_telegram_send(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """TEST origin allows Telegram send when guard is enabled."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_message("Test message", origin="TEST")

        assert result is True
        mock_post.assert_called_once()
        sent_text = mock_post.call_args[1]["json"]["text"]
        assert "Test message" in sent_text
        assert "source=TEST" in sent_text

    @patch("app.api.routes_monitoring.add_telegram_message")
    @patch("app.services.telegram_notifier.http_post")
    @patch("app.services.telegram_notifier.get_runtime_origin")
    @patch.object(TelegramNotifier, "refresh_config")
    def test_test_origin_saved_in_monitoring(
        self, mock_refresh, mock_get_origin, mock_post, mock_add_message
    ):
        """TEST origin messages saved in monitoring with blocked=False."""
        mock_refresh.return_value = _enabled_config("aws")
        mock_get_origin.return_value = "AWS"
        mock_post.return_value = _http_success_response()

        notifier = _ready_notifier()
        result = notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="Test SELL",
            origin="TEST",
        )

        assert result is True or (isinstance(result, dict) and result.get("sent") is True)
        mock_post.assert_called_once()
        success_calls = [
            c for c in mock_add_message.call_args_list if c[1].get("blocked") is False
        ]
        assert success_calls
