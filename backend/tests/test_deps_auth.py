"""Tests for app.deps.auth (x-api-key validation via ATP_API_KEY / INTERNAL_API_KEY)."""
import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.deps.auth import get_current_user


@pytest.fixture
def app():
    app = FastAPI()
    @app.get("/protected")
    def _protected(current_user=Depends(get_current_user)):
        return current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_demo_key_works_when_env_unset(client):
    """When ATP_API_KEY and INTERNAL_API_KEY are unset, demo-key is accepted."""
    with patch.dict(os.environ, {}, clear=False):
        for key in ("ATP_API_KEY", "INTERNAL_API_KEY"):
            os.environ.pop(key, None)
    r = client.get("/protected", headers={"x-api-key": "demo-key"})
    assert r.status_code == 200
    assert r.json() == {"user": "demo"}


def test_custom_key_required_when_atp_api_key_set(client):
    """When ATP_API_KEY is set, that value is required; demo-key is rejected."""
    with patch.dict(os.environ, {"ATP_API_KEY": "prod-secret-xyz"}):
        r_invalid = client.get("/protected", headers={"x-api-key": "demo-key"})
        r_valid = client.get("/protected", headers={"x-api-key": "prod-secret-xyz"})
    assert r_invalid.status_code == 401
    assert r_valid.status_code == 200


def test_missing_header_returns_401(client):
    """Missing x-api-key header returns 401."""
    r = client.get("/protected")
    assert r.status_code == 401
    assert "Invalid API key" in (r.json() or {}).get("detail", "")


def test_internal_api_key_fallback(client):
    """INTERNAL_API_KEY is used when ATP_API_KEY is not set."""
    with patch.dict(os.environ, {"ATP_API_KEY": "", "INTERNAL_API_KEY": "internal-key-123"}):
        r = client.get("/protected", headers={"x-api-key": "internal-key-123"})
    assert r.status_code == 200
