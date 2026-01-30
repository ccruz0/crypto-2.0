import os
import time
import hmac
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextvars import ContextVar

# Import requests for exception types (used in exception handlers)
import requests

# Use mandatory http_client wrapper for all outbound HTTP requests
from app.utils.http_client import http_get, http_post

from .crypto_com_constants import REST_BASE, CONTENT_TYPE_JSON
from app.core.failover_config import (
    CRYPTO_REST_BASE, CRYPTO_TIMEOUT, CRYPTO_RETRIES,
    TRADEBOT_BASE, FAILOVER_ENABLED
)
from app.services.open_orders import UnifiedOpenOrder, _format_timestamp

logger = logging.getLogger(__name__)
trigger_probe_logger = logging.getLogger("app.crypto.trigger_probe")

_USE_CRYPTO_PROXY_OVERRIDE: ContextVar[Optional[bool]] = ContextVar(
    "USE_CRYPTO_PROXY_OVERRIDE",
    default=None,
)

def _clean_env_secret(value: str) -> str:
    """
    Normalize secrets/keys loaded from env.
    - Strip whitespace/newlines
    - Remove wrapping single/double quotes (common in .env files)
    """
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def _preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

def _should_failover(status, exc=None):
    """Determine if we should failover to TRADE_BOT"""
    if not FAILOVER_ENABLED or not TRADEBOT_BASE:
        return False
    if exc is not None:
        return True
    return status in (401, 403, 408, 409, 429, 500, 502, 503, 504)

