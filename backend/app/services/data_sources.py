"""
Multi-source data provider for trading signals
Supports crypto, forex, stocks with automatic fallback
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

try:
    import aiohttp  # type: ignore

    _USE_AIOHTTP = True
except ImportError:  # pragma: no cover - environment dependent
    aiohttp = None
    _USE_AIOHTTP = False

try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover - environment dependent
    httpx = None

HTTP_CLIENT_AVAILABLE = _USE_AIOHTTP or httpx is not None

logger = logging.getLogger(__name__)

if not HTTP_CLIENT_AVAILABLE:
    logger.warning(
        "Neither aiohttp nor httpx is installed; real-time market data requests will fall back to mock data."
    )


async def _http_get_json(url: str, timeout: Optional[float] = None) -> Tuple[Optional[int], Optional[Any]]:
    """Fetch JSON from URL using mandatory http_client wrapper."""
    # Default timeout of 5 seconds if not specified
    if timeout is None:
        timeout = 5.0

    # Use mandatory http_client which enforces egress guard
    from app.utils.http_client import async_http_get
    return await async_http_get(url, timeout=timeout, calling_module="data_sources._http_get_json")

class DataSource:
    """Base class for data sources"""
    
    def __init__(self, name: str, priority: int = 1):
        self.name = name
        self.priority = priority
        self.is_available = True
        self.last_check = None
        self.response_time = 0
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for symbol"""
        raise NotImplementedError
    
    async def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        """Get OHLCV data for symbol"""
        raise NotImplementedError
    
    async def health_check(self) -> bool:
        """Check if data source is available"""
        raise NotImplementedError

class CryptoComSource(DataSource):
    """Crypto.com data source"""
    
    def __init__(self):
        super().__init__("crypto_com", priority=1)
        # Use Crypto.com Exchange API v1 endpoint (not the old v2)
        self.base_url = "https://api.crypto.com/exchange/v1"
    
    async def get_price(self, symbol: str) -> Optional[float]:
        if not HTTP_CLIENT_AVAILABLE:
            logger.debug("Crypto.com price request skipped: no HTTP client available.")
            return None

        # Crypto.com Exchange v1 API uses /public/get-tickers endpoint
        status, data = await _http_get_json(f"{self.base_url}/public/get-tickers")
        if status == 200 and data:
            try:
                # Find the ticker for our symbol
                tickers = data.get("result", {}).get("data", [])
                for ticker in tickers:
                    if ticker.get("i") == symbol:  # 'i' is the instrument_name field
                        return float(ticker.get("a", 0))  # 'a' is the ask price
            except Exception as exc:  # pragma: no cover - defensive parsing
                logger.error("Crypto.com price parse error: %s", exc)

        return None
    
    async def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        if not HTTP_CLIENT_AVAILABLE:
            logger.debug("Crypto.com OHLCV request skipped: no HTTP client available.")
            return []

        status, data = await _http_get_json(
            f"{self.base_url}/public/get-candlestick?instrument_name={symbol}&timeframe={interval}"
        )
        if status == 200 and data:
            try:
                return data["result"]["data"]
            except Exception as exc:  # pragma: no cover - defensive parsing
                logger.error("Crypto.com OHLCV parse error: %s", exc)

        return []
    
    async def health_check(self) -> bool:
        if not HTTP_CLIENT_AVAILABLE:
            self.is_available = False
            self.last_check = datetime.now()
            logger.debug("Crypto.com health check failed: no HTTP client available.")
            return False

        start_time = datetime.now()
        # Crypto.com Exchange v1 API uses /public/get-tickers endpoint
        status_code, data = await _http_get_json(
            f"{self.base_url}/public/get-tickers", timeout=5
        )
        self.response_time = (datetime.now() - start_time).total_seconds()
        # Check if we got valid data with tickers (don't store the data, just check if it exists)
        has_data = data and isinstance(data, dict) and data.get("result", {}).get("data")
        self.is_available = status_code == 200 and has_data
        self.last_check = datetime.now()
        if not self.is_available:
            logger.debug("Crypto.com health check failed with status %s", status_code)
        else:
            logger.debug(f"Crypto.com health check passed (response_time: {self.response_time:.2f}s)")
        return self.is_available

