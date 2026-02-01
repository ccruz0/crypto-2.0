#!/usr/bin/env python3
"""
Simple Crypto.com Exchange auth verification: public get-tickers + private user-balance.

Uses exact same signing + request path as production (CryptoComTradeClient, resolve_crypto_credentials).
Prints base URL, path, method, params format; http status, API code/message, request_id, nonce, sig preview.
Retries 3 times with jitter. Never prints full key/secret.
"""

import os
import sys
import random
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.credential_resolver import resolve_crypto_credentials
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.services.brokers.crypto_com_constants import REST_BASE
from app.utils.http_client import http_get, http_post

try:
    from app.core.crypto_com_guardrail import is_local_execution_context, LOCAL_SKIP_PRIVATE_MESSAGE
except ImportError:
    def is_local_execution_context() -> bool:
        return (os.getenv("EXECUTION_CONTEXT", "LOCAL") or "LOCAL").strip().upper() == "LOCAL"
    LOCAL_SKIP_PRIVATE_MESSAGE = "LOCAL mode: private Crypto.com endpoints are AWS-only"

SIG_PREVIEW_LEN = 10
MAX_RETRIES = 3
JITTER_MIN = 0.3
JITTER_MAX = 0.8


def _sig_preview(sig: str) -> str:
    if not sig or len(sig) <= SIG_PREVIEW_LEN * 2:
        return (sig[:20] + "...") if sig else "<none>"
    return f"{sig[:SIG_PREVIEW_LEN]}....{sig[-SIG_PREVIEW_LEN:]}"


def run_public_tickers() -> dict:
    """Public: GET get-tickers (same as production routes_crypto). No auth. Query: none."""
    base_url = REST_BASE
    path = "/public/get-tickers"
    url = f"{base_url.rstrip('/')}{path}"
    try:
        r = http_get(url, timeout=10, calling_module="verify_crypto_auth_simple")
        try:
            body = r.json() if r.text else {}
        except Exception:
            body = {}
        return {
            "ok": r.status_code == 200 and body.get("code", 0) == 0,
            "base_url": base_url,
            "path": path,
            "method": "GET",
            "params_format": "querystring: none",
            "http_status": r.status_code,
            "code": body.get("code", 0),
            "message": body.get("message", ""),
            "request_id": body.get("id"),
            "nonce": None,
            "sig_preview": None,
        }
    except Exception as e:
        return {
            "ok": False, "base_url": base_url, "path": path, "method": "GET", "params_format": "querystring: none",
            "http_status": None, "code": None, "message": str(e), "request_id": None, "nonce": None, "sig_preview": None,
        }


def run_private_user_balance(client: CryptoComTradeClient) -> dict:
    """Private: POST user-balance. Auth: signed JSON body. Unique request_id per call."""
    method = "private/user-balance"
    request_id = int(time.time() * 1000)
    try:
        payload = client.sign_request(method, {}, _request_id_override=request_id)
        if isinstance(payload, dict) and payload.get("skipped"):
            return {
                "ok": False,
                "base_url": client.base_url,
                "path": f"/{method}",
                "method": "POST",
                "params_format": "JSON body",
                "http_status": None,
                "code": None,
                "message": payload.get("reason", LOCAL_SKIP_PRIVATE_MESSAGE),
                "request_id": payload.get("label"),
                "nonce": None,
                "sig_preview": None,
            }
        url = f"{client.base_url}/{method}"
        r = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="verify_crypto_auth_simple")
        try:
            body = r.json() if r.text else {}
        except Exception:
            body = {}
        sig = payload.get("sig", "")
        return {
            "ok": r.status_code == 200 and body.get("code", 0) == 0,
            "base_url": client.base_url,
            "path": f"/{method}",
            "method": "POST",
            "params_format": "JSON body",
            "http_status": r.status_code,
            "code": body.get("code", 0),
            "message": body.get("message", ""),
            "request_id": payload.get("id"),
            "nonce": payload.get("nonce"),
            "sig_preview": _sig_preview(sig),
        }
    except Exception as e:
        return {
            "ok": False, "base_url": getattr(client, "base_url", ""), "path": f"/{method}", "method": "POST", "params_format": "JSON body",
            "http_status": None, "code": None, "message": str(e), "request_id": request_id, "nonce": None, "sig_preview": None,
        }


def main():
    if is_local_execution_context():
        print("base_url (public):", REST_BASE)
        r_pub = run_public_tickers()
        print(f"  public/get-tickers: http={r_pub.get('http_status')} code={r_pub.get('code')}")
        print(LOCAL_SKIP_PRIVATE_MESSAGE)
        sys.exit(0)
    api_key, api_secret, _, _ = resolve_crypto_credentials()
    if not api_key or not api_secret:
        print("base_url (public):", REST_BASE)
        r_pub = run_public_tickers()
        print(f"  public/get-tickers: http={r_pub.get('http_status')} code={r_pub.get('code')} (no creds -> skipping private)")
        print("FAIL: no credentials (run fingerprint_creds.py to see env)")
        sys.exit(1)
    client = CryptoComTradeClient()
    print("base_url (private):", client.base_url)
    print("base_url (public):", REST_BASE)
    results = []
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
        print(f"\n--- Attempt {attempt}/{MAX_RETRIES} ---")
        r_pub = run_public_tickers()
        r_pub["label"] = "public/get-tickers"
        print(f"  {r_pub['label']}: base={r_pub.get('base_url')} path={r_pub.get('path')} method={r_pub.get('method')} params={r_pub.get('params_format')}")
        print(f"    -> http={r_pub.get('http_status')} code={r_pub.get('code')} message={r_pub.get('message', '')[:50]} request_id={r_pub.get('request_id')}")
        r_priv = run_private_user_balance(client)
        r_priv["label"] = "private/user-balance"
        print(f"  {r_priv['label']}: base={r_priv.get('base_url')} path={r_priv.get('path')} method={r_priv.get('method')} params={r_priv.get('params_format')}")
        print(f"    -> http={r_priv.get('http_status')} code={r_priv.get('code')} message={r_priv.get('message', '')[:50]} request_id={r_priv.get('request_id')} nonce={r_priv.get('nonce')} sig={r_priv.get('sig_preview')}")
        results = [r_pub, r_priv]
        if all(r.get("ok") for r in results):
            break
    ok = all(r.get("ok") for r in results)
    print("\n" + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