class CryptoComTradeClient:
    """Crypto.com Exchange v1 Private API Client"""
    
    def __init__(self):
        # Check if we should use the proxy
        self._use_proxy_default = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
        self.proxy_url = os.getenv("CRYPTO_PROXY_URL", "http://127.0.0.1:9000")
        self.proxy_token = os.getenv("CRYPTO_PROXY_TOKEN", "CRYPTO_PROXY_SECURE_TOKEN_2024")
        
        if self.use_proxy:
            logger.info(f"CryptoComTradeClient using PROXY at {self.proxy_url}")
        else:
            # Crypto.com Exchange API endpoint
            custom_base = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "")
            if custom_base:
                self.base_url = custom_base
            else:
                # Default to Crypto.com Exchange v1 API endpoint
                self.base_url = REST_BASE
        
        self.api_key = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
        self.api_secret = _clean_env_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
        self.live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        self.crypto_auth_diag = os.getenv("CRYPTO_AUTH_DIAG", "false").lower() == "true"
        
        # In-memory cache for instrument metadata (per run)
        self._instrument_cache: Dict[str, dict] = {}

        # Feature flags for account capabilities
        self._trigger_orders_available = True  # Assume available until proven otherwise
        self._last_trigger_alert_time = 0  # Track when we last sent unavailable alert
        self._last_trigger_health_check = 0  # Track when we last checked trigger orders health
        self._trigger_health_check_interval = 86400  # 24 hours in seconds

        # Remember discovered working SL/TP variant formats (in-memory, per process).
        # Keyed by "<instrument_name>|<order_type>|proxy=<0|1>".
        self._sltp_preferred_variants: Dict[str, dict] = {}

        # Security: never log full keys/secrets. Enable limited diagnostics via CRYPTO_AUTH_DIAG=true.
        if self.crypto_auth_diag:
            logger.info("[CRYPTO_AUTH_DIAG] === CREDENTIALS LOADED (SAFE) ===")
            # Never log any portion of API keys (even partial prefixes/suffixes).
            logger.info(
                "[CRYPTO_AUTH_DIAG] api_key=<SET> len=%s",
                len(self.api_key or ""),
            )
            logger.info("[CRYPTO_AUTH_DIAG] api_secret=<SET> len=%s whitespace=%s", len(self.api_secret or ""), any(c.isspace() for c in (self.api_secret or "")))
            logger.info("[CRYPTO_AUTH_DIAG] use_proxy=%s proxy_url=%s", self.use_proxy, self.proxy_url)
            logger.info("[CRYPTO_AUTH_DIAG] =================================")
        
        logger.info(f"CryptoComTradeClient initialized - Live Trading: {self.live_trading}")
        if self.use_proxy:
            logger.info(f"Using PROXY: {self.proxy_url}")
        else:
            logger.info(f"Using base URL: {self.base_url}")

    @property
    def use_proxy(self) -> bool:
        """
        Effective proxy flag.
        Uses a per-request/per-task override (ContextVar) when set, otherwise the env default.
        This prevents one request (or background task) from accidentally affecting others.
        """
        override = _USE_CRYPTO_PROXY_OVERRIDE.get()
        if override is None:
            return bool(getattr(self, "_use_proxy_default", False))
        return bool(override)

    @use_proxy.setter
    def use_proxy(self, value: bool) -> None:
        # Sets override for the current execution context only.
        _USE_CRYPTO_PROXY_OVERRIDE.set(bool(value))

    def clear_use_proxy_override(self) -> None:
        _USE_CRYPTO_PROXY_OVERRIDE.set(None)

    def _refresh_runtime_flags(self) -> None:
        """
        Refresh runtime flags from environment.

        The client instance is long-lived, but some endpoints toggle LIVE_TRADING /
        proxy behavior dynamically (e.g. for one-off SL/TP creation). We must re-read
        env flags at call time rather than caching only at __init__.
        """
        try:
            self.live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        except Exception:
            pass

        # Keep the current runtime proxy flag (it may be overridden per-request by endpoints),
        # but refresh proxy config values and ensure base_url is always available when proxy is off.
        try:
            self.proxy_url = os.getenv("CRYPTO_PROXY_URL", getattr(self, "proxy_url", "http://127.0.0.1:9000"))
            self.proxy_token = os.getenv("CRYPTO_PROXY_TOKEN", getattr(self, "proxy_token", "CRYPTO_PROXY_SECURE_TOKEN_2024"))
        except Exception:
            pass

        # IMPORTANT: If the client was initialized with proxy enabled, base_url may not exist.
        # When endpoints temporarily disable proxy (trade_client.use_proxy = False), direct calls
        # must still work.
        try:
            if not getattr(self, "use_proxy", False):
                if not getattr(self, "base_url", None):
                    custom_base = (os.getenv("EXCHANGE_CUSTOM_BASE_URL", "") or "").strip()
                    self.base_url = custom_base or REST_BASE
        except Exception:
            pass
    
    def _call_proxy(self, method: str, params: dict) -> dict:
        """Call Crypto.com API through the proxy"""
        try:
            response = http_post(
                f"{self.proxy_url}/proxy/private",
                json={"method": method, "params": params},
                headers={"X-Proxy-Token": self.proxy_token},
                timeout=15,
                calling_module="crypto_com_trade._call_proxy"
            )
            response.raise_for_status()
            result = response.json()
            
            # Check if proxy returned an error status
            proxy_status = result.get("status")
            body = result.get("body", {})
            
            # If proxy returned 401, parse the body to check for authentication error
            if proxy_status == 401:
                # body might be a string that needs parsing
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except:
                        pass
                # Return the parsed error for failover detection
                return body
            
            if proxy_status == 200:
                # body might be a string that needs parsing
                if isinstance(body, str):
                    try:
                        return json.loads(body)
                    except:
                        return {}
                return body
            else:
                logger.error(f"Proxy returned status {proxy_status}: {body}")
                return body
        except Exception as e:
            logger.error(f"Error calling proxy: {e}")
            return {}
    
    # ---------- READ-ONLY FALLBACK CALLS (no changes on TRADE_BOT) ----------
    def _fallback_balance(self):
        """Fallback to TRADE_BOT for account balance"""
        url = f"{TRADEBOT_BASE}/api/account/balance?exchange=CRYPTO_COM"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return http_get(url, timeout=CRYPTO_TIMEOUT, calling_module="crypto_com_trade._fallback_balance")
    
    def _fallback_open_orders(self):
        """Fallback to TRADE_BOT for open orders"""
        url = f"{TRADEBOT_BASE}/api/orders/open"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return http_get(url, timeout=CRYPTO_TIMEOUT, calling_module="crypto_com_trade._fallback_open_orders")
    
    def _fallback_history(self):
        """Fallback to TRADE_BOT for order history"""
        url = f"{TRADEBOT_BASE}/api/orders/history"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return http_get(url, timeout=CRYPTO_TIMEOUT, calling_module="crypto_com_trade._fallback_history")
    
    def _fallback_place_order(self, data):
        """Fallback to TRADE_BOT for placing orders"""
        url = f"{TRADEBOT_BASE}/api/orders/place"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return http_post(url, json=data, timeout=CRYPTO_TIMEOUT, calling_module="crypto_com_trade._fallback_place_order")
    
    def _fallback_cancel_order(self, order_id):
        """Fallback to TRADE_BOT for canceling orders"""
        url = f"{TRADEBOT_BASE}/api/orders/cancel"
        logger.info(f"Failover to TRADE_BOT: {url}")
        params = {"order_id": order_id}
        return http_post(url, json=params, timeout=CRYPTO_TIMEOUT, calling_module="crypto_com_trade._fallback_cancel_order")
    # -----------------------------------------------------------------------
    
    def _params_to_str(self, obj, level: int = 0) -> str:
        """Convert params to string following Crypto.com documentation exactly"""
        MAX_LEVEL = 3
        if level >= MAX_LEVEL:
            return str(obj)
        
        return_str = ""
        for key in sorted(obj):
            return_str += key
            if obj[key] is None:
                return_str += 'null'
            elif isinstance(obj[key], list):
                # Handle lists: if items are strings, join them; if dicts, recurse
                for subObj in obj[key]:
                    if isinstance(subObj, dict):
                        return_str += self._params_to_str(subObj, level + 1)
                    else:
                        # For strings or other primitives, just add the value
                        return_str += str(subObj)
            elif isinstance(obj[key], dict):
                return_str += self._params_to_str(obj[key], level + 1)
            else:
                return_str += str(obj[key])
        return return_str

    def _params_to_str_insertion(self, obj, level: int = 0) -> str:
        """
        Convert params to string while preserving insertion order.

        This is ONLY used by the experimental trigger probe (see run_trigger_order_probe)
        to stress-test signing/order acceptance behavior. Production signing uses _params_to_str.
        """
        MAX_LEVEL = 3
        if level >= MAX_LEVEL:
            return str(obj)
        if not isinstance(obj, dict):
            return str(obj)

        return_str = ""
        for key in obj.keys():
            return_str += str(key)
            value = obj.get(key)
            if value is None:
                return_str += "null"
            elif isinstance(value, list):
                for sub_obj in value:
                    if isinstance(sub_obj, dict):
                        return_str += self._params_to_str_insertion(sub_obj, level + 1)
                    else:
                        return_str += str(sub_obj)
            elif isinstance(value, dict):
                return_str += self._params_to_str_insertion(value, level + 1)
            else:
                return_str += str(value)
        return return_str
    
    def sign_request(
        self,
        method: str,
        params: dict,
        *,
        _suppress_log: bool = False,
        _ordered_params_override: Optional[dict] = None,
        _params_str_override: Optional[str] = None,
        _request_id_override: Optional[int] = None,
        _nonce_override_ms: Optional[int] = None,
    ) -> dict:
        """
        Generate signed JSON-RPC 2.0 request for Crypto.com Exchange v1
        Following official docs: method + id + api_key + params_string + nonce
        For empty params: use empty string (verified to work)
        For non-empty params: use _params_to_str method (custom format as per Crypto.com docs)
        """
        nonce_ms = int(_nonce_override_ms if _nonce_override_ms is not None else time.time() * 1000)
        
        # Build params string for signature
        # IMPORTANT: If params is empty {}, use empty string in signature (not '{}')
        # For non-empty params, use _params_to_str (verified: 401 with json.dumps, 400 with _params_to_str)
        # This means authentication works with _params_to_str, but request body may need adjustment
        if _params_str_override is not None:
            params_str = str(_params_str_override)
        elif params:
            # Use _params_to_str for non-empty params (required for Crypto.com Exchange API v1)
            # This sorts alphabetically and concatenates key+value without separators
            params_str = self._params_to_str(params, 0)
        else:
            params_str = ""  # Empty string in signature when params is {}
        
        # Construct payload for JSON body
        # According to Crypto.com Exchange API v1 documentation:
        # - id: Request ID (use 1 for consistency with documentation and working methods)
        # - nonce: Timestamp in milliseconds
        # - api_key: API key
        # - params: Parameters dict (always included, even if empty {})
        # - sig: HMAC signature
        # Note: Documentation shows id: 1, and get_account_summary (which works) uses id: 1
        request_id = int(_request_id_override if _request_id_override is not None else 1)  # default per docs
        
        # IMPORTANT: Ensure params dict is ordered alphabetically to match string_to_sign
        # Some endpoints (like get-order-history) may require params to be in the same order as in string_to_sign
        # In Python 3.7+, dicts maintain insertion order, but we explicitly sort to match string_to_sign
        if _ordered_params_override is not None:
            ordered_params = dict(_ordered_params_override)
        elif params:
            ordered_params = dict(sorted(params.items()))
        else:
            ordered_params = {}
        
        payload = {
            "id": request_id,  # Use 1 as per documentation sample
            "method": method,
            "api_key": self.api_key,
            "params": ordered_params,  # Use ordered params to match string_to_sign
            "nonce": nonce_ms
        }
        
        # String to sign format per Crypto.com Exchange API v1:
        # Format: method + id + api_key + params_str + nonce
        string_to_sign = method + str(request_id) + self.api_key + params_str + str(nonce_ms)

        # Diagnostic logging for authentication debugging
        if not _suppress_log:
            # NOTE: Experimental probes suppress this log to avoid printing any part of credentials.
            key_suffix = self.api_key[-4:] if self.api_key else "NONE"
            logger.info(
                f"[CRYPTOCOM_AUTH] endpoint=/{method} method=POST has_signature=true "
                f"nonce={nonce_ms} ts={nonce_ms} key_suffix={key_suffix} "
                f"params_count={len(params) if params else 0}"
            )
        
        # Security: signing diagnostics are OFF by default.
        if getattr(self, "crypto_auth_diag", False):
            current_utc = datetime.now(timezone.utc).isoformat()
            current_time = time.time()
            logger.info("[CRYPTO_AUTH_DIAG] === SIGNING PROCESS (SAFE) ===")
            logger.info("[CRYPTO_AUTH_DIAG] method=%s", method)
            logger.info("[CRYPTO_AUTH_DIAG] request_id=%s (type=%s)", request_id, type(request_id).__name__)
            logger.info("[CRYPTO_AUTH_DIAG] nonce=%s (type=%s)", nonce_ms, type(nonce_ms).__name__)
            logger.info("[CRYPTO_AUTH_DIAG] server_time_utc=%s", current_utc)
            logger.info("[CRYPTO_AUTH_DIAG] server_time_epoch=%s", current_time)
            logger.info("[CRYPTO_AUTH_DIAG] params_str_len=%s", len(params_str))
            # Do NOT log string_to_sign or signature in full (sensitive).
            logger.info("[CRYPTO_AUTH_DIAG] string_to_sign_len=%s", len(string_to_sign))
        
        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            bytes(str(self.api_secret), 'utf-8'),
            msg=bytes(string_to_sign, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        if getattr(self, "crypto_auth_diag", False):
            # Never log any portion of signatures or API keys.
            logger.info("[CRYPTO_AUTH_DIAG] signature_len=%s", len(signature or ""))
            safe_payload = dict(payload)
            safe_payload["api_key"] = "<SET>"
            safe_payload["sig"] = "<SET>"
            logger.info("[CRYPTO_AUTH_DIAG] payload=%s", json.dumps(safe_payload, indent=2))
            logger.info("[CRYPTO_AUTH_DIAG] ============================")
        
        payload["sig"] = signature
        
        return payload

    def run_trigger_order_probe(
        self,
        instrument_name: str,
        side: str,
        qty: str,
        ref_price: float,
        dry_run: bool = True,
        max_variants: int = 200,
    ) -> dict:
        """
        Experimental: Probe conditional order creation formats for Crypto.com Exchange.

        This runner is intended to gather evidence when STOP_LIMIT / TAKE_PROFIT_LIMIT orders
        are rejected (e.g. code=140001 API_DISABLED) while MARKET/LIMIT work.

        Safety constraints:
        - Enforces a strict max notional (default $1) using qty*ref_price.
        - Triggers are placed away from ref_price (should not execute immediately).
        - If an order is created successfully and dry_run=True, we attempt to cancel it immediately.

        Notes:
        - Always uses direct API calls (no proxy) for reproducible evidence.
        - Writes one JSON record per attempt to /tmp/trigger_probe_<correlation_id>.jsonl
        - Must be invoked behind explicit flags (see routes_control endpoint).
        """
        correlation_id = str(uuid.uuid4())

        side_upper = (side or "").strip().upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")

        instrument_input = (instrument_name or "").strip()
        if not instrument_input:
            raise ValueError("instrument_name is required")

        try:
            qty_float = float(str(qty).strip())
        except Exception:
            raise ValueError("qty must be numeric (string or number)")
        if qty_float <= 0:
            raise ValueError("qty must be > 0")
        if not ref_price or float(ref_price) <= 0:
            raise ValueError("ref_price must be > 0")

        # Hard cap: never place meaningful size
        max_notional_usd = float(os.getenv("CRYPTO_PROBE_MAX_NOTIONAL_USD", "1.0") or "1.0")
        notional = qty_float * float(ref_price)
        if notional > max_notional_usd:
            raise ValueError(
                f"Probe notional too large: qty*ref_price={notional:.6f} > cap={max_notional_usd:.6f} USD"
            )

        # Resolve instrument variants but only include those that exist (via metadata lookup).
        base = instrument_input.upper()
        candidates = [
            base,
            base.replace("-", "_"),
            base.replace("_", "-"),
        ]
        if base.endswith("_USD"):
            candidates.append(base[:-4] + "_USDT")
        if base.endswith("_USDT"):
            candidates.append(base[:-5] + "_USD")

        seen = set()
        uniq_candidates: List[str] = []
        for c in candidates:
            c2 = (c or "").strip().upper()
            if not c2 or c2 in seen:
                continue
            seen.add(c2)
            uniq_candidates.append(c2)

        instrument_variants: List[str] = []
        for cand in uniq_candidates:
            try:
                if self._get_instrument_metadata(cand):
                    instrument_variants.append(cand)
            except Exception:
                continue
        if not instrument_variants:
            instrument_variants = [base]

        max_variants = int(max_variants or 0)
        if max_variants <= 0:
            max_variants = 1
        if max_variants > 200:
            max_variants = 200

        out_path = f"/tmp/trigger_probe_{correlation_id}.jsonl"
        out_file = Path(out_path)
        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        def _safe_payload(payload: dict) -> dict:
            safe = dict(payload or {})
            if "api_key" in safe:
                safe["api_key"] = "<REDACTED>"
            if "sig" in safe:
                safe["sig"] = "<REDACTED>"
            return safe

        def _safe_response(obj: Any) -> Any:
            if isinstance(obj, dict):
                red = dict(obj)
                if "api_key" in red:
                    red["api_key"] = "<REDACTED>"
                if "sig" in red:
                    red["sig"] = "<REDACTED>"
                return red
            return obj

        def _type_of(v: Any) -> str:
            if v is None:
                return "null"
            if isinstance(v, bool):
                return "bool"
            if isinstance(v, int):
                return "int"
            if isinstance(v, float):
                return "float"
            if isinstance(v, str):
                return "str"
            return type(v).__name__

        def _plain_decimal_str(x: float, decimals: int = 12) -> str:
            # ensure plain decimal strings, no scientific notation
            q = Decimal(str(x)).quantize(Decimal("1." + ("0" * decimals)))
            s = format(q, "f")
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return s

        def _build_signed_payload(
            method: str,
            params: dict,
            signing_mode: str,
        ) -> Tuple[dict, dict]:
            nonce_ms = int(time.time() * 1000)
            request_id = 1
            signing_mode_norm = (signing_mode or "default").strip().lower()

            if not params:
                params_str = ""
                ordered_params = {}
            elif signing_mode_norm == "insertion":
                params_str = self._params_to_str_insertion(params, 0)
                ordered_params = params  # preserve insertion order
            elif signing_mode_norm == "json_compact":
                params_str = json.dumps(params, separators=(",", ":"), sort_keys=True)
                ordered_params = params  # preserve insertion order (stress)
            else:
                params_str = self._params_to_str(params, 0)
                ordered_params = dict(sorted(params.items()))

            payload = self.sign_request(
                method,
                params,
                _suppress_log=True,
                _ordered_params_override=ordered_params,
                _params_str_override=params_str,
                _request_id_override=request_id,
                _nonce_override_ms=nonce_ms,
            )

            string_to_sign_len = len(method + str(request_id) + (self.api_key or "") + params_str + str(nonce_ms))
            meta = {
                "sign_mode": signing_mode_norm,
                "params_str_len": len(params_str),
                "string_to_sign_len": string_to_sign_len,
                "signature_len": len(str(payload.get("sig") or "")),
            }
            return payload, meta

        # Always probe direct (no proxy) for evidence.
        prev_override = _USE_CRYPTO_PROXY_OVERRIDE.get()
        self.use_proxy = False
        self._refresh_runtime_flags()

        method = "private/create-order"
        url = f"{self.base_url}/{method}"

        # Variant matrix (bounded)
        order_types = ["STOP_LIMIT", "TAKE_PROFIT_LIMIT"]
        trigger_keys = ["trigger_price", "stop_price", "triggerPrice"]
        tif_values = [None, "GOOD_TILL_CANCEL", "GTC", "IOC", "FOK"]
        flag_values = [None, True, False]
        client_id_keys = [None, "client_oid", "client_order_id"]
        signing_modes = ["default", "insertion", "json_compact"]
        value_type_modes = ["str", "num"]
        offsets = [0.001, 0.0025, 0.005, 0.01]
        limit_rel_modes = ["eq", "better", "worse"]

        def _trigger_condition(op_type: str) -> str:
            if op_type == "STOP_LIMIT":
                return "<=" if side_upper == "SELL" else ">="
            return ">=" if side_upper == "SELL" else "<="

        def _trigger_price(op_type: str, off: float) -> float:
            if op_type == "STOP_LIMIT":
                return float(ref_price) * (1 - off) if side_upper == "SELL" else float(ref_price) * (1 + off)
            return float(ref_price) * (1 + off) if side_upper == "SELL" else float(ref_price) * (1 - off)

        def _limit_price(trigger: float, mode: str) -> float:
            delta = 0.0005  # 0.05%
            if mode == "eq":
                return trigger
            if mode == "better":
                return trigger * (1 + delta) if side_upper == "SELL" else trigger * (1 - delta)
            return trigger * (1 - delta) if side_upper == "SELL" else trigger * (1 + delta)

        attempts = 0
        summary: Dict[Tuple[Optional[int], Optional[int], Optional[str]], int] = {}

        try:
            for instr in instrument_variants:
                for op_type in order_types:
                    for off in offsets:
                        trig = _trigger_price(op_type, off)
                        for limit_rel in limit_rel_modes:
                            limit = _limit_price(trig, limit_rel)
                            for trig_key in trigger_keys:
                                for tif in tif_values:
                                    for reduce_only in flag_values:
                                        for post_only in flag_values:
                                            for client_key in client_id_keys:
                                                for vtype in value_type_modes:
                                                    for sign_mode in signing_modes:
                                                        if attempts >= max_variants:
                                                            break

                                                        omit_price = bool(op_type == "STOP_LIMIT" and trig_key != "trigger_price")
                                                        off_bps = int(off * 10000)
                                                        variant_id = (
                                                            f"{op_type}|instr={instr}|side={side_upper}|off={off_bps}bps|"
                                                            f"limit={limit_rel}|trigkey={trig_key}|tif={tif or 'none'}|"
                                                            f"ro={reduce_only if reduce_only is not None else 'na'}|"
                                                            f"po={post_only if post_only is not None else 'na'}|"
                                                            f"clid={client_key or 'none'}|vtype={vtype}|sign={sign_mode}|"
                                                            f"omit_price={int(omit_price)}"
                                                        )

                                                        params: Dict[str, Any] = {
                                                            "instrument_name": instr,
                                                            "side": side_upper,
                                                            "type": op_type,
                                                        }

                                                        qty_val: Any = str(qty).strip() if vtype == "str" else qty_float
                                                        trig_val: Any = _plain_decimal_str(trig) if vtype == "str" else float(trig)
                                                        limit_val: Any = _plain_decimal_str(limit) if vtype == "str" else float(limit)
                                                        ref_val: Any = _plain_decimal_str(float(ref_price)) if vtype == "str" else float(ref_price)

                                                        params["quantity"] = qty_val
                                                        params["ref_price"] = ref_val
                                                        params[trig_key] = trig_val
                                                        params["trigger_condition"] = f"{_trigger_condition(op_type)} {trig_val}"

                                                        if not omit_price:
                                                            params["price"] = limit_val
                                                        if tif is not None:
                                                            params["time_in_force"] = tif
                                                        if reduce_only is not None:
                                                            params["reduce_only"] = bool(reduce_only)
                                                        if post_only is not None:
                                                            params["post_only"] = bool(post_only)
                                                        if client_key:
                                                            params[client_key] = str(uuid.uuid4())

                                                        payload, signing_meta = _build_signed_payload(method, params, sign_mode)

                                                        safe_payload = _safe_payload(payload)
                                                        params_dict = payload.get("params") or {}
                                                        params_keys = sorted(list(params_dict.keys())) if isinstance(params_dict, dict) else []

                                                        t0 = time.perf_counter()
                                                        http_status: Optional[int] = None
                                                        resp_obj: Any = None
                                                        resp_code: Optional[int] = None
                                                        resp_message: Optional[str] = None
                                                        error: Optional[str] = None
                                                        created_order_id: Optional[str] = None
                                                        cancel_result: Optional[dict] = None

                                                        try:
                                                            resp = http_post(
                                                                url,
                                                                json=payload,
                                                                headers={"Content-Type": "application/json"},
                                                                timeout=10,
                                                                calling_module="crypto_com_trade.trigger_probe",
                                                            )
                                                            http_status = getattr(resp, "status_code", None)
                                                            try:
                                                                resp_obj = resp.json()
                                                            except Exception:
                                                                resp_obj = (getattr(resp, "text", "") or "")[:5000]

                                                            if isinstance(resp_obj, dict):
                                                                resp_code = resp_obj.get("code")
                                                                resp_message = resp_obj.get("message")
                                                                if isinstance(resp_obj.get("result"), dict):
                                                                    created_order_id = (
                                                                        resp_obj["result"].get("order_id")
                                                                        or resp_obj["result"].get("client_order_id")
                                                                    )
                                                        except Exception as e:
                                                            error = str(e)

                                                        elapsed_ms = int((time.perf_counter() - t0) * 1000)

                                                        # Optional cleanup: cancel created probe orders
                                                        if created_order_id and dry_run:
                                                            try:
                                                                cancel_result = self.cancel_order(
                                                                    order_id=str(created_order_id),
                                                                    symbol=str(instr),
                                                                )
                                                            except Exception as cancel_err:
                                                                cancel_result = {"error": str(cancel_err)}

                                                        record = {
                                                            "correlation_id": correlation_id,
                                                            "variant_id": variant_id,
                                                            "order_type": op_type,
                                                            "instrument_name": instr,
                                                            "side": side_upper,
                                                            "payload": safe_payload,
                                                            "params_keys": params_keys,
                                                            "numeric_fields_present": {
                                                                "trigger": trig_key in params,
                                                                "price": "price" in params,
                                                                "quantity": "quantity" in params,
                                                            },
                                                            "value_types": {
                                                                k: _type_of(v)
                                                                for k, v in (
                                                                    params_dict.items()
                                                                    if isinstance(params_dict, dict)
                                                                    else []
                                                                )
                                                            },
                                                            "signing": signing_meta,
                                                            "http_status": http_status,
                                                            "response_json": _safe_response(resp_obj)
                                                            if isinstance(resp_obj, dict)
                                                            else None,
                                                            "response_text": _safe_response(resp_obj)
                                                            if not isinstance(resp_obj, dict)
                                                            else None,
                                                            "elapsed_ms": elapsed_ms,
                                                            "created_order_id": created_order_id,
                                                            "cancel_result": cancel_result,
                                                            "error": error,
                                                        }

                                                        trigger_probe_logger.info(
                                                            "[TRIGGER_PROBE] %s",
                                                            json.dumps(record, ensure_ascii=False),
                                                        )
                                                        try:
                                                            with out_file.open("a", encoding="utf-8") as fp:
                                                                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                                                        except Exception:
                                                            pass

                                                        key = (
                                                            int(http_status) if isinstance(http_status, int) else None,
                                                            int(resp_code) if isinstance(resp_code, int) else None,
                                                            str(resp_message) if resp_message else None,
                                                        )
                                                        summary[key] = summary.get(key, 0) + 1
                                                        attempts += 1
                                            if attempts >= max_variants:
                                                break
                                        if attempts >= max_variants:
                                            break
                                    if attempts >= max_variants:
                                        break
                                if attempts >= max_variants:
                                    break
                            if attempts >= max_variants:
                                break
                        if attempts >= max_variants:
                            break
                    if attempts >= max_variants:
                        break
                if attempts >= max_variants:
                    break
        finally:
            # Restore previous proxy override state
            if prev_override is None:
                self.clear_use_proxy_override()
            else:
                _USE_CRYPTO_PROXY_OVERRIDE.set(prev_override)

        summary_counts: Dict[str, int] = {}
        for (hs, code, msg), count in summary.items():
            summary_counts[f"http={hs}|code={code}|msg={msg}"] = count

        return {
            "correlation_id": correlation_id,
            "jsonl_path": str(out_file),
            "attempts": attempts,
            "summary": summary_counts,
        }
    
    def get_account_summary(self) -> dict:
        """Get account summary (balances)"""
        # [CRYPTO_AUTH_DIAG] Log outbound IP before request
        try:
            from app.utils.egress_guard import validate_outbound_url, log_outbound_request
            ipify_url = "https://api.ipify.org"
            response = http_get(ipify_url, timeout=5, calling_module="crypto_com_trade.get_account_summary")
            egress_ip = response.text.strip()
            logger.info(f"[CRYPTO_AUTH_DIAG] CRYPTO_COM_OUTBOUND_IP: {egress_ip}")
        except Exception as e:
            logger.warning(f"[CRYPTO_AUTH_DIAG] Could not determine outbound IP: {e}")
        
        # Use proxy if enabled (even in dry-run mode for real data)
        if self.use_proxy:
            logger.info("[CRYPTO_AUTH_DIAG] Using PROXY to get account summary")
            method = "private/user-balance"
            params = {}
            
            try:
                result = self._call_proxy(method, params)
                
                # Check if proxy returned a 401
                if isinstance(result, dict) and result.get("code") == 40101:
                    logger.warning("Proxy returned 401 - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        fr = self._fallback_balance()
                        if fr.status_code == 200:
                            data = fr.json()
                            return {"code": 0, "result": data}
                    raise RuntimeError("Crypto.com: account summary failed (no fallback)")
                
                # Handle proxy response
                if "result" in result and "data" in result["result"]:
                    data = result["result"]["data"]
                    accounts = []
                    
                    # Extract position balances - data is an array, first element has position_balances
                    if data and len(data) > 0:
                        position_data = data[0] if isinstance(data, list) else data
                        if "position_balances" in position_data:
                            for balance in position_data["position_balances"]:
                                instrument = balance.get("instrument_name", "")
                                quantity = float(balance.get("quantity", "0"))
                                
                                # Extract currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                                # Crypto.com may return instrument_name as "BTC_USDT" or just "BTC"
                                currency = instrument
                                if "_" in instrument:
                                    # Extract base currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                                    currency = instrument.split("_")[0].upper()
                                else:
                                    currency = instrument.upper()
                                
                                # Only include balances > 0
                                if quantity > 0:
                                    # Include market_value from Crypto.com if available
                                    market_value = balance.get("market_value") or balance.get("usd_value")
                                    account_entry = {
                                        "currency": currency,
                                        "balance": str(quantity),
                                        "available": str(balance.get("max_withdrawal_balance", quantity))
                                    }
                                    if market_value:
                                        account_entry["market_value"] = str(market_value)
                                    accounts.append(account_entry)
                    
                    logger.info(f"Retrieved {len(accounts)} account balances via proxy")
                    
                    # Extract top-level equity/wallet balance fields if present (proxy response)
                    response_data = {"accounts": accounts}
                    if "result" in result and isinstance(result["result"], dict):
                        result_data = result["result"]
                        equity_fields = ["equity", "net_equity", "wallet_balance", "margin_equity", "total_equity", 
                                        "available_equity", "account_equity", "balance_equity"]
                        for field in equity_fields:
                            if field in result_data:
                                value = result_data[field]
                                if value is not None:
                                    try:
                                        equity_value = float(value) if isinstance(value, str) else float(value)
                                        response_data["margin_equity"] = equity_value
                                        logger.info(f"Found margin equity field '{field}' (proxy): {equity_value}")
                                        break
                                    except (ValueError, TypeError):
                                        logger.debug(f"Could not parse equity field '{field}': {value}")
                    
                    return response_data
                else:
                    logger.error(f"Unexpected proxy response for account summary: {result}")
                    return {"accounts": []}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Proxy error: {e} - attempting failover to TRADE_BOT")
                if _should_failover(None, e):
                    fr = self._fallback_balance()
                    if fr.status_code == 200:
                        data = fr.json()
                        return {"code": 0, "result": data}
                raise
        
        # NO SIMULATED DATA - Always try to get real data from API
        # Check if API credentials are configured
        if not self.api_key or not self.api_secret:
            logger.error("API credentials not configured. Cannot get account summary.")
            raise ValueError("API credentials not configured. Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        
        # Try private/user-balance first (same as proxy uses, and it works for get_open_orders)
        # If that fails, try private/get-account-summary
        method = "private/user-balance"
        params = {}
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method} (same as proxy and get_open_orders)")
        
        try:
            # Use same pattern as get_open_orders which works
            url = f"{self.base_url}/{method}"
            
            # SECURITY: Validate outbound URL against allowlist
            try:
                from app.utils.egress_guard import validate_outbound_url, log_outbound_request, EgressGuardError
                validated_url, resolved_ip = validate_outbound_url(url, calling_module="crypto_com_trade.get_account_summary")
            except EgressGuardError as e:
                logger.error(f"[CRYPTO_TRADE] Outbound request blocked: {e}")
                raise RuntimeError(f"Security policy violation: {e}")
            
            logger.debug(f"Request URL: {validated_url}")
            logger.debug(f"Payload keys: {list(payload.keys())}")
            response = http_post(
                validated_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
                calling_module="crypto_com_trade.get_account_summary"
            )
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.warning(f"API authentication failed: {error_msg} (code: {error_code})")
                
                # If IP not whitelisted or other auth issues, try failover before raising error
                if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                    # Get outbound IP for diagnostic purposes
                    try:
                        ipify_url = "https://api.ipify.org"
                        response = http_get(ipify_url, timeout=3, calling_module="crypto_com_trade.get_account_summary")
                        egress_ip = response.text.strip()
                        logger.error(f"API authentication failed: {error_msg} (code: {error_code}). Outbound IP: {egress_ip}")
                    except Exception as ip_check_error:
                        logger.error(f"API authentication failed: {error_msg} (code: {error_code}). Could not check outbound IP: {ip_check_error}")
                    
                    # Try failover to TRADE_BOT if enabled
                    if _should_failover(401):
                        logger.info("Attempting failover to TRADE_BOT for account summary...")
                        try:
                            fr = self._fallback_balance()
                            if fr and fr.status_code == 200:
                                data = fr.json()
                                logger.info("Successfully retrieved account summary via TRADE_BOT failover")
                                return {"code": 0, "result": data}
                        except Exception as failover_error:
                            logger.warning(f"Failover to TRADE_BOT failed: {failover_error}")
                    
                    # Build detailed error message with actionable guidance
                    error_details = f"Crypto.com API authentication failed: {error_msg} (code: {error_code})"
                    if error_code == 40101:
                        error_details += ". Possible causes: 1) Invalid API key/secret - verify EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET match your Crypto.com Exchange API credentials exactly, 2) Missing Read permission - enable 'Read' permission in Crypto.com Exchange API Key settings, 3) API key disabled/suspended - check API key status in Crypto.com Exchange settings."
                    elif error_code == 40103:
                        error_details += ". IP address not whitelisted. Add your server's IP address to the IP whitelist in Crypto.com Exchange API Key settings. Current outbound IP may differ from expected."
                    else:
                        error_details += ". Check: 1) API credentials (EXCHANGE_CUSTOM_API_KEY/SECRET), 2) IP whitelist in Crypto.com Exchange settings, 3) API key permissions and status."
                    
                    raise RuntimeError(error_details)
            
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"Response: {result}")
            
            # Crypto.com get-account-summary returns accounts directly in result.accounts
            # Crypto.com user-balance returns data in result.data format with position_balances
            accounts = []  # Initialize accounts before use
            if "result" in result:
                # Try get-account-summary format first (accounts array)
                if "accounts" in result["result"]:
                    accounts_data = result["result"]["accounts"]
                    for acc in accounts_data:
                        currency = acc.get("currency", "")
                        if currency:
                            # Include market_value from Crypto.com if available
                            market_value = acc.get("market_value") or acc.get("usd_value")
                            account_entry = {
                                "currency": currency,
                                "balance": str(acc.get("balance", "0")),
                                "available": str(acc.get("available", acc.get("balance", "0")))
                            }
                            if market_value:
                                account_entry["market_value"] = str(market_value)
                            accounts.append(account_entry)
                    logger.info(f"Retrieved {len(accounts)} account balances via get-account-summary")
                
                # If no accounts found in first format, try user-balance format (data array with position_balances)
                if len(accounts) == 0 and "data" in result["result"]:
                    data = result["result"]["data"]
                    logger.info("No accounts in result.accounts, trying result.data format with position_balances...")
                elif "data" in result["result"]:
                    # Also check data format even if we found some accounts (might have more data)
                    data = result["result"]["data"]
                    logger.info("Found accounts in result.accounts, but also checking result.data format...")
                else:
                    data = None
                
                # Extract position balances and convert to standard format
                # Crypto.com API provides: instrument_name, quantity, market_value, max_withdrawal_balance
                # and potentially loan/borrowed fields
                def _record_balance_entry(balance, account_type=None):
                    """
                    Normalize Crypto.com account balance entry into account data dict.
                    """
                    # Log ALL fields to discover loan-related data
                    logger.debug(f"Raw balance data from Crypto.com: {balance}")
                    
                    instrument = balance.get("instrument_name") or balance.get("currency") or ""
                    if not instrument:
                        # Skip malformed entries
                        return
                    
                    # FIX: Helper function to safely convert to Decimal, handling None and empty strings
                    # If API returns empty strings for optional fields, Decimal("") raises InvalidOperation
                    # The old code checked `if value` before converting, which skipped empty strings
                    def safe_decimal(value, default="0"):
                        """Convert value to Decimal, handling None and empty strings."""
                        if value is None or value == "":
                            return Decimal(default)
                        return Decimal(str(value))
                    
                    # Convert everything to Decimal via str to avoid float issues
                    # FIX: Use nested .get() calls to preserve legitimate zero values
                    # The old code only fell back when keys were missing (None), not when values were falsy (0)
                    # Using `or` chaining would incorrectly skip valid zero quantities (0 is falsy in Python)
                    # But we still need to handle empty strings, so normalize them to None after getting
                    quantity_raw = balance.get("quantity", balance.get("balance", "0"))
                    if quantity_raw == "":  # Empty string is invalid, treat as missing and use fallback
                        quantity_raw = balance.get("balance", "0")
                        if quantity_raw == "":
                            quantity_raw = "0"
                    
                    market_value_raw = balance.get("market_value", balance.get("usd_value", "0"))
                    if market_value_raw == "":  # Empty string is invalid, treat as missing and use fallback
                        market_value_raw = balance.get("usd_value", "0")
                        if market_value_raw == "":
                            market_value_raw = "0"
                    
                    # For max_withdrawal, preserve the original nested fallback logic
                    max_withdrawal_raw = balance.get("max_withdrawal_balance", balance.get("available", quantity_raw))
                    if max_withdrawal_raw == "":  # Empty string is invalid, treat as missing and use fallback
                        max_withdrawal_raw = balance.get("available", quantity_raw)
                        if max_withdrawal_raw == "":
                            max_withdrawal_raw = quantity_raw if quantity_raw != "" else "0"
                    
                    # Convert all numeric values to Decimal for precision
                    total = safe_decimal(quantity_raw)
                    market_value = safe_decimal(market_value_raw)
                    
                    # FIX: Always convert max_withdrawal_raw to Decimal (preserves zero values)
                    # The .get() chain above already provides appropriate fallbacks, so we always
                    # have a value here. The old code preserved zero values ("0" -> 0.0), so we must too.
                    # We convert to Decimal directly without checking if it's zero, because zero is
                    # a valid value that should be preserved (e.g., locked balance with no available).
                    max_withdrawal = safe_decimal(max_withdrawal_raw)
                    
                    # Extract loan/borrowed fields if present and convert to Decimal
                    # FIX: Handle empty strings gracefully - if API returns empty string, treat as missing
                    # The old code checked `if borrowed_balance` before converting, which skipped empty strings
                    # We must do the same to avoid InvalidOperation when converting empty strings to Decimal
                    
                    borrowed_balance_raw = balance.get("borrowed_balance")
                    borrowed_value_raw = balance.get("borrowed_value")
                    loan_amount_raw = balance.get("loan_amount")
                    loan_value_raw = balance.get("loan_value")
                    debt_amount_raw = balance.get("debt_amount")
                    debt_value_raw = balance.get("debt_value")
                    negative_balance_raw = balance.get("negative_balance")
                    
                    borrowed_balance = safe_decimal(borrowed_balance_raw)
                    borrowed_value = safe_decimal(borrowed_value_raw)
                    loan_amount = safe_decimal(loan_amount_raw)
                    loan_value = safe_decimal(loan_value_raw)
                    debt_amount = safe_decimal(debt_amount_raw)
                    debt_value = safe_decimal(debt_value_raw)
                    negative_balance = safe_decimal(negative_balance_raw)
                    
                    # Extract currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                    # Crypto.com may return instrument_name as "BTC_USDT" or just "BTC"
                    currency = instrument
                    if "_" in instrument:
                        # Extract base currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                        currency = instrument.split("_")[0].upper()
                    else:
                        currency = instrument.upper()
                    
                    # Calculate available and reserved using Decimal for precision
                    # FIX: Use max_withdrawal directly (even if it's Decimal("0")) - don't double-check
                    # The old code preserved zero values, so we must too. The check above already
                    # handles the case where max_withdrawal wasn't provided.
                    available = max_withdrawal
                    # FIX: Ensure locked is never negative (matches old code behavior)
                    # If API returns inconsistent data where max_withdrawal > total, cap locked at 0
                    # This prevents invalid negative locked balances that could occur from API inconsistencies
                    locked = max(Decimal("0"), total - available)
                    
                    # Check for negative balances (indicates borrowed/loan)
                    is_negative = total < 0
                    if is_negative:
                        logger.info(f"🔴 Found negative balance (loan): {currency} = {total}")
                    
                    # Include ALL available data from Crypto.com, using Decimal values for precision
                    account_data = {
                        "currency": currency,
                        "balance": str(total),
                        "available": str(available),
                        "reserved": str(locked),
                        "market_value": str(market_value),  # USD value from Crypto.com (Decimal precision)
                        "max_withdrawal": str(max_withdrawal),  # Decimal precision
                        "quantity": str(total),  # Use Decimal-calculated total for consistency
                    }
                    
                    if account_type:
                        account_data["account_type"] = account_type
                    
                    # Add loan/borrowed fields if present (using Decimal values)
                    if borrowed_balance != 0:
                        account_data["borrowed_balance"] = str(borrowed_balance)
                        logger.info(f"📊 Found borrowed_balance for {currency}: {borrowed_balance}")
                    if borrowed_value != 0:
                        account_data["borrowed_value"] = str(borrowed_value)
                        logger.info(f"📊 Found borrowed_value for {currency}: {borrowed_value}")
                    if loan_amount != 0:
                        account_data["loan_amount"] = str(loan_amount)
                        logger.info(f"📊 Found loan_amount for {currency}: {loan_amount}")
                    if loan_value != 0:
                        account_data["loan_value"] = str(loan_value)
                        logger.info(f"📊 Found loan_value for {currency}: {loan_value}")
                    if debt_amount != 0:
                        account_data["debt_amount"] = str(debt_amount)
                        logger.info(f"📊 Found debt_amount for {currency}: {debt_amount}")
                    if debt_value != 0:
                        account_data["debt_value"] = str(debt_value)
                        logger.info(f"📊 Found debt_value for {currency}: {debt_value}")
                    if is_negative or negative_balance != 0:
                        account_data["is_negative"] = True
                    
                    accounts.append(account_data)

                # Extract equity/wallet balance from position data or top-level result
                margin_equity_value = None
                
                # Check first position element for account-level equity (common in Crypto.com API)
                if data and len(data) > 0:
                    first_position = data[0] if isinstance(data, list) else data
                    if isinstance(first_position, dict):
                        equity_fields = ["equity", "net_equity", "wallet_balance", "margin_equity", "total_equity", 
                                        "available_equity", "account_equity", "balance_equity"]
                        for field in equity_fields:
                            if field in first_position:
                                value = first_position[field]
                                if value is not None:
                                    try:
                                        margin_equity_value = float(value) if isinstance(value, str) else float(value)
                                        logger.info(f"Found margin equity field '{field}' in first position element: {margin_equity_value}")
                                        break
                                    except (ValueError, TypeError):
                                        logger.debug(f"Could not parse equity field '{field}': {value}")
                
                # Check position data array for equity fields (per-position)
                if data:
                    if isinstance(data, list):
                        for position in data:
                            account_type = position.get("account_type")
                            if "position_balances" in position:
                                for balance in position["position_balances"]:
                                    _record_balance_entry(balance, account_type)
                            if "balances" in position:
                                for balance in position["balances"]:
                                    _record_balance_entry(balance, account_type)
                    elif isinstance(data, dict):
                        # Handle single position object
                        account_type = data.get("account_type")
                        if "position_balances" in data:
                            for balance in data["position_balances"]:
                                _record_balance_entry(balance, account_type)
                        if "balances" in data:
                            for balance in data["balances"]:
                                _record_balance_entry(balance, account_type)
                    
                    # Check position-level equity fields
                    if margin_equity_value is None:
                        equity_fields = ["equity", "net_equity", "wallet_balance", "margin_equity", "total_equity", 
                                        "available_equity", "account_equity", "balance_equity"]
                        for field in equity_fields:
                            if field in position:
                                value = position[field]
                                if value is not None:
                                    try:
                                        margin_equity_value = float(value) if isinstance(value, str) else float(value)
                                        logger.info(f"Found margin equity field '{field}' in position data: {margin_equity_value}")
                                        break
                                    except (ValueError, TypeError):
                                        logger.debug(f"Could not parse equity field '{field}': {value}")
                
                logger.info(f"Retrieved {len(accounts)} account balances (after processing both formats)")
                
                # Extract top-level equity/wallet balance fields if present
                # Crypto.com margin wallet may provide pre-computed NET balance
                response_data = {"accounts": accounts}
                
                # Check result["result"] for equity fields (if not found in position data)
                if margin_equity_value is None:
                    result_data = result.get("result", {})
                    if isinstance(result_data, dict):
                        # Check for equity/wallet balance fields (various possible names)
                        equity_fields = ["equity", "net_equity", "wallet_balance", "margin_equity", "total_equity", 
                                        "available_equity", "account_equity", "balance_equity"]
                        for field in equity_fields:
                            if field in result_data:
                                value = result_data[field]
                                if value is not None:
                                    try:
                                        # Convert to float if it's a string
                                        margin_equity_value = float(value) if isinstance(value, str) else float(value)
                                        logger.info(f"Found margin equity field '{field}' in result: {margin_equity_value}")
                                        break  # Use first found field
                                    except (ValueError, TypeError):
                                        logger.debug(f"Could not parse equity field '{field}': {value}")
                
                if margin_equity_value is not None:
                    response_data["margin_equity"] = margin_equity_value
                
                return response_data
            else:
                logger.error(f"Unexpected response format: {result}")
                raise ValueError(f"Invalid response format: {result}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting account balance: {e}")
            # NO SIMULATED DATA - Raise error instead
            raise RuntimeError(f"Failed to get account balance from Crypto.com: {e}")
        except Exception as e:
            logger.error(f"Error getting account balance: {e}")
            # NO SIMULATED DATA - Re-raise error
            raise
    
    def get_open_orders(self, page: int = 0, page_size: int = 200) -> dict:
        """Get all open/pending orders"""
        # NOTE: Reading open orders must NOT depend on LIVE_TRADING. We still need real-time
        # exchange state even when order placement is disabled. Keep LIVE_TRADING gating only
        # for write operations (place/cancel).
        self._refresh_runtime_flags()

        method = "private/get-open-orders"
        params = {
            "page": page,
            "page_size": page_size
            }
        
        # Use proxy if enabled
        if self.use_proxy:
            logger.info("Using PROXY to get open orders")
            try:
                result = self._call_proxy(method, params)
                
                # Check if result is an error response (401 authentication failure)
                if isinstance(result, dict) and result.get("code") in [40101, 40103]:
                    logger.warning(f"Proxy returned authentication error: {result.get('message')} - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        fr = self._fallback_open_orders()
                        if fr.status_code == 200:
                            data = fr.json()
                            orders = data.get("orders", [])
                            logger.info(f"Failover successful: retrieved {len(orders)} orders from TRADE_BOT")
                            return {"data": orders if isinstance(orders, list) else []}
                        else:
                            logger.error(f"TRADE_BOT failover failed with status {fr.status_code}")
                    logger.error("Failover not available or enabled")
                    return {"data": []}
                
                # Handle successful proxy response
                if isinstance(result, dict) and "result" in result and "data" in result["result"]:
                    data = result["result"]["data"]
                    logger.info(f"Successfully retrieved {len(data) if isinstance(data, list) else 0} open orders via proxy")
                    return {"data": data}
                else:
                    logger.warning(f"Unexpected proxy response: {result} - attempting failover")
                    if _should_failover(500):
                        fr = self._fallback_open_orders()
                        if fr.status_code == 200:
                            data = fr.json()
                            orders = data.get("orders", [])
                            logger.info(f"Failover successful: retrieved {len(orders)} orders from TRADE_BOT")
                            return {"data": orders if isinstance(orders, list) else []}
                    return {"data": []}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Proxy error: {e} - attempting failover to TRADE_BOT")
                if _should_failover(None, e):
                    fr = self._fallback_open_orders()
                    if fr.status_code == 200:
                        data = fr.json()
                        orders = data.get("orders", [])
                        logger.info(f"Failover successful: retrieved {len(orders)} orders from TRADE_BOT")
                        return {"data": orders if isinstance(orders, list) else []}
                logger.error("Failover not available or enabled")
                return {"data": []}
        
        # Check if API credentials are configured
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not configured. Cannot fetch open orders.")
            # IMPORTANT: return without 'data' so callers treat this as API failure
            # and preserve existing cache/state (avoid marking everything CANCELLED).
            return {"error": "API credentials not configured"}
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method}")
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.get_open_orders")
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.error(f"Authentication failed: {error_code} - {error_msg}")
                return {"error": f"Authentication failed: {error_code} - {error_msg}"}
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully retrieved open orders")
            logger.debug(f"Response: {result}")
            
            # Crypto.com returns {"result": {"data": [...]}}
            data = result.get("result", {}).get("data", [])
            return {"data": data}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting open orders: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return {"error": str(e)}

    def get_trigger_orders(self, page: int = 0, page_size: int = 200) -> dict:
        """Get trigger-based (TP/SL) open orders."""
        # NOTE: Reading trigger orders must NOT depend on LIVE_TRADING.
        self._refresh_runtime_flags()

        # Check if trigger orders are available for this account
        if not self._check_trigger_orders_health():
            logger.debug("Trigger orders not available for this account, returning empty list")
            return {"data": []}

        method = "private/get-trigger-orders"
        params = {
            "page": page,
            "page_size": page_size
        }

        if self.use_proxy:
            logger.info("Using PROXY to get trigger orders")
            try:
                result = self._call_proxy(method, params)
                if isinstance(result, dict) and result.get("code") in [40101, 40103]:
                    logger.warning(f"Proxy authentication error while fetching trigger orders: {result.get('message')}")
                    return {"data": []}

                if isinstance(result, dict) and "result" in result and "data" in result["result"]:
                    data = result["result"]["data"]
                    logger.info(f"Successfully retrieved {len(data) if isinstance(data, list) else 0} trigger orders via proxy")
                    return {"data": data if isinstance(data, list) else []}

                logger.warning(f"Unexpected proxy response for trigger orders: {result}")
                return {"data": []}
            except requests.exceptions.RequestException as exc:
                logger.error(f"Proxy trigger orders error: {exc}")
                return {"data": []}

        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not configured. Returning empty trigger orders.")
            return {"data": []}

        payload = self.sign_request(method, params)
        try:
            url = f"{self.base_url}/{method}"
            response = http_post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
                calling_module="crypto_com_trade.get_order_history"
            )
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                logger.error(f"Authentication failed for trigger orders: {error_data}")

                # Check if this is a permanent feature limitation (not just temporary auth issue)
                if error_code == 40101:
                    # Set feature flag that trigger orders are not available
                    self._trigger_orders_available = False
                    logger.warning(
                        "⚠️ Trigger orders not available for this account (40101 auth failure). "
                        "SL/TP will use STOP_LIMIT/TAKE_PROFIT_LIMIT orders instead. "
                        "Setting TRIGGER_ORDERS_ENABLED=false"
                    )
                    # Send system alert once per 24h
                    self._send_trigger_orders_unavailable_alert()
                return {"data": []}

            response.raise_for_status()
            result = response.json()
            data = result.get("result", {}).get("data", [])
            logger.info(f"Retrieved {len(data) if isinstance(data, list) else 0} trigger orders from Crypto.com")
            return {"data": data if isinstance(data, list) else []}
        except requests.exceptions.RequestException as exc:
            logger.error(f"Network error getting trigger orders: {exc}")
            return {"data": []}
        except Exception as exc:
                logger.error(f"Error getting trigger orders: {exc}")
                return {"data": []}

    def _check_trigger_orders_health(self) -> bool:
        """Check if trigger orders are available for this account (once per 24h cache)."""
        import time
        current_time = time.time()

        # Check cache first
        if current_time - self._last_trigger_health_check < self._trigger_health_check_interval:
            return self._trigger_orders_available

        self._last_trigger_health_check = current_time

        # Perform minimal health check - try to get trigger orders with minimal params
        try:
            method = "private/get-trigger-orders"
            params = {"page": 0, "page_size": 1}  # Minimal request

            if self.use_proxy:
                result = self._call_proxy(method, params)
                if isinstance(result, dict) and result.get("code") == 0:
                    self._trigger_orders_available = True
                    return True
                elif isinstance(result, dict) and result.get("code") == 40101:
                    self._trigger_orders_available = False
                    return False
            else:
                if not self.api_key or not self.api_secret:
                    self._trigger_orders_available = False
                    return False

                payload = self.sign_request(method, params)
                url = f"{self.base_url}/{method}"
                response = http_post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=5,  # Short timeout for health check
                    calling_module="crypto_com_trade.health_check"
                )

                if response.status_code == 200:
                    self._trigger_orders_available = True
                    return True
                elif response.status_code == 401:
                    error_data = response.json()
                    if error_data.get("code") == 40101:
                        self._trigger_orders_available = False
                        return False

            # If we get here, assume available (don't change cached state)
            return self._trigger_orders_available

        except Exception as e:
            logger.debug(f"Trigger orders health check failed: {e}")
            # On error, assume available to avoid blocking functionality
            return True

    def _send_trigger_orders_unavailable_alert(self):
        """Send system alert about trigger orders being unavailable (once per 24h)."""
        import time
        current_time = time.time()

        # Only send alert once per 24 hours
        if current_time - self._last_trigger_alert_time < 86400:  # 24 hours
            return

        self._last_trigger_alert_time = current_time

        try:
            from app.services.telegram_notifier import telegram_notifier
            alert_msg = (
                "🚫 <b>TRIGGER ORDERS NOT AVAILABLE</b>\n\n"
                "This account does not support trigger orders (40101 auth failure).\n"
                "SL/TP orders will use STOP_LIMIT/TAKE_PROFIT_LIMIT as fallback.\n\n"
                "<i>This alert is sent once per 24h.</i>"
            )
            telegram_notifier.send_message(alert_msg)
            logger.info("✅ Sent system alert: Trigger orders not available")
        except Exception as e:
            logger.warning(f"Failed to send trigger orders unavailable alert: {e}")

    def _send_conditional_orders_api_disabled_alert(self, *, code: int, message: str) -> None:
        """
        Alert when conditional order placement is disabled at the account level (code=140001 API_DISABLED).
        Rate-limited (once per 24h) using the same throttle as other trigger-order capability alerts.
        """
        import time

        current_time = time.time()
        if current_time - self._last_trigger_alert_time < 86400:
            return

        self._last_trigger_alert_time = current_time

        try:
            from app.services.telegram_notifier import telegram_notifier

            safe_msg = (message or "").strip()
            if len(safe_msg) > 240:
                safe_msg = safe_msg[:240] + "…"
            alert_msg = (
                "🚫 <b>CONDITIONAL ORDERS API DISABLED</b>\n\n"
                "Crypto.com rejected STOP_LIMIT / TAKE_PROFIT_LIMIT with API_DISABLED.\n"
                f"code={code} message={safe_msg}\n\n"
                "Impact:\n"
                "- SL/TP trigger orders cannot be created via API for this account.\n"
                "- The backend will stop retrying variants until the next periodic health check.\n\n"
                "<i>This alert is sent once per 24h.</i>"
            )
            telegram_notifier.send_message(alert_msg)
            logger.info("✅ Sent system alert: Conditional orders API_DISABLED")
        except Exception as e:
            logger.warning(f"Failed to send conditional orders API_DISABLED alert: {e}")

    @staticmethod
    def _normalize_price_str(x: Any) -> str:
        """
        Normalize a numeric-like value into a plain decimal string:
        - No scientific notation
        - Trim trailing zeros
        """
        try:
            d = x if isinstance(x, Decimal) else Decimal(str(x))
        except Exception:
            # Last resort: string fallback (still strip whitespace)
            s = str(x).strip()
            return s

        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s in ("-0", "-0.0", ""):
            s = "0"
        return s

    @staticmethod
    def _extract_exchange_error(resp_obj: Any) -> Tuple[Optional[int], Optional[str]]:
        """
        Extract (code, message) from a Crypto.com style response body.
        Returns (None, None) if it doesn't look like an exchange error payload.
        """
        if not isinstance(resp_obj, dict):
            return None, None
        code = resp_obj.get("code")
        msg = resp_obj.get("message")
        try:
            code_int = int(code) if code is not None else None
        except Exception:
            code_int = None
        msg_str = str(msg) if msg is not None else None
        return code_int, msg_str

    def _mark_trigger_orders_unavailable(self, *, code: int, message: str) -> None:
        """
        Mark trigger/conditional order capability unavailable for 24h and emit a rate-limited alert.
        """
        import time

        self._trigger_orders_available = False
        self._last_trigger_health_check = time.time()
        self._send_conditional_orders_api_disabled_alert(code=code, message=message or "")

    def _check_conditional_orders_circuit_breaker(self) -> bool:
        """
        Conditional order placement circuit breaker (used for SL/TP creation).

        This must NOT depend on `private/get-trigger-orders` health, because that endpoint availability
        is independent from the ability to place `STOP_LIMIT` / `TAKE_PROFIT_LIMIT`.

        We only block when we have recently observed `API_DISABLED` (140001) and have explicitly
        marked conditional orders unavailable.
        """
        import time

        interval = float(getattr(self, "_trigger_health_check_interval", 86400) or 86400)
        last = float(getattr(self, "_last_conditional_orders_check", 0.0) or 0.0)
        available = bool(getattr(self, "_conditional_orders_available", True))

        if available:
            return True

        # If we've marked unavailable, allow retries once the interval expires.
        if (time.time() - last) >= interval:
            try:
                self._conditional_orders_available = True
            except Exception:
                pass
            return True

        return False

    def _mark_conditional_orders_unavailable(self, *, code: int, message: str) -> None:
        """Mark conditional order placement unavailable for 24h and emit a rate-limited alert."""
        import time

        self._conditional_orders_available = False
        self._last_conditional_orders_check = time.time()
        self._send_conditional_orders_api_disabled_alert(code=code, message=message or "")

    def _build_sltp_variant_grid(self, *, max_variants: int = 220) -> List[dict]:
        """
        Build a bounded-but-broad grid of SL/TP order creation format variations.
        This is intentionally focused (format + key variations), and is only used on failure.
        """
        order_types = ["STOP_LIMIT", "TAKE_PROFIT_LIMIT"]
        # Exchange v1 docs for `private/create-order` use `ref_price` as the trigger price field.
        # Historical/alternate endpoints and older implementations sometimes use `trigger_price` / `stop_price` / `triggerPrice`.
        trigger_keys = ["ref_price", "trigger_price", "stop_price", "triggerPrice"]
        value_type_modes = ["str", "num"]  # string vs numeric
        tif_values = [None, "GOOD_TILL_CANCEL", "GTC", "IOC", "FOK"]
        flag_values = [None, True, False]
        client_id_keys = [None, "client_oid", "client_order_id"]
        # Prefer minimal payload first; some endpoints reject trigger_condition entirely.
        trigger_condition_modes = ["omit", "space", "nospace"]
        ref_price_modes = ["match_trigger", "use_ref_price"]
        include_price_modes = [True, False]  # mainly relevant for STOP_LIMIT

        buckets: Dict[str, List[dict]] = {t: [] for t in order_types}
        for op_type in order_types:
            for trig_key in trigger_keys:
                for vtype in value_type_modes:
                    for tif in tif_values:
                        for reduce_only in flag_values:
                            for post_only in flag_values:
                                for client_key in client_id_keys:
                                    for tc_mode in trigger_condition_modes:
                                        for ref_mode in ref_price_modes:
                                            for include_price in include_price_modes:
                                                # Avoid explosion for TP: include_price=False isn't meaningful (TP needs price).
                                                if op_type == "TAKE_PROFIT_LIMIT" and not include_price:
                                                    continue
                                                # Keep STOP_LIMIT "omit price" only for non-standard trigger keys (borrowed from probe).
                                                if op_type == "STOP_LIMIT" and not include_price and trig_key == "trigger_price":
                                                    continue

                                                variant_id = (
                                                    f"{op_type}|trigkey={trig_key}|vtype={vtype}|"
                                                    f"tif={tif or 'none'}|ro={reduce_only if reduce_only is not None else 'na'}|"
                                                    f"po={post_only if post_only is not None else 'na'}|"
                                                    f"clid={client_key or 'none'}|tc={tc_mode}|ref={ref_mode}|"
                                                    f"price={int(bool(include_price))}"
                                                )
                                                buckets[op_type].append(
                                                    {
                                                        "variant_id": variant_id,
                                                        "order_type": op_type,
                                                        "trigger_key": trig_key,
                                                        "value_type": vtype,
                                                        "time_in_force": tif,
                                                        "reduce_only": reduce_only,
                                                        "post_only": post_only,
                                                        "client_id_key": client_key,
                                                        "trigger_condition_mode": tc_mode,
                                                        "ref_price_mode": ref_mode,
                                                        "include_price": bool(include_price),
                                                    }
                                                )
        # Cap per order type, then interleave so STOP_LIMIT and TAKE_PROFIT_LIMIT both get coverage.
        max_n = int(max_variants)
        for t in order_types:
            if buckets.get(t) and len(buckets[t]) > max_n:
                buckets[t] = buckets[t][:max_n]

        out: List[dict] = []
        max_total = max_n * max(1, len(order_types))
        while len(out) < max_total:
            progressed = False
            for t in order_types:
                if buckets.get(t):
                    out.append(buckets[t].pop(0))
                    progressed = True
                    if len(out) >= max_total:
                        break
            if not progressed:
                break
        return out

    def _create_order_try_variants(
        self,
        *,
        instrument_name: str,
        side: str,
        order_type: str,
        quantity: float,
        ref_price: float,
        trigger_price: float,
        limit_price: float,
        correlation_id: str,
        variants: List[dict],
        jsonl_path: str,
    ) -> dict:
        """
        Try many parameter-format variations for `private/create-order`.
        Collect every error and stop on first success.

        Returns:
          - {ok: True, order_id: str, variant_id: str, attempts: int, errors: [...]}
          - {ok: False, errors: [...], last_response: Any}
        """
        self._refresh_runtime_flags()

        # If we've already detected conditional orders are unavailable, skip retries.
        if not self._check_conditional_orders_circuit_breaker():
            return {
                "ok": False,
                "errors": [
                    {
                        "variant_id": "SKIPPED",
                        "http_status": None,
                        "code": 140001,
                        "message": "Conditional orders marked unavailable (cached).",
                        "exception": None,
                        "params_keys": [],
                    }
                ],
                "last_response": None,
            }

        method = "private/create-order"
        url = f"{self.base_url}/{method}"

        def _tif_normalize_for_exchange(x: Any) -> Optional[str]:
            """
            Normalize time_in_force values for Crypto.com.
            We sometimes generate shorthands (GTC/IOC/FOK) in the variant grid; map them to docs.
            """
            if x is None:
                return None
            s = str(x).strip().upper()
            if not s:
                return None
            if s == "GTC":
                return "GOOD_TILL_CANCEL"
            if s == "IOC":
                return "IMMEDIATE_OR_CANCEL"
            if s == "FOK":
                return "FILL_OR_KILL"
            return s

        def _try_create_order_list_single(*, base_variant: dict) -> Tuple[bool, Optional[str], Optional[int], Optional[str], Any]:
            """
            Try `private/create-order-list` with a single order in the list.
            This is a post-2025 migration-safe alternative path for trigger orders.
            Returns: (ok, order_id, code, message, raw_response)
            """
            # Build a minimal, docs-aligned order payload.
            # NOTE: Docs state "all numbers must be strings", so we always use the string forms here.
            tif_norm = _tif_normalize_for_exchange(base_variant.get("time_in_force"))
            order_payload: Dict[str, Any] = {
                "instrument_name": instrument_name,
                "side": (side or "").strip().upper(),
                "type": order_type,
                "quantity": qty_str,
                "price": limit_str,
                "trigger_price": trig_str,
            }
            # Optional client id: create-order-list uses client_oid (not client_order_id).
            if base_variant.get("client_id_key"):
                order_payload["client_oid"] = str(uuid.uuid4())
            if tif_norm:
                order_payload["time_in_force"] = tif_norm

            list_method = "private/create-order-list"
            list_params = {"contingency_type": "LIST", "order_list": [order_payload]}

            http_status_local: Optional[int] = None
            resp_obj_local: Any = None
            try:
                if self.use_proxy:
                    resp_obj_local = self._call_proxy(list_method, list_params)
                    http_status_local = 200 if isinstance(resp_obj_local, dict) else None
                else:
                    list_url = f"{self.base_url}/{list_method}"
                    payload = self.sign_request(list_method, list_params, _suppress_log=True)
                    resp = http_post(
                        list_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                        calling_module="crypto_com_trade.sltp_variants",
                    )
                    http_status_local = getattr(resp, "status_code", None)
                    try:
                        resp_obj_local = resp.json()
                    except Exception:
                        resp_obj_local = (getattr(resp, "text", "") or "")[:2000]

                code_local, msg_local = self._extract_exchange_error(resp_obj_local)

                # For create-order-list, per-order status is inside result[0].
                created_order_id_local: Optional[str] = None
                if isinstance(resp_obj_local, dict) and isinstance(resp_obj_local.get("result"), list) and resp_obj_local["result"]:
                    first = resp_obj_local["result"][0]
                    if isinstance(first, dict):
                        # Override code/message with per-order result if present.
                        try:
                            entry_code = first.get("code")
                            entry_msg = first.get("message")
                            if entry_code is not None:
                                code_local = int(entry_code)
                            if entry_msg is not None:
                                msg_local = str(entry_msg)
                        except Exception:
                            pass
                        created_order_id_local = first.get("order_id") or first.get("client_order_id")

                is_ok_local = bool(created_order_id_local) and (
                    (self.use_proxy and (code_local == 0 or code_local is None))
                    or ((not self.use_proxy) and (http_status_local == 200) and (code_local == 0 or code_local is None))
                )
                if is_ok_local:
                    return True, str(created_order_id_local), code_local, msg_local, resp_obj_local
                return False, None, code_local, msg_local, resp_obj_local
            except Exception as exc:
                return False, None, None, str(exc), resp_obj_local

        preferred_key = f"{instrument_name.upper()}|{order_type}|proxy={1 if self.use_proxy else 0}"
        preferred_variant_id = None
        preferred_method = None
        try:
            pref = self._sltp_preferred_variants.get(preferred_key) or {}
            preferred_variant_id = pref.get("variant_id")
            preferred_method = pref.get("api_method")
        except Exception:
            preferred_variant_id = None
            preferred_method = None

        if preferred_variant_id:
            variants = sorted(
                list(variants),
                key=lambda v: 0 if v.get("variant_id") == preferred_variant_id else 1,
            )

        errors: List[dict] = []
        last_response: Any = None
        attempts = 0

        # Pre-format values as strings for vtype=str variations.
        # IMPORTANT: Crypto.com can be strict about tick sizes/decimals (308 INVALID_PRICE).
        # Use existing normalizers (tick-aware) when possible, and fall back to plain decimals.
        side_upper_for_norm = (side or "").strip().upper()
        norm_kind = "STOP_LOSS" if order_type == "STOP_LIMIT" else "TAKE_PROFIT"

        qty_str = self.normalize_quantity(instrument_name, quantity) or self._normalize_price_str(quantity)
        trig_str = (
            self.normalize_price(instrument_name, trigger_price, side_upper_for_norm, order_type=norm_kind)
            or self._normalize_price_str(trigger_price)
        )
        limit_str = (
            self.normalize_price(instrument_name, limit_price, side_upper_for_norm, order_type=norm_kind)
            or self._normalize_price_str(limit_price)
        )
        ref_str = (
            self.normalize_price(instrument_name, ref_price, side_upper_for_norm, order_type=norm_kind)
            or self._normalize_price_str(ref_price)
        )

        def _trigger_condition_operator() -> str:
            side_upper = (side or "").strip().upper()
            if order_type == "STOP_LIMIT":
                return "<=" if side_upper == "SELL" else ">="
            return ">=" if side_upper == "SELL" else "<="

        op = _trigger_condition_operator()

        out_file = Path(jsonl_path)
        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        for v in variants:
            if v.get("order_type") != order_type:
                continue

            attempts += 1
            t0 = time.perf_counter()

            vtype = v.get("value_type")
            trig_key = v.get("trigger_key")
            if not isinstance(trig_key, str) or not trig_key:
                continue
            include_price = bool(v.get("include_price", True))

            params: Dict[str, Any] = {
                "instrument_name": instrument_name,
                "side": (side or "").strip().upper(),
                "type": order_type,
            }

            # Base numeric/string fields
            if vtype == "num":
                params["quantity"] = float(quantity)
                params[trig_key] = float(trigger_price)
                if include_price:
                    params["price"] = float(limit_price)
                # ref_price is numeric in num mode
                if trig_key == "ref_price":
                    # If we're using `ref_price` as the trigger field, keep it aligned to trigger_price.
                    params["ref_price"] = float(trigger_price)
                else:
                    if v.get("ref_price_mode") == "match_trigger":
                        params["ref_price"] = float(trigger_price)
                    else:
                        params["ref_price"] = float(ref_price)
                trig_val_for_tc = self._normalize_price_str(trigger_price)
            else:
                params["quantity"] = qty_str
                params[trig_key] = trig_str
                if include_price:
                    params["price"] = limit_str
                if trig_key == "ref_price":
                    params["ref_price"] = trig_str
                else:
                    if v.get("ref_price_mode") == "match_trigger":
                        params["ref_price"] = trig_str
                    else:
                        params["ref_price"] = ref_str
                trig_val_for_tc = trig_str

            # Optional fields
            tif = v.get("time_in_force")
            if tif is not None:
                params["time_in_force"] = tif
            if v.get("reduce_only") is not None:
                params["reduce_only"] = bool(v.get("reduce_only"))
            if v.get("post_only") is not None:
                params["post_only"] = bool(v.get("post_only"))
            client_key = v.get("client_id_key")
            if client_key:
                params[client_key] = str(uuid.uuid4())

            # trigger_condition formatting
            tc_mode = v.get("trigger_condition_mode")
            if tc_mode == "space":
                params["trigger_condition"] = f"{op} {trig_val_for_tc}"
            elif tc_mode == "nospace":
                params["trigger_condition"] = f"{op}{trig_val_for_tc}"
            else:
                # omit
                pass

            params_keys = sorted(list(params.keys()))

            http_status: Optional[int] = None
            resp_obj: Any = None
            resp_code: Optional[int] = None
            resp_message: Optional[str] = None
            exc_str: Optional[str] = None
            created_order_id: Optional[str] = None

            try:
                # If we previously discovered that create-order-list is the working path, try it first.
                if preferred_method == "private/create-order-list" and v.get("variant_id") == preferred_variant_id:
                    ok_list, order_id_list, code_list, msg_list, resp_obj_list = _try_create_order_list_single(
                        base_variant=v
                    )
                    if ok_list and order_id_list:
                        self._sltp_preferred_variants[preferred_key] = {
                            "variant_id": v.get("variant_id"),
                            "api_method": "private/create-order-list",
                        }
                        elapsed_ms = int((time.perf_counter() - t0) * 1000)
                        record = {
                            "correlation_id": correlation_id,
                            "variant_id": v.get("variant_id"),
                            "order_type": order_type,
                            "api_method": "private/create-order-list",
                            "params_keys": params_keys,
                            "http_status": 200,
                            "code": code_list,
                            "message": msg_list,
                            "elapsed_ms": elapsed_ms,
                            "created_order_id": str(order_id_list),
                        }
                        try:
                            with out_file.open("a", encoding="utf-8") as fp:
                                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                        return {
                            "ok": True,
                            "order_id": str(order_id_list),
                            "variant_id": v.get("variant_id"),
                            "attempts": attempts,
                            "errors": errors,
                        }

                if self.use_proxy:
                    # Proxy expects raw params (no signature).
                    resp_obj = self._call_proxy(method, params)
                    http_status = 200 if isinstance(resp_obj, dict) else None
                else:
                    payload = self.sign_request(method, params, _suppress_log=True)
                    resp = http_post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                        calling_module="crypto_com_trade.sltp_variants",
                    )
                    http_status = getattr(resp, "status_code", None)
                    try:
                        resp_obj = resp.json()
                    except Exception:
                        resp_obj = (getattr(resp, "text", "") or "")[:2000]

                resp_code, resp_message = self._extract_exchange_error(resp_obj)
                last_response = resp_obj

                if isinstance(resp_obj, dict) and isinstance(resp_obj.get("result"), dict):
                    created_order_id = (
                        resp_obj["result"].get("order_id")
                        or resp_obj["result"].get("client_order_id")
                        or resp_obj["result"].get("id")
                    )

                # Success criteria:
                # - Proxy: code==0 and order_id present
                # - Direct: HTTP 200 and body code==0 (or missing) and order_id present
                is_ok = bool(created_order_id) and (
                    (self.use_proxy and (resp_code == 0 or resp_code is None))
                    or ((not self.use_proxy) and (http_status == 200) and (resp_code == 0 or resp_code is None))
                )

                if is_ok:
                    # Persist preferred variant for future reuse
                    self._sltp_preferred_variants[preferred_key] = {
                        "variant_id": v.get("variant_id"),
                        "api_method": "private/create-order",
                    }
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    record = {
                        "correlation_id": correlation_id,
                        "variant_id": v.get("variant_id"),
                        "order_type": order_type,
                        "api_method": "private/create-order",
                        "params_keys": params_keys,
                        "http_status": http_status,
                        "code": resp_code,
                        "message": resp_message,
                        "elapsed_ms": elapsed_ms,
                        "created_order_id": str(created_order_id),
                    }
                    try:
                        with out_file.open("a", encoding="utf-8") as fp:
                            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
                    except Exception:
                        pass

                    return {
                        "ok": True,
                        "order_id": str(created_order_id),
                        "variant_id": v.get("variant_id"),
                        "attempts": attempts,
                        "errors": errors,
                    }

                # If create-order returns API_DISABLED, try the post-migration batch endpoint once
                # before concluding the account is unable to place trigger orders.
                if resp_code == 140001:
                    ok_list, order_id_list, code_list, msg_list, resp_obj_list = _try_create_order_list_single(
                        base_variant=v
                    )
                    # Write a record for the order-list attempt too (even on failure).
                    elapsed_ms_list = int((time.perf_counter() - t0) * 1000)
                    try:
                        record_list = {
                            "correlation_id": correlation_id,
                            "variant_id": v.get("variant_id"),
                            "order_type": order_type,
                            "api_method": "private/create-order-list",
                            "params_keys": sorted(
                                [
                                    "instrument_name",
                                    "side",
                                    "type",
                                    "quantity",
                                    "price",
                                    "trigger_price",
                                ]
                            ),
                            "http_status": 200,
                            "code": code_list,
                            "message": msg_list,
                            "elapsed_ms": elapsed_ms_list,
                            "created_order_id": str(order_id_list) if order_id_list else None,
                        }
                        with out_file.open("a", encoding="utf-8") as fp:
                            fp.write(json.dumps(record_list, ensure_ascii=False) + "\n")
                    except Exception:
                        pass

                    if ok_list and order_id_list:
                        self._sltp_preferred_variants[preferred_key] = {
                            "variant_id": v.get("variant_id"),
                            "api_method": "private/create-order-list",
                        }
                        return {
                            "ok": True,
                            "order_id": str(order_id_list),
                            "variant_id": v.get("variant_id"),
                            "attempts": attempts,
                            "errors": errors,
                        }

                    # Stop early on API_DISABLED after both paths fail.
                    self._mark_conditional_orders_unavailable(code=140001, message=str(msg_list or resp_message or "API_DISABLED"))

            except Exception as e:
                exc_str = str(e)
                last_response = resp_obj

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            record = {
                "correlation_id": correlation_id,
                "variant_id": v.get("variant_id"),
                "order_type": order_type,
                "api_method": "private/create-order",
                "params_keys": params_keys,
                "http_status": http_status,
                "code": resp_code,
                "message": resp_message,
                "elapsed_ms": elapsed_ms,
                "created_order_id": str(created_order_id) if created_order_id else None,
            }
            try:
                with out_file.open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass

            err_rec = {
                "variant_id": v.get("variant_id"),
                "http_status": http_status,
                "code": resp_code,
                "message": resp_message,
                "exception": exc_str,
                "params_keys": params_keys,
            }
            errors.append(err_rec)

            if resp_code == 140001:
                # Stop retry loop once we see API_DISABLED.
                break

        return {"ok": False, "errors": errors, "last_response": last_response}

    def create_stop_loss_take_profit_with_variations(
        self,
        *,
        instrument_name: str,
        side: str,
        quantity: float,
        ref_price: float,
        stop_loss_price: Optional[float],
        take_profit_price: Optional[float],
        correlation_id: str,
        existing_sl_order_id: Optional[str] = None,
        existing_tp_order_id: Optional[str] = None,
        max_variants_per_order: int = 220,
    ) -> dict:
        """
        Failure-only fallback: attempt SL and/or TP creation with many format variations.
        Keeps the success-path unchanged by being invoked only after a normal attempt fails.
        """
        entry_side = (side or "").strip().upper()
        if entry_side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL (entry side)")

        closing_side = "SELL" if entry_side == "BUY" else "BUY"
        variants = self._build_sltp_variant_grid(max_variants=int(max_variants_per_order))

        jsonl_path = f"/tmp/sltp_variants_{correlation_id}.jsonl"

        # SL (STOP_LIMIT)
        sl_result = {
            "ok": bool(existing_sl_order_id),
            "order_id": existing_sl_order_id,
            "variant_id": None,
            "attempts": 0,
            "errors": [],
        }
        if stop_loss_price is not None and not existing_sl_order_id:
            # STOP_LIMIT: trigger and ref are typically the SL price; price can equal trigger as baseline.
            sl_result = self._create_order_try_variants(
                instrument_name=instrument_name,
                side=closing_side,
                order_type="STOP_LIMIT",
                quantity=float(quantity),
                ref_price=float(ref_price),
                trigger_price=float(stop_loss_price),
                limit_price=float(stop_loss_price),
                correlation_id=correlation_id,
                variants=variants,
                jsonl_path=jsonl_path,
            )

        # TP (TAKE_PROFIT_LIMIT)
        tp_result = {
            "ok": bool(existing_tp_order_id),
            "order_id": existing_tp_order_id,
            "variant_id": None,
            "attempts": 0,
            "errors": [],
        }
        if take_profit_price is not None and not existing_tp_order_id:
            # TAKE_PROFIT_LIMIT: trigger_price and price should match TP value.
            tp_result = self._create_order_try_variants(
                instrument_name=instrument_name,
                side=closing_side,
                order_type="TAKE_PROFIT_LIMIT",
                quantity=float(quantity),
                ref_price=float(ref_price),
                trigger_price=float(take_profit_price),
                limit_price=float(take_profit_price),
                correlation_id=correlation_id,
                variants=variants,
                jsonl_path=jsonl_path,
            )

        # Flatten for structured logging at call site
        return {
            "correlation_id": correlation_id,
            "jsonl_path": jsonl_path,
            "ok_sl": bool(sl_result.get("ok")),
            "ok_tp": bool(tp_result.get("ok")),
            "sl_order_id": sl_result.get("order_id"),
            "tp_order_id": tp_result.get("order_id"),
            "sl_variant_id": sl_result.get("variant_id"),
            "tp_variant_id": tp_result.get("variant_id"),
            "sl_attempts": int(sl_result.get("attempts") or 0),
            "tp_attempts": int(tp_result.get("attempts") or 0),
            "sl_errors": sl_result.get("errors") or [],
            "tp_errors": tp_result.get("errors") or [],
        }

    def _map_incoming_order(self, raw: dict, is_trigger: bool) -> UnifiedOpenOrder:
        """
        Normalize a raw order payload (standard or trigger) into UnifiedOpenOrder.
        """

        def _optional_decimal(value):
            if value in (None, ""):
                return None
            if isinstance(value, Decimal):
                return value
            try:
                value_str = str(value).strip()
                if not value_str:
                    return None
                return Decimal(value_str)
            except (InvalidOperation, ValueError, TypeError):
                return None

        symbol = (raw.get("instrument_name") or raw.get("symbol") or "").upper()
        side = (raw.get("side") or "BUY").upper()
        order_type = raw.get("order_type") or raw.get("type") or ("TAKE_PROFIT_LIMIT" if is_trigger else "LIMIT")

        quantity_value = raw.get("quantity") or raw.get("order_quantity") or raw.get("qty") or raw.get("size") or 0
        try:
            quantity = Decimal(str(quantity_value))
        except (InvalidOperation, ValueError, TypeError):
            quantity = Decimal("0")

        price = _optional_decimal(
            raw.get("limit_price")
            or raw.get("price")
            or raw.get("ref_price")
            or raw.get("reference_price")
        )
        trigger_price = _optional_decimal(
            raw.get("trigger_price")
            or raw.get("stop_price")
            or raw.get("trigger_price_value")
        )

        status = (raw.get("status") or raw.get("order_status") or "NEW").upper()
        order_id = str(
            raw.get("order_id")
            or raw.get("id")
            or raw.get("orderId")
            or raw.get("client_oid")
            or raw.get("clientOrderId")
            or uuid.uuid4()
        )
        client_oid = raw.get("client_oid") or raw.get("clientOrderId")

        # Format timestamps as ISO strings (required by app.services.open_orders.UnifiedOpenOrder)
        created_at_str = _format_timestamp(raw.get("create_time") or raw.get("order_time") or raw.get("created_at"))
        updated_at_str = _format_timestamp(raw.get("update_time") or raw.get("updated_at"))

        return UnifiedOpenOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,  # Changed from 'type' to 'order_type'
            status=status,
            price=price,
            trigger_price=trigger_price,
            quantity=quantity,
            is_trigger=is_trigger,
            trigger_type=raw.get("trigger_type") or raw.get("trigger_by"),
            trigger_condition=raw.get("trigger_condition"),
            client_oid=client_oid,
            created_at=created_at_str,  # ISO string format
            updated_at=updated_at_str,  # ISO string format
            source="trigger" if is_trigger else "standard",
            metadata=raw,  # Changed from 'raw' to 'metadata'
        )

    def get_all_unified_orders(self) -> List[UnifiedOpenOrder]:
        """
        Fetch open orders (standard + trigger) and normalize them into a single list.
        """
        combined: List[UnifiedOpenOrder] = []
        seen_ids = set()
        stats = {"normal": 0, "trigger": 0}

        def _extract_orders(response: Optional[dict]) -> List[dict]:
            if not response:
                return []
            if isinstance(response.get("data"), list):
                return response["data"]
            if isinstance(response.get("orders"), list):
                return response["orders"]
            return []

        def _append_orders(raw_orders: List[dict], is_trigger: bool):
            for raw in raw_orders:
                try:
                    mapped = self._map_incoming_order(raw, is_trigger=is_trigger)
                except Exception as exc:
                    logger.warning(f"Failed to normalize order payload: {exc}")
                    continue
                if mapped.order_id in seen_ids:
                    continue
                seen_ids.add(mapped.order_id)
                combined.append(mapped)
                stats["trigger" if is_trigger else "normal"] += 1

        page = 0
        page_size = 200
        while True:
            response = self.get_open_orders(page=page, page_size=page_size)
            raw_orders = _extract_orders(response)
            if not raw_orders:
                break
            _append_orders(raw_orders, is_trigger=False)
            if len(raw_orders) < page_size:
                break
            page += 1

        page = 0
        try:
            while True:
                response = self.get_trigger_orders(page=page, page_size=page_size)
                raw_orders = _extract_orders(response)
                if not raw_orders:
                    break
                _append_orders(raw_orders, is_trigger=True)
                if len(raw_orders) < page_size:
                    break
                page += 1
        except Exception as exc:
            logger.error(f"Trigger orders fetch failed, continuing with standard orders only: {exc}")

        logger.info(
            f"Unified open orders fetched: normal={stats['normal']}, trigger={stats['trigger']}, total={len(combined)}"
        )
        return combined
    
    def get_order_history(self, page_size: int = 200, start_time: int = None, end_time: int = None, page: int = 0) -> dict:
        """Get order history (executed orders)"""
        # According to Crypto.com docs, this endpoint accepts optional parameters:
        # - start_time: start time in milliseconds (optional)
        # - end_time: end time in milliseconds (optional)
        # - page_size: number of results per page (optional)
        # - page: page number (optional)
        # Without params, it only returns 1 order. We need to use date filters to get all orders.
        
        # NOTE: Reading order history must NOT depend on LIVE_TRADING.
        self._refresh_runtime_flags()
        
        # Use proxy if enabled
        if self.use_proxy:
            logger.info("Using PROXY to get order history")
            method = "private/get-order-history"
            params = {}  # This endpoint works without params
            result = self._call_proxy(method, params)
            
            # Handle proxy response - try multiple possible response formats
            if "result" in result:
                # Try "order_list" first (from old working server)
                if "order_list" in result["result"]:
                    data = result["result"]["order_list"]
                    return {"data": data}
                # Try "data" second
                elif "data" in result["result"]:
                    data = result["result"]["data"]
                    return {"data": data}
            
            logger.warning(f"Proxy error or empty response for order history: {result}")
            # Return empty array if API error
            return {"data": []}
        
        # Check if API credentials are configured
        # NOTE: Do NOT return simulated data here; it hides operational issues and can mask missing SL/TP.
        if not self.api_key or not self.api_secret:
            logger.error("API credentials not configured. Cannot get order history from Crypto.com.")
            raise RuntimeError("Crypto.com API credentials not configured (EXCHANGE_CUSTOM_API_KEY/SECRET).")
        
        # Use private/get-order-history endpoint (not advanced - for regular orders)
        # IMPORTANT: Without params, it only returns 1 order. We need date filters to get all orders.
        method = "private/get-order-history"
        
        # Build params - use date range if provided, otherwise get last 30 days
        # IMPORTANT: Crypto.com API requires all numeric params to be integers, not strings
        params = {}
        if start_time is not None or end_time is not None:
            if start_time is not None:
                params['start_time'] = int(start_time)  # Ensure integer type
            if end_time is not None:
                params['end_time'] = int(end_time)  # Ensure integer type
            if page_size:
                params['page_size'] = int(page_size)  # Ensure integer type
            params['page'] = int(page)  # Ensure integer type
        else:
            # Default: Get last 30 days of orders
            from datetime import datetime, timedelta
            end_time_ms = int(time.time() * 1000)
            start_time_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
            params = {
                'start_time': int(start_time_ms),  # Ensure integer type
                'end_time': int(end_time_ms),  # Ensure integer type
                'page_size': int(page_size),  # Ensure integer type
                'page': int(page)  # Ensure integer type
            }
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method} with params: {list(params.keys())}")
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.get_order_history")
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.error(f"Authentication failed: {error_code} - {error_msg}")
                
                # Try fallback if enabled
                if _should_failover(401, None):
                    logger.info("Attempting fallback to TRADE_BOT for order history")
                    try:
                        fallback_response = self._fallback_history()
                        if fallback_response.status_code == 200:
                            fallback_data = fallback_response.json()
                            logger.info("Successfully retrieved order history from TRADE_BOT fallback")
                            # TRADE_BOT returns {"orders": [...]} format
                            if "orders" in fallback_data:
                                return {"data": fallback_data["orders"]}
                            return {"data": fallback_data.get("data", [])}
                    except Exception as fallback_err:
                        logger.warning(f"Fallback to TRADE_BOT failed: {fallback_err}")
                
                return {"data": []}
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully retrieved order history")
            logger.debug(f"Response keys: {list(result.keys())}")
            
            # Crypto.com returns {"result": {"data": [...]}} or {"result": {"order_list": [...]}}
            if "result" in result:
                if "data" in result["result"]:
                    data = result["result"]["data"]
                    return {"data": data}
                elif "order_list" in result["result"]:
                    data = result["result"]["order_list"]
                    return {"data": data}
            
            logger.warning(f"Unexpected response format: {result}")
            return {"data": []}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting order history: {e}")
            return {"data": []}
        except Exception as e:
            logger.error(f"Error getting order history: {e}")
            return {"data": []}
    
    def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        *, 
        is_margin: bool = False, 
        leverage: Optional[float] = None, 
        dry_run: bool = True,
        source: str = "AUTO"  # "AUTO" for bot orders, "TEST" for test scripts
    ) -> dict:
        """
        Place market order (SPOT or MARGIN)
        
        MARGIN ORDER CONSTRUCTION:
        =========================
        For margin orders, we use the same endpoint as spot orders: 'private/create-order'
        
        MARGIN-SPECIFIC PARAMETERS:
        - leverage: Required string parameter (e.g., "10") indicating 10x leverage
        - The presence of 'leverage' in params makes the order a margin order
        
        SIZE PARAMETERS (same for spot and margin):
        - BUY orders: use 'notional' (amount in quote currency, e.g., USDT)
        - SELL orders: use 'quantity' (amount in base currency, e.g., BTC)
        
        REQUEST STRUCTURE:
        {
            "instrument_name": "BTC_USDT",
            "side": "BUY",              # UPPERCASE
            "type": "MARKET",
            "notional": "1000.00",      # For BUY orders (amount in USDT)
            "quantity": "0.1",          # For SELL orders (amount in BTC)
            "client_oid": "<uuid>",
            "leverage": "10"            # REQUIRED for margin orders (string, not number)
        }
        
        NOTE: Crypto.com Exchange does NOT require:
        - exec_inst parameter
        - margin_trading flag
        - Separate margin endpoint
        
        The 'leverage' parameter alone indicates this is a margin order.
        """
        self._refresh_runtime_flags()
        actual_dry_run = dry_run or not self.live_trading
        
        # Validate parameters based on side
        side_upper = side.upper()
        if side_upper == "BUY":
            # Allow notional to be string or number for testing variations
            if notional is None:
                raise ValueError("BUY market orders require 'notional' (amount in USD)")
            if isinstance(notional, str):
                try:
                    notional_float = float(notional)
                    if notional_float <= 0:
                        raise ValueError("BUY market orders require 'notional' > 0")
                except (ValueError, TypeError):
                    raise ValueError("BUY market orders require valid 'notional' (amount in USD)")
            else:
                if float(notional) <= 0:
                    raise ValueError("BUY market orders require 'notional' > 0")
            order_amount = notional if isinstance(notional, (int, float)) else float(notional)
            order_type = "notional"
        elif side_upper == "SELL":
            if qty is None:
                raise ValueError("SELL market orders require 'qty' (amount of crypto)")
            if isinstance(qty, str):
                try:
                    qty_float = float(qty)
                    if qty_float <= 0:
                        raise ValueError("SELL market orders require 'qty' > 0")
                except (ValueError, TypeError):
                    raise ValueError("SELL market orders require valid 'qty' (amount of crypto)")
            else:
                if float(qty) <= 0:
                    raise ValueError("SELL market orders require 'qty' > 0")
            order_amount = qty if isinstance(qty, (int, float)) else float(qty)
            order_type = "quantity"
        else:
            raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'")
        
        # Check verification mode BEFORE dry_run check (for SELL orders, need to normalize first)
        verify_mode = os.getenv("VERIFY_ORDER_FORMAT", "0") == "1"
        if verify_mode and side_upper == "SELL":
            # For verification mode on SELL orders, we need instrument metadata
            inst_meta = self._get_instrument_metadata(symbol)
            if inst_meta:
                quantity_decimals = inst_meta["quantity_decimals"]
                qty_tick_size = inst_meta["qty_tick_size"]
                min_quantity = inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?"
            else:
                quantity_decimals = 2
                qty_tick_size = "0.01"
                min_quantity = "?"
            
            raw_quantity = float(qty)
            normalized_qty_str = self.normalize_quantity(symbol, raw_quantity)
            
            logger.info("=" * 80)
            logger.info(f"[VERIFY_ORDER_FORMAT] VERIFICATION MODE - Order will NOT be placed")
            logger.info(f"[VERIFY_ORDER_FORMAT] Symbol: {symbol}")
            logger.info(f"[VERIFY_ORDER_FORMAT] Side: {side_upper}")
            logger.info(f"[VERIFY_ORDER_FORMAT] Order Type: MARKET")
            logger.info(f"[VERIFY_ORDER_FORMAT] Raw Quantity: {raw_quantity}")
            logger.info(f"[VERIFY_ORDER_FORMAT] Instrument Rules:")
            logger.info(f"  - quantity_decimals: {quantity_decimals}")
            logger.info(f"  - qty_tick_size: {qty_tick_size}")
            logger.info(f"  - min_quantity: {min_quantity}")
            logger.info(f"[VERIFY_ORDER_FORMAT] Normalized Quantity: {normalized_qty_str}")
            logger.info("=" * 80)
            return {
                "verify_mode": True,
                "symbol": symbol,
                "side": side_upper,
                "type": "MARKET",
                "raw_quantity": raw_quantity,
                "normalized_quantity": normalized_qty_str,
                "instrument_rules": {
                    "quantity_decimals": quantity_decimals,
                    "qty_tick_size": qty_tick_size,
                    "min_quantity": min_quantity,
                }
            }
        
        if actual_dry_run:
            logger.info(f"DRY_RUN: place_market_order - {symbol} {side_upper} {order_type}={order_amount}")
            return {
                "order_id": f"dry_market_{int(time.time())}",
                "client_order_id": f"dry_client_market_{int(time.time())}",
                "status": "FILLED",
                "side": side_upper,
                "type": "MARKET",
                order_type: str(order_amount),
                "price": "0",  # Market orders don't have price at creation
                "created_time": int(time.time() * 1000)
            }
        
        # Build params according to Crypto.com Exchange API v1 documentation
        # For MARKET orders:
        # - BUY: use "notional" parameter (amount in USD)
        # - SELL: use "quantity" parameter (amount of crypto)
        client_oid = str(uuid.uuid4())
        
        params = {
            "instrument_name": symbol,
            "side": side_upper,  # UPPERCASE as per documentation
            "type": "MARKET",
            "client_oid": client_oid
        }
        
        if side_upper == "BUY":
            # Format notional (amount in USD)
            # Allow notional to be passed as string or number
            # If string, use as-is (for testing variations)
            # If number, format appropriately
            if isinstance(notional, str):
                params["notional"] = notional
            else:
                # Format as string with 2-4 decimal places
                notional_str = f"{float(notional):.2f}" if float(notional) >= 1 else f"{float(notional):.4f}"
                params["notional"] = notional_str
        else:  # SELL
            # Get instrument metadata for debug logging
            inst_meta = self._get_instrument_metadata(symbol)
            if inst_meta:
                quantity_decimals = inst_meta["quantity_decimals"]
                qty_tick_size = inst_meta["qty_tick_size"]
                min_quantity = inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?"
            else:
                quantity_decimals = 2
                qty_tick_size = "0.01"
                min_quantity = "?"
            
            # Normalize quantity using shared helper
            raw_quantity = float(qty)
            normalized_qty_str = self.normalize_quantity(symbol, raw_quantity)
            
            # Check if normalized quantity is valid
            if normalized_qty_str is None:
                error_msg = f"Quantity {raw_quantity} for {symbol} is below min_quantity {min_quantity} after normalization"
                logger.error(f"❌ {error_msg}")
                # Send Telegram alert if possible (non-blocking)
                try:
                    from app.services.telegram_notifier import telegram_notifier
                    telegram_notifier.send_message(f"⚠️ Order failed: {error_msg}")
                except Exception:
                    pass  # Non-blocking
                return {
                    "error": error_msg,
                    "status": "FAILED",
                    "reason": "quantity_below_min"
                }
            
            # Deterministic debug logs (before sending order)
            logger.info("=" * 80)
            logger.info(f"[ORDER_PLACEMENT] Preparing MARKET SELL order")
            logger.info(f"  Symbol: {symbol}")
            logger.info(f"  Side: {side_upper}")
            logger.info(f"  Order Type: MARKET")
            logger.info(f"  Raw Quantity: {raw_quantity}")
            logger.info(f"  Final Quantity: {normalized_qty_str}")
            logger.info(f"  Instrument Rules:")
            logger.info(f"    - quantity_decimals: {quantity_decimals}")
            logger.info(f"    - qty_tick_size: {qty_tick_size}")
            logger.info(f"    - min_quantity: {min_quantity}")
            logger.info("=" * 80)
            
            # Store normalized quantity as string
            params["quantity"] = normalized_qty_str
        
        # MARGIN TRADING: Include leverage parameter when is_margin = True
        # Crypto.com Exchange API: The presence of 'leverage' parameter makes the order a margin order
        # CRITICAL: leverage must be sent as a STRING (e.g., "10"), not a number
        # ALSO CRITICAL: Manual orders from web interface include exec_inst: ["MARGIN_ORDER"]
        # Analysis of successful manual order (BTC_USD) shows exec_inst: ["MARGIN_ORDER"] in response
        # This suggests the request payload should include exec_inst for margin orders
        if is_margin:
            if leverage:
                # Convert leverage to string as required by Crypto.com API
                params["leverage"] = str(int(leverage))
                leverage_value = params["leverage"]
            else:
                # Default to 10x leverage if not specified
                params["leverage"] = "10"
                leverage_value = "10"
                logger.warning(f"⚠️ MARGIN ORDER: is_margin=True but leverage not specified, using default leverage=10")
            
            # Add exec_inst parameter for margin orders (based on successful manual order analysis)
            # Manual orders that work include exec_inst: ["MARGIN_ORDER"] in the response
            # This suggests the request payload should include exec_inst
            # NOTE: If authentication fails, try setting CRYPTO_SKIP_EXEC_INST=true
            # The 'leverage' parameter alone may be sufficient to indicate margin order
            if os.getenv("CRYPTO_SKIP_EXEC_INST", "false").lower() != "true":
                params["exec_inst"] = ["MARGIN_ORDER"]
                logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value}, exec_inst=['MARGIN_ORDER']")
            else:
                logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value} (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)")
        else:
            logger.info(f"📊 SPOT ORDER (no leverage parameter)")
        
        # Crypto.com Exchange API endpoint for both spot and margin orders
        method = "private/create-order"
        
        # Sign the request (includes api_key, nonce, signature)
        payload = self.sign_request(method, params)
        
        # ========================================================================
        # DETAILED MARGIN ORDER REQUEST LOGGING
        # ========================================================================
        # Log the request payload (without sensitive data like signature/api_key)
        log_payload = payload.copy()
        # Remove sensitive fields for logging
        if "sig" in log_payload:
            log_payload["sig"] = "<REDACTED_SIGNATURE>"
        if "api_key" in log_payload:
            log_payload["api_key"] = "<REDACTED_API_KEY>"
        
        logger.info(f"[MARGIN_REQUEST] endpoint={method}")
        logger.info(f"[MARGIN_REQUEST] symbol={symbol} side={side_upper} type=MARKET is_margin={is_margin}")
        logger.info(f"[MARGIN_REQUEST] payload={json.dumps(log_payload, indent=2)}")
        logger.info(f"[MARGIN_REQUEST] params_detail: instrument_name={symbol}, side={side_upper}, type=MARKET, {order_type}={order_amount}")
        if is_margin:
            logger.info(f"[MARGIN_REQUEST] margin_params: leverage={params.get('leverage')}")
        # SECURITY: never log signed payloads (api_key/sig), even at DEBUG.
        try:
            payload_keys = sorted(list((payload or {}).keys()))
            params_keys = sorted(list(((payload or {}).get("params") or {}).keys()))
        except Exception:
            payload_keys = []
            params_keys = []
        logger.debug("[MARGIN_REQUEST] payload_keys=%s params_keys=%s", payload_keys, params_keys)
        
        # Use proxy if enabled
        if self.use_proxy:
            # Generate unique request ID for tracking
            import uuid as uuid_module
            request_id = str(uuid_module.uuid4())
            
            logger.info("Using PROXY to place market order")
            
            # Log HTTP request details with source and request_id (ENTRY orders via proxy)
            logger.info(
                f"[ENTRY_ORDER][{source}][{request_id}] Sending HTTP request to exchange (via PROXY):\n"
                f"  Method: {method}\n"
                f"  Params JSON: {json.dumps(params, ensure_ascii=False, indent=2)}"
            )
            
            try:
                result = self._call_proxy(method, params)
                
                # Log HTTP response details (from proxy)
                logger.info(
                    f"[ENTRY_ORDER][{source}][{request_id}] Received HTTP response from exchange (via PROXY):\n"
                    f"  Response Body: {json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result}"
                )
                
                # Check if proxy returned a 401
                if isinstance(result, dict) and result.get("code") == 40101:
                    logger.warning("Proxy returned 401 - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        # Prepare order data for TRADE_BOT
                        order_data = {
                            "symbol": symbol,
                            "side": side_upper,
                            "type": "MARKET",
                        }
                        if side_upper == "BUY":
                            order_data["notional"] = notional
                        else:
                            # Use formatted quantity from params (already properly formatted)
                            order_data["qty"] = params.get("quantity", str(qty))
                        # Include margin parameters in fallback
                        if is_margin:
                            order_data["is_margin"] = True
                            order_data["leverage"] = int(leverage) if leverage else 10
                            logger.info(f"📊 FALLBACK MARGIN ORDER: is_margin={is_margin}, leverage={order_data['leverage']}")
                        fr = self._fallback_place_order(order_data)
                        if fr.status_code == 200:
                            data = fr.json()
                            return data.get("result", data)
                    raise RuntimeError("Failed to place market order - no fallback available")
                
                if "result" in result:
                    return result["result"]
                else:
                    logger.error(f"Unexpected proxy response: {result}")
                    return {"error": "Failed to place market order via proxy"}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Proxy error: {e} - attempting failover to TRADE_BOT")
                if _should_failover(None, e):
                    order_data = {
                        "symbol": symbol,
                        "side": side_upper,
                        "type": "MARKET",
                    }
                    if side_upper == "BUY":
                        order_data["notional"] = notional
                    else:
                        # Use formatted quantity from params (already properly formatted)
                        order_data["qty"] = params.get("quantity", str(qty))
                    # Include margin parameters in fallback
                    if is_margin:
                        order_data["is_margin"] = True
                        order_data["leverage"] = int(leverage) if leverage else 10
                        logger.info(f"📊 FALLBACK MARGIN ORDER: is_margin={is_margin}, leverage={order_data['leverage']}")
                    fr = self._fallback_place_order(order_data)
                    if fr.status_code == 200:
                        data = fr.json()
                        return data.get("result", data)
                raise
        else:
            # Direct API call (if not using proxy)
            try:
                # Generate unique request ID for tracking
                import uuid as uuid_module
                request_id = str(uuid_module.uuid4())
                
                url = f"{self.base_url}/{method}"
                logger.debug(f"Request URL: {url}")
                
                # Log HTTP request details with source and request_id (ENTRY orders)
                # SECURITY: never log signed payloads (api_key/sig). Log keys only.
                try:
                    payload_keys = sorted(list((payload or {}).keys()))
                    payload_params_keys = sorted(list(((payload or {}).get("params") or {}).keys()))
                except Exception:
                    payload_keys = []
                    payload_params_keys = []
                logger.info(
                    f"[ENTRY_ORDER][{source}][{request_id}] Sending HTTP request to exchange:\n"
                    f"  URL: {url}\n"
                    f"  Method: POST\n"
                    f"  Payload keys: {payload_keys}\n"
                    f"  Params keys: {payload_params_keys}"
                )
                
                response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.place_market_order")
                
                # Log HTTP response details
                try:
                    response_body = response.json()
                except:
                    response_body = response.text
                
                logger.info(
                    f"[ENTRY_ORDER][{source}][{request_id}] Received HTTP response from exchange:\n"
                    f"  Status Code: {response.status_code}\n"
                    f"  Response Body: {json.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, dict) else response_body}"
                )
                
                if response.status_code == 401:
                    error_data = response.json()
                    error_code = error_data.get("code", 0)
                    error_msg = error_data.get("message", "")
                    
                    # Enhanced diagnostic logging for authentication failures
                    logger.error(
                        f"🔐 AUTHENTICATION FAILED for MARKET order ({symbol} {side_upper}):\n"
                        f"   Error Code: {error_code}\n"
                        f"   Error Message: {error_msg}\n"
                        f"   API Key: <SET> len={len(self.api_key or '')}\n"
                        f"   Base URL: {self.base_url}\n"
                        f"   Method: {method}\n"
                        f"   Using Proxy: {self.use_proxy}\n"
                        f"   Live Trading: {self.live_trading}"
                    )
                    
                    # Try to get outbound IP for diagnostic purposes
                    try:
                        from app.utils.egress_guard import validate_outbound_url, log_outbound_request
                        ipify_url = "https://api.ipify.org"
                        validated_url, _ = validate_outbound_url(ipify_url, calling_module="crypto_com_trade._call_api")
                        egress_ip = http_get(validated_url, timeout=5, calling_module="crypto_com_trade.place_market_order").text.strip()
                        log_outbound_request(validated_url, method="GET", status_code=200, calling_module="crypto_com_trade._call_api")
                        logger.error(f"   Outbound IP: {egress_ip} (must be whitelisted in Crypto.com Exchange)")
                    except Exception as e:
                        logger.debug(f"   Could not check outbound IP: {e}")
                    
                    # Provide specific guidance based on error code
                    if error_code == 40101:
                        logger.error(
                            "   DIAGNOSIS: Authentication failure (40101)\n"
                            "   Possible causes:\n"
                            "   - API key or secret is incorrect\n"
                            "   - API key is expired or revoked\n"
                            "   - API key doesn't have 'Trade' permission\n"
                            "   Run: python backend/scripts/diagnose_auth_issue.py for detailed diagnostics"
                        )
                    elif error_code == 40103:
                        logger.error(
                            "   DIAGNOSIS: IP address not whitelisted (40103)\n"
                            "   Solution:\n"
                            "   1. Go to https://exchange.crypto.com/ → Settings → API Keys\n"
                            "   2. Edit your API key\n"
                            "   3. Add your server's IP address to the whitelist\n"
                            "   4. Wait a few minutes for changes to take effect"
                        )

                    # If env default says "use proxy", but this call ended up direct (likely due to a
                    # per-request override), try proxy once before failing over to TRADE_BOT.
                    try:
                        if getattr(self, "_use_proxy_default", False) and not self.use_proxy:
                            logger.warning(
                                "Direct auth failed but USE_CRYPTO_PROXY default is enabled. "
                                "Attempting proxy fallback for MARKET order..."
                            )
                            proxy_result = self._call_proxy(method, params)
                            if isinstance(proxy_result, dict) and "result" in proxy_result:
                                logger.info("Successfully placed MARKET order via PROXY fallback")
                                return proxy_result["result"]
                    except Exception as proxy_fallback_err:
                        logger.warning(f"Proxy fallback exception for MARKET order: {proxy_fallback_err}")

                    # Attempt failover to TRADE_BOT for MARKET orders (parity with LIMIT create-order)
                    # This is especially useful for AWS IP whitelist issues (40103) or signature/key issues (40101).
                    if error_code in [40101, 40103]:
                        if _should_failover(401):
                            try:
                                # NOTE: this payload is sent as JSON to TRADE_BOT and legitimately
                                # contains mixed types (str/bool/int). Without an explicit type,
                                # Pyright infers `dict[str, str]` from the initial literals and
                                # then errors when we assign `bool`/`int` values (e.g. leverage).
                                order_data: Dict[str, Any] = {
                                    "symbol": symbol,
                                    "side": side_upper,
                                    "type": "MARKET",
                                }
                                if side_upper == "BUY":
                                    order_data["notional"] = notional
                                else:
                                    # Use formatted quantity from params (already properly formatted)
                                    order_data["qty"] = params.get("quantity", str(qty))
                                if is_margin:
                                    order_data["is_margin"] = True
                                    order_data["leverage"] = int(leverage) if leverage else 10
                                fr = self._fallback_place_order(order_data)
                                if fr and fr.status_code == 200:
                                    data = fr.json()
                                    logger.info("Successfully placed MARKET order via TRADE_BOT failover")
                                    return data.get("result", data)
                                else:
                                    logger.warning(
                                        f"TRADE_BOT failover failed for MARKET order: "
                                        f"status={getattr(fr, 'status_code', None)}"
                                    )
                            except Exception as failover_err:
                                logger.warning(f"TRADE_BOT failover exception for MARKET order: {failover_err}")
                        else:
                            logger.warning(
                                f"Failover not enabled or TRADEBOT_BASE not configured. "
                                f"FAILOVER_ENABLED={FAILOVER_ENABLED}, TRADEBOT_BASE={TRADEBOT_BASE}"
                            )

                    return {"error": f"Authentication failed: {error_msg}"}
                
                # Log the response from Crypto.com (before processing)
                try:
                    response_json = response.json()
                    logger.info(f"[MARGIN_RESPONSE] status_code={response.status_code}")
                    logger.info(f"[MARGIN_RESPONSE] payload={json.dumps(response_json, indent=2)}")
                except (ValueError, AttributeError):
                    logger.warning(f"[MARGIN_RESPONSE] status_code={response.status_code} (non-JSON response)")
                    logger.warning(f"[MARGIN_RESPONSE] response_text={response.text[:500]}")
                
                # Check for error responses (400, 500, etc.) before raise_for_status
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_code = error_data.get("code", 0)
                        error_msg = error_data.get("message", "")
                        error_details = f"{response.status_code} Server Error: {error_msg or 'Internal Server Error'}"
                        if error_code:
                            error_details += f" (code: {error_code})"
                        
                        # Special handling for error 213 (Invalid quantity format) for SELL orders
                        if error_code == 213 and side_upper == "SELL" and "quantity" in params:
                            logger.warning(f"⚠️ Error 213 (Invalid quantity format) for MARKET SELL {symbol}. Trying different precision levels...")
                            
                            # Define precision levels to try (same as STOP_LIMIT orders)
                            import decimal as dec
                            precision_levels = [
                                (2, dec.Decimal('0.01')),      # Most common: 2 decimals
                                (8, dec.Decimal('0.00000001')), # Low-value coins like DOGE
                                (6, dec.Decimal('0.000001')),   # High-value coins like BTC
                                (4, dec.Decimal('0.0001')),     # Medium precision
                                (3, dec.Decimal('0.001')),      # Lower precision
                                (1, dec.Decimal('0.1')),         # Very low precision
                                (0, dec.Decimal('1')),          # Whole numbers only
                            ]
                            
                            # Try different precision levels
                            original_qty = qty
                            for prec_decimals, prec_tick in precision_levels:
                                logger.info(f"🔄 Trying MARKET SELL {symbol} with precision {prec_decimals} decimals (tick_size={prec_tick})...")
                                
                                # Re-format quantity with new precision using Decimal
                                qty_decimal = dec.Decimal(str(original_qty))
                                qty_decimal = (qty_decimal / prec_tick).quantize(dec.Decimal('1'), rounding=dec.ROUND_DOWN) * prec_tick
                                
                                # Format with exact precision - keep trailing zeros
                                if prec_decimals == 0:
                                    qty_str_new = str(int(qty_decimal))
                                else:
                                    qty_str_new = format(qty_decimal, f'.{prec_decimals}f')
                                
                                logger.info(f"Quantity formatted: {original_qty} -> '{qty_str_new}' (precision {prec_decimals} decimals)")
                                
                                # Update params with new quantity
                                params_retry = params.copy()
                                params_retry["quantity"] = qty_str_new
                                
                                # Try this precision
                                try:
                                    payload_retry = self.sign_request(method, params_retry)
                                    response_retry = http_post(url, json=payload_retry, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade._call_api")
                                    
                                    if response_retry.status_code == 200:
                                        result_retry = response_retry.json()
                                        logger.info(f"✅ Successfully placed MARKET SELL order with precision {prec_decimals} decimals")
                                        return result_retry.get("result", {})
                                    
                                    # Check if it's still error 213
                                    try:
                                        error_data_retry = response_retry.json()
                                        new_error_code = error_data_retry.get('code', 0)
                                        if new_error_code != 213:
                                            # Different error - stop trying precisions
                                            logger.debug(f"Different error {new_error_code} with precision {prec_decimals}, stopping retry")
                                            break
                                    except:
                                        pass
                                    
                                except Exception as retry_err:
                                    logger.debug(f"Error trying precision {prec_decimals}: {retry_err}")
                                    continue
                            
                            # If all precision levels failed, return original error
                            logger.error(f"❌ All precision levels failed for MARKET SELL {symbol}. Original error: {error_details}")
                        
                        # Special handling for error 306 (INSUFFICIENT_AVAILABLE_BALANCE)
                        if error_code == 306 or "306" in str(error_code):
                            margin_status = "MARGIN" if is_margin else "SPOT"
                            requested_size = params.get("notional") or params.get("quantity", "N/A")
                            leverage_info = f"leverage={params.get('leverage', 'N/A')}" if is_margin else "spot"
                            logger.error(f"[MARGIN_ERROR_306] symbol={symbol} side={side_upper} type=MARKET")
                            logger.error(f"[MARGIN_ERROR_306] requested_size={requested_size} {leverage_info}")
                            logger.error(f"[MARGIN_ERROR_306] raw_response={json.dumps(error_data, indent=2)}")
                            logger.error(f"[MARGIN_ERROR_306] NOTE: This error means insufficient margin balance OR malformed request")
                            logger.error(f"[MARGIN_ERROR_306] Verify: 1) Request payload matches Crypto.com API docs 2) Account has enough margin")
                        else:
                            margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
                            logger.error(f"❌ API error placing {margin_status} market order for {symbol}: {error_details}")
                        
                        logger.error(f"📊 Order parameters that failed: {json.dumps(params, indent=2)}")
                        logger.error(f"Full error response: {json.dumps(error_data, indent=2)}")
                        return {"error": error_details}
                    except (ValueError, KeyError):
                        # If response is not JSON, use status text
                        error_details = f"{response.status_code} Server Error: {response.reason or 'Internal Server Error'}"
                        logger.error(f"API error placing market order (non-JSON response): {error_details}")
                        logger.error(f"Response text: {response.text[:500]}")
                        return {"error": error_details}
                
                response.raise_for_status()
                result = response.json()
                
                # Log successful response
                margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
                logger.info(f"✅ Successfully placed {margin_status} market order for {symbol}")
                logger.info(f"[MARGIN_RESPONSE] success: order_id={result.get('result', {}).get('order_id', 'N/A')}")
                logger.info(f"📊 Order response: {result.get('result', {})}")
                logger.debug(f"Full response: {result}")
                
                return result.get("result", {})
            except requests.exceptions.HTTPError as e:
                # Handle other HTTP errors (4xx, 5xx)
                try:
                    error_data = response.json()
                    error_code = error_data.get("code", 0)
                    error_msg = error_data.get("message", str(e))
                    error_details = f"{response.status_code} Server Error: {error_msg}"
                    if error_code:
                        error_details += f" (code: {error_code})"
                    logger.error(f"HTTP error placing market order: {error_details}")
                    return {"error": error_details}
                except (ValueError, KeyError, AttributeError):
                    logger.error(f"HTTP error placing market order: {e}")
                    return {"error": f"{response.status_code} Server Error: {str(e)}"}
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error placing market order: {e}")
                return {"error": str(e)}
            except Exception as e:
                logger.error(f"Error placing market order: {e}", exc_info=True)
                return {"error": str(e)}
    
    def place_limit_order(
        self, 
        symbol: str, 
        side: str, 
        price: float, 
        qty: float, 
        *, 
        is_margin: bool = False, 
        leverage: Optional[float] = None, 
        dry_run: bool = True
    ) -> dict:
        """Place limit order"""
        self._refresh_runtime_flags()
        actual_dry_run = dry_run or not self.live_trading
        
        if actual_dry_run:
            logger.info(f"DRY_RUN: place_limit_order - {symbol} {side} {qty} @ {price}")
            return {
                "order_id": f"dry_{int(time.time())}",
                "client_order_id": f"dry_{int(time.time())}",
                "status": "OPEN",
                "side": side,
                "type": "LIMIT",
                "quantity": str(qty),
                "price": str(price),
                "created_time": int(time.time() * 1000)
            }
        
        method = "private/create-order"
        # Build params according to Crypto.com Exchange API v1 documentation
        # Required params: instrument_name, side, type, price (for LIMIT), quantity
        # Optional but recommended: time_in_force (defaults to GOOD_TILL_CANCEL for LIMIT)
        # Format price and quantity according to documented logic (docs/trading/crypto_com_order_formatting.md)
        
        # Normalize price using helper function (per Rule 3: directional rounding, Rule 4: preserve trailing zeros)
        normalized_price_str = self.normalize_price(symbol, price, side, order_type="LIMIT")
        if normalized_price_str is None:
            error_msg = f"Instrument metadata unavailable for {symbol} - cannot format price"
            logger.error(f"❌ [LIMIT_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ LIMIT order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "instrument_metadata_unavailable"
            }
        price_str = normalized_price_str
        
        # Normalize quantity using shared helper (per documented logic)
        raw_quantity = float(qty)
        normalized_qty_str = self.normalize_quantity(symbol, raw_quantity)
        
        # Fail-safe: block order if normalization failed
        if normalized_qty_str is None:
            inst_meta = self._get_instrument_metadata(symbol)
            min_quantity = (
                (inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?")
                if inst_meta
                else "?"
            )
            error_msg = f"Quantity {raw_quantity} for {symbol} is below min_quantity {min_quantity} after normalization"
            logger.error(f"❌ [LIMIT_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ LIMIT order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "quantity_below_min"
            }
        
        # Get instrument metadata for debug logging
        inst_meta = self._get_instrument_metadata(symbol)
        if inst_meta:
            quantity_decimals = inst_meta["quantity_decimals"]
            qty_tick_size = inst_meta["qty_tick_size"]
            min_quantity = inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?"
        else:
            quantity_decimals = 2
            qty_tick_size = "0.01"
            min_quantity = "?"
        
        # Deterministic debug logs (before sending order)
        logger.info("=" * 80)
        logger.info(f"[ORDER_PLACEMENT] Preparing LIMIT order")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Side: {side.upper()}")
        logger.info(f"  Order Type: LIMIT")
        logger.info(f"  Price: {price} -> {price_str}")
        logger.info(f"  Raw Quantity: {raw_quantity}")
        logger.info(f"  Final Quantity: {normalized_qty_str}")
        logger.info(f"  Instrument Rules:")
        logger.info(f"    - quantity_decimals: {quantity_decimals}")
        logger.info(f"    - qty_tick_size: {qty_tick_size}")
        logger.info(f"    - min_quantity: {min_quantity}")
        logger.info("=" * 80)
        
        # Build params according to Crypto.com Exchange API v1 documentation
        client_oid = str(uuid.uuid4())
        params = {
            "instrument_name": symbol,
            "side": side.upper(),
            "type": "LIMIT",
            "price": price_str,
            "quantity": normalized_qty_str,  # Use normalized quantity
            "client_oid": client_oid,
            "time_in_force": "GOOD_TILL_CANCEL"
        }
        
        # MARGIN TRADING: Include leverage parameter when is_margin = True
        # Crypto.com Exchange API: The presence of 'leverage' parameter makes the order a margin order
        # CRITICAL: leverage must be sent as a STRING (e.g., "10"), not a number
        # ALSO CRITICAL: Manual orders from web interface include exec_inst: ["MARGIN_ORDER"]
        # Analysis of successful manual order (BTC_USD) shows exec_inst: ["MARGIN_ORDER"] in response
        # This suggests the request payload should include exec_inst for margin orders
        if is_margin:
            if leverage:
                # Convert leverage to string as required by Crypto.com API
                params["leverage"] = str(int(leverage))
                leverage_value = params["leverage"]
            else:
                # Default to 10x leverage if not specified
                params["leverage"] = "10"
                leverage_value = "10"
                logger.warning(f"⚠️ MARGIN ORDER: is_margin=True but leverage not specified, using default leverage=10")
            
            # Add exec_inst parameter for margin orders (based on successful manual order analysis)
            # Manual orders that work include exec_inst: ["MARGIN_ORDER"] in the response
            # This suggests the request payload should include exec_inst
            # NOTE: If authentication fails, try setting CRYPTO_SKIP_EXEC_INST=true
            # The 'leverage' parameter alone may be sufficient to indicate margin order
            if os.getenv("CRYPTO_SKIP_EXEC_INST", "false").lower() != "true":
                params["exec_inst"] = ["MARGIN_ORDER"]
                logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value}, exec_inst=['MARGIN_ORDER']")
            else:
                logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value} (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)")
        else:
            logger.info(f"📊 SPOT ORDER (no leverage parameter)")
        
        # Sign the request (includes api_key, nonce, signature)
        payload = self.sign_request(method, params)
        
        # ========================================================================
        # DETAILED MARGIN ORDER REQUEST LOGGING
        # ========================================================================
        # Log the request payload (without sensitive data like signature/api_key)
        log_payload = payload.copy()
        # Remove sensitive fields for logging
        if "sig" in log_payload:
            log_payload["sig"] = "<REDACTED_SIGNATURE>"
        if "api_key" in log_payload:
            log_payload["api_key"] = "<REDACTED_API_KEY>"
        
        logger.info(f"[MARGIN_REQUEST] endpoint={method}")
        logger.info(f"[MARGIN_REQUEST] symbol={symbol} side={side.upper()} type=LIMIT is_margin={is_margin}")
        logger.info(f"[MARGIN_REQUEST] payload={json.dumps(log_payload, indent=2)}")
        logger.info(f"[MARGIN_REQUEST] params_detail: instrument_name={symbol}, side={side.upper()}, type=LIMIT, price={price_str}, quantity={normalized_qty_str}")
        if is_margin:
            logger.info(f"[MARGIN_REQUEST] margin_params: leverage={params.get('leverage')}")
        logger.info(f"Price string: '{price_str}', Quantity string: '{normalized_qty_str}'")
        # SECURITY: never log signed payloads (api_key/sig), even at DEBUG.
        try:
            payload_keys = sorted(list((payload or {}).keys()))
            params_keys = sorted(list(((payload or {}).get("params") or {}).keys()))
        except Exception:
            payload_keys = []
            params_keys = []
        logger.debug("[MARGIN_REQUEST] payload_keys=%s params_keys=%s", payload_keys, params_keys)
        
        # Use proxy if enabled
        if self.use_proxy:
            logger.info("Using PROXY to place limit order")
            try:
                result = self._call_proxy(method, params)
                
                # Check if proxy returned a 401
                if isinstance(result, dict) and result.get("code") == 40101:
                    logger.warning("Proxy returned 401 - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        order_data = {
                            "symbol": symbol,
                            "side": side.upper(),
                            "type": "LIMIT",
                            "qty": qty,
                            "price": price
                        }
                        # Include margin parameters in fallback
                        if is_margin:
                            order_data["is_margin"] = True
                            order_data["leverage"] = int(leverage) if leverage else 10
                            logger.info(f"📊 FALLBACK MARGIN ORDER: is_margin={is_margin}, leverage={order_data['leverage']}")
                        fr = self._fallback_place_order(order_data)
                        if fr.status_code == 200:
                            data = fr.json()
                            return data.get("result", data)
                    raise RuntimeError("Failed to place limit order - no fallback available")
                
                if "result" in result:
                    return result["result"]
                else:
                    logger.error(f"Unexpected proxy response: {result}")
                    return {"error": "Failed to place limit order via proxy"}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Proxy error: {e} - attempting failover to TRADE_BOT")
                if _should_failover(None, e):
                    order_data = {
                        "symbol": symbol,
                        "side": side.upper(),
                        "type": "LIMIT",
                        "qty": qty,
                        "price": price
                    }
                    fr = self._fallback_place_order(order_data)
                    if fr.status_code == 200:
                        data = fr.json()
                        return data.get("result", data)
                raise
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.place_limit_order")
            
            # Check if authentication failed - same handling as get_account_summary
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.warning(f"API authentication failed: {error_msg} (code: {error_code})")
                
                # Attempt failover to TRADE_BOT (same as get_account_summary)
                if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                    logger.warning("Authentication failure for create-order - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        order_data = {
                            "symbol": symbol,
                            "side": side.upper(),
                            "type": "LIMIT",
                            "qty": qty,
                            "price": price
                        }
                        fr = self._fallback_place_order(order_data)
                        if fr.status_code == 200:
                            data = fr.json()
                            logger.info("Successfully placed order via TRADE_BOT fallback")
                            return data.get("result", data)
                        else:
                            logger.error(f"TRADE_BOT fallback failed: {fr.status_code}")
                
                # Return error if no fallback available
                return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
            
            # Log the response from Crypto.com (before processing)
            try:
                response_json = response.json()
                logger.info(f"[MARGIN_RESPONSE] status_code={response.status_code}")
                logger.info(f"[MARGIN_RESPONSE] payload={json.dumps(response_json, indent=2)}")
            except (ValueError, AttributeError):
                logger.warning(f"[MARGIN_RESPONSE] status_code={response.status_code} (non-JSON response)")
                logger.warning(f"[MARGIN_RESPONSE] response_text={response.text[:500]}")
            
            # Check for error responses (400, etc.) before raise_for_status
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_code = error_data.get('code', 0)
                    error_msg = error_data.get('message', 'Unknown error')
                    margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
                    
                    # Special handling for error 306 (INSUFFICIENT_AVAILABLE_BALANCE)
                    if error_code == 306 or "306" in str(error_code):
                        requested_size = params.get("quantity", "N/A")
                        leverage_info = f"leverage={params.get('leverage', 'N/A')}" if is_margin else "spot"
                        logger.error(f"[MARGIN_ERROR_306] symbol={symbol} side={side.upper()} type=LIMIT")
                        logger.error(f"[MARGIN_ERROR_306] requested_size={requested_size} price={price_str} {leverage_info}")
                        logger.error(f"[MARGIN_ERROR_306] raw_response={json.dumps(error_data, indent=2)}")
                        logger.error(f"[MARGIN_ERROR_306] NOTE: This error means insufficient margin balance OR malformed request")
                        logger.error(f"[MARGIN_ERROR_306] Verify: 1) Request payload matches Crypto.com API docs 2) Account has enough margin")
                    else:
                        # Log the specific error for debugging
                        logger.error(f"❌ Error creating {margin_status} limit order: HTTP {response.status_code}, code={error_code}, message={error_msg}, symbol={symbol}, price={price}, qty={qty}")
                    
                    logger.error(f"📊 Order parameters that failed: {json.dumps(params, indent=2)}")
                    
                    # Map specific error codes to user-friendly messages with full API details
                    # Always show exact error code and message for transparency
                    if error_code == 315:
                        return {"error": f"❌ Error {error_code}: Precio límite muy lejos del mercado\n\nEl precio debe estar cerca del precio actual de mercado (±5-10%).\n\nMensaje API: {error_msg}"}
                    elif error_code == 40004:
                        return {"error": f"❌ Error {error_code}: Parámetro faltante o inválido\n\nVerifica que todos los parámetros sean correctos.\n\nMensaje API: {error_msg}"}
                    elif error_code == 306:
                        # Extract symbol from params if available
                        symbol_name = symbol if 'symbol' in locals() else params.get('instrument_name', 'UNKNOWN').split('_')[0] if isinstance(params, dict) else 'UNKNOWN'
                        return {"error": f"❌ Error {error_code}: Balance insuficiente\n\nNo tienes suficiente {symbol_name} disponible en tu cuenta para {side.lower()} esta cantidad.\nVerifica tu balance disponible antes de crear la orden.\n\nMensaje API: {error_msg}"}
                    
                    # For any other error code, show code and message
                    return {"error": f"❌ Error {error_code}: {error_msg}\n\nConsulta la documentación de Crypto.com Exchange para más detalles sobre este código de error."}
                except Exception as parse_err:
                    logger.error(f"Error parsing error response: {parse_err}, response text: {response.text[:200]}")
                    return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
            
            response.raise_for_status()
            result = response.json()
            
            # Log successful response
            margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
            logger.info(f"✅ Successfully placed {margin_status} limit order for {symbol}")
            logger.info(f"[MARGIN_RESPONSE] success: order_id={result.get('result', {}).get('order_id', 'N/A')}")
            logger.info(f"📊 Order response: {result.get('result', {})}")
            logger.debug(f"Full response: {result}")
            
            return result.get("result", {})
            
        except requests.exceptions.RequestException as e:
            margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
            logger.error(f"❌ Network error placing {margin_status} limit order for {symbol}: {e}")
            # Try to parse error response for more details
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_code = error_data.get('code', 0)
                    error_msg = error_data.get('message', str(e))
                    
                    # Map specific error codes to user-friendly messages with full API details
                    # Always show exact error code and message for transparency
                    if error_code == 315:
                        return {"error": f"❌ Error {error_code}: Precio límite muy lejos del mercado\n\nEl precio debe estar cerca del precio actual de mercado (±5-10%).\n\nMensaje API: {error_msg}"}
                    elif error_code == 40004:
                        return {"error": f"❌ Error {error_code}: Parámetro faltante o inválido\n\nVerifica que todos los parámetros sean correctos.\n\nMensaje API: {error_msg}"}
                    elif error_code == 306:
                        # Extract symbol from params if available
                        symbol_name = symbol if 'symbol' in locals() else params.get('instrument_name', 'UNKNOWN').split('_')[0] if isinstance(params, dict) else 'UNKNOWN'
                        return {"error": f"❌ Error {error_code}: Balance insuficiente\n\nNo tienes suficiente {symbol_name} disponible en tu cuenta para {side.lower()} esta cantidad.\nVerifica tu balance disponible antes de crear la orden.\n\nMensaje API: {error_msg}"}
                    
                    # For any other error code, show code and message
                    return {"error": f"❌ Error {error_code}: {error_msg}\n\nConsulta la documentación de Crypto.com Exchange para más detalles sobre este código de error."}
                except:
                    pass
            return {"error": str(e)}
        except Exception as e:
            margin_status = f"MARGIN (leverage={params.get('leverage', 'N/A')})" if is_margin else "SPOT"
            logger.error(f"❌ Error placing {margin_status} limit order for {symbol}: {e}")
            return {"error": str(e)}
    
    def cancel_order(self, order_id: str) -> dict:
        """Cancel order by order_id"""
        self._refresh_runtime_flags()
        if not self.live_trading:
            logger.info(f"DRY_RUN: cancel_order - {order_id}")
            return {"order_id": order_id, "status": "CANCELLED"}
        
        method = "private/cancel-order"
        params = {"order_id": order_id}
        
        logger.info(f"Live: cancel_order - {order_id}")
        
        # Use proxy if enabled
        if self.use_proxy:
            logger.info("Using PROXY to cancel order")
            try:
                result = self._call_proxy(method, params)
                
                # Check if proxy returned a 401
                if isinstance(result, dict) and result.get("code") == 40101:
                    logger.warning("Proxy returned 401 - attempting failover to TRADE_BOT")
                    if _should_failover(401):
                        fr = self._fallback_cancel_order(order_id)
                        if fr.status_code == 200:
                            data = fr.json()
                            return data.get("result", data)
                    raise RuntimeError("Failed to cancel order - no fallback available")
                
                if "result" in result:
                    return result["result"]
                else:
                    logger.error(f"Unexpected proxy response: {result}")
                    return {"error": "Failed to cancel order via proxy"}
            except requests.exceptions.RequestException as e:
                logger.warning(f"Proxy error: {e} - attempting failover to TRADE_BOT")
                if _should_failover(None, e):
                    fr = self._fallback_cancel_order(order_id)
                    if fr.status_code == 200:
                        data = fr.json()
                        return data.get("result", data)
                raise
        
        # Direct API call
        payload = self.sign_request(method, params)
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.cancel_order")
            
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                logger.error(f"Authentication failed: {error_code} - {error_msg}")
                return {"error": f"Authentication failed: {error_msg}"}
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully cancelled order")
            logger.debug(f"Response: {result}")
            
            return result.get("result", {})
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error cancelling order: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {"error": str(e)}
    
    def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        trigger_price: float,
        *,
        entry_price: Optional[float] = None,
        is_margin: bool = False,
        leverage: Optional[float] = None,
        dry_run: bool = True,
        source: str = "unknown"  # "auto" or "manual" to track the source
    ) -> dict:
        """Place stop loss order (STOP_LIMIT)"""
        self._refresh_runtime_flags()
        actual_dry_run = dry_run or not self.live_trading
        
        if actual_dry_run:
            logger.info(f"DRY_RUN: place_stop_loss_order - {symbol} {side} {qty} @ {price} trigger={trigger_price}")
            return {
                "order_id": f"dry_sl_{int(time.time())}",
                "client_order_id": f"dry_sl_{int(time.time())}",
                "status": "OPEN",
                "side": side,
                "type": "STOP_LIMIT",
                "quantity": str(qty),
                "price": str(price),
                "trigger_price": str(trigger_price),
                "created_time": int(time.time() * 1000)
            }
        
        method = "private/create-order"
        
        # Normalize price using helper function (per Rule 3: STOP_LOSS uses ROUND_DOWN)
        # For STOP_LIMIT orders, execution price should also use ROUND_DOWN (conservative)
        normalized_price_str = self.normalize_price(symbol, price, side, order_type="STOP_LOSS")
        if normalized_price_str is None:
            error_msg = f"Instrument metadata unavailable for {symbol} - cannot format price"
            logger.error(f"❌ [STOP_LOSS_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ STOP_LOSS order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "instrument_metadata_unavailable"
            }
        price_str = normalized_price_str
        
        # Normalize quantity using shared helper (per documented logic: docs/trading/crypto_com_order_formatting.md)
        raw_quantity = float(qty)
        normalized_qty_str = self.normalize_quantity(symbol, raw_quantity)
        
        # Fail-safe: block order if normalization failed
        if normalized_qty_str is None:
            inst_meta = self._get_instrument_metadata(symbol)
            min_quantity = (
                (inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?")
                if inst_meta
                else "?"
            )
            error_msg = f"Quantity {raw_quantity} for {symbol} is below min_quantity {min_quantity} after normalization"
            logger.error(f"❌ [STOP_LOSS_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ STOP_LOSS order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "quantity_below_min"
            }
        
        # Get instrument metadata for debug logging
        inst_meta = self._get_instrument_metadata(symbol)
        if inst_meta:
            quantity_decimals = inst_meta["quantity_decimals"]
            qty_tick_size = inst_meta["qty_tick_size"]
            min_quantity = inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?"
        else:
            quantity_decimals = 2
            qty_tick_size = "0.01"
            min_quantity = "?"
        
        # Deterministic debug logs (before sending order)
        logger.info("=" * 80)
        logger.info(f"[ORDER_PLACEMENT] Preparing STOP_LIMIT order")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Side: {side}")
        logger.info(f"  Order Type: STOP_LIMIT")
        logger.info(f"  Price: {price} -> {price_str}")
        logger.info(f"  Raw Quantity: {raw_quantity}")
        logger.info(f"  Final Quantity: {normalized_qty_str}")
        logger.info(f"  Instrument Rules:")
        logger.info(f"    - quantity_decimals: {quantity_decimals}")
        logger.info(f"    - qty_tick_size: {qty_tick_size}")
        logger.info(f"    - min_quantity: {min_quantity}")
        logger.info("=" * 80)
        
        qty_str = normalized_qty_str
        
        # Normalize trigger_price using helper function (per Rule 3: STOP_LOSS triggers use ROUND_DOWN)
        normalized_trigger_str = self.normalize_price(symbol, trigger_price, side, order_type="STOP_LOSS")
        if normalized_trigger_str is None:
            error_msg = f"Instrument metadata unavailable for {symbol} - cannot format trigger_price"
            logger.error(f"❌ [STOP_LOSS_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ STOP_LOSS order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "instrument_metadata_unavailable"
            }
        trigger_str = normalized_trigger_str
        
        # Now that trigger_str is defined, log trigger mapping deterministically.
        logger.info(f"  Trigger Price: {trigger_price} -> {trigger_str}")
        
        # For STOP_LIMIT orders, ref_price should be the LAST BUY PRICE (entry price) from order history
        # However, Crypto.com uses ref_price for the Trigger Condition display
        # Based on user feedback: Trigger Condition should equal trigger_price (SL price), not ref_price (entry price)
        # So we set ref_price = trigger_price to ensure Trigger Condition shows the correct value
        # Use entry_price if provided, otherwise try to get it from order history (for internal tracking)
        entry_price_for_ref = entry_price
        
        if not entry_price_for_ref:
            # Try to get entry price from order history (most recent filled BUY order)
            try:
                from app.database import SessionLocal
                from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
                db = SessionLocal()
                try:
                    buy_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.symbol == symbol,
                        ExchangeOrder.side == OrderSideEnum.BUY,
                        ExchangeOrder.status == OrderStatusEnum.FILLED
                    ).order_by(ExchangeOrder.exchange_create_time.desc()).first()
                    
                    if buy_order:
                        entry_price_for_ref = float(buy_order.avg_price or buy_order.price)
                        logger.info(f"✅ Got entry price from order history for STOP_LIMIT {symbol}: {entry_price_for_ref}")
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Could not get entry price from order history for {symbol}: {e}")
        
        # IMPORTANT: For STOP_LIMIT orders, Crypto.com uses ref_price for Trigger Condition display
        # User requirement: Trigger Condition should equal trigger_price (SL price), not entry_price
        # Therefore, set ref_price = trigger_price to ensure correct Trigger Condition display
        ref_price = trigger_price  # Use trigger_price (SL price) for ref_price so Trigger Condition shows correctly
        
        logger.info(f"Using ref_price={ref_price} (trigger_price/SL price) for STOP_LIMIT order Trigger Condition, trigger_price={trigger_price}, entry_price={entry_price_for_ref}")
        
        # Format ref_price with SAME precision as trigger_price to ensure they match exactly
        # This is critical: Crypto.com uses ref_price for Trigger Condition display
        # We want Trigger Condition to show SL price (trigger_price), so ref_price should equal trigger_price
        # Normalize ref_price using same method as trigger_price (per Rule 3: STOP_LOSS uses ROUND_DOWN)
        # Since ref_price should match trigger_price, we'll normalize it and then force exact match
        normalized_ref_str = self.normalize_price(symbol, ref_price, side, order_type="STOP_LOSS")
        if normalized_ref_str is None:
            # If normalization fails, just use trigger_str (they should be equal anyway)
            ref_price_str = trigger_str
        else:
            ref_price_str = normalized_ref_str
        
        # CRITICAL: Ensure ref_price_str equals trigger_str exactly (both represent SL price)
        # This ensures Trigger Condition shows SL price, not entry_price
        if ref_price_str != trigger_str:
            logger.warning(f"⚠️ ref_price_str ({ref_price_str}) != trigger_str ({trigger_str}). Forcing ref_price_str = trigger_str to ensure correct Trigger Condition.")
            ref_price_str = trigger_str  # Force exact match
        
        # Generate client_oid for tracking
        client_oid = str(uuid.uuid4())
        
        # Try different parameter combinations until one works
        # Also try different side formats - STOP_LIMIT may require specific side format
        side_upper = side.upper() if side else "SELL"
        side_lower = side.lower() if side else "sell"
        
        # Helper function to create params dict with margin support
        def create_params_dict(side_format: str, include_time_in_force: bool = True, include_client_oid: bool = True) -> dict:
            params = {
                "instrument_name": symbol,
                "side": side_format,
                "type": "STOP_LIMIT",
                "price": price_str,
                "quantity": qty_str,
                "trigger_price": trigger_str,
                "ref_price": ref_price_str
            }
            # Crypto.com expects "GOOD_TILL_CANCEL" (and rejects "GTC" with Error 40003).
            if include_time_in_force:
                params["time_in_force"] = "GOOD_TILL_CANCEL"
            if include_client_oid:
                params["client_oid"] = client_oid
            # Add leverage if margin trading
            if is_margin and leverage:
                params["leverage"] = str(int(leverage))
            return params
        
        # Create variations with different side formats and parameter combinations
        params_variations = []
        
        # Variation 1-4: With side.upper() (UPPERCASE)
        params_variations.extend([
            # Variation 1: All params with UPPERCASE side
            create_params_dict(side_upper, include_time_in_force=True, include_client_oid=True),
            # Variation 2: Without time_in_force, UPPERCASE side
            create_params_dict(side_upper, include_time_in_force=False, include_client_oid=True),
            # Variation 3: Without client_oid, UPPERCASE side
            create_params_dict(side_upper, include_time_in_force=True, include_client_oid=False),
            # Variation 4: Minimal params, UPPERCASE side
            create_params_dict(side_upper, include_time_in_force=False, include_client_oid=False)
        ])
        
        # Variation 5-8: With side.lower() (lowercase) - some APIs prefer lowercase
        params_variations.extend([
            # Variation 5: All params with lowercase side
            create_params_dict(side_lower, include_time_in_force=True, include_client_oid=True),
            # Variation 6: Without time_in_force, lowercase side
            create_params_dict(side_lower, include_time_in_force=False, include_client_oid=True),
            # Variation 7: Without client_oid, lowercase side
            create_params_dict(side_lower, include_time_in_force=True, include_client_oid=False),
            # Variation 8: Minimal params, lowercase side
            create_params_dict(side_lower, include_time_in_force=False, include_client_oid=False)
        ])
        
        # Variation 9-12: Additional variations to handle error 40004
        # IMPORTANT: Always include ref_price with SL price value to ensure correct Trigger Condition
        params_variations.extend([
            # Variation 9: Without client_oid but WITH ref_price (ref_price is required for correct Trigger Condition)
            {
                "instrument_name": symbol,
                "side": side_upper,
                "type": "STOP_LIMIT",
                "price": price_str,
                "quantity": qty_str,
                "trigger_price": trigger_str,
                "ref_price": ref_price_str  # Always include ref_price = SL price
            },
            # Variation 10: Minimal params but WITH ref_price (ref_price is required for correct Trigger Condition)
            {
                "instrument_name": symbol,
                "side": side_upper,
                "type": "STOP_LIMIT",
                "price": price_str,
                "quantity": qty_str,
                "trigger_price": trigger_str,
                "ref_price": ref_price_str  # Always include ref_price = SL price
            },
            # Variation 11: Different parameter order (trigger_price before price)
            {
                "instrument_name": symbol,
                "side": side_upper,
                "type": "STOP_LIMIT",
                "trigger_price": trigger_str,
                "price": price_str,
                "quantity": qty_str,
                "ref_price": ref_price_str
            },
            # Variation 12: Explicit time_in_force (GOOD_TILL_CANCEL)
            {
                "instrument_name": symbol,
                "side": side_upper,
                "type": "STOP_LIMIT",
                "price": price_str,
                "quantity": qty_str,
                "trigger_price": trigger_str,
                "ref_price": ref_price_str,
                "time_in_force": "GOOD_TILL_CANCEL"
            }
        ])
        
        # Try each variation until one works
        last_error = None
        variation_names = [
            "all params (UPPERCASE side)", "without time_in_force (UPPERCASE side)", 
            "without client_oid (UPPERCASE side)", "minimal params (UPPERCASE side)",
            "all params (lowercase side)", "without time_in_force (lowercase side)",
            "without client_oid (lowercase side)", "minimal params (lowercase side)",
            "without client_oid + ref_price (UPPERCASE side)", "minimal + ref_price (UPPERCASE side)",
            "different param order (UPPERCASE side)", "GTC time_in_force (UPPERCASE side)"
        ]
        
        for variation_idx, params in enumerate(params_variations, 1):
            variation_name = variation_names[variation_idx - 1] if variation_idx <= len(variation_names) else f"variation {variation_idx}"
            logger.info(f"🔄 Trying STOP_LIMIT params variation {variation_idx}: {variation_name}")
            
            try:
                # Generate unique request ID for tracking
                import uuid as uuid_module
                request_id = str(uuid_module.uuid4())
                
                logger.info(f"Live: place_stop_loss_order - {symbol} {side} {qty} @ {price} trigger={trigger_price}")
                logger.info(f"Params sent: {params}")  # Log params at INFO level for debugging
                logger.info(f"Price string: '{price_str}', Quantity string: '{qty_str}', Trigger string: '{trigger_str}'")
                
                # Use proxy if enabled (same as successful orders)
                if self.use_proxy:
                    logger.info(f"[SL_ORDER][{source.upper()}][{request_id}] Using PROXY to place stop loss order")
                    try:
                        result = self._call_proxy(method, params)
                        if not isinstance(result, dict):
                            logger.warning(f"Unexpected proxy response type: {type(result)}")
                            last_error = "Unexpected proxy response type"
                            continue

                        # Proxy returns Crypto.com body: {"code": <int>, "result": {...}} on success
                        code = result.get("code", 0)
                        if code != 0:
                            msg = result.get("message", "Unknown error")
                            last_error = f"Error {code}: {msg}"
                            # If proxy returns an auth/IP error, try the existing TRADE_BOT failover path.
                            # This reuses the same failover system already used elsewhere (e.g. market orders).
                            if code in [40101, 40103]:
                                logger.warning(
                                    f"⚠️ Proxy SL order auth failure (code={code}). Attempting failover to TRADE_BOT."
                                )
                                if _should_failover(401):
                                    order_data = {
                                        "symbol": symbol,
                                        "side": side.upper(),
                                        "type": "STOP_LIMIT",
                                        "qty": qty,
                                        "price": price,
                                        "trigger_price": trigger_price,
                                    }
                                    if entry_price:
                                        order_data["entry_price"] = entry_price
                                    if is_margin and leverage:
                                        order_data["is_margin"] = True
                                        order_data["leverage"] = int(leverage)
                                    try:
                                        fr = self._fallback_place_order(order_data)
                                        if fr.status_code == 200:
                                            data = fr.json()
                                            result_data = data.get("result", data)
                                            order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                            if order_id:
                                                logger.info(
                                                    f"✅ Successfully created SL order via TRADE_BOT fallback: order_id={order_id}"
                                                )
                                                return {"order_id": str(order_id), "error": None}
                                    except Exception as fallback_err:
                                        logger.error(f"TRADE_BOT fallback failed for SL order: {fallback_err}", exc_info=True)
                            logger.warning(f"⚠️ Proxy SL order failed: {last_error}")
                            continue

                        order_result = result.get("result") or {}
                        order_id = order_result.get("order_id") or order_result.get("client_order_id")
                        if order_id:
                            logger.info(f"✅ Successfully created SL order via PROXY: order_id={order_id}")
                            return {"order_id": str(order_id), "error": None}

                        logger.warning(f"Proxy SL order success but missing order_id: {result}")
                        last_error = "Proxy success missing order_id"
                        continue
                    except requests.exceptions.RequestException as proxy_err:
                        logger.warning(f"Proxy error: {proxy_err} - falling back to direct API call")
                        # Fall through to direct API call below
                    except Exception as proxy_err:
                        logger.warning(f"Proxy error: {proxy_err} - falling back to direct API call")
                        # Fall through to direct API call below
                
                # Direct API call (when proxy is disabled or proxy failed)
                payload = self.sign_request(method, params)
                # SECURITY: never log signed payloads (api_key/sig).
                try:
                    payload_keys = sorted(list(payload.keys()))
                    params_keys = sorted(list((payload.get("params") or {}).keys()))
                except Exception:
                    payload_keys = []
                    params_keys = []
                
                url = f"{self.base_url}/{method}"
                
                # Log HTTP request details with source and request_id
                logger.info(
                    f"[SL_ORDER][{source.upper()}][{request_id}] Sending HTTP request to exchange:\n"
                    f"  URL: {url}\n"
                    f"  Method: POST\n"
                    f"  Source: {source}\n"
                    f"  Payload keys: {payload_keys}\n"
                    f"  Params keys: {params_keys}"
                )
                
                logger.debug(f"Request URL: {url}")
                response = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.create_params_dict")
                
                # Log HTTP response details
                try:
                    response_body = response.json()
                except:
                    response_body = response.text
                
                logger.info(
                    f"[SL_ORDER][{source.upper()}][{request_id}] Received HTTP response from exchange:\n"
                    f"  Status Code: {response.status_code}\n"
                    f"  Response Body: {json.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, dict) else response_body}"
                )
                
                if response.status_code == 401:
                    error_data = response.json()
                    error_code = error_data.get("code", 0)
                    error_msg = error_data.get("message", "")
                    logger.error(f"Authentication failed: {error_code} - {error_msg}")
                    
                    # Try fallback to TRADE_BOT (same as successful orders)
                    if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                        logger.warning("Authentication failure for stop loss order - attempting failover to TRADE_BOT")
                        if _should_failover(401):
                            # Build order data for TRADE_BOT fallback
                            order_data = {
                                "symbol": symbol,
                                "side": side.upper(),
                                "type": "STOP_LIMIT",
                                "qty": qty,
                                "price": price,
                                "trigger_price": trigger_price
                            }
                            if entry_price:
                                order_data["entry_price"] = entry_price
                            if is_margin and leverage:
                                order_data["is_margin"] = True
                                order_data["leverage"] = int(leverage)
                            
                            try:
                                logger.info(f"Calling TRADE_BOT fallback for SL order: {order_data}")
                                fr = self._fallback_place_order(order_data)
                                logger.info(f"TRADE_BOT fallback response status: {fr.status_code}")
                                if fr.status_code == 200:
                                    data = fr.json()
                                    logger.info(f"TRADE_BOT fallback response: {data}")
                                    result_data = data.get("result", data)
                                    order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                    if order_id:
                                        logger.info(f"✅ Successfully created SL order via TRADE_BOT fallback: order_id={order_id}")
                                        return {"order_id": str(order_id), "error": None}
                                    else:
                                        logger.warning(f"TRADE_BOT fallback succeeded but no order_id in response: {result_data}")
                                else:
                                    logger.warning(f"TRADE_BOT fallback failed with status {fr.status_code}: {fr.text[:200]}")
                            except Exception as fallback_err:
                                logger.error(f"TRADE_BOT fallback failed: {fallback_err}", exc_info=True)
                        else:
                            logger.warning(f"Failover not enabled or TRADEBOT_BASE not configured. FAILOVER_ENABLED={FAILOVER_ENABLED}, TRADEBOT_BASE={TRADEBOT_BASE}")
                    
                    return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
            
                # Check for error responses (400, etc.) before raise_for_status
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        error_code = error_data.get('code', 0)
                        error_msg = error_data.get('message', 'Unknown error')
                        
                        # If error 213 (Invalid quantity format), try different precision
                        if error_code == 213:
                            logger.warning(f"⚠️ Variation {variation_idx} failed with error 213 (Invalid quantity format). Trying different precision levels...")
                            last_error = f"Error {error_code}: {error_msg}"
                            
                            # Define precision levels to try (same as MARKET SELL orders)
                            import decimal
                            precision_levels = [
                                (2, decimal.Decimal('0.01')),      # Most common: 2 decimals
                                (8, decimal.Decimal('0.00000001')), # Low-value coins like DOGE
                                (6, decimal.Decimal('0.000001')),   # High-value coins like BTC
                                (4, decimal.Decimal('0.0001')),     # Medium precision
                                (3, decimal.Decimal('0.001')),      # Lower precision
                                (1, decimal.Decimal('0.1')),         # Very low precision
                                (0, decimal.Decimal('1')),          # Whole numbers only
                            ]
                            
                            # Get instrument metadata for comparison
                            inst_meta_retry = self._get_instrument_metadata(symbol)
                            got_instrument_info_retry = inst_meta_retry is not None
                            quantity_decimals_retry = inst_meta_retry.get("quantity_decimals") if inst_meta_retry else None
                            
                            # Try ALL different precision levels automatically
                            # This works even if we got instrument info (it might be wrong or insufficient)
                            precision_tried_this_variation = False
                            for prec_decimals, prec_tick in precision_levels:
                                # Skip the precision we already tried for this variation
                                if got_instrument_info_retry and prec_decimals == quantity_decimals_retry and not precision_tried_this_variation:
                                    precision_tried_this_variation = True
                                    continue  # Already tried this precision
                                
                                logger.info(f"🔄 Trying variation {variation_idx} with precision {prec_decimals} decimals (tick_size={prec_tick})...")
                                
                                # Re-format quantity with new precision using Decimal for exact rounding
                                # Per Rule 3: All quantities use ROUND_DOWN (never exceed available balance)
                                qty_decimal = decimal.Decimal(str(qty))
                                tick_decimal = prec_tick  # Already a Decimal
                                qty_decimal = (qty_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_DOWN) * tick_decimal
                                
                                # Format with exact precision - always use fixed point notation (no scientific notation)
                                # Crypto.com API expects a string with exact number of decimals
                                # DO NOT strip trailing zeros - they may be required for some instruments
                                if prec_decimals == 0:
                                    # Whole number only
                                    qty_str_new = str(int(qty_decimal))
                                else:
                                    # Format with exact precision - always show exactly prec_decimals decimals
                                    # Use fixed format to avoid scientific notation (e.g., 5106.33760000 instead of 5.1063376e+03)
                                    qty_str_new = format(qty_decimal, f'.{prec_decimals}f')
                                    # Keep trailing zeros - Crypto.com may require them for validation
                                    # Example: DOGE_USDT may require "5106.33760000" (8 decimals) not "5106.3376"
                                
                                logger.info(f"Quantity formatted: {qty} -> '{qty_str_new}' (precision {prec_decimals} decimals, length={len(qty_str_new)})")
                                
                                # Update params with new quantity (preserve all other params from this variation)
                                params_updated = params.copy()
                                params_updated["quantity"] = qty_str_new
                                
                                # Try this variation with new precision
                                try:
                                    payload = self.sign_request(method, params_updated)
                                    url = f"{self.base_url}/{method}"
                                    
                                    # Log HTTP request for precision variation
                                    import uuid as uuid_module
                                    request_id_prec = str(uuid_module.uuid4())
                                    # SECURITY: never log signed payloads (api_key/sig). Log keys only.
                                    try:
                                        payload_keys = sorted(list(payload.keys()))
                                        payload_params_keys = sorted(list((payload.get("params") or {}).keys()))
                                    except Exception:
                                        payload_keys = []
                                        payload_params_keys = []
                                    logger.info(
                                        f"[SL_ORDER][{source.upper()}][{request_id_prec}] Sending HTTP request (precision variation {prec_decimals}):\n"
                                        f"  URL: {url}\n"
                                        f"  Method: POST\n"
                                        f"  Source: {source}\n"
                                        f"  Payload keys: {payload_keys}\n"
                                        f"  Params keys: {payload_params_keys}"
                                    )
                                    
                                    response_prec = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.create_params_dict")
                                    
                                    # Log HTTP response for precision variation
                                    try:
                                        response_body_prec = response_prec.json()
                                    except:
                                        response_body_prec = response_prec.text
                                    
                                    logger.info(
                                        f"[SL_ORDER][{source.upper()}][{request_id_prec}] Received HTTP response (precision variation {prec_decimals}):\n"
                                        f"  Status Code: {response_prec.status_code}\n"
                                        f"  Response Body: {json.dumps(response_body_prec, ensure_ascii=False, indent=2) if isinstance(response_body_prec, dict) else response_body_prec}"
                                    )
                                    
                                    if response_prec.status_code == 200:
                                        result = response_prec.json()
                                        logger.info(f"✅ Successfully placed stop loss order with variation {variation_idx} and precision {prec_decimals} decimals!")
                                        return result.get("result", {})
                                    
                                    # Check if it's still error 213 (then try next precision) or different error (then try next variation)
                                    if response_prec.status_code != 200:
                                        try:
                                            error_data_prec = response_prec.json()
                                            new_error_code = error_data_prec.get('code', 0)
                                            new_error_msg = error_data_prec.get('message', 'Unknown error')
                                            logger.debug(f"Precision {prec_decimals} failed with error {new_error_code}: {new_error_msg}")
                                            if new_error_code != 213:
                                                # Different error - stop trying precisions and try next variation
                                                logger.debug(f"Different error {new_error_code} with precision {prec_decimals}, trying next variation")
                                                break
                                        except Exception as parse_err:
                                            logger.debug(f"Error parsing response with precision {prec_decimals}: {parse_err}")
                                            pass  # Continue trying precisions
                                except Exception as prec_err:
                                    logger.warning(f"Error trying precision {prec_decimals}: {prec_err}")
                                    continue  # Try next precision
                            
                            # If all precision levels failed for this variation, try next variation
                            logger.warning(f"⚠️ All precision levels failed for variation {variation_idx}, trying next variation...")
                            continue  # Try next variation
                        elif error_code == 220:
                            logger.warning(f"⚠️ Variation {variation_idx} failed with error 220 (INVALID_SIDE). Trying next variation...")
                            last_error = f"Error {error_code}: {error_msg}"
                            continue  # Try next variation
                        elif error_code == 308:
                            logger.warning(f"⚠️ Variation {variation_idx} failed with error 308 (Invalid price format). Trying different price precision...")
                            last_error = f"Error {error_code}: {error_msg}"
                            
                            # Try to fetch instrument info again if we didn't get it initially
                            # This helps us use the correct tick size for the symbol
                            # Define variables for price precision retry
                            import decimal
                            retry_price_decimals = None
                            retry_price_tick_size = None
                            got_instrument_info_retry = False
                            
                            # Get instrument metadata if not already fetched
                            inst_meta_retry = self._get_instrument_metadata(symbol)
                            if inst_meta_retry:
                                got_instrument_info_retry = True
                                retry_price_decimals = inst_meta_retry.get("price_decimals")
                                price_tick_size_str_retry = inst_meta_retry.get("price_tick_size", "0.01")
                                try:
                                    retry_price_tick_size = float(price_tick_size_str_retry) if price_tick_size_str_retry else None
                                except:
                                    retry_price_tick_size = None
                            
                            if not got_instrument_info_retry:
                                try:
                                    import requests as req
                                    inst_url = "https://api.crypto.com/exchange/v1/public/get-instruments"
                                    inst_response = req.get(inst_url, timeout=10)
                                    if inst_response.status_code == 200:
                                        inst_data = inst_response.json()
                                        if "result" in inst_data and "instruments" in inst_data["result"]:
                                            for inst in inst_data["result"]["instruments"]:
                                                inst_name = inst.get("instrument_name", "") or inst.get("symbol", "")
                                                if inst_name.upper() == symbol.upper():
                                                    retry_price_decimals = inst.get("price_decimals")
                                                    price_tick_size_str = inst.get("price_tick_size", "0.01")
                                                    try:
                                                        retry_price_tick_size = float(price_tick_size_str) if price_tick_size_str else None
                                                    except:
                                                        retry_price_tick_size = None
                                                    logger.info(f"✅ Retry: Got instrument info for {symbol}: price_decimals={retry_price_decimals}, price_tick_size={retry_price_tick_size}")
                                                    break
                                except Exception as retry_inst_err:
                                    logger.debug(f"Could not fetch instrument info on retry for {symbol}: {retry_inst_err}")
                            
                            # Build price precision levels - prioritize common tick sizes
                            # For low-price coins like ALGO_USDT, 4 decimals (0.0001) is most common
                            price_precision_levels = []
                            
                            # If we have instrument info, use it first
                            if retry_price_decimals is not None and retry_price_tick_size is not None:
                                price_precision_levels.append((retry_price_decimals, retry_price_tick_size))
                                logger.info(f"🔄 Will try instrument-specific precision first: {retry_price_decimals} decimals, tick_size={retry_price_tick_size}")
                            
                            # Add common precision levels, prioritizing 4 decimals for low-price coins
                            common_levels = [
                                (4, 0.0001),    # 4 decimals - most common for coins like ALGO_USDT
                                (5, 0.00001),   # 5 decimals
                                (6, 0.000001),  # 6 decimals
                                (3, 0.001),     # 3 decimals
                                (2, 0.01),      # 2 decimals
                                (1, 0.1),       # 1 decimal
                            ]
                            
                            # Add common levels, avoiding duplicates
                            for prec_decimals, prec_tick in common_levels:
                                if (prec_decimals, prec_tick) not in price_precision_levels:
                                    price_precision_levels.append((prec_decimals, prec_tick))
                            
                            # Try different price precisions
                            price_precision_success = False
                            for prec_decimals, prec_tick in price_precision_levels:
                                logger.info(f"🔄 Trying variation {variation_idx} with price precision {prec_decimals} decimals (tick_size={prec_tick})...")
                                
                                # Re-format price with new precision using proper tick size rounding
                                # Per Rule 3: STOP_LOSS uses ROUND_DOWN (conservative trigger)
                                price_decimal_new = decimal.Decimal(str(price))
                                tick_decimal_new = decimal.Decimal(str(prec_tick))
                                price_decimal_new = (price_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_DOWN) * tick_decimal_new
                                price_str_new = f"{price_decimal_new:.{prec_decimals}f}"
                                
                                # Re-format trigger_price with same precision
                                # Per Rule 3: STOP_LOSS triggers use ROUND_DOWN
                                trigger_decimal_new = decimal.Decimal(str(trigger_price))
                                trigger_decimal_new = (trigger_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_DOWN) * tick_decimal_new
                                trigger_str_new = f"{trigger_decimal_new:.{prec_decimals}f}"
                                
                                logger.info(f"Price formatted: {price} -> '{price_str_new}', Trigger: {trigger_price} -> '{trigger_str_new}'")
                                
                                # Update params with new price precision
                                params_updated = params.copy()
                                params_updated["price"] = price_str_new
                                params_updated["trigger_price"] = trigger_str_new
                                
                                # Also update ref_price with same precision if present
                                if "ref_price" in params_updated:
                                    ref_price_val = params_updated.get("ref_price")
                                    if ref_price_val:
                                        try:
                                            # Per Rule 3: STOP_LOSS uses ROUND_DOWN (ref_price should match trigger_price)
                                            ref_decimal_new = decimal.Decimal(str(ref_price_val))
                                            ref_decimal_new = (ref_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_DOWN) * tick_decimal_new
                                            ref_str_new = f"{ref_decimal_new:.{prec_decimals}f}"
                                            params_updated["ref_price"] = ref_str_new
                                            logger.debug(f"Ref_price also formatted: {ref_price_val} -> '{ref_str_new}'")
                                        except Exception as ref_err:
                                            logger.debug(f"Could not format ref_price: {ref_err}")
                                            # Keep original ref_price if formatting fails
                                
                                # Try this variation with new price precision
                                try:
                                    payload = self.sign_request(method, params_updated)
                                    url = f"{self.base_url}/{method}"
                                    response_prec = http_post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10, calling_module="crypto_com_trade.create_params_dict")
                                    
                                    if response_prec.status_code == 200:
                                        result = response_prec.json()
                                        logger.info(f"✅ Successfully placed stop loss order with variation {variation_idx} and price precision {prec_decimals} decimals!")
                                        price_precision_success = True
                                        return result.get("result", {})
                                    
                                    # Check if it's still error 308 (then try next precision) or different error (then try next variation)
                                    if response_prec.status_code != 200:
                                        try:
                                            error_data_prec = response_prec.json()
                                            new_error_code = error_data_prec.get('code', 0)
                                            new_error_msg = error_data_prec.get('message', 'Unknown error')
                                            logger.info(f"Price precision {prec_decimals} ({price_str_new}/{trigger_str_new}) failed with error {new_error_code}: {new_error_msg}")
                                            if new_error_code != 308:
                                                # Different error - stop trying price precisions and try next variation
                                                logger.warning(f"Different error {new_error_code} with price precision {prec_decimals}, trying next variation")
                                                break
                                        except Exception as parse_err:
                                            logger.warning(f"Error parsing response with price precision {prec_decimals}: {parse_err}, response: {response_prec.text[:200]}")
                                            # Continue trying precisions
                                except Exception as prec_err:
                                    logger.warning(f"Error trying price precision {prec_decimals}: {prec_err}")
                                    continue  # Try next precision
                            
                            # If all price precision levels failed for this variation, try next variation
                            if not price_precision_success:
                                logger.warning(f"⚠️ All price precision levels failed for variation {variation_idx}, trying next variation...")
                            continue  # Try next variation
                        elif error_code == 40004:
                            logger.warning(f"⚠️ Variation {variation_idx} failed with error 40004 (Missing or invalid argument). Trying next variation...")
                            last_error = f"Error {error_code}: {error_msg}"
                            continue  # Try next variation
                        elif error_code == 140001:
                            # Conditional orders (STOP_LIMIT/TAKE_PROFIT_LIMIT) can be disabled at the account level.
                            # If this happens, retrying formatting variations won't help.
                            logger.error(
                                f"❌ STOP_LIMIT rejected with code 140001 (API_DISABLED): {error_msg}. "
                                f"This account likely cannot place conditional orders (TP/SL) via API."
                            )
                            try:
                                # Do NOT mark trigger orders unavailable here. A failure-only fallback may still
                                # succeed via the migrated batch endpoint (`private/create-order-list`).
                                self._send_conditional_orders_api_disabled_alert(code=140001, message=str(error_msg or "API_DISABLED"))
                            except Exception:
                                pass
                            return {"error": f"Error {error_code}: {error_msg} (API_DISABLED)"}
                        
                        # For other errors, return immediately
                        logger.error(f"Error creating stop loss order: HTTP {response.status_code}, code={error_code}, message={error_msg}, symbol={symbol}, price={price}, qty={qty}")
                        return {"error": f"Error {error_code}: {error_msg}"}
                    except Exception as parse_err:
                        logger.error(f"Error parsing error response: {parse_err}, response text: {response.text[:200]}")
                        return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
                
                # Success!
                response.raise_for_status()
                result = response.json()

                # Crypto.com may return HTTP 200 with auth failure in the JSON body.
                if isinstance(result, dict) and result.get("code") in [40101, 40103]:
                    error_code = result.get("code", 0)
                    error_msg = result.get("message", "Authentication failure")
                    logger.error(f"Authentication failed: {error_code} - {error_msg}")
                    if _should_failover(401):
                        order_data = {
                            "symbol": symbol,
                            "side": side.upper(),
                            "type": "STOP_LIMIT",
                            "qty": qty,
                            "price": price,
                            "trigger_price": trigger_price,
                        }
                        if entry_price:
                            order_data["entry_price"] = entry_price
                        if is_margin and leverage:
                            order_data["is_margin"] = True
                            order_data["leverage"] = int(leverage)
                        try:
                            fr = self._fallback_place_order(order_data)
                            if fr.status_code == 200:
                                data = fr.json()
                                result_data = data.get("result", data)
                                order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                if order_id:
                                    logger.info(
                                        f"✅ Successfully created SL order via TRADE_BOT fallback: order_id={order_id}"
                                    )
                                    return {"order_id": str(order_id), "error": None}
                        except Exception as fallback_err:
                            logger.error(f"TRADE_BOT fallback failed for SL order: {fallback_err}", exc_info=True)
                    return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
                
                logger.info(f"✅ Successfully placed stop loss order with variation {variation_idx}: {variation_name}")
                logger.debug(f"Response: {result}")
                
                return result.get("result", {})
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"⚠️ Variation {variation_idx} failed with network error: {e}. Trying next variation...")
                last_error = str(e)
                continue  # Try next variation
            except Exception as e:
                logger.warning(f"⚠️ Variation {variation_idx} failed with error: {e}. Trying next variation...")
                last_error = str(e)
                continue  # Try next variation
        
        # All variations failed
        logger.error(f"❌ All parameter variations failed. Last error: {last_error}")
        return {"error": f"All variations failed. Last error: {last_error}"}
    
    def place_take_profit_order(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        *,
        trigger_price: Optional[float] = None,
        entry_price: Optional[float] = None,
        is_margin: bool = False,
        leverage: Optional[float] = None,
        dry_run: bool = True,
        source: str = "unknown"  # "auto" or "manual" to track the source
    ) -> dict:
        """Place take profit order (TAKE_PROFIT_LIMIT)"""
        self._refresh_runtime_flags()
        actual_dry_run = dry_run or not self.live_trading
        
        if actual_dry_run:
            logger.info(f"DRY_RUN: place_take_profit_order - {symbol} {side} {qty} @ {price}")
            return {
                "order_id": f"dry_tp_{int(time.time())}",
                "client_order_id": f"dry_tp_{int(time.time())}",
                "status": "OPEN",
                "side": side,
                "type": "TAKE_PROFIT_LIMIT",
                "quantity": str(qty),
                "price": str(price),
                "created_time": int(time.time() * 1000)
            }
        
        method = "private/create-order"
        
        # Normalize price using helper function (per Rule 3: TAKE_PROFIT uses ROUND_UP)
        normalized_price_str = self.normalize_price(symbol, price, side, order_type="TAKE_PROFIT")
        if normalized_price_str is None:
            error_msg = f"Instrument metadata unavailable for {symbol} - cannot format price"
            logger.error(f"❌ [TAKE_PROFIT_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ TAKE_PROFIT order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "instrument_metadata_unavailable"
            }
        price_str = normalized_price_str
        
        # Normalize quantity using shared helper (per documented logic: docs/trading/crypto_com_order_formatting.md)
        raw_quantity = float(qty)
        normalized_qty_str = self.normalize_quantity(symbol, raw_quantity)
        
        # Fail-safe: block order if normalization failed
        if normalized_qty_str is None:
            inst_meta = self._get_instrument_metadata(symbol)
            min_quantity = (
                (inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?")
                if inst_meta
                else "?"
            )
            error_msg = f"Quantity {raw_quantity} for {symbol} is below min_quantity {min_quantity} after normalization"
            logger.error(f"❌ [TAKE_PROFIT_ORDER] {error_msg}")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ TAKE_PROFIT order failed: {error_msg}")
            except Exception:
                pass
            return {
                "error": error_msg,
                "status": "FAILED",
                "reason": "quantity_below_min"
            }
        
        # Get instrument metadata for debug logging
        inst_meta = self._get_instrument_metadata(symbol)
        if inst_meta:
            quantity_decimals = inst_meta["quantity_decimals"]
            qty_tick_size = inst_meta["qty_tick_size"]
            min_quantity = inst_meta.get("min_quantity") or inst_meta.get("qty_tick_size") or "?"
        else:
            quantity_decimals = 4
            qty_tick_size = "0.0001"
            min_quantity = "?"
        
        # Deterministic debug logs (before sending order)
        logger.info("=" * 80)
        logger.info(f"[ORDER_PLACEMENT] Preparing TAKE_PROFIT_LIMIT order")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Side: {side}")
        logger.info(f"  Order Type: TAKE_PROFIT_LIMIT")
        logger.info(f"  Price: {price} -> {price_str}")
        logger.info(f"  Raw Quantity: {raw_quantity}")
        logger.info(f"  Final Quantity: {normalized_qty_str}")
        logger.info(f"  Instrument Rules:")
        logger.info(f"    - quantity_decimals: {quantity_decimals}")
        logger.info(f"    - qty_tick_size: {qty_tick_size}")
        logger.info(f"    - min_quantity: {min_quantity}")
        logger.info("=" * 80)
        
        qty_str = normalized_qty_str
        
        # Format trigger_price if provided (should be equal to price for TAKE_PROFIT_LIMIT)
        # IMPORTANT: For TAKE_PROFIT_LIMIT, trigger_price MUST equal price (TP Value)
        # Both represent the same value: the price at which the order triggers and executes
        trigger_str = None
        if trigger_price is not None:
            # Verify that trigger_price equals price (both should be TP Value)
            if abs(trigger_price - price) > 0.0001:  # Allow small floating point differences
                logger.warning(f"⚠️ TAKE_PROFIT_LIMIT: trigger_price ({trigger_price}) != price ({price}). Setting trigger_price = price.")
                trigger_price = price  # Force equality
            
            # Normalize trigger_price using helper function (per Rule 3: TAKE_PROFIT uses ROUND_UP)
            normalized_trigger_str = self.normalize_price(symbol, trigger_price, side, order_type="TAKE_PROFIT")
            if normalized_trigger_str is None:
                # If normalization fails, use price_str (they should be equal anyway)
                trigger_str = price_str
            else:
                trigger_str = normalized_trigger_str
        else:
            # If no trigger_price provided, use price as trigger (both are TP Value)
            logger.info(f"TAKE_PROFIT_LIMIT: No trigger_price provided, using price ({price}) as trigger_price (TP Value)")
            trigger_price = price  # Set trigger_price to price
            trigger_str = price_str  # Use same formatted string (already normalized)
        
        # Generate client_oid for tracking
        client_oid = str(uuid.uuid4())
        
        # Build SAFE price format variations derived from the normalized (tick-quantized) price.
        #
        # IMPORTANT:
        # - We should NOT change the TP value (e.g. rounding to int) just to satisfy formatting.
        # - We only vary *string representation* (decimal padding / optional trimming) of the SAME normalized value.
        import decimal
        inst_meta_format = self._get_instrument_metadata(symbol) or {}
        price_tick_size_str = str(inst_meta_format.get("price_tick_size") or "0.01")
        price_decimals_format = inst_meta_format.get("price_decimals")

        # Ensure trigger_price is set (must equal price for TAKE_PROFIT_LIMIT)
        if trigger_price is None:
            trigger_price = price
            trigger_str = price_str
            logger.info(f"TAKE_PROFIT_LIMIT: trigger_price was None, using price ({price}) as trigger_price")

        # Derive decimal candidates from metadata + current normalized string
        base_decimals = len(price_str.split(".", 1)[1]) if "." in price_str else 0
        tick_decimals = 0
        if "." in price_tick_size_str:
            frac = price_tick_size_str.split(".", 1)[1]
            tick_decimals = len(frac.rstrip("0"))

        decimals_candidates = [base_decimals, tick_decimals]
        try:
            if price_decimals_format is not None:
                decimals_candidates.append(int(price_decimals_format))
        except Exception:
            pass

        # Keep unique, non-negative
        unique_decimals = sorted({int(d) for d in decimals_candidates if d is not None and int(d) >= 0})

        price_decimal_norm = decimal.Decimal(str(price_str))
        price_format_variations = [format(price_decimal_norm, f".{d}f") for d in unique_decimals]

        # Optional: also try trimmed representation (some endpoints accept variable decimals)
        trimmed = price_str.rstrip("0").rstrip(".")
        if trimmed and trimmed not in price_format_variations:
            price_format_variations.append(trimmed)

        # De-dupe while preserving order
        seen = set()
        unique_price_formats = []
        for fmt in price_format_variations:
            if fmt not in seen:
                seen.add(fmt)
                unique_price_formats.append(fmt)

        # For TAKE_PROFIT_LIMIT, trigger_price MUST equal price (same value, same format).
        unique_trigger_formats = unique_price_formats

        logger.info(
            f"🔄 Trying TAKE_PROFIT_LIMIT with {len(unique_price_formats)} safe price/trigger format variations "
            f"(tick_size={price_tick_size_str}, price_decimals={price_decimals_format})"
        )
        
        last_error = "Unknown error"
        
        # For TAKE_PROFIT_LIMIT, ref_price MUST be the TP PRICE (same as trigger_price and price)
        # Based on error 229 (INVALID_REF_PRICE) analysis, Crypto.com expects ref_price = TP price
        # trigger_condition = ">= {TP_price}" where TP_price is the TP price
        # This ensures the order activates when price reaches the TP level
        # ref_price will be set to the TP price (same as trigger_price) in the loop below
        
        # Always use ref_price for TAKE_PROFIT_LIMIT (required by API)
        # ref_price should be the TP price, NOT entry_price (this causes error 229)
        
        # For TAKE_PROFIT_LIMIT, trigger_price MUST equal price (both are the TP price)
        # So we only iterate over price formats, not trigger formats
        # IMPORTANT: Both trigger_price and price must be the TP price value
        for price_fmt_idx, price_fmt in enumerate(unique_price_formats, 1):
            variation_name = f"{price_fmt_idx}"
            
            # Try different parameter combinations similar to STOP_LIMIT
            # Create multiple variations with different parameter combinations
            # CRITICAL: For TAKE_PROFIT_LIMIT orders, side MUST be the closing side:
            # - After BUY (long position): side MUST be SELL (to close the position)
            # - After SELL (short position): side MUST be BUY (to close the position)
            # The 'side' parameter passed to this function should already be the closing side
            # (inverted from entry), but we ensure it's correct here
            
            side_upper = side.upper() if side else "SELL"
            
            # IMPORTANT: Only use the correct closing side - do NOT try both BUY and SELL
            # If side is already correct (SELL for long positions), use only SELL
            # If side is incorrect (BUY for long positions), this is a bug upstream and should be fixed
            # For now, prioritize SELL for long positions (most common case)
            if side_upper == "SELL":
                # Correct: SELL is the closing side for long positions (BUY entry)
                side_variations = ["SELL"]  # Only try SELL - this is correct
            elif side_upper == "BUY":
                # This should only happen for short positions (SELL entry)
                # But if we're here for a long position, it's a bug - log warning
                logger.warning(f"⚠️ TAKE_PROFIT_LIMIT: side=BUY received. This is only correct for short positions (SELL entry). If this is for a long position (BUY entry), this is a bug!")
                side_variations = ["BUY"]  # Only try BUY - this should be correct for short positions
            else:
                # Fallback: default to SELL (most common case - long positions)
                logger.warning(f"⚠️ TAKE_PROFIT_LIMIT: Invalid side '{side}', defaulting to SELL")
                side_variations = ["SELL"]
            
            unique_sides = side_variations  # No need to deduplicate since we only have one
            
            # Try each side variation
            for side_fmt in unique_sides:
                # Both price and trigger_price must be the TP price (same value, same format)
                tp_price_formatted = price_fmt  # This is the TP price formatted

                # For TAKE_PROFIT_LIMIT, keep price/trigger_price/ref_price EXACTLY the same string.
                # This avoids mismatches that can lead to API rejections and ensures Trigger Condition displays the TP price.
                params_base = {
                    "instrument_name": symbol,
                    "type": "TAKE_PROFIT_LIMIT",
                    "price": tp_price_formatted,  # TP price (sale price)
                    "quantity": qty_str,
                    "trigger_price": tp_price_formatted,  # TP price (trigger price) - MUST equal price
                }
                
                # Ensure trigger_price and price are EXACTLY the same string
                params_base["trigger_price"] = params_base["price"]  # Force exact equality
                
                # Add ref_price (REQUIRED) - must match TP price exactly
                params_base["ref_price"] = params_base["price"]

                # Build trigger_condition variations (some endpoints are strict about spacing)
                trigger_condition_variations = [
                    f">= {tp_price_formatted}",
                    f">={tp_price_formatted}",
                ]
                
                # Add leverage if margin trading
                if is_margin and leverage:
                    params_base["leverage"] = str(int(leverage))
                
                # CRITICAL: side field is REQUIRED for TAKE_PROFIT_LIMIT orders
                # Crypto.com rejects orders without side field (error 40004: Missing or invalid argument)
                if side_fmt is None:
                    logger.error(f"❌ TAKE_PROFIT_LIMIT: side_fmt is None, cannot create order")
                    last_error = "side parameter is required but was None"
                    continue
                
                params_base["side"] = side_fmt
                
                # Try different combinations of optional parameters
                # Based on successful orders in history, try these variations:
                # IMPORTANT: Always include side field - Crypto.com requires it
                params_variations_list = []
                
                # Variation set: WITH side field (required)
                params_with_side = params_base.copy()
                # CRITICAL: Always include client_oid to avoid DUPLICATE_CLORDID errors
                # Crypto.com uses id: 1 as client_oid when client_oid is missing, causing duplicates
                params_variations_list.extend([
                    # Variation 1: Minimal params with side AND client_oid (required to avoid DUPLICATE_CLORDID)
                    {**params_with_side, "client_oid": str(uuid.uuid4())},
                    # Variation 2: With client_oid and time_in_force
                    {**params_with_side, "client_oid": str(uuid.uuid4()), "time_in_force": "GOOD_TILL_CANCEL"},
                    # Variation 3: With time_in_force only (fallback, but should include client_oid)
                    {**params_with_side, "client_oid": str(uuid.uuid4()), "time_in_force": "GOOD_TILL_CANCEL"},
                ])
            
                # Try each params variation x trigger_condition variation
                for params_idx, params_base_variant in enumerate(params_variations_list, 1):
                    for tc_idx, trigger_condition in enumerate(trigger_condition_variations, 1):
                        params = params_base_variant.copy()
                        params["trigger_condition"] = trigger_condition

                        # Determine if this variation includes side field
                        has_side_field = "side" in params
                        side_in_params = params.get("side", "NONE")
                        side_label = f"side{side_in_params}" if has_side_field else "no-side"
                        variation_name_full = f"{variation_name}-{side_label}-params{params_idx}-tc{tc_idx}"
                        
                        trigger_price_val = params.get("trigger_price", "N/A")
                        ref_price_val_str = params.get("ref_price", "N/A")
                        trigger_condition_val = params.get("trigger_condition", "N/A")
                        
                        # Generate unique request ID for tracking
                        import uuid as uuid_module
                        request_id = str(uuid_module.uuid4())
                        
                        logger.info(f"🔄 Trying TAKE_PROFIT_LIMIT variation {variation_name_full}: price='{price_fmt}', trigger_price='{trigger_price_val}', ref_price='{ref_price_val_str}', trigger_condition='{trigger_condition_val}', quantity='{qty_str}', side='{side_fmt}'")
                        logger.info(f"   📦 FULL PAYLOAD: {params}")
                        logger.debug(f"   Full params: {params}")
                    
                        # Use proxy if enabled (same as successful orders)
                        if self.use_proxy:
                            logger.info(f"[TP_ORDER][{source.upper()}][{request_id}] Using PROXY to place take profit order")
                            try:
                                result = self._call_proxy(method, params)
                                if not isinstance(result, dict):
                                    logger.warning(f"Unexpected proxy response type: {type(result)}")
                                    last_error = "Unexpected proxy response type"
                                    continue

                                code = result.get("code", 0)
                                if code != 0:
                                    msg = result.get("message", "Unknown error")
                                    last_error = f"Error {code}: {msg}"
                                    # If proxy returns an auth/IP error, try the existing TRADE_BOT failover path.
                                    if code in [40101, 40103]:
                                        logger.warning(
                                            f"⚠️ Proxy TP order auth failure (code={code}). Attempting failover to TRADE_BOT."
                                        )
                                        if _should_failover(401):
                                            order_data = {
                                                "symbol": symbol,
                                                "side": side_fmt.upper(),
                                                "type": "TAKE_PROFIT_LIMIT",
                                                "qty": qty,
                                                "price": price,
                                                "trigger_price": trigger_price if trigger_price else price,
                                            }
                                            if entry_price:
                                                order_data["entry_price"] = entry_price
                                            if is_margin and leverage:
                                                order_data["is_margin"] = True
                                                order_data["leverage"] = int(leverage)
                                            try:
                                                fr = self._fallback_place_order(order_data)
                                                if fr.status_code == 200:
                                                    data = fr.json()
                                                    result_data = data.get("result", data)
                                                    order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                                    if order_id:
                                                        logger.info(
                                                            f"✅ Successfully created TP order via TRADE_BOT fallback: order_id={order_id}"
                                                        )
                                                        return {"order_id": str(order_id), "error": None}
                                            except Exception as fallback_err:
                                                logger.error(
                                                    f"TRADE_BOT fallback failed for TP order: {fallback_err}",
                                                    exc_info=True,
                                                )
                                    logger.warning(f"⚠️ Proxy TP order failed: {last_error}")
                                    continue

                                order_result = result.get("result") or {}
                                order_id = order_result.get("order_id") or order_result.get("client_order_id")
                                if order_id:
                                    logger.info(f"✅ Successfully created TP order via PROXY: order_id={order_id}")
                                    return {"order_id": str(order_id), "error": None}

                                logger.warning(f"Proxy TP order success but missing order_id: {result}")
                                last_error = "Proxy success missing order_id"
                                continue
                            except requests.exceptions.RequestException as proxy_err:
                                logger.warning(f"Proxy error: {proxy_err} - falling back to direct API call")
                                # Fall through to direct API call below
                            except Exception as proxy_err:
                                logger.warning(f"Proxy error: {proxy_err} - falling back to direct API call")
                                # Fall through to direct API call below
                        
                        # Direct API call (when proxy is disabled or proxy failed)
                        # DEBUG: Log before sign_request
                        logger.info(f"[DEBUG][{source.upper()}][{request_id}] About to call sign_request for variation {variation_name_full}")
                        
                        payload = self.sign_request(method, params)
                        
                        # DEBUG: Log after sign_request
                        logger.info(f"[DEBUG][{source.upper()}][{request_id}] sign_request completed, payload keys: {list(payload.keys())}")
                        
                        # Log HTTP request details with source and request_id
                        url = f"{self.base_url}/{method}"
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}] Sending HTTP request to exchange:")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   URL: {url}")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Method: POST")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Source: {source}")
                        # SECURITY: never log signed payloads (api_key/sig). Log keys only.
                        try:
                            params_keys = sorted(list((payload.get("params") or {}).keys()))
                        except Exception:
                            params_keys = []
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Payload keys: {sorted(list(payload.keys()))}")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Params keys: {params_keys}")
                        
                        try:
                            logger.debug(f"Request URL: {url}")
                            response = http_post(
                                url,
                                json=payload,
                                headers={"Content-Type": "application/json"},
                                timeout=10,
                                calling_module="crypto_com_trade.place_take_profit_order",
                            )
                        except requests.exceptions.RequestException as e:
                            logger.warning(
                                f"⚠️ Variation {variation_name_full} failed with network error: {e}. Trying next variation..."
                            )
                            last_error = str(e)
                            continue  # Try next params variation
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Variation {variation_name_full} failed with error: {e}. Trying next variation..."
                            )
                            last_error = str(e)
                            continue  # Try next params variation
                        
                        # Log HTTP response details
                        try:
                            response_body = response.json()
                        except Exception:
                            response_body = response.text
                        
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}] Received HTTP response from exchange:")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Status Code: {response.status_code}")
                        response_body_str = json.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, dict) else str(response_body)
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Response Body: {response_body_str}")
                        
                        if response.status_code == 401:
                            error_data = response.json()
                            error_code = error_data.get("code", 0)
                            error_msg = error_data.get("message", "")
                            logger.error(f"Authentication failed: {error_code} - {error_msg}")
                            
                            # Try fallback to TRADE_BOT (same as successful orders)
                            if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                                logger.warning("Authentication failure for take profit order - attempting failover to TRADE_BOT")
                                if _should_failover(401):
                                    # Build order data for TRADE_BOT fallback
                                    order_data = {
                                        "symbol": symbol,
                                        "side": side_fmt.upper(),
                                        "type": "TAKE_PROFIT_LIMIT",
                                        "qty": qty,
                                        "price": price,
                                        "trigger_price": trigger_price if trigger_price else price
                                    }
                                    if entry_price:
                                        order_data["entry_price"] = entry_price
                                    if is_margin and leverage:
                                        order_data["is_margin"] = True
                                        order_data["leverage"] = int(leverage)
                                    
                                    try:
                                        logger.info(f"Calling TRADE_BOT fallback for TP order: {order_data}")
                                        fr = self._fallback_place_order(order_data)
                                        logger.info(f"TRADE_BOT fallback response status: {fr.status_code}")
                                        if fr.status_code == 200:
                                            data = fr.json()
                                            logger.info(f"TRADE_BOT fallback response: {data}")
                                            result_data = data.get("result", data)
                                            order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                            if order_id:
                                                logger.info(f"✅ Successfully created TP order via TRADE_BOT fallback: order_id={order_id}")
                                                return {"order_id": str(order_id), "error": None}
                                            else:
                                                logger.warning(f"TRADE_BOT fallback succeeded but no order_id in response: {result_data}")
                                        else:
                                            logger.warning(f"TRADE_BOT fallback failed with status {fr.status_code}: {fr.text[:200]}")
                                    except Exception as fallback_err:
                                        logger.error(f"TRADE_BOT fallback failed: {fallback_err}", exc_info=True)
                                else:
                                    logger.warning(f"Failover not enabled or TRADEBOT_BASE not configured. FAILOVER_ENABLED={FAILOVER_ENABLED}, TRADEBOT_BASE={TRADEBOT_BASE}")
                            
                            return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
                        
                        # Check for error responses (400, etc.) before raise_for_status
                        if response.status_code != 200:
                            try:
                                error_data = response.json()
                                error_code = error_data.get('code', 0)
                                error_msg = error_data.get('message', 'Unknown error')
                                last_error = f"Error {error_code}: {error_msg}"
                                
                                # If conditional orders are disabled for this account/symbol, no point trying other variations.
                                if error_code == 140001:
                                    logger.error(
                                        f"❌ TAKE_PROFIT_LIMIT rejected with code 140001 (API_DISABLED): {error_msg}. "
                                        f"This account likely cannot place conditional orders (TP/SL) via API."
                                    )
                                    try:
                                        # Do NOT mark trigger orders unavailable here. A failure-only fallback may still
                                        # succeed via the migrated batch endpoint (`private/create-order-list`).
                                        self._send_conditional_orders_api_disabled_alert(code=140001, message=str(error_msg or "API_DISABLED"))
                                    except Exception:
                                        pass
                                    return {"error": f"Error {error_code}: {error_msg} (API_DISABLED)"}
                                
                                # If error 308 (Invalid price format), try next variation
                                if error_code == 308:
                                    logger.warning(f"⚠️ Variation {variation_name_full} failed with error 308 (Invalid price format): price='{price_fmt}', trigger='{price_fmt}'. Trying next variation...")
                                    continue  # Try next params variation
                                
                                # If error 40004 (Missing or invalid argument), try next variation
                                if error_code == 40004:
                                    logger.warning(f"⚠️ Variation {variation_name_full} failed with error 40004 (Missing or invalid argument): {error_msg}. Trying next variation...")
                                    last_error = f"Error {error_code}: {error_msg}"
                                    continue  # Try next params variation
                                
                                # If error 220 (INVALID_SIDE), try next side variation
                                if error_code == 220:
                                    logger.warning(f"⚠️ Variation {variation_name_full} failed with error 220 (INVALID_SIDE): side='{side_fmt}'. Trying next side variation...")
                                    last_error = f"Error {error_code}: {error_msg}"
                                    continue  # Try next params variation (will try next side_fmt in outer loop)
                                
                                # IMPORTANT: Handle error 204 (DUPLICATE_CLORDID) specially
                                # Error 204 means the order already exists or was rejected
                                # We should NOT treat it as success - instead, fail and let the duplicate check
                                # in _create_sl_tp_for_filled_order handle it
                                if error_code == 204:
                                    logger.warning(f"⚠️ Variation {variation_name_full} failed with error 204 (DUPLICATE_CLORDID): {error_msg}")
                                    logger.warning(f"   This usually means a duplicate order exists or the order was rejected.")
                                    logger.warning(f"   Skipping this variation - duplicate check should prevent this from happening.")
                                    last_error = f"Error {error_code}: {error_msg} (DUPLICATE_CLORDID - order may be rejected or duplicate)"
                                    continue  # Try next params variation (but likely all will fail with same error)
                                
                                # For other errors, try next variation (don't return immediately, try all combinations)
                                logger.warning(f"⚠️ Variation {variation_name_full} failed with error {error_code}: {error_msg}. Trying next variation...")
                                last_error = f"Error {error_code}: {error_msg}"
                                continue  # Try next params variation
                                
                            except Exception as parse_err:
                                logger.error(f"Error parsing error response: {parse_err}, response text: {response.text[:200]}")
                                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                                continue  # Try next params variation
                        
                        # Success!
                        response.raise_for_status()
                        result = response.json()

                        # Crypto.com may return HTTP 200 with auth failure in the JSON body.
                        if isinstance(result, dict) and result.get("code") in [40101, 40103]:
                            error_code = result.get("code", 0)
                            error_msg = result.get("message", "Authentication failure")
                            logger.error(f"Authentication failed: {error_code} - {error_msg}")
                            if _should_failover(401):
                                order_data = {
                                    "symbol": symbol,
                                    "side": side_fmt.upper(),
                                    "type": "TAKE_PROFIT_LIMIT",
                                    "qty": qty,
                                    "price": price,
                                    "trigger_price": trigger_price if trigger_price else price,
                                }
                                if entry_price:
                                    order_data["entry_price"] = entry_price
                                if is_margin and leverage:
                                    order_data["is_margin"] = True
                                    order_data["leverage"] = int(leverage)
                                try:
                                    fr = self._fallback_place_order(order_data)
                                    if fr.status_code == 200:
                                        data = fr.json()
                                        result_data = data.get("result", data)
                                        order_id = result_data.get("order_id") or result_data.get("client_order_id")
                                        if order_id:
                                            logger.info(
                                                f"✅ Successfully created TP order via TRADE_BOT fallback: order_id={order_id}"
                                            )
                                            return {"order_id": str(order_id), "error": None}
                                except Exception as fallback_err:
                                    logger.error(
                                        f"TRADE_BOT fallback failed for TP order: {fallback_err}",
                                        exc_info=True,
                                    )
                            return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
                        
                        order_result = result.get("result", {})
                        order_id = order_result.get("order_id") or order_result.get("id")
                        
                        if order_id:
                            logger.info(f"✅ ✅ ✅ SUCCESS! TAKE_PROFIT_LIMIT order created with variation {variation_name_full}")
                            logger.info(f"   Order ID: {order_id}")
                            logger.info(f"   Symbol: {symbol}, Side: {side_fmt}, Price: {price_fmt}, Trigger: {price_fmt}, Ref Price: {ref_price_val_str}")
                            logger.info(f"   Quantity: {qty_str}")
                            logger.debug(f"Full response: {result}")
                            return order_result
                        else:
                            logger.warning(f"⚠️ Response missing order_id, trying next variation...")
                            last_error = "Response missing order_id"
                            continue
                    
        
        # All variations failed
        logger.error(f"❌ All TAKE_PROFIT_LIMIT price/trigger format variations failed. Last error: {last_error}")
        return {"error": f"All format variations failed. Last error: {last_error}"}
    
    def _get_instrument_metadata(self, symbol: str) -> Optional[dict]:
        """
        Get instrument metadata for a symbol from Crypto.com Exchange API.
        Caches results in-memory for the run to avoid repeated API calls.
        
        Returns dict with keys:
        - quantity_decimals: int
        - qty_tick_size: str (e.g., "0.1")
        - min_quantity: str (optional)
        - price_decimals: int
        - price_tick_size: str
        Returns None if instrument not found or API call fails.
        """
        symbol_upper = symbol.upper()
        
        # Check cache first
        if symbol_upper in self._instrument_cache:
            return self._instrument_cache[symbol_upper]
        
        try:
            public_url = f"{REST_BASE}/public/get-instruments"
            response = http_get(public_url, timeout=10, calling_module="crypto_com_trade._get_instrument_metadata")
            response.raise_for_status()
            result = response.json()
            
            if "result" in result:
                # Crypto.com API v1 uses "data" field (not "instruments")
                instruments = result["result"].get("data", result["result"].get("instruments", []))
                for inst in instruments:
                    # Crypto.com API uses "symbol" field
                    inst_name = inst.get("symbol", "") or inst.get("instrument_name", "")
                    if inst_name.upper() == symbol_upper:
                        # Extract and preserve as strings (NO float conversion - per Rule 1)
                        qty_tick_size_raw = inst.get("qty_tick_size")
                        min_quantity_raw = inst.get("min_quantity")
                        price_tick_size_raw = inst.get("price_tick_size")
                        
                        # VALIDATION: Ensure qty_tick_size exists and is valid
                        if not qty_tick_size_raw or qty_tick_size_raw == "":
                            logger.error(f"❌ Missing qty_tick_size for {symbol_upper} in instrument data")
                            self._instrument_cache[symbol_upper] = None
                            return None
                        
                        # If min_quantity is missing from the exchange instrument metadata,
                        # do NOT default to "0.001" (too large for BTC-like instruments).
                        # Instead, use qty_tick_size as a conservative minimum.
                        min_qty_fallback = min_quantity_raw
                        try:
                            if min_qty_fallback is None or str(min_qty_fallback).strip() == "":
                                min_qty_fallback = qty_tick_size_raw or "0"
                        except Exception:
                            min_qty_fallback = qty_tick_size_raw or "0"

                        metadata = {
                            "quantity_decimals": inst.get("quantity_decimals", 2),
                            "qty_tick_size": str(qty_tick_size_raw),  # Keep as string (no float conversion)
                            "min_quantity": str(min_qty_fallback),  # Keep as string
                            "price_decimals": inst.get("price_decimals", 2),
                            "price_tick_size": str(price_tick_size_raw) if price_tick_size_raw is not None else "0.0001",  # Keep as string
                        }
                        
                        # Log full raw instrument entry for validation
                        logger.info(f"✅ [INSTRUMENT_METADATA] Fetched for {symbol_upper}:")
                        logger.info(f"   Full raw API entry: {json.dumps(inst, indent=2)}")
                        logger.info(f"   Parsed metadata: qty_tick_size='{metadata['qty_tick_size']}' (type: str), quantity_decimals={metadata['quantity_decimals']}, min_quantity='{metadata['min_quantity']}'")
                        
                        # Cache it
                        self._instrument_cache[symbol_upper] = metadata
                        return metadata
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch instrument metadata for {symbol_upper}: {e}")
        
        # Not found - cache None to avoid repeated failed lookups
        self._instrument_cache[symbol_upper] = None
        return None
    
    def normalize_quantity(self, symbol: str, raw_quantity: float) -> Optional[str]:
        """
        Normalize quantity according to Crypto.com Exchange instrument rules.
        
        REFERENCE: See docs/trading/crypto_com_order_formatting.md for documented decimal/step-size logic.
        This function implements Rule 2 (Quantize to step_size), Rule 3 (Round DOWN), and Rule 4 (String output).
        
        Rules:
        - Round DOWN to the allowed step size (qty_tick_size) - per Rule 3 (all quantities use ROUND_DOWN)
        - Format to exact quantity_decimals decimal places - per Rule 4 (exact decimals, no scientific notation)
        - Ensure quantity >= min_quantity (returns None if below)
        - Returns quantity as string (never float, never scientific notation)
        
        FAIL-SAFE: If instrument rules cannot be loaded, returns None to block order placement.
        This prevents "Invalid quantity format (code: 213)" errors when rules are unavailable.
        
        Args:
            symbol: Trading pair symbol (e.g., "NEAR_USDT")
            raw_quantity: Raw quantity value (float)
        
        Returns:
            Normalized quantity as string, or None if:
            - Below min_quantity after normalization
            - Instrument rules unavailable (fail-safe behavior)
        """
        import decimal
        
        # Get instrument metadata (FAIL-SAFE: must succeed, no fallbacks)
        inst_meta = self._get_instrument_metadata(symbol)
        
        if not inst_meta:
            # FAIL-SAFE: Instrument rules unavailable - block order to prevent code 213
            logger.error(f"❌ Instrument rules unavailable for {symbol} - blocking order to prevent 'Invalid quantity format (code: 213)'")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ Order blocked for {symbol}: Instrument rules unavailable; order blocked to prevent code 213.")
            except Exception:
                pass  # Non-blocking
            return None
        
        quantity_decimals = inst_meta["quantity_decimals"]
        qty_tick_size_str = inst_meta["qty_tick_size"]
        # If min_quantity is missing, fall back to step_size (or "0") rather than a hard-coded "0.001".
        min_quantity_str = inst_meta.get("min_quantity") or qty_tick_size_str or "0"
        
        # VALIDATION: Ensure step_size is valid (not missing or zero)
        if not qty_tick_size_str or qty_tick_size_str == "0" or qty_tick_size_str == "":
            logger.error(f"❌ Invalid qty_tick_size for {symbol}: '{qty_tick_size_str}' - blocking order")
            try:
                from app.services.telegram_notifier import telegram_notifier
                telegram_notifier.send_message(f"⚠️ Order blocked for {symbol}: Invalid qty_tick_size ({qty_tick_size_str}); order blocked to prevent code 213.")
            except Exception:
                pass
            return None
        
        # Convert to Decimal for precise arithmetic (NO float conversion)
        qty_decimal = decimal.Decimal(str(raw_quantity))
        tick_decimal = decimal.Decimal(str(qty_tick_size_str))  # Keep as string → Decimal (no float)
        min_qty_decimal = decimal.Decimal(str(min_quantity_str))
        
        # Log detailed normalization math for validation
        logger.debug(f"[NORMALIZE_QUANTITY] {symbol}: raw_qty={raw_quantity}, step_size={qty_tick_size_str} (type: {type(qty_tick_size_str).__name__}), quantity_decimals={quantity_decimals}")
        logger.debug(f"[NORMALIZE_QUANTITY] {symbol}: qty_decimal={qty_decimal}, tick_decimal={tick_decimal}, min_qty_decimal={min_qty_decimal}")
        
        # Round DOWN to nearest tick size (per Rule 2 and Rule 3 from docs/trading/crypto_com_order_formatting.md)
        # Formula: floor(qty / tick_size) * tick_size
        division_result = qty_decimal / tick_decimal
        floored_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_FLOOR)
        qty_normalized = floored_result * tick_decimal
        
        logger.debug(f"[NORMALIZE_QUANTITY] {symbol}: raw_qty/step_size={division_result}, floored={floored_result}, normalized={qty_normalized}")
        
        # WARNING: Check for suspiciously large step_size (e.g., >= 0.1 for assets that usually allow more precision)
        tick_decimal_val = float(qty_tick_size_str)  # Only for comparison, not for calculation
        if tick_decimal_val >= 0.1:
            logger.warning(f"⚠️ [NORMALIZE_QUANTITY] {symbol} has large step_size={qty_tick_size_str} (quantity_decimals={quantity_decimals}) - this may limit precision")
        
        # Check minimum quantity
        if qty_normalized < min_qty_decimal:
            logger.warning(
                f"⚠️ Normalized quantity {qty_normalized} for {symbol} is below min_quantity {min_qty_decimal}. "
                f"Raw quantity was {raw_quantity}"
            )
            return None
        
        # Format to exact decimal places required by exchange
        # Use format() to avoid scientific notation
        qty_str = format(qty_normalized, f'.{quantity_decimals}f')
        
        return qty_str
    
    def normalize_price(
        self,
        symbol: str,
        price: float,
        side: str,
        order_type: str = "LIMIT"
    ) -> Optional[str]:
        """
        Normalize price according to docs/trading/crypto_com_order_formatting.md
        
        Rules:
        - BUY LIMIT: ROUND_DOWN (never exceed intended buy price)
        - SELL LIMIT: ROUND_UP (never undershoot intended sell price)
        - TAKE PROFIT: ROUND_UP (ensure profit target is met)
        - STOP LOSS trigger: ROUND_DOWN (conservative trigger)
        - Always preserve trailing zeros
        - Fetch instrument metadata
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC_USDT")
            price: Raw price value (float)
            side: Order side ("BUY" or "SELL")
            order_type: Order type ("LIMIT", "TAKE_PROFIT", "STOP_LOSS")
        
        Returns:
            Normalized price as string, or None if instrument metadata unavailable
        """
        import decimal
        
        # Get instrument metadata
        inst_meta = self._get_instrument_metadata(symbol)
        if not inst_meta:
            logger.error(f"❌ Instrument metadata unavailable for {symbol} - cannot normalize price")
            return None
        
        price_decimals = inst_meta.get("price_decimals", 2)
        price_tick_size_str = inst_meta.get("price_tick_size", "0.01")
        
        # Guardrail: ensure we format with enough decimals for the tick size.
        # Some instruments have inconsistent metadata (e.g. tick_size=0.0001 but price_decimals=2).
        tick_decimals = 0
        if isinstance(price_tick_size_str, str) and "." in price_tick_size_str:
            frac = price_tick_size_str.split(".", 1)[1]
            # Keep significant decimal places implied by tick size (strip trailing zeros).
            tick_decimals = len(frac.rstrip("0"))
        effective_decimals = max(int(price_decimals or 0), int(tick_decimals or 0))
        
        # Convert to Decimal for precise arithmetic
        price_decimal = decimal.Decimal(str(price))
        tick_decimal = decimal.Decimal(str(price_tick_size_str))
        
        # Determine rounding direction based on order type and side (per Rule 3)
        if order_type == "STOP_LOSS":
            # STOP LOSS triggers: ROUND_DOWN (conservative)
            rounding = decimal.ROUND_DOWN
        elif order_type == "TAKE_PROFIT":
            # TAKE PROFIT: ROUND_UP (ensure profit target is met)
            rounding = decimal.ROUND_UP
        elif side.upper() == "BUY":
            # BUY LIMIT: ROUND_DOWN (never exceed intended buy price)
            rounding = decimal.ROUND_DOWN
        else:  # SELL
            # SELL LIMIT: ROUND_UP (never undershoot intended sell price)
            rounding = decimal.ROUND_UP
        
        # Quantize to tick size (per Rule 2)
        division_result = price_decimal / tick_decimal
        quantized_result = division_result.quantize(decimal.Decimal('1'), rounding=rounding)
        price_normalized = quantized_result * tick_decimal
        
        # Format to exact decimal places (per Rule 4: preserve trailing zeros).
        # Use effective_decimals to satisfy tick size formatting requirements.
        price_str = format(price_normalized, f'.{effective_decimals}f')
        
        logger.debug(
            f"[NORMALIZE_PRICE] {symbol} {side} {order_type}: "
            f"raw={price} -> {price_str} (decimals={price_decimals}, tick={price_tick_size_str}, effective_decimals={effective_decimals}, rounding={rounding})"
        )
        
        return price_str
    
    def normalize_quantity_safe_with_fallback(
        self, 
        symbol: str, 
        raw_quantity: float,
        for_sl_tp: bool = True
    ) -> tuple[Optional[str], dict]:
        """
        Safe quantity normalization with multiple fallback strategies.
        
        CRITICAL: For SL/TP creation, positions must NEVER be left unprotected.
        This function tries multiple strategies before giving up.
        
        Strategies (in order):
        1. Standard normalization (respects minQty)
        2. Aggressive rounding (rounds down even if below minQty - may fail at exchange but worth trying)
        3. Use min_quantity as last resort (only for SL/TP protection)
        
        Args:
            symbol: Trading pair symbol
            raw_quantity: Raw quantity value
            for_sl_tp: If True, enables aggressive fallbacks for protection orders
            
        Returns:
            Tuple of (normalized_quantity_str, diagnostics_dict)
            - normalized_quantity_str: Normalized quantity string, or None if all strategies failed
            - diagnostics_dict: Contains all instrument rules, normalization attempts, and reasons
        """
        import decimal
        
        diagnostics = {
            "symbol": symbol,
            "raw_quantity": raw_quantity,
            "strategies_tried": [],
            "instrument_metadata": None,
            "final_result": None,
            "final_reason": None,
        }
        
        # Get instrument metadata
        inst_meta = self._get_instrument_metadata(symbol)
        diagnostics["instrument_metadata"] = inst_meta
        
        if not inst_meta:
            diagnostics["final_reason"] = "instrument_rules_unavailable"
            logger.error(
                f"❌ [NORMALIZE_SAFE] {symbol}: Instrument rules unavailable. "
                f"raw_qty={raw_quantity}, for_sl_tp={for_sl_tp}"
            )
            return None, diagnostics
        
        quantity_decimals = inst_meta["quantity_decimals"]
        qty_tick_size_str = inst_meta["qty_tick_size"]
        # If min_quantity is missing, fall back to step_size (or "0") rather than a hard-coded "0.001".
        min_quantity_str = inst_meta.get("min_quantity") or qty_tick_size_str or "0"
        
        diagnostics["min_quantity"] = min_quantity_str
        diagnostics["step_size"] = qty_tick_size_str
        diagnostics["quantity_decimals"] = quantity_decimals
        
        # Validate step_size
        if not qty_tick_size_str or qty_tick_size_str == "0" or qty_tick_size_str == "":
            diagnostics["final_reason"] = "invalid_step_size"
            logger.error(
                f"❌ [NORMALIZE_SAFE] {symbol}: Invalid step_size '{qty_tick_size_str}'. "
                f"raw_qty={raw_quantity}"
            )
            return None, diagnostics
        
        qty_decimal = decimal.Decimal(str(raw_quantity))
        tick_decimal = decimal.Decimal(str(qty_tick_size_str))
        min_qty_decimal = decimal.Decimal(str(min_quantity_str))
        
        # Strategy 1: Standard normalization (respects minQty)
        diagnostics["strategies_tried"].append("standard")
        division_result = qty_decimal / tick_decimal
        floored_result = division_result.quantize(decimal.Decimal('1'), rounding=decimal.ROUND_FLOOR)
        qty_normalized = floored_result * tick_decimal
        
        if qty_normalized >= min_qty_decimal:
            # Success with standard normalization
            qty_str = format(qty_normalized, f'.{quantity_decimals}f')
            diagnostics["final_result"] = qty_str
            diagnostics["final_reason"] = "standard_success"
            logger.info(
                f"✅ [NORMALIZE_SAFE] {symbol}: Standard normalization succeeded. "
                f"raw={raw_quantity} -> normalized={qty_str}"
            )
            return qty_str, diagnostics
        
        # Strategy 1 failed (below minQty)
        diagnostics["strategies_tried"].append("standard_failed_below_minqty")
        logger.warning(
            f"⚠️ [NORMALIZE_SAFE] {symbol}: Standard normalization failed (below minQty). "
            f"raw={raw_quantity}, normalized={qty_normalized}, minQty={min_qty_decimal}"
        )
        
        # Strategy 2: Aggressive rounding (use rounded value even if below minQty)
        # This may fail at exchange, but worth trying for protection orders
        if for_sl_tp and qty_normalized > 0:
            diagnostics["strategies_tried"].append("aggressive_rounding")
            qty_str_aggressive = format(qty_normalized, f'.{quantity_decimals}f')
            diagnostics["final_result"] = qty_str_aggressive
            diagnostics["final_reason"] = "aggressive_rounding_warning_below_minqty"
            logger.warning(
                f"⚠️ [NORMALIZE_SAFE] {symbol}: Using aggressive rounding (below minQty). "
                f"raw={raw_quantity} -> normalized={qty_str_aggressive} (minQty={min_qty_decimal}). "
                f"Exchange may reject, but attempting for protection."
            )
            return qty_str_aggressive, diagnostics
        
        # Strategy 3: Use min_quantity as absolute last resort (only for SL/TP)
        if for_sl_tp:
            diagnostics["strategies_tried"].append("min_quantity_fallback")
            min_qty_str = format(min_qty_decimal, f'.{quantity_decimals}f')
            diagnostics["final_result"] = min_qty_str
            diagnostics["final_reason"] = "min_quantity_fallback_warning_larger_than_executed"
            logger.warning(
                f"⚠️ [NORMALIZE_SAFE] {symbol}: Using min_quantity as fallback. "
                f"raw={raw_quantity} -> minQty={min_qty_str}. "
                f"WARNING: This is LARGER than executed quantity - protection may over-close position."
            )
            return min_qty_str, diagnostics
        
        # All strategies failed
        diagnostics["final_reason"] = "all_strategies_failed"
        logger.error(
            f"❌ [NORMALIZE_SAFE] {symbol}: All normalization strategies failed. "
            f"raw={raw_quantity}, minQty={min_qty_decimal}, for_sl_tp={for_sl_tp}"
        )
        return None, diagnostics
    
    def get_instruments(self) -> list:
        """Get list of available trading instruments (public endpoint)"""
        # Use public API endpoint for instruments (v1)
        public_url = f"{REST_BASE}/public/get-instruments"
        
        try:
            response = http_get(public_url, timeout=10, calling_module="crypto_com_trade.get_instruments")
            response.raise_for_status()
            result = response.json()
            
            if "result" in result and "instruments" in result["result"]:
                instruments = result["result"]["instruments"]
                # Extract just the symbol names
                symbols = [inst.get("instrument_name", "") for inst in instruments if inst.get("instrument_name")]
                logger.info(f"Retrieved {len(symbols)} instruments")
                return symbols
            else:
                logger.error(f"Unexpected response format: {result}")
                return []
                
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting instruments: {e}")
            # Return common symbols as fallback
            return ["BTC_USDT", "ETH_USDT", "BNB_USDT", "SOL_USDT", "ADA_USDT", "DOGE_USDT", "XRP_USDT", "MATIC_USDT"]
        except Exception as e:
            logger.error(f"Error getting instruments: {e}")
            return ["BTC_USDT", "ETH_USDT", "BNB_USDT", "SOL_USDT", "ADA_USDT", "DOGE_USDT", "XRP_USDT", "MATIC_USDT"]


# Singleton instance
trade_client = CryptoComTradeClient()
