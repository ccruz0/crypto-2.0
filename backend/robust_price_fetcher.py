"""
Robust Price Fetcher with Multiple Fallback Sources
Supports CoinPaprika, CoinGecko, Binance, and Crypto.com with automatic fallback
"""

import requests
import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random

logger = logging.getLogger(__name__)

@dataclass
class PriceResult:
    price: float
    source: str
    timestamp: float
    success: bool
    error: Optional[str] = None

class RobustPriceFetcher:
    def __init__(self):
        self.cache = {}
        self.cache_duration = 30  # 30 seconds cache
        self.request_timeout = 10
        self.max_retries = 2
        self.rate_limit_delay = 0.1  # Base delay between requests
        self.last_request_time = 0
        
        # Create session with connection pooling and retry logic
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            backoff_factor=1,
            raise_on_status=False
        )
        
        # Mount adapters with retry strategy
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=20,
            pool_block=False
        )
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers to look like a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        # Symbol mappings for different APIs
        self.symbol_mappings = {
            'coinpaprika': {
                "BTC_USDT": "btc-bitcoin",
                "ETH_USDT": "eth-ethereum",
                "SOL_USDT": "sol-solana",
                "BNB_USDT": "bnb-binancecoin",
                "XRP_USDT": "xrp-xrp",
                "ADA_USDT": "ada-cardano",
                "DOGE_USDT": "doge-dogecoin",
                "DOT_USDT": "dot-polkadot",
                "LINK_USDT": "link-chainlink",
                "MATIC_USDT": "matic-polygon",
                "AVAX_USDT": "avax-avalanche",
                "ALGO_USDT": "algo-algorand",
                "UNI_USDT": "uni-uniswap",
                "ATOM_USDT": "atom-cosmos",
                "ETC_USDT": "etc-ethereum-classic",
                "LTC_USDT": "ltc-litecoin",
                "BCH_USDT": "bch-bitcoin-cash",
                "XLM_USDT": "xlm-stellar",
                "FIL_USDT": "fil-filecoin",
                "TRX_USDT": "trx-tron",
                "BTC_USD": "btc-bitcoin"
            },
            'coingecko': {
                "BTC_USDT": "bitcoin",
                "ETH_USDT": "ethereum",
                "SOL_USDT": "solana",
                "BNB_USDT": "binancecoin",
                "XRP_USDT": "ripple",
                "ADA_USDT": "cardano",
                "DOGE_USDT": "dogecoin",
                "DOT_USDT": "polkadot",
                "LINK_USDT": "chainlink",
                "MATIC_USDT": "matic-network",
                "AVAX_USDT": "avalanche-2",
                "ALGO_USDT": "algorand",
                "UNI_USDT": "uniswap",
                "ATOM_USDT": "cosmos",
                "ETC_USDT": "ethereum-classic",
                "LTC_USDT": "litecoin",
                "BCH_USDT": "bitcoin-cash",
                "XLM_USDT": "stellar",
                "FIL_USDT": "filecoin",
                "TRX_USDT": "tron",
                "BTC_USD": "bitcoin"
            },
            'binance': {
                "BTC_USDT": "BTCUSDT",
                "ETH_USDT": "ETHUSDT",
                "SOL_USDT": "SOLUSDT",
                "BNB_USDT": "BNBUSDT",
                "XRP_USDT": "XRPUSDT",
                "ADA_USDT": "ADAUSDT",
                "DOGE_USDT": "DOGEUSDT",
                "DOT_USDT": "DOTUSDT",
                "LINK_USDT": "LINKUSDT",
                "MATIC_USDT": "MATICUSDT",
                "AVAX_USDT": "AVAXUSDT",
                "ALGO_USDT": "ALGOUSDT",
                "UNI_USDT": "UNIUSDT",
                "ATOM_USDT": "ATOMUSDT",
                "ETC_USDT": "ETCUSDT",
                "LTC_USDT": "LTCUSDT",
                "BCH_USDT": "BCHUSDT",
                "XLM_USDT": "XLMUSDT",
                "FIL_USDT": "FILUSDT",
                "TRX_USDT": "TRXUSDT",
                "BTC_USD": "BTCUSDT"
            }
        }
    
    def _rate_limit_delay(self):
        """Add delay between requests to avoid rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
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
    
    def _fetch_coinpaprika(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from CoinPaprika API"""
        try:
            paprika_id = self.symbol_mappings['coinpaprika'].get(symbol)
            if not paprika_id:
                return None
            
            self._rate_limit_delay()
            url = f"https://api.coinpaprika.com/v1/tickers/{paprika_id}"
            response = self.session.get(url, timeout=self.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                if "quotes" in data and "USD" in data["quotes"]:
                    price = data["quotes"]["USD"]["price"]
                    return PriceResult(
                        price=price,
                        source="coinpaprika",
                        timestamp=time.time(),
                        success=True
                    )
            elif response.status_code == 429:
                logger.warning(f"CoinPaprika rate limited for {symbol}, waiting...")
                time.sleep(1)  # Wait for rate limit
        except Exception as e:
            logger.warning(f"CoinPaprika API failed for {symbol}: {e}")
        return None
    
    def _fetch_coingecko(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from CoinGecko API"""
        try:
            gecko_id = self.symbol_mappings['coingecko'].get(symbol)
            if not gecko_id:
                return None
            
            self._rate_limit_delay()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd"
            response = self.session.get(url, timeout=self.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                if gecko_id in data and "usd" in data[gecko_id]:
                    price = data[gecko_id]["usd"]
                    return PriceResult(
                        price=price,
                        source="coingecko",
                        timestamp=time.time(),
                        success=True
                    )
            elif response.status_code == 429:
                logger.warning(f"CoinGecko rate limited for {symbol}, waiting...")
                time.sleep(2)  # CoinGecko has stricter rate limits
        except Exception as e:
            logger.warning(f"CoinGecko API failed for {symbol}: {e}")
        return None
    
    def _fetch_binance(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from Binance API"""
        try:
            binance_symbol = self.symbol_mappings['binance'].get(symbol)
            if not binance_symbol:
                return None
            
            self._rate_limit_delay()
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"
            response = self.session.get(url, timeout=self.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                if "price" in data:
                    price = float(data["price"])
                    return PriceResult(
                        price=price,
                        source="binance",
                        timestamp=time.time(),
                        success=True
                    )
            elif response.status_code == 429:
                logger.warning(f"Binance rate limited for {symbol}, waiting...")
                time.sleep(1)
        except Exception as e:
            logger.warning(f"Binance API failed for {symbol}: {e}")
        return None
    
    def _fetch_crypto_com(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from Crypto.com API"""
        try:
            # Convert symbol format for Crypto.com
            crypto_symbol = symbol.replace("_USDT", "_USD").replace("_USD", "_USD")
            
            self._rate_limit_delay()
            url = f"https://api.crypto.com/v2/public/get-ticker?instrument_name={crypto_symbol}"
            response = self.session.get(url, timeout=self.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data and "data" in data["result"] and data["result"]["data"]:
                    ticker_data = data["result"]["data"]
                    if "a" in ticker_data:  # 'a' is the ask price
                        price = float(ticker_data["a"])
                        return PriceResult(
                            price=price,
                            source="crypto_com",
                            timestamp=time.time(),
                            success=True
                        )
            elif response.status_code == 429:
                logger.warning(f"Crypto.com rate limited for {symbol}, waiting...")
                time.sleep(3)
        except Exception as e:
            logger.warning(f"Crypto.com API failed for {symbol}: {e}")
        return None
    
    def get_price(self, symbol: str) -> PriceResult:
        """
        Get price with automatic fallback through multiple sources
        Priority: CoinPaprika -> CoinGecko -> Binance -> Crypto.com
        """
        # Check cache first
        cached_result = self._get_cached_price(symbol)
        if cached_result:
            return cached_result
        
        # Define fallback sources in order of preference
        sources = [
            ("coinpaprika", self._fetch_coinpaprika),
            ("coingecko", self._fetch_coingecko),
            ("binance", self._fetch_binance),
            ("crypto_com", self._fetch_crypto_com)
        ]
        
        last_error = None
        
        for source_name, fetch_func in sources:
            try:
                result = fetch_func(symbol)
                if result and result.success:
                    # Cache successful result
                    self._cache_price(symbol, result.price, result.source)
                    logger.info(f"✅ Got price for {symbol}: ${result.price} from {result.source}")
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"❌ {source_name} failed for {symbol}: {e}")
                continue
        
        # If all sources failed, return error result
        error_msg = f"All price sources failed for {symbol}"
        if last_error:
            error_msg += f". Last error: {last_error}"
        
        logger.error(error_msg)
        return PriceResult(
            price=1.0,  # Fallback price
            source="fallback",
            timestamp=time.time(),
            success=False,
            error=error_msg
        )
    
    def get_multiple_prices(self, symbols: list) -> Dict[str, PriceResult]:
        """Get prices for multiple symbols efficiently"""
        results = {}
        
        # Process symbols in smaller batches to avoid overwhelming APIs
        batch_size = 5
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            for symbol in batch:
                results[symbol] = self.get_price(symbol)
                # Shorter delay between requests
                time.sleep(0.1)
            
            # Shorter delay between batches
            if i + batch_size < len(symbols):
                time.sleep(0.5)
        
        return results

# Global instance
price_fetcher = RobustPriceFetcher()
