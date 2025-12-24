"""Diagnostic endpoints for Crypto.com authentication troubleshooting"""
from fastapi import APIRouter
import logging
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/diag/crypto-auth")
def crypto_auth_diagnostic():
    """Public diagnostic endpoint to test Crypto.com authentication"""
    import os
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.utils.http_client import http_get, http_post
    
    results = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "server_time_epoch": time.time(),
        "outbound_ip": None,
        "credentials_status": {},
        "test_result": {}
    }
    
    # Get outbound IP
    try:
        results["outbound_ip"] = http_get("https://api.ipify.org", timeout=5, calling_module="routes_diag").text.strip()
        logger.info(f"[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: {results['outbound_ip']}")
    except Exception as e:
        logger.error(f"[CRYPTO_AUTH_DIAG] Failed to get outbound IP: {e}")
        results["outbound_ip"] = None
    
    # Check credentials
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    
    results["credentials_status"] = {
        "api_key_set": bool(api_key),
        "api_key_length": len(api_key),
        "api_key_preview": f"{api_key[:4]}....{api_key[-4:]}" if len(api_key) >= 4 else "NOT_SET",
        "secret_set": bool(api_secret),
        "secret_length": len(api_secret),
        "secret_starts_with": api_secret[:6] if len(api_secret) >= 6 else "N/A",
        "secret_has_whitespace": any(c.isspace() for c in api_secret) if api_secret else False
    }
    
    # Try to make a test request
    if api_key and api_secret:
        try:
            client = CryptoComTradeClient()
            result = client.get_account_summary()
            
            if result and "accounts" in result:
                results["test_result"] = {
                    "success": True,
                    "accounts_count": len(result.get("accounts", [])),
                    "message": "Authentication successful"
                }
            else:
                results["test_result"] = {
                    "success": False,
                    "error": "No accounts in response",
                    "response": str(result)[:200]
                }
        except Exception as e:
            results["test_result"] = {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    else:
        results["test_result"] = {
            "success": False,
            "error": "Credentials not configured"
        }
    
    return results



