#!/usr/bin/env python3
"""Test multiple Crypto.com API methods to find which one works"""

import requests
import hmac
import hashlib
import time
import json

api_key = "HaTZb9EMihNmJUyNJ19frs"
api_secret = "cxakp_oGDfb6D6JW396cYGz8FHmg"

methods = [
    "private/get-account-summary",
    "private/get-account",
    "private/get-balance",
    "private/user-balance",
    "private/get-positions"
]

for method in methods:
    nonce = int(time.time() * 1000)
    request_id = 1
    params_str = ""
    string_to_sign = f"{method}{request_id}{api_key}{params_str}{nonce}"
    sig = hmac.new(bytes(str(api_secret), "utf-8"), bytes(string_to_sign, "utf-8"), hashlib.sha256).hexdigest()
    body = {"id": request_id, "method": method, "api_key": api_key, "sig": sig, "nonce": nonce, "params": {}}
    
    try:
        resp = requests.post(f"https://api.crypto.com/exchange/v1/{method}", json=body, headers={"Content-Type": "application/json"}, timeout=15)
        result = resp.json()
        if "result" in result:
            print(f"✅ SUCCESS with {method}!")
            print(json.dumps(result, indent=2))
            break
        else:
            code = result.get("code", "unknown")
            msg = result.get("message", "unknown")
            print(f"❌ {method}: {code} - {msg}")
    except Exception as e:
        print(f"⚠️  {method}: Error - {e}")


