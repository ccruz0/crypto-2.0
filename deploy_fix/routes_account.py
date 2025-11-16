from fastapi import APIRouter, Depends, HTTPException, Query
from app.deps.auth import get_current_user
from app.services.brokers.crypto_com_trade import trade_client
from app.utils.redact import redact_secrets
import logging
import requests
from typing import Dict, Optional

logger = logging.getLogger(__name__)
router = APIRouter()

def get_crypto_prices() -> Dict[str, float]:
    """Get current prices for major cryptocurrencies"""
    try:
        # Get prices from Crypto.com Exchange public API
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        prices = {}
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"]:
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                
                # Convert BTC_USDT -> BTC, SOL_USDT -> SOL, etc.
                if "_USDT" in instrument_name:
                    crypto = instrument_name.replace("_USDT", "")
                    prices[crypto] = last_price
                elif "_USD" in instrument_name:
                    crypto = instrument_name.replace("_USD", "")
                    prices[crypto] = last_price
        
        # Ensure USD and USDT are 1.0
        prices["USD"] = 1.0
        prices["USDT"] = 1.0
        
        return prices
    except Exception as e:
        logger.error(f"Error fetching crypto prices: {e}")
        # Return fallback prices
        return {
            "BTC": 65000.0,
            "ETH": 3500.0,
            "USDT": 1.0,
            "USD": 1.0,
            "EUR": 1.08,
            "SOL": 100.0,
            "XRP": 0.6,
            "ADA": 0.5,
            "DOT": 7.0,
            "ALGO": 0.2,
            "AVAX": 35.0,
            "SUI": 1.5,
            "APT": 10.0,
            "AAVE": 100.0,
            "NEAR": 4.0,
            "TON": 5.0,
            "CRO": 0.1,
            "LDO": 2.5,
            "STRK": 0.7,
            "DGB": 0.01,
            "BONK": 0.00001,
            "AKT": 1.0
        }

@router.get("/account/balance")
def get_account_balance(
    exchange: str = Query(..., description="Exchange name"),
    include_usd: bool = Query(True, description="Include USD conversion"),
    current_user = Depends(get_current_user)
):
    """Get account balance for specified exchange with optional USD conversion"""
    if exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    try:
        result = trade_client.get_account_summary()
        logger.info(f"Account balance retrieved for {exchange}")
        
        # Add USD conversion if requested
        if include_usd and "accounts" in result:
            prices = get_crypto_prices()
            total_usd = 0.0
            
            for account in result["accounts"]:
                currency = account.get("currency", "")
                balance = float(account.get("balance", 0))
                
                # Calculate USD value
                if currency == "USDT":
                    usd_value = balance
                else:
                    price = prices.get(currency, 0)
                    usd_value = balance * price
                
                account["usd_value"] = round(usd_value, 2)
                total_usd += usd_value
            
            result["total_usd"] = round(total_usd, 2)
        
        logger.debug(f"Response: {redact_secrets(result)}")
        return result
    except Exception as e:
        logger.error(f"Error getting account balance: {e}")
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg:
            raise HTTPException(
                status_code=401, 
                detail="API authentication failed. Please check: 1) API key permissions include 'Read balance', 2) IP whitelist includes your server IP, 3) API credentials are correct. See: https://help.crypto.com/en/articles/3511424-api"
            )
        raise HTTPException(status_code=502, detail=str(e))

