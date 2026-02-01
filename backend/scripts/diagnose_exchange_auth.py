#!/usr/bin/env python3
"""
Minimal Crypto.com Exchange auth diagnostic: egress IP + one signed call.
No secrets printed. Safe to run in AWS container or locally.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any, Dict, Tuple

try:
    import requests
except ImportError:
    requests = None

METHOD = "private/user-balance"
DEFAULT_BASE = "https://api.crypto.com/exchange/v1"


def _clean_env_secret(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def _params_to_str(obj: Any, level: int = 0) -> str:
    MAX_LEVEL = 3
    if level >= MAX_LEVEL:
        return str(obj)
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, dict):
        out = ""
        for k in sorted(obj):
            out += str(k)
            v = obj.get(k)
            if v is None:
                out += "null"
            elif isinstance(v, bool):
                out += "true" if v else "false"
            elif isinstance(v, list):
                for sub in v:
                    out += _params_to_str(sub, level + 1)
            elif isinstance(v, dict):
                out += _params_to_str(v, level + 1)
            else:
                out += str(v)
        return out
    if isinstance(obj, list):
        return "".join(_params_to_str(x, level + 1) for x in obj)
    return str(obj)


def _sign(api_key: str, api_secret: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    request_id = 1
    nonce_ms = int(time.time() * 1000)
    ordered_params = dict(sorted((params or {}).items())) if params else {}
    params_str = _params_to_str(params, 0) if params else ""
    string_to_sign = method + str(request_id) + api_key + params_str + str(nonce_ms)
    sig = hmac.new(
        bytes(str(api_secret), "utf-8"),
        msg=bytes(string_to_sign, "utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": ordered_params,
        "nonce": nonce_ms,
        "sig": sig,
    }


def _sha256_12(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def get_public_ip() -> str | None:
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "ip" in data:
                return str(data["ip"]).strip()
    except Exception:
        pass
    try:
        r = requests.get("https://ifconfig.me/ip", timeout=5)
        if r.status_code == 200 and r.text:
            return r.text.strip()
    except Exception:
        pass
    return None


def main() -> int:
    # Credentials from env (never print)
    key_raw = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    sec_raw = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    key = _clean_env_secret(key_raw)
    sec = _clean_env_secret(sec_raw)

    print("KEY set:", bool(key))
    print("KEY len:", len(key))
    print("SEC set:", bool(sec))
    print("SEC len:", len(sec))

    ip = get_public_ip()
    if ip is None:
        print("Public egress IP: <unable to detect>")
    else:
        print("Public egress IP:", ip)

    if not requests:
        print("http_status: N/A")
        print("response code: N/A")
        print("message: requests module not installed")
        print("AUTH_OK: False")
        return 1

    if not key or not sec:
        print("http_status: N/A")
        print("response code: N/A")
        print("message: EXCHANGE_CUSTOM_API_KEY and/or EXCHANGE_CUSTOM_API_SECRET not set")
        print("AUTH_OK: False")
        return 1

    base_url = (os.getenv("EXCHANGE_CUSTOM_BASE_URL") or "").strip() or DEFAULT_BASE
    url = f"{base_url.rstrip('/')}/{METHOD}"
    payload = _sign(key, sec, METHOD, {})

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
    except Exception as e:
        print("http_status: N/A")
        print("response code: N/A")
        print("message:", str(e))
        print("AUTH_OK: False")
        return 1

    http_status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = {"code": None, "message": resp.text[:200] if resp.text else "non-JSON response"}

    code = body.get("code") if isinstance(body, dict) else None
    msg = body.get("message") if isinstance(body, dict) else None
    if msg is None and isinstance(body, dict):
        msg = body.get("result")  # some responses put message elsewhere
    msg_str = str(msg) if msg is not None else ""

    print("http_status:", http_status)
    print("response code:", code)
    print("message:", msg_str)
    auth_ok = http_status == 200 and (code == 0 or code is None)
    print("AUTH_OK:", auth_ok)

    if not auth_ok and code == 40101:
        print("Hint: Si 40101 y IP no está whitelisted -> whitelist issue (añade Public egress IP en Exchange API Keys).")

    return 0 if auth_ok else 1


if __name__ == "__main__":
    sys.exit(main())
