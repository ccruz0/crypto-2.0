"""
Crypto.com Exchange API v1 Production Constants
These constants should be used across backend and proxy for consistency
"""
import os

# REST API Base URLs
# Use IP directly if DNS fails (fallback)
_CRYPTO_IP = os.getenv("CRYPTO_API_IP", "104.19.223.17")
_USE_IP = os.getenv("USE_CRYPTO_IP", "false").lower() == "true"
REST_BASE = f"https://{_CRYPTO_IP}/exchange/v1" if _USE_IP else "https://api.crypto.com/exchange/v1"

# WebSocket URLs (for future use)
WS_USER = "wss://stream.crypto.com/exchange/v1/user"
WS_MARKET = "wss://stream.crypto.com/exchange/v1/market"

# Request Content-Type
CONTENT_TYPE_JSON = "application/json"

# Timeout settings
DEFAULT_TIMEOUT = 10  # seconds


