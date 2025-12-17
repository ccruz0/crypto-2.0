from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import JSONResponse
from app.deps.auth import get_current_user
from app.database import get_db
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.watchlist import WatchlistItem
from app.schemas.watchlist import WatchlistItemUpdate
import requests
import logging
import sqlite3
import time
from typing import List, Dict, Optional, Tuple
from fastapi import Depends
import sys
import os
from datetime import datetime, timezone

# Add paths to find simple_price_fetcher (can be in /app or /app/app)
backend_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # /app
app_root = os.path.dirname(os.path.dirname(__file__))  # /app/app
for path in [backend_root, app_root]:
    if path not in sys.path:
        sys.path.insert(0, path)
from simple_price_fetcher import price_fetcher
from app.services.trading_signals import calculate_trading_signals
from app.services.strategy_profiles import resolve_strategy_profile
try:
    # Newer versions export this helper; older deployments may not.
    from app.services.watchlist_selector import deduplicate_watchlist_items as _deduplicate_watchlist_items  # type: ignore
except Exception:  # pragma: no cover - defensive for older prod images
    _deduplicate_watchlist_items = None
from app.services.signal_throttle import (
    reset_throttle_state,
    set_force_next_signal,
    build_strategy_key,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Global cache for top coins data
_top_coins_cache: Optional[Dict] = None
_top_coins_cache_timestamp: Optional[float] = None


def _log_alert_state(action: str, watchlist_item: WatchlistItem) -> None:
    try:
        logger.info(
            "[ALERT] %s | %s -> alert_enabled=%s, buy_alert_enabled=%s, sell_alert_enabled=%s",
            action,
            watchlist_item.symbol,
            bool(getattr(watchlist_item, "alert_enabled", False)),
            bool(getattr(watchlist_item, "buy_alert_enabled", False)),
            bool(getattr(watchlist_item, "sell_alert_enabled", False)),
        )
    except Exception as log_err:
        logger.warning("Failed to log alert state: %s", log_err)


def deduplicate_watchlist_items(items: List[WatchlistItem]) -> List[WatchlistItem]:
    """
    Collapse duplicate watchlist rows per symbol (best-effort).

    This is used by market endpoints to avoid UI inconsistency when duplicates exist.
    We keep this local wrapper so older deployments don't crash if the shared helper
    isn't available.
    """
    if _deduplicate_watchlist_items:
        return _deduplicate_watchlist_items(items)

    if not items:
        return []

    def _ts(item: WatchlistItem) -> float:
        value = getattr(item, "updated_at", None) or getattr(item, "modified_at", None) or getattr(item, "created_at", None)
        try:
            return value.timestamp() if value else 0.0
        except Exception:
            return 0.0

    def _key(item: WatchlistItem) -> tuple[str, str]:
        symbol = (getattr(item, "symbol", "") or "").upper()
        exchange = (getattr(item, "exchange", "CRYPTO_COM") or "CRYPTO_COM").upper()
        return symbol, exchange

    grouped: Dict[tuple[str, str], List[WatchlistItem]] = {}
    for it in items:
        k = _key(it)
        if not k[0]:
            continue
        grouped.setdefault(k, []).append(it)

    result: List[WatchlistItem] = []
    for (symbol, exchange), group in grouped.items():
        def _priority(it: WatchlistItem):
            is_deleted = 1 if getattr(it, "is_deleted", False) else 0
            alert_priority = 0 if getattr(it, "alert_enabled", False) else 1
            ts_priority = -_ts(it)
            id_priority = -(getattr(it, "id", 0) or 0)
            return (is_deleted, alert_priority, ts_priority, id_priority)

        chosen = sorted(group, key=_priority)[0]
        if len(group) > 1:
            logger.warning(
                "[WATCHLIST_DUPLICATE_FALLBACK] symbol=%s exchange=%s rows=%s chosen_id=%s",
                symbol,
                exchange,
                len(group),
                getattr(chosen, "id", None),
            )
        result.append(chosen)

    return result


def _select_watchlist_item_for_toggle(db: Session, symbol_upper: str, *, exchange: str = "CRYPTO_COM") -> Optional[WatchlistItem]:
    """
    Pick the safest row to mutate for legacy /watchlist/* toggle endpoints.

    Critical behavior:
    - Prefer ACTIVE row (is_deleted=False) when duplicates exist.
    - Only return a deleted row if no active row exists (safe to restore).
    """
    try:
        q = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
        try:
            q = q.filter(WatchlistItem.exchange == exchange)
        except Exception:
            pass

        # Prefer active rows to avoid unique constraint violations when restoring duplicates.
        try:
            active = (
                q.filter(WatchlistItem.is_deleted == False)
                .order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc())
                .first()
            )
            if active:
                return active
        except Exception:
            # If is_deleted/created_at isn't available, fall back below.
            pass

        try:
            return q.order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc()).first()
        except Exception:
            return q.order_by(WatchlistItem.id.desc()).first()
    except Exception as err:
        logger.warning("Failed selecting watchlist row for %s: %s", symbol_upper, err, exc_info=True)
        return None


CUSTOM_TOP_COINS_TABLE = """
CREATE TABLE IF NOT EXISTS custom_top_coins (
    instrument_name TEXT PRIMARY KEY,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def _get_db_connection() -> sqlite3.Connection:
    # Use /tmp for better permissions compatibility in Docker
    db_path = os.getenv("CUSTOM_COINS_DB_PATH", os.path.join("/tmp", "top_coins.db"))
    # Use a shorter timeout (2 seconds) to prevent blocking
    conn = sqlite3.connect(db_path, timeout=2.0)
    conn.row_factory = sqlite3.Row
    # Set busy timeout to prevent blocking
    conn.execute("PRAGMA busy_timeout = 2000")  # 2 seconds
    # Enable WAL mode for better concurrency
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        # If WAL mode fails, continue without it (some filesystems don't support WAL)
        pass
    return conn


def _ensure_custom_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(CUSTOM_TOP_COINS_TABLE)
    conn.commit()


def _upsert_custom_coin(conn: sqlite3.Connection, instrument_name: str, base_currency: str, quote_currency: str) -> None:
    _ensure_custom_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO custom_top_coins (instrument_name, base_currency, quote_currency)
        VALUES (?, ?, ?)
        """,
        (instrument_name, base_currency, quote_currency),
    )
    conn.commit()


def _delete_custom_coin(conn: sqlite3.Connection, instrument_name: str) -> None:
    _ensure_custom_table(conn)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_top_coins WHERE instrument_name = ?", (instrument_name,))
    conn.commit()


