"""
Tests for Telegram alert origin gatekeeper

These tests verify that:
- AWS origin sends alerts to Telegram with [AWS] prefix
- TEST origin sends alerts to Telegram with [TEST] prefix
- LOCAL origin blocks alerts and logs instead
- Origin parameter is properly passed through the call chain
"""
import pytest
from unittest.mock import patch, MagicMock, call
from app.services.telegram_notifier import TelegramNotifier


class TestTelegramAlertsOrigin:
    """Test origin-based alert blocking"""
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_aws_origin_sends_telegram_message(self, mock_get_origin, mock_post):
        """AWS origin should send message to Telegram"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_message("Test message", origin="AWS")
        
        # Verify
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]['json']['text'] == "[AWS] Test message"
        assert call_args[1]['json']['chat_id'] == "test_chat_id"
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_local_origin_does_not_send_telegram_message(self, mock_get_origin, mock_post):
        """LOCAL origin should NOT send message to Telegram, only log"""
        # Setup
        mock_get_origin.return_value = "LOCAL"
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        with patch('app.services.telegram_notifier.logger') as mock_logger:
            result = notifier.send_message("Test message", origin="LOCAL")
        
        # Verify
        assert result is False
        mock_post.assert_not_called()  # Should NOT call Telegram API
        mock_logger.info.assert_called()
        # Check that log contains the expected message
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("[TG_LOCAL_DEBUG]" in str(call) for call in log_calls)
        assert any("non-AWS/non-TEST origin" in str(call) or "non-AWS origin" in str(call) for call in log_calls)
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_send_buy_signal_with_aws_origin(self, mock_get_origin, mock_post):
        """send_buy_signal with AWS origin should send to Telegram"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="RSI < 40",
            origin="AWS"
        )
        
        # Verify
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "[AWS]" in call_args[1]['json']['text']
        assert "BTC_USDT" in call_args[1]['json']['text']
        assert "BUY SIGNAL" in call_args[1]['json']['text']
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_send_buy_signal_with_local_origin(self, mock_get_origin, mock_post):
        """send_buy_signal with LOCAL origin should NOT send to Telegram"""
        # Setup
        mock_get_origin.return_value = "LOCAL"
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        with patch('app.services.telegram_notifier.logger') as mock_logger:
            result = notifier.send_buy_signal(
                symbol="BTC_USDT",
                price=50000.0,
                reason="RSI < 40",
                origin="LOCAL"
            )
        
        # Verify
        assert result is False
        mock_post.assert_not_called()
        mock_logger.info.assert_called()
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("[TG_LOCAL_DEBUG]" in str(call) for call in log_calls)
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_send_sell_signal_with_aws_origin(self, mock_get_origin, mock_post):
        """send_sell_signal with AWS origin should send to Telegram"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="RSI > 70",
            origin="AWS"
        )
        
        # Verify
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "[AWS]" in call_args[1]['json']['text']
        assert "ETH_USDT" in call_args[1]['json']['text']
        assert "SELL SIGNAL" in call_args[1]['json']['text']
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_send_sell_signal_with_local_origin(self, mock_get_origin, mock_post):
        """send_sell_signal with LOCAL origin should NOT send to Telegram"""
        # Setup
        mock_get_origin.return_value = "LOCAL"
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        with patch('app.services.telegram_notifier.logger') as mock_logger:
            result = notifier.send_sell_signal(
                symbol="ETH_USDT",
                price=3000.0,
                reason="RSI > 70",
                origin="LOCAL"
            )
        
        # Verify
        assert result is False
        mock_post.assert_not_called()
        mock_logger.info.assert_called()
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("[TG_LOCAL_DEBUG]" in str(call) for call in log_calls)
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_default_origin_falls_back_to_runtime(self, mock_get_origin, mock_post):
        """If origin not provided, should use runtime origin"""
        # Setup
        mock_get_origin.return_value = "LOCAL"  # Runtime is LOCAL
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute (no origin parameter)
        with patch('app.services.telegram_notifier.logger') as mock_logger:
            result = notifier.send_message("Test message")  # No origin parameter
        
        # Verify
        assert result is False  # LOCAL runtime blocks
        mock_post.assert_not_called()
        mock_get_origin.assert_called()  # Should check runtime origin
        mock_logger.info.assert_called()
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_debug_origin_blocks_telegram(self, mock_get_origin, mock_post):
        """DEBUG origin should also block Telegram sends"""
        # Setup
        mock_get_origin.return_value = "AWS"
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        with patch('app.services.telegram_notifier.logger') as mock_logger:
            result = notifier.send_message("Test message", origin="DEBUG")
        
        # Verify
        assert result is False
        mock_post.assert_not_called()
        mock_logger.info.assert_called()
        log_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("non-AWS/non-TEST origin" in str(call) or "non-AWS origin" in str(call) for call in log_calls)
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_test_origin_sends_telegram_message(self, mock_get_origin, mock_post):
        """TEST origin should send message to Telegram with [TEST] prefix"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_message("Test alert message", origin="TEST")
        
        # Verify
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[1]['json']['text'] == "[TEST] Test alert message"
        assert call_args[1]['json']['chat_id'] == "test_chat_id"
    
    @patch('app.api.routes_monitoring.add_telegram_message')
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_test_origin_recorded_in_monitoring(self, mock_get_origin, mock_post, mock_add_message):
        """TEST origin messages should be recorded in monitoring with blocked=False"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_message("Test alert for BTC_USDT", origin="TEST")
        
        # Verify
        assert result is True
        # Verify add_telegram_message was called with blocked=False and [TEST] prefix
        mock_add_message.assert_called_once()
        call_args = mock_add_message.call_args
        assert "[TEST]" in call_args[0][0]  # Message contains [TEST] prefix
        assert call_args[1]['blocked'] is False  # Not blocked
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_test_origin_flows_through_to_send_message(self, mock_get_origin, mock_post):
        """TEST origin flows from send_buy_signal through to send_message"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"message_id": 123}}
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute - send_buy_signal with origin=TEST
        result = notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="Test reason",
            origin="TEST"
        )
        
        # Verify
        assert result is True
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        # Verify message starts with [TEST] prefix
        sent_message = call_args[1]['json']['text']
        assert sent_message.startswith("[TEST]")
        assert "BUY SIGNAL" in sent_message
        assert "BTC_USDT" in sent_message
    
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_test_origin_allows_telegram_send(self, mock_get_origin, mock_post):
        """TEST origin allows Telegram send (not blocked by gatekeeper)"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"message_id": 456}}
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_message("Test message", origin="TEST")
        
        # Verify
        assert result is True
        mock_post.assert_called_once()  # Should call Telegram API
        call_args = mock_post.call_args
        assert call_args[1]['json']['text'] == "[TEST] Test message"
    
    @patch('app.api.routes_monitoring.add_telegram_message')
    @patch('app.services.telegram_notifier.requests.post')
    @patch('app.services.telegram_notifier.get_runtime_origin')
    def test_test_origin_saved_in_monitoring(self, mock_get_origin, mock_post, mock_add_message):
        """TEST origin messages saved in monitoring with blocked=False"""
        # Setup
        mock_get_origin.return_value = "AWS"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"message_id": 789}}
        mock_post.return_value = mock_response
        
        notifier = TelegramNotifier()
        notifier.enabled = True
        notifier.bot_token = "test_token"
        notifier.chat_id = "test_chat_id"
        
        # Execute
        result = notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="Test SELL",
            origin="TEST"
        )
        
        # Verify
        assert result is True
        # Verify add_telegram_message was called with blocked=False
        mock_add_message.assert_called()
        # Find the call with [TEST] prefix
        test_call = None
        for call in mock_add_message.call_args_list:
            if "[TEST]" in str(call):
                test_call = call
                break
        assert test_call is not None, "add_telegram_message should be called with [TEST] message"
        # Verify blocked=False
        call_kwargs = test_call[1] if len(test_call) > 1 else {}
        assert call_kwargs.get('blocked', True) is False, "TEST alerts should have blocked=False"

