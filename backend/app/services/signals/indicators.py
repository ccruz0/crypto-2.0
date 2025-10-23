from typing import List

def compute_rsi(closes: List[float], period: int = 14) -> float:
    """Compute RSI using classic gain/loss method"""
    if len(closes) < period + 1:
        return 50.0  # Neutral if not enough data
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    # Separate gains and losses
    gains = [delta if delta > 0 else 0 for delta in deltas]
    losses = [-delta if delta < 0 else 0 for delta in deltas]
    
    # Calculate average gain and loss
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)

def compute_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Compute Average True Range"""
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(highs)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        true_ranges.append(max(tr1, tr2, tr3))
    
    if len(true_ranges) < period:
        return 0.0
    
    atr = sum(true_ranges[-period:]) / period
    return round(atr, 2)

def moving_average(values: List[float], period: int) -> float:
    """Compute Simple Moving Average"""
    if len(values) < period:
        return 0.0
    
    ma = sum(values[-period:]) / period
    return round(ma, 2)

def exponential_moving_average(values: List[float], period: int) -> float:
    """Compute Exponential Moving Average"""
    if len(values) < period:
        return 0.0
    
    multiplier = 2 / (period + 1)
    ema = values[-period]
    
    for i in range(-period + 1, 0):
        ema = (values[i] - ema) * multiplier + ema
    
    return round(ema, 2)
