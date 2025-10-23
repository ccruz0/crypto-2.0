import requests
from typing import List, Dict
from fastapi import HTTPException, status
from app.services.brokers.base import MarketDataAdapter

class CryptoComAdapter(MarketDataAdapter):
    BASE_URL = "https://api.crypto.com/v2/public"
    
    def get_price(self, symbol: str) -> float:
        """Get current price from Crypto.com"""
        try:
            # Crypto.com uses underscores in symbols
            response = requests.get(
                f"{self.BASE_URL}/get-ticker",
                params={"instrument_name": symbol},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            # Use ask price or last price
            result = data.get("result", {})
            data_obj = result.get("data", {})
            
            # Crypto.com returns an array in "data"
            if isinstance(data_obj, list) and len(data_obj) > 0:
                ticker = data_obj[0]
                # Use "a" (ask) or "h" (high) as price indicator
                if "a" in ticker:
                    return float(ticker["a"])
                elif "h" in ticker:
                    return float(ticker["h"])
                else:
                    raise ValueError("No price data available")
            else:
                raise ValueError("No price data available")
        except requests.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Crypto.com API error: {e.response.text if hasattr(e, 'response') else str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Crypto.com connection error: {str(e)}"
            )
    
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get OHLCV data from Crypto.com"""
        try:
            # Crypto.com uses underscores in symbols
            response = requests.get(
                f"{self.BASE_URL}/get-candlestick",
                params={
                    "instrument_name": symbol,
                    "timeframe": interval
                },
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            result_data = data.get("result", {}).get("data", [])
            
            # Convert Crypto.com format to our format
            result = []
            for candle in result_data[:limit]:
                result.append({
                    "t": candle["t"],  # timestamp
                    "o": float(candle["o"]),  # open
                    "h": float(candle["h"]),  # high
                    "l": float(candle["l"]),  # low
                    "c": float(candle["c"]),  # close
                    "v": float(candle["v"])   # volume
                })
            return result
        except requests.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Crypto.com API error: {e.response.text if hasattr(e, 'response') else str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Crypto.com connection error: {str(e)}"
            )
