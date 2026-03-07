#!/usr/bin/env python3
"""
Raw API test for private/get-order-history (default + spot_margin=MARGIN) and private/get-trades from EC2.
Uses the same params-to-string signing as the backend (Crypto.com Exchange v1).
Run inside backend container: python scripts/run_order_history_raw_test.py
Does not print secrets. If default returns 0 and spot_margin=MARGIN returns data, orders are margin (Cross).
"""
import os
import sys
import time
import hmac
import hashlib
import requests

# Params-to-string for signature (must match backend crypto_com_trade._params_to_str)
def _params_to_str(obj, level: int = 0) -> str:
    MAX_LEVEL = 3
    if level >= MAX_LEVEL:
        return str(obj)
    if not obj:
        return ""
    out = ""
    for key in sorted(obj):
        out += key
        val = obj[key]
        if val is None:
            out += "null"
        elif isinstance(val, list):
            for sub in val:
                if isinstance(sub, dict):
                    out += _params_to_str(sub, level + 1)
                else:
                    out += str(sub)
        elif isinstance(val, dict):
            out += _params_to_str(val, level + 1)
        else:
            out += str(val)
    return out


def main():
    base = os.environ.get("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1").rstrip("/")
    key = os.environ.get("EXCHANGE_CUSTOM_API_KEY")
    sec = os.environ.get("EXCHANGE_CUSTOM_API_SECRET")
    if not key or not sec:
        print("Missing EXCHANGE_CUSTOM_API_KEY or EXCHANGE_CUSTOM_API_SECRET")
        sys.exit(1)
    sec_b = sec.encode() if isinstance(sec, str) else sec
    request_id = 1

    def call(method: str, params: dict, label: str = ""):
        nonce_ms = int(time.time() * 1000)
        params_str = _params_to_str(params, 0) if params else ""
        string_to_sign = f"{method}{request_id}{key}{params_str}{nonce_ms}"
        sig = hmac.new(sec_b, string_to_sign.encode(), hashlib.sha256).hexdigest()
        payload = {
            "id": request_id,
            "method": method,
            "api_key": key,
            "params": params or {},
            "nonce": nonce_ms,
            "sig": sig,
        }
        r = requests.post(f"{base}/{method}", json=payload, timeout=20)
        code, data_len, first_keys = None, None, None
        try:
            j = r.json()
            code = j.get("code")
            result = j.get("result") or {}
            data = result.get("data") if isinstance(result, dict) else None
            if isinstance(data, list):
                data_len = len(data)
                if data and isinstance(data[0], dict):
                    first_keys = list(data[0].keys())
        except Exception:
            pass
        print(f"endpoint={method} {label}")
        print(f"  http={r.status_code} code={code} data_len={data_len} first_order_keys={first_keys}")
        print(r.text[:800])
        print()

    call("private/get-order-history", {"limit": 20}, "(default/spot)")
    time.sleep(1)
    call("private/get-order-history", {"limit": 20, "spot_margin": "MARGIN"}, "(spot_margin=MARGIN)")
    time.sleep(1)
    call("private/get-trades", {"limit": 20}, "")


if __name__ == "__main__":
    main()
