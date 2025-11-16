import os

# Primary: Crypto.com v1
CRYPTO_REST_BASE = os.getenv("CRYPTO_REST_BASE", "https://api.crypto.com/exchange/v1")
CRYPTO_TIMEOUT   = float(os.getenv("CRYPTO_HTTP_TIMEOUT", "8"))
CRYPTO_RETRIES   = int(os.getenv("CRYPTO_HTTP_RETRIES", "1"))

# Fallback to TRADE_BOT (read-only). Example: http://10.0.2.45:8001
TRADEBOT_BASE    = os.getenv("TRADEBOT_BASE", "").rstrip("/")
FAILOVER_ENABLED = os.getenv("CRYPTO_FAILOVER", "true").lower() == "true"
