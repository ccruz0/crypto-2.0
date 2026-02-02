#!/usr/bin/env python3
"""
Runtime verification of Crypto.com Exchange API credentials.

Runs INSIDE the backend container (or locally with env loaded) and prints:
- SAFE fingerprint of credentials actually loaded (key/secret prefix/suffix only)
- Source of creds (env vars), container hostname, UTC time, outbound IP
- LIVE_TRADING and USE_CRYPTO_PROXY
- Verification: public request, private user-balance, private get-open-orders (trade-permission check)
- PASS/FAIL summary with retries (3 attempts, small jitter)

Never prints full key or secret.
"""

import os
import sys
import random
import time
import socket
from datetime import datetime, timezone

# Add parent directory so app is importable (backend/ when local, /app when in container)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# After path is set, import app utilities and production client
from app.utils.credential_resolver import resolve_crypto_credentials
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.utils.http_client import http_get, http_post

try:
    from app.core.crypto_com_guardrail import is_local_execution_context, LOCAL_SKIP_PRIVATE_MESSAGE
except ImportError:
    def is_local_execution_context() -> bool:
        return (os.getenv("EXECUTION_CONTEXT", "LOCAL") or "LOCAL").strip().upper() == "LOCAL"
    LOCAL_SKIP_PRIVATE_MESSAGE = "LOCAL mode: private Crypto.com endpoints are AWS-only"

# Safe preview: never more than first N and last N chars
PREFIX_LEN = 4
SUFFIX_LEN = 4
SIG_PREVIEW_LEN = 10
MAX_RETRIES = 3
JITTER_MIN = 0.3
JITTER_MAX = 0.8


def _safe_preview(value: str, prefix_len: int = PREFIX_LEN, suffix_len: int = SUFFIX_LEN) -> str:
    if not value:
        return "<NOT_SET>"
    if len(value) <= prefix_len + suffix_len:
        return "<SET>"
    return f"{value[:prefix_len]}....{value[-suffix_len:]}"


def _sig_preview(sig: str) -> str:
    if not sig or len(sig) <= SIG_PREVIEW_LEN * 2:
        return sig[:20] + "..." if sig else "<none>"
    return f"{sig[:SIG_PREVIEW_LEN]}....{sig[-SIG_PREVIEW_LEN:]}"


def print_fingerprint():
    """Print SAFE fingerprint of credentials loaded at runtime."""
    print("\n" + "=" * 60)
    print("CREDENTIAL FINGERPRINT (runtime)")
    print("=" * 60)
    api_key, api_secret, used_pair_name, diagnostics = resolve_crypto_credentials()
    source = "env vars"
    pair_name = used_pair_name if used_pair_name else "EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET"
    print(f"  source:           {source} ({pair_name})")
    if api_key:
        print(f"  key_len:          {len(api_key)}")
        print(f"  key_prefix(4):   {api_key[:4] if len(api_key) >= 4 else api_key}")
        print(f"  key_suffix(4):   {api_key[-4:] if len(api_key) >= 4 else api_key}")
    else:
        print("  key_len:          0  key_prefix/suffix: <NOT_SET>")
    if api_secret:
        print(f"  secret_len:       {len(api_secret)}")
        print(f"  secret_prefix(4): {api_secret[:4] if len(api_secret) >= 4 else '<SET>'}")
        print(f"  secret_suffix(4): {api_secret[-4:] if len(api_secret) >= 4 else '<SET>'}")
    else:
        print("  secret_len:       0  secret_prefix/suffix: <NOT_SET>")
    print(f"  hostname:        {socket.gethostname()}")
    print(f"  utc_time:        {datetime.now(timezone.utc).isoformat()}")
    live = os.getenv("LIVE_TRADING", "false").lower() == "true"
    proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    print(f"  LIVE_TRADING:     {live}")
    print(f"  USE_CRYPTO_PROXY: {proxy}")
    # Outbound IP (use requests for script simplicity; ipify is allowlisted in egress when using http_get)
    try:
        r = http_get("https://api.ipify.org", timeout=5, calling_module="verify_exchange_creds_runtime")
        outbound_ip = r.text.strip()
    except Exception as e:
        outbound_ip = f"<error: {e}>"
    print(f"  outbound_ip:      {outbound_ip}")
    print("=" * 60)
    return api_key, api_secret


