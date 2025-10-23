from typing import Literal, List, Dict
from abc import ABC, abstractmethod

Exchange = Literal["BINANCE", "CRYPTO_COM"]

class MarketDataAdapter(ABC):
    @abstractmethod
    def get_price(self, symbol: str) -> float:
        """Get current price for a symbol"""
        pass
    
    @abstractmethod
    def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 100) -> List[Dict]:
        """Get OHLCV data for a symbol"""
        pass

def normalize(symbol: str) -> str:
    """Normalize symbol: BTC_USDT -> BTCUSDT (for Binance), stays BTC_USDT for Crypto.com"""
    return symbol.replace("_", "")
