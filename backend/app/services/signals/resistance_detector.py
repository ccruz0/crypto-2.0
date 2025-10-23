from typing import List, Dict

def find_resistances(prices: List[float], lookback: int = 50) -> Dict:
    """Find support and resistance levels using swing highs/lows"""
    if len(prices) < lookback:
        return {
            "res_up": prices[-1] if prices else 0,
            "res_down": prices[-1] if prices else 0,
            "method": "insufficient_data"
        }
    
    # Use last lookback periods
    recent_prices = prices[-lookback:]
    
    # Find swing highs (resistance) and swing lows (support)
    swing_highs = []
    swing_lows = []
    
    # Look for local maxima and minima
    for i in range(2, len(recent_prices) - 2):
        # Swing high: price is higher than previous and next 2 candles
        if (recent_prices[i] > recent_prices[i-1] and 
            recent_prices[i] > recent_prices[i-2] and
            recent_prices[i] > recent_prices[i+1] and
            recent_prices[i] > recent_prices[i+2]):
            swing_highs.append(recent_prices[i])
        
        # Swing low: price is lower than previous and next 2 candles
        if (recent_prices[i] < recent_prices[i-1] and 
            recent_prices[i] < recent_prices[i-2] and
            recent_prices[i] < recent_prices[i+1] and
            recent_prices[i] < recent_prices[i+2]):
            swing_lows.append(recent_prices[i])
    
    # Find resistance (highest swing high) and support (lowest swing low)
    res_up = max(swing_highs) if swing_highs else max(recent_prices)
    res_down = min(swing_lows) if swing_lows else min(recent_prices)
    
    return {
        "res_up": round(res_up, 2),
        "res_down": round(res_down, 2),
        "method": "swing_highs+confirm(2)"
    }