class BinanceSource(DataSource):
    """Binance data source"""
    
    def __init__(self):
        super().__init__("binance", priority=2)
        self.base_url = "https://api.binance.com/api/v3"
    
    async def get_price(self, symbol: str) -> Optional[float]:
        if not HTTP_CLIENT_AVAILABLE:
            logger.debug("Binance price request skipped: no HTTP client available.")
            return None

        binance_symbol = symbol.replace("_", "")
        status, data = await _http_get_json(f"{self.base_url}/ticker/price?symbol={binance_symbol}")
        if status == 200 and data:
            try:
                return float(data["price"])
            except Exception as exc:  # pragma: no cover - defensive parsing
                logger.error("Binance price parse error: %s", exc)
        return None
    
    async def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        if not HTTP_CLIENT_AVAILABLE:
            logger.debug("Binance OHLCV request skipped: no HTTP client available.")
            return []

        binance_symbol = symbol.replace("_", "")
        status, data = await _http_get_json(
            f"{self.base_url}/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
        )
        if status == 200 and data:
            try:
                return [
                    {
                        "t": kline[0],
                        "o": float(kline[1]),
                        "h": float(kline[2]),
                        "l": float(kline[3]),
                        "c": float(kline[4]),
                        "v": float(kline[5]),
                    }
                    for kline in data
                ]
            except Exception as exc:  # pragma: no cover - defensive parsing
                logger.error("Binance OHLCV parse error: %s", exc)
        return []
    
    async def health_check(self) -> bool:
        if not HTTP_CLIENT_AVAILABLE:
            self.is_available = False
            self.last_check = datetime.now()
            logger.debug("Binance health check failed: no HTTP client available.")
            return False

        start_time = datetime.now()
        status, _ = await _http_get_json(f"{self.base_url}/ping", timeout=5)
        self.response_time = (datetime.now() - start_time).total_seconds()
        self.is_available = status == 200
        self.last_check = datetime.now()
        if not self.is_available:
            logger.debug("Binance health check failed with status %s", status)
        return self.is_available

class MockSource(DataSource):
    """Mock data source for testing and fallback"""
    
    def __init__(self):
        super().__init__("mock", priority=999)  # Lowest priority
        self.is_available = True
    
    async def get_price(self, symbol: str) -> Optional[float]:
        # Generate realistic mock prices
        base_prices = {
            "BTC_USDT": 50000,
            "ETH_USDT": 3000,
            "SOL_USDT": 100,
            "BNB_USDT": 300,
            "XRP_USDT": 0.5,
        }
        base_price = base_prices.get(symbol, 100)
        # Add some random variation
        variation = random.uniform(0.95, 1.05)
        return base_price * variation
    
    async def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        # Generate mock OHLCV data
        base_prices = {
            "BTC_USDT": 50000,
            "ETH_USDT": 3000,
            "SOL_USDT": 100,
            "BNB_USDT": 300,
            "XRP_USDT": 0.5,
        }
        base_price = base_prices.get(symbol, 100)
        current_time = int(datetime.now().timestamp() * 1000)
        
        ohlcv_data = []
        price = base_price
        
        for i in range(limit):
            # Generate realistic price movement
            change_pct = random.uniform(-0.05, 0.05)  # ±5% change
            price = price * (1 + change_pct)
            
            # Generate OHLC from price
            high = price * random.uniform(1.0, 1.02)
            low = price * random.uniform(0.98, 1.0)
            open_price = price * random.uniform(0.99, 1.01)
            close_price = price
            
            # Generate volume
            volume = random.uniform(1000, 10000)
            
            ohlcv_data.append({
                "t": current_time - (limit - i) * 3600000,  # 1 hour intervals
                "o": round(open_price, 2),
                "h": round(high, 2),
                "l": round(low, 2),
                "c": round(close_price, 2),
                "v": round(volume, 2)
            })
            
            price = close_price
        
        return ohlcv_data
    
    async def health_check(self) -> bool:
        self.is_available = True
        self.last_check = datetime.now()
        return True

