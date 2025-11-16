"""
FastAPI routes for price fetching with multi-source fallback
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
import logging

# Import our price fetcher
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from price_fetcher import get_price_with_fallback

router = APIRouter(prefix="/api", tags=["price"])

@router.get("/fetch_price")
def fetch_price(
    symbol: str = Query("BTC_USDT", description="Trading symbol (e.g., BTC_USDT, ETH_USDT)"),
    timeframe: str = Query("15m", description="Timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)")
) -> Dict[str, Any]:
    """
    Fetch real-time price data with automatic fallback between multiple sources.
    
    Sources (in order):
    1. Crypto.com Exchange
    2. Binance Spot
    3. Kraken
    4. CoinPaprika
    
    Returns:
    - symbol: Trading symbol
    - source: Which API provided the data
    - price: Current price
    - rsi: 14-period RSI
    - ma10, ma50, ma200: Moving averages
    - time: Timestamp
    """
    try:
        result = get_price_with_fallback(symbol, timeframe)
        return result
    except Exception as e:
        logging.error(f"Price fetch failed for {symbol}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch price data for {symbol}: {str(e)}"
        )

@router.get("/price_sources")
def get_price_sources() -> Dict[str, Any]:
    """Get information about available price sources"""
    return {
        "sources": [
            {
                "name": "crypto_com",
                "description": "Crypto.com Exchange API",
                "priority": 1,
                "status": "active"
            },
            {
                "name": "binance", 
                "description": "Binance Spot API",
                "priority": 2,
                "status": "active"
            },
            {
                "name": "kraken",
                "description": "Kraken API", 
                "priority": 3,
                "status": "active"
            },
            {
                "name": "coinpaprika",
                "description": "CoinPaprika API",
                "priority": 4,
                "status": "active"
            }
        ],
        "fallback_enabled": True,
        "timeout_seconds": 5
    }
