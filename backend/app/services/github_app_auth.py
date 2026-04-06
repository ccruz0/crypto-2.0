"""
GitHub App authentication helpers for AWS automation mode startup checks.

Validates env-based GitHub App credentials (no network calls).
Supports emergency legacy PAT when ALLOW_LEGACY_GITHUB_PAT=true and GITHUB_TOKEN is set.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger(__name__)


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


def _github_app_private_key_usable() -> bool:
    """
    Decode GITHUB_APP_PRIVATE_KEY_B64 and ensure the PEM loads as a private key.
    """
    b64 = (os.getenv("GITHUB_APP_PRIVATE_KEY_B64") or "").strip()
    if not b64:
        return False
    try:
        pem = base64.b64decode(b64, validate=False)
    except Exception:
        return False
    if b"BEGIN" not in pem or b"PRIVATE KEY" not in pem:
        return False
    try:
        serialization.load_pem_private_key(pem, password=None, backend=default_backend())
    except Exception:
        return False
    return True


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
