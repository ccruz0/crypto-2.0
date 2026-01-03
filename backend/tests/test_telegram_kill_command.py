"""Tests for Telegram /kill command"""
import os
import pytest
from unittest.mock import patch, MagicMock, call
from sqlalchemy.orm import Session

from app.services.telegram_commands import handle_kill_command, _is_authorized
from app.models.trading_settings import TradingSettings


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def mock_trading_settings():
    """Mock TradingSettings object"""
    setting = MagicMock(spec=TradingSettings)
    setting.setting_key = "TRADING_KILL_SWITCH"
    setting.setting_value = "false"
    return setting


class TestKillCommandOn:
    """Test /kill on command"""
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.services.telegram_commands.logger')
    def test_kill_on_sets_setting_to_true(self, mock_logger, mock_send_response, mock_db, mock_trading_settings):
        """Test that /kill on sets TRADING_KILL_SWITCH to true"""
        mock_send_response.return_value = True  # Mock return value
        # Mock query to return existing setting
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_trading_settings
        mock_db.query.return_value = mock_query
        mock_db.rollback.return_value = None
        mock_db.commit.return_value = None
        
        result = handle_kill_command("12345", "/kill on", db=mock_db)
        
        # Verify setting was updated
        assert mock_trading_settings.setting_value == "true"
        mock_db.commit.assert_called_once()
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        assert call_args[0] == "12345"  # chat_id
        assert "KILL SWITCH ACTIVATED" in call_args[1]
        assert "ALL TRADING DISABLED" in call_args[1]
        
        assert result is True
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.models.trading_settings.TradingSettings')
    @patch('app.services.telegram_commands.logger')
    def test_kill_on_creates_setting_if_not_exists(self, mock_logger, mock_trading_settings_class, mock_send_response, mock_db):
        """Test that /kill on creates setting if it doesn't exist"""
        mock_send_response.return_value = True  # Mock return value
        # Mock query to return None (setting doesn't exist)
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        mock_db.rollback.return_value = None
        mock_db.commit.return_value = None
        mock_db.add = MagicMock()
        
        # Mock TradingSettings constructor
        new_setting = MagicMock()
        mock_trading_settings_class.return_value = new_setting
        
        result = handle_kill_command("12345", "/kill on", db=mock_db)
        
        # Verify new setting was created and added
        mock_trading_settings_class.assert_called_once_with(
            setting_key="TRADING_KILL_SWITCH",
            setting_value="true",
            description="Global Telegram kill switch to disable all trading"
        )
        mock_db.add.assert_called_once_with(new_setting)
        mock_db.commit.assert_called_once()
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        assert result is True


class TestKillCommandOff:
    """Test /kill off command"""
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.services.telegram_commands.logger')
    def test_kill_off_sets_setting_to_false(self, mock_logger, mock_send_response, mock_db, mock_trading_settings):
        """Test that /kill off sets TRADING_KILL_SWITCH to false"""
        mock_send_response.return_value = True  # Mock return value
        # Mock query to return existing setting
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_trading_settings
        mock_db.query.return_value = mock_query
        mock_db.rollback.return_value = None
        mock_db.commit.return_value = None
        
        result = handle_kill_command("12345", "/kill off", db=mock_db)
        
        # Verify setting was updated
        assert mock_trading_settings.setting_value == "false"
        mock_db.commit.assert_called_once()
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        assert call_args[0] == "12345"  # chat_id
        assert "KILL SWITCH DEACTIVATED" in call_args[1]
        assert "Trading is now allowed" in call_args[1]
        
        assert result is True
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.services.telegram_commands.logger')
    def test_kill_off_handles_missing_setting(self, mock_logger, mock_send_response, mock_db):
        """Test that /kill off handles case where setting doesn't exist (already OFF)"""
        mock_send_response.return_value = True  # Mock return value
        # Mock query to return None (setting doesn't exist)
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        mock_db.rollback.return_value = None
        
        result = handle_kill_command("12345", "/kill off", db=mock_db)
        
        # Should not commit (setting doesn't exist, which means it's already OFF)
        mock_db.commit.assert_not_called()
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        assert result is True


class TestKillCommandStatus:
    """Test /kill status command"""
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.live_trading.get_live_trading_status')
    def test_kill_status_shows_current_state(self, mock_get_live, mock_get_kill, mock_send_response, mock_db):
        """Test that /kill status shows current state"""
        mock_send_response.return_value = True  # Mock return value
        mock_get_live.return_value = True
        mock_get_kill.return_value = False
        
        result = handle_kill_command("12345", "/kill status", db=mock_db)
        
        # Verify functions were called
        mock_get_live.assert_called_once_with(mock_db)
        mock_get_kill.assert_called_once_with(mock_db)
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        assert call_args[0] == "12345"  # chat_id
        message = call_args[1]
        assert "TRADING STATUS" in message
        assert "Live Toggle" in message
        assert "Kill Switch" in message
        
        assert result is True
    
    @patch('app.services.telegram_commands.send_command_response')
    @patch('app.utils.trading_guardrails._get_telegram_kill_switch_status')
    @patch('app.utils.live_trading.get_live_trading_status')
    def test_kill_status_shows_disabled_when_kill_on(self, mock_get_live, mock_get_kill, mock_send_response, mock_db):
        """Test that /kill status shows disabled when kill switch is ON"""
        mock_send_response.return_value = True  # Mock return value
        mock_get_live.return_value = True
        mock_get_kill.return_value = True  # Kill switch ON
        
        result = handle_kill_command("12345", "/kill status", db=mock_db)
        
        # Verify response was sent
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        message = call_args[1]
        assert "TRADING IS DISABLED" in message
        assert "Kill switch is ON" in message
        
        assert result is True


class TestKillCommandInvalid:
    """Test /kill command with invalid arguments"""
    
    @patch('app.services.telegram_commands.send_command_response')
    def test_kill_invalid_action_shows_usage(self, mock_send_response, mock_db):
        """Test that invalid /kill action shows usage"""
        mock_send_response.return_value = True  # Mock return value
        result = handle_kill_command("12345", "/kill invalid", db=mock_db)
        
        # Verify response was sent with usage
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        message = call_args[1]
        assert "Invalid /kill command" in message
        assert "/kill on" in message
        assert "/kill off" in message
        assert "/kill status" in message
        
        assert result is True


class TestKillCommandNoDb:
    """Test /kill command without database"""
    
    @patch('app.services.telegram_commands.send_command_response')
    def test_kill_no_db_returns_error(self, mock_send_response):
        """Test that /kill command returns error if database is not available"""
        mock_send_response.return_value = False  # Mock return value (error case)
        result = handle_kill_command("12345", "/kill on", db=None)
        
        # Verify error response was sent
        mock_send_response.assert_called_once()
        call_args = mock_send_response.call_args[0]
        assert "Database not available" in call_args[1]
        
        assert result is False
