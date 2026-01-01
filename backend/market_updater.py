"""
Market Data Updater Worker
This module runs as a separate process to update market data from external APIs.
It respects rate limits (3s delay between coins) and saves results to shared storage.
Now includes technical indicators: RSI, MA50, MA200, EMA10, ATR
"""
import asyncio
import logging
import sys
import os
import time
import requests
import numpy as np
from typing import Dict, List, Optional

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

FETCH_SYMBOL_LIMIT = 50  # Increased from 10 to 50 to process more symbols
_non_custom_offset = 0

# Default list of major cryptocurrencies that should always be tracked
DEFAULT_TRACKED_SYMBOLS = [
    "BTC_USDT", "BTC_USD", "ETH_USDT", "ETH_USD",
    "DOGE_USDT", "ADA_USDT", "TON_USDT", "SOL_USDT",
    "BNB_USDT", "XRP_USDT", "DOT_USDT", "LINK_USDT",
    "MATIC_USDT", "AVAX_USDT", "ALGO_USDT", "UNI_USDT",
    "ATOM_USDT", "ETC_USDT", "LTC_USDT", "BCH_USDT",
    "XLM_USDT", "FIL_USDT", "TRX_USDT"
]

# Import after path setup
from app.api.routes_market import (
    _get_db_connection,
    _fetch_custom_coins
)
from app.api.routes_signals import (
    calculate_rsi,
    calculate_atr,
    calculate_ma,
    calculate_ema,
    calculate_volume_index
)
from simple_price_fetcher import price_fetcher, PriceResult
from market_cache_storage import save_cache_to_storage

# Import database models and session
try:
    from app.database import SessionLocal, Base, engine
    from app.models.market_price import MarketPrice, MarketData
    from sqlalchemy import func
    # Only create MarketPrice and MarketData tables, not all tables
    # This avoids errors with other tables that may have schema issues
    MarketPrice.__table__.create(bind=engine, checkfirst=True)
    MarketData.__table__.create(bind=engine, checkfirst=True)
    DB_AVAILABLE = True
except Exception as e:
    logger.warning(f"Database not available, will only use JSON cache: {e}")
    DB_AVAILABLE = False

# Import signal_writer to sync watchlist to TradeSignal
try:
    from app.services.signal_writer import sync_watchlist_to_signals
    SIGNAL_WRITER_AVAILABLE = True
except Exception as e:
    logger.warning(f"Signal writer not available: {e}")
    SIGNAL_WRITER_AVAILABLE = False


