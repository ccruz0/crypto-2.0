#!/usr/bin/env python3
"""
Direct API test script for Crypto.com Exchange
Tests authentication and provides detailed diagnostic information
"""
import os
import sys
import requests
import hmac
import hashlib
import json
import time
from pathlib import Path

# Load .env.local if available
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)

env_files = [
    Path(project_root) / '.env.local',
    Path(project_root) / '.env',
    Path('/opt/automated-trading-platform/.env.local'),
    Path('/home/ubuntu/crypto-2.0/.env.local'),
]

for env_path in env_files:
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key not in os.environ:
                        os.environ[key] = value
        break

def clean_secret(value: str) -> str:
    """Clean secret from env"""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def generate_signature(method: str, params: dict, api_key: str, api_secret: str, request_id: int, nonce: int) -> str:
    """Generate HMAC-SHA256 signature for Crypto.com API"""
    # Convert params to string (sorted keys, no spaces)
    params_str = json.dumps(params, separators=(',', ':')) if params else '{}'
    
    # String to sign: method + id + api_key + params_str + nonce
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce)
    
    # Generate signature
    signature = hmac.new(
        bytes(api_secret, 'utf-8'),
        msg=bytes(string_to_sign, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    return signature

def test_api_call(method: str, params: dict = None):
    """Test a direct API call to Crypto.com"""
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
    
    if not api_key or not api_secret:
        print("❌ API credentials not configured")
        return None
    
    params = params or {}
    request_id = int(time.time() * 1000)
    nonce = int(time.time() * 1000)
    
    # Generate signature
    signature = generate_signature(method, params, api_key, api_secret, request_id, nonce)
    
    # Build payload
    payload = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": params,
        "nonce": nonce,
        "sig": signature
    }
    
    # Make request
    url = f"{base_url}/{method}"
    print(f"\n📡 Testing: {method}")
    print(f"   URL: {url}")
    print(f"   Request ID: {request_id}")
    print(f"   Nonce: {nonce}")
    
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ SUCCESS")
            if "result" in result:
                print(f"   Response keys: {list(result.keys())}")
            return result
        else:
            error_data = response.json()
            error_code = error_data.get("code", 0)
            error_msg = error_data.get("message", "")
            print(f"   ❌ ERROR {error_code}: {error_msg}")
            
            if error_code == 40101:
                print(f"\n   🔍 DIAGNOSIS for 40101:")
                print(f"      • Verify API key matches Crypto.com Exchange exactly")
                print(f"      • Check API key has 'Read' permission enabled")
                print(f"      • Verify API key is Active (not Disabled/Suspended)")
                print(f"      • Ensure API secret matches exactly")
            elif error_code == 40103:
                print(f"\n   🔍 DIAGNOSIS for 40103:")
                print(f"      • IP address not whitelisted")
                print(f"      • Add your server IP to Crypto.com Exchange API key whitelist")
            
            return error_data
            
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Request failed: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        return None

def main():
    print("=" * 70)
    print("🧪 DIRECT CRYPTO.COM API TEST")
    print("=" * 70)
    
    # Check credentials
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    
    if not api_key or not api_secret:
        print("\n❌ API credentials not configured")
        print("   Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        return
    
    print(f"\n✅ Credentials loaded")
    print(f"   API Key: {api_key[:4]}....{api_key[-4:]}")
    print(f"   API Secret: {'*' * min(len(api_secret), 20)}...")
    
    # Get outbound IP
    try:
        egress_ip = requests.get("https://api.ipify.org", timeout=3).text.strip()
        print(f"\n🌐 Outbound IP: {egress_ip}")
        print(f"   💡 Make sure this IP is whitelisted in Crypto.com Exchange")
    except:
        print("\n⚠️  Could not determine outbound IP")
    
    # Test public endpoint first
    print("\n" + "=" * 70)
    print("1️⃣  TESTING PUBLIC ENDPOINT")
    print("=" * 70)
    try:
        response = requests.get("https://api.crypto.com/exchange/v1/public/get-tickers", timeout=10)
        if response.status_code == 200:
            print("✅ Public API is accessible")
        else:
            print(f"⚠️  Public API returned status {response.status_code}")
    except Exception as e:
        print(f"❌ Public API test failed: {e}")
        return
    
    # Test private endpoint
    print("\n" + "=" * 70)
    print("2️⃣  TESTING PRIVATE ENDPOINT (Authentication)")
    print("=" * 70)
    result = test_api_call("private/user-balance", {})
    
    if result and "code" in result:
        error_code = result.get("code")
        if error_code == 40101:
            print("\n" + "=" * 70)
            print("🔧 RECOMMENDED ACTIONS")
            print("=" * 70)
            print("1. Go to https://exchange.crypto.com/")
            print("2. Settings → API Keys")
            print("3. Edit your API key")
            print("4. Enable 'Read' permission ✅")
            print("5. Verify API key status is 'Active'")
            print("6. Check API key and secret match exactly")
            print("7. Restart backend: docker compose restart backend")
        elif error_code == 40103:
            print("\n" + "=" * 70)
            print("🔧 RECOMMENDED ACTIONS")
            print("=" * 70)
            print(f"1. Add IP {egress_ip} to Crypto.com Exchange API key whitelist")
            print("2. Go to https://exchange.crypto.com/")
            print("3. Settings → API Keys")
            print("4. Edit your API key")
            print("5. Add IP to whitelist")
            print("6. Restart backend: docker compose restart backend")
    elif result and "result" in result:
        print("\n✅ Authentication successful!")
        data = result.get("result", {}).get("data", [])
        if data:
            print(f"\n📊 Account data received ({len(data)} entries)")

if __name__ == "__main__":
    main()
















