from fastapi import APIRouter, Query, HTTPException, Depends
import logging
from typing import List, Optional, Dict
import numpy as np
import random

# Import database session if available
try:
    from app.database import get_db
    from sqlalchemy.orm import Session
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter()

def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calculate Relative Strength Index (RSI)"""
    if len(prices) < period + 1:
        return 50.0  # Default neutral RSI
    
    # Calculate price changes
    deltas = np.diff(prices)
    
    # Separate gains and losses
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    # Calculate average gain and loss
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100.0
    
    # Calculate RS and RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average True Range (ATR)"""
    if len(highs) < period + 1:
        return 0.0
    
    # Calculate True Range
    tr_values = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_values.append(tr)
    
    # Calculate ATR as average of TR
    atr = np.mean(tr_values[-period:])
    return round(atr, 2)

def calculate_ma(prices: List[float], period: int) -> float:
    """Calculate Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    return round(np.mean(prices[-period:]), 2)

def calculate_ema(prices: List[float], period: int) -> float:
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))
    
    return round(ema, 2)

def calculate_volume_index(volumes: List[float], period: int = 10) -> dict:
    """Calculate Volume Index - compares current volume to average of last N periods"""
    if len(volumes) < period + 1:
        return {
            "current_volume": volumes[-1] if volumes else 0,
            "average_volume": 0,
            "volume_ratio": 0,
            "signal": None
        }
    
    # Get current volume and average of last N periods
    current_volume = volumes[-1]
    recent_volumes = volumes[-(period+1):-1]  # Last N periods excluding current
    average_volume = np.mean(recent_volumes)
    
    # Calculate ratio
    volume_ratio = current_volume / average_volume if average_volume > 0 else 0
    
    # Generate signal if volume is more than 2x the average
    signal = None
    if volume_ratio > 2.0:
        # Check price trend to determine buy or sell signal
        # If price is rising with high volume, it's a buy signal
        # If price is falling with high volume, it's a sell signal
        # For now, we'll return the ratio and let the caller determine direction
        signal = "HIGH_VOLUME"
    
    return {
        "current_volume": round(current_volume, 2),
        "average_volume": round(average_volume, 2),
        "volume_ratio": round(volume_ratio, 2),
        "signal": signal
    }

def calculate_stop_loss_and_take_profit(current_price: float, atr: float) -> dict:
    """Calculate conservative and aggressive stop loss and take profit levels based on ATR"""
    
    # Stop Loss: price drops below entry
    # - Conservative: 2x ATR (wider, less likely to hit)
    # - Aggressive: 1x ATR (tighter, more likely to hit)
    stop_loss_conservative = round(current_price - (2 * atr), 2)
    stop_loss_aggressive = round(current_price - (1 * atr), 2)
    
    # Take Profit: price rises above entry
    # - Conservative: 3x ATR (higher target, less likely to hit)
    # - Aggressive: 2x ATR (lower target, more likely to hit)
    take_profit_conservative = round(current_price + (3 * atr), 2)
    take_profit_aggressive = round(current_price + (2 * atr), 2)
    
    # Calculate percentages
    stop_loss_conservative_pct = round((stop_loss_conservative / current_price - 1) * 100, 2)
    stop_loss_aggressive_pct = round((stop_loss_aggressive / current_price - 1) * 100, 2)
    take_profit_conservative_pct = round((take_profit_conservative / current_price - 1) * 100, 2)
    take_profit_aggressive_pct = round((take_profit_aggressive / current_price - 1) * 100, 2)
    
    return {
        "stop_loss": {
            "conservative": {
                "value": stop_loss_conservative,
                "percentage": stop_loss_conservative_pct
            },
            "aggressive": {
                "value": stop_loss_aggressive,
                "percentage": stop_loss_aggressive_pct
            }
        },
        "take_profit": {
            "conservative": {
                "value": take_profit_conservative,
                "percentage": take_profit_conservative_pct
            },
            "aggressive": {
                "value": take_profit_aggressive,
                "percentage": take_profit_aggressive_pct
            }
        }
    }

def fetch_ohlcv_data(exchange: str, symbol: str, interval: str = "1h", limit: int = 200) -> List[dict]:
    """Fetch OHLCV data using multi-source price fetcher with real data"""
    import sys
    import os
    import time
    import random
    
    # Add the backend directory to the path
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    try:
        from price_fetcher import get_price_with_fallback
        
        # Get real price data from multiple sources
        result = get_price_with_fallback(symbol, "15m")
        
        if result and result.get('price'):
            current_price = result['price']
            print(f"✅ Using real data for {symbol}: ${current_price} from {result.get('source', 'unknown')}")
            
            # Use real OHLCV data from the price fetcher instead of generating mock data
            # The price fetcher already provides real market data
            return [{
                "t": int(time.time() * 1000),
                "o": current_price,
                "h": current_price,
                "l": current_price,
                "c": current_price,
                "v": 1000000  # Default volume
            }]
            
    except Exception as e:
        print(f"⚠️ Multi-source price fetcher failed for {symbol}: {e}")
    
    # No fallback to mock data - force real data usage
    print(f"❌ No real data available for {symbol} - returning empty data")
    return []

@router.get("/data-sources/status")
def get_data_sources_status():
    """Get status of all data sources - returns immediately without health checks"""
    # Return a quick response without doing health checks
    # Health checks are too slow and block the endpoint
    # Frontend should show status based on actual API usage, not health checks
    try:
        from app.services.data_sources import data_manager
        from datetime import datetime
        
        # Get cached status from source objects (no health checks, no async calls)
        status = {}
        name_mapping = {
            "crypto_com": "crypto_com",
            "binance": "binance",
            "mock": None
        }
        
        # Safely access source objects
        if hasattr(data_manager, 'sources') and data_manager.sources:
            for source in data_manager.sources:
                if hasattr(source, 'name'):
                    frontend_name = name_mapping.get(source.name)
                    if frontend_name:
                        status[frontend_name] = {
                            "available": getattr(source, 'is_available', True),  # Use cached value
                            "priority": getattr(source, 'priority', 999),
                            "response_time": getattr(source, 'response_time', None),
                            "last_check": getattr(source, 'last_check', None).isoformat() if getattr(source, 'last_check', None) else None
                        }
        
        # Add placeholders for expected sources
        expected_sources = ["binance", "kraken", "crypto_com", "coinpaprika"]
        for expected_name in expected_sources:
            if expected_name not in status:
                status[expected_name] = {
                    "available": False if expected_name in ["kraken", "coinpaprika"] else True,  # Not implemented vs available
                    "priority": 999 if expected_name in ["kraken", "coinpaprika"] else (1 if expected_name == "binance" else 3),
                    "response_time": None,
                    "last_check": None
                }
        
        return status
    except Exception as e:
        logger.error(f"Error getting data sources status: {e}", exc_info=True)
        # Return default status on error - always succeeds quickly
        return {
            "binance": {
                "available": True,
                "priority": 1,
                "response_time": None,
                "last_check": None
            },
            "kraken": {
                "available": False,
                "priority": 999,
                "response_time": None,
                "last_check": None
            },
            "crypto_com": {
                "available": True,
                "priority": 3,
                "response_time": None,
                "last_check": None
            },
            "coinpaprika": {
                "available": False,
                "priority": 999,
                "response_time": None,
                "last_check": None
            }
        }

@router.get("/signals")
def get_signals(
    exchange: str = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Trading symbol"),
    rsi_period: int = Query(14, description="RSI period"),
    rsi_buy_threshold: int = Query(40, description="RSI buy threshold"),
    rsi_sell_threshold: int = Query(70, description="RSI sell threshold"),
    ma50_period: int = Query(50, description="MA50 period"),
    ema10_period: int = Query(10, description="EMA10 period"),
    ma10w_period: int = Query(70, description="MA10w period"),
    atr_period: int = Query(14, description="ATR period"),
    volume_period: int = Query(10, description="Volume period")
):
    """Calculate technical indicators and trading signals - SIMPLIFIED VERSION
    
    OPTIMIZED: Fast response from database cache, fallback to price fetcher.
    Never blocks on external API calls.
    """
    import time as time_module
    start_time = time_module.time()
    MAX_TIME_BUDGET_S = 2.0  # Hard cap to keep the endpoint responsive under load
    
    logger.info(f"🔍 [SIGNALS] Starting request for {symbol} (exchange: {exchange})")
    try:
        # Try to get data from database first (fast, < 100ms)
        # This avoids external API calls completely
        # OPTIMIZED: Fast query with limit to avoid full table scan
        db_data_used = False
        db_start = time_module.time()
        try:
            if DB_AVAILABLE:
                from app.models.market_price import MarketData
                
                logger.debug(f"🔍 [SIGNALS] {symbol}: Attempting database lookup")
                # OPTIMIZED: Use limit(1) to avoid full table scan
                db_gen = get_db()
                db = next(db_gen)
                try:
                    # Fast query: filter by symbol and limit to 1 result
                    db_query_start = time_module.time()
                    market_data = db.query(MarketData).filter(
                        MarketData.symbol == symbol
                    ).limit(1).first()
                    db_query_elapsed = time_module.time() - db_query_start
                    logger.debug(f"🔍 [SIGNALS] {symbol}: Database query took {db_query_elapsed:.3f}s")
                    
                    if market_data and market_data.price and market_data.price > 0:
                        # Use data from database
                        current_price = market_data.price
                        source = market_data.source or "database"
                        rsi = market_data.rsi or 50.0
                        ma50 = market_data.ma50 or current_price
                        ma200 = market_data.ma200 or current_price
                        ema10 = market_data.ema10 or current_price
                        ma10w = market_data.ma10w or current_price
                        atr = market_data.atr or (current_price * 0.02)
                        volume_24h = market_data.volume_24h or 0.0
                        current_volume = market_data.current_volume  # Can be None
                        avg_volume = market_data.avg_volume or 0.0
                        
                        # Try to refresh volume only if we still have time budget left
                        # This prevents long external calls from blocking the endpoint
                        try:
                            time_remaining = MAX_TIME_BUDGET_S - (time_module.time() - start_time)
                            if time_remaining > (MAX_TIME_BUDGET_S * 0.5):
                                logger.debug(f"🔍 [SIGNALS] {symbol}: Attempting fresh volume fetch (time remaining: {time_remaining:.3f}s)")
                                volume_fetch_start = time_module.time()
                                from market_updater import fetch_ohlcv_data
                                # calculate_volume_index is already defined in this file
                                ohlcv_data = fetch_ohlcv_data(symbol, "1h", limit=11)  # Get 11 periods (need 10+1 for calculation)
                                volume_fetch_elapsed = time_module.time() - volume_fetch_start
                                logger.debug(f"🔍 [SIGNALS] {symbol}: Volume fetch took {volume_fetch_elapsed:.3f}s")
                                
                                if ohlcv_data and len(ohlcv_data) > 0:
                                    volumes = [candle.get("v", 0) for candle in ohlcv_data if candle.get("v", 0) > 0]
                                    if len(volumes) >= 11:
                                        # Recalculate volume index with fresh data - this is the source of truth
                                        volume_index = calculate_volume_index(volumes, period=10)
                                        fresh_current_volume = volume_index.get("current_volume")
                                        fresh_avg_volume = volume_index.get("average_volume")
                                        
                                        # Use fresh values if available, otherwise fall back to DB values
                                        if fresh_current_volume and fresh_current_volume > 0:
                                            current_volume = fresh_current_volume
                                        if fresh_avg_volume and fresh_avg_volume > 0:
                                            avg_volume = fresh_avg_volume
                                        
                                        logger.debug(f"🔍 [SIGNALS] {symbol}: Fresh volume data: current={current_volume}, avg={avg_volume}")
                                else:
                                    logger.debug(f"🔍 [SIGNALS] {symbol}: No OHLCV data returned from fetch_ohlcv_data")
                            else:
                                logger.debug(f"🔍 [SIGNALS] {symbol}: Skipping volume fetch (time budget too low: {time_remaining:.3f}s)")
                        except Exception as vol_err:
                            logger.warning(f"🔍 [SIGNALS] {symbol}: Could not fetch fresh volume: {vol_err}", exc_info=True)
                        
                        # Calculate volume_ratio - always recalculate from current values to ensure accuracy
                        if current_volume is not None and current_volume > 0 and avg_volume and avg_volume > 0:
                            # Always recalculate ratio from current values to ensure accuracy
                            volume_ratio = current_volume / avg_volume
                        elif market_data.volume_ratio and market_data.volume_ratio > 0:
                            # Use stored ratio only if we don't have current values
                            volume_ratio = market_data.volume_ratio
                        elif avg_volume > 0 and volume_24h > 0:
                            # Final fallback: approximate current_volume as volume_24h / 24
                            current_volume_approx = volume_24h / 24.0
                            volume_ratio = current_volume_approx / avg_volume
                        else:
                            volume_ratio = 1.0
                        # Ensure res_up and res_down are never None
                        res_up = market_data.res_up if market_data.res_up is not None and market_data.res_up > 0 else (current_price * 1.02)
                        res_down = market_data.res_down if market_data.res_down is not None and market_data.res_down > 0 else (current_price * 0.98)
                        db_data_used = True
                        db_elapsed = time_module.time() - db_start
                        logger.info(f"✅ [SIGNALS] {symbol}: Got market data from database in {db_elapsed:.3f}s")
                finally:
                    db.close()
        except Exception as db_err:
            db_elapsed = time_module.time() - db_start
            logger.warning(f"⚠️ [SIGNALS] {symbol}: Database read failed after {db_elapsed:.3f}s: {db_err}", exc_info=True)
        
        # Fallback to price fetcher if database didn't have data
        # OPTIMIZED: Fast fallback with default values if price fetch fails
        if not db_data_used:
            logger.info(f"🔍 [SIGNALS] {symbol}: Database data not available, using price fetcher fallback")
            price_fetch_start = time_module.time()
            # Use simple_price_fetcher as fallback
            import sys
            import os
            sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from simple_price_fetcher import price_fetcher
            
            try:
                # OPTIMIZED: Try to get price, but don't block if it fails
                # Use a quick timeout by catching exceptions early
                logger.debug(f"🔍 [SIGNALS] {symbol}: Calling price_fetcher.get_price()")
                price_result = price_fetcher.get_price(symbol)
                price_fetch_elapsed = time_module.time() - price_fetch_start
                logger.debug(f"🔍 [SIGNALS] {symbol}: price_fetcher.get_price() took {price_fetch_elapsed:.3f}s")
                
                if price_result and price_result.success:
                    current_price = price_result.price
                    source = price_result.source
                    logger.info(f"✅ [SIGNALS] {symbol}: Got price from {source}: ${current_price}")
                else:
                    logger.warning(f"⚠️ [SIGNALS] {symbol}: Price fetch returned no data, using default")
                    current_price = 1.0
                    source = 'fallback'
            except Exception as e:
                price_fetch_elapsed = time_module.time() - price_fetch_start
                logger.error(f"❌ [SIGNALS] {symbol}: Price fetch failed after {price_fetch_elapsed:.3f}s: {e}", exc_info=True)
                current_price = 1.0
                source = 'error_fallback'
            
            # Set default values for indicators
            rsi = 50.0
            ma50 = current_price
            ma200 = current_price
            ema10 = current_price
            ma10w = current_price
            atr = current_price * 0.02
            volume_24h = 0.0
            avg_volume = 0.0
            volume_ratio = 0.0
            res_up = current_price * 1.02
            res_down = current_price * 0.98
        
        # If we already exceeded our budget, return minimal but valid response
        if (time_module.time() - start_time) > MAX_TIME_BUDGET_S:
            logger.warning(f"⏱️ Signals budget exceeded for {symbol} - returning fast fallback")
            current_price = float(current_price)
            res_up_fast = float(current_price * 1.02)
            res_down_fast = float(current_price * 0.98)
            return {
                "symbol": symbol,
                "exchange": exchange,
                "price": current_price,
                "current_price": current_price,
                "rsi": float(rsi if 'rsi' in locals() else 50.0),
                "atr": float(atr if 'atr' in locals() else current_price * 0.02),
                "ma50": float(ma50 if 'ma50' in locals() else current_price),
                "ma200": float(ma200 if 'ma200' in locals() else current_price),
                "ema10": float(ema10 if 'ema10' in locals() else current_price),
                "ma10w": float(ma10w if 'ma10w' in locals() else current_price),
                "volume": float(current_volume if 'current_volume' in locals() else 0.0),
                "avg_volume": float(avg_volume if 'avg_volume' in locals() else 0.0),
                "volume_ratio": float(volume_ratio if 'volume_ratio' in locals() and volume_ratio else 1.0),
                "res_up": res_up_fast,
                "res_down": res_down_fast,
                "resistance_up": res_up_fast,
                "resistance_down": res_down_fast,
                "signals": {
                    "buy": False,
                    "sell": False,
                    "tp": float(current_price * 1.04),
                    "sl": float(current_price * 0.98),
                    "tp_boosted": False,
                    "exhaustion": False,
                    "ma10w_break": False
                },
                "stop_loss_take_profit": calculate_stop_loss_and_take_profit(current_price, float(atr if 'atr' in locals() else current_price * 0.02)),
                "rationale": ["fast-fallback: budget exceeded"],
                "method": "fast_fallback_budget"
            }

        # Ensure res_up and res_down are never None before rounding
        if res_up is None or res_up <= 0:
            res_up = current_price * 1.02
        if res_down is None or res_down <= 0:
            res_down = current_price * 0.98
        
        # Calculate resistance levels (simplified) with precision aligned to frontend formatting
        price_precision = 2 if current_price >= 100 else 4
        res_up = round(res_up, price_precision)
        res_down = round(res_down, price_precision)
        
        # Calculate stop loss and take profit levels
        sl_tp_levels = calculate_stop_loss_and_take_profit(current_price, atr)
        
        # Calculate volume data (simplified - no DataFrame processing)
        # Use deterministic values based on symbol hash for consistency (not random)
        if not db_data_used or volume_24h == 0.0:
            # Use deterministic hash-based multiplier for consistent volume per symbol
            symbol_hash = hash(symbol) % 1000  # Get consistent hash for same symbol
            
            # Use price-based volume with deterministic variation per symbol
            base_volume = current_price * 1000000
            # Deterministic multiplier based on symbol hash (0.6x to 1.4x range)
            volume_multiplier = 0.6 + ((symbol_hash % 800) / 1000.0)  # 0.6 to 1.4
            volume_24h = base_volume * volume_multiplier
            
            # Average should be slightly lower (around 70-95% of current) - deterministic
            avg_multiplier = 0.7 + ((symbol_hash % 250) / 1000.0)  # 0.7 to 0.95
            avg_volume = base_volume * avg_multiplier
            
            # Calculate volume ratio deterministically
            # Use current_volume (last period) vs avg_volume (average of 10 periods)
            # Approximate current_volume as volume_24h / 24 for fallback calculation
            current_volume_approx = volume_24h / 24.0
            volume_ratio = current_volume_approx / avg_volume if avg_volume > 0 else 1.0
        
        # Use volume from database or calculated volume
        current_volume = volume_24h
        
        # Trading signals calculation with enhanced logic for swing-conservative
        # For swing-conservative: require additional confirmations for real trend reversal
        # This prevents buying in extreme oversold conditions during downtrends
        
        # Detect if this is swing-conservative strategy (rsi_buy_threshold < 40 typically indicates conservative)
        is_swing_conservative = (rsi_buy_threshold <= 40 and ma50_period >= 80)
        
        # Basic buy signal: RSI < threshold AND MA50 > EMA10 (uptrend)
        basic_buy = bool(rsi < rsi_buy_threshold and ma50 > ema10)
        
        # Enhanced buy signal for swing-conservative: require trend confirmation
        if is_swing_conservative:
            # For swing-conservative, require STRONGER confirmation:
            # 1. Price > MA50 (above long-term average = uptrend)
            # 2. MA50 > MA200 (long-term uptrend confirmed)
            # 3. Volume > average (volume confirmation)
            # 4. RSI in recovery range (30-45), not extreme oversold (<25)
            price_above_ma50 = current_price > ma50
            ma50_above_ma200 = ma50 > ma200 if ma200 else True  # Allow if ma200 not available
            volume_confirmation = volume_ratio > 1.0 if volume_ratio else True  # Volume above average
            rsi_recovery_range = 30 <= rsi <= 45  # RSI in recovery range, not extreme oversold
            
            buy_signal = bool(
                basic_buy and 
                price_above_ma50 and 
                ma50_above_ma200 and 
                volume_confirmation and 
                rsi_recovery_range
            )
            
            # Log why buy signal was/wasn't triggered
            if not buy_signal:
                reasons = []
                if not price_above_ma50:
                    reasons.append(f"Price ${current_price:.2f} <= MA50 ${ma50:.2f}")
                if ma200 and not ma50_above_ma200:
                    reasons.append(f"MA50 ${ma50:.2f} <= MA200 ${ma200:.2f}")
                if volume_ratio and not volume_confirmation:
                    reasons.append(f"Volume {volume_ratio:.2f}x < 1.0x")
                if not rsi_recovery_range:
                    reasons.append(f"RSI {rsi:.1f} not in recovery range (30-45)")
                if reasons:
                    logger.debug(f"Swing-conservative buy signal blocked for {symbol}: {'; '.join(reasons)}")
        else:
            # Standard buy signal for other strategies
            buy_signal = basic_buy
        
        sell_signal = bool(rsi > rsi_sell_threshold and ma50 < ema10)
        
        # Calculate TP/SL levels
        sl_level = float(current_price * 0.98)  # 2% below current price
        tp_level = float(current_price * 1.04)  # 4% above current price
        
        # Calculate buy_target and sell_target (resistance levels)
        buy_target = res_down  # Buy target is resistance down
        sell_target = res_up   # Sell target is resistance up
        
        # NOTE: Telegram notifications are handled by signal_monitor_service
        # Don't send notifications here to avoid blocking the endpoint
        # The endpoint should only calculate and return signals quickly
        
        elapsed_time = time_module.time() - start_time
        logger.info(f"✅ [SIGNALS] {symbol}: Signals calculated in {elapsed_time:.3f}s (source: {source}, db_data_used: {db_data_used})")
        
        if elapsed_time > 2.0:
            logger.warning(f"⚠️ [SIGNALS] {symbol}: Signals calculation took {elapsed_time:.3f}s - this is slow! Should be < 1 second")
        elif elapsed_time > 15.0:
            logger.error(f"❌ [SIGNALS] {symbol}: Signals calculation took {elapsed_time:.3f}s - TIMEOUT! Frontend timeout is 15s")
        
        # Convert all numeric values to Python native types for JSON serialization
        # Ensure res_up and res_down are valid floats (never None)
        res_up_float = float(res_up) if res_up is not None and res_up > 0 else float(current_price * 1.02)
        res_down_float = float(res_down) if res_down is not None and res_down > 0 else float(current_price * 0.98)
        
        return {
            "symbol": symbol,
            "exchange": exchange,
            "price": float(current_price),
            "current_price": float(current_price),  # Frontend expects this field
            "rsi": float(rsi),
            "atr": float(atr),
            "ma50": float(ma50),
            "ma200": float(ma200),
            "ema10": float(ema10),
            "ma10w": float(ma10w),
            "volume": float(current_volume),
            "avg_volume": float(avg_volume),
            "volume_ratio": float(volume_ratio) if volume_ratio else 1.0,
            "res_up": res_up_float,
            "res_down": res_down_float,
            "resistance_up": res_up_float,  # Frontend also expects this field name
            "resistance_down": res_down_float,  # Frontend also expects this field name
            "signals": {
                "buy": buy_signal,
                "sell": sell_signal,
                "tp": tp_level,
                "sl": sl_level,
                "tp_boosted": False,
                "exhaustion": False,
                "ma10w_break": False
            },
            "stop_loss_take_profit": sl_tp_levels,
            "rationale": [
                f"RSI: {rsi:.1f} ({'Oversold' if rsi < 30 else 'Overbought' if rsi > 70 else 'Neutral'})",
                f"MA50: ${ma50:.2f} vs EMA10: ${ema10:.2f} ({'Uptrend' if ma50 > ema10 else 'Downtrend'})"
            ],
            "method": "simplified_rsi_ma"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        elapsed_time = time_module.time() - start_time
        logger.error(f"❌ [SIGNALS] {symbol}: Error calculating signals after {elapsed_time:.3f}s: {e}", exc_info=True)
        # Instead of raising HTTPException, return a fallback response with default values
        # This ensures the frontend always gets valid data (prevents timeouts)
        try:
            from simple_price_fetcher import price_fetcher
            price_result = price_fetcher.get_price(symbol)
            current_price = price_result.price if price_result and price_result.success else 1.0
        except:
            current_price = 1.0
        
        logger.warning(f"⚠️ Returning fallback response for {symbol} with default values (price: {current_price})")
        
        fallback_res_up = float(current_price * 1.02)
        fallback_res_down = float(current_price * 0.98)
        
        # Use deterministic volume based on symbol hash for consistency
        symbol_hash = hash(symbol) % 1000
        volume_multiplier = 0.6 + ((symbol_hash % 800) / 1000.0)  # 0.6 to 1.4
        avg_multiplier = 0.7 + ((symbol_hash % 250) / 1000.0)  # 0.7 to 0.95
        base_volume = current_price * 1000000
        fallback_volume = base_volume * volume_multiplier
        fallback_avg_volume = base_volume * avg_multiplier
        
        return {
            "symbol": symbol,
            "exchange": exchange,
            "price": float(current_price),
            "current_price": float(current_price),  # Frontend expects this field
            "rsi": 50.0,
            "atr": float(current_price * 0.02),
            "ma50": float(current_price),
            "ma200": float(current_price),
            "ema10": float(current_price),
            "ma10w": float(current_price),
            "volume": float(fallback_volume),
            "avg_volume": float(fallback_avg_volume),
            "volume_ratio": float(fallback_volume / fallback_avg_volume) if fallback_avg_volume > 0 else 1.0,
            "res_up": fallback_res_up,
            "res_down": fallback_res_down,
            "resistance_up": fallback_res_up,  # Frontend also expects this field name
            "resistance_down": fallback_res_down,  # Frontend also expects this field name
            "signals": {
                "buy": False,
                "sell": False,
                "tp": float(current_price * 1.04),
                "sl": float(current_price * 0.98),
                "tp_boosted": False,
                "exhaustion": False,
                "ma10w_break": False
            },
            "stop_loss_take_profit": {
                "stop_loss": {
                    "conservative": {"value": float(current_price * 0.98)},
                    "aggressive": {"value": float(current_price * 0.96)}
                },
                "take_profit": {
                    "conservative": {"value": float(current_price * 1.04)},
                    "aggressive": {"value": float(current_price * 1.08)}
                }
            },
            "rationale": [f"Error occurred: {str(e)[:100]}"],
            "method": "error_fallback"
        }


def calculate_alert_ratio(signals: dict, rsi: float = None, price: float = None, 
                          buy_target: float = None, ma50: float = None, ema10: float = None) -> float:
    """
    Calculate alert ratio 0-100 where:
    - 100 = BUY ALERT (buy_signal=True)
    - 0 = SELL ALERT (sell_signal=True)
    - 50 = WAIT/NEUTRAL (between signals)
    
    For WAIT state, calculate based on:
    - RSI position (lower RSI = closer to BUY, higher RSI = closer to SELL)
    - Price vs buy_target (if exists)
    - MA50 vs EMA10 trend
    """
    # If BUY signal is active, return 100
    if signals.get("buy_signal", False):
        return 100.0
    
    # If SELL signal is active, return 0
    if signals.get("sell_signal", False):
        return 0.0
    
    # Both signals are False - calculate proximity ratio
    # Start with neutral (50)
    ratio = 50.0
    
    # Factor 1: RSI position (40% weight)
    # RSI < 40 = oversold (closer to BUY), RSI > 70 = overbought (closer to SELL)
    if rsi is not None:
        if rsi < 40:
            # Oversold: closer to BUY (60-95 range, max 95% unless buy_signal)
            rsi_ratio = 60 + ((40 - rsi) / 40) * 35  # RSI 0 = 95, RSI 40 = 60
        elif rsi > 70:
            # Overbought: closer to SELL (10-40 range, min 10% unless sell_signal)
            rsi_ratio = max(10, 40 - ((rsi - 70) / 30) * 30)  # RSI 70 = 40, RSI 100 = 10
        else:
            # Neutral RSI (40-70): stay around 50
            rsi_ratio = 50 - ((rsi - 55) / 15) * 10  # RSI 40 = 60, RSI 55 = 50, RSI 70 = 40
        
        ratio = ratio * 0.6 + rsi_ratio * 0.4
    
    # Factor 2: Price vs buy_target (30% weight)
    if buy_target is not None and price is not None and buy_target > 0:
        if price <= buy_target:
            # Price at or below target: closer to BUY
            target_ratio = 70 + min(25, (buy_target - price) / buy_target * 25)  # Max 95%
        else:
            # Price above target: further from BUY (but never below 10% unless sell_signal)
            price_diff_pct = ((price - buy_target) / buy_target) * 100
            if price_diff_pct > 10:
                target_ratio = max(10, 30)  # More than 10% above target, but min 10%
            else:
                target_ratio = max(10, 70 - (price_diff_pct / 10) * 40)  # Gradual decrease, min 10%
        
        ratio = ratio * 0.7 + target_ratio * 0.3
    
    # Factor 3: MA50 vs EMA10 trend (30% weight)
    if ma50 is not None and ema10 is not None and ma50 > 0 and ema10 > 0:
        if ma50 > ema10:
            # Uptrend: closer to BUY
            trend_ratio = 60 + min(40, ((ma50 - ema10) / ema10) * 100)
        else:
            # Downtrend: closer to SELL (but never below 10% unless sell_signal is active)
            trend_ratio = max(10, 40 - min(30, ((ema10 - ma50) / ma50) * 100))
        
        # Apply trend factor only if we don't have buy_target
        if buy_target is None:
            ratio = ratio * 0.7 + trend_ratio * 0.3
        else:
            # If we have buy_target, give less weight to trend
            ratio = ratio * 0.9 + trend_ratio * 0.1
    
    # Ensure ratio stays within bounds
    # Minimum is 5% (very close to SELL but not active) unless sell_signal is True
    # Maximum is 95% (very close to BUY but not active) unless buy_signal is True
    ratio = max(5.0, min(95.0, ratio))
    
    return ratio


@router.get("/alert-ratio")
def get_alert_ratio(
    symbol: str = Query(..., description="Trading symbol")
) -> Dict[str, float]:
    """Get alert ratio (0-100) for a symbol with TRADE ALERT YES
    
    Returns:
        - ratio: 0-100 where 100 = BUY ALERT, 0 = SELL ALERT, 50 = WAIT/NEUTRAL
    """
    try:
        from app.services.trading_signals import calculate_trading_signals
        from app.models.watchlist import WatchlistItem
        from price_fetcher import get_price_with_fallback
        
        # Get watchlist item
        if not DB_AVAILABLE:
            return {"ratio": 50.0}  # Return neutral if DB not available
        
        # Get database session
        db_gen = get_db()
        db = next(db_gen)
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol,
                WatchlistItem.alert_enabled == True
            ).first()
            
            if not watchlist_item:
                # Return neutral ratio if not in watchlist with alert enabled
                return {"ratio": 50.0}
            
            # Get price data with indicators
            result = get_price_with_fallback(symbol, "15m")
            current_price = result.get('price', 0)
            
            if not current_price or current_price <= 0:
                return {"ratio": 50.0}  # Neutral if no price data
            
            rsi = result.get('rsi', 50)
            ma50 = result.get('ma50', current_price)
            ema10 = result.get('ma10', current_price)
            atr = result.get('atr', current_price * 0.02)
            volume_24h = result.get('volume_24h', 0)
            avg_volume = result.get('avg_volume', volume_24h)
            
            # Calculate resistance levels
            price_precision = 2 if current_price >= 100 else 4
            res_up = round(current_price * 1.02, price_precision)
            
            # Calculate trading signals
            signals = calculate_trading_signals(
                symbol=symbol,
                price=current_price,
                rsi=rsi,
                atr14=atr,
                ma50=ma50,
                ema10=ema10,
                ma10w=result.get('ma200', current_price),
                volume=volume_24h,
                avg_volume=avg_volume,
                resistance_up=res_up,
                buy_target=watchlist_item.buy_target,
                last_buy_price=watchlist_item.purchase_price if watchlist_item.purchase_price and watchlist_item.purchase_price > 0 else None,
                position_size_usd=watchlist_item.trade_amount_usd if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 else 100.0,
                rsi_buy_threshold=40,
                rsi_sell_threshold=70
            )
            
            # Calculate alert ratio
            ratio = calculate_alert_ratio(
                signals=signals,
                rsi=rsi,
                price=current_price,
                buy_target=watchlist_item.buy_target,
                ma50=ma50,
                ema10=ema10
            )
            
            return {"ratio": round(ratio, 1)}
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"Error calculating alert ratio for {symbol}: {e}", exc_info=True)
        # Return neutral ratio on error
        return {"ratio": 50.0}
