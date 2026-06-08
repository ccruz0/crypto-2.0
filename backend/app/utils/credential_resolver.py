"""
Credential resolver for Crypto.com Exchange API credentials.

Supports multiple environment variable naming conventions and returns
canonical names for missing_env reporting.
"""

import os
import logging
from pathlib import Path
from typing import Any, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

# Canonical credential names (used in missing_env)
CANONICAL_API_KEY = "EXCHANGE_CUSTOM_API_KEY"
CANONICAL_API_SECRET = "EXCHANGE_CUSTOM_API_SECRET"

# Supported credential pairs (checked in order, first match wins)
CREDENTIAL_PAIRS = [
    ("EXCHANGE_CUSTOM_API_KEY", "EXCHANGE_CUSTOM_API_SECRET"),
    ("CRYPTO_COM_API_KEY", "CRYPTO_COM_API_SECRET"),
    ("CRYPTOCOM_API_KEY", "CRYPTOCOM_API_SECRET"),
]


def runtime_env_file_path() -> Path:
    """Container/runtime path for secrets/runtime.env (no secret values read here)."""
    custom = (os.getenv("RUNTIME_ENV_PATH") or "").strip()
    if custom:
        return Path(custom)
    for candidate in (Path("/app/secrets/runtime.env"), Path("secrets/runtime.env")):
        if candidate.exists():
            return candidate
    return Path("/app/secrets/runtime.env")


def hydrate_crypto_env_from_runtime_file() -> dict[str, bool]:
    """
    Load Crypto.com credential env vars from runtime.env into os.environ when missing.
    Safe for logging: returns presence flags only, never values.
    """
    path = runtime_env_file_path()
    hydrated: dict[str, bool] = {}
    if not path.is_file():
        return hydrated

    wanted = {name for pair in CREDENTIAL_PAIRS for name in pair}
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in wanted:
                continue
            val = value.strip().strip("'\"")
            if not val:
                continue
            if not (os.getenv(key) or "").strip():
                os.environ[key] = val
                hydrated[key] = True
            else:
                hydrated[key] = True
    except OSError as exc:
        logger.warning("hydrate_crypto_env_from_runtime_file failed path=%s err=%s", path, type(exc).__name__)
    return hydrated


def ensure_trade_client_crypto_credentials() -> dict[str, Any]:
    """
    Align the shared trade_client singleton with the same credential resolution
    used by portfolio_cache and portfolio_snapshot. Read-only; no API calls.
    """
    from app.services.brokers.crypto_com_trade import trade_client

    hydrate_crypto_env_from_runtime_file()
    api_key, api_secret, used_pair_name, diagnostics = resolve_crypto_credentials()

    use_proxy = (os.getenv("USE_CRYPTO_PROXY") or "false").strip().lower() == "true"
    if use_proxy:
        trade_client.use_proxy = True

    if api_key and api_secret:
        if trade_client.api_key != api_key or trade_client.api_secret != api_secret:
            trade_client.api_key = api_key
            trade_client.api_secret = api_secret

    return {
        "credentials_loaded": bool(api_key and api_secret),
        "used_pair_name": used_pair_name,
        "credential_diagnostics": diagnostics,
        "proxy_enabled": bool(trade_client.use_proxy),
        "runtime_env_path": str(runtime_env_file_path()),
    }


def resolve_crypto_credentials() -> Tuple[Optional[str], Optional[str], Optional[str], Dict[str, bool]]:
    """
    Resolve Crypto.com API credentials from environment variables.
    
    Checks multiple env var naming conventions and returns the first match.
    
    Returns:
        Tuple of:
        - api_key: The resolved API key (or None if not found)
        - api_secret: The resolved API secret (or None if not found)
        - used_pair_name: Name of the pair used (e.g., "CRYPTO_COM_API_KEY/SECRET") or None
        - diagnostics: Dict with credential presence info (safe for logging)
    
    Example:
        >>> api_key, api_secret, used_pair, diag = resolve_crypto_credentials()
        >>> if api_key and api_secret:
        ...     print(f"Using {used_pair}")
        >>> else:
        ...     print(f"Missing: {CANONICAL_API_KEY}, {CANONICAL_API_SECRET}")
    """
    diagnostics: Dict[str, bool] = {}
    hydrate_crypto_env_from_runtime_file()

    # Check each credential pair in order
    for key_name, secret_name in CREDENTIAL_PAIRS:
        api_key = os.getenv(key_name, "").strip()
        api_secret = os.getenv(secret_name, "").strip()
        
        # Track presence (safe for logging)
        diagnostics[f"{key_name}_PRESENT"] = bool(api_key)
        diagnostics[f"{secret_name}_PRESENT"] = bool(api_secret)
        
        # If both are present, use this pair
        if api_key and api_secret:
            # Clean up quotes if present
            if len(api_key) >= 2 and api_key[0] == api_key[-1] and api_key[0] in ("'", '"'):
                api_key = api_key[1:-1].strip()
            if len(api_secret) >= 2 and api_secret[0] == api_secret[-1] and api_secret[0] in ("'", '"'):
                api_secret = api_secret[1:-1].strip()
            
            # Determine pair name for reporting
            if key_name == CANONICAL_API_KEY:
                used_pair_name = None  # Canonical pair, no need to report
            else:
                used_pair_name = f"{key_name}/{secret_name}"
            
            return api_key, api_secret, used_pair_name, diagnostics
    
    # No credentials found
    return None, None, None, diagnostics


def get_missing_env_vars() -> list:
    """
    Get list of canonical missing environment variable names.
    
    Returns:
        List of canonical env var names that are missing.
        Always returns [CANONICAL_API_KEY, CANONICAL_API_SECRET] if no credentials found.
    """
    api_key, api_secret, _, _ = resolve_crypto_credentials()
    
    missing = []
    if not api_key:
        missing.append(CANONICAL_API_KEY)
    if not api_secret:
        missing.append(CANONICAL_API_SECRET)
    
    return missing


