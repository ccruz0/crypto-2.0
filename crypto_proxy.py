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

logger.info("Crypto.com Signer Proxy initialized")

class ProxyRequest(BaseModel):
    method: str
    params: dict = {}

def generate_signature(method: str, request_id: int, nonce: int, params: dict = None) -> str:
    """Generate HMAC-SHA256 signature for Crypto.com API
    Payload: method + id + api_key + nonce + json.dumps(params, separators=(',',':'))
    """
    params_str = json.dumps(params or {}, separators=(',', ':'))
    payload = f"{method}{request_id}{CRYPTO_API_KEY}{nonce}{params_str}"
    signature = hmac.new(
        CRYPTO_API_SECRET.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
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
        # Generate unique nonce and request ID
        nonce = int(time.time() * 1000)
        request_id = nonce
        
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
        
        logger.info(f"Proxying request: {request.method}")
        
        # Forward request to Crypto.com API
        response = requests.post(
            f"{REST_BASE}/{request.method}",
            json=crypto_body,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        
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
