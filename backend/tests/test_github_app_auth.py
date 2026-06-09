"""Tests for github_app_auth (no real secrets)."""

import base64
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import github_app_auth as gaa


def _rsa_pem_b64() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(pem).decode("ascii")


def test_legacy_pat_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_LEGACY_GITHUB_PAT", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    assert gaa.github_api_token_configured() is True
    assert gaa.is_github_app_configured() is False


def test_app_credentials_without_valid_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_LEGACY_GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", "e30=")
    assert gaa.is_github_app_configured() is True
    assert gaa.github_api_token_configured() is False


def test_app_credentials_with_valid_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_LEGACY_GITHUB_PAT", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", _rsa_pem_b64())
    assert gaa.github_api_token_configured() is True


def test_diagnose_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    d = gaa.diagnose_github_app_config()
    assert d["github_app_id_present"] is False
    assert isinstance(d, dict)


def test_get_github_api_token_prefers_app_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    gaa._installation_token_cache = None
    monkeypatch.setenv("ALLOW_LEGACY_GITHUB_PAT", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_legacy")
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_B64", _rsa_pem_b64())

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "token": "ghs_installation_token",
        "expires_at": "2099-01-01T00:00:00Z",
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_resp

    with patch("app.services.github_app_auth.httpx.Client", return_value=mock_client):
        token, method = gaa.get_github_api_token()

    assert token == "ghs_installation_token"
    assert method == "github_app"


def test_get_github_api_token_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    gaa._installation_token_cache = None
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.setenv("ALLOW_LEGACY_GITHUB_PAT", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_legacy_only")

    token, method = gaa.get_github_api_token()
    assert token == "ghp_legacy_only"
    assert method == "legacy_pat"


def test_get_github_api_token_none_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    gaa._installation_token_cache = None
    for name in (
        "GITHUB_APP_ID",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_APP_PRIVATE_KEY_B64",
        "GITHUB_TOKEN",
        "ALLOW_LEGACY_GITHUB_PAT",
    ):
        monkeypatch.delenv(name, raising=False)

    token, method = gaa.get_github_api_token()
    assert token == ""
    assert method == "none"