def fetch_ohlcv_data(symbol: str, interval: str = "1h", limit: int = 200) -> Optional[List[Dict]]:
    """Fetch OHLCV data from Crypto.com API with fallback to Binance if Crypto.com doesn't have the pair"""
    # Try Crypto.com first
    try:
        # Normalize symbol for Crypto.com API - automatically add _USDT if no pair specified
        normalized_symbol = symbol
        # Only normalize if symbol has no underscore (no pair specified)
        # OR if it has underscore AND ends with a supported pair (we can convert _USD to _USDT)
        has_pair = "_" in symbol
        ends_with_supported_pair = any(symbol.upper().endswith(f"_{q}") for q in ["USDT", "USD", "BTC", "ETH", "EUR"])
        
        if not has_pair:
            # No pair specified - add _USDT for Crypto.com
            normalized_symbol = f"{symbol}_USDT"
            logger.debug(f"Normalized symbol {symbol} to {normalized_symbol} for Crypto.com API")
        elif has_pair and not ends_with_supported_pair:
            # Has underscore but doesn't end with supported pair (e.g., BTC_UNKNOWN) - use as-is, don't normalize
            # This prevents creating invalid symbols like "BTC_UNKNOWN_USDT"
            logger.debug(f"Symbol {symbol} has non-standard pair, using as-is (no normalization)")
        elif symbol.upper().endswith("_USD"):
            # Convert _USD to _USDT for Crypto.com (they use USDT pairs)
            normalized_symbol = symbol.replace("_USD", "_USDT")
            logger.debug(f"Normalized symbol {symbol} to {normalized_symbol} for Crypto.com API")
        
        # Use Crypto.com Exchange API v1 (not v2)
        url = "https://api.crypto.com/exchange/v1/public/get-candlestick"
        params = {
            "instrument_name": normalized_symbol,
            "timeframe": interval
        }
        # Note: v1 API doesn't use "count" parameter, it returns default amount
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Check if Crypto.com returned an error (e.g., invalid instrument)
        if "code" in result and result.get("code") != 0:
            error_code = result.get("code")
            error_msg = result.get("message", "")
            logger.debug(f"Crypto.com error for {symbol} ({normalized_symbol}): code={error_code}, message={error_msg}")
            # Fall through to Binance fallback
        elif "result" in result and "data" in result["result"]:
            data = result["result"]["data"]
            if data and len(data) > 0:
                # Convert to standardized format
                ohlcv_data = []
                for candle in data:
                    ohlcv_data.append({
                        "t": candle.get("t", 0),  # timestamp
                        "o": float(candle.get("o", 0)),  # open
                        "h": float(candle.get("h", 0)),  # high
                        "l": float(candle.get("l", 0)),  # low
                        "c": float(candle.get("c", 0)),  # close
                        "v": float(candle.get("v", 0))   # volume
                    })
                # CRITICAL: Crypto.com API v1 only returns ~25 candles by default
                # If we need more than 50 candles (for RSI/MA calculations), use Binance fallback
                if len(ohlcv_data) < 50 and limit >= 50:
                    logger.debug(f"⚠️ Crypto.com only returned {len(ohlcv_data)} candles for {symbol} (need {limit}), trying Binance fallback for more data")
                    # Fall through to Binance fallback to get more candles
                else:
                    logger.debug(f"✅ Fetched {len(ohlcv_data)} candles from Crypto.com for {symbol} (normalized: {normalized_symbol})")
                    return ohlcv_data
    except requests.exceptions.HTTPError as e:
        # HTTP error (404, 400, etc.) - Crypto.com doesn't have this pair
        logger.debug(f"Crypto.com HTTP error for {symbol}: {e}, trying Binance fallback...")
    except Exception as e:
        logger.debug(f"Crypto.com error for {symbol}: {e}, trying Binance fallback...")
    
    # Fallback to Binance for pairs Crypto.com doesn't support (e.g., BNB_USDT)
    try:
        # Convert symbol format for Binance: BTC_USDT -> BTCUSDT, BNB_USD -> BNBUSDT
        # IMPORTANT: Check for _USDT first (before _USD) to avoid creating "USDTUSDT"
        # This prevents creating invalid symbols like "BNBUSDTT"
        if symbol.endswith("_USDT"):
            # Remove _USDT and append USDT: BTC_USDT -> BTC + USDT = BTCUSDT
            binance_symbol = symbol[:-5] + "USDT"  # Remove last 5 chars (_USDT) and add USDT
        elif symbol.endswith("_USD"):
            # Remove _USD and append USDT: BNB_USD -> BNB + USDT = BNBUSDT
            binance_symbol = symbol[:-4] + "USDT"  # Remove last 4 chars (_USD) and add USDT
        else:
            # For other formats, just remove underscore: BTC_ETH -> BTCETH
            binance_symbol = symbol.replace("_", "")
        
        # Map interval to Binance format
        interval_map = {
            "1m": "1m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w"
        }
        binance_interval = interval_map.get(interval, "1h")
        
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": binance_symbol,
            "interval": binance_interval,
            "limit": min(limit, 1000)  # Binance max is 1000
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data and len(data) > 0:
            # Binance returns array of arrays: [timestamp, open, high, low, close, volume, ...]
            ohlcv_data = []
            for kline in data:
                ohlcv_data.append({
                    "t": kline[0],  # timestamp (ms)
                    "o": float(kline[1]),  # open
                    "h": float(kline[2]),  # high
                    "l": float(kline[3]),  # low
                    "c": float(kline[4]),  # close
                    "v": float(kline[5])   # volume
                })
            logger.info(f"✅ Fetched {len(ohlcv_data)} candles from Binance for {symbol} (Binance symbol: {binance_symbol})")
            # Warn if insufficient data for proper RSI calculation
            if len(ohlcv_data) < 50:
                logger.warning(f"⚠️ Only {len(ohlcv_data)} candles for {symbol} (need 50+ for reliable RSI calculation)")
            return ohlcv_data
        else:
            logger.warning(f"No OHLCV data from Binance for {symbol} (Binance symbol: {binance_symbol})")
            return None
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Binance HTTP error for {symbol} (Binance symbol: {binance_symbol}): {e}")
        return None
    except Exception as e:
        logger.warning(f"Binance error for {symbol} (Binance symbol: {binance_symbol}): {e}")
        return None