def run_public_ticker(base_url: str) -> dict:
    """One public request: get-tickers BTC_USDT (Exchange v1; get-ticker returns 404). No auth."""
    url = f"{base_url.rstrip('/')}/public/get-tickers?instrument_name=BTC_USDT"
    try:
        r = http_get(url, timeout=10, calling_module="verify_exchange_creds_runtime")
        try:
            body = r.json() if r.text else {}
        except Exception:
            body = {}
        code = body.get("code", 0)
        return {
            "ok": r.status_code == 200 and code == 0,
            "http_status": r.status_code,
            "code": code,
            "message": body.get("message", ""),
            "request_id": body.get("id"),
            "nonce": None,
            "sig_preview": None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "http_status": None, "code": None, "message": str(e)}


def run_private_request(client: CryptoComTradeClient, method: str, params: dict, label: str) -> dict:
    """One private request using production client (signed)."""
    try:
        payload = client.sign_request(method, params)
        url = f"{client.base_url}/{method}"
        r = http_post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
            calling_module="verify_exchange_creds_runtime",
        )
        try:
            body = r.json() if r.text else {}
        except Exception:
            body = {}
        code = body.get("code", 0)
        sig = payload.get("sig", "")
        return {
            "ok": r.status_code == 200 and code == 0,
            "http_status": r.status_code,
            "code": code,
            "message": body.get("message", ""),
            "request_id": payload.get("id"),
            "nonce": payload.get("nonce"),
            "sig_preview": _sig_preview(sig),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "http_status": None, "code": None, "message": str(e)}


def verify_with_retries(api_key: str, api_secret: str) -> tuple:
    """Run public, private user-balance, and private get-open-orders with retries. Return (all_ok, results)."""
    if not api_key or not api_secret:
        print("\nSKIP verification: no credentials loaded.")
        return False, []
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
    client = CryptoComTradeClient()
    results = []
    for attempt in range(1, MAX_RETRIES + 1):
        jitter = random.uniform(JITTER_MIN, JITTER_MAX)
        if attempt > 1:
            time.sleep(jitter)
        print(f"\n--- Attempt {attempt}/{MAX_RETRIES} ---")
        r_public = run_public_ticker(base_url)
        r_public["label"] = "public/get-tickers BTC_USDT"
        print(f"  {r_public['label']}: http={r_public.get('http_status')} code={r_public.get('code')} msg={r_public.get('message', r_public.get('error', ''))[:60]}")
        if not r_public.get("ok") and r_public.get("error"):
            results = [r_public]
            continue
        r_balance = run_private_request(client, "private/user-balance", {}, "private/user-balance")
        r_balance["label"] = "private/user-balance"
        print(f"  {r_balance['label']}: http={r_balance.get('http_status')} code={r_balance.get('code')} request_id={r_balance.get('request_id')} nonce={r_balance.get('nonce')} sig={r_balance.get('sig_preview')}")
        if not r_balance.get("ok"):
            if r_balance.get("code") == 40101:
                print("  (40101 = auth failure: wrong key/secret or missing Trade permission)")
            if r_balance.get("code") == 40103:
                print("  (40103 = IP not whitelisted; whitelist this host's outbound IP in Exchange)")
        r_orders = run_private_request(
            client, "private/get-open-orders", {"page": 0, "page_size": 10}, "private/get-open-orders"
        )
        r_orders["label"] = "private/get-open-orders (trade permission)"
        print(f"  {r_orders['label']}: http={r_orders.get('http_status')} code={r_orders.get('code')} request_id={r_orders.get('request_id')} nonce={r_orders.get('nonce')} sig={r_orders.get('sig_preview')}")
        if not r_orders.get("ok") and r_orders.get("code") == 40101:
            print("  (40101 on get-open-orders often means 'Trade' permission not enabled on API key)")
        results = [r_public, r_balance, r_orders]
        if all(r.get("ok") for r in results):
            break
    all_ok = all(r.get("ok") for r in results)
    return all_ok, results


def main():
    print("\nCrypto.com Exchange API – runtime credential verification")
    api_key, api_secret = print_fingerprint()
    if is_local_execution_context():
        base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
        r_public = run_public_ticker(base_url)
        r_public["label"] = "public/get-tickers BTC_USDT"
        print(f"\n  {r_public['label']}: http={r_public.get('http_status')} code={r_public.get('code')}")
        print("\n" + LOCAL_SKIP_PRIVATE_MESSAGE)
        print("=" * 60)
        return 0
    print("\nVerification (public + private user-balance + private get-open-orders)")
    all_ok, results = verify_with_retries(api_key, api_secret)
    print("\n" + "=" * 60)
    if all_ok:
        print("PASS: All checks succeeded.")
    else:
        print("FAIL: One or more checks failed.")
        for r in results:
            if not r.get("ok"):
                print(f"  - {r.get('label', '?')}: http={r.get('http_status')} code={r.get('code')} {r.get('message', r.get('error', ''))[:80]}")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
