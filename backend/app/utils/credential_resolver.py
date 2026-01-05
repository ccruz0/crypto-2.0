"""
Credential resolver for Crypto.com Exchange API credentials.

Supports multiple environment variable naming conventions and returns
canonical names for missing_env reporting.
"""

import os
import logging
from typing import Tuple, Optional, Dict

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
    diagnostics = {}
    
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


