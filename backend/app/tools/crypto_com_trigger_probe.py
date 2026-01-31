"""
Crypto.com Exchange trigger order brute-force probe.

Purpose
-------
Systematically brute-force request payload variations for conditional orders
(STOP_* / TAKE_PROFIT_*) against the live Crypto.com Exchange API and capture
the exchange's real behavior (e.g. API_DISABLED 140001).

Constraints (intentional)
-------------------------
- Sends REAL authenticated requests
- Does NOT reuse existing order placement logic (standalone signing + request)
- Never throws on failure; never returns early on errors
- No retries; no "fixing" responses
- Logs every attempt as JSONL to /tmp/crypto_trigger_probe_<correlation_id>.jsonl
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import itertools
import json
import os
import sys
import time
import traceback
import uuid
from decimal import Decimal
from decimal import ROUND_DOWN
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


DEFAULT_BASE_URL = "https://api.crypto.com/exchange/v1"
METHOD_CREATE_ORDER = "private/create-order"  # conditional/trigger order creation
METHOD_GET_INSTRUMENTS = "public/get-instruments"
METHOD_GET_ORDER_DETAIL = "private/get-order-detail"
METHOD_ADVANCED_GET_ORDER_DETAIL = "private/advanced/get-order-detail"
METHOD_GET_OPEN_ORDERS = "private/get-open-orders"
METHOD_GET_ORDER_HISTORY = "private/get-order-history"
METHOD_CANCEL_ORDER = "private/cancel-order"
METHOD_ADVANCED_CANCEL_ORDER = "private/advanced/cancel-order"
METHOD_CANCEL_ALL_ORDERS = "private/cancel-all-orders"
METHOD_ADVANCED_CANCEL_ALL_ORDERS = "private/advanced/cancel-all-orders"


def _iso_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat()


def _json_default(o: Any) -> Any:
    # Never "normalize payloads" for correctness; this is only to ensure JSON serialization.
    if isinstance(o, Decimal):
        # Keep exact string representation.
        return str(o)
    return str(o)


def _append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    try:
        line = json.dumps(obj, ensure_ascii=False, default=_json_default)
    except Exception:
        # As a last resort, log something rather than failing to write.
        line = json.dumps({"ts": _iso_now(), "serialization_error": traceback.format_exc(), "raw_obj": repr(obj)})
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # No raising (ever). If we can't write, we still continue.
        pass


def _clean_env_secret(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v


def _params_to_str(obj: Any, level: int = 0) -> str:
    """
    Convert params to signature string following Crypto.com Exchange v1 behavior:
    alphabetically sorted keys, concatenated key+value without separators.

    This is reimplemented locally (standalone) to avoid reusing existing order logic.
    """
    MAX_LEVEL = 3
    if level >= MAX_LEVEL:
        return str(obj)
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        # Crypto.com signing expects JSON-style boolean literals.
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
                    if isinstance(sub, dict):
                        out += _params_to_str(sub, level + 1)
                    else:
                        out += _params_to_str(sub, level + 1)
            elif isinstance(v, dict):
                out += _params_to_str(v, level + 1)
            else:
                out += str(v)
        return out
    if isinstance(obj, list):
        return "".join(_params_to_str(x, level + 1) for x in obj)
    return str(obj)


def _sign_request(api_key: str, api_secret: str, method: str, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Sign a JSON-RPC request per Crypto.com Exchange v1.

    Returns (payload, meta) where meta is non-sensitive debug info.
    """
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

    payload: Dict[str, Any] = {
        "id": request_id,
        "method": method,
        "api_key": api_key,
        "params": ordered_params,
        "nonce": nonce_ms,
        "sig": sig,
    }
    meta = {
        "nonce": nonce_ms,
        "request_id": request_id,
        "params_str_len": len(params_str),
        "signature_len": len(sig or ""),
    }
    return payload, meta


def _fetch_instruments(base_url: str) -> Dict[str, Any]:
    """
    Fetch Crypto.com Exchange instrument metadata from public endpoint.
    Cached per-run by caller.
    """
    url = f"{base_url.rstrip('/')}/{METHOD_GET_INSTRUMENTS}"
    resp = requests.get(url, timeout=15)
    raw: Any
    try:
        raw = resp.json()
    except Exception:
        raw = resp.text
    if not isinstance(raw, dict):
        return {"_raw": raw, "_http_status": resp.status_code, "instruments": []}
    # Common shapes observed:
    # - {"code":0,"result":{"data":[{"symbol": "...", "price_tick_size":"...", "qty_tick_size":"..."}]}}
    # - {"code":0,"result":{"instruments":[...]}}
    result = raw.get("result") if isinstance(raw, dict) else None
    instruments: List[dict] = []
    if isinstance(result, dict):
        if isinstance(result.get("data"), list):
            instruments = result.get("data") or []
        elif isinstance(result.get("instruments"), list):
            instruments = result.get("instruments") or []
    return {"_raw": raw, "_http_status": resp.status_code, "instruments": instruments}


def _coerce_decimal(v: Any) -> Optional[Decimal]:
    try:
        if v is None:
            return None
        if isinstance(v, Decimal):
            return v
        # Avoid float binary artifacts by going through str()
        return Decimal(str(v))
    except Exception:
        return None


