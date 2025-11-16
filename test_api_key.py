import hmac
import hashlib
import time
import requests
import json

API_KEY = "z3HWF8m292zJKABkzfXWvQ"
SECRET_KEY = "cxakp_oGDfb6D6JW396cYGz8FHmg"

def test_api_key():
    """Test if the API key is valid by trying a simple request"""
    print("🔍 Testing API key validity...")
    
    # Test 1: Try to get account summary with minimal request
    nonce = int(time.time() * 1000)
    
    req = {
        "id": 1,
        "method": "private/get-account-summary",
        "api_key": API_KEY,
        "params": {},
        "nonce": nonce
    }
    
    # Generate signature
    param_str = ""
    payload_str = req['method'] + str(req['id']) + req['api_key'] + param_str + str(req['nonce'])
    
    signature = hmac.new(
        bytes(str(SECRET_KEY), 'utf-8'),
        msg=bytes(payload_str, 'utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    req['sig'] = signature
    
    print(f"📝 Request: {json.dumps(req, indent=2)}")
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    try:
        response = requests.post('https://api.crypto.com/exchange/v1/private', headers=headers, json=req, timeout=15)
        print(f"📡 Response status: {response.status_code}")
        print(f"📄 Response body: {response.text}")
        
        if response.status_code == 200:
            print("✅ API key is valid!")
            return True
        else:
            print("❌ API key authentication failed")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_public_api():
    """Test if we can access the public API"""
    print("\n🔍 Testing public API access...")
    
    try:
        response = requests.get('https://api.crypto.com/exchange/v1/public/get-tickers', timeout=10)
        print(f"📡 Public API status: {response.status_code}")
        if response.status_code == 200:
            print("✅ Public API is accessible")
            return True
        else:
            print("❌ Public API failed")
            return False
    except Exception as e:
        print(f"❌ Public API error: {e}")
        return False

def test_different_endpoints():
    """Test different possible endpoints"""
    print("\n🔍 Testing different endpoints...")
    
    endpoints = [
        "https://api.crypto.com/exchange/v1/private",
        "https://api.crypto.com/v2/private",
        "https://api.crypto.com/exchange/v1/private/get-account-summary"
    ]
    
    for endpoint in endpoints:
        print(f"Testing: {endpoint}")
        try:
            response = requests.post(endpoint, json={"test": "test"}, timeout=5)
            print(f"  Status: {response.status_code}")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    print("🚀 Testing Crypto.com API connectivity...")
    print(f"🔑 API Key: {API_KEY[:10]}...")
    print(f"🔐 Secret Key: {SECRET_KEY[:10]}...")
    
    # Test public API first
    public_works = test_public_api()
    
    if public_works:
        # Test private API
        private_works = test_api_key()
        
        if not private_works:
            # Test different endpoints
            test_different_endpoints()
    else:
        print("❌ Cannot access public API - check internet connection")

