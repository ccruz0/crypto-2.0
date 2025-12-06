#!/usr/bin/env python3
"""
Crypto.com Signer Proxy Service
Runs on trade_Bot instance and signs authenticated requests to Crypto.com Exchange API
"""

import os
import hmac
import hashlib
import time
import requests
import json
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# REST API Base URL
# Exchange API v1 uses: https://api.crypto.com/exchange/v1
# Spot API v2 uses: https://api.crypto.com/v2
REST_BASE = "https://api.crypto.com/exchange/v1"

app = FastAPI(title="Crypto.com Signer Proxy", version="1.0.0")

# Environment variables
CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY", "").strip()
CRYPTO_API_SECRET = os.getenv("CRYPTO_API_SECRET", "").strip()
CRYPTO_PROXY_TOKEN = os.getenv("CRYPTO_PROXY_TOKEN", "").strip()

# Validate environment variables
if not CRYPTO_API_KEY or not CRYPTO_API_SECRET:
    logger.error("CRYPTO_API_KEY or CRYPTO_API_SECRET not set")
    raise ValueError("Missing required environment variables")

if not CRYPTO_PROXY_TOKEN:
    logger.error("CRYPTO_PROXY_TOKEN not set")
    raise ValueError("Missing CRYPTO_PROXY_TOKEN")

# [CRYPTO_KEY_DEBUG] Log API key (first 4 and last 4 chars only, NEVER the secret)
if CRYPTO_API_KEY:
    key_preview = f"{CRYPTO_API_KEY[:4]}....{CRYPTO_API_KEY[-4:]}"
else:
    key_preview = "NOT_SET"
logger.info(f"[CRYPTO_KEY_DEBUG] crypto_proxy using api_key: {key_preview} (from CRYPTO_API_KEY)")

logger.info("Crypto.com Signer Proxy initialized")

class ProxyRequest(BaseModel):
    method: str
    params: dict = {}

def _params_to_str(obj, level: int = 0) -> str:
    """Convert params to string following Crypto.com Exchange API v1 spec exactly
    For empty params: return empty string (not '{}')
    For non-empty params: sort keys alphabetically and concatenate key+value without separators
    """
    MAX_LEVEL = 3
    if level >= MAX_LEVEL:
        return str(obj)
    
    if not obj:
        return ""  # Empty dict -> empty string for signature
    
    return_str = ""
    for key in sorted(obj):
        return_str += key
        if obj[key] is None:
            return_str += 'null'
        elif isinstance(obj[key], list):
            for subObj in obj[key]:
                if isinstance(subObj, dict):
                    return_str += _params_to_str(subObj, level + 1)
                else:
                    return_str += str(subObj)
        elif isinstance(obj[key], dict):
            return_str += _params_to_str(obj[key], level + 1)
        else:
            return_str += str(obj[key])
    return return_str

