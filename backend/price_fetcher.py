"""
Multi-source price fetcher with automatic fallback
Supports Crypto.com, Binance, Kraken, and CoinPaprika APIs
"""

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
import time
import logging
import sys
import os
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add the backend directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PriceFetcher:
    """Multi-source price fetcher with automatic fallback"""
    
    def __init__(self):
        self.timeout = 5
        self.cache_duration = 30  # seconds
        self.stale_cache_duration = 180  # seconds
        self.cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.cache_lock = threading.Lock()
        self.last_request_ts = 0.0
        self.min_delay = 0.3
        self.rate_limit_backoff = 2.0
        self.provider_retries = 2
        self.retry_backoff = 1.0

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TradingBot/1.0'
        })
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
            backoff_factor=1,
            raise_on_status=False,
            respect_retry_after_header=True
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=50
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.coinpaprika_symbol_cache: Dict[str, str] = {}
        self.coinpaprika_overrides: Dict[str, str] = {
            "ldo": "ldo-lido-dao",
            "wif": "wif-dogwifcoin",
            "bonk": "bonk-bonk",
            "apt": "apt-aptos",
            "sui": "sui-sui",
        }
    
    def _get_cache_key(self, symbol: str, timeframe: str) -> Tuple[str, str]:
        return symbol.upper(), timeframe.lower()
    
    def _get_cached_result(self, key: Tuple[str, str], allow_stale: bool = False) -> Optional[Dict[str, Any]]:
        with self.cache_lock:
            entry = self.cache.get(key)
        if not entry:
            return None
        age = time.time() - entry["timestamp"]
        if age <= self.cache_duration:
            return entry["data"]
        if allow_stale and age <= self.cache_duration + self.stale_cache_duration:
            logger.warning(
                "Using stale cached data for %s/%s (age %.1fs)",
                key[0],
                key[1],
                age,
            )
            return entry["data"]
        if age > self.cache_duration + self.stale_cache_duration:
            with self.cache_lock:
                self.cache.pop(key, None)
        return None
    
    def _cache_result(self, key: Tuple[str, str], data: Dict[str, Any]):
        with self.cache_lock:
            self.cache[key] = {
                "data": data,
                "timestamp": time.time()
            }
    
    def _rate_limit_delay(self):
        now = time.time()
        elapsed = now - self.last_request_ts
        if elapsed < self.min_delay:
            time.sleep(self.min_delay - elapsed)
        self.last_request_ts = time.time()
    
    def _perform_request(self, url: str) -> Optional[requests.Response]:
        for attempt in range(self.provider_retries + 1):
            try:
                self._rate_limit_delay()
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 429:
                    wait_time = self.rate_limit_backoff * (attempt + 1)
                    logger.warning("Rate limited for %s, backing off %.1fs", url, wait_time)
                    time.sleep(wait_time)
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                wait_time = self.retry_backoff * (attempt + 1)
                logger.warning("Request error for %s: %s (retry in %.1fs)", url, exc, wait_time)
                time.sleep(wait_time)
        return None
    
    def _fetch_json(self, url: str) -> Optional[Any]:
        response = self._perform_request(url)
        if not response:
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning("Invalid JSON response from %s: %s", url, exc)
            return None
    
    def normalize_symbol(self, symbol: str, provider: str) -> str:
        """Normalize symbol format for different providers"""
        if provider == "crypto_com":
            return symbol.replace("_", "_")
        elif provider == "binance":
            # Convert BTC_USD to BTCUSDT, ETH_USD to ETHUSDT, etc.
            if symbol.endswith("_USD"):
                return symbol.replace("_USD", "USDT")
            return symbol.replace("_", "")
        elif provider == "kraken":
            return symbol.replace("_", "/")
        elif provider == "coinpaprika":
            return symbol.replace("_", "-")
        return symbol
    
    def get_crypto_com(self, symbol: str, timeframe: str = "15m") -> Optional[Dict[str, Any]]:
        """Fetch data from Crypto.com Exchange API"""
        try:
            normalized_symbol = self.normalize_symbol(symbol, "crypto_com")
            
            # Get ticker data
            ticker_url = f"https://api.crypto.com/v2/public/get-ticker?instrument_name={normalized_symbol}"
            ticker_data = self._fetch_json(ticker_url)
            ticker_payload = ticker_data.get('result', {}).get('data') if ticker_data else None
            
            if isinstance(ticker_payload, dict) and ticker_payload.get('a'):
                current_price = float(ticker_payload['a'])  # Ask price
                
                # Get OHLCV data
                ohlcv_url = f"https://api.crypto.com/v2/public/get-candlestick?instrument_name={normalized_symbol}&timeframe={timeframe}"
                ohlcv_data = self._fetch_json(ohlcv_url)
                
                if ohlcv_data and ohlcv_data.get('result', {}).get('data'):
                    df = self._process_ohlcv_data(ohlcv_data['result']['data'], current_price)
                    return self._calculate_indicators(df, symbol, "crypto_com")
                    
        except Exception as e:
            logger.warning(f"Crypto.com API failed for {symbol}: {e}")
            return None
    
    def get_binance(self, symbol: str, timeframe: str = "15m") -> Optional[Dict[str, Any]]:
        """Fetch data from Binance Spot API"""
        try:
            normalized_symbol = self.normalize_symbol(symbol, "binance")
            
            # Map timeframe
            interval_map = {
                "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
                "1h": "1h", "4h": "4h", "1d": "1d"
            }
            interval = interval_map.get(timeframe, "15m")
            
            # Get klines data
            klines_url = f"https://api.binance.com/api/v3/klines?symbol={normalized_symbol}&interval={interval}&limit=200"
            klines_data = self._fetch_json(klines_url)
            
            if klines_data:
                df = self._process_binance_klines(klines_data)
                current_price = df['close'].iloc[-1]
                return self._calculate_indicators(df, symbol, "binance")
                
        except Exception as e:
            logger.warning(f"Binance API failed for {symbol}: {e}")
            return None
    
    def get_kraken(self, symbol: str, timeframe: str = "15m") -> Optional[Dict[str, Any]]:
        """Fetch data from Kraken API"""
        try:
            normalized_symbol = self.normalize_symbol(symbol, "kraken")
            
            # Get ticker data
            ticker_url = f"https://api.kraken.com/0/public/Ticker?pair={normalized_symbol}"
            ticker_data = self._fetch_json(ticker_url)
            
            if ticker_data and ticker_data.get('result'):
                # Get the first (and usually only) pair data
                pair_data = list(ticker_data['result'].values())[0]
                current_price = float(pair_data['c'][0])  # Last trade closed price
                
                # Get OHLC data
                ohlc_url = f"https://api.kraken.com/0/public/OHLC?pair={normalized_symbol}&interval=15"
                ohlc_data = self._fetch_json(ohlc_url)
                
                if ohlc_data and ohlc_data.get('result'):
                    result_map = ohlc_data['result']
                    # Kraken responds with specific pair codes, fall back to first entry if direct lookup fails
                    series = result_map.get(normalized_symbol)
                    if series is None and result_map:
                        series = next(iter(result_map.values()))
                    if series:
                        df = self._process_kraken_ohlc(series)
                    return self._calculate_indicators(df, symbol, "kraken")
                    
        except Exception as e:
            logger.warning(f"Kraken API failed for {symbol}: {e}")
            return None
    
    def get_coinpaprika(self, symbol: str, timeframe: str = "15m") -> Optional[Dict[str, Any]]:
        """Fetch data from CoinPaprika API"""
        try:
            # CoinPaprika uses different symbol format
            base_symbol = symbol.split('_')[0].lower()
            coin_id = self._resolve_coinpaprika_id(base_symbol)
            if not coin_id:
                logger.warning("CoinPaprika ID not found for %s", base_symbol)
                return None
            
            # Get current price
            price_url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
            price_data = self._fetch_json(price_url)
            
            if price_data and price_data.get('quotes', {}).get('USD'):
                current_price = price_data['quotes']['USD']['price']
                
                # Get historical data
                start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
                hist_url = (
                    f"https://api.coinpaprika.com/v1/coins/{coin_id}/ohlcv/historical"
                    f"?start={start_date}&limit=200"
                )
                hist_data = self._fetch_json(hist_url)
                
                if hist_data:
                    df = self._process_coinpaprika_data(hist_data, current_price)
                    return self._calculate_indicators(df, symbol, "coinpaprika")
                    
        except Exception as e:
            logger.warning(f"CoinPaprika API failed for {symbol}: {e}")
            return None

    def _resolve_coinpaprika_id(self, base_symbol: str) -> Optional[str]:
        """Resolve CoinPaprika coin ID for given base symbol."""
        upper_symbol = base_symbol.upper()

        if base_symbol in self.coinpaprika_symbol_cache:
            return self.coinpaprika_symbol_cache[base_symbol]

        if base_symbol in self.coinpaprika_overrides:
            coin_id = self.coinpaprika_overrides[base_symbol]
            self.coinpaprika_symbol_cache[base_symbol] = coin_id
            return coin_id

        search_url = f"https://api.coinpaprika.com/v1/search?q={base_symbol}&c=currencies&limit=10"
        search_data = self._fetch_json(search_url)
        if search_data and 'currencies' in search_data:
            for entry in search_data['currencies']:
                if entry.get('symbol', '').upper() == upper_symbol and entry.get('id'):
                    coin_id = entry['id']
                    self.coinpaprika_symbol_cache[base_symbol] = coin_id
                    return coin_id
            return None
    
    def _process_ohlcv_data(self, data: List[Dict], current_price: float) -> pd.DataFrame:
        """Process Crypto.com OHLCV data"""
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
        df['open'] = df['o'].astype(float)
        df['high'] = df['h'].astype(float)
        df['low'] = df['l'].astype(float)
        df['close'] = df['c'].astype(float)
        df['volume'] = df['v'].astype(float)
        
        # Update last close with current price
        df.iloc[-1, df.columns.get_loc('close')] = current_price
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].set_index('timestamp')
    
    def _process_binance_klines(self, data: List[List]) -> pd.DataFrame:
        """Process Binance klines data"""
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].set_index('timestamp')
    
    def _process_kraken_ohlc(self, data: List[List]) -> pd.DataFrame:
        """Process Kraken OHLC data"""
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].set_index('timestamp')
    
    def _process_coinpaprika_data(self, data: List[Dict], current_price: float) -> pd.DataFrame:
        """Process CoinPaprika historical data"""
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['time_open'])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # Update last close with current price
        df.iloc[-1, df.columns.get_loc('close')] = current_price
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].set_index('timestamp')
    
    def _calculate_indicators(self, df: pd.DataFrame, symbol: str, source: str) -> Dict[str, Any]:
        """Calculate technical indicators"""
        try:
            # Ensure we have enough data
            if len(df) < 50:
                raise ValueError("Insufficient data for indicators")
            
            # Calculate RSI
            rsi = self._calculate_rsi(df['close'], 14)
            
            # Calculate Moving Averages
            ma10 = df['close'].rolling(window=10).mean().iloc[-1]
            ma50 = df['close'].rolling(window=50).mean().iloc[-1]
            ma200 = df['close'].rolling(window=200).mean().iloc[-1]
            
            current_price = df['close'].iloc[-1]
            
            # Use adaptive precision based on value magnitude (matching frontend logic)
            def get_ma_precision(value: float) -> int:
                if value >= 100:
                    return 2  # Values >= $100: 2 decimals
                elif value >= 1:
                    return 2  # Values $1-$99: 2 decimals
                elif value >= 0.01:
                    return 6  # Values $0.01-$0.99: 6 decimals
                else:
                    return 10  # Values < $0.01: 10 decimals
            
            price_decimals = get_ma_precision(current_price)
            
            return {
                "symbol": symbol,
                "source": source,
                "price": round(current_price, price_decimals),
                "rsi": round(rsi, 2),  # RSI should show 2 decimals
                "ma10": round(ma10, get_ma_precision(ma10)),
                "ma50": round(ma50, get_ma_precision(ma50)),
                "ma200": round(ma200, get_ma_precision(ma200)),
                "time": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            raise
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not rsi.empty else 50.0
    
    def get_price_with_fallback(self, symbol: str = "BTC_USDT", timeframe: str = "15m") -> Dict[str, Any]:
        """Get price data with automatic fallback between providers"""
        cache_key = self._get_cache_key(symbol, timeframe)
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            logger.info(f"♻️ Using cached data for {symbol} ({cached_result.get('source')})")
            return cached_result
        
        providers = [
            ("crypto_com", self.get_crypto_com),
            ("binance", self.get_binance),
            ("kraken", self.get_kraken),
            ("coinpaprika", self.get_coinpaprika)
        ]
        last_error: Optional[Exception] = None
        
        for provider_name, provider_func in providers:
            try:
                logger.info(f"Trying {provider_name} for {symbol}")
                result = provider_func(symbol, timeframe)
                if result:
                    self._cache_result(cache_key, result)
                    logger.info(f"✅ Successfully got data from {provider_name}")
                    return result
            except Exception as e:
                last_error = e
                logger.warning(f"❌ {provider_name} failed: {e}")
            time.sleep(0.2)
        
        stale_result = self._get_cached_result(cache_key, allow_stale=True)
        if stale_result:
            logger.warning(f"⚠️ Returning stale cached data for {symbol}")
            return stale_result
        
        # If all providers fail, return error
        error_message = f"All price providers failed for {symbol}"
        if last_error:
            error_message += f" (last error: {last_error})"
        raise Exception(error_message)

# Global instance
price_fetcher = PriceFetcher()

def get_price_with_fallback(symbol: str = "BTC_USDT", timeframe: str = "15m") -> Dict[str, Any]:
    """Public function to get price data with fallback"""
    return price_fetcher.get_price_with_fallback(symbol, timeframe)
