"""
GitHub App authentication helpers for AWS automation.

Validates env-based GitHub App credentials and mints installation access tokens.
Supports emergency legacy PAT when ALLOW_LEGACY_GITHUB_PAT=true and GITHUB_TOKEN is set.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_INSTALLATION_TOKEN_URL = (
    _GITHUB_API + "/app/installations/{installation_id}/access_tokens"
)
_TOKEN_CACHE_BUFFER_SEC = 120


def _env_nonempty(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def legacy_pat_allowed() -> bool:
    """True when operators explicitly enabled the legacy PAT escape hatch."""
    v = (os.getenv("ALLOW_LEGACY_GITHUB_PAT") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def is_github_app_configured() -> bool:
    """True when all three GitHub App env vars are non-empty (shape not yet validated)."""
    return (
        _env_nonempty("GITHUB_APP_ID")
        and _env_nonempty("GITHUB_APP_INSTALLATION_ID")
        and _env_nonempty("GITHUB_APP_PRIVATE_KEY_B64")
    )


def _load_private_key_pem() -> bytes | None:
    """Decode GITHUB_APP_PRIVATE_KEY_B64 and return PEM bytes, or None on failure."""
    b64 = (os.getenv("GITHUB_APP_PRIVATE_KEY_B64") or "").strip()
    if not b64:
        return None
    try:
        pem = base64.b64decode(b64, validate=False)
    except Exception:
        return None
    if b"BEGIN" not in pem or b"PRIVATE KEY" not in pem:
        return None
    try:
        serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    except Exception:
        return None
    return pem


def _load_private_key():
    pem = _load_private_key_pem()
    if pem is None:
        return None
    return serialization.load_pem_private_key(pem, password=None, backend=default_backend())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _github_app_private_key_usable() -> bool:
    """Decode GITHUB_APP_PRIVATE_KEY_B64 and ensure the PEM loads as a private key."""
    return _load_private_key_pem() is not None


def github_api_token_configured() -> bool:
    """
    True if the process can authenticate to the GitHub API: either legacy PAT (when allowed)
    or a usable GitHub App installation key material.
    """
    if legacy_pat_allowed() and _env_nonempty("GITHUB_TOKEN"):
        return True
    if not is_github_app_configured():
        return False
    return _github_app_private_key_usable()


@dataclass
class _CachedInstallationToken:
    token: str
    expires_at: float


_installation_token_cache: _CachedInstallationToken | None = None


def _create_app_jwt() -> str:
    """Create a short-lived GitHub App JWT (RS256)."""
    app_id = (os.getenv("GITHUB_APP_ID") or "").strip()
    private_key = _load_private_key()
    if not app_id or private_key is None:
        raise ValueError("GitHub App credentials missing or unusable")

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id,
    }
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _mint_installation_access_token() -> tuple[str, float]:
    """
    Exchange a GitHub App JWT for an installation access token.

    Returns (token, expires_at_unix).
    """
    installation_id = (os.getenv("GITHUB_APP_INSTALLATION_ID") or "").strip()
    if not installation_id:
        raise ValueError("GITHUB_APP_INSTALLATION_ID is not set")

    app_jwt = _create_app_jwt()
    url = _INSTALLATION_TOKEN_URL.format(installation_id=installation_id)
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
    }

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, headers=headers)

    if resp.status_code != 201:
        body = (resp.text or "")[:500]
        raise RuntimeError(
            f"GitHub installation token request failed: HTTP {resp.status_code}: {body}"
        )

    data = resp.json()
    token = (data.get("token") or "").strip()
    if not token:
        raise RuntimeError("GitHub installation token response missing token")

    expires_raw = data.get("expires_at")
    expires_at = time.time() + 3600
    if expires_raw:
        try:
            from datetime import datetime

            expires_at = datetime.fromisoformat(
                expires_raw.replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            pass

    return token, expires_at


def get_github_api_token() -> tuple[str, str]:
    """
    Return a bearer token for GitHub API calls and the auth method used.

    Preference order:
    1. GitHub App installation token (auth_method=github_app)
    2. Legacy PAT when ALLOW_LEGACY_GITHUB_PAT=true (auth_method=legacy_pat)

    Returns ("", "none") when no auth is available.
    """
    global _installation_token_cache

    if is_github_app_configured() and _github_app_private_key_usable():
        cached = _installation_token_cache
        if cached and cached.expires_at > time.time() + _TOKEN_CACHE_BUFFER_SEC:
            logger.debug("auth_method=github_app (cached installation token)")
            return cached.token, "github_app"

        try:
            token, expires_at = _mint_installation_access_token()
            _installation_token_cache = _CachedInstallationToken(
                token=token, expires_at=expires_at
            )
            logger.info("auth_method=github_app (minted installation access token)")
            return token, "github_app"
        except Exception as exc:
            logger.error(
                "auth_method=github_app failed to mint installation token: %s",
                exc,
            )
            if not (legacy_pat_allowed() and _env_nonempty("GITHUB_TOKEN")):
                return "", "none"

    if legacy_pat_allowed() and _env_nonempty("GITHUB_TOKEN"):
        logger.info("auth_method=legacy_pat")
        return (os.getenv("GITHUB_TOKEN") or "").strip(), "legacy_pat"

    return "", "none"


def github_authorization_header() -> tuple[dict[str, str], str]:
    """
    Return GitHub API headers with Authorization and the auth_method used.
    """
    token, auth_method = get_github_api_token()
    if not token:
        return {}, auth_method
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }, auth_method


def diagnose_github_app_config() -> dict[str, Any]:
    """Structured diagnostics for logs (never includes secret values)."""
    app = is_github_app_configured()
    return {
        "github_app_id_present": _env_nonempty("GITHUB_APP_ID"),
        "github_installation_id_present": _env_nonempty("GITHUB_APP_INSTALLATION_ID"),
        "private_key_b64_present": _env_nonempty("GITHUB_APP_PRIVATE_KEY_B64"),
        "private_key_pem_loads": _github_app_private_key_usable() if app else False,
        "legacy_pat_escape_hatch": legacy_pat_allowed(),
        "legacy_token_env_present": _env_nonempty("GITHUB_TOKEN"),
    }


def log_redundant_github_token_if_app_active() -> None:
    """Warn when both PAT and App credentials are present (prefer App on AWS)."""
    if not _env_nonempty("GITHUB_TOKEN"):
        return
    if not is_github_app_configured():
        return
    if not _github_app_private_key_usable():
        return
    logger.warning(
        "GITHUB_TOKEN is set while GitHub App credentials are present and loadable; "
        "prefer GitHub App only on AWS (see backend/docs/GITHUB_APP_AUTH.md)."
    )
