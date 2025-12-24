#!/usr/bin/env python3
"""
Deep authentication diagnostic - tests signature generation step by step
Helps identify exact issue with Crypto.com API authentication
"""
import os
import sys
import time
import hmac
import hashlib
import json
import requests
from pathlib import Path
from datetime import datetime, timezone

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
    print(f"⚠️  No .env file found in common locations, checking system environment...")
    if not os.getenv("EXCHANGE_CUSTOM_API_KEY"):
        print("   ⚠️  EXCHANGE_CUSTOM_API_KEY not set")
    if not os.getenv("EXCHANGE_CUSTOM_API_SECRET"):
        print("   ⚠️  EXCHANGE_CUSTOM_API_SECRET not set")

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

def _params_to_str(params: dict, level: int = 0) -> str:
    """Convert params to string following Crypto.com Exchange API v1 spec"""
    if not params:
        return ""
    
    # Sort keys alphabetically
    sorted_items = sorted(params.items())
    result = ""
    for key, value in sorted_items:
        if isinstance(value, dict):
            result += key + _params_to_str(value, level + 1)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    result += key + _params_to_str(item, level + 1)
                else:
                    result += key + str(item)
        else:
            result += key + str(value)
    return result

def test_signature_generation(api_key: str, api_secret: str, method: str, params: dict = None):
    """Test signature generation step by step"""
    print("\n" + "=" * 80)
    print("🔐 SIGNATURE GENERATION TEST")
    print("=" * 80)
    
    if params is None:
        params = {}
    
    # Step 1: Generate nonce
    nonce_ms = int(time.time() * 1000)
    request_id = 1
    
    print(f"\n1️⃣  INPUTS:")
    print(f"   Method: {method}")
    print(f"   Request ID: {request_id}")
    print(f"   API Key: {preview_secret(api_key)} (len: {len(api_key)})")
    print(f"   API Secret: {preview_secret(api_secret)} (len: {len(api_secret)})")
    print(f"   Nonce: {nonce_ms}")
    print(f"   Params: {params}")
    
    # Step 2: Build params string
    if params:
        params_str = _params_to_str(params, 0)
    else:
        params_str = ""
    
    print(f"\n2️⃣  PARAMS STRING:")
    print(f"   Params string: '{params_str}' (len: {len(params_str)})")
    print(f"   Is empty: {params_str == ''}")
    
    # Step 3: Build string to sign
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce_ms)
    
    print(f"\n3️⃣  STRING TO SIGN:")
    print(f"   Format: method + id + api_key + params_str + nonce")
    print(f"   Length: {len(string_to_sign)}")
    print(f"   Preview: {string_to_sign[:50]}...{string_to_sign[-30:]}")
    
    # Check for encoding issues
    try:
        string_bytes = bytes(string_to_sign, 'utf-8')
        print(f"   UTF-8 encoding: ✅ OK (len: {len(string_bytes)})")
    except Exception as e:
        print(f"   UTF-8 encoding: ❌ ERROR: {e}")
        return None
    
    # Step 4: Generate signature
    try:
        secret_bytes = bytes(str(api_secret), 'utf-8')
        signature = hmac.new(
            secret_bytes,
            msg=string_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        print(f"\n4️⃣  SIGNATURE:")
        print(f"   Secret encoding: ✅ OK (len: {len(secret_bytes)})")
        print(f"   Signature: {signature[:20]}...{signature[-20:]}")
        print(f"   Signature length: {len(signature)} (expected: 64)")
        
        if len(signature) != 64:
            print(f"   ⚠️  WARNING: Signature length is not 64 (expected for SHA256)")
        
    except Exception as e:
        print(f"   ❌ ERROR generating signature: {e}")
        return None
    
    # Step 5: Build payload
    if params:
        ordered_params = dict(sorted(params.items()))
    else:
        ordered_params = {}
    
    payload = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": ordered_params,
        "nonce": nonce_ms,
        "sig": signature
    }
    
    print(f"\n5️⃣  PAYLOAD:")
    safe_payload = dict(payload)
    safe_payload["api_key"] = preview_secret(api_key)
    safe_payload["sig"] = f"{signature[:10]}...{signature[-10:]}"
    print(f"   {json.dumps(safe_payload, indent=2)}")
    
    return payload, signature, string_to_sign

