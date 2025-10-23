import logging
from typing import Dict
from time import time
from app.services.market_data_manager import market_data_manager
from app.services.brokers.base import Exchange
from app.services.signals.indicators import compute_rsi, compute_atr, moving_average, exponential_moving_average
from app.services.signals.resistance_detector import find_resistances

logger = logging.getLogger(__name__)

# Simple cache for signals
_signal_cache: Dict[str, tuple[Dict, float]] = {}
SIGNAL_CACHE_TTL = 60  # seconds

def evaluate_signals(symbol: str, exchange: Exchange) -> Dict:
    """Evaluate technical indicators and signals for a symbol"""
    cache_key = f"{exchange}:{symbol}"
    current_time = time()
    
    # Check cache
    if cache_key in _signal_cache:
        signals, timestamp = _signal_cache[cache_key]
        if current_time - timestamp < SIGNAL_CACHE_TTL:
            logger.info(f"Using cached signals for {symbol} on {exchange}")
            return signals
    
    try:
        # Get OHLCV data
        ohlcv_data = market_data_manager.get_ohlcv(exchange, symbol, "1h", 200)
        
        if not ohlcv_data or len(ohlcv_data) < 50:
            logger.warning(f"Insufficient OHLCV data for {symbol} on {exchange}")
            return {
                "rsi": 50.0,
                "atr": 0.0,
                "ma50": 0.0,
                "ma200": 0.0,
                "ema10": 0.0,
                "res_up": 0.0,
                "res_down": 0.0,
                "method": "insufficient_data"
            }
        
        # Extract price arrays
        closes = [float(candle["c"]) for candle in ohlcv_data]
        highs = [float(candle["h"]) for candle in ohlcv_data]
        lows = [float(candle["l"]) for candle in ohlcv_data]
        prices = closes
        
        # Calculate indicators
        rsi = compute_rsi(closes)
        atr = compute_atr(highs, lows, closes)
        ma50 = moving_average(closes, 50)
        ma200 = moving_average(closes, 200)
        ema10 = exponential_moving_average(closes, 10)
        
        # Find resistances
        resistance_data = find_resistances(prices)
        
        signals = {
            "rsi": rsi,
            "atr": atr,
            "ma50": ma50,
            "ma200": ma200,
            "ema10": ema10,
            "res_up": resistance_data["res_up"],
            "res_down": resistance_data["res_down"],
            "method": resistance_data["method"]
        }
        
        # Update cache
        _signal_cache[cache_key] = (signals, current_time)
        
        logger.info(f"Signals for {symbol} on {exchange}: RSI={rsi}, Res_up={resistance_data['res_up']}, Res_down={resistance_data['res_down']}")
        
        return signals
        
    except Exception as e:
        logger.error(f"Error evaluating signals for {symbol} on {exchange}: {e}")
        return {
            "rsi": 50.0,
            "atr": 0.0,
            "ma50": 0.0,
            "ma200": 0.0,
            "ema10": 0.0,
            "res_up": 0.0,
            "res_down": 0.0,
            "method": "error"
        }