def _fetch_custom_coins(conn: sqlite3.Connection) -> List[Dict]:
    _ensure_custom_table(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT instrument_name, base_currency, quote_currency, created_at
        FROM custom_top_coins
        ORDER BY created_at
        """
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def _split_instrument(instrument: str) -> Tuple[str, str]:
    if "_" not in instrument:
        raise HTTPException(
            status_code=400,
            detail="Instrument name must include an underscore separating base and quote currencies, e.g. BTC_USDT.",
        )
    base, quote = instrument.split("_", 1)
    if not base or not quote:
        raise HTTPException(
            status_code=400,
            detail="Invalid instrument name. Provide both base and quote currencies, e.g. BTC_USDT.",
        )
    return base.upper(), quote.upper()


def _should_disable_auth() -> bool:
    """Check if auth should be disabled (for testing)"""
    return os.getenv("DISABLE_AUTH", "false").lower() == "true"


def _get_auth_dependency():
    """
    Get auth dependency based on DISABLE_AUTH env var.
    This is called by FastAPI at request time when used as: current_user = Depends(_get_auth_dependency)
    
    Returns a callable that FastAPI will execute to get the current user.
    If auth is disabled, returns a callable that returns None.
    If auth is enabled, returns get_current_user directly (which FastAPI will execute).
    """
    if _should_disable_auth():
        # Return a callable that returns None (no auth required)
        def no_auth():
            return None
        return no_auth
    # Return the actual dependency function - FastAPI will call it at request time
    return get_current_user


@router.post("/market/top-coins/custom")
def add_custom_top_coin(
    payload: Dict[str, str] = Body(...),
):
    # No auth required - this endpoint is public for adding coins
    logger.info(f"[ADD_COIN] Received request: {payload}")
    try:
        instrument_name = payload.get("instrument_name") or payload.get("symbol")
        if not instrument_name:
            logger.error("[ADD_COIN] Missing instrument_name")
            raise HTTPException(status_code=400, detail="instrument_name is required")
        instrument_name = instrument_name.upper()
        logger.info(f"[ADD_COIN] Processing: {instrument_name}")

        base_currency = payload.get("base_currency")
        quote_currency = payload.get("quote_currency")

        if base_currency and quote_currency:
            base_currency = base_currency.upper()
            quote_currency = quote_currency.upper()
        else:
            base_currency, quote_currency = _split_instrument(instrument_name)
        
        logger.info(f"[ADD_COIN] Parsed: {instrument_name} = {base_currency}/{quote_currency}")

        conn = None
        try:
            logger.info("[ADD_COIN] Opening database connection")
            conn = _get_db_connection()
            logger.info("[ADD_COIN] Database connection opened")
            _upsert_custom_coin(conn, instrument_name, base_currency, quote_currency)
            logger.info(f"[ADD_COIN] Successfully added {instrument_name}")
            return {
                "ok": True,
                "instrument_name": instrument_name,
                "base_currency": base_currency,
                "quote_currency": quote_currency,
            }
        except Exception as db_error:
            logger.error(f"[ADD_COIN] Database error: {db_error}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Database error: {str(db_error)}")
        finally:
            if conn:
                try:
                    conn.close()
                    logger.info("[ADD_COIN] Database connection closed")
                except Exception as e:
                    logger.warning(f"[ADD_COIN] Error closing connection: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ADD_COIN] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.delete("/market/top-coins/custom/{instrument_name}")
def delete_custom_top_coin(
    instrument_name: str,
    current_user = Depends(_get_auth_dependency),
):
    if not instrument_name:
        raise HTTPException(status_code=400, detail="instrument_name is required")
    instrument_name = instrument_name.upper()

    conn = _get_db_connection()
    try:
        _delete_custom_coin(conn, instrument_name)
        return {"ok": True, "instrument_name": instrument_name}
    finally:
        conn.close()

@router.get("/ohlcv")
def get_ohlcv(
    exchange: str = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Trading symbol"),
    interval: str = Query("1h", description="Time interval"),
    limit: int = Query(100, description="Number of candles"),
    current_user = Depends(get_current_user)
):
    """Get OHLCV (Open, High, Low, Close, Volume) data from exchange"""
    
    if exchange == "CRYPTO_COM":
        try:
            # Crypto.com v2 public API
            # Convert interval to Crypto.com format
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }
            crypto_interval = interval_map.get(interval, "1h")
            
            url = f"https://api.crypto.com/v2/public/get-candlestick"
            params = {
                "instrument_name": symbol,
                "timeframe": crypto_interval,
                "count": limit
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            if "result" in result and "data" in result["result"]:
                data = result["result"]["data"]
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
                
                logger.info(f"Retrieved {len(ohlcv_data)} candles for {symbol}")
                return ohlcv_data
            else:
                logger.error(f"Unexpected response format: {result}")
                raise HTTPException(status_code=502, detail="Invalid response from exchange")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting OHLCV: {e}")
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            logger.error(f"Error getting OHLCV: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    elif exchange == "BINANCE":
        try:
            # Binance public API
            # Convert interval to Binance format
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }
            binance_interval = interval_map.get(interval, "1h")
            
            # Convert symbol format: BTC_USDT -> BTCUSDT
            binance_symbol = symbol.replace("_", "")
            
            url = f"https://api.binance.com/api/v3/klines"
            params = {
                "symbol": binance_symbol,
                "interval": binance_interval,
                "limit": limit
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Convert to standardized format
            ohlcv_data = []
            for candle in data:
                ohlcv_data.append({
                    "t": candle[0],  # timestamp
                    "o": float(candle[1]),  # open
                    "h": float(candle[2]),  # high
                    "l": float(candle[3]),  # low
                    "c": float(candle[4]),  # close
                    "v": float(candle[5])   # volume
                })
            
            logger.info(f"Retrieved {len(ohlcv_data)} candles for {symbol}")
            return ohlcv_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting OHLCV from Binance: {e}")
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:
            logger.error(f"Error getting OHLCV from Binance: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    else:
        raise HTTPException(status_code=400, detail="Unsupported exchange")

@router.get("/ticker")
def get_ticker(
    exchange: str = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Trading symbol"),
    current_user = Depends(get_current_user)
):
    """Get current ticker (price) data"""
    
    if exchange == "CRYPTO_COM":
        try:
            url = f"https://api.crypto.com/v2/public/get-ticker"
            params = {"instrument_name": symbol}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            result = response.json()
            
            if "result" in result and "data" in result["result"]:
                data = result["result"]["data"][0] if result["result"]["data"] else {}
                return {
                    "symbol": symbol,
                    "price": float(data.get("a", 0)),  # last price
                    "volume": float(data.get("v", 0)),  # 24h volume
                    "high": float(data.get("h", 0)),    # 24h high
                    "low": float(data.get("l", 0))      # 24h low
                }
            else:
                raise HTTPException(status_code=502, detail="Invalid response from exchange")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting ticker: {e}")
            raise HTTPException(status_code=502, detail=str(e))
    
    elif exchange == "BINANCE":
        try:
            binance_symbol = symbol.replace("_", "")
            url = f"https://api.binance.com/api/v3/ticker/24hr"
            params = {"symbol": binance_symbol}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            return {
                "symbol": symbol,
                "price": float(data.get("lastPrice", 0)),
                "volume": float(data.get("volume", 0)),
                "high": float(data.get("highPrice", 0)),
                "low": float(data.get("lowPrice", 0))
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error getting ticker from Binance: {e}")
            raise HTTPException(status_code=502, detail=str(e))
    
    else:
        raise HTTPException(status_code=400, detail="Unsupported exchange")

@router.get("/market/top-coins")
def get_top_coins():
    """Get top 20 coins by volume from Crypto.com"""
    start_time = time.time()
    try:
        # Fetch all instruments from Crypto.com
        url = "https://api.crypto.com/exchange/v1/public/get-instruments"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        if "result" in result and "instruments" in result["result"]:
            # Filter for USD pairs and calculate 24h volume
            instruments = []
            for inst in result["result"]["instruments"]:
                instrument_name = inst.get("instrument_name", "")
                quote_currency = inst.get("quote_currency", "")
                base_currency = inst.get("base_currency", "")
                
                # Only include USD/USDT pairs
                if quote_currency in ["USD", "USDT"]:
                    # Get ticker data for volume
                    ticker_url = f"https://api.crypto.com/exchange/v1/public/get-tickers"
                    ticker_resp = requests.get(ticker_url, timeout=10)
                    if ticker_resp.status_code == 200:
                        ticker_data = ticker_resp.json()
                        volume_24h = 0
                        if "result" in ticker_data and "data" in ticker_data["result"]:
                            for ticker in ticker_data["result"]["data"]:
                                if ticker.get("i") == instrument_name:
                                    volume_24h = float(ticker.get("v", 0)) or 0
                                    break
                        
                        if volume_24h > 0:
                            instruments.append({
                                "instrument_name": instrument_name,
                                "base_currency": base_currency,
                                "quote_currency": quote_currency,
                                "status": inst.get("status", ""),
                                "volume_24h": volume_24h
                            })
            
            # Sort by volume descending and get top 20
            instruments.sort(key=lambda x: x["volume_24h"], reverse=True)
            top_20 = instruments[:20]
            
            # Store in SQLite database
            conn = sqlite3.connect("top_coins.db")
            cursor = conn.cursor()
            
            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS top_coins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    instrument_name TEXT UNIQUE NOT NULL,
                    base_currency TEXT,
                    quote_currency TEXT,
                    volume_24h REAL,
                    rank INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Clear and insert top coins
            cursor.execute("DELETE FROM top_coins")
            
            for rank, coin in enumerate(top_20, 1):
                cursor.execute("""
                    INSERT INTO top_coins 
                    (instrument_name, base_currency, quote_currency, volume_24h, rank)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    coin["instrument_name"],
                    coin["base_currency"],
                    coin["quote_currency"],
                    coin["volume_24h"],
                    rank
                ))
            
            conn.commit()
            conn.close()
            
            return {
                "coins": top_20,
                "count": len(top_20)
            }
            
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"❌ Error fetching top coins after {elapsed_time:.2f}s: {e}", exc_info=True)
        # Return empty response instead of raising exception - prevents frontend timeouts
        return {
            "coins": [],
            "count": 0,
            "source": "error",
            "error": str(e),
            "timestamp": time.time()
        }

    # Default fallback if external API returned unexpected payload
    return {
        "coins": [],
        "count": 0,
        "source": "empty",
        "timestamp": time.time()
    }

