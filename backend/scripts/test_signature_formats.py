#!/usr/bin/env python3
"""
Test different signature formats to identify the correct one for Crypto.com Exchange API v1
This script tries multiple formats and reports which one works (if any).
"""

import os
import sys
import hmac
import hashlib
import time
import json
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load credentials
api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY") or os.getenv("CRYPTO_API_KEY", "").strip()
api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET") or os.getenv("CRYPTO_API_SECRET", "").strip()

if not api_key or not api_secret:
    print("❌ Missing API credentials")
    sys.exit(1)

method = "private/get-account-summary"
params = {}
nonce_ms = int(time.time() * 1000)

print("=" * 80)
print("TESTING MULTIPLE SIGNATURE FORMATS")
print("=" * 80)
print(f"Method: {method}")
print(f"Params: {params}")
print(f"Nonce: {nonce_ms}")
print()

# Format 1: method + id + api_key + nonce + json.dumps(params) where id = nonce
# This is what screenshot_test.py and demo_error_for_support.py use
print("📋 Format 1: method + id + api_key + nonce + json.dumps(params), id=nonce")
req_id_1 = nonce_ms
params_str_1 = json.dumps(params, separators=(",", ":"))  # "{}"
string_to_sign_1 = f"{method}{req_id_1}{api_key}{nonce_ms}{params_str_1}"
sig_1 = hmac.new(bytes(str(api_secret), 'utf-8'), bytes(string_to_sign_1, 'utf-8'), hashlib.sha256).hexdigest()
body_1 = {
    "id": req_id_1,
    "method": method,
    "api_key": api_key,
    "sig": sig_1,
    "nonce": nonce_ms,
    "params": params
}
print(f"   String to sign: {string_to_sign_1}")
print(f"   Signature: {sig_1[:20]}...")

try:
    resp_1 = requests.post(
        f"https://api.crypto.com/exchange/v1/{method}",
        json=body_1,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    result_1 = resp_1.json()
    print(f"   ✅ Status: {resp_1.status_code}")
    if "result" in result_1:
        print(f"   ✅✅✅ SUCCESS! Format 1 works!")
    elif result_1.get("code") == 10002:
        print(f"   ❌ Code: {result_1.get('code')}, Message: {result_1.get('message')}")
    else:
        print(f"   ⚠️  Response: {json.dumps(result_1, indent=2)}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# Format 2: method + "1" + api_key + "" + nonce, id=1 (current backend format)
print("📋 Format 2: method + '1' + api_key + '' + nonce, id=1 (current backend)")
req_id_2 = 1
params_str_2 = ""  # Empty string for empty params
string_to_sign_2 = f"{method}{req_id_2}{api_key}{params_str_2}{nonce_ms}"
sig_2 = hmac.new(bytes(str(api_secret), 'utf-8'), bytes(string_to_sign_2, 'utf-8'), hashlib.sha256).hexdigest()
body_2 = {
    "id": req_id_2,
    "method": method,
    "api_key": api_key,
    "sig": sig_2,
    "nonce": nonce_ms,
    "params": params
}
print(f"   String to sign: {string_to_sign_2}")
print(f"   Signature: {sig_2[:20]}...")

try:
    resp_2 = requests.post(
        f"https://api.crypto.com/exchange/v1/{method}",
        json=body_2,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    result_2 = resp_2.json()
    print(f"   ✅ Status: {resp_2.status_code}")
    if "result" in result_2:
        print(f"   ✅✅✅ SUCCESS! Format 2 works!")
    elif result_2.get("code") == 10002:
        print(f"   ❌ Code: {result_2.get('code')}, Message: {result_2.get('message')}")
    else:
        print(f"   ⚠️  Response: {json.dumps(result_2, indent=2)}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# Format 3: method + id + api_key + nonce + "", id=nonce (like Format 1 but empty string for params)
print("📋 Format 3: method + id + api_key + nonce + '', id=nonce")
req_id_3 = nonce_ms
params_str_3 = ""  # Empty string instead of "{}"
string_to_sign_3 = f"{method}{req_id_3}{api_key}{nonce_ms}{params_str_3}"
sig_3 = hmac.new(bytes(str(api_secret), 'utf-8'), bytes(string_to_sign_3, 'utf-8'), hashlib.sha256).hexdigest()
body_3 = {
    "id": req_id_3,
    "method": method,
    "api_key": api_key,
    "sig": sig_3,
    "nonce": nonce_ms,
    "params": params
}
print(f"   String to sign: {string_to_sign_3}")
print(f"   Signature: {sig_3[:20]}...")

try:
    resp_3 = requests.post(
        f"https://api.crypto.com/exchange/v1/{method}",
        json=body_3,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    result_3 = resp_3.json()
    print(f"   ✅ Status: {resp_3.status_code}")
    if "result" in result_3:
        print(f"   ✅✅✅ SUCCESS! Format 3 works!")
    elif result_3.get("code") == 10002:
        print(f"   ❌ Code: {result_3.get('code')}, Message: {result_3.get('message')}")
    else:
        print(f"   ⚠️  Response: {json.dumps(result_3, indent=2)}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

# Format 4: method + "1" + api_key + "{}" + nonce, id=1
print("📋 Format 4: method + '1' + api_key + '{}' + nonce, id=1")
req_id_4 = 1
params_str_4 = "{}"  # Explicit "{}" for empty params
string_to_sign_4 = f"{method}{req_id_4}{api_key}{params_str_4}{nonce_ms}"
sig_4 = hmac.new(bytes(str(api_secret), 'utf-8'), bytes(string_to_sign_4, 'utf-8'), hashlib.sha256).hexdigest()
body_4 = {
    "id": req_id_4,
    "method": method,
    "api_key": api_key,
    "sig": sig_4,
    "nonce": nonce_ms,
    "params": params
}
print(f"   String to sign: {string_to_sign_4}")
print(f"   Signature: {sig_4[:20]}...")

try:
    resp_4 = requests.post(
        f"https://api.crypto.com/exchange/v1/{method}",
        json=body_4,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    result_4 = resp_4.json()
    print(f"   ✅ Status: {resp_4.status_code}")
    if "result" in result_4:
        print(f"   ✅✅✅ SUCCESS! Format 4 works!")
    elif result_4.get("code") == 10002:
        print(f"   ❌ Code: {result_4.get('code')}, Message: {result_4.get('message')}")
    else:
        print(f"   ⚠️  Response: {json.dumps(result_4, indent=2)}")
except Exception as e:
    print(f"   ❌ Error: {e}")
print()

print("=" * 80)
print("SUMMARY: Check above for which format (if any) returned 'SUCCESS!'")
print("=" * 80)


