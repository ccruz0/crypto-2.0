"""Tests for Telegram health-check helper"""
import os
import pytest
from unittest.mock import patch, MagicMock
from app.services.telegram_health import check_telegram_health


def test_telegram_health_missing_vars(caplog):
    """Test health check with missing environment variables"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "true",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }, clear=False):
        with patch("app.services.telegram_health.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                RUN_TELEGRAM="true",
                TELEGRAM_BOT_TOKEN="",
                TELEGRAM_CHAT_ID="",
                APP_ENV="",
                ENVIRONMENT="",
            )
            
            result = check_telegram_health(origin="test")
            
            assert result["enabled"] is True
            assert result["token_present"] is False
            assert result["chat_id_present"] is False
            assert result["fully_configured"] is False
            assert result["origin"] == "test"
            
            # Check log was emitted
            assert "[TELEGRAM_HEALTH]" in caplog.text
            assert "NOT_FULLY_CONFIGURED" in caplog.text


def test_telegram_health_all_present(caplog):
    """Test health check with all variables present"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "true",
        "TELEGRAM_BOT_TOKEN": "test_token_123",
        "TELEGRAM_CHAT_ID": "test_chat_456",
        "APP_ENV": "aws",
    }, clear=False):
        with patch("app.services.telegram_health.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                RUN_TELEGRAM="true",
                TELEGRAM_BOT_TOKEN="test_token_123",
                TELEGRAM_CHAT_ID="test_chat_456",
                APP_ENV="aws",
                ENVIRONMENT="",
            )
            
            result = check_telegram_health(origin="test")
            
            assert result["enabled"] is True
            assert result["token_present"] is True
            assert result["chat_id_present"] is True
            assert result["fully_configured"] is True
            assert result["source"] == ".env.aws"
            assert result["origin"] == "test"
            
            # Check log was emitted
            assert "[TELEGRAM_HEALTH]" in caplog.text
            assert "fully_configured=True" in caplog.text


def test_telegram_health_disabled(caplog):
    """Test health check with RUN_TELEGRAM disabled"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "false",
        "TELEGRAM_BOT_TOKEN": "test_token_123",
        "TELEGRAM_CHAT_ID": "test_chat_456",
    }, clear=False):
        with patch("app.services.telegram_health.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                RUN_TELEGRAM="false",
                TELEGRAM_BOT_TOKEN="test_token_123",
                TELEGRAM_CHAT_ID="test_chat_456",
                APP_ENV="",
                ENVIRONMENT="",
            )
            
            result = check_telegram_health(origin="test")
            
            assert result["enabled"] is False
            assert result["token_present"] is True
            assert result["chat_id_present"] is True
            assert result["fully_configured"] is False  # Disabled even if vars present
            assert result["source"] == "env"
            
            # Check log was emitted
            assert "[TELEGRAM_HEALTH]" in caplog.text


def test_telegram_health_source_detection():
    """Test that source is correctly detected as .env.aws or env"""
    with patch.dict(os.environ, {
        "APP_ENV": "aws",
    }, clear=False):
        with patch("app.services.telegram_health.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                RUN_TELEGRAM="true",
                TELEGRAM_BOT_TOKEN="",
                TELEGRAM_CHAT_ID="",
                APP_ENV="aws",
                ENVIRONMENT="",
            )
            
            result = check_telegram_health(origin="test")
            assert result["source"] == ".env.aws"
    
    with patch.dict(os.environ, {
        "APP_ENV": "local",
    }, clear=False):
        with patch("app.services.telegram_health.Settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                RUN_TELEGRAM="true",
                TELEGRAM_BOT_TOKEN="",
                TELEGRAM_CHAT_ID="",
                APP_ENV="local",
                ENVIRONMENT="",
            )
            
            result = check_telegram_health(origin="test")
            assert result["source"] == "env"








