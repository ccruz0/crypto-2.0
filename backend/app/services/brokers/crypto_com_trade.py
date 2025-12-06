import os
import time
import hmac
import hashlib
import json
import logging
import requests
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from .crypto_com_constants import REST_BASE, CONTENT_TYPE_JSON
from app.core.failover_config import (
    CRYPTO_REST_BASE, CRYPTO_TIMEOUT, CRYPTO_RETRIES,
    TRADEBOT_BASE, FAILOVER_ENABLED
)
from app.services.open_orders import UnifiedOpenOrder, _format_timestamp

logger = logging.getLogger(__name__)

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
        self.use_proxy = os.getenv("USE_CRYPTO_PROXY", "true").lower() == "true"
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
        
        self.api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
        self.api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
        self.live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        
        # [CRYPTO_AUTH_DIAG] Enhanced credential logging
        logger.info(f"[CRYPTO_AUTH_DIAG] === CREDENTIALS LOADED ===")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY repr: {repr(self.api_key)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY length: {len(self.api_key)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] API_KEY preview: {self.api_key[:4]}....{self.api_key[-4:] if len(self.api_key) >= 4 else ''}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY length: {len(self.api_secret)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY starts with: {self.api_secret[:6] if len(self.api_secret) >= 6 else 'N/A'}")
        logger.info(f"[CRYPTO_AUTH_DIAG] SECRET_KEY has whitespace: {any(c.isspace() for c in self.api_secret) if self.api_secret else False}")
        logger.info(f"[CRYPTO_AUTH_DIAG] =========================")
        
        logger.info(f"CryptoComTradeClient initialized - Live Trading: {self.live_trading}")
        if self.use_proxy:
            logger.info(f"Using PROXY: {self.proxy_url}")
        else:
            logger.info(f"Using base URL: {self.base_url}")
    
    def _call_proxy(self, method: str, params: dict) -> dict:
        """Call Crypto.com API through the proxy"""
        try:
            response = requests.post(
                f"{self.proxy_url}/proxy/private",
                json={"method": method, "params": params},
                headers={"X-Proxy-Token": self.proxy_token},
                timeout=15
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
        return requests.get(url, timeout=CRYPTO_TIMEOUT)
    
    def _fallback_open_orders(self):
        """Fallback to TRADE_BOT for open orders"""
        url = f"{TRADEBOT_BASE}/api/orders/open"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return requests.get(url, timeout=CRYPTO_TIMEOUT)
    
    def _fallback_history(self):
        """Fallback to TRADE_BOT for order history"""
        url = f"{TRADEBOT_BASE}/api/orders/history"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return requests.get(url, timeout=CRYPTO_TIMEOUT)
    
    def _fallback_place_order(self, data):
        """Fallback to TRADE_BOT for placing orders"""
        url = f"{TRADEBOT_BASE}/api/orders/place"
        logger.info(f"Failover to TRADE_BOT: {url}")
        return requests.post(url, json=data, timeout=CRYPTO_TIMEOUT)
    
    def _fallback_cancel_order(self, order_id):
        """Fallback to TRADE_BOT for canceling orders"""
        url = f"{TRADEBOT_BASE}/api/orders/cancel"
        logger.info(f"Failover to TRADE_BOT: {url}")
        params = {"order_id": order_id}
        return requests.post(url, json=params, timeout=CRYPTO_TIMEOUT)
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
    
    def sign_request(self, method: str, params: dict) -> dict:
        """
        Generate signed JSON-RPC 2.0 request for Crypto.com Exchange v1
        Following official docs: method + id + api_key + params_string + nonce
        For empty params: use empty string (verified to work)
        For non-empty params: use _params_to_str method (custom format as per Crypto.com docs)
        """
        nonce_ms = int(time.time() * 1000)
        
        # Build params string for signature
        # IMPORTANT: If params is empty {}, use empty string in signature (not '{}')
        # For non-empty params, use _params_to_str (verified: 401 with json.dumps, 400 with _params_to_str)
        # This means authentication works with _params_to_str, but request body may need adjustment
        if params:
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
        request_id = 1  # Use 1 as per documentation and working methods
        payload = {
            "id": request_id,  # Use 1 as per documentation sample
            "method": method,
            "api_key": self.api_key,
            "params": params,  # Always include params, even if empty {}
            "nonce": nonce_ms
        }
        
        # String to sign format per Crypto.com Exchange API v1:
        # Format: method + id + api_key + params_str + nonce
        string_to_sign = method + str(request_id) + self.api_key + params_str + str(nonce_ms)
        
        # [CRYPTO_AUTH_DIAG] Complete signing process logging
        current_utc = datetime.now(timezone.utc).isoformat()
        current_time = time.time()
        logger.info(f"[CRYPTO_AUTH_DIAG] === SIGNING PROCESS ===")
        logger.info(f"[CRYPTO_AUTH_DIAG] method={method}")
        logger.info(f"[CRYPTO_AUTH_DIAG] params={json.dumps(params)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] request_id={request_id} (type={type(request_id).__name__})")
        logger.info(f"[CRYPTO_AUTH_DIAG] nonce={nonce_ms} (type={type(nonce_ms).__name__})")
        logger.info(f"[CRYPTO_AUTH_DIAG] server_time_utc={current_utc}")
        logger.info(f"[CRYPTO_AUTH_DIAG] server_time_epoch={current_time}")
        logger.info(f"[CRYPTO_AUTH_DIAG] params_str_len={len(params_str)}, params_str_repr={repr(params_str)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] string_to_sign_length={len(string_to_sign)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] string_to_sign={string_to_sign}")
        
        # Generate HMAC-SHA256 signature
        signature = hmac.new(
            bytes(str(self.api_secret), 'utf-8'),
            msg=bytes(string_to_sign, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        logger.info(f"[CRYPTO_AUTH_DIAG] signature={signature}")
        logger.info(f"[CRYPTO_AUTH_DIAG] payload={json.dumps({k: v if k != 'sig' else signature[:10] + '...' + signature[-10:] for k, v in payload.items()}, indent=2)}")
        logger.info(f"[CRYPTO_AUTH_DIAG] ====================")
        
        payload["sig"] = signature
        
        return payload
    
    def get_account_summary(self) -> dict:
        """Get account summary (balances)"""
        # [CRYPTO_AUTH_DIAG] Log outbound IP before request
        try:
            egress_ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
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
                                    accounts.append({
                                        "currency": currency,
                                        "balance": str(quantity),
                                        "available": str(balance.get("max_withdrawal_balance", quantity))
                                    })
                    
                    logger.info(f"Retrieved {len(accounts)} account balances via proxy")
                    return {"accounts": accounts}
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
        
        method = "private/user-balance"
        params = {}
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method}")
        
        try:
            # Crypto.com Exchange v1 API expects the method as the URL path
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            # Disable SSL verification when using IP directly (certificate is for api.crypto.com)
            verify_ssl = not url.startswith("https://104.")
            headers = {"Content-Type": "application/json"}
            # Add Host header when using IP directly (required for SSL/TLS)
            if url.startswith("https://104."):
                headers["Host"] = "api.crypto.com"
            response = requests.post(url, json=payload, headers=headers, timeout=10, verify=verify_ssl)
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.warning(f"API authentication failed: {error_msg} (code: {error_code})")
                
                # If IP not whitelisted or other auth issues, raise error (NO SIMULATED DATA)
                if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                    logger.error(f"API authentication failed: {error_msg} (code: {error_code})")
                    raise RuntimeError(f"Crypto.com API authentication failed: {error_msg} (code: {error_code}). Check API credentials and IP whitelist.")
            
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"Response: {result}")
            
            # Crypto.com returns data in result.data format with position_balances
            if "result" in result and "data" in result["result"]:
                data = result["result"]["data"]
                accounts = []
                
                # Extract position balances and convert to standard format
                # Crypto.com API provides: instrument_name, quantity, market_value, max_withdrawal_balance
                # and potentially loan/borrowed fields
                def _record_balance_entry(balance, account_type=None):
                            # Log ALL fields to discover loan-related data
                            logger.debug(f"Raw balance data from Crypto.com: {balance}")
                            
                    instrument = balance.get("instrument_name") or balance.get("currency") or ""
                    quantity = balance.get("quantity", balance.get("balance", "0"))
                    market_value = balance.get("market_value", balance.get("usd_value", "0"))
                    max_withdrawal = balance.get("max_withdrawal_balance", balance.get("available", quantity))
                            
                            # Extract loan/borrowed fields if present
                            borrowed_balance = balance.get("borrowed_balance", "0")
                            borrowed_value = balance.get("borrowed_value", "0")
                            loan_amount = balance.get("loan_amount", "0")
                            loan_value = balance.get("loan_value", "0")
                            debt_amount = balance.get("debt_amount", "0")
                            debt_value = balance.get("debt_value", "0")
                            negative_balance = balance.get("negative_balance", "0")
                            
                            # Extract currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                            # Crypto.com may return instrument_name as "BTC_USDT" or just "BTC"
                            currency = instrument
                            if "_" in instrument:
                                # Extract base currency from instrument_name (e.g., "BTC_USDT" -> "BTC")
                                currency = instrument.split("_")[0].upper()
                            else:
                                currency = instrument.upper()
                            
                            # Calculate available and reserved
                            available_qty = float(max_withdrawal) if max_withdrawal else float(quantity)
                            balance_qty = float(quantity)
                            reserved_qty = max(0, balance_qty - available_qty)
                            
                            # Check for negative balances (indicates borrowed/loan)
                            is_negative = balance_qty < 0
                            if is_negative:
                                logger.info(f"🔴 Found negative balance (loan): {currency} = {balance_qty}")
                            
                            # Include ALL available data from Crypto.com
                            account_data = {
                                "currency": currency,
                                "balance": str(balance_qty),
                                "available": str(available_qty),
                                "reserved": str(reserved_qty),
                                "market_value": str(market_value),  # USD value from Crypto.com
                                "max_withdrawal": str(max_withdrawal),
                        "quantity": str(quantity),  # Keep original quantity
                            }
                    if account_type:
                        account_data["account_type"] = account_type
                            
                            # Add loan/borrowed fields if present
                            if borrowed_balance and float(borrowed_balance) != 0:
                                account_data["borrowed_balance"] = str(borrowed_balance)
                                logger.info(f"📊 Found borrowed_balance for {currency}: {borrowed_balance}")
                            if borrowed_value and float(borrowed_value) != 0:
                                account_data["borrowed_value"] = str(borrowed_value)
                                logger.info(f"📊 Found borrowed_value for {currency}: {borrowed_value}")
                            if loan_amount and float(loan_amount) != 0:
                                account_data["loan_amount"] = str(loan_amount)
                                logger.info(f"📊 Found loan_amount for {currency}: {loan_amount}")
                            if loan_value and float(loan_value) != 0:
                                account_data["loan_value"] = str(loan_value)
                                logger.info(f"📊 Found loan_value for {currency}: {loan_value}")
                            if debt_amount and float(debt_amount) != 0:
                                account_data["debt_amount"] = str(debt_amount)
                                logger.info(f"📊 Found debt_amount for {currency}: {debt_amount}")
                            if debt_value and float(debt_value) != 0:
                                account_data["debt_value"] = str(debt_value)
                                logger.info(f"📊 Found debt_value for {currency}: {debt_value}")
                    if is_negative or (negative_balance and float(negative_balance) != 0):
                                account_data["is_negative"] = True
                            
                            accounts.append(account_data)

                for position in data:
                    account_type = position.get("account_type")
                    if "position_balances" in position:
                        for balance in position["position_balances"]:
                            _record_balance_entry(balance, account_type)
                    if "balances" in position:
                        for balance in position["balances"]:
                            _record_balance_entry(balance, account_type)
                
                logger.info(f"Retrieved {len(accounts)} account balances")
                return {"accounts": accounts}
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
        if not self.live_trading:
            logger.info("DRY_RUN: get_open_orders - returning simulated data")
            return {
                "data": [
                    {
                        "order_id": "dry_123456",
                        "client_oid": "dry_123456",
                        "status": "ACTIVE",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "instrument_name": "BTC_USDT",
                        "quantity": "0.001",
                        "limit_price": "50000.00",
                        "order_value": "50.00",
                        "create_time": int(time.time() * 1000),
                        "update_time": int(time.time() * 1000)
                    }
                ]
            }
        
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
            logger.warning("API credentials not configured. Returning simulated data.")
            return {
                "orders": []
            }
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method}")
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.error(f"Authentication failed: {error_code} - {error_msg}")
                return {"orders": []}
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Successfully retrieved open orders")
            logger.debug(f"Response: {result}")
            
            # Crypto.com returns {"result": {"data": [...]}}
            data = result.get("result", {}).get("data", [])
            return {"data": data}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting open orders: {e}")
            return {"orders": []}
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return {"orders": []}

    def get_trigger_orders(self, page: int = 0, page_size: int = 200) -> dict:
        """Get trigger-based (TP/SL) open orders."""
        if not self.live_trading:
            logger.info("DRY_RUN: get_trigger_orders - returning simulated data")
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
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if response.status_code == 401:
                error_data = response.json()
                logger.error(f"Authentication failed for trigger orders: {error_data}")
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
        
        if not self.live_trading:
            logger.info("DRY_RUN: get_order_history - returning simulated data")
            return {
                "data": [
                    {
                        "order_id": "dry_789012",
                        "client_oid": "dry_789012",
                        "status": "FILLED",
                        "side": "BUY",
                        "order_type": "MARKET",
                        "instrument_name": "BTC_USDT",
                        "quantity": "0.001",
                        "limit_price": "50000.00",
                        "price": "50000.00",
                        "avg_price": "50000.00",
                        "order_value": "50.00",
                        "exec_inst": [],
                        "create_time": int(time.time() * 1000) - 3600000,
                        "update_time": int(time.time() * 1000) - 3500000
                    }
                ]
            }
        
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
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not configured. Returning simulated data.")
            return {"data": []}
        
        # Use private/get-order-history endpoint (not advanced - for regular orders)
        # IMPORTANT: Without params, it only returns 1 order. We need date filters to get all orders.
        method = "private/get-order-history"
        
        # Build params - use date range if provided, otherwise get last 30 days
        params = {}
        if start_time is not None or end_time is not None:
            if start_time is not None:
                params['start_time'] = start_time
            if end_time is not None:
                params['end_time'] = end_time
            if page_size:
                params['page_size'] = page_size
            params['page'] = page
        else:
            # Default: Get last 30 days of orders
            from datetime import datetime, timedelta
            end_time_ms = int(time.time() * 1000)
            start_time_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
            params = {
                'start_time': start_time_ms,
                'end_time': end_time_ms,
                'page_size': page_size,
                'page': page
            }
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method} with params: {list(params.keys())}")
        
        try:
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.error(f"Authentication failed: {error_code} - {error_msg}")
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
            # Format quantity - use appropriate precision
            if qty >= 1:
                qty_str = f"{qty:.3f}".rstrip('0').rstrip('.')
            else:
                qty_str = f"{qty:.8f}".rstrip('0').rstrip('.')
            params["quantity"] = qty_str
        
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
            params["exec_inst"] = ["MARGIN_ORDER"]
            
            logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value}, exec_inst=['MARGIN_ORDER']")
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
        logger.debug(f"[MARGIN_REQUEST] full_payload_with_secrets: {json.dumps(payload, indent=2)}")
        
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
                            order_data["qty"] = qty
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
                        order_data["qty"] = qty
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
                logger.info(
                    f"[ENTRY_ORDER][{source}][{request_id}] Sending HTTP request to exchange:\n"
                    f"  URL: {url}\n"
                    f"  Method: POST\n"
                    f"  Payload JSON: {json.dumps(payload, ensure_ascii=False, indent=2)}"
                )
                
                response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                
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
                    logger.error(f"Authentication failed: {error_code} - {error_msg}")
                    return {"error": f"Authentication failed: {error_msg}"}
                
                # Log the response from Crypto.com (before processing)
                try:
                    response_json = response.json()
                    logger.info(f"[MARGIN_RESPONSE] status_code={response.status_code}")
                    logger.info(f"[MARGIN_RESPONSE] payload={json.dumps(response_json, indent=2)}")
                except (ValueError, AttributeError):
                    logger.warning(f"[MARGIN_RESPONSE] status_code={response.status_code} (non-JSON response)")
                    logger.warning(f"[MARGIN_RESPONSE] response_text={response.text[:500]}")
                
                # Check for 500 errors and extract detailed error message
                if response.status_code == 500:
                    try:
                        error_data = response.json()
                        error_code = error_data.get("code", 0)
                        error_msg = error_data.get("message", "")
                        error_details = f"{response.status_code} Server Error: {error_msg or 'Internal Server Error'}"
                        if error_code:
                            error_details += f" (code: {error_code})"
                        
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
                            logger.error(f"❌ API 500 error placing {margin_status} market order for {symbol}: {error_details}")
                        
                        logger.error(f"📊 Order parameters that failed: {json.dumps(params, indent=2)}")
                        logger.error(f"Full error response: {json.dumps(error_data, indent=2)}")
                        return {"error": error_details}
                    except (ValueError, KeyError):
                        # If response is not JSON, use status text
                        error_details = f"{response.status_code} Server Error: {response.reason or 'Internal Server Error'}"
                        logger.error(f"API 500 error placing market order (non-JSON response): {error_details}")
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
        # Format price and quantity to match existing orders format
        # Based on documentation and testing, use sufficient precision
        # For high prices (>= 100): use 2-4 decimal places
        # For medium prices (>= 1): use 4-6 decimal places
        # For small prices (< 1): use 8 decimal places
        # Keep decimal precision but remove unnecessary trailing zeros for readability
        if price >= 100:
            # For ETH/BTC prices: use 2 decimal places minimum (e.g., "3857.76")
            price_str = f"{price:.2f}" if price % 1 == 0 else f"{price:.4f}".rstrip('0').rstrip('.')
        elif price >= 1:
            price_str = f"{price:.4f}".rstrip('0').rstrip('.')
        else:
            price_str = f"{price:.8f}".rstrip('0').rstrip('.')
        
        # For quantity: use sufficient precision
        # Small quantities (< 1) may need 8 decimals for accuracy
        if qty >= 1:
            qty_str = f"{qty:.3f}".rstrip('0').rstrip('.')
        else:
            # For small quantities, use 8 decimals but remove trailing zeros
            qty_str = f"{qty:.8f}".rstrip('0').rstrip('.')
            # Ensure at least 2 significant decimals for very small values
            if '.' in qty_str and len(qty_str.split('.')[1]) < 2:
                qty_str = f"{qty:.8f}"
        
        # Build params according to Crypto.com Exchange API v1 documentation
        # Required params: instrument_name, side, type, price (for LIMIT), quantity
        # Optional: time_in_force, client_oid, exec_inst
        # Add client_oid as shown in documentation example (may help with validation)
        # uuid is now imported at the top of the file
        client_oid = str(uuid.uuid4())
        
        # Build params exactly as per documentation example that works
        # Key finding: side must be 'BUY'/'SELL' in UPPERCASE, not lowercase
        # Also include time_in_force for LIMIT orders (required for proper validation)
        params = {
            "instrument_name": symbol,
            "side": side.upper(),  # Use UPPERCASE as per documentation example (verified to work)
            "type": "LIMIT",
            "price": price_str,  # Formatted to match existing orders
            "quantity": qty_str,  # Formatted to match existing orders
            "client_oid": client_oid,  # Add client_oid as per documentation example
            "time_in_force": "GOOD_TILL_CANCEL"  # Required for LIMIT orders (verified to work)
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
            params["exec_inst"] = ["MARGIN_ORDER"]
            
            logger.info(f"📊 MARGIN ORDER CONFIGURED: leverage={leverage_value}, exec_inst=['MARGIN_ORDER']")
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
        logger.info(f"[MARGIN_REQUEST] params_detail: instrument_name={symbol}, side={side.upper()}, type=LIMIT, price={price_str}, quantity={qty_str}")
        if is_margin:
            logger.info(f"[MARGIN_REQUEST] margin_params: leverage={params.get('leverage')}")
        logger.info(f"Price string: '{price_str}', Quantity string: '{qty_str}'")
        logger.debug(f"[MARGIN_REQUEST] full_payload_with_secrets: {json.dumps(payload, indent=2)}")
        
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
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            
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
            response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            
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
        
        # Get instrument info to determine exact price and quantity precision required
        price_decimals = None
        price_tick_size = None
        quantity_decimals = 2
        qty_tick_size = 0.01
        got_instrument_info = False
        
        try:
            import requests as req
            import decimal as dec
            inst_url = "https://api.crypto.com/exchange/v1/public/get-instruments"
            inst_response = req.get(inst_url, timeout=3)
            if inst_response.status_code == 200:
                inst_data = inst_response.json()
                if "result" in inst_data and "instruments" in inst_data["result"]:
                    for inst in inst_data["result"]["instruments"]:
                        inst_name = inst.get("instrument_name", "") or inst.get("symbol", "")
                        if inst_name.upper() == symbol.upper():
                            price_decimals = inst.get("price_decimals")
                            price_tick_size_str = inst.get("price_tick_size", "0.01")
                            quantity_decimals = inst.get("quantity_decimals", 2)
                            qty_tick_size_str = inst.get("qty_tick_size", "0.01")
                            try:
                                price_tick_size = float(price_tick_size_str) if price_tick_size_str else None
                                qty_tick_size = float(qty_tick_size_str)
                            except:
                                price_tick_size = None
                                qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.01
                            got_instrument_info = True
                            logger.info(f"✅ Got instrument info for {symbol}: price_decimals={price_decimals}, price_tick_size={price_tick_size}, quantity_decimals={quantity_decimals}, qty_tick_size={qty_tick_size}")
                            break
        except Exception as e:
            logger.debug(f"Could not fetch instrument info for {symbol}: {e}. Using default precision.")
        
        # Format price with instrument-specific precision
        import decimal
        price_decimal = decimal.Decimal(str(price))
        
        if price_decimals is not None:
            # Use instrument-specific precision
            if price_tick_size and price_tick_size > 0:
                # Round to nearest tick size
                tick_decimal = decimal.Decimal(str(price_tick_size))
                price_decimal = (price_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
                # Format with exact precision required
                price_str = f"{price_decimal:.{price_decimals}f}"
            else:
                # Round to price_decimals decimal places
                precision = decimal.Decimal('0.1') ** price_decimals
                price_decimal = price_decimal.quantize(precision, rounding=decimal.ROUND_HALF_UP)
                price_str = f"{price_decimal:.{price_decimals}f}"
            logger.info(f"✅ Formatted price for STOP_LIMIT {symbol} with precision {price_decimals}: {price} -> {price_str}")
        else:
            # Fallback: Use default precision based on price range
            if price >= 100:
                price_str = f"{price:.2f}" if price % 1 == 0 else f"{price:.4f}".rstrip('0').rstrip('.')
            elif price >= 1:
                price_str = f"{price:.4f}".rstrip('0').rstrip('.')
            else:
                # For prices < 1, use more decimals but ensure at least 6 decimals for low-price coins
                price_str = f"{price:.6f}".rstrip('0').rstrip('.')
                # If still less than 6 decimals after stripping, pad to 6
                if '.' in price_str:
                    decimal_part = price_str.split('.')[1]
                    if len(decimal_part) < 6:
                        price_str = f"{price:.6f}"
            logger.debug(f"Formatted price for STOP_LIMIT {symbol} with default precision: {price} -> {price_str}")
        
        # Format quantity according to Crypto.com API requirements for STOP_LIMIT
        # Different instruments have different quantity_decimals (e.g., APT_USDT=2, DOGE_USDT=8)
        # Try multiple precision levels automatically
        import decimal
        
        # Common precision levels to try
        # APT_USDT, most USDT pairs: 2 decimals (0.01 tick)
        # DOGE_USDT, low-value coins: 8 decimals (0.00000001 tick)
        # BTC_USDT, high-value coins: 6 decimals (0.000001 tick)
        # Use Decimal for precision to avoid floating point issues
        import decimal as dec
        precision_levels = [
            (2, dec.Decimal('0.01')),      # Most common: 2 decimals
            (8, dec.Decimal('0.00000001')), # Low-value coins like DOGE
            (6, dec.Decimal('0.000001')),   # High-value coins like BTC
            (4, dec.Decimal('0.0001')),     # Medium precision
            (3, dec.Decimal('0.001')),      # Some coins use 3 decimals
            (1, dec.Decimal('0.1')),        # Some coins use 1 decimal
            (0, dec.Decimal('1')),          # Whole numbers only
        ]
        
        # Use quantity_decimals and qty_tick_size already obtained from instrument info above
        
        # Format quantity - will try different precisions in the retry loop
        qty_decimal = decimal.Decimal(str(qty))
        
        # If we got instrument info, use it directly
        if got_instrument_info:
            tick_decimal = decimal.Decimal(str(qty_tick_size))
            qty_decimal = (qty_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
            qty_float = float(qty_decimal)
            qty_str = f"{qty_float:.{quantity_decimals}f}"
            logger.info(f"✅ Formatted quantity for STOP_LIMIT {symbol}: {qty} -> {qty_str} ({quantity_decimals} decimals)")
        else:
            # Default: Try to preserve original precision, but use at least 4 decimals to avoid rounding errors
            # For ETH with 0.0051, we need at least 4 decimals (0.0051), not 2 (which would round to 0.01)
            # Calculate required decimals from the original quantity
            qty_str_original = f"{qty:.10f}".rstrip('0').rstrip('.')
            if '.' in qty_str_original:
                decimals_needed = len(qty_str_original.split('.')[1])
                # Use at least 4 decimals, but preserve original precision if higher
                decimals_to_use = max(4, decimals_needed)
            else:
                decimals_to_use = 4
            
            # Use appropriate tick size based on decimals needed
            tick_size = decimal.Decimal('0.1') ** decimals_to_use
            qty_decimal = (qty_decimal / tick_size).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_size
            qty_float = float(qty_decimal)
            qty_str = f"{qty_float:.{decimals_to_use}f}"
            logger.info(f"✅ Formatted quantity for STOP_LIMIT {symbol}: {qty} -> {qty_str} (preserving precision: {decimals_to_use} decimals, will try others if needed)")
        
        # Format trigger_price with same precision as price
        trigger_decimal = decimal.Decimal(str(trigger_price))
        
        if price_decimals is not None:
            # Use same precision as price
            if price_tick_size and price_tick_size > 0:
                tick_decimal = decimal.Decimal(str(price_tick_size))
                trigger_decimal = (trigger_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
                trigger_str = f"{trigger_decimal:.{price_decimals}f}"
            else:
                precision = decimal.Decimal('0.1') ** price_decimals
                trigger_decimal = trigger_decimal.quantize(precision, rounding=decimal.ROUND_HALF_UP)
                trigger_str = f"{trigger_decimal:.{price_decimals}f}"
            logger.info(f"✅ Formatted trigger_price for STOP_LIMIT {symbol} with precision {price_decimals}: {trigger_price} -> {trigger_str}")
        else:
            # Fallback: Use default precision
            if trigger_price >= 100:
                trigger_str = f"{trigger_price:.2f}" if trigger_price % 1 == 0 else f"{trigger_price:.4f}".rstrip('0').rstrip('.')
            elif trigger_price >= 1:
                trigger_str = f"{trigger_price:.4f}".rstrip('0').rstrip('.')
            else:
                # For prices < 1, use more decimals
                trigger_str = f"{trigger_price:.6f}".rstrip('0').rstrip('.')
                if '.' in trigger_str:
                    decimal_part = trigger_str.split('.')[1]
                    if len(decimal_part) < 6:
                        trigger_str = f"{trigger_price:.6f}"
            logger.debug(f"Formatted trigger_price for STOP_LIMIT {symbol} with default precision: {trigger_price} -> {trigger_str}")
        
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
        # We want Trigger Condition to show SL price (trigger_price), so ref_price must equal trigger_price
        if price_decimals is not None:
            # Use same precision as price and trigger_price
            if price_tick_size and price_tick_size > 0:
                ref_decimal = decimal.Decimal(str(ref_price))
                tick_decimal = decimal.Decimal(str(price_tick_size))
                ref_decimal = (ref_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
                ref_price_str = f"{ref_decimal:.{price_decimals}f}"
            else:
                precision = decimal.Decimal('0.1') ** price_decimals
                ref_decimal = decimal.Decimal(str(ref_price))
                ref_decimal = ref_decimal.quantize(precision, rounding=decimal.ROUND_HALF_UP)
                ref_price_str = f"{ref_decimal:.{price_decimals}f}"
            logger.info(f"✅ Formatted ref_price for STOP_LIMIT {symbol} with precision {price_decimals}: {ref_price} -> {ref_price_str} (should match trigger_str: {trigger_str})")
        else:
            # Fallback: Use same format as trigger_price
            if ref_price >= 100:
                ref_price_str = f"{ref_price:.2f}" if ref_price % 1 == 0 else f"{ref_price:.4f}".rstrip('0').rstrip('.')
            elif ref_price >= 1:
                ref_price_str = f"{ref_price:.4f}".rstrip('0').rstrip('.')
            else:
                ref_price_str = f"{ref_price:.8f}".rstrip('0').rstrip('.')
            logger.info(f"✅ Formatted ref_price for STOP_LIMIT {symbol} with default precision: {ref_price} -> {ref_price_str} (should match trigger_str: {trigger_str})")
        
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
            # Variation 12: Try with GTC instead of GOOD_TILL_CANCEL
            {
                "instrument_name": symbol,
                "side": side_upper,
                "type": "STOP_LIMIT",
                "price": price_str,
                "quantity": qty_str,
                "trigger_price": trigger_str,
                "ref_price": ref_price_str,
                "time_in_force": "GTC"
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
                payload = self.sign_request(method, params)
                
                # Generate unique request ID for tracking
                import uuid as uuid_module
                request_id = str(uuid_module.uuid4())
                
                logger.info(f"Live: place_stop_loss_order - {symbol} {side} {qty} @ {price} trigger={trigger_price}")
                logger.info(f"Params sent: {params}")  # Log params at INFO level for debugging
                logger.info(f"Price string: '{price_str}', Quantity string: '{qty_str}', Trigger string: '{trigger_str}'")
                logger.debug(f"Payload: {payload}")
                
                url = f"{self.base_url}/{method}"
                
                # Log HTTP request details with source and request_id
                import json as json_module
                logger.info(
                    f"[SL_ORDER][{source.upper()}][{request_id}] Sending HTTP request to exchange:\n"
                    f"  URL: {url}\n"
                    f"  Method: POST\n"
                    f"  Source: {source}\n"
                    f"  Payload JSON: {json_module.dumps(payload, ensure_ascii=False, indent=2)}"
                )
                
                logger.debug(f"Request URL: {url}")
                response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                
                # Log HTTP response details
                try:
                    response_body = response.json()
                except:
                    response_body = response.text
                
                logger.info(
                    f"[SL_ORDER][{source.upper()}][{request_id}] Received HTTP response from exchange:\n"
                    f"  Status Code: {response.status_code}\n"
                    f"  Response Body: {json_module.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, dict) else response_body}"
                )
                
                if response.status_code == 401:
                    error_data = response.json()
                    error_code = error_data.get("code", 0)
                    error_msg = error_data.get("message", "")
                    logger.error(f"Authentication failed: {error_code} - {error_msg}")
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
                            
                            # Try ALL different precision levels automatically
                            # This works even if we got instrument info (it might be wrong or insufficient)
                            precision_tried_this_variation = False
                            for prec_decimals, prec_tick in precision_levels:
                                # Skip the precision we already tried for this variation
                                if got_instrument_info and prec_decimals == quantity_decimals and not precision_tried_this_variation:
                                    precision_tried_this_variation = True
                                    continue  # Already tried this precision
                                
                                logger.info(f"🔄 Trying variation {variation_idx} with precision {prec_decimals} decimals (tick_size={prec_tick})...")
                                
                                # Re-format quantity with new precision using Decimal for exact rounding
                                qty_decimal = decimal.Decimal(str(qty))
                                tick_decimal = prec_tick  # Already a Decimal
                                qty_decimal = (qty_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
                                
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
                                    import json as json_module
                                    request_id_prec = str(uuid_module.uuid4())
                                    logger.info(
                                        f"[SL_ORDER][{source.upper()}][{request_id_prec}] Sending HTTP request (precision variation {prec_decimals}):\n"
                                        f"  URL: {url}\n"
                                        f"  Method: POST\n"
                                        f"  Source: {source}\n"
                                        f"  Payload JSON: {json_module.dumps(payload, ensure_ascii=False, indent=2)}"
                                    )
                                    
                                    response_prec = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                                    
                                    # Log HTTP response for precision variation
                                    try:
                                        response_body_prec = response_prec.json()
                                    except:
                                        response_body_prec = response_prec.text
                                    
                                    logger.info(
                                        f"[SL_ORDER][{source.upper()}][{request_id_prec}] Received HTTP response (precision variation {prec_decimals}):\n"
                                        f"  Status Code: {response_prec.status_code}\n"
                                        f"  Response Body: {json_module.dumps(response_body_prec, ensure_ascii=False, indent=2) if isinstance(response_body_prec, dict) else response_body_prec}"
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
                            
                            # Try different price precision levels automatically
                            # Include more precision options, especially for low-price coins like ALGO
                            price_precision_levels = [
                                (5, 0.00001),   # 5 decimals (common for coins like ALGO around $0.17-0.21)
                                (4, 0.0001),    # 4 decimals
                                (6, 0.000001),  # 6 decimals
                                (3, 0.001),     # 3 decimals
                                (2, 0.01),      # 2 decimals
                                (1, 0.1),       # 1 decimal
                            ]
                            
                            # Try different price precisions
                            price_precision_success = False
                            for prec_decimals, prec_tick in price_precision_levels:
                                logger.info(f"🔄 Trying variation {variation_idx} with price precision {prec_decimals} decimals (tick_size={prec_tick})...")
                                
                                # Re-format price with new precision
                                price_decimal_new = decimal.Decimal(str(price))
                                tick_decimal_new = decimal.Decimal(str(prec_tick))
                                price_decimal_new = (price_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal_new
                                price_str_new = f"{price_decimal_new:.{prec_decimals}f}"
                                
                                # Re-format trigger_price with same precision
                                trigger_decimal_new = decimal.Decimal(str(trigger_price))
                                trigger_decimal_new = (trigger_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal_new
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
                                            ref_decimal_new = decimal.Decimal(str(ref_price_val))
                                            ref_decimal_new = (ref_decimal_new / tick_decimal_new).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal_new
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
                                    response_prec = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                                    
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
                        
                        # For other errors, return immediately
                        logger.error(f"Error creating stop loss order: HTTP {response.status_code}, code={error_code}, message={error_msg}, symbol={symbol}, price={price}, qty={qty}")
                        return {"error": f"Error {error_code}: {error_msg}"}
                    except Exception as parse_err:
                        logger.error(f"Error parsing error response: {parse_err}, response text: {response.text[:200]}")
                        return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
                
                # Success!
                response.raise_for_status()
                result = response.json()
                
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
        
        # Get instrument info to determine exact price and quantity precision required
        price_decimals = None
        price_tick_size = None
        quantity_decimals = 4  # Default to 4 decimals instead of 3
        qty_tick_size = 0.0001
        got_instrument_info = False
        
        try:
            import requests as req
            inst_url = "https://api.crypto.com/exchange/v1/public/get-instruments"
            inst_response = req.get(inst_url, timeout=3)
            if inst_response.status_code == 200:
                inst_data = inst_response.json()
                # API returns instruments in result.data, not result.instruments
                instruments_list = None
                if "result" in inst_data:
                    if "data" in inst_data["result"]:
                        instruments_list = inst_data["result"]["data"]
                    elif "instruments" in inst_data["result"]:
                        instruments_list = inst_data["result"]["instruments"]
                
                if instruments_list:
                    for inst in instruments_list:
                        inst_name = inst.get("instrument_name", "") or inst.get("symbol", "")
                        if inst_name.upper() == symbol.upper():
                            # Try price_decimals first, fallback to quote_decimals
                            price_decimals = inst.get("price_decimals") or inst.get("quote_decimals")
                            price_tick_size_str = inst.get("price_tick_size", "0.01")
                            quantity_decimals = inst.get("quantity_decimals", 4)  # Default to 4 decimals
                            qty_tick_size_str = inst.get("qty_tick_size", "0.0001")
                            try:
                                price_tick_size = float(price_tick_size_str) if price_tick_size_str else None
                                qty_tick_size = float(qty_tick_size_str)
                            except:
                                price_tick_size = None
                                qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.0001
                            got_instrument_info = True
                            logger.info(f"✅ Got instrument info for TAKE_PROFIT_LIMIT {symbol}: price_decimals={price_decimals}, quantity_decimals={quantity_decimals}, price_tick_size={price_tick_size}, qty_tick_size={qty_tick_size}")
                            break
        except Exception as e:
            logger.debug(f"Could not fetch instrument info for {symbol}: {e}. Using default precision.")
        
        # Format price with instrument-specific precision
        import decimal
        price_decimal = decimal.Decimal(str(price))
        
        if price_decimals is not None and price_tick_size:
            # Use instrument-specific precision
            tick_decimal = decimal.Decimal(str(price_tick_size))
            price_decimal = (price_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
            price_str = f"{price_decimal:.{price_decimals}f}"
        elif price >= 100:
            price_str = f"{price:.2f}" if price % 1 == 0 else f"{price:.4f}".rstrip('0').rstrip('.')
        elif price >= 1:
            price_str = f"{price:.4f}".rstrip('0').rstrip('.')
        else:
            price_str = f"{price:.8f}".rstrip('0').rstrip('.')
        
        # Format quantity with instrument-specific precision
        # IMPORTANT: Round DOWN to avoid exceeding available balance
        qty_decimal = decimal.Decimal(str(qty))
        
        if got_instrument_info and qty_tick_size:
            # Use instrument-specific tick size
            tick_decimal = decimal.Decimal(str(qty_tick_size))
            # Round DOWN (ROUND_FLOOR) to ensure we don't exceed available balance
            qty_decimal = (qty_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_FLOOR) * tick_decimal
            # Format with exact decimals, then remove trailing zeros if needed
            qty_str = f"{qty_decimal:.{quantity_decimals}f}".rstrip('0').rstrip('.')
            # Ensure at least one decimal if quantity_decimals > 0
            if quantity_decimals > 0 and '.' not in qty_str:
                qty_str = f"{qty_decimal:.{quantity_decimals}f}"
        else:
            # Preserve original precision with at least 4 decimals
            qty_str_original = f"{qty:.10f}".rstrip('0').rstrip('.')
            if '.' in qty_str_original:
                decimals_needed = len(qty_str_original.split('.')[1])
                decimals_to_use = max(4, decimals_needed)
            else:
                decimals_to_use = 4
            qty_str = f"{qty:.{decimals_to_use}f}"
        
        # Format trigger_price if provided (should be equal to price for TAKE_PROFIT_LIMIT)
        # IMPORTANT: For TAKE_PROFIT_LIMIT, trigger_price MUST equal price (TP Value)
        # Both represent the same value: the price at which the order triggers and executes
        trigger_str = None
        if trigger_price is not None:
            # Verify that trigger_price equals price (both should be TP Value)
            if abs(trigger_price - price) > 0.0001:  # Allow small floating point differences
                logger.warning(f"⚠️ TAKE_PROFIT_LIMIT: trigger_price ({trigger_price}) != price ({price}). Setting trigger_price = price.")
                trigger_price = price  # Force equality
            
            if trigger_price >= 100:
                trigger_str = f"{trigger_price:.2f}" if trigger_price % 1 == 0 else f"{trigger_price:.4f}".rstrip('0').rstrip('.')
            elif trigger_price >= 1:
                trigger_str = f"{trigger_price:.4f}".rstrip('0').rstrip('.')
            else:
                trigger_str = f"{trigger_price:.8f}".rstrip('0').rstrip('.')
        else:
            # If no trigger_price provided, use price as trigger (both are TP Value)
            logger.info(f"TAKE_PROFIT_LIMIT: No trigger_price provided, using price ({price}) as trigger_price (TP Value)")
            trigger_price = price  # Set trigger_price to price
            trigger_str = price_str  # Use same formatted string
        
        # Generate client_oid for tracking
        client_oid = str(uuid.uuid4())
        
        # Try different price format variations (similar to STOP_LIMIT)
        # Crypto.com may require specific price formatting for TAKE_PROFIT_LIMIT
        # Based on user's successful TP order: 3,899 (no decimals) for ETH
        # Priority: Try rounded values without decimals FIRST, then with 1-2 decimals
        # This is critical - simple formats work better than complex ones
        price_format_variations = []
        
        # For high-value coins (ETH, BTC, etc.), try rounded values first (HIGHEST PRIORITY)
        if price >= 100:
            # Variation 1: Round to nearest integer (no decimals) - HIGHEST PRIORITY
            # This matches the user's successful format: 3,899
            price_rounded_int = round(price)
            price_format_variations.append(f"{price_rounded_int}")
            price_format_variations.append(f"{int(price_rounded_int)}")
            
            # Variation 2: Round to 1 decimal (only if different from integer)
            price_rounded_1 = round(price, 1)
            if price_rounded_1 != price_rounded_int:
                if price_rounded_1 % 1 == 0:
                    price_format_variations.append(f"{int(price_rounded_1)}")
                else:
                    price_format_variations.append(f"{price_rounded_1:.1f}")
            
            # Variation 3: Round to 2 decimals (only if different from previous)
            price_rounded_2 = round(price, 2)
            if price_rounded_2 != price_rounded_1:
                if price_rounded_2 % 1 == 0:
                    price_format_variations.append(f"{int(price_rounded_2)}")
                else:
                    price_format_variations.append(f"{price_rounded_2:.2f}")
            
            # Variation 4: Round to 0 decimals but up/down (if different)
            price_rounded_up = int(price) + 1
            price_rounded_down = int(price)
            if price_rounded_up != price_rounded_int:
                price_format_variations.append(f"{price_rounded_up}")
            if price_rounded_down != price_rounded_int:
                price_format_variations.append(f"{price_rounded_down}")
        
        # Variation 5: Try without trailing zeros (simpler format)
        price_format_variations.append(price_str.rstrip('0').rstrip('.'))
        
        # Variation 6: Original format (4 decimals for prices > 1) - LOWER PRIORITY
        price_format_variations.append(price_str)
        
        # Variation 7: Try 3 decimals - LOWER PRIORITY
        price_format_variations.append(f"{price:.3f}")
        
        # Variation 8: Try 6 decimals (more precision) - LOWEST PRIORITY
        price_format_variations.append(f"{price:.6f}")
        
        # Variation 9: If got instrument info, use exact price_decimals format - LOWEST PRIORITY
        if price_decimals is not None:
            price_format_variations.append(f"{price:.{price_decimals}f}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_price_formats = []
        for fmt in price_format_variations:
            if fmt not in seen:
                seen.add(fmt)
                unique_price_formats.append(fmt)
        
        # Also try variations for trigger_price
        # IMPORTANT: Ensure trigger_price is set (should equal price for TAKE_PROFIT_LIMIT)
        if trigger_price is None:
            trigger_price = price  # Set trigger_price to price if not provided
            trigger_str = price_str  # Use same formatted string
            logger.info(f"TAKE_PROFIT_LIMIT: trigger_price was None, using price ({price}) as trigger_price")
        
        trigger_format_variations = []
        if trigger_str and trigger_price is not None:
            # For high-value coins, try rounded values first (same as price) - HIGHEST PRIORITY
            if trigger_price >= 100:
                # Variation 1: Round to nearest integer (no decimals) - HIGHEST PRIORITY
                trigger_rounded_int = round(trigger_price)
                trigger_format_variations.append(f"{trigger_rounded_int}")
                trigger_format_variations.append(f"{int(trigger_rounded_int)}")
                
                # Variation 2: Round to 1 decimal (only if different from integer)
                trigger_rounded_1 = round(trigger_price, 1)
                if trigger_rounded_1 != trigger_rounded_int:
                    if trigger_rounded_1 % 1 == 0:
                        trigger_format_variations.append(f"{int(trigger_rounded_1)}")
                    else:
                        trigger_format_variations.append(f"{trigger_rounded_1:.1f}")
                
                # Variation 3: Round to 2 decimals (only if different from previous)
                trigger_rounded_2 = round(trigger_price, 2)
                if trigger_rounded_2 != trigger_rounded_1:
                    if trigger_rounded_2 % 1 == 0:
                        trigger_format_variations.append(f"{int(trigger_rounded_2)}")
                    else:
                        trigger_format_variations.append(f"{trigger_rounded_2:.2f}")
            
            # Variation 4: Without trailing zeros (simpler format)
            trigger_format_variations.append(trigger_str.rstrip('0').rstrip('.'))
            
            # Variation 5: Original format - LOWER PRIORITY
            trigger_format_variations.append(trigger_str)
            
            # Variation 6: 3 decimals - LOWER PRIORITY
            trigger_format_variations.append(f"{trigger_price:.3f}")
            
            # Variation 7: Instrument-specific precision - LOWEST PRIORITY
            if price_decimals is not None:
                trigger_format_variations.append(f"{trigger_price:.{price_decimals}f}")
        
        seen_triggers = set()
        unique_trigger_formats = []
        for fmt in trigger_format_variations:
            if fmt not in seen_triggers:
                seen_triggers.add(fmt)
                unique_trigger_formats.append(fmt)
        
        logger.info(f"🔄 Trying TAKE_PROFIT_LIMIT with {len(unique_price_formats)} price format variations and {len(unique_trigger_formats)} trigger format variations")
        
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
                
                # Format ref_price - Try multiple approaches based on error 229 analysis
                # Error 229 (INVALID_REF_PRICE) suggests ref_price format/value is wrong
                # Try: 1) Current market price, 2) Entry price, 3) TP price (as fallback)
                ref_price_str = None
                ref_price_val = None
                
                # Get current market price (ticker_price) - REQUIRED for ref_price validation
                # Crypto.com validates ref_price must be on the correct side of market:
                # - If side=SELL, ref_price must be < current market price
                # - If side=BUY, ref_price must be > current market price
                ticker_price = None
                try:
                    # Try to get ticker from Crypto.com public API
                    # Use v2 endpoint which supports single instrument lookup
                    import requests as requests_module
                    ticker_url = "https://api.crypto.com/v2/public/get-ticker"
                    ticker_params = {"instrument_name": symbol}
                    ticker_response = requests_module.get(ticker_url, params=ticker_params, timeout=5)
                    if ticker_response.status_code == 200:
                        ticker_data = ticker_response.json()
                        result_data = ticker_data.get("result", {})
                        if "data" in result_data and len(result_data["data"]) > 0:
                            # Get latest price from ticker (use ask price for SELL, bid for BUY)
                            ticker_data_item = result_data["data"][0]
                            # For SELL orders, use ask price; for BUY orders, use bid price
                            if side_fmt == "SELL":
                                ticker_price = ticker_data_item.get("a")  # Ask price
                            else:
                                ticker_price = ticker_data_item.get("b")  # Bid price
                            
                            if ticker_price:
                                ticker_price = float(ticker_price)
                                logger.info(f"✅ Got current market price from Crypto.com API for {symbol}: {ticker_price} (side={side_fmt})")
                    else:
                        # Fallback to v1 get-tickers endpoint
                        ticker_url_v1 = f"{REST_BASE}/public/get-tickers"
                        ticker_response_v1 = requests_module.get(ticker_url_v1, timeout=5)
                        if ticker_response_v1.status_code == 200:
                            ticker_data_v1 = ticker_response_v1.json()
                            result_data_v1 = ticker_data_v1.get("result", {})
                            if "data" in result_data_v1:
                                # Find our symbol in the tickers list
                                for ticker_item in result_data_v1["data"]:
                                    if ticker_item.get("i") == symbol:
                                        if side_fmt == "SELL":
                                            ticker_price = ticker_item.get("a")  # Ask price
                                        else:
                                            ticker_price = ticker_item.get("b")  # Bid price
                                        if ticker_price:
                                            ticker_price = float(ticker_price)
                                            logger.info(f"✅ Got current market price from Crypto.com v1 API for {symbol}: {ticker_price} (side={side_fmt})")
                                        break
                except Exception as e:
                    logger.debug(f"Could not get market price from Crypto.com API for ref_price: {e}")
                    # Fallback to cached price
                    try:
                        from app.services.data_sources import get_crypto_prices
                        market_prices = get_crypto_prices()
                        if symbol in market_prices:
                            ticker_price = market_prices[symbol]
                            logger.debug(f"Got cached market price for {symbol}: {ticker_price}")
                    except Exception as e2:
                        logger.debug(f"Could not get cached market price: {e2}")
                
                # IMPORTANT: Based on user feedback and successful orders from yesterday,
                # ref_price should equal trigger_price (TP price) for TAKE_PROFIT_LIMIT orders
                # Crypto.com uses ref_price for Trigger Condition display
                # Therefore, ref_price should equal trigger_price (TP price) to ensure correct Trigger Condition
                # For TAKE_PROFIT_LIMIT orders, use TP price directly as ref_price
                # Note: Crypto.com API may validate ref_price, but user requirement is Trigger Condition = TP price
                ref_price_val = price  # Use TP price directly for ref_price so Trigger Condition shows TP price
                
                logger.info(
                    f"[TP_ORDER][{source.upper()}] Final ref_price={ref_price_val}, ticker={ticker_price}, "
                    f"tp_price={price}, closing_side={side_fmt}, instrument_name={symbol}"
                )
                # Note: 'side' parameter is already the CLOSING side (inverted from entry)
                # entry_side would be the inverse: BUY if side=SELL, SELL if side=BUY
                entry_side_inferred = "BUY" if side_fmt == "SELL" else "SELL"
                logger.info(
                    f"[TP_ORDER][{source.upper()}] Closing TP side={side_fmt}, entry_side={entry_side_inferred}, "
                    f"ref_price={ref_price_val}, price={price}, instrument={symbol}"
                )
                
                # Format ref_price with appropriate precision (round to 6 decimals as requested)
                if ref_price_val:
                    # Round to 6 decimal places first
                    ref_price_val = round(ref_price_val, 6)
                    
                    if got_instrument_info and price_tick_size:
                        ref_decimal = decimal.Decimal(str(ref_price_val))
                        tick_decimal = decimal.Decimal(str(price_tick_size))
                        ref_decimal = (ref_decimal / tick_decimal).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP) * tick_decimal
                        ref_price_str = f"{ref_decimal:.{price_decimals or 6}f}".rstrip('0').rstrip('.')
                    elif ref_price_val >= 100:
                        ref_price_str = f"{ref_price_val:.2f}" if ref_price_val % 1 == 0 else f"{ref_price_val:.6f}".rstrip('0').rstrip('.')
                    elif ref_price_val >= 1:
                        ref_price_str = f"{ref_price_val:.6f}".rstrip('0').rstrip('.')
                    else:
                        ref_price_str = f"{ref_price_val:.6f}".rstrip('0').rstrip('.')
                
                # Build params_base - ref_price is REQUIRED for TAKE_PROFIT_LIMIT
                params_base = {
                    "instrument_name": symbol,
                    "type": "TAKE_PROFIT_LIMIT",
                    "price": tp_price_formatted,  # TP price (sale price)
                    "quantity": qty_str,
                    "trigger_price": tp_price_formatted,  # TP price (trigger price) - MUST equal price
                }
                
                # Ensure trigger_price and price are EXACTLY the same string
                params_base["trigger_price"] = params_base["price"]  # Force exact equality
                
                # Add ref_price (REQUIRED by Crypto.com API) - must be TP price (same as trigger_price)
                # Based on error 229 analysis: ref_price must equal trigger_price (both are TP price)
                if ref_price_str:
                    params_base["ref_price"] = ref_price_str
                
                # Add trigger_condition (format: ">= {TP_price}") where TP_price is the TP price
                # Based on user feedback: trigger_condition = ">= {TP}" = ">= 1.5630"
                # The order activates when price reaches >= TP price, then executes at TP price
                params_base["trigger_condition"] = f">= {tp_price_formatted}"
                
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
                params_variations_list.extend([
                    # Variation 1: Minimal params with side
                    params_with_side.copy(),
                    # Variation 2: With client_oid only
                    {**params_with_side, "client_oid": str(uuid.uuid4())},
                    # Variation 3: With time_in_force only
                    {**params_with_side, "time_in_force": "GOOD_TILL_CANCEL"},
                    # Variation 4: All params with client_oid and time_in_force
                    {**params_with_side, "client_oid": str(uuid.uuid4()), "time_in_force": "GOOD_TILL_CANCEL"},
                ])
            
                # Try each params variation - ref_price is already set in params_base (TP price)
                for params_idx, params in enumerate(params_variations_list, 1):
                    # Determine if this variation includes side field
                    has_side_field = "side" in params
                    side_in_params = params.get("side", "NONE")
                    side_label = f"side{side_in_params}" if has_side_field else "no-side"
                    variation_name_full = f"{variation_name}-{side_label}-params{params_idx}"
                    
                    # ref_price and trigger_condition are already set in params_base above
                    # They use the TP price, so trigger_condition = ">= {TP_price}"
                    trigger_price_val = params_base.get("trigger_price", "N/A")
                    ref_price_val_str = params.get("ref_price", "N/A")
                    trigger_condition_val = params.get("trigger_condition", "N/A")
                    
                    # Generate unique request ID for tracking
                    import uuid as uuid_module
                    request_id = str(uuid_module.uuid4())
                    
                    logger.info(f"🔄 Trying TAKE_PROFIT_LIMIT variation {variation_name_full}: price='{price_fmt}', trigger_price='{trigger_price_val}', ref_price='{ref_price_val_str}', trigger_condition='{trigger_condition_val}', quantity='{qty_str}', side='{side_fmt}'")
                    logger.info(f"   📦 FULL PAYLOAD: {params}")
                    logger.debug(f"   Full params: {params}")
                    
                    # DEBUG: Log before sign_request
                    logger.info(f"[DEBUG][{source.upper()}][{request_id}] About to call sign_request for variation {variation_name_full}")
                    
                    payload = self.sign_request(method, params)
                    
                    # DEBUG: Log after sign_request
                    logger.info(f"[DEBUG][{source.upper()}][{request_id}] sign_request completed, payload keys: {list(payload.keys())}")
                    
                    # Log HTTP request details with source and request_id
                    import json as json_module
                    url = f"{self.base_url}/{method}"
                    logger.info(f"[TP_ORDER][{source.upper()}][{request_id}] Sending HTTP request to exchange:")
                    logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   URL: {url}")
                    logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Method: POST")
                    logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Source: {source}")
                    logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Payload JSON: {json_module.dumps(payload, ensure_ascii=False, indent=2)}")
                    
                    try:
                        logger.debug(f"Request URL: {url}")
                        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
                        
                        # Log HTTP response details
                        try:
                            response_body = response.json()
                        except:
                            response_body = response.text
                        
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}] Received HTTP response from exchange:")
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Status Code: {response.status_code}")
                        response_body_str = json_module.dumps(response_body, ensure_ascii=False, indent=2) if isinstance(response_body, dict) else str(response_body)
                        logger.info(f"[TP_ORDER][{source.upper()}][{request_id}]   Response Body: {response_body_str}")
                        
                        if response.status_code == 401:
                            error_data = response.json()
                            error_code = error_data.get("code", 0)
                            error_msg = error_data.get("message", "")
                            logger.error(f"Authentication failed: {error_code} - {error_msg}")
                            return {"error": f"Authentication failed: {error_msg} (code: {error_code})"}
                        
                        # Check for error responses (400, etc.) before raise_for_status
                        if response.status_code != 200:
                            try:
                                error_data = response.json()
                                error_code = error_data.get('code', 0)
                                error_msg = error_data.get('message', 'Unknown error')
                                last_error = f"Error {error_code}: {error_msg}"
                                
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
                    
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"⚠️ Variation {variation_name_full} failed with network error: {e}. Trying next variation...")
                        last_error = str(e)
                        continue  # Try next params variation
                    except Exception as e:
                        logger.warning(f"⚠️ Variation {variation_name_full} failed with error: {e}. Trying next variation...")
                        last_error = str(e)
                        continue  # Try next params variation
        
        # All variations failed
        logger.error(f"❌ All TAKE_PROFIT_LIMIT price/trigger format variations failed. Last error: {last_error}")
        return {"error": f"All format variations failed. Last error: {last_error}"}
    
    def get_instruments(self) -> list:
        """Get list of available trading instruments (public endpoint)"""
        # Use public API endpoint for instruments (v1)
        public_url = f"{REST_BASE}/public/get-instruments"
        
        try:
            response = requests.get(public_url, timeout=10)
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
