#!/usr/bin/env python3
"""
Test script for Crypto.com Signer Proxy
"""

import requests
import json

# Configuration
PROXY_URL = "http://127.0.0.1:9000"
TOKEN = "CRYPTO_PROXY_SECURE_TOKEN_2024"

def test_proxy():
    """Test the Crypto.com Signer Proxy"""
    print("🔍 Testing Crypto.com Signer Proxy")
    print("=" * 40)
    
    # Test health endpoint
    try:
        response = requests.get(f"{PROXY_URL}/health", timeout=5)
        print(f"✅ Health check: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return
    
    # Test proxy endpoint
    try:
        headers = {
            "X-Proxy-Token": TOKEN,
            "Content-Type": "application/json"
        }
        
        data = {
            "method": "private/get-account-summary",
            "params": {}
        }
        
        print(f"\n📡 Testing proxy endpoint...")
        print(f"URL: {PROXY_URL}/proxy/private")
        print(f"Headers: {headers}")
        print(f"Data: {data}")
        
        response = requests.post(
            f"{PROXY_URL}/proxy/private",
            json=data,
            headers=headers,
            timeout=15
        )
        
        print(f"\n📊 Response:")
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        try:
            result = response.json()
            print(f"Body: {json.dumps(result, indent=2)}")
            
            if result.get("status") == 200:
                print("✅ SUCCESS: Proxy working correctly!")
            else:
                print(f"⚠️  API returned status {result.get('status')}")
                print(f"Response: {result.get('body')}")
                
        except json.JSONDecodeError:
            print(f"Raw response: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ Request timeout")
    except requests.exceptions.ConnectionError:
        print("❌ Connection error - is the proxy running?")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_proxy()

