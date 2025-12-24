#!/usr/bin/env python3
"""
Diagnostic script to identify Crypto.com Exchange API authentication issues
Run this script on AWS to diagnose authentication problems
"""

import os
import sys
import requests
import hmac
import hashlib
import time
import json
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _clean_env_secret(value: str) -> str:
    """Normalize secrets/keys loaded from env"""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def _preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

def check_credentials():
    """Check if API credentials are configured"""
    print("\n" + "="*60)
    print("1. CHECKING API CREDENTIALS")
    print("="*60)
    
    api_key = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    print(f"USE_CRYPTO_PROXY: {use_proxy}")
    print(f"LIVE_TRADING: {live_trading}")
    print(f"API Key: {_preview_secret(api_key)} (length: {len(api_key)})")
    print(f"API Secret: {'<SET>' if api_secret else '<NOT_SET>'} (length: {len(api_secret)})")
    
    if not api_key or not api_secret:
        print("\n❌ ERROR: API credentials are not configured!")
        print("\nTo fix this:")
        print("1. Set EXCHANGE_CUSTOM_API_KEY environment variable")
        print("2. Set EXCHANGE_CUSTOM_API_SECRET environment variable")
        print("3. If using proxy, ensure CRYPTO_PROXY_URL and CRYPTO_PROXY_TOKEN are set")
        return False, None, None
    
    print("✅ API credentials are configured")
    return True, api_key, api_secret

def check_ip_address():
    """Check the outbound IP address"""
    print("\n" + "="*60)
    print("2. CHECKING OUTBOUND IP ADDRESS")
    print("="*60)
    
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        ip = response.text.strip()
        print(f"Outbound IP: {ip}")
        print(f"\n⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange")
        print(f"   Go to: https://exchange.crypto.com/ → Settings → API Keys")
        print(f"   Edit your API key and add this IP to the whitelist")
        return ip
    except Exception as e:
        print(f"❌ Could not determine IP address: {e}")
        return None

def test_authentication(api_key: str, api_secret: str):
    """Test authentication with a simple API call"""
    print("\n" + "="*60)
    print("3. TESTING AUTHENTICATION")
    print("="*60)
    
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
    method = "private/user-balance"
    url = f"{base_url}/{method}"
    
    # Generate signature
    nonce_ms = int(time.time() * 1000)
    params = {}
    params_str = ""  # Empty params
    
    request_id = 1
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce_ms)
    
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
    
    print(f"Request URL: {url}")
    print(f"Method: {method}")
    print(f"Nonce: {nonce_ms}")
    print(f"API Key: {_preview_secret(api_key)}")
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"\nResponse Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                print("✅ Authentication successful!")
                return True, None
            else:
                error_code = result.get("code", 0)
                error_msg = result.get("message", "Unknown error")
                print(f"❌ API returned error: {error_msg} (code: {error_code})")
                return False, f"{error_msg} (code: {error_code})"
        
        elif response.status_code == 401:
            try:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "Authentication failed")
                print(f"❌ Authentication failed: {error_msg} (code: {error_code})")
                
                    if error_code == 40101:
                        print("\n🔍 DIAGNOSIS: Authentication failure (40101)")
                        print("   Possible causes:")
                        print("   - API key or secret is incorrect")
                        print("   - API key is expired or revoked")
                        print("   - ⚠️  API key doesn't have 'Trade' permission (MOST COMMON)")
                        print("      → Read operations work, but order creation fails")
                        print("      → Solution: Enable 'Trade' permission in Crypto.com Exchange")
                
                elif error_code == 40103:
                    print("\n🔍 DIAGNOSIS: IP address not whitelisted (40103)")
                    print("   Solution:")
                    print("   1. Go to https://exchange.crypto.com/ → Settings → API Keys")
                    print("   2. Edit your API key")
                    print("   3. Add your server's IP address to the whitelist")
                    print("   4. Wait a few minutes for changes to take effect")
                
                return False, f"{error_msg} (code: {error_code})"
            except:
                print(f"❌ Authentication failed: HTTP 401")
                return False, "Authentication failed: HTTP 401"
        
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return False, f"HTTP {response.status_code}"
    
    except requests.exceptions.Timeout:
        print("❌ Request timeout - API server may be unreachable")
        return False, "Request timeout"
    except requests.exceptions.ConnectionError:
        print("❌ Connection error - Cannot reach API server")
        return False, "Connection error"
    except Exception as e:
        print(f"❌ Error: {e}")
        return False, str(e)

def check_proxy_configuration():
    """Check proxy configuration if enabled"""
    print("\n" + "="*60)
    print("4. CHECKING PROXY CONFIGURATION")
    print("="*60)
    
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    
    if not use_proxy:
        print("✅ Proxy is disabled - using direct connection")
        return True
    
    proxy_url = os.getenv("CRYPTO_PROXY_URL", "http://127.0.0.1:9000")
    proxy_token = os.getenv("CRYPTO_PROXY_TOKEN", "")
    
    print(f"Proxy URL: {proxy_url}")
    print(f"Proxy Token: {'<SET>' if proxy_token else '<NOT_SET>'}")
    
    # Test proxy connection
    try:
        test_url = f"{proxy_url}/health"
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            print("✅ Proxy is reachable")
            return True
        else:
            print(f"⚠️  Proxy returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot reach proxy: {e}")
        print("   Make sure the proxy service is running")
        return False

def main():
    print("\n" + "="*60)
    print("CRYPTO.COM EXCHANGE API AUTHENTICATION DIAGNOSTIC")
    print("="*60)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    
    # Step 1: Check credentials
    creds_ok, api_key, api_secret = check_credentials()
    if not creds_ok:
        print("\n" + "="*60)
        print("❌ DIAGNOSIS COMPLETE: Credentials not configured")
        print("="*60)
        return 1
    
    # Step 2: Check IP
    ip = check_ip_address()
    
    # Step 3: Check proxy if enabled
    proxy_ok = check_proxy_configuration()
    
    # Step 4: Test authentication (only if not using proxy)
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    if not use_proxy:
        auth_ok, error_msg = test_authentication(api_key, api_secret)
    else:
        print("\n" + "="*60)
        print("5. SKIPPING DIRECT AUTHENTICATION TEST (Using Proxy)")
        print("="*60)
        print("Proxy is enabled - authentication is handled by the proxy service")
        auth_ok = None
        error_msg = None
    
    # Summary
    print("\n" + "="*60)
    print("DIAGNOSIS SUMMARY")
    print("="*60)
    
    if use_proxy:
        if proxy_ok:
            print("✅ Proxy configuration looks correct")
            print("⚠️  If authentication still fails, check the proxy service logs")
        else:
            print("❌ Proxy is not reachable - fix proxy configuration first")
    else:
        if auth_ok:
            print("✅ Authentication is working correctly!")
        elif auth_ok is False:
            print(f"❌ Authentication failed: {error_msg}")
            print("\n📋 TROUBLESHOOTING STEPS:")
            print("1. Verify API key and secret are correct")
            print("2. Check that IP address is whitelisted in Crypto.com Exchange")
            print("3. Ensure API key has 'Trade' permission enabled")
            print("4. Check if API key is expired or revoked")
            print("5. Wait a few minutes after updating IP whitelist")
    
    if ip:
        print(f"\n🌐 Your server IP: {ip}")
        print("   Make sure this IP is whitelisted in Crypto.com Exchange")
    
    print("\n" + "="*60)
    return 0 if (auth_ok is not False) else 1

if __name__ == "__main__":
    sys.exit(main())
