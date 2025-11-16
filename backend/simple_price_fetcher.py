"""
Dynamic Price Fetcher with automatic provider rotation
Automatically switches between Crypto.com, CoinPaprika, and CoinGecko when rate limits are detected
"""

import requests
import time
import logging
import threading
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class PriceResult:
    price: float
    source: str
    timestamp: float
    success: bool
    error: Optional[str] = None

@dataclass
class ProviderStatus:
    """Track provider health and rate limit status"""
    name: str
    rate_limited_until: float = 0  # Timestamp when rate limit expires
    consecutive_failures: int = 0  # Track consecutive failures
    last_success: float = 0  # Timestamp of last successful request
    total_requests: int = 0
    successful_requests: int = 0

class SimplePriceFetcher:
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60  # 1 minute cache (reduced from 5 minutes for faster price updates)
        self.request_timeout = 3  # Reduced to 3 seconds for faster timeout
        self.lock = threading.Lock()  # Thread-safe operations
        # Cache for Crypto.com ticker list (shared across symbols)
        self._crypto_com_tickers_cache = None
        self._crypto_com_tickers_cache_time = 0
        self._crypto_com_tickers_cache_duration = 30  # 30 seconds cache for ticker list
        
        # Provider priority order - Crypto.com is ALWAYS first (the exchange we trade on)
        # Only falls back to others if Crypto.com is rate limited or unavailable
        self.providers = ["crypto_com", "coinpaprika", "coingecko"]
        
        # Track provider status
        self.provider_status: Dict[str, ProviderStatus] = {
            "crypto_com": ProviderStatus(name="crypto_com"),
            "coinpaprika": ProviderStatus(name="coinpaprika"),
            "coingecko": ProviderStatus(name="coingecko")
        }
        
        # Rate limit cooldown periods (seconds)
        self.rate_limit_cooldowns = {
            "crypto_com": 60,      # 1 minute cooldown
            "coinpaprika": 300,    # 5 minutes cooldown (strict limits)
            "coingecko": 120       # 2 minutes cooldown
        }
        
        # Symbol mappings for CoinPaprika and CoinGecko
        self.symbol_mappings_paprika = {
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
            "BTC_USD": "btc-bitcoin",
            "LDO_USDT": "ldo-lido-dao",
            "LDO_USD": "ldo-lido-dao"
        }
        
        self.symbol_mappings_gecko = {
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
            "BTC_USD": "bitcoin",
            "LDO_USDT": "lido-dao",
            "LDO_USD": "lido-dao"
        }
    
    def _is_provider_available(self, provider: str) -> bool:
        """Check if provider is available (not rate limited)"""
        with self.lock:
            status = self.provider_status.get(provider)
            if not status:
                return False
            return time.time() >= status.rate_limited_until
    
    def _mark_provider_rate_limited(self, provider: str):
        """Mark a provider as rate limited"""
        with self.lock:
            status = self.provider_status.get(provider)
            if status:
                cooldown = self.rate_limit_cooldowns.get(provider, 60)
                status.rate_limited_until = time.time() + cooldown
                status.consecutive_failures += 1
                logger.warning(f"🚫 Provider {provider} rate limited. Cooldown: {cooldown}s")
    
    def _mark_provider_success(self, provider: str):
        """Mark a provider request as successful"""
        with self.lock:
            status = self.provider_status.get(provider)
            if status:
                status.last_success = time.time()
                status.consecutive_failures = 0
                status.total_requests += 1
                status.successful_requests += 1
    
    def _mark_provider_failure(self, provider: str, is_rate_limit: bool = False):
        """Mark a provider request as failed"""
        with self.lock:
            status = self.provider_status.get(provider)
            if status:
                status.total_requests += 1
                if is_rate_limit:
                    self._mark_provider_rate_limited(provider)
                else:
                    status.consecutive_failures += 1
    
    def _get_available_providers(self) -> List[str]:
        """Get list of available providers in priority order"""
        available = []
        now = time.time()
        
        with self.lock:
            for provider in self.providers:
                status = self.provider_status.get(provider)
                if status and now >= status.rate_limited_until:
                    available.append(provider)
        
        return available if available else self.providers  # If all rate limited, try all anyway
    
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
    
    def _get_crypto_com_tickers(self) -> Optional[list]:
        """Get Crypto.com tickers with caching to avoid repeated API calls"""
        now = time.time()
        
        # Check if we have a recent cache
        with self.lock:
            if (self._crypto_com_tickers_cache and 
                now - self._crypto_com_tickers_cache_time < self._crypto_com_tickers_cache_duration):
                return self._crypto_com_tickers_cache
        
        # Fetch fresh tickers
        try:
            url = f"https://api.crypto.com/exchange/v1/public/get-tickers"
            response = requests.get(
                url,
                timeout=self.request_timeout,
                headers={'User-Agent': 'TradingBot/1.0'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data and "data" in data["result"]:
                    tickers = data["result"]["data"]
                    # Cache the tickers
                    with self.lock:
                        self._crypto_com_tickers_cache = tickers
                        self._crypto_com_tickers_cache_time = now
                    return tickers
            elif response.status_code == 429:
                self._mark_provider_failure("crypto_com", is_rate_limit=True)
                return None
            else:
                self._mark_provider_failure("crypto_com")
                return None
                
        except Exception as e:
            logger.warning(f"Crypto.com API error fetching tickers: {e}")
            self._mark_provider_failure("crypto_com")
            return None
    
    def _fetch_from_crypto_com(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from Crypto.com using cached ticker list"""
        tickers = self._get_crypto_com_tickers()
        if not tickers:
            return None
        
        # Search for our symbol in the cached tickers
        for ticker in tickers:
            instrument_name = ticker.get("i", "")
            if instrument_name == symbol:
                ask_price = float(ticker.get("a", 0))
                bid_price = float(ticker.get("b", 0))
                price = ask_price if ask_price > 0 else bid_price
                
                if price > 0:
                    self._mark_provider_success("crypto_com")
                    return PriceResult(
                        price=price,
                        source="crypto_com",
                    timestamp=time.time(),
                        success=True
                    )
        
        # Symbol not found in tickers
        return None
    
    def _fetch_from_coinpaprika(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from CoinPaprika"""
        paprika_id = self.symbol_mappings_paprika.get(symbol)
        if not paprika_id:
            return None
        
        try:
            url = f"https://api.coinpaprika.com/v1/tickers/{paprika_id}"
            response = requests.get(
                url, 
                timeout=self.request_timeout,
                headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if "quotes" in data and "USD" in data["quotes"]:
                    price = data["quotes"]["USD"]["price"]
                    self._mark_provider_success("coinpaprika")
                    return PriceResult(
                        price=price,
                        source="coinpaprika",
                        timestamp=time.time(),
                        success=True
                    )
                return None
            elif response.status_code == 429:
                self._mark_provider_failure("coinpaprika", is_rate_limit=True)
                return None
            else:
                self._mark_provider_failure("coinpaprika")
                return None
                
        except Exception as e:
            logger.warning(f"CoinPaprika API error for {symbol}: {e}")
            self._mark_provider_failure("coinpaprika")
            return None
    
    def _fetch_from_coingecko(self, symbol: str) -> Optional[PriceResult]:
        """Fetch price from CoinGecko"""
        gecko_id = self.symbol_mappings_gecko.get(symbol)
        if not gecko_id:
            return None
        
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={gecko_id}&vs_currencies=usd"
            response = requests.get(url, timeout=self.request_timeout)
            
            if response.status_code == 200:
                data = response.json()
                if gecko_id in data and "usd" in data[gecko_id]:
                    price = data[gecko_id]["usd"]
                    self._mark_provider_success("coingecko")
                    return PriceResult(
                        price=price,
                        source="coingecko",
                        timestamp=time.time(),
                        success=True
                    )
            elif response.status_code == 429:
                self._mark_provider_failure("coingecko", is_rate_limit=True)
                return None
            else:
                self._mark_provider_failure("coingecko")
                return None
                
        except Exception as e:
            logger.warning(f"CoinGecko API error for {symbol}: {e}")
            self._mark_provider_failure("coingecko")
            return None
    
    def get_price(self, symbol: str) -> PriceResult:
        """Get price using dynamic provider rotation - Crypto.com is ALWAYS tried first"""
        # Check cache first
        cached_result = self._get_cached_price(symbol)
        if cached_result:
            return cached_result
        
        # Map provider names to fetch functions
        fetch_functions = {
            "crypto_com": self._fetch_from_crypto_com,
            "coinpaprika": self._fetch_from_coinpaprika,
            "coingecko": self._fetch_from_coingecko
        }
        
        # ALWAYS try Crypto.com first (the exchange we trade on)
        # Only skip it if it's currently rate-limited
        primary_provider = "crypto_com"
        
        if self._is_provider_available(primary_provider):
            logger.info(f"🌐 Trying {primary_provider} for {symbol} (primary provider)...")
            fetch_func = fetch_functions.get(primary_provider)
            if fetch_func:
                result = fetch_func(symbol)
                if result and result.success:
                    self._cache_price(symbol, result.price, result.source)
                    logger.info(f"✅ Got price for {symbol}: ${result.price} from {primary_provider}")
                    return result
                else:
                    logger.debug(f"⚠️ {primary_provider} failed for {symbol}, trying backup providers...")
        else:
            logger.debug(f"⏸️ {primary_provider} rate limited, using backup providers...")

        # If Crypto.com fails or is rate-limited, try backup providers
        backup_providers = [p for p in self.providers if p != primary_provider]
        available_backups = self._get_available_providers()
        backup_providers = [p for p in backup_providers if p in available_backups]
        
        for provider in backup_providers:
            if not self._is_provider_available(provider):
                logger.debug(f"⏸️ Skipping {provider} (rate limited)")
                continue
            
            logger.info(f"🔄 Trying {provider} for {symbol} (backup)...")
            fetch_func = fetch_functions.get(provider)
            if not fetch_func:
                continue
            
            result = fetch_func(symbol)
            if result and result.success:
                self._cache_price(symbol, result.price, result.source)
                logger.info(f"✅ Got price for {symbol}: ${result.price} from {provider} (backup)")
                return result
            else:
                logger.debug(f"⚠️ {provider} failed for {symbol}, trying next backup...")
        
        # All providers failed - log status
        with self.lock:
            status_summary = []
            for provider in self.providers:
                status = self.provider_status.get(provider)
                if status:
                    rate_limited = time.time() < status.rate_limited_until
                    status_summary.append(f"{provider}: {'🚫 rate limited' if rate_limited else '❌ unavailable'}")
        
        logger.error(f"❌ All providers failed for {symbol}. Status: {', '.join(status_summary)}")
        
        return PriceResult(
            price=0.0,
            source="error",
            timestamp=time.time(),
            success=False,
            error=f"All providers failed: {', '.join(status_summary)}"
        )
    
    def get_provider_stats(self) -> Dict[str, Dict]:
        """Get statistics about provider usage"""
        with self.lock:
            stats = {}
            for provider, status in self.provider_status.items():
                now = time.time()
                stats[provider] = {
                    "rate_limited": now < status.rate_limited_until,
                    "rate_limited_until": status.rate_limited_until,
                    "consecutive_failures": status.consecutive_failures,
                    "total_requests": status.total_requests,
                    "successful_requests": status.successful_requests,
                    "success_rate": (status.successful_requests / status.total_requests * 100) if status.total_requests > 0 else 0,
                    "last_success": status.last_success
        }
            return stats
    
    def get_multiple_prices(self, symbols: list) -> Dict[str, PriceResult]:
        """Get prices for multiple symbols using parallel processing with timeout"""
        import concurrent.futures
        
        results = {}
        
        def fetch_single_price(symbol):
            return symbol, self.get_price(symbol)
        
        # Use ThreadPoolExecutor for parallel requests with timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_symbol = {
                executor.submit(fetch_single_price, symbol): symbol 
                for symbol in symbols
            }
            
            # Collect results as they complete with 3-second timeout (increased from 2s)
            try:
                for future in concurrent.futures.as_completed(future_to_symbol, timeout=3):
                    try:
                        symbol, result = future.result(timeout=0.3)  # Individual result timeout
                        results[symbol] = result
                    except Exception as e:
                        symbol = future_to_symbol.get(future, "unknown")
                        logger.warning(f"Error fetching price for {symbol}: {e}")
                        results[symbol] = PriceResult(
                            price=0.0,
                            source="error",
                            timestamp=time.time(),
                            success=False,
                            error=str(e)
                        )
            except concurrent.futures.TimeoutError:
                # Timeout occurred - return partial results
                logger.warning(f"Price fetch timeout after 3 seconds. Returning {len(results)}/{len(symbols)} prices")
                # Mark remaining symbols as timeout
                for future, symbol in future_to_symbol.items():
                    if symbol not in results:
                        results[symbol] = PriceResult(
                            price=0.0,
                            source="timeout",
                            timestamp=time.time(),
                            success=False,
                            error="Fetch timeout"
                        )
        
        return results

# Global instance
price_fetcher = SimplePriceFetcher()
