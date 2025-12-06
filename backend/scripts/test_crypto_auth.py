#!/usr/bin/env python3
"""
Crypto.com Exchange API v1 Authentication Healthcheck Script

This script tests the authentication layer by sending a single request to
Crypto.com Exchange API using the same signing logic as the backend.

Usage:
    # Via Docker (recommended):
    docker compose exec backend python scripts/test_crypto_auth.py
    
    # Or directly (requires env vars):
    python scripts/test_crypto_auth.py

The script uses EXACTLY the same environment variables and signing logic
as the backend service. It will output detailed debug information about
the authentication process without exposing secrets.
"""

import os
import sys
import hmac
import hashlib
import time
import json
import requests
import logging
from datetime import datetime

# Add parent directory to path to import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Try to use the same signing logic as the backend
try:
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    USE_BACKEND_CLIENT = True
except ImportError:
    USE_BACKEND_CLIENT = False
    print("⚠️  Warning: Could not import CryptoComTradeClient, using standalone signing logic")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

def _params_to_str(obj, level: int = 0) -> str:
    """Convert params to string following Crypto.com Exchange API v1 spec exactly
    Same implementation as backend/app/services/brokers/crypto_com_trade.py
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

def sign_request_standalone(method: str, params: dict, api_key: str, api_secret: str) -> dict:
    """Standalone signing logic matching backend implementation exactly"""
    nonce_ms = int(time.time() * 1000)
    request_id = 1  # Use 1 as per Crypto.com Exchange API v1 documentation
    
    # Build params string - CRITICAL: empty dict -> empty string, not '{}'
    if params:
        params_str = _params_to_str(params, 0)
    else:
        params_str = ""  # Empty string when params is {}
    
    # String to sign: method + id + api_key + params_string + nonce
    # ORDER MATTERS: params must come BEFORE nonce
    string_to_sign = f"{method}{request_id}{api_key}{params_str}{nonce_ms}"
    
    # Generate HMAC-SHA256 signature
    signature = hmac.new(
        bytes(str(api_secret), 'utf-8'),
        msg=bytes(string_to_sign, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    payload = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": params,
        "nonce": nonce_ms,
        "sig": signature
    }
    
    return payload, string_to_sign, nonce_ms, request_id

def main():
    print("=" * 80)
    print("CRYPTO.COM EXCHANGE API v1 - AUTHENTICATION HEALTHCHECK")
    print("=" * 80)
    print(f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    
    # Load credentials from environment (same as backend)
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY") or os.getenv("CRYPTO_API_KEY", "").strip()
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET") or os.getenv("CRYPTO_API_SECRET", "").strip()
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    proxy_url = os.getenv("CRYPTO_PROXY_URL", "")
    proxy_token = os.getenv("CRYPTO_PROXY_TOKEN", "")
    
    # Validate credentials
    if not api_key or not api_secret:
        print("❌ ERROR: Missing API credentials")
        print("   Required env vars: EXCHANGE_CUSTOM_API_KEY, EXCHANGE_CUSTOM_API_SECRET")
        print("   Or: CRYPTO_API_KEY, CRYPTO_API_SECRET")
        sys.exit(1)
    
    # [CRYPTO_KEY_DEBUG] Log API key (first 4 and last 4 chars only, NEVER the secret)
    if api_key:
        key_preview = f"{api_key[:4]}....{api_key[-4:]}"
        # Determine which env var was used
        if os.getenv("EXCHANGE_CUSTOM_API_KEY"):
            env_source = "EXCHANGE_CUSTOM_API_KEY"
        elif os.getenv("CRYPTO_API_KEY"):
            env_source = "CRYPTO_API_KEY"
        else:
            env_source = "UNKNOWN"
        print(f"[CRYPTO_KEY_DEBUG] test_crypto_auth using api_key: {key_preview} (from {env_source})")
    else:
        print("[CRYPTO_KEY_DEBUG] test_crypto_auth using api_key: NOT_SET")
    
    print(f"✅ API Key: {api_key[:4]}...{api_key[-4:]} ({len(api_key)} chars)")
    print(f"✅ API Secret: {'*' * 20} ({len(api_secret)} chars)")
    print(f"✅ Use Proxy: {use_proxy}")
    if use_proxy:
        print(f"✅ Proxy URL: {proxy_url}")
    print()
    
    # Test method
    method = "private/get-account-summary"
    params = {}
    
    print(f"📡 Method: {method}")
    print(f"📋 Params: {params}")
    print()
    
    # Generate signature
    if USE_BACKEND_CLIENT:
        print("🔐 Using CryptoComTradeClient from backend...")
        try:
            client = CryptoComTradeClient()
            signed_payload = client.sign_request(method, params)
            string_to_sign = "N/A (using backend client)"
            nonce = signed_payload.get("nonce")
            request_id = signed_payload.get("id")
        except Exception as e:
            print(f"⚠️  Backend client failed: {e}")
            print("   Falling back to standalone signing...")
            signed_payload, string_to_sign, nonce, request_id = sign_request_standalone(
                method, params, api_key, api_secret
            )
    else:
        print("🔐 Using standalone signing logic...")
        signed_payload, string_to_sign, nonce, request_id = sign_request_standalone(
            method, params, api_key, api_secret
        )
    
    # Debug output (without exposing secrets)
    print("=" * 80)
    print("DEBUG INFO (no secrets exposed):")
    print("=" * 80)
    print(f"Request ID: {request_id} (type: {type(request_id).__name__})")
    print(f"Nonce: {nonce} (type: {type(nonce).__name__})")
    print(f"Nonce timestamp: {datetime.utcfromtimestamp(nonce/1000).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if string_to_sign != "N/A (using backend client)":
        print(f"String to sign length: {len(string_to_sign)} chars")
        print(f"String to sign preview: {string_to_sign[:80]}...")
    print(f"Signature (first 10): {signed_payload.get('sig', '')[:10]}...")
    print(f"Signature (last 10): ...{signed_payload.get('sig', '')[-10:]}")
    print()
    
    # Safe payload (mask secrets)
    safe_payload = dict(signed_payload)
    safe_payload["api_key"] = f"{api_key[:4]}...{api_key[-4:]}"
    safe_payload["sig"] = f"{signed_payload.get('sig', '')[:10]}...{signed_payload.get('sig', '')[-10:]}"
    print("Request Payload (safe):")
    print(json.dumps(safe_payload, indent=2))
    print()
    
    # Send request
    print("=" * 80)
    print("SENDING REQUEST...")
    print("=" * 80)
    print()
    
    try:
        if use_proxy and proxy_url:
            print(f"📤 Sending via proxy: {proxy_url}/proxy/private")
            response = requests.post(
                f"{proxy_url}/proxy/private",
                json={"method": method, "params": params},
                headers={"X-Proxy-Token": proxy_token},
                timeout=15
            )
            response.raise_for_status()
            result = response.json()
            
            # Parse proxy response
            proxy_status = result.get("status")
            body = result.get("body", {})
            
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except:
                    pass
            
            print(f"✅ Proxy Response Status: {proxy_status}")
            print(f"📄 Response Body:")
            print(json.dumps(body, indent=2))
            
            if proxy_status == 200 and isinstance(body, dict) and "result" in body:
                print("\n✅ SUCCESS: Authentication successful!")
                sys.exit(0)
            elif isinstance(body, dict) and body.get("code") == 10002:
                print("\n❌ ERROR: UNAUTHORIZED (code 10002)")
                print("   This indicates an authentication failure.")
                sys.exit(1)
            else:
                print(f"\n⚠️  Unexpected response status: {proxy_status}")
                sys.exit(1)
        else:
            # Direct call to Crypto.com
            endpoint_url = f"https://api.crypto.com/exchange/v1/{method}"
            print(f"📤 Sending directly to: {endpoint_url}")
            
            response = requests.post(
                endpoint_url,
                json=signed_payload,
                headers={"Content-Type": "application/json"},
                timeout=15
            )
            
            print(f"✅ HTTP Status: {response.status_code}")
            
            try:
                response_json = response.json()
                print(f"📄 Response Body:")
                print(json.dumps(response_json, indent=2))
                
                if response.status_code == 200 and "result" in response_json:
                    print("\n✅ SUCCESS: Authentication successful!")
                    sys.exit(0)
                elif response_json.get("code") == 10002:
                    print("\n❌ ERROR: UNAUTHORIZED (code 10002)")
                    print("   This indicates an authentication failure.")
                    sys.exit(1)
                else:
                    print(f"\n⚠️  Unexpected response")
                    sys.exit(1)
            except json.JSONDecodeError:
                print(f"❌ ERROR: Invalid JSON response")
                print(f"Response text: {response.text[:500]}")
                sys.exit(1)
    
    except requests.exceptions.Timeout:
        print("❌ ERROR: Request timeout")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Request failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

