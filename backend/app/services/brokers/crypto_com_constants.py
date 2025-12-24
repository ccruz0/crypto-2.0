"""
Crypto.com Exchange API v1 Production Constants
These constants should be used across backend and proxy for consistency
"""
import os
import logging

logger = logging.getLogger(__name__)

# REST API Base URLs
# SECURITY: Raw IP usage is disabled by default to prevent scanning patterns
# Use domain names only - they are validated by egress_guard
_CRYPTO_IP = os.getenv("CRYPTO_API_IP", "104.19.223.17")
_USE_IP = os.getenv("USE_CRYPTO_IP", "false").lower() == "true"

# SECURITY: Block raw IP usage - use domain names only
if _USE_IP:
    logger.error(
        f"[SECURITY] USE_CRYPTO_IP=true is disabled for security. "
        f"Raw IP connections are not allowed. Using domain name instead."
    )
    _USE_IP = False

REST_BASE = "https://api.crypto.com/exchange/v1"

# WebSocket URLs (for future use)
WS_USER = "wss://stream.crypto.com/exchange/v1/user"
WS_MARKET = "wss://stream.crypto.com/exchange/v1/market"

# Request Content-Type
CONTENT_TYPE_JSON = "application/json"

# Timeout settings
DEFAULT_TIMEOUT = 10  # seconds


