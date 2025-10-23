import requests
from typing import List, Dict
from fastapi import HTTPException, status
from app.services.brokers.base import MarketDataAdapter, normalize

class BinanceAdapter(MarketDataAdapter):
    BASE_URL = "https://api.binance.com/api/v3"
    
    def get_price(self, symbol: str) -> float:
        """Get current price from Binance"""
        try:
            # Normalize symbol: BTC_USDT -> BTCUSDT
            normalized_symbol = normalize(symbol)
            response = requests.get(
                f"{self.BASE_URL}/ticker/price",
                params={"symbol": normalized_symbol},
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except requests.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Binance API error: {e.response.text if hasattr(e, 'response') else str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Binance connection error: {str(e)}"
            )
    
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get OHLCV data from Binance"""
        try:
            # Normalize symbol: BTC_USDT -> BTCUSDT
            normalized_symbol = normalize(symbol)
            response = requests.get(
                f"{self.BASE_URL}/klines",
                params={
                    "symbol": normalized_symbol,
                    "interval": interval,
                    "limit": limit
                },
                timeout=5
            )
            response.raise_for_status()
            klines = response.json()
            
            # Convert Binance klines format to our format
            result = []
            for kline in klines:
                result.append({
                    "t": kline[0],  # timestamp
                    "o": float(kline[1]),  # open
                    "h": float(kline[2]),  # high
                    "l": float(kline[3]),  # low
                    "c": float(kline[4]),  # close
                    "v": float(kline[5])   # volume
                })
            return result
        except requests.HTTPError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Binance API error: {e.response.text if hasattr(e, 'response') else str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Binance connection error: {str(e)}"
            )