def test_authentication_request(payload: dict, method: str):
    """Test actual authentication request"""
    print("\n" + "=" * 80)
    print("🌐 AUTHENTICATION REQUEST TEST")
    print("=" * 80)
    
    base_url = "https://api.crypto.com/exchange/v1"
    url = f"{base_url}/{method}"
    
    print(f"\n📍 REQUEST DETAILS:")
    print(f"   URL: {url}")
    print(f"   Method: POST")
    print(f"   Content-Type: application/json")
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    try:
        print(f"\n📤 Sending request...")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        print(f"\n📥 RESPONSE:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Headers: {dict(response.headers)}")
        
        try:
            response_data = response.json()
            print(f"   Response: {json.dumps(response_data, indent=2)}")
            
            if response.status_code == 200:
                print(f"\n   ✅ SUCCESS! Authentication worked!")
                return True
            elif response.status_code == 401:
                error_code = response_data.get("code", 0)
                error_msg = response_data.get("message", "")
                print(f"\n   ❌ AUTHENTICATION FAILED")
                print(f"   Error Code: {error_code}")
                print(f"   Error Message: {error_msg}")
                
                if error_code == 40101:
                    print(f"\n   🔍 DIAGNOSIS for 40101:")
                    print(f"   This typically means:")
                    print(f"   1. API key doesn't have 'Read' permission")
                    print(f"   2. API key is disabled or suspended")
                    print(f"   3. Invalid API key or secret")
                    print(f"   4. Signature generation issue (less likely)")
                elif error_code == 40103:
                    print(f"\n   🔍 DIAGNOSIS for 40103:")
                    print(f"   IP address not whitelisted")
                
                return False
            else:
                print(f"\n   ⚠️  Unexpected status code")
                return False
                
        except json.JSONDecodeError:
            print(f"   Response text: {response.text[:500]}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"\n   ❌ REQUEST ERROR: {e}")
        return False

def main():
    print("=" * 80)
    print("🔍 DEEP AUTHENTICATION DIAGNOSTIC")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    
    # Get credentials
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    
    if not api_key or not api_secret:
        print("\n❌ ERROR: API credentials not configured!")
        print("   Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        return 1
    
    # Get outbound IP
    print("\n" + "=" * 80)
    print("🌐 NETWORK INFORMATION")
    print("=" * 80)
    try:
        egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
        print(f"   Outbound IP: {egress_ip}")
        print(f"   💡 This IP must be whitelisted in Crypto.com Exchange")
    except Exception as e:
        print(f"   ⚠️  Could not determine outbound IP: {e}")
        egress_ip = None
    
    # Test 1: private/user-balance (same as get_account_summary uses)
    method1 = "private/user-balance"
    params1 = {}
    
    print("\n" + "=" * 80)
    print("TEST 1: private/user-balance")
    print("=" * 80)
    
    result1 = test_signature_generation(api_key, api_secret, method1, params1)
    if result1:
        payload1, sig1, sts1 = result1
        success1 = test_authentication_request(payload1, method1)
    else:
        print("\n❌ Signature generation failed")
        success1 = False
    
    # Test 2: private/get-account-summary (alternative endpoint)
    method2 = "private/get-account-summary"
    params2 = {}
    
    print("\n" + "=" * 80)
    print("TEST 2: private/get-account-summary")
    print("=" * 80)
    
    result2 = test_signature_generation(api_key, api_secret, method2, params2)
    if result2:
        payload2, sig2, sts2 = result2
        success2 = test_authentication_request(payload2, method2)
    else:
        print("\n❌ Signature generation failed")
        success2 = False
    
    # Summary
    print("\n" + "=" * 80)
    print("📋 SUMMARY")
    print("=" * 80)
    
    if success1 or success2:
        print("✅ At least one endpoint works!")
        if success1:
            print("   ✅ private/user-balance: WORKING")
        if success2:
            print("   ✅ private/get-account-summary: WORKING")
    else:
        print("❌ All endpoints failed authentication")
        print("\n🔧 RECOMMENDED ACTIONS:")
        print("1. Verify API key has 'Read' permission enabled in Crypto.com Exchange")
        print("2. Check API key status is 'Enabled' (not Disabled/Suspended)")
        print("3. Verify API key and secret are correct (no extra spaces/quotes)")
        if egress_ip:
            print(f"4. Add IP {egress_ip} to API key whitelist")
        print("5. Wait 30-60 seconds after making changes")
        print("6. Regenerate API key if needed")
    
    return 0 if (success1 or success2) else 1

if __name__ == "__main__":
    sys.exit(main())

