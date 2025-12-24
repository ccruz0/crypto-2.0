from fastapi import APIRouter, Depends, HTTPException, Query
from app.deps.auth import get_current_user
from app.services.brokers.crypto_com_trade import trade_client
from app.services.portfolio_cache import get_portfolio_summary, update_portfolio_cache
from app.models.db import get_db
from app.utils.redact import redact_secrets
import logging
from typing import Dict, Optional
from app.utils.http_client import http_get, http_post

logger = logging.getLogger(__name__)
router = APIRouter()

def get_crypto_prices() -> Dict[str, float]:
    """Get current prices for major cryptocurrencies"""
    try:
        # Get prices from Crypto.com Exchange public API
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = http_get(url, timeout=10, calling_module="routes_account")
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
    db = Depends(get_db)
    # Temporarily disable auth for testing
    # current_user = Depends(get_current_user)
):
    """Get account balance for specified exchange with optional USD conversion"""
    if exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    try:
        # Get cached portfolio data
        portfolio_summary = get_portfolio_summary(db)
        
        if not portfolio_summary or not portfolio_summary.get("balances"):
            # No cached data, try to fetch fresh data
            logger.info("No cached data found, fetching fresh data...")
            update_result = update_portfolio_cache(db)
            if update_result.get("success"):
                portfolio_summary = get_portfolio_summary(db)
            else:
                logger.warning("Failed to update portfolio cache")
        
        # Convert to expected format
        accounts = []
        for balance in portfolio_summary.get("balances", []):
            accounts.append({
                "currency": balance["currency"],
                "balance": str(balance["balance"]),
                "usd_value": balance["usd_value"]
            })
        
        result = {
            "accounts": accounts,
            "total_usd": portfolio_summary.get("total_usd", 0.0),
            "last_updated": portfolio_summary.get("last_updated")
        }
        
        logger.info(f"Account balance retrieved for {exchange}")
        logger.debug(f"Response: {redact_secrets(result)}")
        return result
    except Exception as e:
        logger.error(f"Error getting account balance: {e}")
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg or "40101" in error_msg or "40103" in error_msg:
            # Extract error code if present
            error_code = "40101" if "40101" in error_msg else ("40103" if "40103" in error_msg else "401")
            detail_msg = f"API authentication failed (code: {error_code}). "
            if "40101" in error_msg:
                detail_msg += "Check: 1) API key has 'Read' permission enabled, 2) API key is not disabled/suspended, 3) API credentials are correct."
            elif "40103" in error_msg:
                detail_msg += "IP address not whitelisted. Add your server's outbound IP to Crypto.com Exchange API key whitelist."
            else:
                detail_msg += "Please check: 1) API key permissions include 'Read', 2) IP whitelist includes your server IP, 3) API credentials are correct."
            raise HTTPException(status_code=401, detail=detail_msg)
        raise HTTPException(status_code=502, detail=str(e))

@router.post("/account/balance/refresh")
def refresh_account_balance(
    exchange: str = Query(..., description="Exchange name"),
    db = Depends(get_db)
    # Temporarily disable auth for testing
    # current_user = Depends(get_current_user)
):
    """Manually refresh the cached account balance from Crypto.com"""
    if exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")
    
    try:
        logger.info(f"Manual refresh requested for {exchange}")
        result = update_portfolio_cache(db)
        
        if result.get("success"):
            return {
                "message": "Portfolio cache updated successfully",
                "last_updated": result.get("last_updated"),
                "total_usd": result.get("total_usd")
            }
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to update portfolio cache: {result.get('error', 'Unknown error')}"
            )
    except Exception as e:
        logger.error(f"Error refreshing account balance: {e}")
        raise HTTPException(status_code=502, detail=str(e))

