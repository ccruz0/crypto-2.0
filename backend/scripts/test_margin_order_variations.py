#!/usr/bin/env python3
"""
Test script to try different payload variations for ALGO_USDT margin orders.
We'll test various parameter combinations to find one that works.
"""
import sys
import os
import logging
import json
import requests
import hmac
import hashlib
import time
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
DESIRED_SYMBOL = "ALGO_USDT"
DESIRED_SIDE = "BUY"
DESIRED_LEVERAGE = 2
DESIRED_NOTIONAL = 1000.0

def sign_request(api_key: str, api_secret: str, method: str, params: dict, nonce: int) -> dict:
    """Sign request for Crypto.com API"""
    payload = {
        "id": 1,
        "method": method,
        "api_key": api_key,
        "params": params,
        "nonce": nonce
    }
    
    # Create signature
    param_str = json.dumps(params, separators=(',', ':'))
    sig_str = f"{method}{api_key}{param_str}{nonce}"
    sig = hmac.new(api_secret.encode(), sig_str.encode(), hashlib.sha256).hexdigest()
    
    payload["sig"] = sig
    return payload

def test_payload_variation(variation_name: str, params: dict, api_key: str, api_secret: str, base_url: str):
    """Test a specific payload variation"""
    logger.info("=" * 80)
    logger.info(f"TESTING VARIATION: {variation_name}")
    logger.info("=" * 80)
    logger.info(f"Params: {json.dumps(params, indent=2, ensure_ascii=False)}")
    
    method = "private/create-order"
    nonce = int(time.time() * 1000)
    
    payload = sign_request(api_key, api_secret, method, params, nonce)
    
    # Log payload (with redacted secrets)
    log_payload = payload.copy()
    log_payload["api_key"] = "<REDACTED>"
    log_payload["sig"] = "<REDACTED>"
    logger.info(f"Full payload: {json.dumps(log_payload, indent=2, ensure_ascii=False)}")
    
    url = f"{base_url}/{method}"
    
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        response_data = response.json()
        
        logger.info(f"Status Code: {response.status_code}")
        logger.info(f"Response: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
        
        if response.status_code == 200 and "error" not in str(response_data):
            logger.info(f"✅ SUCCESS! Variation '{variation_name}' worked!")
            return True
        elif response_data.get("code") == 306:
            logger.warning(f"❌ Still error 306 (INSUFFICIENT_AVAILABLE_BALANCE) - but payload format might be correct")
        else:
            logger.warning(f"⚠️ Different error: code={response_data.get('code')}, message={response_data.get('message')}")
        
        return False
    except Exception as e:
        logger.error(f"❌ Exception: {e}", exc_info=True)
        return False

def main():
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "")
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "")
    base_url = os.getenv("CRYPTO_REST_BASE", "https://api.crypto.com/exchange/v1")
    
    if not api_key or not api_secret:
        logger.error("Missing EXCHANGE_CUSTOM_API_KEY or EXCHANGE_CUSTOM_API_SECRET")
        return
    
    client_oid = str(uuid.uuid4())
    
    # Variation 1: Current payload (baseline)
    variation_1 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "notional": "1000.00",
        "leverage": "2"
    }
    
    # Variation 2: leverage as number (not string)
    variation_2 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "notional": "1000.00",
        "leverage": 2
    }
    
    # Variation 3: notional as number (not string)
    variation_3 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "notional": 1000.00,
        "leverage": "2"
    }
    
    # Variation 4: both as numbers
    variation_4 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "notional": 1000.00,
        "leverage": 2
    }
    
    # Variation 5: Remove client_oid
    variation_5 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "notional": "1000.00",
        "leverage": "2"
    }
    
    # Variation 6: Add time_in_force
    variation_6 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "notional": "1000.00",
        "leverage": "2",
        "time_in_force": "IOC"  # Immediate or Cancel for market orders
    }
    
    # Variation 7: Use quantity instead of notional (calculate qty from notional)
    # First get current price to calculate quantity
    try:
        ticker_url = f"{base_url}/public/get-ticker"
        ticker_response = requests.get(f"{ticker_url}?instrument_name={DESIRED_SYMBOL}", timeout=5)
        ticker_data = ticker_response.json()
        if "result" in ticker_data and "data" in ticker_data["result"]:
            ticker = ticker_data["result"]["data"]
            if isinstance(ticker, list) and len(ticker) > 0:
                current_price = float(ticker[0].get("a", 1.0))  # 'a' is ask price
            else:
                current_price = float(ticker.get("a", 1.0))
        else:
            current_price = 1.0  # Fallback
        
        qty = DESIRED_NOTIONAL / current_price
        logger.info(f"Current {DESIRED_SYMBOL} price: ${current_price}, calculated qty for ${DESIRED_NOTIONAL}: {qty}")
    except:
        current_price = 1.0
        qty = DESIRED_NOTIONAL
    
    variation_7 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "client_oid": client_oid,
        "quantity": f"{qty:.8f}".rstrip('0').rstrip('.'),
        "leverage": "2"
    }
    
    # Variation 8: No client_oid, leverage as number
    variation_8 = {
        "instrument_name": DESIRED_SYMBOL,
        "side": DESIRED_SIDE,
        "type": "MARKET",
        "notional": "1000.00",
        "leverage": 2
    }
    
    variations = [
        ("1. Baseline (current)", variation_1),
        ("2. leverage as number", variation_2),
        ("3. notional as number", variation_3),
        ("4. both as numbers", variation_4),
        ("5. no client_oid", variation_5),
        ("6. with time_in_force", variation_6),
        ("7. use quantity instead of notional", variation_7),
        ("8. no client_oid + leverage as number", variation_8),
    ]
    
    logger.info("=" * 80)
    logger.info("STARTING PAYLOAD VARIATION TESTS")
    logger.info("=" * 80)
    
    for name, params in variations:
        # Use unique client_oid for each variation (except those that don't use it)
        if "client_oid" in params:
            params["client_oid"] = str(uuid.uuid4())
        
        success = test_payload_variation(name, params, api_key, api_secret, base_url)
        
        if success:
            logger.info("=" * 80)
            logger.info(f"🎉 FOUND WORKING VARIATION: {name}")
            logger.info("=" * 80)
            break
        
        # Small delay between tests
        time.sleep(2)
    
    logger.info("=" * 80)
    logger.info("ALL VARIATIONS TESTED")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()