def generate_signature(method: str, request_id: int, nonce: int, params: dict = None) -> str:
    """Generate HMAC-SHA256 signature for Crypto.com Exchange API v1
    Format per Crypto.com docs: method + id + api_key + params_string + nonce
    For empty params: use empty string (not '{}')
    """
    # Build params string - CRITICAL: empty dict -> empty string, not '{}'
    if params:
        params_str = _params_to_str(params, 0)
    else:
        params_str = ""  # Empty string when params is {}
    
    # String to sign: method + id + api_key + params_string + nonce
    # ORDER MATTERS: params must come BEFORE nonce
    string_to_sign = f"{method}{request_id}{CRYPTO_API_KEY}{params_str}{nonce}"
    
    # [CRYPTO_AUTH_DIAG] Log signature components
    logger.info(f"[CRYPTO_AUTH_DIAG] === SIGNATURE GENERATION ===")
    logger.info(f"[CRYPTO_AUTH_DIAG] params_str_len={len(params_str)}, params_str_repr={repr(params_str)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] string_to_sign_length={len(string_to_sign)}")
    logger.info(f"[CRYPTO_AUTH_DIAG] string_to_sign={string_to_sign}")
    
    signature = hmac.new(
        CRYPTO_API_SECRET.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # [CRYPTO_AUTH_DIAG] Log signature
    logger.info(f"[CRYPTO_AUTH_DIAG] signature={signature}")
    logger.info(f"[CRYPTO_AUTH_DIAG] ============================")
    
    return signature

@app.post("/proxy/private")
async def proxy_private(
    request: ProxyRequest,
    x_proxy_token: str = Header(..., alias="X-Proxy-Token")
):
    """
    Proxy endpoint for Crypto.com private API calls
    """
    # Validate proxy token
    if x_proxy_token != CRYPTO_PROXY_TOKEN:
        logger.warning(f"Invalid proxy token from client")
        raise HTTPException(status_code=401, detail="Invalid proxy token")
    
    try:
        # [CRYPTO_AUTH_DIAG] Log outbound IP (from proxy's perspective)
        try:
            egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
            logger.info(f"[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: {egress_ip}")
        except Exception as e:
            logger.warning(f"[CRYPTO_AUTH_DIAG] Could not determine outbound IP: {e}")
        
        # [CRYPTO_AUTH_DIAG] Log credentials used by proxy
        logger.info(f"[CRYPTO_AUTH_DIAG] === PROXY CREDENTIALS ===")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY repr: {repr(CRYPTO_API_KEY)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY length: {len(CRYPTO_API_KEY)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY preview: {CRYPTO_API_KEY[:4]}....{CRYPTO_API_KEY[-4:] if len(CRYPTO_API_KEY) >= 4 else ''}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY length: {len(CRYPTO_API_SECRET)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY starts with: {CRYPTO_API_SECRET[:6] if len(CRYPTO_API_SECRET) >= 6 else 'N/A'}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY has whitespace: {any(c.isspace() for c in CRYPTO_API_SECRET) if CRYPTO_API_SECRET else False}")
        
        # Generate unique nonce and request ID
        # Per Crypto.com Exchange API v1: use request_id = 1 for consistency with working methods
        nonce = int(time.time() * 1000)
        request_id = 1  # Use 1 as per Crypto.com Exchange API v1 documentation
        
        current_utc = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        current_time = time.time()
        
        # [CRYPTO_AUTH_DIAG] Log request details
        logger.info(f"[CRYPTO_AUTH_DIAG] === PROXY REQUEST START ===")
        logger.info(f"[CRYPTO_AUTH_DIAG] method={request.method}")
        logger.info(f"[CRYPTO_AUTH_DIAG] params={request.params}")
        logger.info(f"[CRYPTO_AUTH_DIAG] server_time_utc={current_utc}")
        logger.info(f"[CRYPTO_AUTH_DIAG] server_time_epoch={current_time}")
        logger.info(f"[CRYPTO_AUTH_DIAG] nonce={nonce} (type={type(nonce).__name__})")
        logger.info(f"[CRYPTO_AUTH_DIAG] request_id={request_id}")
        
        # Generate signature
        signature = generate_signature(request.method, request_id, nonce, request.params)
        
        # Prepare request body for Crypto.com API
        crypto_body = {
            "id": request_id,
            "method": request.method,
            "api_key": CRYPTO_API_KEY,
            "sig": signature,
            "nonce": nonce,
            "params": request.params
        }
        
        # [CRYPTO_AUTH_DEBUG] Log payload (without secret)
        safe_body = dict(crypto_body)
        safe_body["api_key"] = f"{CRYPTO_API_KEY[:3]}...{CRYPTO_API_KEY[-3:]}" if len(CRYPTO_API_KEY) >= 6 else "***"
        safe_body["sig"] = f"{signature[:3]}...{signature[-3]}"
        logger.info(f"[CRYPTO_AUTH_DEBUG] payload={json.dumps(safe_body, indent=2)}")
        
        logger.info(f"Proxying request: {request.method}")
        
        # Forward request to Crypto.com API
        # Note: REST_BASE is "https://api.crypto.com/v2", but Exchange API v1 uses /exchange/v1
        # Check which endpoint format is expected
        if request.method.startswith("private/"):
            # Exchange API v1 format
            endpoint_url = f"https://api.crypto.com/exchange/v1/{request.method}"
        else:
            endpoint_url = f"{REST_BASE}/{request.method}"
        
        logger.info(f"[CRYPTO_AUTH_DEBUG] endpoint_url={endpoint_url}")
        
        response = requests.post(
            endpoint_url,
            json=crypto_body,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        
        # [CRYPTO_AUTH_DIAG] Log response
        logger.info(f"[CRYPTO_AUTH_DIAG] response_status={response.status_code}")
        try:
            response_json = response.json()
            logger.info(f"[CRYPTO_AUTH_DIAG] response_body={json.dumps(response_json, indent=2)}")
        except:
            logger.info(f"[CRYPTO_AUTH_DIAG] response_body_text={response.text[:200]}")
        logger.info(f"[CRYPTO_AUTH_DIAG] === PROXY REQUEST END ===")
        
        # Return response to client
        return JSONResponse(
            status_code=200,
            content={
                "status": response.status_code,
                "body": response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text,
                "rid": request_id
            }
        )
        
    except requests.exceptions.Timeout:
        logger.error("Crypto.com API timeout")
        return JSONResponse(
            status_code=504,
            content={
                "status": 504,
                "body": {"error": "Crypto.com API timeout"},
                "rid": request_id
            }
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Crypto.com API error: {e}")
        return JSONResponse(
            status_code=502,
            content={
                "status": 502,
                "body": {"error": f"Crypto.com API error: {str(e)}"},
                "rid": request_id
            }
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": 500,
                "body": {"error": f"Proxy error: {str(e)}"},
                "rid": request_id
            }
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "crypto-proxy"}

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Crypto.com Signer Proxy", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9000)
