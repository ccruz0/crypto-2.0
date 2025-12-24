from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import os, time, hmac, hashlib, requests
import logging
from datetime import datetime, timezone

from app.deps.auth import get_current_user
from app.models.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

from app.services.brokers.crypto_com_constants import REST_BASE
CRYPTO_BASE = os.getenv("EXCHANGE_CUSTOM_BASE_URL", REST_BASE)
API_KEY = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
API_SECRET = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()

def _egress_ip(timeout=5):
    """Get the public IP address used for outbound connections"""
    try:
        ip = http_get("https://api.ipify.org", timeout=timeout, calling_module="routes_internal").text.strip()
        logger.info(f"[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: {ip}")
        return ip
    except Exception as e:
        logger.error(f"[CRYPTO_AUTH_DIAG] Failed to get outbound IP: {e}")
        return None

def _sign_payload(method: str, params: dict, api_key: str, api_secret: str, nonce: int) -> dict:
    """Sign payload using Crypto.com Exchange API v1 format: method + id + api_key + params_str + nonce"""
    request_id = 1  # Use 1 as per Crypto.com Exchange API v1 documentation
    
    # Build params string for signature (empty string if params is empty)
    if params:
        def flatten(d):
            return "".join(f"{k}{v}" for k, v in sorted((d or {}).items(), key=lambda x: x[0]))
        params_str = flatten(params)
    else:
        params_str = ""  # Empty string when params is {}
    
    # String to sign: method + id + api_key + params_str + nonce
    string_to_sign = f"{method}{request_id}{api_key}{params_str}{nonce}"
    
    # [CRYPTO_AUTH_DIAG] Log signing details
    logger.info(f"[CRYPTO_AUTH_DIAG] _sign_payload: method={method}, params={params}, request_id={request_id}, nonce={nonce}")
    logger.info(f"[CRYPTO_AUTH_DIAG] _sign_payload: params_str={repr(params_str)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] _sign_payload: string_to_sign={string_to_sign}")
    
    sig = hmac.new(api_secret.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    
    payload = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": params or {},
        "nonce": nonce,
        "sig": sig
    }
    return payload

@router.get("/internal/diagnostics/failover")
def diag():
    """Failover diagnostics (no auth required)"""
    try:
        from app.core.failover_config import CRYPTO_REST_BASE, TRADEBOT_BASE, FAILOVER_ENABLED
        return {
            "rest_base": CRYPTO_REST_BASE,
            "tradebot_base": bool(TRADEBOT_BASE),
            "tradebot_url": TRADEBOT_BASE if TRADEBOT_BASE else None,
            "failover": FAILOVER_ENABLED
        }
    except Exception as e:
        return {
            "error": str(e),
            "rest_base": "N/A",
            "tradebot_base": False,
            "failover": False
        }

@router.get("/internal/websocket/status")
def websocket_status():
    """WebSocket connection status (no auth required)"""
    try:
        from app.services.websocket_manager import is_websocket_connected
        from app.services.brokers.crypto_com_websocket import get_ws_client
        from app.utils.http_client import http_get, http_post
        
        connected = is_websocket_connected()
        ws_client = get_ws_client()
        
        return {
            "websocket_enabled": os.getenv("USE_WEBSOCKET", "false").lower() == "true",
            "connected": connected,
            "subscribed": ws_client.subscribed if connected else False,
            "ws_url": ws_client.ws_url if connected else None
        }
    except Exception as e:
        return {
            "websocket_enabled": os.getenv("USE_WEBSOCKET", "false").lower() == "true",
            "connected": False,
            "error": str(e)
        }

@router.get("/internal/crypto/ping-private")
def ping_private(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Diagnostic endpoint to test Crypto.com private API authentication"""
    if not API_KEY or not API_SECRET:
        raise HTTPException(status_code=500, detail="Missing EXCHANGE_CUSTOM_API_KEY/SECRET in env")
    
    # [CRYPTO_AUTH_DIAG] Log credentials
    logger.info(f"[CRYPTO_AUTH_DIAG] === DIAGNOSTIC REQUEST ===")
    logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY repr: {repr(API_KEY)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY length: {len(API_KEY)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY length: {len(API_SECRET)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY has whitespace: {any(c.isspace() for c in API_SECRET)}")

    eip = _egress_ip()
    current_time = time.time()
    current_utc = datetime.now(timezone.utc).isoformat()
    nonce = int(time.time() * 1000)
    
    logger.info(f"[CRYPTO_AUTH_DIAG] server_time_utc: {current_utc}")
    logger.info(f"[CRYPTO_AUTH_DIAG] server_time_epoch: {current_time}")
    logger.info(f"[CRYPTO_AUTH_DIAG] nonce: {nonce} (type: {type(nonce).__name__})")
    
    url = f"{CRYPTO_BASE}/private/get-account-summary"
    payload = _sign_payload("private/get-account-summary", {}, API_KEY, API_SECRET, nonce)
    
    logger.info(f"[CRYPTO_AUTH_DIAG] URL: {url}")
    logger.info(f"[CRYPTO_AUTH_DIAG] Payload (safe): {repr({k: v if k != 'sig' else v[:10] + '...' for k, v in payload.items()})}")

    try:
        r = http_post(url, json=payload, timeout=10, calling_module="routes_internal")
        code, msg = None, None
        try:
            j = r.json()
            code = j.get("code") or j.get("error", {}).get("code")
            msg = j.get("message") or j.get("error", {}).get("message")
        except Exception:
            pass

        hints = []
        if code == 10007:
            hints.append("⚠️ INVALID_NONCE: check clock sync (Chrony/NTP) and strictly increasing nonce.")
        if r.status_code in (401, 403):
            hints.append("🔒 Auth/IP issue. Check whitelist and API keys.")
        if r.status_code == 429:
            hints.append("🚫 Rate limited. Wait before retry.")
        if eip is None:
            hints.append("🌐 Could not resolve egress IP (network/DNS issue).")

        return {
            "ok": r.ok,
            "status": r.status_code,
            "code": code,
            "message": msg,
            "egress_ip": eip,
            "nonce": nonce,
            "base_url": CRYPTO_BASE,
            "hints": hints,
            "raw": r.text[:800]
        }
    except requests.RequestException as ex:
        raise HTTPException(status_code=502, detail=f"Network error: {ex}")
