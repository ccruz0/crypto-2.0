from typing import Dict, List
from time import time
from app.services.brokers.base import Exchange
from app.services.brokers.binance import BinanceAdapter
from app.services.brokers.crypto_com import CryptoComAdapter

class MarketDataManager:
    def __init__(self):
        self.binance = BinanceAdapter()
        self.crypto_com = CryptoComAdapter()
        
        # Simple in-memory cache
        self.price_cache: Dict[str, tuple[float, float]] = {}  # key -> (price, timestamp)
        self.ohlcv_cache: Dict[str, tuple[List[Dict], float]] = {}  # key -> (data, timestamp)
        
        self.PRICE_TTL = 5  # seconds
        self.OHLCV_TTL = 30  # seconds
    
    def _get_adapter(self, exchange: Exchange):
        """Get the appropriate adapter for the exchange"""
        if exchange == "BINANCE":
            return self.binance
        elif exchange == "CRYPTO_COM":
            return self.crypto_com
        else:
            raise ValueError(f"Unknown exchange: {exchange}")
    
    def get_last_price(self, exchange: Exchange, symbol: str) -> float:
        """Get last price with caching"""
        cache_key = f"{exchange}:{symbol}"
        current_time = time()
        
        # Check cache
        if cache_key in self.price_cache:
            price, timestamp = self.price_cache[cache_key]
            if current_time - timestamp < self.PRICE_TTL:
                return price
        
        # Fetch from exchange
        adapter = self._get_adapter(exchange)
        price = adapter.get_price(symbol)
        
        # Update cache
        self.price_cache[cache_key] = (price, current_time)
        
        return price
    
    def get_ohlcv(self, exchange: Exchange, symbol: str, interval: str, limit: int) -> List[Dict]:
        """Get OHLCV data with caching"""
        cache_key = f"{exchange}:{symbol}:{interval}:{limit}"
        current_time = time()
        
        # Check cache
        if cache_key in self.ohlcv_cache:
            data, timestamp = self.ohlcv_cache[cache_key]
            if current_time - timestamp < self.OHLCV_TTL:
                return data
        
        # Fetch from exchange
        adapter = self._get_adapter(exchange)
        data = adapter.get_ohlcv(symbol, interval, limit)
        
        # Update cache
        self.ohlcv_cache[cache_key] = (data, current_time)
        
        return data

# Singleton instance
market_data_manager = MarketDataManager()
