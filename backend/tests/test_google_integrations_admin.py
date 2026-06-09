"""Tests for Jarvis Google integrations admin endpoints in routes_admin."""

from __future__ import annotations

import io
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.api.routes_admin import router as admin_router

_ADMIN_KEY = "test-admin-key-1234567890"
_READINESS_KEYS = frozenset({"success", "overall_status", "next_action", "items"})


@pytest.fixture
def app():
    application = FastAPI()
    application.include_router(admin_router, prefix="/api")
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def mock_admin_key():
    with patch.dict(os.environ, {"ADMIN_ACTIONS_KEY": _ADMIN_KEY}):
        yield _ADMIN_KEY


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/integrations/google/settings", "get"),
        ("/api/integrations/google/status", "get"),
        ("/api/integrations/google/readiness", "get"),
        ("/api/integrations/google/readiness/message", "get"),
    ],
)
def test_google_endpoints_require_admin_key(client, mock_admin_key, path, method):
    response = client.request(method, path)
    assert response.status_code == 401
    assert "unauthorized" in response.json()["detail"].lower()

    response = client.request(
        method,
        path,
        headers={"X-Admin-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_google_settings_returns_masked_developer_token(client, mock_admin_key):
    secret_token = "super-secret-developer-token-abcdef12"
    with patch.dict(
        os.environ,
        {
            "ADMIN_ACTIONS_KEY": _ADMIN_KEY,
            "JARVIS_GOOGLE_ADS_DEVELOPER_TOKEN": secret_token,
            "JARVIS_GOOGLE_ADS_CUSTOMER_ID": "1234567890",
        },
    ):
        response = client.get(
            "/api/integrations/google/settings",
            headers={"X-Admin-Key": _ADMIN_KEY},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    ads = body["settings"]["google_ads_developer_token"]
    assert ads["configured"] is True
    masked = ads["masked_value"]
    assert secret_token not in masked
    assert masked.startswith("********")
    assert masked.endswith("ef12")
    dumped = json.dumps(body)
    assert secret_token not in dumped


def test_google_readiness_payload_shape_is_stable(client, mock_admin_key):
    fake_status = {
        "success": False,
        "uploaded": False,
        "valid": False,
        "filename": None,
        "error": "Credentials JSON is missing",
        "env_key": "JARVIS_GA4_CREDENTIALS_JSON",
    }
    with patch("app.api.routes_admin._resolve_ga4_status", return_value=fake_status), patch(
        "app.api.routes_admin._resolve_gsc_status", return_value=fake_status
    ), patch("app.api.routes_admin._resolve_google_ads_status", return_value=fake_status):
        response = client.get(
            "/api/integrations/google/readiness",
            headers={"X-Admin-Key": _ADMIN_KEY},
        )

    assert response.status_code == 200
    payload = response.json()
    assert _READINESS_KEYS <= set(payload.keys())
    assert payload["success"] is True
    assert payload["overall_status"] in ("ready", "error", "incomplete")
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) == 3
    for item in payload["items"]:
        assert {"integration", "title", "status", "message"} <= set(item.keys())


def test_ga4_upload_rejects_non_json_file(client, mock_admin_key):
    response = client.post(
        "/api/upload/ga4-credentials",
        headers={"X-Admin-Key": _ADMIN_KEY},
        files={"ga4_credentials": ("credentials.txt", b"not-json", "text/plain")},
    )
    assert response.status_code == 400
    assert "json" in response.json()["detail"].lower()


def test_ga4_upload_rejects_malformed_json(client, mock_admin_key):
    response = client.post(
        "/api/upload/ga4-credentials",
        headers={"X-Admin-Key": _ADMIN_KEY},
        files={"ga4_credentials": ("credentials.json", b"{not valid", "application/json")},
    )
    assert response.status_code == 400
    assert "json" in response.json()["detail"].lower()


def test_ga4_upload_requires_admin_key(client, mock_admin_key):
    response = client.post(
        "/api/upload/ga4-credentials",
        files={"ga4_credentials": ("credentials.json", b"{}", "application/json")},
    )
    assert response.status_code == 401