def calculate_technical_indicators(ohlcv_data: List[Dict], current_price: float, ohlcv_data_daily: Optional[List[Dict]] = None, ohlcv_data_volume: Optional[List[Dict]] = None) -> Dict[str, float]:
    """Calculate all technical indicators from OHLCV data
    Args:
        ohlcv_data: Hourly OHLCV data for most indicators (RSI, MA50, MA200, EMA10, ATR)
        current_price: Current market price
        ohlcv_data_daily: Optional daily OHLCV data for accurate MA10w calculation (10-week MA = 70 days)
        ohlcv_data_volume: Optional OHLCV data with shorter timeframe (e.g., 10m) for volume calculation
    """
    if not ohlcv_data or len(ohlcv_data) < 50:
        # Return default values if insufficient data
        # Use current_price for all MAs if we have a valid price
        fallback_ma = current_price if current_price > 0 else 0.0
        return {
            "rsi": 50.0,
            "ma50": fallback_ma,
            "ma200": fallback_ma,
            "ema10": fallback_ma,
            "ma10w": fallback_ma,  # Will be recalculated if we have more data later
            "atr": current_price * 0.02 if current_price > 0 else 0.0,  # 2% default
            "volume_24h": 0.0,
            "avg_volume": 0.0,
            "volume_ratio": 0.0
        }
    
    # Extract price arrays
    closes = [candle["c"] for candle in ohlcv_data]
    highs = [candle["h"] for candle in ohlcv_data]
    lows = [candle["l"] for candle in ohlcv_data]
    volumes = [candle["v"] for candle in ohlcv_data]
    
    # Update last close with current price
    if closes:
        closes[-1] = current_price
    
    try:
        # Calculate indicators
        rsi = calculate_rsi(closes, period=14)
        ma50 = calculate_ma(closes, period=50)
        ma200 = calculate_ma(closes, period=200) if len(closes) >= 200 else calculate_ma(closes, period=min(200, len(closes)))
        ema10 = calculate_ema(closes, period=10)
        
        # Calculate MA10w (10-week moving average = 70 days)
        # Use daily data if available for accurate calculation, otherwise use hourly data as approximation
        ma10w = None
        if ohlcv_data_daily and len(ohlcv_data_daily) >= 70:
            # Use daily data for accurate 10-week MA (70 days)
            daily_closes = [candle["c"] for candle in ohlcv_data_daily]
            # Update last close with current price for most recent value
            if daily_closes:
                daily_closes[-1] = current_price
            ma10w = calculate_ma(daily_closes, period=70)  # 70 days = 10 weeks
            logger.debug(f"✅ MA10w calculated from daily data: {ma10w:.2f} (using {len(daily_closes)} daily periods)")
        elif ohlcv_data_daily and len(ohlcv_data_daily) >= 50:
            # Use available daily periods if we have at least 50 days
            daily_closes = [candle["c"] for candle in ohlcv_data_daily]
            if daily_closes:
                daily_closes[-1] = current_price
            ma10w = calculate_ma(daily_closes, period=min(70, len(daily_closes)))
            logger.debug(f"⚠️ MA10w calculated from limited daily data: {ma10w:.2f} (only {len(daily_closes)} days available)")
        elif len(closes) >= 70:
            # Fallback: use hourly data if daily not available (less accurate)
            ma10w = calculate_ma(closes, period=70)  # Approximate 10-week MA (70 hours ≈ 3 days - not ideal)
            logger.debug(f"⚠️ MA10w calculated from hourly data (approximation): {ma10w:.2f} (70 hours ≈ 3 days)")
        elif len(closes) >= 50:
            # Use available hourly periods if we have at least 50
            ma10w = calculate_ma(closes, period=min(70, len(closes)))
            logger.debug(f"⚠️ MA10w calculated from limited hourly data: {ma10w:.2f} (only {len(closes)} hours available)")
        else:
            # Use MA200 as approximation if we have it, otherwise use current price
            ma10w = float(ma200) if ma200 > 0 else current_price
            logger.debug(f"⚠️ MA10w using fallback (MA200 or price): {ma10w:.2f}")
        
        # Calculate ATR with adaptive precision based on current price
        atr = calculate_atr(highs, lows, closes, period=14, current_price=current_price)
        
        # Volume indicators - use shorter timeframe data if available (e.g., 5m), otherwise use hourly data
        # Using period=5 means: 5 periods of the selected timeframe (5*5m = 25min with 5m data, or 5h with 1h data)
        if ohlcv_data_volume and len(ohlcv_data_volume) >= 3:
            # Use shorter timeframe data (e.g., 5m) for more responsive volume calculation
            volume_data = [candle["v"] for candle in ohlcv_data_volume]
            volume_index = calculate_volume_index(volume_data, period=5)
            # For volume_24h, sum last 24 hours worth of periods (e.g., 288 periods for 5m = 24h)
            periods_per_24h = 288 if len(ohlcv_data_volume) >= 288 else len(ohlcv_data_volume)
            volume_24h = sum(volume_data[-periods_per_24h:]) if len(volume_data) >= periods_per_24h else sum(volume_data)
            current_volume = volume_index.get("current_volume", volume_data[-1] if volume_data else 0)
        else:
            # Fallback to hourly data for volume
            volume_index = calculate_volume_index(volumes, period=5)
            volume_24h = sum(volumes[-24:]) if len(volumes) >= 24 else sum(volumes)
            current_volume = volume_index.get("current_volume", volumes[-1] if volumes else 0)
        
        return {
            "rsi": float(rsi),
            "ma50": float(ma50),
            "ma200": float(ma200),
            "ema10": float(ema10),
            "ma10w": float(ma10w),
            "atr": float(atr),
            "volume_24h": float(volume_24h),
            "current_volume": float(current_volume),
            "avg_volume": float(volume_index.get("average_volume", 0)),
            "volume_ratio": float(volume_index.get("volume_ratio", 0))
        }
    except Exception as e:
        logger.warning(f"Error calculating indicators: {e}")
        # Return defaults on error - use MA200 or MA50 as fallback for MA10w if available
        fallback_ma = current_price if current_price > 0 else 0.0
        return {
            "rsi": 50.0,
            "ma50": fallback_ma,
            "ma200": fallback_ma,
            "ema10": fallback_ma,
            "ma10w": fallback_ma,
            "atr": current_price * 0.02 if current_price > 0 else 0.0,
            "volume_24h": 0.0,
            "current_volume": 0.0,
            "avg_volume": 0.0,
            "volume_ratio": 0.0
        }


