#!/usr/bin/env python3
"""
Comprehensive diagnostic script for Crypto.com API authentication error 40101
"""
import os
import sys
import requests
import hmac
import hashlib
import json
import time
from pathlib import Path

# Load credentials from .env.local if available, or use system environment variables
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)

# Try multiple .env file locations (for AWS deployment)
env_files = [
    Path(project_root) / '.env.local',
    Path(project_root) / '.env',
    Path.home() / '.env.local',
    Path('/opt/automated-trading-platform/.env.local'),
    Path('/home/ubuntu/automated-trading-platform/.env.local'),
]

env_file = None
for env_path in env_files:
    if env_path.exists():
        env_file = env_path
        break

if env_file:
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                # Don't override if already set in environment
                if key not in os.environ:
                    os.environ[key] = value
    print(f"✅ Loaded credentials from {env_file}")
elif os.getenv("EXCHANGE_CUSTOM_API_KEY") and os.getenv("EXCHANGE_CUSTOM_API_SECRET"):
    print("✅ Using credentials from system environment variables")
else:
    print(f"⚠️  No .env file found, checking system environment...")

sys.path.insert(0, backend_dir)

def clean_secret(value: str) -> str:
    """Clean secret from env (remove quotes, whitespace)"""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    """Preview secret safely"""
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

