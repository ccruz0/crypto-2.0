"""
Tests for portfolio snapshot credential resolver.

Verifies that the credential resolver picks the right env var pairs
and returns canonical names in missing_env when nothing is set.
"""

import os
import pytest
from unittest.mock import patch
from app.utils.credential_resolver import (
    resolve_crypto_credentials,
    get_missing_env_vars,
    CANONICAL_API_KEY,
    CANONICAL_API_SECRET,
)


def test_resolve_crypto_credentials_canonical():
    """Test that canonical pair is used when present."""
    with patch.dict(os.environ, {
        "EXCHANGE_CUSTOM_API_KEY": "test_key_123",
        "EXCHANGE_CUSTOM_API_SECRET": "test_secret_456",
    }, clear=False):
        api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
        
        assert api_key == "test_key_123"
        assert api_secret == "test_secret_456"
        assert used_pair is None  # Canonical pair, no need to report
        assert diagnostics["EXCHANGE_CUSTOM_API_KEY_PRESENT"] is True
        assert diagnostics["EXCHANGE_CUSTOM_API_SECRET_PRESENT"] is True


def test_resolve_crypto_credentials_alternative_pair():
    """Test that CRYPTO_COM_API_KEY/SECRET pair is used when canonical is missing."""
    with patch.dict(os.environ, {
        "CRYPTO_COM_API_KEY": "alt_key_789",
        "CRYPTO_COM_API_SECRET": "alt_secret_012",
    }, clear=False):
        # Remove canonical pair if present
        os.environ.pop("EXCHANGE_CUSTOM_API_KEY", None)
        os.environ.pop("EXCHANGE_CUSTOM_API_SECRET", None)
        
        api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
        
        assert api_key == "alt_key_789"
        assert api_secret == "alt_secret_012"
        assert used_pair == "CRYPTO_COM_API_KEY/CRYPTO_COM_API_SECRET"
        assert diagnostics["CRYPTO_COM_API_KEY_PRESENT"] is True
        assert diagnostics["CRYPTO_COM_API_SECRET_PRESENT"] is True


def test_resolve_crypto_credentials_third_pair():
    """Test that CRYPTOCOM_API_KEY/SECRET pair is used when others are missing."""
    with patch.dict(os.environ, {
        "CRYPTOCOM_API_KEY": "third_key_345",
        "CRYPTOCOM_API_SECRET": "third_secret_678",
    }, clear=False):
        # Remove other pairs if present
        os.environ.pop("EXCHANGE_CUSTOM_API_KEY", None)
        os.environ.pop("EXCHANGE_CUSTOM_API_SECRET", None)
        os.environ.pop("CRYPTO_COM_API_KEY", None)
        os.environ.pop("CRYPTO_COM_API_SECRET", None)
        
        api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
        
        assert api_key == "third_key_345"
        assert api_secret == "third_secret_678"
        assert used_pair == "CRYPTOCOM_API_KEY/CRYPTOCOM_API_SECRET"


def test_resolve_crypto_credentials_none_missing():
    """Test that None is returned when no credentials are found."""
    # Remove all credential pairs
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("EXCHANGE_CUSTOM_API_KEY", None)
        os.environ.pop("EXCHANGE_CUSTOM_API_SECRET", None)
        os.environ.pop("CRYPTO_COM_API_KEY", None)
        os.environ.pop("CRYPTO_COM_API_SECRET", None)
        os.environ.pop("CRYPTOCOM_API_KEY", None)
        os.environ.pop("CRYPTOCOM_API_SECRET", None)
        
        api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
        
        assert api_key is None
        assert api_secret is None
        assert used_pair is None
        assert diagnostics["EXCHANGE_CUSTOM_API_KEY_PRESENT"] is False
        assert diagnostics["EXCHANGE_CUSTOM_API_SECRET_PRESENT"] is False


def test_resolve_crypto_credentials_quotes_stripped():
    """Test that quotes are stripped from env values."""
    with patch.dict(os.environ, {
        "EXCHANGE_CUSTOM_API_KEY": '"quoted_key"',
        "EXCHANGE_CUSTOM_API_SECRET": "'quoted_secret'",
    }, clear=False):
        api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
        
        assert api_key == "quoted_key"
        assert api_secret == "quoted_secret"


def test_get_missing_env_vars_none_set():
    """Test that canonical names are returned when nothing is set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("EXCHANGE_CUSTOM_API_KEY", None)
        os.environ.pop("EXCHANGE_CUSTOM_API_SECRET", None)
        os.environ.pop("CRYPTO_COM_API_KEY", None)
        os.environ.pop("CRYPTO_COM_API_SECRET", None)
        os.environ.pop("CRYPTOCOM_API_KEY", None)
        os.environ.pop("CRYPTOCOM_API_SECRET", None)
        
        missing = get_missing_env_vars()
        
        assert missing == [CANONICAL_API_KEY, CANONICAL_API_SECRET]


def test_get_missing_env_vars_canonical_set():
    """Test that empty list is returned when canonical pair is set."""
    with patch.dict(os.environ, {
        "EXCHANGE_CUSTOM_API_KEY": "test_key",
        "EXCHANGE_CUSTOM_API_SECRET": "test_secret",
    }, clear=False):
        missing = get_missing_env_vars()
        
        assert missing == []


def test_get_missing_env_vars_alternative_set():
    """Test that empty list is returned when alternative pair is set (canonical still reported)."""
    with patch.dict(os.environ, {
        "CRYPTO_COM_API_KEY": "alt_key",
        "CRYPTO_COM_API_SECRET": "alt_secret",
    }, clear=False):
        os.environ.pop("EXCHANGE_CUSTOM_API_KEY", None)
        os.environ.pop("EXCHANGE_CUSTOM_API_SECRET", None)
        
        missing = get_missing_env_vars()
        
        # Should return empty because credentials are available (even if non-canonical)
        assert missing == []


def test_resolve_crypto_credentials_priority_order():
    """Test that first match wins (canonical > CRYPTO_COM > CRYPTOCOM)."""
    # Set all three pairs
    with patch.dict(os.environ, {
        "EXCHANGE_CUSTOM_API_KEY": "canonical_key",
        "EXCHANGE_CUSTOM_API_SECRET": "canonical_secret",
        "CRYPTO_COM_API_KEY": "alt_key",
        "CRYPTO_COM_API_SECRET": "alt_secret",
        "CRYPTOCOM_API_KEY": "third_key",
        "CRYPTOCOM_API_SECRET": "third_secret",
    }, clear=False):
        api_key, api_secret, used_pair, _ = resolve_crypto_credentials()
        
        # Should use canonical (first match)
        assert api_key == "canonical_key"
        assert api_secret == "canonical_secret"
        assert used_pair is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


