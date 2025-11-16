from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import os, time, hmac, hashlib, requests

from app.deps.auth import get_current_user
from app.models.db import get_db

router = APIRouter()

from app.services.brokers.crypto_com_constants import REST_BASE
CRYPTO_BASE = os.getenv("EXCHANGE_CUSTOM_BASE_URL", REST_BASE)
API_KEY = os.getenv("EXCHANGE_CUSTOM_API_KEY")
API_SECRET = os.getenv("EXCHANGE_CUSTOM_API_SECRET")

def _egress_ip(timeout=5):
    try:
        return requests.get("https://api.ipify.org", timeout=timeout).text.strip()
    except Exception:
        return None

def _sign_payload(method: str, params: dict, api_key: str, api_secret: str, nonce: int) -> dict:
    payload = {
        "id": nonce,
        "method": method,
        "api_key": api_key,
        "params": params or {},
        "nonce": nonce,
    }

    def flatten(d):
        return "".join(f"{k}{v}" for k, v in sorted((d or {}).items(), key=lambda x: x[0]))
    prehash = f"{payload['method']}{flatten(payload['params'])}{payload['nonce']}{payload['api_key']}"
    sig = hmac.new(API_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()
    payload["sig"] = sig
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
    if not API_KEY or not API_SECRET:
        raise HTTPException(status_code=500, detail="Missing EXCHANGE_CUSTOM_API_KEY/SECRET in env")

    eip = _egress_ip()
    nonce = int(time.time() * 1000)
    url = f"{CRYPTO_BASE}/private/get-account-summary"
    payload = _sign_payload("private/get-account-summary", {}, API_KEY, API_SECRET, nonce)

    try:
        r = requests.post(url, json=payload, timeout=10)
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