class DataSourceManager:
    """Manages multiple data sources with automatic fallback"""
    
    def __init__(self):
        self.sources = [
            CryptoComSource(),
            BinanceSource(),
            MockSource()  # Always available as fallback
        ]
        self.current_source = None
        self.last_health_check = None
    
    async def get_best_source(self) -> DataSource:
        """Get the best available data source"""
        if self.current_source and self.current_source.is_available:
            return self.current_source
        
        # Check all sources and pick the best one
        available_sources = []
        for source in self.sources:
            if await source.health_check():
                available_sources.append(source)
        
        if available_sources:
            # Sort by priority (lower number = higher priority) and response time
            available_sources.sort(key=lambda x: (x.priority, x.response_time))
            self.current_source = available_sources[0]
            return self.current_source
        
        # Fallback to mock source
        self.current_source = MockSource()
        return self.current_source
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """Get price from the best available source"""
        source = await self.get_best_source()
        return await source.get_price(symbol)
    
    async def get_ohlcv(self, symbol: str, interval: str = "1h", limit: int = 200) -> List[Dict]:
        """Get OHLCV data from the best available source"""
        source = await self.get_best_source()
        return await source.get_ohlcv(symbol, interval, limit)
    
    async def get_source_status(self) -> Dict[str, Any]:
        """Get status of all data sources - with caching and parallel checks"""
        import asyncio
        from datetime import timedelta
        
        # Use cached status if available and fresh (less than 30 seconds old)
        now = datetime.now()
        if self.last_health_check and (now - self.last_health_check) < timedelta(seconds=30):
            # Return cached status from source objects
            status = {}
            name_mapping = {
                "crypto_com": "crypto_com",
                "binance": "binance",
                "mock": None
            }
            for source in self.sources:
                frontend_name = name_mapping.get(source.name)
                if frontend_name:
                    status[frontend_name] = {
                        "available": source.is_available,
                        "priority": source.priority,
                        "response_time": source.response_time if source.response_time else None,
                        "last_check": source.last_check.isoformat() if source.last_check else None
                    }
            
            # Add placeholders for expected sources
            expected_sources = ["binance", "kraken", "crypto_com", "coinpaprika"]
            for expected_name in expected_sources:
                if expected_name not in status:
                    status[expected_name] = {
                        "available": False,
                        "priority": 999,
                        "response_time": None,
                        "last_check": None
                    }
            
            return status
        
        # Run health checks in parallel with timeout
        status = {}
        name_mapping = {
            "crypto_com": "crypto_com",
            "binance": "binance",
            "mock": None
        }
        
        # Run health checks in parallel with a max timeout of 10 seconds total
        async def check_source(source):
            try:
                # Run health check with individual timeout
                await asyncio.wait_for(source.health_check(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"Health check timeout for {source.name}")
                source.is_available = False
                source.last_check = datetime.now()
            except Exception as e:
                logger.warning(f"Health check error for {source.name}: {e}")
                source.is_available = False
                source.last_check = datetime.now()
        
        # Run all health checks in parallel
        health_check_tasks = [
            check_source(source) 
            for source in self.sources 
            if name_mapping.get(source.name) is not None
        ]
        
        if health_check_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*health_check_tasks, return_exceptions=True),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("Health checks timed out - using cached status")
        
        # Build status response
        for source in self.sources:
            frontend_name = name_mapping.get(source.name)
            if frontend_name:
                status[frontend_name] = {
                    "available": source.is_available,
                    "priority": source.priority,
                    "response_time": source.response_time if source.response_time else None,
                    "last_check": source.last_check.isoformat() if source.last_check else None
                }
        
        # Add placeholder entries for sources the frontend expects but we don't have
        expected_sources = ["binance", "kraken", "crypto_com", "coinpaprika"]
        for expected_name in expected_sources:
            if expected_name not in status:
                status[expected_name] = {
                    "available": False,
                    "priority": 999,
                    "response_time": None,
                    "last_check": None
                }
        
        # Update cache timestamp
        self.last_health_check = now
        
        return status

# Global instance
data_manager = DataSourceManager()
