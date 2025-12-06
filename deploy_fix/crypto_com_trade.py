import os
import time
import hmac
import hashlib
import json
import logging
import requests
from typing import Dict, Optional
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class CryptoComTradeClient:
    """Crypto.com Exchange v1 Private API Client"""
    
    def __init__(self):
        # Crypto.com Exchange API endpoint
        custom_base = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "")
        if custom_base:
            self.base_url = custom_base
        else:
            # Default to Crypto.com Exchange v1 API endpoint
            self.base_url = "https://api.crypto.com/exchange/v1"
        
        self.api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "")
        self.api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "")
        self.live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        
        logger.info(f"CryptoComTradeClient initialized - Live Trading: {self.live_trading}")
        logger.info(f"Using base URL: {self.base_url}")
    
    def _params_to_str(self, obj, level=0):
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
                for subObj in obj[key]:
                    return_str += self._params_to_str(subObj, level + 1)
            else:
                return_str += str(obj[key])
        return return_str
    
    def sign_request(self, method: str, params: dict) -> dict:
        """
        Generate signed JSON-RPC 2.0 request for Crypto.com Exchange v1
        Following official docs exactly: method + id + api_key + params_string + nonce
        """
        nonce_ms = int(time.time() * 1000)
        
        # Build params string exactly as Crypto.com docs specify
        param_str = ""
        if params:
            param_str = self._params_to_str(params, 0)
        
        # Construct payload
        payload = {
            "id": nonce_ms,
            "method": method,
            "api_key": self.api_key,
            "params": params,
            "nonce": nonce_ms
        }
        
        # String to sign: method + id + api_key + params_string + nonce
        string_to_sign = method + str(nonce_ms) + self.api_key + param_str + str(nonce_ms)
        
        logger.info(f"String to sign: {string_to_sign}")
        logger.info(f"API Key: {self.api_key}")
        logger.info(f"API Secret (first 10): {self.api_secret[:10] if self.api_secret else 'None'}")
        
        # Generate HMAC-SetCode
        signature = hmac.new(
            bytes(str(self.api_secret), 'utf-8'),
            msg=bytes(string_to_sign, 'utf-8'),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        logger.info(f"Generated signature: {signature}")
        
        payload["sig"] = signature
        
        return payload
    
    def get_account_summary(self) -> dict:
        """Get account summary (balances)"""
        if not self.live_trading:
            logger.info("DRY_RUN: get_account_summary - returning simulated data")
            return {
                "accounts": [
                    {"currency": "USDT", "balance": "10000.0", "available": "10000.0"},
                    {"currency": "BTC", "balance": "0.1", "available": "0.1"}
                ]
            }
        
        # Check if API credentials are configured
        if not self.api_key or not self.api_secret:
            logger.warning("API credentials not configured. Returning simulated data.")
            return {
                "accounts": [
                    {"currency": "USDT", "balance": "0.0", "available": "0.0"},
                    {"currency": "BTC", "balance": "0.0", "available": "0.0"}
                ]
            }
        
        method = "private/user-balance"
        params = {}
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: Calling {method}")
        
        try:
            # Crypto.com Exchange v1 API expects the method as the URL path
            url = f"{self.base_url}/{method}"
            logger.debug(f"Request URL: {url}")
            response = requests.post(url, json=payload, timeout=10)
            
            # Check if authentication failed
            if response.status_code == 401:
                error_data = response.json()
                error_code = error_data.get("code", 0)
                error_msg = error_data.get("message", "")
                
                logger.warning(f"API authentication failed: {error_msg} (code: {error_code})")
                
                # If IP not whitelisted or other auth issues, return simulated data
                if error_code in [40101, 40103]:  # Authentication failure or IP illegal
                    logger.info("Falling back to simulated data due to authentication failure")
                    return {
                        "accounts": [
                            {"currency": "USDT", "balance": "10000.0", "available": "10000.0"},
                            {"currency": "BTC", "balance": "0.1", "available": "0.1"}
                        ]
                    }
            
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"Response: {result}")
            
            # Crypto.com returns data in result.data format with position_balances
            if "result" in result and "data" in result["result"]:
                data = result["result"]["data"]
                accounts = []
                
                # Extract position balances and convert to standard format
                for position in data:
                    if "position_balances" in position:
                        for balance in position["position_balances"]:
                            instrument = balance.get("instrument_name", "")
                            quantity = balance.get("quantity", "0")
                            market_value = balance.get("market_value", "0")
                            
                            # Convert quantity to string format
                            accounts.append({
                                "currency": instrument,
                                "balance": str(quantity),
                                "available": str(quantity)  # For user-balance, available = balance
                            })
                
                logger.info(f"Retrieved {len(accounts)} account balances")
                return {"accounts": accounts}
            else:
                logger.error(f"Unexpected response format: {result}")
                raise HTTPException(status_code=502, detail="Invalid response format")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting account balance: {e}")
            # Fall back to simulated data on network errors
            logger.info("Falling back to simulated data due to network error")
            return {
                "accounts": [
                    {"currency": "USDT", "balance": "10000.0", "available": "10000.0"},
                    {"currency": "BTC", "balance": "0.1", "available": "0.1"}
                ]
            }
        except Exception as e:
            logger.error(f"Error getting account balance: {e}")
            # Fall back to simulated data on any error
            logger.info("Falling back to simulated data due to error")
            return {
                "accounts": [
                    {"currency": "USDT", "balance": "10000.0", "available": "10000.0"},
                    {"currency": "BTC", "balance": "0.1", "available": "0.1"}
                ]
            }
    
    def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        qty: float, 
        *, 
        is_margin: bool = False, 
        leverage: Optional[float] = None, 
        dry_run: bool = True
    ) -> dict:
        """Place market order"""
        actual_dry_run = dry_run or not self.live_trading
        
        if actual_dry_run:
            logger.info(f"DRY_RUN: place_market_order - {symbol} {side} {qty}")
            return {
                "order_id": f"dry_{int(time.time())}",
                "client_order_id": f"dry_{int(time.time())}",
                "status": "FILLED",
                "side": side,
                "type": "MARKET",
                "quantity": str(qty),
                "price": "0",  # Market orders don't have price
                "created_time": int(time.time() * 1000)
            }
        
        method = "private/create-order"
        params = {
            "instrument_name": symbol,
            "side": side.lower(),
            "type": "MARKET",
            "quantity": str(qty)
        }
        
        if is_margin and leverage:
            params["leverage"] = str(int(leverage))
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: place_market_order - {symbol} {side} {qty}")
        logger.debug(f"Payload: {payload}")
        
        # TODO: Make actual HTTP request
        # response = requests.post(self.base_url, json=payload)
        # return response.json()
        
        return {"error": "Not implemented - need HTTP client"}
    
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
        params = {
            "instrument_name": symbol,
            "side": side.lower(),
            "type": "LIMIT",
            "price": str(price),
            "quantity": str(qty)
        }
        
        if is_margin and leverage:
            params["leverage"] = str(int(leverage))
        
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: place_limit_order - {symbol} {side} {qty} @ {price}")
        logger.debug(f"Payload: {payload}")
        
        # TODO: Make actual HTTP request
        # response = requests.post(self.base_url, json=payload)
        # return response.json()
        
        return {"error": "Not implemented - need HTTP client"}
    
    def cancel_order(self, order_id: str) -> dict:
        """Cancel order by order_id"""
        if not self.live_trading:
            logger.info(f"DRY_RUN: cancel_order - {order_id}")
            return {"order_id": order_id, "status": "CANCELLED"}
        
        method = "private/cancel-order"
        params = {"order_id": order_id}
        payload = self.sign_request(method, params)
        
        logger.info(f"Live: cancel_order - {order_id}")
        
        # TODO: Make actual HTTP request
        return {"error": "Not implemented - need HTTP client"}
    
    def get_instruments(self) -> list:
        """Get list of available trading instruments (public endpoint)"""
        # Use public API endpoint for instruments
        public_url = "https://api.crypto.com/v2/public/get-instruments"
        
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