async def update_market_data():
    """Update market data from external APIs (slow operation with delays)
    Now includes technical indicators calculation
    """
    start_time = time.time()
    logger.info("Starting market data update with technical indicators")
    
    try:
        # Get coins from PostgreSQL (MarketPrice) and custom coins from SQLite
        logger.info("Fetching coins from database")
        coins = []
        custom_coins = []
        
        # Get custom coins from SQLite (non-critical, can fail gracefully)
        try:
            conn = _get_db_connection()
            custom_coins = _fetch_custom_coins(conn)
            logger.info(f"Fetched {len(custom_coins)} custom coins")
            conn.close()
        except Exception as custom_err:
            logger.warning(f"Failed to fetch custom coins (non-critical): {custom_err}")
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
        
        # CRITICAL CHANGE: Get coins from watchlist_items (is_deleted=False) instead of just MarketPrice
        # This ensures ALL non-deleted watchlist coins are updated, even if they don't have prices yet
        if DB_AVAILABLE:
            try:
                db = SessionLocal()
                from app.models.watchlist import WatchlistItem
                
                # Get all non-deleted watchlist items (this is the source of truth)
                watchlist_items = db.query(WatchlistItem).filter(
                    WatchlistItem.is_deleted == False
                ).all()
                
                logger.info(f"Found {len(watchlist_items)} non-deleted watchlist items")
                
                # Get existing MarketPrice entries for reference
                market_prices = db.query(MarketPrice).all()
                market_price_map = {mp.symbol: mp for mp in market_prices}
                
                # Build coins list from watchlist_items (not just MarketPrice)
                coins = []
                existing_symbols_set = set()
                
                for idx, item in enumerate(watchlist_items):
                    symbol = item.symbol
                    existing_symbols_set.add(symbol)
                    
                    # Get MarketPrice data if available
                    mp = market_price_map.get(symbol)
                    
                    # Parse symbol to get base and quote currency
                    if "_" in symbol:
                        base_currency = symbol.split("_")[0]
                        quote_currency = symbol.split("_")[1]
                    else:
                        base_currency = symbol
                        quote_currency = "USD"
                    
                    coins.append({
                        "instrument_name": symbol,
                        "base_currency": base_currency,
                        "quote_currency": quote_currency,
                        "volume_24h": float(mp.volume_24h) if mp and mp.volume_24h else 0.0,
                        "rank": idx + 1,
                        "updated_at": mp.updated_at.isoformat() if mp and mp.updated_at else None,
                        "is_custom": True,  # All watchlist coins are user-tracked
                    })
                
                # Add default tracked symbols that are missing from watchlist
                # This ensures major coins are always tracked even if they're not in watchlist yet
                missing_default_symbols = [s for s in DEFAULT_TRACKED_SYMBOLS if s not in existing_symbols_set]
                if missing_default_symbols:
                    logger.info(f"Adding {len(missing_default_symbols)} default tracked symbols that are missing from watchlist")
                    for symbol in missing_default_symbols:
                        base_currency = symbol.split("_")[0] if "_" in symbol else symbol
                        quote_currency = symbol.split("_")[1] if "_" in symbol else "USD"
                        mp = market_price_map.get(symbol)
                        coins.append({
                            "instrument_name": symbol,
                            "base_currency": base_currency,
                            "quote_currency": quote_currency,
                            "volume_24h": float(mp.volume_24h) if mp and mp.volume_24h else 0.0,
                            "rank": len(coins) + 1,
                            "updated_at": mp.updated_at.isoformat() if mp and mp.updated_at else None,
                            "is_custom": False,
                        })
                
                logger.info(f"Fetched {len(watchlist_items)} coins from watchlist, added {len(missing_default_symbols)} default symbols, total: {len(coins)}")
                db.close()
            except Exception as pg_error:
                logger.error(f"PostgreSQL error: {pg_error}", exc_info=True)
                # Fallback: use default symbols if database is unavailable
                coins = [
                    {
                        "instrument_name": symbol,
                        "base_currency": symbol.split("_")[0] if "_" in symbol else symbol,
                        "quote_currency": symbol.split("_")[1] if "_" in symbol else "USD",
                        "volume_24h": 0.0,
                        "rank": idx + 1,
                        "updated_at": None,
                    }
                    for idx, symbol in enumerate(DEFAULT_TRACKED_SYMBOLS)
                ]
                logger.warning(f"Using fallback default symbols list: {len(coins)} symbols")
        else:
            logger.warning("PostgreSQL not available, using default tracked symbols")
            coins = [
                {
                    "instrument_name": symbol,
                    "base_currency": symbol.split("_")[0] if "_" in symbol else symbol,
                    "quote_currency": symbol.split("_")[1] if "_" in symbol else "USD",
                    "volume_24h": 0.0,
                    "rank": idx + 1,
                    "updated_at": None,
                }
                for idx, symbol in enumerate(DEFAULT_TRACKED_SYMBOLS)
            ]

        # Merge coins into a single mapping to avoid duplicates
        coin_map: Dict[str, Dict] = {}
        for coin in coins:
            instrument = coin["instrument_name"]
            coin_map[instrument] = {
                "rank": coin["rank"],
                "instrument_name": instrument,
                "base_currency": coin["base_currency"],
                "quote_currency": coin["quote_currency"],
                "volume_24h": coin.get("volume_24h", 0) or 0,
                "updated_at": coin.get("updated_at"),
                "is_custom": False,
            }

        next_rank = len(coin_map) + 1
        for coin in custom_coins:
            instrument = coin["instrument_name"]
            if instrument in coin_map:
                continue
            coin_map[instrument] = {
                "rank": next_rank,
                "instrument_name": instrument,
                "base_currency": coin["base_currency"],
                "quote_currency": coin["quote_currency"],
                "volume_24h": 0,
                "updated_at": coin.get("created_at"),
                "is_custom": True,
            }
            next_rank += 1

        coins = list(coin_map.values())

        # Load existing market prices/indicators from database for fallback values
        existing_prices: Dict[str, float] = {}
        existing_volumes: Dict[str, float] = {}
        existing_indicators: Dict[str, Dict[str, float]] = {}
        if DB_AVAILABLE:
            try:
                db = SessionLocal()
                try:
                    market_prices = db.query(MarketPrice).all()
                    for mp in market_prices:
                        existing_prices[mp.symbol] = mp.price or 0.0
                        existing_volumes[mp.symbol] = mp.volume_24h or 0.0
                    market_data_rows = db.query(MarketData).all()
                    for md in market_data_rows:
                        existing_indicators[md.symbol] = {
                            "rsi": float(md.rsi) if md.rsi is not None else 50.0,
                            "ma50": float(md.ma50) if md.ma50 is not None else float(md.price or 0.0),
                            "ma200": float(md.ma200) if md.ma200 is not None else float(md.price or 0.0),
                            "ema10": float(md.ema10) if md.ema10 is not None else float(md.price or 0.0),
                            "ma10w": float(md.ma10w) if md.ma10w is not None else float(md.price or 0.0),
                            "atr": float(md.atr) if md.atr is not None else float((md.price or 0.0) * 0.02),
                            "volume_24h": float(md.volume_24h) if md.volume_24h is not None else 0.0,
                            "avg_volume": float(md.avg_volume) if md.avg_volume is not None else 0.0,
                            "volume_ratio": float(md.volume_ratio) if md.volume_ratio is not None else 0.0,
                        }
                finally:
                    db.close()
            except Exception as existing_err:
                logger.warning(f"Failed to load existing market prices: {existing_err}")

        # Get prices with simple fetcher - this is the slow part with external API calls
        prices_map: Dict[str, float] = {}
        volume_map: Dict[str, float] = {}
        symbols = [coin["instrument_name"] for coin in coins]
        
        try:
            logger.info(f"Starting price fetch for {len(symbols)} symbols (with 3s delay between each)")
            max_symbols = FETCH_SYMBOL_LIMIT
            if len(symbols) > max_symbols:
                custom_symbols = [coin["instrument_name"] for coin in coins if coin.get("is_custom")]
                non_custom_symbols = [s for s in symbols if s not in custom_symbols]
                selected_symbols: List[str] = []

                # Always include custom symbols first (up to the limit)
                for s in custom_symbols:
                    if len(selected_symbols) >= max_symbols:
                        break
                    selected_symbols.append(s)

                # Rotate through non-custom symbols across runs
                if non_custom_symbols:
                    global _non_custom_offset
                    remaining = max_symbols - len(selected_symbols)
                    total_non_custom = len(non_custom_symbols)
                    if remaining > 0:
                        chosen = []
                        idx = 0
                        while len(chosen) < remaining and idx < total_non_custom:
                            symbol_idx = (_non_custom_offset + idx) % total_non_custom
                            candidate = non_custom_symbols[symbol_idx]
                            if candidate not in selected_symbols:
                                chosen.append(candidate)
                            idx += 1
                        selected_symbols.extend(chosen[:remaining])
                        _non_custom_offset = (_non_custom_offset + len(chosen)) % total_non_custom

                # Fallback: if still underfilled (unlikely), append remaining from original order
                if len(selected_symbols) < max_symbols:
                    for s in symbols:
                        if len(selected_symbols) >= max_symbols:
                            break
                        if s not in selected_symbols:
                            selected_symbols.append(s)

                logger.warning(
                    f"Too many symbols ({len(symbols)}), limiting to {max_symbols} for performance "
                    f"(custom={len(custom_symbols)}, selected={len(selected_symbols)})"
                )
                logger.debug(f"Selected symbols for price fetch: {selected_symbols}")
                symbols = selected_symbols
            
            # Start with existing prices/volumes to avoid zeroing out untouched coins
            for coin in coins:
                symbol = coin["instrument_name"]
                prices_map[symbol] = existing_prices.get(symbol, coin.get("current_price") or 0.0)
                volume_map[symbol] = existing_volumes.get(symbol, coin.get("volume_24h") or 0.0)
            
            indicators_map: Dict[str, Dict[str, float]] = {
                symbol: data.copy() for symbol, data in existing_indicators.items()
            }
            
            # Fetch prices sequentially with 3s delay between each coin
            price_results: Dict[str, Optional["PriceResult"]] = {}
            
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Fetch prices, OHLCV, and indicators one by one with 3s delay between each
            for idx, symbol in enumerate(symbols):
                try:
                    logger.debug(f"Fetching price and indicators for {symbol} ({idx + 1}/{len(symbols)})")
                    
                    # Fetch price
                    price_result = await loop.run_in_executor(
                        None,
                        price_fetcher.get_price,
                        symbol
                    )
                    price_results[symbol] = price_result
                    
                    current_price = 0.0
                    if price_result and price_result.success:
                        current_price = price_result.price
                        logger.debug(f"✅ Price for {symbol}: ${current_price} from {price_result.source}")
                    else:
                        logger.debug(f"⚠️ Failed to get price for {symbol}, using 0.0")
                    
                    # Fetch OHLCV data for indicators (if we got a price)
                    indicators = {}
                    if current_price > 0:
                        try:
                            # Fetch hourly data for most indicators (RSI, MA50, MA200, EMA10, ATR)
                            ohlcv_data_1h = fetch_ohlcv_data(symbol, interval="1h", limit=200)
                            
                            # Fetch daily data for MA10w (10-week MA = 70 days)
                            ohlcv_data_1d = fetch_ohlcv_data(symbol, interval="1d", limit=75)  # Get 75 daily candles for 10-week MA (70 days + buffer)
                            
                            # Fetch 5-minute data for volume calculation (more responsive)
                            # Get ~288 periods = 24 hours of 5-minute data
                            ohlcv_data_5m = fetch_ohlcv_data(symbol, interval="5m", limit=288)
                            
                            if ohlcv_data_1h:
                                indicators = calculate_technical_indicators(ohlcv_data_1h, current_price, ohlcv_data_daily=ohlcv_data_1d, ohlcv_data_volume=ohlcv_data_5m)
                                # Log at INFO level so it's visible in production logs
                                logger.info(f"✅ Indicators for {symbol}: RSI={indicators.get('rsi', 0):.1f}, MA50={indicators.get('ma50', 0):.2f}, MA10w={indicators.get('ma10w', 0):.2f}, Volume ratio={indicators.get('volume_ratio', 0):.2f}x (candles: {len(ohlcv_data_1h)})")
                            else:
                                logger.warning(f"⚠️ No OHLCV data for {symbol}, using defaults (price={current_price})")
                                # Use defaults
                                indicators = calculate_technical_indicators([], current_price, ohlcv_data_daily=None, ohlcv_data_volume=None)
                        except Exception as e:
                            logger.warning(f"Error calculating indicators for {symbol}: {e}")
                            indicators = calculate_technical_indicators([], current_price, ohlcv_data_daily=None, ohlcv_data_volume=None)
                    else:
                        # No price, use defaults
                        indicators = calculate_technical_indicators([], 0.0, ohlcv_data_daily=None, ohlcv_data_volume=None)
                    
                    indicators_map[symbol] = indicators
                    
                    # Wait 3 seconds before next coin (except after the last one)
                    if idx < len(symbols) - 1:
                        await asyncio.sleep(3)
                        
                except Exception as e:
                    logger.warning(f"Error fetching data for {symbol}: {e}")
                    price_results[symbol] = None
                    if symbol not in indicators_map:
                                indicators_map[symbol] = calculate_technical_indicators([], prices_map.get(symbol, 0.0), ohlcv_data_daily=None, ohlcv_data_volume=None)
            
            logger.info(f"Finished price fetch for {len(symbols)} symbols, got {len(price_results)} results")
            
            # Process results (prices and indicators) - keep price_results for later use
            for coin in coins:
                symbol = coin["instrument_name"]
                price_result = price_results.get(symbol)
                indicators = indicators_map.get(symbol, {})
                
                if price_result and price_result.success:
                    prices_map[symbol] = price_result.price
                    # Use real volume from indicators if available
                    volume_map[symbol] = indicators.get("volume_24h", price_result.price * 1000000)
                else:
                    if symbol not in prices_map:
                        prices_map[symbol] = coin.get("current_price") or existing_prices.get(symbol, 0.0)
                    if symbol not in volume_map:
                        volume_map[symbol] = indicators.get("volume_24h", existing_volumes.get(symbol, 0.0))
                    if symbol not in indicators_map:
                        # Ensure indicators_map has an entry for later use
                        indicators_map[symbol] = existing_indicators.get(symbol, calculate_technical_indicators([], prices_map[symbol], ohlcv_data_daily=None, ohlcv_data_volume=None))
            
            # Keep price_results and indicators_map in scope for database saving
            # They are now available for the database update section below
                        
        except Exception as e:
            logger.error(f"Error in simple price fetching: {e}")
            # Use 0.0 for all symbols on error
            for coin in coins:
                symbol = coin["instrument_name"]
                if symbol not in prices_map:
                    prices_map[symbol] = existing_prices.get(symbol, 0.0)
                    volume_map[symbol] = existing_volumes.get(symbol, 0.0)
            indicators_map = existing_indicators.copy()
        
        # Enrich coins with prices, volumes, and technical indicators
        enriched_coins = []
        for coin in coins:
            instrument = coin["instrument_name"]
            updated_at = coin.get("updated_at")
            if updated_at and not isinstance(updated_at, str):
                updated_at = str(updated_at)
            
            # Get indicators for this coin
            indicators = indicators_map.get(instrument, existing_indicators.get(instrument, {}))
            current_price = float(prices_map.get(instrument, 0))
            
            # Ensure MA10w has a valid value - use MA200 or MA50 as fallback if needed
            ma10w = indicators.get("ma10w")
            if not ma10w or ma10w == 0:
                # Try to use MA200 as fallback
                ma200 = indicators.get("ma200")
                if ma200 and ma200 > 0:
                    ma10w = ma200
                else:
                    # Try MA50 as fallback
                    ma50 = indicators.get("ma50")
                    if ma50 and ma50 > 0:
                        ma10w = ma50
                    else:
                        # Last resort: use current price
                        ma10w = current_price if current_price > 0 else 0.0
            
            enriched_coin = {
                "rank": int(coin.get("rank", 0)) if coin.get("rank") else 0,
                "instrument_name": str(instrument),
                "base_currency": str(coin.get("base_currency", "")),
                "quote_currency": str(coin.get("quote_currency", "")),
                "current_price": current_price,
                "volume_24h": float(volume_map.get(instrument, coin.get("volume_24h") or 0)),
                "updated_at": str(updated_at) if updated_at else None,
                "is_custom": bool(coin.get("is_custom", False)),
                # Technical indicators
                "rsi": float(indicators.get("rsi", 50.0)),
                "ma50": float(indicators.get("ma50", current_price)),
                "ma200": float(indicators.get("ma200", current_price)),
                "ema10": float(indicators.get("ema10", current_price)),
                "ma10w": float(ma10w),
                "atr": float(indicators.get("atr", current_price * 0.02 if current_price > 0 else 0.0)),
                "current_volume": float(indicators.get("current_volume", 0)),
                "avg_volume": float(indicators.get("avg_volume", 0)),
                "volume_ratio": float(indicators.get("volume_ratio", 0)),
            }
            enriched_coins.append(enriched_coin)
        
        # Save to database if available
        if DB_AVAILABLE:
            try:
                db = SessionLocal()
                try:
                    for coin in enriched_coins:
                        symbol = coin["instrument_name"]
                        price = coin["current_price"]
                        source = "cache"  # Default source
                        
                        # Find source from price_results if available
                        price_result = price_results.get(symbol)
                        if price_result and price_result.success:
                            source = price_result.source
                        
                        # Update or insert MarketPrice
                        market_price = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
                        if market_price:
                            market_price.price = price
                            market_price.source = source
                            market_price.volume_24h = coin.get("volume_24h")
                            market_price.updated_at = func.now()
                        else:
                            market_price = MarketPrice(
                                symbol=symbol,
                                exchange="CRYPTO_COM",
                                price=price,
                                source=source,
                                volume_24h=coin.get("volume_24h")
                            )
                            db.add(market_price)
                        
                        # Update or insert MarketData
                        market_data = db.query(MarketData).filter(MarketData.symbol == symbol).first()
                        if market_data:
                            market_data.price = price
                            market_data.rsi = coin.get("rsi")
                            market_data.atr = coin.get("atr")
                            market_data.ma50 = coin.get("ma50")
                            market_data.ma200 = coin.get("ma200")
                            market_data.ema10 = coin.get("ema10")
                            market_data.ma10w = coin.get("ma10w")
                            market_data.volume_24h = coin.get("volume_24h")
                            market_data.current_volume = coin.get("current_volume")
                            market_data.avg_volume = coin.get("avg_volume")
                            market_data.volume_ratio = coin.get("volume_ratio")
                            market_data.res_up = price * 1.02 if price > 0 else None
                            market_data.res_down = price * 0.98 if price > 0 else None
                            market_data.source = source
                            market_data.updated_at = func.now()
                        else:
                            market_data = MarketData(
                                symbol=symbol,
                                exchange="CRYPTO_COM",
                                price=price,
                                rsi=coin.get("rsi"),
                                atr=coin.get("atr"),
                                ma50=coin.get("ma50"),
                                ma200=coin.get("ma200"),
                                ema10=coin.get("ema10"),
                                ma10w=coin.get("ma10w"),
                                volume_24h=coin.get("volume_24h"),
                                current_volume=coin.get("current_volume"),
                                avg_volume=coin.get("avg_volume"),
                                volume_ratio=coin.get("volume_ratio"),
                                res_up=price * 1.02 if price > 0 else None,
                                res_down=price * 0.98 if price > 0 else None,
                                source=source
                            )
                            db.add(market_data)
                        
                        # CRITICAL: Also update watchlist_master table (source of truth for UI)
                        try:
                            from app.models.watchlist_master import WatchlistMaster
                            from datetime import datetime, timezone
                            
                            master = db.query(WatchlistMaster).filter(
                                WatchlistMaster.symbol == symbol.upper()
                            ).first()
                            
                            if master:
                                # Update market data fields in master table with timestamps
                                now = datetime.now(timezone.utc)
                                if price is not None:
                                    master.update_field('price', price, now)
                                if coin.get("rsi") is not None:
                                    master.update_field('rsi', coin.get("rsi"), now)
                                if coin.get("atr") is not None:
                                    master.update_field('atr', coin.get("atr"), now)
                                if coin.get("ma50") is not None:
                                    master.update_field('ma50', coin.get("ma50"), now)
                                if coin.get("ma200") is not None:
                                    master.update_field('ma200', coin.get("ma200"), now)
                                if coin.get("ema10") is not None:
                                    master.update_field('ema10', coin.get("ema10"), now)
                                if coin.get("volume_ratio") is not None:
                                    master.update_field('volume_ratio', coin.get("volume_ratio"), now)
                                if coin.get("current_volume") is not None:
                                    master.update_field('current_volume', coin.get("current_volume"), now)
                                if coin.get("avg_volume") is not None:
                                    master.update_field('avg_volume', coin.get("avg_volume"), now)
                                if coin.get("volume_24h") is not None:
                                    master.update_field('volume_24h', coin.get("volume_24h"), now)
                                
                                res_up = price * 1.02 if price and price > 0 else None
                                res_down = price * 0.98 if price and price > 0 else None
                                if res_up is not None:
                                    master.update_field('res_up', res_up, now)
                                if res_down is not None:
                                    master.update_field('res_down', res_down, now)
                                
                                master.updated_at = now
                            else:
                                # Master row doesn't exist - will be created by seeding on next API call
                                logger.debug(f"watchlist_master row not found for {symbol}, will be seeded on next API call")
                        except Exception as master_err:
                            # Don't fail the entire update if master table update fails
                            logger.warning(f"Error updating watchlist_master for {symbol}: {master_err}")
                    
                    db.commit()
                    logger.info(f"✅ Saved {len(enriched_coins)} market prices and data to database")
                    
                    # Sync watchlist to TradeSignal after updating market data
                    if SIGNAL_WRITER_AVAILABLE:
                        try:
                            logger.debug("Syncing watchlist to TradeSignal...")
                            sync_watchlist_to_signals(db)
                            logger.info("✅ Synced watchlist to TradeSignal")
                        except Exception as sync_error:
                            logger.warning(f"Error syncing watchlist to TradeSignal: {sync_error}")
                except Exception as db_error:
                    db.rollback()
                    logger.error(f"Error saving to database: {db_error}", exc_info=True)
                finally:
                    db.close()
            except Exception as e:
                logger.warning(f"Database session error: {e}")
        
        # Save to shared storage (JSON cache - for backward compatibility)
        cache_data = {
            "coins": enriched_coins,
            "count": len(enriched_coins),
            "timestamp": time.time()
        }
        save_cache_to_storage(cache_data)
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Updated market data cache, {len(enriched_coins)} items, took {elapsed:.2f} seconds")
        
    except Exception as e:
        logger.error(f"Error updating market data: {e}", exc_info=True)
        # Save empty cache on error
        save_cache_to_storage({"coins": [], "count": 0})


