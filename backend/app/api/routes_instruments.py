from fastapi import APIRouter, HTTPException
from typing import List
import logging
import requests

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/instruments")
async def get_instruments():
    """Get list of available trading instruments"""
    try:
        # Fetch instruments from Crypto.com Exchange public API
        url = "https://api.crypto.com/exchange/v1/public/get-instruments"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        if "result" in result and "instruments" in result["result"]:
            instruments = []
            for inst in result["result"]["instruments"]:
                instruments.append({
                    "symbol": inst.get("instrument_name", ""),
                    "status": inst.get("status", "unknown"),
                    "base_currency": inst.get("base_currency", ""),
                    "quote_currency": inst.get("quote_currency", ""),
                    "price_decimals": inst.get("price_decimals", 0),
                    "quantity_decimals": inst.get("quantity_decimals", 0)
                })
            return {"instruments": instruments}
        else:
            logger.warning("Unexpected response format from Crypto.com API")
            # Fallback to basic list
            return {
                "instruments": [
                    {"symbol": "CRO_USDT", "status": "active"},
                    {"symbol": "BTC_USDT", "status": "active"},
                ]
            }
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        # Return fallback data on error
        return {
            "instruments": [
                {"symbol": "CRO_USDT", "status": "active"},
                {"symbol": "BTC_USDT", "status": "active"},
            ]
        }

@router.get("/instruments/{symbol}")
async def get_instrument(symbol: str):
    """Get details for a specific instrument"""
    try:
        # Fetch all instruments and filter by symbol
        url = "https://api.crypto.com/exchange/v1/public/get-instruments"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        if "result" in result and "instruments" in result["result"]:
            # Find the specific instrument
            for inst in result["result"]["instruments"]:
                if inst.get("instrument_name", "").upper() == symbol.upper():
                    return {
                        "symbol": inst.get("instrument_name", ""),
                        "status": inst.get("status", "unknown"),
                        "base_currency": inst.get("base_currency", ""),
                        "quote_currency": inst.get("quote_currency", ""),
                        "price_decimals": inst.get("price_decimals", 0),
                        "quantity_decimals": inst.get("quantity_decimals", 0),
                        "min_price_increment": inst.get("min_price_increment", "0.0001"),
                        "min_quantity": inst.get("min_quantity", "0.001"),
                        "max_quantity": inst.get("max_quantity", ""),
                        "margin_trading_enabled": inst.get("margin_trading_enabled", False)
                    }
        
        # If instrument not found, return basic info
        logger.warning(f"Instrument {symbol} not found in API response")
        return {
            "symbol": symbol,
            "status": "not_found",
            "min_price_increment": "0.0001",
            "min_quantity": "0.001"
        }
    except Exception as e:
        logger.error(f"Error fetching instrument {symbol}: {e}")
        # Return fallback data on error
        return {
            "symbol": symbol,
            "status": "error",
            "min_price_increment": "0.0001",
            "min_quantity": "0.001"
        }
