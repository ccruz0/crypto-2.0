"""Diagnostic endpoints for Crypto.com authentication troubleshooting"""
from fastapi import APIRouter
import logging
from datetime import datetime, timezone
import time
import os

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


@router.get("/diagnostics/whoami")
def whoami_diagnostic():
    """
    Safe diagnostic endpoint to identify which backend service is running.
    Gated by ENVIRONMENT=local or PORTFOLIO_DEBUG=1.
    Returns service info without exposing secrets.
    """
    # Gate by environment or debug flag
    environment = os.getenv("ENVIRONMENT", "UNKNOWN")
    portfolio_debug = os.getenv("PORTFOLIO_DEBUG", "0") == "1"
    is_local = environment == "local" or environment == "UNKNOWN"
    
    if not (is_local or portfolio_debug):
        return {
            "error": "Diagnostic endpoint disabled. Set ENVIRONMENT=local or PORTFOLIO_DEBUG=1 to enable."
        }
    
    import sys
    import platform
    
    # Get process info
    process_id = os.getpid()
    
    # Get container/service name
    container_name = os.getenv("HOSTNAME", os.getenv("CONTAINER_NAME", "UNKNOWN"))
    
    # Get runtime origin
    runtime_origin = os.getenv("RUNTIME_ORIGIN", "UNKNOWN")
    
    # Get app version/commit if available
    app_version = os.getenv("ATP_GIT_SHA", os.getenv("GIT_SHA", "UNKNOWN"))
    build_time = os.getenv("ATP_BUILD_TIME", os.getenv("BUILD_TIME", "UNKNOWN"))
    
    # Get env file names that are loaded (names only, not paths or contents)
    env_files_loaded = []
    if os.path.exists(".env"):
        env_files_loaded.append(".env")
    if os.path.exists(".env.local"):
        env_files_loaded.append(".env.local")
    if os.path.exists(".env.aws"):
        env_files_loaded.append(".env.aws")
    # Check if env_file directive loaded any (docker-compose sets these)
    env_file_var = os.getenv("ENV_FILE", "")
    if env_file_var:
        env_files_loaded.extend([f for f in env_file_var.split(",") if f.strip()])
    
    # Check which credential pairs are present (names only, not values)
    from app.utils.credential_resolver import resolve_crypto_credentials
    _, _, used_pair_name, credential_diagnostics = resolve_crypto_credentials()
    
    # Build safe credential info (only env var names)
    credential_info = {
        "selected_pair": used_pair_name if used_pair_name else "NONE",
        "checked_pairs": [k.replace("_PRESENT", "") for k in credential_diagnostics.keys() if k.endswith("_PRESENT")]
    }
    
    # Get client path info (safe)
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    client_path = "crypto_com_proxy" if use_proxy else "crypto_com_direct"
    
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "service_info": {
            "process_id": process_id,
            "container_name": container_name,
            "runtime_origin": runtime_origin,
            "environment": environment,
            "app_version": app_version,
            "build_time": build_time,
            "python_version": sys.version.split()[0],
            "platform": platform.platform()
        },
        "env_files_loaded": env_files_loaded,
        "credential_info": credential_info,
        "client_path": client_path,
        "use_crypto_proxy": use_proxy
    }



