"""
Unit tests for Telegram environment prefix functionality.

Tests verify that:
1. APP_ENV=aws adds [AWS] prefix to messages
2. APP_ENV=local adds [LOCAL] prefix to messages
3. Missing APP_ENV defaults to [LOCAL] with warning
4. All alert methods route through send_message() which adds the prefix
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.telegram_notifier import TelegramNotifier, get_app_env, AppEnv
from app.core.config import Settings


class TestAppEnvHelper:
    """Tests for get_app_env() helper function"""
    
    def test_get_app_env_aws(self):
        """Test that APP_ENV=aws returns AppEnv.AWS"""
        with patch.dict(os.environ, {'APP_ENV': 'aws'}):
            # Reload settings to pick up new env var
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.AWS
    
    def test_get_app_env_local(self):
        """Test that APP_ENV=local returns AppEnv.LOCAL"""
        with patch.dict(os.environ, {'APP_ENV': 'local'}):
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.LOCAL
    
    def test_get_app_env_defaults_to_local(self):
        """Test that missing APP_ENV defaults to AppEnv.LOCAL"""
        # Remove APP_ENV if it exists
        env_backup = os.environ.pop('APP_ENV', None)
        try:
            from importlib import reload
            from app import core
            reload(core.config)
            env = get_app_env()
            assert env == AppEnv.LOCAL
        finally:
            # Restore original value
            if env_backup:
                os.environ['APP_ENV'] = env_backup


class TestTelegramNotifierEnvPrefix:
    """Tests for TelegramNotifier environment prefix in send_message()"""
    
    @pytest.fixture
    def mock_requests(self):
        """Mock requests.post for Telegram API calls"""
        with patch('app.services.telegram_notifier.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.raise_for_status = Mock()
            mock_post.return_value = mock_response
            yield mock_post
    
    @pytest.fixture
    def telegram_notifier_aws(self, mock_requests):
        """Create TelegramNotifier instance with APP_ENV=aws"""
        with patch.dict(os.environ, {
            'APP_ENV': 'aws',
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id'
        }):
            from importlib import reload
            from app import core
            reload(core.config)
            notifier = TelegramNotifier()
            yield notifier
    
    @pytest.fixture
    def telegram_notifier_local(self, mock_requests):
        """Create TelegramNotifier instance with APP_ENV=local"""
        with patch.dict(os.environ, {
            'APP_ENV': 'local',
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': 'test_chat_id'
        }):
            from importlib import reload
            from app import core
            reload(core.config)
            notifier = TelegramNotifier()
            yield notifier
    
    def test_send_message_adds_aws_prefix(self, telegram_notifier_aws, mock_requests):
        """Test that send_message() adds [AWS] prefix when APP_ENV=aws"""
        message = "Test alert message"
        telegram_notifier_aws.send_message(message)
        
        # Verify request was made
        assert mock_requests.called
        
        # Get the payload sent
        call_args = mock_requests.call_args
        payload = call_args[1]['json']  # kwargs['json']
        sent_message = payload['text']
        
        # Verify prefix was added
        assert sent_message.startswith("[AWS]")
        assert "[AWS] Test alert message" in sent_message
    
    def test_send_message_adds_local_prefix(self, telegram_notifier_local, mock_requests):
        """Test that send_message() adds [LOCAL] prefix when APP_ENV=local"""
        message = "Test alert message"
        telegram_notifier_local.send_message(message)
        
        # Verify request was made
        assert mock_requests.called
        
        # Get the payload sent
        call_args = mock_requests.call_args
        payload = call_args[1]['json']
        sent_message = payload['text']
        
        # Verify prefix was added
        assert sent_message.startswith("[LOCAL]")
        assert "[LOCAL] Test alert message" in sent_message
    
    def test_send_message_does_not_duplicate_prefix(self, telegram_notifier_aws, mock_requests):
        """Test that send_message() doesn't add prefix if message already has one"""
        message = "[AWS] Pre-prefixed message"
        telegram_notifier_aws.send_message(message)
        
        # Get the payload sent
        call_args = mock_requests.call_args
        payload = call_args[1]['json']
        sent_message = payload['text']
        
        # Verify prefix was not duplicated
        assert sent_message == "[AWS] Pre-prefixed message"
        assert sent_message.count("[AWS]") == 1
    
    def test_send_buy_signal_includes_prefix(self, telegram_notifier_aws, mock_requests):
        """Test that send_buy_signal() routes through send_message() and includes prefix"""
        # Mock database query to return a watchlist item with alert_enabled=True
        with patch('app.services.telegram_notifier.SessionLocal') as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            
            mock_watchlist_item = Mock()
            mock_watchlist_item.symbol = "BTC_USDT"
            mock_watchlist_item.alert_enabled = True
            
            mock_query = MagicMock()
            mock_query.filter.return_value.first.return_value = mock_watchlist_item
            mock_db.query.return_value = mock_query
            
            telegram_notifier_aws.send_buy_signal(
                symbol="BTC_USDT",
                price=50000.0,
                reason="RSI=30",
                strategy_type="Swing",
                risk_approach="Conservative",
                price_variation="+1.23%",
            )
            
            # Verify request was made
            assert mock_requests.called
            
            # Get the payload sent
            call_args = mock_requests.call_args
            payload = call_args[1]['json']
            sent_message = payload['text']
            
            # Verify prefix was added
            assert sent_message.startswith("[AWS]")
            assert "BUY SIGNAL DETECTED" in sent_message
            assert "🎯 Strategy: <b>Swing</b>" in sent_message
            assert "⚖️ Approach: <b>Conservative</b>" in sent_message
            assert "(+1.23%)" in sent_message

