"""
Mock Price Fetcher - Realistic Mock Prices
Provides stable, realistic mock prices to avoid API rate limits
"""

import time
import logging
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class PriceResult:
    price: float
    source: str
    timestamp: float
    success: bool
    error: Optional[str] = None

class MockPriceFetcher:
    def __init__(self):
        self.cache = {}
        self.cache_duration = 300  # 5 minutes cache
        
        # Realistic base prices (as of late 2024)
        self.base_prices = {
            "BTC_USDT": 113000.0,
            "ETH_USDT": 4080.0,
            "SOL_USDT": 199.0,
            "BNB_USDT": 580.0,
            "XRP_USDT": 0.62,
            "ADA_USDT": 0.45,
            "DOGE_USDT": 0.08,
            "DOT_USDT": 6.80,
            "LINK_USDT": 18.50,
            "MATIC_USDT": 0.85,
            "AVAX_USDT": 35.20,
            "ALGO_USDT": 0.15,
            "UNI_USDT": 12.30,
            "ATOM_USDT": 8.90,
            "ETC_USDT": 25.40,
            "LTC_USDT": 85.60,
            "BCH_USDT": 420.0,
            "XLM_USDT": 0.12,
            "FIL_USDT": 5.20,
            "TRX_USDT": 0.11,
            "BTC_USD": 113000.0
        }
    
    def _is_cache_valid(self, symbol: str) -> bool:
        """Check if cached data is still valid"""
        if symbol not in self.cache:
            return False
        return time.time() - self.cache[symbol]['timestamp'] < self.cache_duration
    
    def _get_cached_price(self, symbol: str) -> Optional[PriceResult]:
        """Get price from cache if valid"""
        if self._is_cache_valid(symbol):
            cached = self.cache[symbol]
            return PriceResult(
                price=cached['price'],
                source=f"cached_{cached['source']}",
                timestamp=cached['timestamp'],
                success=True
            )
        return None
    
    def _cache_price(self, symbol: str, price: float, source: str):
        """Cache the price result"""
        self.cache[symbol] = {
            'price': price,
            'source': source,
            'timestamp': time.time()
        }
    
    def _generate_realistic_price(self, symbol: str) -> float:
        """Generate a realistic price with small variations"""
        base_price = self.base_prices.get(symbol, 1.0)
        
        # Add small random variation (±2%)
        import random
        variation = random.uniform(-0.02, 0.02)
        current_price = base_price * (1 + variation)
        
        # Round to appropriate decimal places
        if current_price >= 100:
            return round(current_price, 2)
        elif current_price >= 1:
            return round(current_price, 4)
        else:
            return round(current_price, 6)
    
    def get_price(self, symbol: str) -> PriceResult:
        """Get realistic mock price"""
        # Check cache first
        cached_result = self._get_cached_price(symbol)
        if cached_result:
            return cached_result
        
        # Generate realistic price
        price = self._generate_realistic_price(symbol)
        self._cache_price(symbol, price, "mock")
        
        logger.info(f"💰 Mock price for {symbol}: ${price}")
        return PriceResult(
            price=price,
            source="mock",
            timestamp=time.time(),
            success=True
        )
    
    def get_multiple_prices(self, symbols: list) -> Dict[str, PriceResult]:
        """Get prices for multiple symbols"""
        results = {}
        
        for symbol in symbols:
            results[symbol] = self.get_price(symbol)
        
        return results

# Global instance
mock_price_fetcher = MockPriceFetcher()

