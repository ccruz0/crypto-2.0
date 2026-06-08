"""Tests for Telegram health-check helper"""
import os
import pytest
from unittest.mock import patch
from app.services.telegram_health import check_telegram_health


def test_telegram_health_missing_vars(caplog):
    """Test health check with missing environment variables"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "true",
        "APP_ENV": "local",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "TELEGRAM_BOT_TOKEN_AWS": "",
        "TELEGRAM_CHAT_ID_AWS": "",
    }, clear=False):
        result = check_telegram_health(origin="test")
        assert result["enabled"] is False
        assert result["token_present"] is False
        assert result["chat_id_present"] is False
        assert result["fully_configured"] is False
        assert result["origin"] == "test"


def test_telegram_health_all_present(caplog):
    """Test health check with all variables present"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "true",
        "TELEGRAM_BOT_TOKEN": "test_token_123",
        "TELEGRAM_CHAT_ID": "test_chat_456",
        "APP_ENV": "aws",
    }, clear=False):
        result = check_telegram_health(origin="test")
        assert result["enabled"] is True
        assert result["token_present"] is True
        assert result["chat_id_present"] is True
        assert result["fully_configured"] is True
        assert result["source"] == ".env.aws"
        assert result["origin"] == "test"


def test_telegram_health_disabled(caplog):
    """Test health check with RUN_TELEGRAM disabled"""
    with patch.dict(os.environ, {
        "RUN_TELEGRAM": "false",
        "TELEGRAM_BOT_TOKEN": "test_token_123",
        "TELEGRAM_CHAT_ID": "test_chat_456",
    }, clear=False):
        result = check_telegram_health(origin="test")
        assert result["enabled"] is False
        assert result["token_present"] is True
        assert result["chat_id_present"] is True
        assert result["fully_configured"] is False  # Disabled even if vars present
        assert result["source"] == "env"


def test_telegram_health_source_detection():
    """Test that source is correctly detected as .env.aws or env"""
    with patch.dict(os.environ, {
        "APP_ENV": "aws",
    }, clear=False):
        result = check_telegram_health(origin="test")
        assert result["source"] == ".env.aws"
    
    with patch.dict(os.environ, {
        "APP_ENV": "local",
    }, clear=False):
        result = check_telegram_health(origin="test")
        assert result["source"] == "env"








