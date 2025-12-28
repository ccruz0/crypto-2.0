"""
Tests for Telegram /start command and related functionality
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import os

# Test /start command parsing with @botname
def test_start_command_with_botname():
    """Test that /start@BotName is parsed correctly to /start"""
    text = "/start@Hilovivolocal_bot"
    
    # Simulate the parsing logic from handle_telegram_message
    if "@" in text and text.startswith("/"):
        text = text.split("@")[0].strip()
    
    assert text == "/start"
    assert text.startswith("/start")

def test_start_command_without_botname():
    """Test that /start without @botname works"""
    text = "/start"
    
    assert text.startswith("/start")
    assert text == "/start"

def test_start_command_parsing_in_groups():
    """Test that /start@BotName in groups is handled correctly"""
    # Simulate group command format
    commands = [
        "/start@Hilovivolocal_bot",
        "/start@SomeOtherBot",
        "/start",
    ]
    
    for cmd in commands:
        if "@" in cmd and cmd.startswith("/"):
            parsed = cmd.split("@")[0].strip()
        else:
            parsed = cmd.strip()
        
        assert parsed == "/start" or parsed.startswith("/start")

# Test authorization in groups
def test_authorization_in_group():
    """Test that authorization works in groups using user_id"""
    from app.services.telegram_commands import _is_authorized, AUTH_CHAT_ID, AUTHORIZED_USER_IDS
    
    # Simulate group message
    chat_id = "-1001234567890"  # Group chat ID (negative)
    user_id = "123456789"  # User ID (positive)
    
    # Mock the authorization setup
    with patch('app.services.telegram_commands.AUTH_CHAT_ID', None), \
         patch('app.services.telegram_commands.AUTHORIZED_USER_IDS', {'123456789'}):
        # In groups, user_id should match AUTHORIZED_USER_IDS
        is_authorized = _is_authorized(chat_id, user_id)
        assert is_authorized == True

def test_authorization_in_private_chat():
    """Test that authorization works in private chats using chat_id"""
    from app.services.telegram_commands import _is_authorized
    
    # Simulate private chat
    chat_id = "123456789"  # Private chat ID (same as user_id)
    user_id = "123456789"
    
    # Mock the authorization setup
    with patch('app.services.telegram_commands.AUTH_CHAT_ID', None), \
         patch('app.services.telegram_commands.AUTHORIZED_USER_IDS', {'123456789'}):
        # In private chats, chat_id should match AUTHORIZED_USER_IDS
        is_authorized = _is_authorized(chat_id, user_id)
        assert is_authorized == True

def test_authorization_denied():
    """Test that unauthorized users are denied"""
    from app.services.telegram_commands import _is_authorized
    
    chat_id = "999999999"
    user_id = "999999999"
    
    # Mock the authorization setup
    with patch('app.services.telegram_commands.AUTH_CHAT_ID', None), \
         patch('app.services.telegram_commands.AUTHORIZED_USER_IDS', {'123456789'}):
        # Unauthorized user should be denied
        is_authorized = _is_authorized(chat_id, user_id)
        assert is_authorized == False

def test_authorization_with_channel_id():
    """Test that channel ID authorization works"""
    from app.services.telegram_commands import _is_authorized
    
    # Simulate channel interaction
    chat_id = "-1001234567890"  # Channel ID
    user_id = "123456789"
    
    # Mock: channel ID matches AUTH_CHAT_ID
    with patch('app.services.telegram_commands.AUTH_CHAT_ID', '-1001234567890'), \
         patch('app.services.telegram_commands.AUTHORIZED_USER_IDS', set()):
        is_authorized = _is_authorized(chat_id, user_id)
        assert is_authorized == True

# Test webhook deletion
def test_webhook_deletion_on_startup():
    """Test that webhook deletion is called on startup"""
    with patch('requests.get') as mock_get, \
         patch('requests.post') as mock_post:
        
        # Mock getWebhookInfo response with webhook
        mock_webhook_response = Mock()
        mock_webhook_response.json.return_value = {
            "ok": True,
            "result": {
                "url": "https://example.com/webhook",
                "pending_update_count": 0
            }
        }
        mock_webhook_response.raise_for_status = Mock()
        
        # Mock deleteWebhook response
        mock_delete_response = Mock()
        mock_delete_response.json.return_value = {"ok": True}
        mock_delete_response.raise_for_status = Mock()
        
        mock_get.return_value = mock_webhook_response
        mock_post.return_value = mock_delete_response
        
        # Import and call diagnostics (simulating startup)
        from app.services.telegram_commands import _run_startup_diagnostics
        
        # Set up environment
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': '123456789'
        }):
            with patch('app.services.telegram_commands.TELEGRAM_ENABLED', True), \
                 patch('app.services.telegram_commands.BOT_TOKEN', 'test_token'):
                _run_startup_diagnostics()
        
        # Verify deleteWebhook was called
        assert mock_post.called
        delete_call = [call for call in mock_post.call_args_list 
                      if 'deleteWebhook' in str(call)]
        assert len(delete_call) > 0

def test_webhook_not_deleted_if_none():
    """Test that deleteWebhook is not called if no webhook exists"""
    with patch('requests.get') as mock_get, \
         patch('requests.post') as mock_post:
        
        # Mock getWebhookInfo response without webhook
        mock_webhook_response = Mock()
        mock_webhook_response.json.return_value = {
            "ok": True,
            "result": {
                "url": "",  # No webhook
                "pending_update_count": 0
            }
        }
        mock_webhook_response.raise_for_status = Mock()
        
        mock_get.return_value = mock_webhook_response
        
        # Import and call diagnostics
        from app.services.telegram_commands import _run_startup_diagnostics
        
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': '123456789'
        }):
            with patch('app.services.telegram_commands.TELEGRAM_ENABLED', True), \
                 patch('app.services.telegram_commands.BOT_TOKEN', 'test_token'):
                _run_startup_diagnostics()
        
        # Verify deleteWebhook was NOT called
        delete_calls = [call for call in mock_post.call_args_list 
                       if 'deleteWebhook' in str(call)]
        assert len(delete_calls) == 0

# Test menu rendering
def test_welcome_message_has_keyboard():
    """Test that welcome message includes reply keyboard"""
    with patch('requests.post') as mock_post:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        from app.services.telegram_commands import send_welcome_message
from app.utils.http_client import http_get, http_post
        
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': 'test_token',
            'TELEGRAM_CHAT_ID': '123456789'
        }):
            with patch('app.services.telegram_commands.TELEGRAM_ENABLED', True), \
                 patch('app.services.telegram_commands.BOT_TOKEN', 'test_token'):
                result = send_welcome_message("123456789")
        
        assert result == True
        assert mock_post.called
        
        # Check that reply_markup (keyboard) was sent
        call_args = mock_post.call_args
        payload = call_args[1]['json']
        assert 'reply_markup' in payload
        assert 'keyboard' in payload['reply_markup']
        assert len(payload['reply_markup']['keyboard']) > 0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

