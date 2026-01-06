"""
Tests for admin-only API endpoints
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import the admin router
from app.api.routes_admin import router as admin_router


@pytest.fixture
def app():
    """Create test FastAPI app"""
    app = FastAPI()
    app.include_router(admin_router)
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_admin_key():
    """Mock admin key"""
    with patch.dict(os.environ, {"ADMIN_ACTIONS_KEY": "test-admin-key-123"}):
        yield "test-admin-key-123"


@pytest.fixture
def mock_telegram_notifier():
    """Mock telegram notifier"""
    with patch("app.api.routes_admin.telegram_notifier") as mock:
        mock.enabled = True
        mock.send_message.return_value = True
        yield mock


def test_test_telegram_missing_key(client, mock_admin_key):
    """Test that missing admin key returns 401"""
    response = client.post("/api/admin/test-telegram")
    assert response.status_code == 401
    assert "unauthorized" in response.json()["detail"].lower()


def test_test_telegram_wrong_key(client, mock_admin_key):
    """Test that wrong admin key returns 401"""
    response = client.post(
        "/api/admin/test-telegram",
        headers={"X-Admin-Key": "wrong-key"}
    )
    assert response.status_code == 401
    assert "unauthorized" in response.json()["detail"].lower()


def test_test_telegram_correct_key(client, mock_admin_key, mock_telegram_notifier):
    """Test that correct admin key sends test message"""
    response = client.post(
        "/api/admin/test-telegram",
        headers={"X-Admin-Key": "test-admin-key-123"}
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_telegram_notifier.send_message.assert_called_once()


def test_test_telegram_rate_limit(client, mock_admin_key, mock_telegram_notifier):
    """Test that rate limiting works (second call within 60s returns 429)"""
    # First call should succeed
    response1 = client.post(
        "/api/admin/test-telegram",
        headers={"X-Admin-Key": "test-admin-key-123"}
    )
    assert response1.status_code == 200
    assert response1.json()["ok"] is True

    # Second call immediately should be rate limited
    # Note: We need to mock the time to simulate cooldown
    with patch("app.api.routes_admin.time") as mock_time:
        mock_time.time.return_value = 0  # Same time as first call
        response2 = client.post(
            "/api/admin/test-telegram",
            headers={"X-Admin-Key": "test-admin-key-123"}
        )
        assert response2.status_code == 429
        assert "rate_limited" in response2.json()["detail"].lower()


def test_test_telegram_disabled(client, mock_admin_key):
    """Test that disabled Telegram returns ok: false"""
    with patch("app.api.routes_admin.telegram_notifier") as mock:
        mock.enabled = False
        response = client.post(
            "/api/admin/test-telegram",
            headers={"X-Admin-Key": "test-admin-key-123"}
        )
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["error"] == "telegram_disabled"


def test_market_updater_health_running():
    """Test market updater health returns PASS when data is fresh"""
    from app.services.system_health import _check_market_updater_health

    market_data = {
        "max_age_minutes": 2.5,
        "status": "PASS"
    }
    result = _check_market_updater_health(market_data, stale_threshold_minutes=30)

    assert result["status"] == "PASS"
    assert result["is_running"] is True
    assert result["last_heartbeat_age_minutes"] == 2.5


def test_market_updater_health_stopped():
    """Test market updater health returns FAIL when data is stale"""
    from app.services.system_health import _check_market_updater_health

    market_data = {
        "max_age_minutes": 45.0,
        "status": "FAIL"
    }
    result = _check_market_updater_health(market_data, stale_threshold_minutes=30)

    assert result["status"] == "FAIL"
    assert result["is_running"] is False
    assert result["last_heartbeat_age_minutes"] == 45.0


def test_market_updater_health_no_data():
    """Test market updater health returns FAIL when no data"""
    from app.services.system_health import _check_market_updater_health

    market_data = {
        "max_age_minutes": None,
        "status": "FAIL"
    }
    result = _check_market_updater_health(market_data, stale_threshold_minutes=30)

    assert result["status"] == "FAIL"
    assert result["is_running"] is False
    assert result["last_heartbeat_age_minutes"] is None