def main():
    print("=" * 80)
    print("🔍 COMPREHENSIVE AUTHENTICATION DIAGNOSTIC - Error 40101")
    print("=" * 80)
    print()
    
    # 1. Check environment variables
    print("1️⃣  CHECKING ENVIRONMENT VARIABLES")
    print("-" * 80)
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    print(f"   EXCHANGE_CUSTOM_API_KEY: {preview_secret(api_key)} (len: {len(api_key)})")
    print(f"   EXCHANGE_CUSTOM_API_SECRET: {preview_secret(api_secret)} (len: {len(api_secret)})")
    print(f"   USE_CRYPTO_PROXY: {use_proxy}")
    print(f"   LIVE_TRADING: {live_trading}")
    
    if not api_key or not api_secret:
        print("   ❌ CRITICAL: API credentials not configured!")
        print("   💡 Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        return
    else:
        print("   ✅ API credentials are configured")
    
    # Check for common issues
    issues = []
    if api_key.startswith("'") or api_key.startswith('"'):
        issues.append("API key appears to have quotes - may need cleaning")
    if api_secret.startswith("'") or api_secret.startswith('"'):
        issues.append("API secret appears to have quotes - may need cleaning")
    if len(api_key) < 10:
        issues.append("API key seems too short")
    if len(api_secret) < 10:
        issues.append("API secret seems too short")
    
    if issues:
        print("   ⚠️  Potential issues detected:")
        for issue in issues:
            print(f"      - {issue}")
    print()
    
    # 2. Get outbound IP
    print("2️⃣  CHECKING OUTBOUND IP ADDRESS")
    print("-" * 80)
    try:
        egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        print(f"   📍 Outbound IP: {egress_ip}")
        print(f"   💡 This IP must be whitelisted in Crypto.com Exchange settings")
        print(f"   💡 Go to: https://exchange.crypto.com/ → Settings → API Keys")
        print(f"   💡 Edit your API key and add this IP to the whitelist")
    except Exception as e:
        print(f"   ❌ Could not determine outbound IP: {e}")
        egress_ip = None
    print()
    
    # 3. Test public API
    print("3️⃣  TESTING PUBLIC API (No Authentication Required)")
    print("-" * 80)
    try:
        response = requests.get(
            'https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT',
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'data' in data['result']:
                ticker = data['result']['data'][0]
                price = float(ticker.get("a", 0))
                print(f"   ✅ Public API works! BTC_USDT price: ${price:,.2f}")
            else:
                print(f"   ⚠️  Public API responded but unexpected format")
        else:
            print(f"   ❌ Public API failed: HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ Public API error: {e}")
    print()
    
    # 4. Test authentication with detailed diagnostics
    print("4️⃣  TESTING AUTHENTICATION (Detailed Diagnostics)")
    print("-" * 80)
    
    base_url = "https://api.crypto.com/exchange/v1"
    method = "private/user-balance"
    request_id = 1
    nonce_ms = int(time.time() * 1000)
    params = {}
    
    # Generate params string (sorted, no spaces)
    if params:
        params_str = json.dumps(params, separators=(',', ':'))
    else:
        params_str = ""
    
    # String to sign: method + id + api_key + params_str + nonce
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce_ms)
    
    # Generate signature
    signature = hmac.new(
        bytes(api_secret, 'utf-8'),
        msg=bytes(string_to_sign, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # Build request payload
    payload = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": params,
        "nonce": nonce_ms
    }
    
    # Add signature
    payload["sig"] = signature
    
    print(f"   Method: {method}")
    print(f"   Request ID: {request_id}")
    print(f"   Nonce: {nonce_ms}")
    print(f"   Params: {params}")
    print(f"   String to sign length: {len(string_to_sign)}")
    print(f"   Signature preview: {signature[:10]}...{signature[-10:]}")
    print()
    
    # Make request
    url = f"{base_url}/{method}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    print(f"   Sending request to: {url}")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        print(f"   Response status: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✅ Authentication successful!")
            try:
                data = response.json()
                print(f"   Response keys: {list(data.keys())}")
            except:
                print(f"   Response: {response.text[:200]}")
        elif response.status_code == 401:
            print("   ❌ Authentication failed (401)")
            try:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                print(f"   Error code: {error_code}")
                print(f"   Error message: {error_msg}")
                print()
                
                if error_code == 40101:
                    print("   🔍 ERROR 40101 DIAGNOSIS:")
                    print("   " + "=" * 76)
                    print("   This error typically means:")
                    print("   1. ❌ API key doesn't have 'Read' permission")
                    print("      → Go to Crypto.com Exchange → Settings → API Keys")
                    print("      → Edit your API key and enable 'Read' permission")
                    print()
                    print("   2. ❌ API key is disabled or suspended")
                    print("      → Check API key status in Crypto.com Exchange settings")
                    print("      → If suspended, contact Crypto.com support")
                    print()
                    print("   3. ❌ Invalid API key or secret")
                    print("      → Verify EXCHANGE_CUSTOM_API_KEY matches your API key")
                    print("      → Verify EXCHANGE_CUSTOM_API_SECRET matches your secret")
                    print("      → Check for extra spaces or quotes in environment variables")
                    print()
                    if egress_ip:
                        print(f"   4. ⚠️  IP address may not be whitelisted")
                        print(f"      → Your outbound IP is: {egress_ip}")
                        print(f"      → Add this IP to your API key whitelist in Crypto.com Exchange")
                    print()
                elif error_code == 40103:
                    print("   🔍 ERROR 40103 DIAGNOSIS:")
                    print("   " + "=" * 76)
                    print("   This error means: IP address not whitelisted")
                    if egress_ip:
                        print(f"   → Your outbound IP is: {egress_ip}")
                        print(f"   → Add this IP to your API key whitelist")
                        print(f"   → Go to: https://exchange.crypto.com/ → Settings → API Keys")
                        print(f"   → Edit your API key and add: {egress_ip}")
                    print()
            except Exception as e:
                print(f"   Could not parse error response: {e}")
                print(f"   Raw response: {response.text[:200]}")
        else:
            print(f"   ⚠️  Unexpected status code: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
    except Exception as e:
        print(f"   ❌ Request error: {e}")
    
    print()
    print("=" * 80)
    print("📋 SUMMARY & RECOMMENDATIONS")
    print("=" * 80)
    print()
    print("If authentication is failing with error 40101:")
    print()
    print("1. ✅ Verify API Key Permissions:")
    print("   - Go to https://exchange.crypto.com/ → Settings → API Keys")
    print("   - Edit your API key")
    print("   - Ensure 'Read' permission is ENABLED")
    print("   - Save changes")
    print()
    print("2. ✅ Verify API Key Status:")
    print("   - Check that API key is ENABLED (not disabled/suspended)")
    print("   - If suspended, contact Crypto.com support")
    print()
    if egress_ip:
        print(f"3. ✅ Verify IP Whitelist:")
        print(f"   - Your outbound IP: {egress_ip}")
        print(f"   - Add this IP to your API key whitelist")
        print(f"   - Remove any extra spaces")
        print(f"   - Wait a few seconds after adding")
        print()
    print("4. ✅ Verify Credentials:")
    print("   - Check EXCHANGE_CUSTOM_API_KEY matches your API key exactly")
    print("   - Check EXCHANGE_CUSTOM_API_SECRET matches your secret exactly")
    print("   - Remove any quotes or extra spaces")
    print("   - If needed, regenerate API key and update credentials")
    print()
    print("5. ✅ After making changes:")
    print("   - Restart the backend: docker compose restart backend-aws")
    print("   - Run this script again to verify")
    print()

if __name__ == "__main__":
    main()

