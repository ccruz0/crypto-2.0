from fastapi import APIRouter
from typing import List, Dict, Any
import requests
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/crypto-data")
def get_crypto_data():
    """Get real crypto data from Crypto.com API"""
    try:
        # Get real crypto prices from Crypto.com
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Process real data
        crypto_data = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"][:20]:  # Get first 20 cryptos
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                volume_24h = float(ticker.get("v", 0))
                price_change_24h = float(ticker.get("c", 0))
                
                if "_USDT" in instrument_name:
                    crypto = instrument_name.replace("_USDT", "")
                    crypto_data.append({
                        "symbol": crypto,
                        "price": last_price,
                        "volume_24h": volume_24h,
                        "change_24h": price_change_24h,
                        "change_percent": (price_change_24h / last_price * 100) if last_price > 0 else 0
                    })
        
        return {
            "success": True,
            "data": crypto_data,
            "count": len(crypto_data),
            "source": "Crypto.com API"
        }
    except Exception as e:
        logger.error(f"Error fetching crypto data: {e}")
        return {
            "success": False,
            "error": str(e),
            "data": []
        }