@router.get("/market/top-coins/from-db")
def get_top_coins_from_db():
    """Get top coins from local database"""
    try:
        conn = sqlite3.connect("top_coins.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT instrument_name, base_currency, quote_currency, volume_24h, rank
            FROM top_coins
            ORDER BY rank
        """)
        
        rows = cursor.fetchall()
        coins = [dict(row) for row in rows]
        
        conn.close()
        
        return {
            "coins": coins,
            "count": len(coins)
        }
        
    except Exception as e:
        logger.error(f"Error fetching top coins from DB: {e}")
        return {"coins": [], "count": 0}

async def update_top_coins_cache():
    """Update the top coins cache with data from external APIs (slow operation)"""
    global _top_coins_cache, _top_coins_cache_timestamp
    import asyncio as async_lib
    
    start_time = time.time()
    logger.info("Starting top coins cache update")
    
    try:
        # Get coins from database (primary list + custom overrides)
        logger.info("Fetching coins from database")
        conn = None
        try:
            conn = _get_db_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM top_coins ORDER BY rank")
            rows = cursor.fetchall()
            coins = [dict(row) for row in rows]
            logger.info(f"Fetched {len(coins)} coins from database")

            custom_coins = _fetch_custom_coins(conn)
            logger.info(f"Fetched {len(custom_coins)} custom coins")
        except Exception as db_error:
            logger.error(f"Database error: {db_error}", exc_info=True)
            coins = []
            custom_coins = []
        finally:
            if conn:
                conn.close()

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
            # Avoid overwriting existing entries fetched from the main table
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

        # Use simple price fetcher for real prices (Crypto.com primary, CoinPaprika backup)
        prices_map = {}
        volume_map = {}
        
        # Get symbols list
        symbols = [coin["instrument_name"] for coin in coins]
        
        # Get prices with simple fetcher - this is the slow part with external API calls
        # Process sequentially with 3s delay between each coin to respect rate limits
        try:
            logger.info(f"Starting price fetch for {len(symbols)} symbols (with 3s delay between each)")
            # Limit the number of symbols to avoid timeouts - set to 10 for balance between speed and data
            max_symbols = 10  # Limit to 10 symbols max to avoid timeout
            if len(symbols) > max_symbols:
                custom_symbols = [coin["instrument_name"] for coin in coins if coin.get("is_custom")]
                non_custom_symbols = [s for s in symbols if s not in custom_symbols]
                selected_symbols: List[str] = []
                
                # Always include custom symbols first
                for s in custom_symbols:
                    if len(selected_symbols) >= max_symbols:
                        break
                    selected_symbols.append(s)
                
                # Fill remaining slots with non-custom symbols (preserve original order)
                for s in non_custom_symbols:
                    if len(selected_symbols) >= max_symbols:
                        break
                    if s not in selected_symbols:
                        selected_symbols.append(s)

                logger.warning(
                    f"Too many symbols ({len(symbols)}), limiting to {max_symbols} for performance "
                    f"(custom={len(custom_symbols)}, final={len(selected_symbols)})"
                )
                symbols = selected_symbols
            
            # Set initial prices to 0 for ALL coins (will be updated if fetch succeeds)
            for coin in coins:
                symbol = coin["instrument_name"]
                prices_map[symbol] = 0.0
                volume_map[symbol] = 0
            
            # Fetch prices sequentially with 3s delay between each coin
            # This is a background task so delays are OK
            price_results = {}
            
            try:
                loop = async_lib.get_running_loop()
            except RuntimeError:
                loop = async_lib.new_event_loop()
                async_lib.set_event_loop(loop)
                
            # Fetch prices one by one with 3s delay between each
            for idx, symbol in enumerate(symbols):
                try:
                    logger.debug(f"Fetching price for {symbol} ({idx + 1}/{len(symbols)})")
                    # Fetch single price in executor to avoid blocking
                    price_result = await loop.run_in_executor(
                        None,
                        price_fetcher.get_price,
                        symbol
                    )
                    price_results[symbol] = price_result
                    
                    if price_result and price_result.success:
                        logger.debug(f"✅ Price for {symbol}: ${price_result.price} from {price_result.source}")
                    else:
                        logger.debug(f"⚠️ Failed to get price for {symbol}, using 0.0")
                    
                    # Wait 3 seconds before next coin (except after the last one)
                    if idx < len(symbols) - 1:
                        await async_lib.sleep(3)
                except Exception as e:
                    logger.warning(f"Error fetching price for {symbol}: {e}")
                    price_results[symbol] = None
            
            logger.info(f"Finished price fetch for {len(symbols)} symbols, got {len(price_results)} results")
            
            # Process results
            for coin in coins:
                symbol = coin["instrument_name"]
                price_result = price_results.get(symbol)
                
                if price_result and price_result.success:
                    prices_map[symbol] = price_result.price
                    volume_map[symbol] = price_result.price * 1000000  # Mock volume
                else:
                    if symbol not in prices_map:
                        prices_map[symbol] = 0.0
                        volume_map[symbol] = 0
                    
        except Exception as e:
            logger.error(f"Error in simple price fetching: {e}")
            # Use 0.0 for all symbols on error
            for coin in coins:
                symbol = coin["instrument_name"]
                if symbol not in prices_map:
                    prices_map[symbol] = 0.0
                    volume_map[symbol] = 0
        
        # Enrich coins with prices and volumes
        enriched_coins = []
        for coin in coins:
            instrument = coin["instrument_name"]
            # Ensure all values are JSON-serializable
            updated_at = coin.get("updated_at")
            if updated_at and not isinstance(updated_at, str):
                updated_at = str(updated_at)
            
            enriched_coin = {
                "rank": int(coin.get("rank", 0)) if coin.get("rank") else 0,
                "instrument_name": str(instrument),
                "base_currency": str(coin.get("base_currency", "")),
                "quote_currency": str(coin.get("quote_currency", "")),
                "current_price": float(prices_map.get(instrument, 0)),
                "volume_24h": float(volume_map.get(instrument, coin.get("volume_24h") or 0)),
                "updated_at": str(updated_at) if updated_at else None,
                "is_custom": bool(coin.get("is_custom", False)),
            }
            enriched_coins.append(enriched_coin)
        
        # Update global cache
        _top_coins_cache = {
            "coins": enriched_coins,
            "count": len(enriched_coins)
        }
        _top_coins_cache_timestamp = time.time()
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Updated top coins cache, {len(enriched_coins)} items, took {elapsed:.2f} seconds")
        
    except Exception as e:
        logger.error(f"Error updating top coins cache: {e}", exc_info=True)
        # On error, keep existing cache or set empty cache
        if _top_coins_cache is None:
            _top_coins_cache = {"coins": [], "count": 0}
            _top_coins_cache_timestamp = time.time()


@router.post("/market/update-cache")
async def trigger_cache_update():
    """Manually trigger cache update (for testing/debugging)
    
    Note: In production, use the separate market_updater.py worker process instead.
    This endpoint is kept for manual testing only.
    """
    try:
        logger.info("Manual cache update triggered via API")
        # Use the updater function from market_updater module
        from market_updater import update_market_data
        await update_market_data()
        
        # Load updated cache to return info
        from market_cache_storage import load_cache_from_storage
        cache_data = load_cache_from_storage()
        
        if cache_data:
            return {
                "ok": True,
                "message": "Cache updated successfully",
                "count": cache_data.get("count", 0),
                "cache_age": cache_data.get("cache_age", 0)
            }
        else:
            return {
                "ok": True,
                "message": "Cache update completed but no data available",
                "count": 0,
                "cache_age": 0
            }
    except Exception as e:
        logger.error(f"Error triggering cache update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/top-coins-data")
def get_top_coins_with_prices(
    db: Session = Depends(get_db),
    current_user = Depends(_get_auth_dependency)
):
    """Get top coins with current prices from database (fast response <100ms)
    
    This endpoint ONLY reads from database and NEVER calls external APIs.
    The market_updater.py worker process is responsible for updating the database every 60 seconds.
    Falls back to JSON cache if database is empty.
    
    OPTIMIZED: Added timing and error handling for fast, reliable response.
    CRITICAL: This endpoint must respond quickly to avoid 504 Gateway Timeout errors.
    """
    import time as time_module
    start_time = time_module.time()
    
    # CRITICAL: Set a maximum execution time to prevent hanging
    MAX_EXECUTION_TIME = 5.0  # 5 seconds max
    try:
        # Try to get data from database first (fast)
        if db:
            try:
                from app.models.market_price import MarketPrice, MarketData
                
                # CRITICAL CHANGE: Start from watchlist_items (is_deleted=False) instead of MarketPrice
                # This ensures ALL non-deleted watchlist coins are shown, even if they don't have prices yet
                from app.models.watchlist import WatchlistItem
                
                # Get all watchlist items that are NOT deleted (this is the source of truth)
                # OPTIMIZATION: Query all columns at once to avoid lazy loading
                watchlist_query = db.query(WatchlistItem).filter(
                    WatchlistItem.is_deleted == False
                )
                all_watchlist_items = watchlist_query.all()
                canonical_watchlist_items = deduplicate_watchlist_items(all_watchlist_items)
                if len(canonical_watchlist_items) < len(all_watchlist_items):
                    logger.warning(
                        "[TOP_COINS] deduplicated watchlist rows %s -> %s",
                        len(all_watchlist_items),
                        len(canonical_watchlist_items),
                    )
                
                logger.debug(
                    "Found %s canonical non-deleted watchlist items (raw rows=%s)",
                    len(canonical_watchlist_items),
                    len(all_watchlist_items),
                )
                
                # Get all MarketPrice entries for price data - OPTIMIZED: only get what we need
                market_prices_all = db.query(MarketPrice).all()
                market_price_map = {mp.symbol: mp for mp in market_prices_all}
                
                # Get all MarketData entries for technical indicators - OPTIMIZED: batch query
                all_symbols = [item.symbol for item in canonical_watchlist_items]
                market_data_list = []
                if all_symbols:
                    # Use single query instead of chunks for better performance
                    market_data_list = db.query(MarketData).filter(MarketData.symbol.in_(all_symbols)).all()
                
                data_map = {md.symbol: md for md in market_data_list}
                
                # Build coins list from watchlist_items (not from MarketPrice)
                # This ensures ALL non-deleted coins are shown
                coins = []
                for watchlist_item in canonical_watchlist_items:
                    symbol = watchlist_item.symbol
                    
                    # Get MarketPrice if available (for price and volume)
                    mp = market_price_map.get(symbol)
                    md = data_map.get(symbol)
                    
                    # Use MarketPrice data if available, otherwise use watchlist_item data or defaults
                    current_price = (mp.price if mp and mp.price else watchlist_item.price) or 0.0
                    volume_24h = (mp.volume_24h if mp and mp.volume_24h else 0.0) or 0.0
                    
                    # Use MarketData indicators if available, otherwise fall back to watchlist_item data
                    # OPTIMIZATION: Access watchlist_item attributes directly (already loaded, no lazy loading)
                    rsi = md.rsi if md and md.rsi is not None else (watchlist_item.rsi if hasattr(watchlist_item, 'rsi') and watchlist_item.rsi is not None else None)
                    ma50 = md.ma50 if md and md.ma50 is not None else (watchlist_item.ma50 if hasattr(watchlist_item, 'ma50') and watchlist_item.ma50 is not None else None)
                    ma200 = md.ma200 if md and md.ma200 is not None else (watchlist_item.ma200 if hasattr(watchlist_item, 'ma200') and watchlist_item.ma200 is not None else None)
                    ema10 = md.ema10 if md and md.ema10 is not None else (watchlist_item.ema10 if hasattr(watchlist_item, 'ema10') and watchlist_item.ema10 is not None else None)
                    atr = md.atr if md and md.atr is not None else (watchlist_item.atr if hasattr(watchlist_item, 'atr') and watchlist_item.atr is not None else None)
                    res_up = md.res_up if md and md.res_up is not None else (watchlist_item.res_up if hasattr(watchlist_item, 'res_up') and watchlist_item.res_up is not None else None)
                    res_down = md.res_down if md and md.res_down is not None else (watchlist_item.res_down if hasattr(watchlist_item, 'res_down') and watchlist_item.res_down is not None else None)
                    
                    # Ensure MA10w has a valid value - use fallbacks if needed
                    ma10w = None
                    if md and md.ma10w is not None and md.ma10w > 0:
                        ma10w = md.ma10w
                    elif ma200 and ma200 > 0:
                        ma10w = ma200  # Use MA200 as fallback
                    elif ma50 and ma50 > 0:
                        ma10w = ma50  # Use MA50 as fallback
                    elif current_price > 0:
                        ma10w = current_price  # Use current price as last resort
                    
                    # Mark as custom if it's a user-added coin (has watchlist_item with custom config)
                    # For now, all coins in watchlist are considered "custom" since they're user-tracked
                    is_custom = True  # All watchlist coins are user-tracked
                    
                    # Get updated_at from MarketPrice if available, otherwise from watchlist_item
                    # OPTIMIZATION: Safe datetime serialization
                    updated_at = None
                    try:
                        if mp and hasattr(mp, 'updated_at') and mp.updated_at:
                            if hasattr(mp.updated_at, 'isoformat'):
                                updated_at = mp.updated_at.isoformat()
                            else:
                                updated_at = str(mp.updated_at)
                        elif hasattr(watchlist_item, 'created_at') and watchlist_item.created_at:
                            if hasattr(watchlist_item.created_at, 'isoformat'):
                                updated_at = watchlist_item.created_at.isoformat()
                            else:
                                updated_at = str(watchlist_item.created_at)
                    except Exception as dt_err:
                        logger.debug(f"Error serializing datetime for {symbol}: {dt_err}")
                        updated_at = None
                    
                    # Calculate trading signal (BUY/WAIT/SELL)
                    signal = "WAIT"
                    strategy_state = None  # FIX: Initialize strategy_state to None
                    resolved_strategy_type = None
                    resolved_risk_approach = None
                    try:
                        if current_price and current_price > 0:
                            
                            # Get buy_target and last_buy_price from watchlist_item if available
                            buy_target = watchlist_item.buy_target if watchlist_item else None
                            last_buy_price = watchlist_item.purchase_price if watchlist_item and watchlist_item.purchase_price and watchlist_item.purchase_price > 0 else None
                            
                            strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
                            # Expose backend-resolved profile to frontend for consistent tooltips.
                            resolved_strategy_type = strategy_type
                            resolved_risk_approach = risk_approach

                            # CRITICAL: Use current_volume (hourly) for signal calculation, not volume_24h
                            # This ensures consistent signal calculation across all endpoints
                            # IMPORTANT: Keep displayed volume and signal volume consistent.
                            # If MarketData has stale/zero current_volume, fall back to volume_24h/24 for BOTH signal + UI.
                            current_volume_for_signals = None
                            if md and md.current_volume is not None and md.current_volume > 0:
                                current_volume_for_signals = md.current_volume
                            elif volume_24h and volume_24h > 0:
                                # Fallback: approximate current_volume from volume_24h / 24
                                current_volume_for_signals = volume_24h / 24.0

                            avg_volume_for_signals = None
                            if md and md.avg_volume is not None and md.avg_volume > 0:
                                avg_volume_for_signals = md.avg_volume
                            elif volume_24h and volume_24h > 0:
                                # Fallback: approximate avg_volume when MarketData is missing (keeps volume_ratio consistent)
                                avg_volume_for_signals = volume_24h / 24.0

                            signals = calculate_trading_signals(
                                symbol=symbol,
                                price=current_price,
                                rsi=rsi,
                                atr14=atr,
                                ma50=ma50,
                                ma200=ma200,
                                ema10=ema10,
                                ma10w=ma10w,
                                volume=current_volume_for_signals,  # CRITICAL: Use current_volume (hourly), not volume_24h
                                avg_volume=avg_volume_for_signals,
                                resistance_up=res_up,
                                buy_target=buy_target,
                                last_buy_price=last_buy_price,
                                position_size_usd=watchlist_item.trade_amount_usd if watchlist_item and watchlist_item.trade_amount_usd else 100.0,
                                rsi_buy_threshold=40,
                                rsi_sell_threshold=70,
                                strategy_type=strategy_type,
                                risk_approach=risk_approach,
                            )
                            
                            if signals.get("buy_signal"):
                                signal = "BUY"
                            elif signals.get("sell_signal"):
                                signal = "SELL"
                            else:
                                signal = "WAIT"
                            
                            # FIX: Extract strategy_state from signals result for frontend
                            strategy_state = signals.get("strategy") if signals else None
                    except Exception as sig_err:
                        logger.debug(f"Could not calculate signal for {symbol}: {sig_err}")
                        signal = "WAIT"  # Default to WAIT on error
                        strategy_state = None  # FIX: Ensure strategy_state is None on error
                    
                    # Volume data from MarketData
                    # OPTIMIZATION: Use MarketData values directly instead of fetching OHLCV for each symbol
                    # This avoids making 20+ external API calls per request, which was causing 5+ second timeouts
                    # The market_updater service already updates MarketData with fresh volume data every 60 seconds
                    # Keep volume fields consistent with signal fallbacks (prevents "0.00x volume but BUY signal").
                    current_volume_value = None
                    if md and md.current_volume is not None and md.current_volume > 0:
                        current_volume_value = md.current_volume
                    elif volume_24h and volume_24h > 0:
                        current_volume_value = volume_24h / 24.0

                    avg_volume_value = None
                    if md and md.avg_volume is not None and md.avg_volume > 0:
                        avg_volume_value = md.avg_volume
                    elif volume_24h and volume_24h > 0:
                        avg_volume_value = volume_24h / 24.0
                    
                    # Only fetch fresh volume if MarketData is missing or stale (>5 minutes old)
                    # This is a rare fallback case, not the common path
                    if (current_volume_value is None or avg_volume_value is None) and len(canonical_watchlist_items) < 10:
                        # Only fetch for small watchlists to avoid timeouts
                        try:
                            from market_updater import fetch_ohlcv_data
                            from app.api.routes_signals import calculate_volume_index
                            ohlcv_data = fetch_ohlcv_data(symbol, "1h", limit=11)
                            if ohlcv_data and len(ohlcv_data) > 0:
                                volumes = [candle.get("v", 0) for candle in ohlcv_data if candle.get("v", 0) > 0]
                                if len(volumes) >= 11:
                                    # Recalculate volume index with fresh data - this is the source of truth
                                    volume_index = calculate_volume_index(volumes, period=5)
                                    fresh_current_volume = volume_index.get("current_volume")
                                    fresh_avg_volume = volume_index.get("average_volume")
                                    
                                    # Use fresh values if available, otherwise fall back to DB values
                                    if fresh_current_volume and fresh_current_volume > 0:
                                        current_volume_value = fresh_current_volume
                                    if fresh_avg_volume and fresh_avg_volume > 0:
                                        avg_volume_value = fresh_avg_volume
                                    
                                    logger.debug(f"Fresh volume data for {symbol}: current={current_volume_value}, avg={avg_volume_value}")
                        except Exception as vol_err:
                            logger.debug(f"Could not fetch fresh volume for {symbol}: {vol_err}")
                    
                    # Calculate volume_ratio - always recalculate from current values to ensure accuracy
                    # CRITICAL: If current_volume is 0.0, volume_ratio must be 0.0 (not None) to avoid frontend fallback calculations
                    volume_ratio_value = None
                    if current_volume_value is not None and avg_volume_value is not None and avg_volume_value > 0:
                        # Always recalculate ratio from current values (including when current_volume is 0.0)
                        volume_ratio_value = current_volume_value / avg_volume_value if current_volume_value > 0 else 0.0
                    elif md and md.volume_ratio is not None:
                        # Use stored ratio only if we don't have current values
                        volume_ratio_value = md.volume_ratio
                    
                    coin = {
                        "instrument_name": symbol,
                        "current_price": current_price,
                        "volume_24h": volume_24h,
                        "source": mp.source if mp else "watchlist",
                        "updated_at": updated_at,
                        # Technical indicators (prefer MarketData, fallback to watchlist_item)
                        "rsi": rsi,
                        "ma50": ma50,
                        "ma200": ma200,
                        "ema10": ema10,
                        "ma10w": ma10w,
                        "atr": atr,
                        # Volume data from MarketData (with fallback to last available volume)
                        # CRITICAL: Use avg_volume_value (which may have been updated with fresh data) not md.avg_volume
                        "current_volume": current_volume_value,
                        "avg_volume": avg_volume_value,
                        "volume_ratio": volume_ratio_value,
                        # Resistance levels
                        "res_up": res_up,
                        "res_down": res_down,
                        # Trading signal (BUY/WAIT/SELL)
                        "signal": signal,
                        # FIX: Include strategy_state with buy_volume_ok for frontend
                        "strategy_state": strategy_state,
                        # CANONICAL: expose backend-resolved strategy profile for UI consistency
                        "strategy_profile": {
                            "preset": getattr(resolved_strategy_type, "value", None),
                            "approach": getattr(resolved_risk_approach, "value", None),
                        },
                        # Mark as custom if user-added to watchlist
                        "is_custom": is_custom,
                        # Alert enabled status - include all alert flags for frontend
                        "alert_enabled": watchlist_item.alert_enabled if watchlist_item else False,
                        "buy_alert_enabled": getattr(watchlist_item, "buy_alert_enabled", False) if watchlist_item else False,
                        "sell_alert_enabled": getattr(watchlist_item, "sell_alert_enabled", False) if watchlist_item else False,
                    }
                    coins.append(coin)
                
                elapsed_time = time_module.time() - start_time
                logger.info(
                    "✅ Built %s coins from %s canonical watchlist items (raw_rows=%s, enriched with %s MarketPrice entries, %s MarketData entries) in %.3fs",
                    len(coins),
                    len(canonical_watchlist_items),
                    len(all_watchlist_items),
                    len(market_price_map),
                    len(market_data_list),
                    elapsed_time,
                )
                
                # Check if we're taking too long
                if elapsed_time > MAX_EXECUTION_TIME:
                    logger.error(f"❌ CRITICAL: Top coins data fetch took {elapsed_time:.3f}s - exceeds max {MAX_EXECUTION_TIME}s! Returning partial data to avoid timeout.")
                    # Return what we have so far to avoid timeout
                    return {
                        "coins": coins[:len(coins)],  # Return all coins we've built
                        "count": len(coins),
                        "source": "database",
                        "timestamp": time.time(),
                        "warning": f"Response took {elapsed_time:.3f}s - may be incomplete"
                    }
                
                if elapsed_time > 0.5:
                    logger.warning(f"⚠️ Top coins data fetch took {elapsed_time:.3f}s - this is slow! Should be < 0.3 seconds. Consider optimizing database queries or adding indexes.")
                elif elapsed_time > 1.0:
                    logger.error(f"❌ Top coins data fetch took {elapsed_time:.3f}s - this is VERY slow! Check for blocking operations.")
                
                return {
                    "coins": coins,
                    "count": len(coins),
                    "source": "database",
                    "timestamp": time.time()
                }
            except Exception as db_err:
                logger.warning(f"Database read failed, falling back to JSON cache: {db_err}")
        else:
            logger.debug("Database not available, falling back to JSON cache")
        
        # Fallback to JSON cache if database didn't have data
        try:
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            from market_cache_storage import load_cache_from_storage, get_empty_cache_response
            
            # Load cache from shared storage (JSON file)
            cache_data = load_cache_from_storage()
            
            if cache_data is None:
                logger.info("Served top coins from cache: empty-cache (no data yet)")
                return get_empty_cache_response()
            
            # Calculate cache age if timestamp exists
            cache_age = cache_data.get("cache_age", 0)
            if "timestamp" in cache_data:
                cache_age = time.time() - cache_data["timestamp"]
            
            logger.debug(f"Served top coins from JSON cache, age={cache_age:.1f}s, count={cache_data.get('count', 0)}")
            
            elapsed_time = time_module.time() - start_time
            logger.info(f"✅ Top coins data fetched in {elapsed_time:.2f}s: {cache_data.get('count', 0)} coins from cache")
            
            if elapsed_time > 1.0:
                logger.warning(f"⚠️ Top coins data fetch took {elapsed_time:.2f}s - this is slow! Should be < 0.5 seconds")
            
            # Return cached data with explicit structure (fast response - no external API calls)
            # This ensures proper JSON serialization
            return {
                "coins": cache_data.get("coins", []),
                "count": cache_data.get("count", 0),
                "source": "cache",
                "timestamp": time.time(),
                "cache_age": cache_age
            }
        except Exception as cache_err:
            logger.error(f"Error loading top coins cache: {cache_err}", exc_info=True)
            # Return empty response on error
            try:
                from market_cache_storage import get_empty_cache_response
                return get_empty_cache_response()
            except Exception:
                return {"coins": [], "count": 0, "source": "error", "timestamp": time.time()}
            
    except Exception as e:
        elapsed_time = time_module.time() - start_time
        logger.error(f"❌ Error in get_top_coins_with_prices after {elapsed_time:.2f}s: {e}", exc_info=True)
        # Return empty response on error (prevents frontend timeouts)
        try:
            from market_cache_storage import get_empty_cache_response
            return get_empty_cache_response()
        except Exception as cache_err:
            logger.error(f"Error getting empty cache response: {cache_err}")
            return {"coins": [], "count": 0, "source": "error", "timestamp": time.time()}


@router.put("/watchlist/{symbol}/alert")
def update_watchlist_alert(
    symbol: str,
    payload: Dict[str, bool] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(_get_auth_dependency)
):
    """Update alert_enabled for a watchlist item (legacy endpoint - kept for backward compatibility)"""
    import time
    start_time = time.time()
    symbol_upper = symbol.upper()
    
    try:
        if db is None:
            logger.error(f"Database session is None for {symbol_upper}")
            raise HTTPException(status_code=503, detail="Database connection unavailable")
        
        alert_enabled = payload.get("alert_enabled", False)
        logger.info(f"🔄 [ALERT UPDATE] Starting update for {symbol_upper}: alert_enabled={alert_enabled}")
        
        # Find or create watchlist item with timeout protection.
        # IMPORTANT: Prefer active row to avoid restoring a deleted duplicate (unique violation).
        query_start = time.time()
        watchlist_item = _select_watchlist_item_for_toggle(db, symbol_upper)
        query_elapsed = time.time() - query_start
        logger.debug(f"Query elapsed for {symbol_upper}: {query_elapsed:.3f}s")
        
        if not watchlist_item:
            # Create new watchlist item if it doesn't exist
            logger.info(f"Creating new watchlist item for {symbol_upper}")
            watchlist_item = WatchlistItem(
                symbol=symbol_upper,
                exchange="CRYPTO_COM",
                is_deleted=False,
                alert_enabled=alert_enabled
            )
            db.add(watchlist_item)
        else:
            # If item is deleted, reactivate it first (safe: we only select deleted when no active exists).
            if hasattr(watchlist_item, "is_deleted") and watchlist_item.is_deleted:
                watchlist_item.is_deleted = False
            # Update existing item - set both buy and sell to match legacy behavior
            watchlist_item.alert_enabled = alert_enabled
            if hasattr(watchlist_item, "buy_alert_enabled"):
                watchlist_item.buy_alert_enabled = alert_enabled
            if hasattr(watchlist_item, "sell_alert_enabled"):
                watchlist_item.sell_alert_enabled = alert_enabled
        
        # Commit with timeout protection
        commit_start = time.time()
        try:
            db.commit()
        except IntegrityError as ie:
            # Duplicate restore attempt: fallback to canonical active row and retry update.
            db.rollback()
            err_text = str(getattr(ie, "orig", ie))
            if "uq_watchlist_symbol_exchange_active" in err_text or "watchlist_symbol_exchange_active" in err_text or "duplicate key" in err_text:
                logger.warning("⚠️ [ALERT UPDATE] Unique violation for %s, retrying on active canonical row: %s", symbol_upper, err_text)
                canonical = _select_watchlist_item_for_toggle(db, symbol_upper)
                if canonical and not getattr(canonical, "is_deleted", False):
                    canonical.alert_enabled = alert_enabled
                    if hasattr(canonical, "buy_alert_enabled"):
                        canonical.buy_alert_enabled = alert_enabled
                    if hasattr(canonical, "sell_alert_enabled"):
                        canonical.sell_alert_enabled = alert_enabled
                    db.commit()
                    watchlist_item = canonical
                else:
                    raise HTTPException(status_code=409, detail=f"Duplicate active watchlist row exists for {symbol_upper}; toggle rejected.")
            else:
                raise
        commit_elapsed = time.time() - commit_start
        logger.debug(f"Commit elapsed for {symbol_upper}: {commit_elapsed:.3f}s")
        
        try:
            db.refresh(watchlist_item)
        except Exception as refresh_err:
            logger.warning("Failed to refresh watchlist item %s after alert update: %s", symbol_upper, refresh_err)
        
        total_elapsed = time.time() - start_time
        logger.info(f"✅ [ALERT UPDATE] Updated alert_enabled for {symbol_upper}: {alert_enabled} (took {total_elapsed:.3f}s)")
        _log_alert_state("LEGACY ALERT UPDATE", watchlist_item)
        
        return {
            "ok": True,
            "symbol": symbol_upper,
            "alert_enabled": alert_enabled
        }
    except HTTPException:
        raise
    except Exception as e:
        total_elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"❌ [ALERT UPDATE] Error updating alert_enabled for {symbol_upper} after {total_elapsed:.3f}s: {error_msg}", exc_info=True)
        try:
            db.rollback()
        except Exception as rollback_err:
            logger.warning(f"Failed to rollback for {symbol_upper}: {rollback_err}")
        
        # Provide more helpful error messages
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(status_code=504, detail=f"Database operation timed out for {symbol_upper}. Please try again.")
        elif "lock" in error_msg.lower() or "deadlock" in error_msg.lower():
            raise HTTPException(status_code=503, detail=f"Database is busy. Please try again in a moment.")
        else:
            raise HTTPException(status_code=500, detail=f"Error updating alert for {symbol_upper}: {error_msg}")


@router.put("/watchlist/{symbol}/buy-alert")
def update_buy_alert(
    symbol: str,
    payload: Dict[str, bool] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(_get_auth_dependency)
):
    """Update buy_alert_enabled for a watchlist item"""
    symbol_upper = symbol.upper()
    logger.info(f"🔄 [BUY ALERT] Request received for {symbol_upper}: payload={payload}")
    
    try:
        buy_alert_enabled = payload.get("buy_alert_enabled", False)
        
        # Find or create watchlist item (prefer active canonical row).
        watchlist_item = _select_watchlist_item_for_toggle(db, symbol_upper)
        
        # Track previous state to detect toggle
        old_buy_alert_enabled = getattr(watchlist_item, "buy_alert_enabled", False) if watchlist_item else False
        
        if not watchlist_item:
            # Create new watchlist item if it doesn't exist
            logger.info(f"📝 [BUY ALERT] Creating new watchlist item for {symbol_upper}")
            watchlist_item = WatchlistItem(
                symbol=symbol_upper,
                exchange="CRYPTO_COM",
                is_deleted=False,
                alert_enabled=buy_alert_enabled  # Master switch follows buy alert
            )
            # Set buy/sell alert fields (will work even if columns don't exist yet - SQLAlchemy handles it)
            try:
                watchlist_item.buy_alert_enabled = buy_alert_enabled
            except AttributeError:
                logger.warning(f"⚠️ [BUY ALERT] buy_alert_enabled column not found for {symbol_upper}")
                pass  # Column doesn't exist yet, will be added by migration
            try:
                watchlist_item.sell_alert_enabled = False
            except AttributeError:
                pass  # Column doesn't exist yet, will be added by migration
            db.add(watchlist_item)
        else:
            # If item is deleted, reactivate it first (safe: selected only if no active exists).
            if hasattr(watchlist_item, "is_deleted") and watchlist_item.is_deleted:
                logger.info(f"♻️ [BUY ALERT] Reactivating deleted watchlist item for {symbol_upper} (no active row existed)")
                watchlist_item.is_deleted = False
            # Update existing item
            if hasattr(watchlist_item, "buy_alert_enabled"):
                watchlist_item.buy_alert_enabled = buy_alert_enabled
            # Update master alert_enabled if either buy or sell is enabled
            if hasattr(watchlist_item, "sell_alert_enabled"):
                watchlist_item.alert_enabled = buy_alert_enabled or watchlist_item.sell_alert_enabled
            else:
                watchlist_item.alert_enabled = buy_alert_enabled
        
        try:
            db.commit()
        except IntegrityError as ie:
            db.rollback()
            err_text = str(getattr(ie, "orig", ie))
            if "uq_watchlist_symbol_exchange_active" in err_text or "watchlist_symbol_exchange_active" in err_text or "duplicate key" in err_text:
                logger.warning("⚠️ [BUY ALERT] Unique violation for %s, retrying on active canonical row: %s", symbol_upper, err_text)
                canonical = _select_watchlist_item_for_toggle(db, symbol_upper)
                if canonical and not getattr(canonical, "is_deleted", False):
                    if hasattr(canonical, "buy_alert_enabled"):
                        canonical.buy_alert_enabled = buy_alert_enabled
                    if hasattr(canonical, "sell_alert_enabled"):
                        canonical.alert_enabled = buy_alert_enabled or bool(getattr(canonical, "sell_alert_enabled", False))
                    else:
                        canonical.alert_enabled = buy_alert_enabled
                    db.commit()
                    watchlist_item = canonical
                else:
                    raise HTTPException(status_code=409, detail=f"Duplicate active watchlist row exists for {symbol_upper}; toggle rejected.")
            else:
                raise
        logger.debug(f"✅ [BUY ALERT] Database commit successful for {symbol_upper}")
        
        try:
            db.refresh(watchlist_item)
        except Exception as refresh_err:
            logger.warning(f"⚠️ [BUY ALERT] Failed to refresh watchlist item {symbol_upper} after update: {refresh_err}")
        
        # Reset throttle state when toggling alert status
        if old_buy_alert_enabled != buy_alert_enabled:
            try:
                # Resolve strategy_key for this symbol
                strategy_type, risk_approach = resolve_strategy_profile(symbol_upper, db, watchlist_item)
                strategy_key = build_strategy_key(strategy_type, risk_approach)
                
                # Reset throttle state for BUY side (always reset on any toggle)
                reset_throttle_state(db, symbol=symbol_upper, strategy_key=strategy_key, side="BUY")
                logger.info(f"🔄 [BUY ALERT] Reset throttle state for {symbol_upper} BUY (strategy: {strategy_key})")
                
                if buy_alert_enabled:
                    # Enabling: set force flag to allow immediate signal on next evaluation
                    set_force_next_signal(db, symbol=symbol_upper, strategy_key=strategy_key, side="BUY", enabled=True)
                    logger.info(f"⚡ [BUY ALERT] Set force_next_signal for {symbol_upper} BUY - next evaluation will bypass throttle")
                else:
                    # Disabling: ensure force flag is cleared
                    set_force_next_signal(db, symbol=symbol_upper, strategy_key=strategy_key, side="BUY", enabled=False)
                    logger.info(f"🔄 [BUY ALERT] Cleared force_next_signal for {symbol_upper} BUY")
            except Exception as throttle_err:
                # Log but don't fail the toggle operation
                logger.warning(f"⚠️ [BUY ALERT] Failed to reset throttle state for {symbol_upper}: {throttle_err}", exc_info=True)
        
        logger.info(f"✅ Updated buy_alert_enabled for {symbol_upper}: {buy_alert_enabled}")
        _log_alert_state("BUY ALERT UPDATE", watchlist_item)
        
        return {
            "ok": True,
            "symbol": symbol_upper,
            "buy_alert_enabled": buy_alert_enabled,
            "alert_enabled": watchlist_item.alert_enabled,
            "message": f"BUY alert {'enabled' if buy_alert_enabled else 'disabled'} for {symbol_upper}"
        }
    except HTTPException:
        # Re-raise HTTP exceptions (e.g., from auth)
        raise
    except Exception as e:
        logger.error(f"❌ [BUY ALERT] Error updating buy_alert_enabled for {symbol_upper}: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception as rollback_err:
            logger.error(f"❌ [BUY ALERT] Failed to rollback transaction for {symbol_upper}: {rollback_err}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/watchlist/{symbol}/sell-alert")
def update_sell_alert(
    symbol: str,
    payload: Dict[str, bool] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(_get_auth_dependency)
):
    """Update sell_alert_enabled for a watchlist item"""
    symbol_upper = symbol.upper()
    logger.info(f"🔄 [SELL ALERT] Request to update {symbol_upper}: payload={payload}")
    
    try:
        sell_alert_enabled = payload.get("sell_alert_enabled", False)
        
        # Find or create watchlist item (prefer active canonical row).
        watchlist_item = _select_watchlist_item_for_toggle(db, symbol_upper)
        
        # Track previous state to detect toggle
        old_sell_alert_enabled = getattr(watchlist_item, "sell_alert_enabled", False) if watchlist_item else False
        
        if not watchlist_item:
            # Create new watchlist item if it doesn't exist
            logger.info(f"📝 [SELL ALERT] Creating new watchlist item for {symbol_upper}")
            watchlist_item = WatchlistItem(
                symbol=symbol_upper,
                exchange="CRYPTO_COM",
                is_deleted=False,
                alert_enabled=sell_alert_enabled  # Master switch follows sell alert
            )
            # Set buy/sell alert fields (will work even if columns don't exist yet - SQLAlchemy handles it)
            try:
                watchlist_item.buy_alert_enabled = False
            except AttributeError:
                pass  # Column doesn't exist yet, will be added by migration
            try:
                watchlist_item.sell_alert_enabled = sell_alert_enabled
            except AttributeError:
                logger.warning(f"⚠️ [SELL ALERT] sell_alert_enabled column not found for {symbol_upper}")
                pass  # Column doesn't exist yet, will be added by migration
            db.add(watchlist_item)
        else:
            # If item is deleted, reactivate it first (safe: selected only if no active exists).
            if hasattr(watchlist_item, "is_deleted") and watchlist_item.is_deleted:
                logger.info(f"♻️ [SELL ALERT] Reactivating deleted watchlist item for {symbol_upper} (no active row existed)")
                watchlist_item.is_deleted = False
            # Update existing item
            if hasattr(watchlist_item, "sell_alert_enabled"):
                watchlist_item.sell_alert_enabled = sell_alert_enabled
            # Update master alert_enabled if either buy or sell is enabled
            if hasattr(watchlist_item, "buy_alert_enabled"):
                watchlist_item.alert_enabled = watchlist_item.buy_alert_enabled or sell_alert_enabled
            else:
                watchlist_item.alert_enabled = sell_alert_enabled
        
        try:
            db.commit()
        except IntegrityError as ie:
            db.rollback()
            err_text = str(getattr(ie, "orig", ie))
            if "uq_watchlist_symbol_exchange_active" in err_text or "watchlist_symbol_exchange_active" in err_text or "duplicate key" in err_text:
                logger.warning("⚠️ [SELL ALERT] Unique violation for %s, retrying on active canonical row: %s", symbol_upper, err_text)
                canonical = _select_watchlist_item_for_toggle(db, symbol_upper)
                if canonical and not getattr(canonical, "is_deleted", False):
                    if hasattr(canonical, "sell_alert_enabled"):
                        canonical.sell_alert_enabled = sell_alert_enabled
                    if hasattr(canonical, "buy_alert_enabled"):
                        canonical.alert_enabled = bool(getattr(canonical, "buy_alert_enabled", False)) or sell_alert_enabled
                    else:
                        canonical.alert_enabled = sell_alert_enabled
                    db.commit()
                    watchlist_item = canonical
                else:
                    raise HTTPException(status_code=409, detail=f"Duplicate active watchlist row exists for {symbol_upper}; toggle rejected.")
            else:
                raise
        logger.debug(f"✅ [SELL ALERT] Database commit successful for {symbol_upper}")
        
        try:
            db.refresh(watchlist_item)
        except Exception as refresh_err:
            logger.warning(f"⚠️ [SELL ALERT] Failed to refresh watchlist item {symbol_upper} after update: {refresh_err}")
        
        # Reset throttle state when toggling alert status
        if old_sell_alert_enabled != sell_alert_enabled:
            try:
                # Resolve strategy_key for this symbol
                strategy_type, risk_approach = resolve_strategy_profile(symbol_upper, db, watchlist_item)
                strategy_key = build_strategy_key(strategy_type, risk_approach)
                
                # Reset throttle state for SELL side (always reset on any toggle)
                reset_throttle_state(db, symbol=symbol_upper, strategy_key=strategy_key, side="SELL")
                logger.info(f"🔄 [SELL ALERT] Reset throttle state for {symbol_upper} SELL (strategy: {strategy_key})")
                
                if sell_alert_enabled:
                    # Enabling: set force flag to allow immediate signal on next evaluation
                    set_force_next_signal(db, symbol=symbol_upper, strategy_key=strategy_key, side="SELL", enabled=True)
                    logger.info(f"⚡ [SELL ALERT] Set force_next_signal for {symbol_upper} SELL - next evaluation will bypass throttle")
                else:
                    # Disabling: ensure force flag is cleared
                    set_force_next_signal(db, symbol=symbol_upper, strategy_key=strategy_key, side="SELL", enabled=False)
                    logger.info(f"🔄 [SELL ALERT] Cleared force_next_signal for {symbol_upper} SELL")
            except Exception as throttle_err:
                # Log but don't fail the toggle operation
                logger.warning(f"⚠️ [SELL ALERT] Failed to reset throttle state for {symbol_upper}: {throttle_err}", exc_info=True)
        
        logger.info(f"✅ Updated sell_alert_enabled for {symbol_upper}: {sell_alert_enabled}")
        _log_alert_state("SELL ALERT UPDATE", watchlist_item)
        
        return {
            "ok": True,
            "symbol": symbol_upper,
            "sell_alert_enabled": sell_alert_enabled,
            "alert_enabled": watchlist_item.alert_enabled,
            "message": f"SELL alert {'enabled' if sell_alert_enabled else 'disabled'} for {symbol_upper}"
        }
    except HTTPException:
        # Re-raise HTTP exceptions (e.g., from auth)
        raise
    except Exception as e:
        logger.error(f"❌ [SELL ALERT] Error updating sell_alert_enabled for {symbol_upper}: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception as rollback_err:
            logger.error(f"❌ [SELL ALERT] Failed to rollback transaction for {symbol_upper}: {rollback_err}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
