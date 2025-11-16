#!/usr/bin/env python3
"""
Test script for Crypto.com API to capture error screenshot
Run this and take a screenshot of the output
"""

import requests
import hmac
import hashlib
import json
import time
from datetime import datetime

print("=" * 80)
print("CRYPTO.COM EXCHANGE API v1 - AUTHENTICATION TEST")
print("=" * 80)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
print()

# API Configuration
api_key = "z3HWF8m292zJKABkzfXWvQ"
api_secret = "cxakp_oGDfb6D6JW396cYGz8FHmg"
base_url = "https://api.crypto.com/exchange/v1"
method = "private/get-account-summary"

print(f"API Endpoint: {base_url}/{method}")
print(f"API Key: {api_key}")
print(f"Secret: {api_secret[:15]}..." + "*" * 20)
print()

# Generate signature
nonce = int(time.time() * 1000)
req_id = nonce
params = {}
params_str = json.dumps(params, separators=(",", ":"))

payload_string = f"{method}{req_id}{api_key}{nonce}{params_str}"
signature = hmac.new(
    api_secret.encode("utf-8"),
    payload_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

print(f"Request ID: {req_id}")
print(f"Nonce: {nonce}")
print(f"Payload for signature: {payload_string[:80]}...")
print(f"Signature: {signature}")
print()

# Build request body
request_body = {
    "id": req_id,
    "method": method,
    "api_key": api_key,
    "sig": signature,
    "nonce": nonce,
    "params": params
}

print("Request Body:")
print(json.dumps(request_body, indent=2))
print()

# Make the request
print("=" * 80)
print("SENDING REQUEST...")
print("=" * 80)
print()

try:
    response = requests.post(
        f"{base_url}/{method}",
        json=request_body,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    
    print(f"Status Code: {response.status_code}")
    print()
    print("Response Body:")
    print(response.text)
    print()
    
    if response.status_code == 200:
        print("✅ SUCCESS: Authentication successful!")
    else:
        print("❌ ERROR: Authentication failed!")
        print(f"Error: {response.text}")
        
except Exception as e:
    print(f"❌ EXCEPTION: {str(e)}")

print()
print("=" * 80)
print("Test completed at:", datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'))
print("=" * 80)