def _round_down_to_step(x: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return x
    q = (x / step).to_integral_value(rounding=ROUND_DOWN)
    return q * step


def _format_decimal_to_step(x: Decimal, step: Decimal) -> str:
    """
    Format x aligned to step without scientific notation.
    Keeps fixed decimals implied by step.
    """
    try:
        q = x.quantize(step, rounding=ROUND_DOWN)
    except Exception:
        q = x
    s = format(q, "f")
    # Keep trailing zeros only as required by step quantize().
    return s


def _resolve_instrument_meta(instruments: List[dict], instrument_name: str) -> Optional[dict]:
    name = (instrument_name or "").strip()
    if not name:
        return None
    # Try exact match first (either "instrument_name" or "symbol" depending on endpoint shape).
    for it in instruments or []:
        if isinstance(it, dict) and (it.get("instrument_name") == name or it.get("symbol") == name):
            return it
    # Then case-insensitive match.
    for it in instruments or []:
        if isinstance(it, dict) and (
            str(it.get("instrument_name") or "").upper() == name.upper()
            or str(it.get("symbol") or "").upper() == name.upper()
        ):
            return it
    return None


def _normalize_params_with_meta(params: Dict[str, Any], *, instrument_meta: Optional[dict]) -> Dict[str, Any]:
    """
    Normalize price/qty-like fields to strings aligned with tick/lot sizes (if available).
    Only touches params values; does NOT change which keys are present.
    """
    if not params:
        return params
    meta = instrument_meta or {}

    # Common keys seen in Crypto.com Exchange instrument metadata.
    price_step = _coerce_decimal(meta.get("price_tick_size") or meta.get("price_increment") or meta.get("tick_size"))
    qty_step = _coerce_decimal(
        meta.get("quantity_tick_size")
        or meta.get("qty_tick_size")
        or meta.get("quantity_increment")
        or meta.get("lot_size")
    )

    out = dict(params)
    price_like_keys = ["price", "stop_price", "trigger_price", "ref_price"]
    for k in price_like_keys:
        if k not in out:
            continue
        dv = _coerce_decimal(out.get(k))
        if dv is None:
            continue
        if price_step is not None:
            dv = _round_down_to_step(dv, price_step)
            out[k] = _format_decimal_to_step(dv, price_step)
        else:
            out[k] = format(dv, "f")

    if "quantity" in out:
        dq = _coerce_decimal(out.get("quantity"))
        if dq is not None:
            if qty_step is not None:
                dq = _round_down_to_step(dq, qty_step)
                out["quantity"] = _format_decimal_to_step(dq, qty_step)
            else:
                out["quantity"] = format(dq, "f")

    return out


def _extract_error_code_message(raw_body: Any) -> Tuple[Optional[int], Optional[str]]:
    if isinstance(raw_body, dict):
        code = raw_body.get("code")
        msg = raw_body.get("message") or raw_body.get("msg")
        if isinstance(code, int) or code is None:
            return code, str(msg) if msg is not None else None
        try:
            return int(code), str(msg) if msg is not None else None
        except Exception:
            return None, str(msg) if msg is not None else None
    return None, None


def _extract_order_id(raw_body: Any) -> Optional[str]:
    """Extract order identifier from result.order_id, result.orderId, or result.client_order_id."""
    if isinstance(raw_body, dict):
        result = raw_body.get("result")
        if isinstance(result, dict):
            oid = (
                result.get("order_id")
                or result.get("orderId")
                or result.get("client_order_id")
            )
            return str(oid) if oid is not None else None
    return None


def _sanitize_raw_body(raw_body: Any) -> Dict[str, Any]:
    """Return a safe copy of raw_body for logging (code, message, result only)."""
    if not isinstance(raw_body, dict):
        return {}
    return {
        "code": raw_body.get("code"),
        "message": raw_body.get("message"),
        "result": raw_body.get("result"),
    }


def _verify_order_exists(
    api_key: str,
    api_secret: str,
    base_url: str,
    order_id: str,
    instrument_name: str,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """
    Verify that an order_id exists on the exchange. Tries get-order-detail first,
    then get-open-orders, then get-order-history as fallbacks. Uses retries with delays.
    Uses the same signing as create-order. Never raises; returns a dict with verified_exists, verify_method_used, etc.
    """
    out: Dict[str, Any] = {
        "verified_exists": None,
        "verify_method_used": "none",
        "verify_http_status": None,
        "verify_code": None,
        "verify_message": None,
        "verify_result_snippet": None,
    }
    if not order_id or not api_key or not api_secret:
        return out

    retry_delays = [0.4, 0.8, 1.2]
    for attempt_idx, delay in enumerate(retry_delays):
        if attempt_idx > 0:
            time.sleep(delay)

        # Try 1: get-order-detail (standard endpoint for single conditional orders)
        try:
            params_detail = {"order_id": str(order_id)}
            detail_method = METHOD_GET_ORDER_DETAIL
            payload, _ = _sign_request(api_key, api_secret, detail_method, params_detail)
            url = f"{base_url.rstrip('/')}/{detail_method}"
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if out["verify_http_status"] is None:
                out["verify_http_status"] = resp.status_code
            try:
                raw = resp.json()
            except Exception:
                raw = None
            if isinstance(raw, dict):
                if out["verify_code"] is None:
                    out["verify_code"] = raw.get("code")
                if out["verify_message"] is None:
                    out["verify_message"] = raw.get("message") or raw.get("msg")
                out["verify_result_snippet"] = _sanitize_raw_body(raw)
                if resp.status_code == 200 and (raw.get("code") == 0 or raw.get("code") is None):
                    result = raw.get("result")
                    if isinstance(result, dict):
                        oid = result.get("order_id") or result.get("orderId") or result.get("client_order_id")
                        if oid is not None and str(oid) == str(order_id):
                            out["verified_exists"] = True
                            out["verify_method_used"] = "get-order-detail"
                            return out
                    if result is not None:
                        out["verified_exists"] = True
                        out["verify_method_used"] = "get-order-detail"
                        return out
        except Exception:
            pass

        # Try 2: get-open-orders and search for order_id
        try:
            params_open = {"page": 0, "page_size": 200}
            payload, _ = _sign_request(api_key, api_secret, METHOD_GET_OPEN_ORDERS, params_open)
            url = f"{base_url.rstrip('/')}/{METHOD_GET_OPEN_ORDERS}"
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if out["verify_http_status"] is None:
                out["verify_http_status"] = resp.status_code
            try:
                raw = resp.json()
            except Exception:
                raw = None
            if isinstance(raw, dict):
                if out["verify_code"] is None:
                    out["verify_code"] = raw.get("code")
                if out["verify_message"] is None:
                    out["verify_message"] = raw.get("message") or raw.get("msg")
                out["verify_result_snippet"] = _sanitize_raw_body(raw)
                result = raw.get("result")
                data = None
                if isinstance(result, dict):
                    data = result.get("data") or result.get("order_list") or result.get("orders")
                if isinstance(result, list):
                    data = result
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        oid = item.get("order_id") or item.get("orderId") or item.get("client_order_id") or item.get("id")
                        if oid is not None and str(oid) == str(order_id):
                            out["verified_exists"] = True
                            out["verify_method_used"] = "get-open-orders"
                            return out
        except Exception:
            pass

        # Try 3: get-order-history (fallback for recently created orders that may be in history)
        try:
            from datetime import datetime, timedelta
            end_time_ms = int(time.time() * 1000)
            start_time_ms = int((datetime.now() - timedelta(minutes=5)).timestamp() * 1000)
            params_history = {
                "start_time": int(start_time_ms),
                "end_time": int(end_time_ms),
                "page_size": 200,
                "page": 0,
            }
            payload, _ = _sign_request(api_key, api_secret, METHOD_GET_ORDER_HISTORY, params_history)
            url = f"{base_url.rstrip('/')}/{METHOD_GET_ORDER_HISTORY}"
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if out["verify_http_status"] is None:
                out["verify_http_status"] = resp.status_code
            try:
                raw = resp.json()
            except Exception:
                raw = None
            if isinstance(raw, dict):
                if out["verify_code"] is None:
                    out["verify_code"] = raw.get("code")
                if out["verify_message"] is None:
                    out["verify_message"] = raw.get("message") or raw.get("msg")
                out["verify_result_snippet"] = _sanitize_raw_body(raw)
                result = raw.get("result")
                data = None
                if isinstance(result, dict):
                    data = result.get("data") or result.get("order_list")
                if isinstance(result, list):
                    data = result
                if isinstance(data, list):
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        oid = item.get("order_id") or item.get("orderId") or item.get("client_order_id") or item.get("id")
                        if oid is not None and str(oid) == str(order_id):
                            out["verified_exists"] = True
                            out["verify_method_used"] = "get-order-history"
                            return out
        except Exception:
            pass

    # All retries exhausted
    if out["verified_exists"] is None:
        out["verified_exists"] = False
        if out["verify_method_used"] == "none":
            out["verify_method_used"] = "get-order-detail+get-open-orders+get-order-history"
    return out


def _analyze_jsonl(path: str, max_samples_per_group: int = 3) -> Dict[str, Any]:
    """
    Analyze the JSONL output file and print a compact summary.

    Success classification (uses verification when present):
    - SUCCESS_CLEAN: order_id present AND (code 0 or missing) AND verified_exists == true.
    - SUCCESS_WITH_CODE_VERIFIED: order_id present AND code != 0 AND verified_exists == true.
    - PHANTOM_ORDER: order_id present AND verified_exists == false.
    - FAIL: no order_id in result.

    Security: Do NOT print request payloads (api_key/sig). Only prints response grouping and variant IDs.
    """
    from collections import Counter, defaultdict

    counts: Counter[Tuple[Any, Any, Any]] = Counter()
    samples: Dict[Tuple[Any, Any, Any], List[str]] = defaultdict(list)
    success_clean: List[Tuple[str, str]] = []
    success_with_code_verified: List[Tuple[str, str, Any, Any]] = []
    order_id_but_rejected_220: List[Tuple[str, str]] = []  # code=220 always FAIL even if order_id present
    phantom_orders: List[Dict[str, Any]] = []  # variant_id, oid, code, msg, params_highlights
    invalid_side_with_oid: List[Dict[str, Any]] = []  # first 3: sanitized response + params
    ALLOWED_VERIFIED_CODES = {140001}

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                variant_id = obj.get("variant_id")
                if variant_id == "__meta__":
                    continue
                resp = obj.get("response") or {}
                http_status = resp.get("http_status")
                raw_body = resp.get("raw_body")
                code = resp.get("code")
                msg = resp.get("message")
                if (code is None and msg is None) and isinstance(raw_body, dict):
                    code2, msg2 = _extract_error_code_message(raw_body)
                    code = code2 if code is None else code
                    msg = msg2 if msg is None else msg
                key = (http_status, code, msg)
                counts[key] += 1
                if len(samples[key]) < int(max_samples_per_group):
                    samples[key].append(str(variant_id))

                oid = _extract_order_id(raw_body)
                verification = obj.get("verification") or {}
                verified_exists = verification.get("verified_exists")

                if oid:
                    if verified_exists is True:
                        if code is None or code == 0:
                            success_clean.append((str(variant_id), oid))
                        elif code == 220:
                            order_id_but_rejected_220.append((str(variant_id), str(oid)))
                            msg_upper = (msg or "").upper()
                            if "INVALID_SIDE" in msg_upper and len(invalid_side_with_oid) < 3:
                                params = {}
                                try:
                                    req = obj.get("request") or {}
                                    params = (req.get("payload") or {}).get("params") or {}
                                except Exception:
                                    pass
                                invalid_side_with_oid.append({
                                    "variant_id": variant_id,
                                    "order_id": oid,
                                    "code": code,
                                    "message": msg,
                                    "raw_body_sanitized": _sanitize_raw_body(raw_body),
                                    "params": params,
                                })
                        elif code in ALLOWED_VERIFIED_CODES:
                            success_with_code_verified.append((str(variant_id), oid, code, msg))
                            msg_upper = (msg or "").upper()
                            if "INVALID_SIDE" in msg_upper and len(invalid_side_with_oid) < 3:
                                params = {}
                                try:
                                    req = obj.get("request") or {}
                                    params = (req.get("payload") or {}).get("params") or {}
                                except Exception:
                                    pass
                                invalid_side_with_oid.append({
                                    "variant_id": variant_id,
                                    "order_id": oid,
                                    "code": code,
                                    "message": msg,
                                    "raw_body_sanitized": _sanitize_raw_body(raw_body),
                                    "params": params,
                                })
                    elif verified_exists is False:
                        params_highlights = {}
                        verification_details = {}
                        try:
                            req = obj.get("request") or {}
                            p = (req.get("payload") or {}).get("params") or {}
                            keys = ["type", "price", "quantity", "trigger_price", "ref_price", "time_in_force", "instrument_name", "side"]
                            params_highlights = {k: p.get(k) for k in keys if k in p and k != "trigger_condition"}
                            # Get verification details
                            verif = obj.get("verification") or {}
                            verification_details = {
                                "verify_method_used": verif.get("verify_method_used"),
                                "verify_http_status": verif.get("verify_http_status"),
                                "verify_code": verif.get("verify_code"),
                                "verify_message": verif.get("verify_message"),
                                "verify_result_snippet": verif.get("verify_result_snippet"),
                            }
                        except Exception:
                            pass
                        phantom_orders.append({
                            "variant_id": str(variant_id),
                            "order_id": oid,
                            "code": code,
                            "message": msg,
                            "params_highlights": params_highlights,
                            "verification": verification_details,
                        })
                # else: FAIL (no order_id)
    except Exception:
        return {"ok": False, "path": path, "groups": [], "success_clean": [], "success_with_code_verified": [], "phantom_orders": []}

    print("")
    print("SUMMARY")
    print("-------")

    def _label(hs: Any, code: Any, msg: Any) -> str:
        if code is None and msg is None:
            return "(no_code/no_message)"
        if code is None:
            return str(msg)
        if msg is None:
            return str(code)
        return f"{code} {msg}"

    for (hs, code, msg), n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        label = _label(hs, code, msg)
        if hs in (400, 401, 403):
            print(f"{hs} {label}: {n}")
        else:
            print(f"{label}: {n}")

    print("")
    print("SUCCESS CLASSIFICATION (verified)")
    print("---------------------------------")
    print(f"SUCCESS_CLEAN (order_id present, code 0 or missing, verified_exists=true): {len(success_clean)}")
    if success_clean:
        for vid, oid in success_clean[:10]:
            print(f"  - {vid} order_id={oid}")
    print(f"SUCCESS_WITH_CODE_VERIFIED (order_id present, code != 0, verified_exists=true): {len(success_with_code_verified)}")
    if success_with_code_verified:
        for vid, oid, c, m in success_with_code_verified[:10]:
            print(f"  - {vid} order_id={oid} code={c} message={m}")
    print(f"ORDER_ID_BUT_REJECTED (code=220): {len(order_id_but_rejected_220)}")
    if order_id_but_rejected_220:
        for vid, oid in order_id_but_rejected_220[:5]:
            print(f"  - {vid} order_id={oid}")
    print(f"PHANTOM_ORDER (order_id present, verified_exists=false): {len(phantom_orders)}")
    if phantom_orders:
        for ex in phantom_orders[:3]:
            print(f"  - {ex['variant_id']} order_id={ex['order_id']} code={ex['code']} msg={ex['message']}")
            print(f"    params_highlights: {json.dumps(ex['params_highlights'], ensure_ascii=False, default=_json_default, sort_keys=True)}")
            verif = ex.get("verification") or {}
            print(f"    verification: method={verif.get('verify_method_used')} http={verif.get('verify_http_status')} code={verif.get('verify_code')} msg={verif.get('verify_message')}")
            if verif.get("verify_result_snippet"):
                print(f"    verify_result_snippet: {json.dumps(verif.get('verify_result_snippet'), ensure_ascii=False, default=_json_default)}")
    fail_count = " (see group counts above)"
    print(f"FAIL (no order_id):{fail_count}")

    if invalid_side_with_oid:
        print("")
        print("INVALID_SIDE with order_id (first 3) — code is top-level in response")
        print("-------------------------------------------------------------------")
        for i, ex in enumerate(invalid_side_with_oid[:3], 1):
            print(f"Example {i} variant_id={ex['variant_id']} order_id={ex['order_id']}")
            print(f"  code={ex['code']} message={ex['message']}")
            print(f"  raw_body (sanitized): {json.dumps(ex['raw_body_sanitized'], default=_json_default)}")
            p_display = {k: v for k, v in (ex.get("params") or {}).items() if k != "trigger_condition"}
            print(f"  params: {json.dumps(p_display, ensure_ascii=False, default=_json_default, sort_keys=True)}")

    non_140001 = [(k, n) for (k, n) in counts.items() if k[1] != 140001]
    if non_140001:
        print("")
        print("NON_140001 (samples)")
        print("--------------------")
        for (hs, code, msg), n in sorted(non_140001, key=lambda kv: (-kv[1], str(kv[0]))):
            label = _label(hs, code, msg)
            vids = ", ".join(samples.get((hs, code, msg), [])[:5])
            print(f"- http={hs} {label}: {n}  variants: {vids}")

    return {
        "ok": True,
        "path": path,
        "groups": [{"http_status": k[0], "code": k[1], "message": k[2], "count": n} for k, n in counts.items()],
        "success_clean": [{"variant_id": v, "order_id": oid} for v, oid in success_clean],
        "success_with_code_verified": [
            {"variant_id": v, "order_id": oid, "code": c, "message": m}
            for v, oid, c, m in success_with_code_verified
        ],
        "phantom_orders": phantom_orders,
    }


def _mk_qty_variants(qty: str) -> List[Tuple[str, Any]]:
    """
    Produce different JSON-serializable representations.
    """
    variants: List[Tuple[str, Any]] = []
    qty_s = str(qty).strip()
    variants.append(("str", qty_s))

    try:
        qty_f = float(qty_s)
        variants.append(("float_full", qty_f))
        variants.append(("float_round_8", round(qty_f, 8)))
        variants.append(("float_round_6", round(qty_f, 6)))
    except Exception:
        pass

    try:
        qty_d = Decimal(qty_s)
        variants.append(("decimal_full", qty_d))
        variants.append(("decimal_round_8", qty_d.quantize(Decimal("0.00000001"))))
        variants.append(("decimal_round_6", qty_d.quantize(Decimal("0.000001"))))
    except Exception:
        pass

    try:
        qty_i = int(Decimal(qty_s))
        variants.append(("int", qty_i))
    except Exception:
        pass

    # De-dup by repr() to avoid sending identical payloads too often.
    seen = set()
    uniq: List[Tuple[str, Any]] = []
    for name, val in variants:
        key = (name, repr(val))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((name, val))
    return uniq


def _mk_symbol_variants(instrument_name: str) -> List[Tuple[str, str]]:
    base = (instrument_name or "").strip()
    out: List[Tuple[str, str]] = []
    out.append(("as_is", base))
    out.append(("upper", base.upper()))
    out.append(("lower", base.lower()))
    out.append(("usdt_underscore_upper", base.upper().replace("-", "_")))
    out.append(("usdt_dash_upper", base.upper().replace("_", "-")))

    # De-dup
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for name, val in out:
        if val in seen:
            continue
        seen.add(val)
        uniq.append((name, val))
    return uniq


def _mk_trigger_field_variants(ref_price: float) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Explicitly try all listed trigger field combinations.
    We choose numeric values relative to ref_price purely to keep them plausible and non-zero.
    """
    rp = float(ref_price)
    # Pick prices away from ref_price to reduce chance of immediate execution (still black box).
    price = rp * 0.995
    stop_price = rp * 1.005
    trigger_price = rp * 1.002

    combos: List[Tuple[str, Dict[str, Any]]] = [
        ("stop_price", {"stop_price": stop_price}),
        ("trigger_price", {"trigger_price": trigger_price}),
        ("price", {"price": price}),
        ("ref_price", {"ref_price": rp}),
        ("stop_price+price", {"stop_price": stop_price, "price": price}),
        ("trigger_price+price", {"trigger_price": trigger_price, "price": price}),
        ("only_price", {"price": price}),
        ("only_stop_price", {"stop_price": stop_price}),
        ("only_trigger_price", {"trigger_price": trigger_price}),
    ]
    # De-dup by sorted items
    seen = set()
    uniq: List[Tuple[str, Dict[str, Any]]] = []
    for name, d in combos:
        key = tuple(sorted((k, str(v)) for k, v in d.items()))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((name, d))
    return uniq


def _is_valid_side_for_trigger(type_str: str, side: str, trigger_price: float, mark_price: float) -> bool:
    """
    Enforce Crypto.com rule table:
    - trigger below market: SELL STOP_LOSS/STOP_LIMIT, BUY TAKE_PROFIT/TAKE_PROFIT_LIMIT
    - trigger above market: BUY STOP_LOSS/STOP_LIMIT, SELL TAKE_PROFIT/TAKE_PROFIT_LIMIT
    - If trigger_price == mark_price, allow both (don't filter).
    """
    try:
        tp = float(trigger_price)
        mp = float(mark_price)
    except (TypeError, ValueError):
        return True
    side_upper = (side or "").strip().upper()
    type_upper = (type_str or "").strip().upper()
    stop_types = {"STOP_LIMIT", "STOP_LOSS"}
    tp_types = {"TAKE_PROFIT_LIMIT", "TAKE_PROFIT"}
    if tp == mp:
        return True
    below = tp < mp
    if below:
        if type_upper in stop_types:
            return side_upper == "SELL"
        if type_upper in tp_types:
            return side_upper == "BUY"
    else:
        if type_upper in stop_types:
            return side_upper == "BUY"
        if type_upper in tp_types:
            return side_upper == "SELL"
    return True


def run_trigger_probe(
    instrument_name: str,
    side: str,
    qty: str,
    ref_price: float,
    max_variants: int = 200,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Execute the probe.

    Never throws. Always returns a summary dict (including output file path).
    """
    correlation_id = str(uuid.uuid4())
    out_path = f"/tmp/crypto_trigger_probe_{correlation_id}.jsonl"

    base_url = (os.getenv("EXCHANGE_CUSTOM_BASE_URL") or "").strip() or DEFAULT_BASE_URL
    create_method = METHOD_CREATE_ORDER  # standard endpoint only
    endpoint = f"{base_url.rstrip('/')}/{create_method}"

    # Fetch instrument metadata once per run (best-effort). Used only for probe-side rounding.
    instruments_payload: Optional[dict] = None
    instruments_list: List[dict] = []
    try:
        instruments_payload = _fetch_instruments(base_url)
        raw_instruments = instruments_payload.get("instruments") if isinstance(instruments_payload, dict) else []
        instruments_list = list(raw_instruments) if isinstance(raw_instruments, list) else []
    except Exception:
        instruments_payload = None
        instruments_list = []

    api_key_raw = os.getenv("EXCHANGE_CUSTOM_API_KEY","").strip()
    api_secret_raw = os.getenv("EXCHANGE_CUSTOM_API_SECRET","").strip()
    creds_missing = (not api_key_raw) or (not api_secret_raw)

    # Preserve existing runtime behavior when credentials exist by continuing to use
    # the same normalization for signing/requests.
    api_key = _clean_env_secret(api_key_raw) if not creds_missing else ""
    api_secret = _clean_env_secret(api_secret_raw) if not creds_missing else ""

    # Always record a header record for traceability.
    _append_jsonl(
        out_path,
        {
            "ts": _iso_now(),
            "variant_id": "__meta__",
            "request": {"endpoint": endpoint, "headers": {}, "payload": {}},
            "response": {
                "http_status": None,
                "raw_body": {
                    "correlation_id": correlation_id,
                    "env": {
                        "EXCHANGE_CUSTOM_BASE_URL": os.getenv("EXCHANGE_CUSTOM_BASE_URL"),
                        "EXCHANGE_CUSTOM_API_KEY_set": bool(api_key_raw),
                        "EXCHANGE_CUSTOM_API_SECRET_set": bool(api_secret_raw),
                    },
                },
                "code": None,
                "message": None,
            },
        },
    )

    # Preflight: log missing credentials once, but do not stop execution.
    if creds_missing:
        _append_jsonl(
            out_path,
            {
                "ts": _iso_now(),
                "variant_id": "preflight:missing_credentials",
                "request": {"endpoint": endpoint, "headers": {}, "payload": {}},
                "response": {
                    "http_status": None,
                    "raw_body": None,
                    "code": None,
                    "message": None,
                },
                "exception": "Missing credentials: EXCHANGE_CUSTOM_API_KEY and/or EXCHANGE_CUSTOM_API_SECRET",
            },
        )

    headers = {"Content-Type": "application/json"}

    # Golden payload: only conditional limit types with GTC. No IOC/FOK for conditional orders.
    order_types = ["STOP_LIMIT", "TAKE_PROFIT_LIMIT"]

    side_fixed = (side or "").strip().upper() or "SELL"

    # Time-in-force: GOOD_TILL_CANCEL only for conditional types (and default for probe).
    tif_fixed = "GOOD_TILL_CANCEL"

    client_oid_variants: List[Tuple[str, Optional[str]]] = [
        ("with_client_oid", f"probe_{correlation_id.replace('-', '')[:16]}"),
        ("without_client_oid", None),
    ]

    # Price relation: eq = price equals trigger; better = more favorable fill; worse = less favorable.
    def _price_relation_factor(order_type: str, relation: str, side_upper: str) -> Decimal:
        # STOP_LIMIT SELL: trigger when price <= trigger_price; limit at price (eq/better/worse).
        # TAKE_PROFIT_LIMIT SELL: trigger when price >= trigger_price; limit at price.
        if relation == "eq":
            return Decimal("1")
        if relation == "better":
            # SELL stop: better = lower limit price; SELL TP: better = higher limit price.
            return Decimal("0.998") if order_type == "STOP_LIMIT" else Decimal("1.002")
        # worse
        return Decimal("1.002") if order_type == "STOP_LIMIT" else Decimal("0.998")

    price_relation_variants: List[Tuple[str, str]] = [
        ("eq", "eq"),
        ("better", "better"),
        ("worse", "worse"),
    ]

    # Golden template: STOP_LIMIT / TAKE_PROFIT_LIMIT with trigger_price or ref_price + price + GOOD_TILL_CANCEL (no trigger_condition).
    rp_d = Decimal(str(ref_price))
    mark_price = float(ref_price)
    instrument_fixed = (instrument_name or "").strip()

    baseline_stop_trigger = rp_d * Decimal("0.995")
    baseline_tp_trigger = rp_d * Decimal("1.005")
    baseline_variants: List[Dict[str, Any]] = [
        {
            "variant_id": "BASELINE|STOP_LIMIT|trigger_price+price|tif=GTC",
            "params": {
                "instrument_name": instrument_fixed,
                "side": side_fixed,
                "type": "STOP_LIMIT",
                "quantity": qty,
                "trigger_price": baseline_stop_trigger,
                "price": baseline_stop_trigger,
                "time_in_force": tif_fixed,
            },
            "trigger_price_float": float(baseline_stop_trigger),
        },
        {
            "variant_id": "BASELINE|TAKE_PROFIT_LIMIT|trigger_price+price|tif=GTC",
            "params": {
                "instrument_name": instrument_fixed,
                "side": side_fixed,
                "type": "TAKE_PROFIT_LIMIT",
                "quantity": qty,
                "trigger_price": baseline_tp_trigger,
                "price": baseline_tp_trigger,
                "time_in_force": tif_fixed,
            },
            "trigger_price_float": float(baseline_tp_trigger),
        },
    ]

    attempts: List[Dict[str, Any]] = []
    seq = 0
    filtered_invalid_side_count = 0

    def _add_variant_with_schemas(b: Dict[str, Any], meta_extra: Optional[Dict[str, Any]] = None) -> None:
        nonlocal seq, filtered_invalid_side_count
        params_base = b["params"]
        order_type = params_base.get("type", "")
        trigger_float = b.get("trigger_price_float") or float(params_base.get("trigger_price", 0))
        if not _is_valid_side_for_trigger(order_type, side_fixed, trigger_float, mark_price):
            filtered_invalid_side_count += 1
            _append_jsonl(
                out_path,
                {
                    "ts": _iso_now(),
                    "variant_id": b.get("variant_id", ""),
                    "filtered_invalid_side_rule": True,
                    "order_type": order_type,
                    "side": side_fixed,
                    "trigger_price": trigger_float,
                    "mark_price": mark_price,
                },
            )
            return
        base_id = b.get("variant_id", "")
        params_trigger = dict(params_base)
        params_ref = {k: v for k, v in params_base.items() if k != "trigger_price"}
        params_ref["ref_price"] = params_base.get("trigger_price")
        for schema_name, params in (("trigger_price", params_trigger), ("ref_price", params_ref)):
            seq += 1
            if seq > int(max_variants or 0):
                return
            variant_id = f"{seq:04d}|{base_id}|schema={schema_name}"
            meta = dict(meta_extra or {})
            meta["schema"] = schema_name
            if b.get("meta"):
                meta.update(b["meta"])
            attempts.append({"variant_id": variant_id, "params": dict(params), "meta": meta})

    # First: 2 baseline variants (each becomes 2 attempts: trigger_price + ref_price if valid)
    for b in baseline_variants:
        _add_variant_with_schemas(b, {"baseline": True})

    # Cartesian: order_type × price_relation × client_oid
    for order_type, (price_rel_fmt, price_rel_val), (clid_fmt, clid_val) in itertools.product(
        order_types,
        price_relation_variants,
        client_oid_variants,
    ):
        if seq >= int(max_variants or 0):
            break

        if order_type == "STOP_LIMIT":
            trigger_price = rp_d * Decimal("0.995")
        else:
            trigger_price = rp_d * Decimal("1.005")

        factor = _price_relation_factor(order_type, price_rel_val, side_fixed)
        price_val = trigger_price * factor

        params_base: Dict[str, Any] = {
            "instrument_name": instrument_fixed,
            "side": side_fixed,
            "type": order_type,
            "quantity": qty,
            "trigger_price": trigger_price,
            "price": price_val,
            "time_in_force": tif_fixed,
        }
        if clid_val is not None:
            params_base["client_oid"] = clid_val

        base_id = f"type={order_type}|price_rel={price_rel_fmt}|clid={clid_fmt}"
        b = {"variant_id": base_id, "params": params_base, "trigger_price_float": float(trigger_price), "meta": {"order_type": order_type, "side": side_fixed, "price_relation": price_rel_fmt, "client_oid": clid_fmt}}
        _add_variant_with_schemas(b)

    # Execute attempts
    results: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[Any, Any, Any], List[str]] = {}
    best_params_by_group: Dict[Tuple[Any, Any, Any], Dict[str, Any]] = {}
    best_variant_by_group: Dict[Tuple[Any, Any, Any], str] = {}
    # Track failed cancels for fallback cleanup
    failed_cancel_order_ids: List[str] = []

    for attempt in attempts:
        variant_id = attempt["variant_id"]
        raw_params = attempt["params"]

        # Normalize params using instrument metadata (best-effort) to fix tick/lot size issues.
        instrument_meta = _resolve_instrument_meta(instruments_list, str(raw_params.get("instrument_name") or ""))
        params = _normalize_params_with_meta(raw_params, instrument_meta=instrument_meta)

        try:
            if creds_missing:
                # Per-variant behavior when creds are missing:
                # - Write one JSONL record per attempt
                # - Skip signing and skip HTTP
                ordered_params = dict(sorted((params or {}).items())) if params else {}
                schema_tag = (attempt.get("meta") or {}).get("schema", "")
                record = {
                    "ts": _iso_now(),
                    "variant_id": variant_id,
                    "schema": schema_tag,
                    "request": {
                        "endpoint": endpoint,
                        "headers": dict(headers),
                        # Would-be JSON-RPC payload shape (no signing performed).
                        "payload": {
                            "id": 1,
                            "method": create_method,
                            "api_key": None,
                            "params": ordered_params,
                            "nonce": None,
                            "sig": None,
                        },
                    },
                    "response": {
                        "http_status": None,
                        "raw_body": None,
                        "code": None,
                        "message": None,
                    },
                    "exception": "Missing EXCHANGE_CUSTOM_API_KEY/EXCHANGE_CUSTOM_API_SECRET",
                }
                _append_jsonl(out_path, record)
                results.append(record)
                grouped.setdefault((None, None, "exception"), []).append(variant_id)
                key = (None, None, "exception")
                if key not in best_params_by_group:
                    best_params_by_group[key] = dict(ordered_params)
                    best_variant_by_group[key] = variant_id
                continue

            payload, signing_meta = _sign_request(api_key, api_secret, create_method, params)
            req_headers = dict(headers)

            # Send request (no retries, do not fail-fast on status)
            resp = requests.post(endpoint, headers=req_headers, json=payload, timeout=15)
            http_status = resp.status_code

            try:
                raw_body: Any = resp.json()
            except Exception:
                raw_body = resp.text

            code, msg = _extract_error_code_message(raw_body)

            schema_tag = (attempt.get("meta") or {}).get("schema", "")
            record = {
                "ts": _iso_now(),
                "variant_id": variant_id,
                "schema": schema_tag,
                "request": {"endpoint": endpoint, "headers": req_headers, "payload": payload},
                "response": {
                    "http_status": http_status,
                    "raw_body": raw_body,
                    "code": code,
                    "message": msg,
                },
                "signing": signing_meta,
            }

            created_order_id = _extract_order_id(raw_body)
            if created_order_id:
                verification = _verify_order_exists(
                    api_key, api_secret, base_url, created_order_id, instrument_fixed, headers
                )
                record["verification"] = verification
                if dry_run and verification.get("verified_exists") is True:
                    cancel_result_snippet: Optional[Dict[str, Any]] = None
                    # Standard cancel for single conditional orders (private/cancel-order)
                    cancel_method = METHOD_CANCEL_ORDER
                    cancel_order_type = "TRIGGER"
                    api_family = "standard"
                    try:
                        cancel_payload, _ = _sign_request(
                            api_key, api_secret, METHOD_CANCEL_ORDER, {"order_id": created_order_id}
                        )
                        cancel_url = f"{base_url.rstrip('/')}/{METHOD_CANCEL_ORDER}"
                        cancel_resp = requests.post(cancel_url, headers=headers, json=cancel_payload, timeout=15)
                        try:
                            cancel_raw = cancel_resp.json()
                        except Exception:
                            cancel_raw = cancel_resp.text
                        cancel_code, cancel_msg = _extract_error_code_message(cancel_raw)
                        cancel_result_snippet = {
                            "method": cancel_method,
                            "api_family": api_family,
                            "http_status": cancel_resp.status_code,
                            "code": cancel_code,
                            "message": cancel_msg,
                            "order_id": created_order_id,
                            "type": cancel_order_type,
                            "variant_id": variant_id,
                            "body": _sanitize_raw_body(cancel_raw) if isinstance(cancel_raw, dict) else None,
                        }
                        # Track failed cancels for fallback cleanup
                        if not (cancel_resp.status_code == 200 and (cancel_code == 0 or cancel_code is None)):
                            failed_cancel_order_ids.append(created_order_id)
                    except Exception:
                        cancel_result_snippet = {
                            "method": cancel_method,
                            "api_family": api_family,
                            "error": traceback.format_exc(),
                            "order_id": created_order_id,
                            "type": cancel_order_type,
                            "variant_id": variant_id,
                        }
                        # Track failed cancels (exception case)
                        failed_cancel_order_ids.append(created_order_id)
                    record["cancel_result"] = cancel_result_snippet
            else:
                record["verification"] = {
                    "verified_exists": None,
                    "verify_method_used": "none",
                    "verify_http_status": None,
                    "verify_code": None,
                    "verify_message": None,
                    "verify_result_snippet": None,
                }

            _append_jsonl(out_path, record)
            results.append(record)

            key = (http_status, code, msg)
            grouped.setdefault(key, []).append(variant_id)
            if key not in best_params_by_group:
                try:
                    best_params_by_group[key] = dict((record.get("request") or {}).get("payload") or {}).get("params") or dict(params)
                except Exception:
                    best_params_by_group[key] = dict(params)
                best_variant_by_group[key] = variant_id

        except Exception:
            tb = traceback.format_exc()
            schema_tag = (attempt.get("meta") or {}).get("schema", "")
            record = {
                "ts": _iso_now(),
                "variant_id": variant_id,
                "schema": schema_tag,
                "request": {"endpoint": endpoint, "headers": dict(headers), "payload": {"method": create_method, "params": params}},
                "response": {
                    "http_status": None,
                    "raw_body": None,
                    "code": None,
                    "message": None,
                },
                "exception": tb,
            }
            _append_jsonl(out_path, record)
            results.append(record)
            grouped.setdefault((None, None, "exception"), []).append(variant_id)
            key = (None, None, "exception")
            if key not in best_params_by_group:
                best_params_by_group[key] = dict(params)
                best_variant_by_group[key] = variant_id

    # Print summary table to stdout
    print("")
    print("=== Crypto.com Trigger Probe Summary ===")
    print(f"correlation_id: {correlation_id}")
    print(f"jsonl_path: {out_path}")
    print(f"attempts: {len(results)} (max_variants={max_variants})")
    if filtered_invalid_side_count > 0:
        print(f"filtered_invalid_side_rule: {filtered_invalid_side_count} (excluded by side/type/trigger-direction rule)")
    print("")
    print("Group counts by (http_status, code, message):")

    def _sort_key(item):
        (hs, code, msg), vids = item
        hs_sort = hs if isinstance(hs, int) else 9999
        code_sort = code if isinstance(code, int) else 9999999
        msg_sort = msg or ""
        return (hs_sort, code_sort, msg_sort, -len(vids))

    for (http_status, code, msg), vids in sorted(grouped.items(), key=_sort_key):
        label = f"http={http_status} code={code} msg={msg}"
        print(f"- {len(vids):4d}  {label}")

    print("")
    print("Best candidate payload per group (sample):")
    for (http_status, code, msg), vids in sorted(grouped.items(), key=_sort_key):
        key = (http_status, code, msg)
        sample_vid = best_variant_by_group.get(key) or (vids[0] if vids else "")
        sample_params = best_params_by_group.get(key) or {}
        print(f"- http={http_status} code={code} msg={msg} count={len(vids)}")
        print(f"  sample_variant_id: {sample_vid}")
        try:
            # Print params without trigger_condition (probe never sends it).
            params_display = {k: v for k, v in sample_params.items() if k != "trigger_condition"}
            print(f"  params: {json.dumps(params_display, ensure_ascii=False, default=_json_default, sort_keys=True)}")
            keys = ["type", "price", "quantity", "trigger_price", "stop_price", "ref_price", "time_in_force", "instrument_name", "side"]
            highlights = {k: params_display.get(k) for k in keys if k in params_display}
            print(f"  highlights: {json.dumps(highlights, ensure_ascii=False, default=_json_default, sort_keys=True)}")
        except Exception:
            p_repr = {k: v for k, v in (sample_params or {}).items() if k != "trigger_condition"}
            print(f"  params: {repr(p_repr)}")

    # Highlight any variant not returning API_DISABLED 140001
    print("")
    print("Highlights (non-API_DISABLED outcomes):")
    non_disabled: List[Tuple[Tuple[Any, Any, Any], List[str]]] = []
    for key, vids in grouped.items():
        (hs, code, msg) = key
        if code == 140001 and (msg or "").upper() == "API_DISABLED":
            continue
        non_disabled.append((key, vids))

    if not non_disabled:
        print("- (none) All grouped outcomes were API_DISABLED or exceptions")
    else:
        for (hs, code, msg), vids in sorted(non_disabled, key=_sort_key):
            sample = ", ".join(vids[:5])
            more = "" if len(vids) <= 5 else f" (+{len(vids) - 5} more)"
            print(f"- http={hs} code={code} msg={msg}  variants: {sample}{more}")

    # Secondary analysis pass based on JSONL output file (no request payloads printed).
    _analyze_jsonl(out_path)

    # Fallback cleanup: cancel-all-orders if individual cancels failed (standard endpoint for conditional orders)
    cancel_all_orders_result: Optional[Dict[str, Any]] = None
    if dry_run and failed_cancel_order_ids and not creds_missing:
        try:
            cancel_all_payload, _ = _sign_request(
                api_key, api_secret, METHOD_CANCEL_ALL_ORDERS, {"instrument_name": instrument_fixed, "type": "TRIGGER"}
            )
            cancel_all_url = f"{base_url.rstrip('/')}/{METHOD_CANCEL_ALL_ORDERS}"
            cancel_all_resp = requests.post(cancel_all_url, headers=headers, json=cancel_all_payload, timeout=15)
            try:
                cancel_all_raw = cancel_all_resp.json()
            except Exception:
                cancel_all_raw = cancel_all_resp.text
            cancel_all_code, cancel_all_msg = _extract_error_code_message(cancel_all_raw)
            cancel_all_orders_result = {
                "method": "cancel-all-orders",
                "api_family": "standard",
                "http_status": cancel_all_resp.status_code,
                "code": cancel_all_code,
                "message": cancel_all_msg,
                "instrument_name": instrument_fixed,
                "type": "TRIGGER",
                "body": _sanitize_raw_body(cancel_all_raw) if isinstance(cancel_all_raw, dict) else None,
            }
            # Append to JSONL
            _append_jsonl(
                out_path,
                {
                    "ts": _iso_now(),
                    "variant_id": "__cleanup__cancel_all_orders",
                    "request": {"endpoint": cancel_all_url, "headers": headers, "payload": cancel_all_payload},
                    "response": {
                        "http_status": cancel_all_resp.status_code,
                        "raw_body": cancel_all_raw,
                        "code": cancel_all_code,
                        "message": cancel_all_msg,
                    },
                    "cancel_all_orders_result": cancel_all_orders_result,
                },
            )
        except Exception:
            cancel_all_orders_result = {
                "method": "cancel-all-orders",
                "api_family": "standard",
                "error": traceback.format_exc(),
                "instrument_name": instrument_fixed,
                "type": "TRIGGER",
            }
            _append_jsonl(
                out_path,
                {
                    "ts": _iso_now(),
                    "variant_id": "__cleanup__cancel_all_orders",
                    "exception": traceback.format_exc(),
                    "cancel_all_orders_result": cancel_all_orders_result,
                },
            )

    # Cancel summary (only when --dry-run was used)
    if dry_run:
        cancel_order_attempted = 0
        cancel_order_ok = 0
        cancel_order_failed = 0
        cancel_fail_samples: List[Dict[str, Any]] = []
        cancel_all_orders_attempted = 0
        cancel_all_orders_ok = False
        cancel_all_orders_failed = False
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    variant_id = obj.get("variant_id")
                    if variant_id == "__meta__":
                        continue
                    # Check for cancel-order results
                    cancel_result = obj.get("cancel_result")
                    if cancel_result is not None:
                        cancel_order_attempted += 1
                        method = cancel_result.get("method", "cancel-order")
                        http_status = cancel_result.get("http_status")
                        code = cancel_result.get("code")
                        message = cancel_result.get("message")
                        order_id = cancel_result.get("order_id")
                        if "error" in cancel_result:
                            cancel_order_failed += 1
                            if len(cancel_fail_samples) < 3:
                                cancel_fail_samples.append({
                                    "variant_id": variant_id,
                                    "method": method,
                                    "order_id": order_id,
                                    "error": "exception",
                                })
                        elif http_status == 200 and (code == 0 or code is None):
                            cancel_order_ok += 1
                        else:
                            cancel_order_failed += 1
                            if len(cancel_fail_samples) < 3:
                                cancel_fail_samples.append({
                                    "variant_id": variant_id,
                                    "method": method,
                                    "http_status": http_status,
                                    "code": code,
                                    "message": message,
                                    "order_id": order_id,
                                })
                    # Check for cancel-all-orders result
                    cancel_all_result = obj.get("cancel_all_orders_result")
                    if cancel_all_result is not None:
                        cancel_all_orders_attempted = 1
                        if "error" in cancel_all_result:
                            cancel_all_orders_failed = True
                        else:
                            http_status_all = cancel_all_result.get("http_status")
                            code_all = cancel_all_result.get("code")
                            if http_status_all == 200 and (code_all == 0 or code_all is None):
                                cancel_all_orders_ok = True
                            else:
                                cancel_all_orders_failed = True
        except Exception:
            pass

        if cancel_order_attempted > 0 or cancel_all_orders_attempted > 0:
            print("")
            print("CANCEL SUMMARY (--dry-run)")
            print("--------------------------")
            print(f"cancel_order_attempted: {cancel_order_attempted}")
            print(f"cancel_order_ok: {cancel_order_ok}")
            print(f"cancel_order_failed: {cancel_order_failed}")
            if cancel_fail_samples:
                print("")
                print("Cancel failures (first 3):")
                for i, sample in enumerate(cancel_fail_samples[:3], 1):
                    print(f"  {i}. variant_id={sample.get('variant_id')} method={sample.get('method')} order_id={sample.get('order_id')}")
                    if "error" in sample:
                        print(f"     error: exception occurred")
                    else:
                        print(f"     http_status={sample.get('http_status')} code={sample.get('code')} message={sample.get('message')}")
            if cancel_all_orders_attempted > 0:
                print("")
                print(f"cancel_all_orders_attempted: {cancel_all_orders_attempted}")
                print(f"cancel_all_orders_ok: {cancel_all_orders_ok}")
                print(f"cancel_all_orders_failed: {cancel_all_orders_failed}")
                if cancel_all_orders_result:
                    print(f"  method={cancel_all_orders_result.get('method')} instrument={cancel_all_orders_result.get('instrument_name')} type={cancel_all_orders_result.get('type')}")
                    if "error" in cancel_all_orders_result:
                        print(f"  error: exception occurred")
                    else:
                        print(f"  http_status={cancel_all_orders_result.get('http_status')} code={cancel_all_orders_result.get('code')} message={cancel_all_orders_result.get('message')}")

    return {
        "correlation_id": correlation_id,
        "jsonl_path": out_path,
        "attempts": len(results),
        "grouped_keys": [{"http_status": k[0], "code": k[1], "message": k[2], "count": len(v)} for k, v in grouped.items()],
    }


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Crypto.com trigger order brute-force probe (real requests)")
    ap.add_argument("--instrument", required=True, help="Instrument name (e.g. LINK_USDT)")
    ap.add_argument("--side", required=True, help="BUY or SELL")
    ap.add_argument("--qty", required=True, help="Quantity (string recommended)")
    ap.add_argument("--ref-price", required=True, type=float, help="Reference price (float)")
    ap.add_argument("--max-variants", type=int, default=50, help="Cap number of variants to send (default: 50)")
    ap.add_argument("--dry-run", action="store_true", help="If verification finds order exists, attempt cancel and record cancel_result")
    args = ap.parse_args(argv)

    # Never throw; return non-zero only if probe couldn't run at all.
    try:
        run_trigger_probe(
            instrument_name=args.instrument,
            side=args.side,
            qty=args.qty,
            ref_price=float(args.ref_price),
            max_variants=int(args.max_variants),
            dry_run=bool(args.dry_run),
        )
        return 0
    except Exception:
        # Should be unreachable (run_trigger_probe never throws), but keep CLI safe.
        print(traceback.format_exc())
        return 2


if __name__ == "__main__":
    # Intentionally avoid raising or exiting; allow natural process exit with code 0.
    _main()