async def run_updater():
    """Main updater loop - runs every 60 seconds"""
    logger.info("Market data updater worker started")
    logger.info("Update interval: 60 seconds")
    
    # Run initial update immediately
    logger.info("Running initial update...")
    await update_market_data()
    
    # Track update count for heartbeat
    update_count = 0
    last_heartbeat_time = time.time()
    
    # Then update every 60 seconds
    while True:
        try:
            await asyncio.sleep(60)
            update_count += 1
            logger.info("Scheduled update: running update_market_data()")
            await update_market_data()
            
            # Heartbeat log every 10 updates (~10 minutes)
            current_time = time.time()
            if update_count % 10 == 0 or (current_time - last_heartbeat_time) >= 600:
                logger.info(f"[MARKET_UPDATER_HEARTBEAT] Market updater alive - update_count={update_count} last_update={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))}")
                last_heartbeat_time = current_time
                
                # Check for stale data and log warning if ALL symbols are stale
                try:
                    db = SessionLocal()
                    try:
                        from app.models.market_price import MarketPrice
                        from datetime import datetime, timedelta, timezone
                        stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
                        total_symbols = db.query(MarketPrice).count()
                        stale_symbols = db.query(MarketPrice).filter(MarketPrice.updated_at < stale_threshold).count()
                        
                        if total_symbols > 0 and stale_symbols == total_symbols:
                            logger.warning(f"[MARKET_DATA_STALE_GLOBAL] ⚠️ ALL {total_symbols} symbols have stale prices (>30min old). Market data updater may be failing.")
                            # Send system alert (throttled to once per 24h)
                            try:
                                from app.services.system_alerts import check_and_alert_stale_market_data
                                check_and_alert_stale_market_data()
                            except Exception:
                                pass  # Don't fail updater if alert fails
                    except Exception as check_err:
                        logger.debug(f"Error checking stale data: {check_err}")
                    finally:
                        db.close()
                except Exception:
                    pass  # Don't fail updater if stale check fails
                    
        except KeyboardInterrupt:
            logger.info("Updater stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in updater loop: {e}", exc_info=True)
            # Continue running even if one update fails
            await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run_updater())
    except KeyboardInterrupt:
        logger.info("Updater process terminated")

