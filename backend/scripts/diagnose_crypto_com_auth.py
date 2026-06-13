#!/usr/bin/env python3
"""
Read-only Crypto.com Exchange API authentication diagnostic.

Never prints full API key or secret. Safe to run inside backend-aws container:

  python /app/scripts/diagnose_crypto_com_auth.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.crypto_com_guardrail import AUTH_40101_MESSAGE, get_execution_context
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
from app.utils.credential_resolver import resolve_crypto_credentials
from app.utils.http_client import http_get, http_post

PREFIX_LEN = 4
SUFFIX_LEN = 4


def _mask(value: str) -> str:
    if not value:
        return "<NOT_SET>"
    if len(value) <= PREFIX_LEN + SUFFIX_LEN:
        return "<SET>"
    return f"{value[:PREFIX_LEN]}....{value[-SUFFIX_LEN:]}"


def _outbound_ip() -> str:
    try:
        return http_get("https://api.ipify.org", timeout=5, calling_module="diagnose_crypto_com_auth").text.strip()
    except Exception as exc:
        return f"<error: {type(exc).__name__}>"


def _classify_failure(http_status: int, body: dict[str, Any]) -> str:
    code = body.get("code")
    if http_status == 0:
        return "network_blocked"
    if not resolve_crypto_credentials()[0]:
        return "missing_credentials"
    if code == 40103:
        return "ip_whitelist_rejected"
    if code == 40101:
        return "auth_rejected"
    if http_status >= 400:
        return "api_error"
    return "unknown"


def _private_probe(
    client: CryptoComTradeClient,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = params or {}
    payload = client.sign_request(method, params, _suppress_log=True)
    nonce = payload.get("nonce")
    request_id = payload.get("id")
    url = f"{client.base_url}/{method}"
    started = time.time()
    try:
        response = http_post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=12,
            calling_module="diagnose_crypto_com_auth",
        )
        elapsed_ms = int((time.time() - started) * 1000)
        try:
            body = response.json()
        except Exception:
            body = {"raw": (response.text or "")[:200]}
        code = body.get("code")
        return {
            "method": method,
            "http_status": response.status_code,
            "code": code,
            "message": body.get("message"),
            "elapsed_ms": elapsed_ms,
            "nonce": nonce,
            "request_id": request_id,
            "classification": _classify_failure(response.status_code, body if isinstance(body, dict) else {}),
            "sync_status": "ok" if response.status_code == 200 and code in (0, None) else "failed_auth",
        }
    except Exception as exc:
        return {
            "method": method,
            "http_status": 0,
            "code": None,
            "message": str(exc),
            "elapsed_ms": int((time.time() - started) * 1000),
            "nonce": nonce,
            "request_id": request_id,
            "classification": "network_blocked",
            "sync_status": "api_error",
        }


def _public_probe(base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/public/get-tickers?instrument_name=BTC_USDT"
    started = time.time()
    try:
        response = http_get(url, timeout=10, calling_module="diagnose_crypto_com_auth")
        elapsed_ms = int((time.time() - started) * 1000)
        body = response.json()
        return {
            "method": "public/get-tickers",
            "http_status": response.status_code,
            "code": body.get("code"),
            "message": body.get("message"),
            "elapsed_ms": elapsed_ms,
            "classification": "ok" if response.status_code == 200 else "api_error",
        }
    except Exception as exc:
        return {
            "method": "public/get-tickers",
            "http_status": 0,
            "code": None,
            "message": str(exc),
            "elapsed_ms": int((time.time() - started) * 1000),
            "classification": "network_blocked",
        }


def _root_cause_assessment(results: list[dict[str, Any]], *, outbound_ip: str, docs_elastic_ip: str) -> list[str]:
    notes: list[str] = []
    public_ok = any(r.get("method", "").startswith("public/") and r.get("http_status") == 200 for r in results)
    private = [r for r in results if r.get("method", "").startswith("private/")]
    private_ok = any(r.get("http_status") == 200 and r.get("code") in (0, None) for r in private)

    if not resolve_crypto_credentials()[0]:
        notes.append("Credentials missing from environment/runtime.env.")
        return notes

    if public_ok and not private_ok:
        notes.append("Public API works but all private endpoints failed — signing reaches Crypto.com but auth is rejected.")
        codes = {r.get("code") for r in private}
        if 40103 in codes:
            notes.append("40103 indicates IP whitelist rejection; whitelist outbound IP in Crypto.com API key settings.")
        if 40101 in codes:
            notes.append(
                "40101 usually means invalid/rotated API key or secret, missing Read/Trade permission, "
                "or IP not allowlisted (Crypto.com sometimes returns 40101 instead of 40103)."
            )
            notes.append(f"Documented Elastic IP {docs_elastic_ip} differs from current outbound {outbound_ip}.")
        notes.append("Signing implementation uses method+id+api_key+sorted_params+nonce HMAC-SHA256 per Exchange API v1.")
        notes.append(f"Endpoint base URL: {os.getenv('EXCHANGE_CUSTOM_BASE_URL', 'https://api.crypto.com/exchange/v1')}")
    elif not public_ok:
        notes.append("Public endpoint failed — check network egress/DNS before investigating credentials.")
    elif private_ok:
        notes.append("Private authentication succeeded; sync failures elsewhere are not credential-related.")

    return notes


def main() -> int:
    api_key, api_secret, used_pair, diagnostics = resolve_crypto_credentials()
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL") or os.getenv("CRYPTO_REST_BASE") or "https://api.crypto.com/exchange/v1"
    docs_elastic_ip = os.getenv("AWS_INSTANCE_IP") or "47.130.143.159"
    outbound_ip = _outbound_ip()
    now = datetime.now(timezone.utc)
    nonce_sample = int(time.time() * 1000)

    print("=" * 72)
    print("CRYPTO.COM AUTH DIAGNOSTIC (read-only)")
    print("=" * 72)
    print(f"  utc_time:           {now.isoformat()}")
    print(f"  hostname:           {socket.gethostname()}")
    print(f"  execution_context:  {get_execution_context()}")
    print(f"  base_url:           {base_url}")
    print(f"  outbound_ip:        {outbound_ip}")
    print(f"  documented_eip:     {docs_elastic_ip}")
    print(f"  LIVE_TRADING:       {os.getenv('LIVE_TRADING', 'false')}")
    print(f"  USE_CRYPTO_PROXY:   {os.getenv('USE_CRYPTO_PROXY', 'false')}")
    print()
    print("CREDENTIALS (masked)")
    print(f"  pair:               {used_pair or 'EXCHANGE_CUSTOM_API_KEY / EXCHANGE_CUSTOM_API_SECRET'}")
    print(f"  key_len:            {len(api_key or '')}")
    print(f"  key_masked:         {_mask(api_key or '')}")
    print(f"  secret_len:         {len(api_secret or '')}")
    print(f"  secret_masked:      {_mask(api_secret or '')}")
    print(f"  key_present:        {diagnostics.get('EXCHANGE_CUSTOM_API_KEY_PRESENT')}")
    print(f"  secret_present:     {diagnostics.get('EXCHANGE_CUSTOM_API_SECRET_PRESENT')}")
    print(f"  sample_nonce_ms:    {nonce_sample}")
    print()

    if not api_key or not api_secret:
        print("RESULT: missing_credentials — set EXCHANGE_CUSTOM_API_KEY/SECRET via approved secret mechanism.")
        return 2

    client = CryptoComTradeClient()
    client.api_key = api_key
    client.api_secret = api_secret
    client.base_url = base_url.rstrip("/")

    probes = [
        _public_probe(base_url),
        _private_probe(client, "private/user-balance", {}),
        _private_probe(client, "private/get-open-orders", {"page": 0, "page_size": 1}),
        _private_probe(client, "private/get-trigger-orders", {"page": 0, "page_size": 1}),
    ]

    print("ENDPOINT PROBES")
    print("-" * 72)
    for row in probes:
        print(
            f"  {row['method']}: http={row.get('http_status')} code={row.get('code')} "
            f"class={row.get('classification')} sync_status={row.get('sync_status', 'n/a')} "
            f"msg={row.get('message')!r} elapsed_ms={row.get('elapsed_ms')}"
        )
        if row.get("nonce") is not None:
            print(f"    nonce={row.get('nonce')} request_id={row.get('request_id')}")

    print()
    print("ROOT CAUSE ASSESSMENT")
    print("-" * 72)
    for line in _root_cause_assessment(probes, outbound_ip=outbound_ip, docs_elastic_ip=docs_elastic_ip):
        print(f"  - {line}")
    if any(r.get("code") == 40101 for r in probes):
        print(f"  - {AUTH_40101_MESSAGE}")

    private_ok = any(
        r.get("method", "").startswith("private/")
        and r.get("http_status") == 200
        and r.get("code") in (0, None)
        for r in probes
    )
    print()
    print("SUMMARY:", "PASS" if private_ok else "FAIL")
    return 0 if private_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
