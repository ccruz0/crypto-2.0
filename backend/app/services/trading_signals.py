"""
Trading Signals Service
Implements advanced TP/SL logic with dynamic adjustments and momentum detection.
Extends existing signals calculation with position-aware trading logic.
"""

from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


def calculate_trading_signals(
    symbol: str,
    price: float,
    rsi: Optional[float] = None,
    atr14: Optional[float] = None,
    ma50: Optional[float] = None,
    ema10: Optional[float] = None,
    ma10w: Optional[float] = None,
    volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
    resistance_up: Optional[float] = None,
    buy_target: Optional[float] = None,
    last_buy_price: Optional[float] = None,
    position_size_usd: float = 1000.0,
    rsi_buy_threshold: int = 40,
    rsi_sell_threshold: int = 70
) -> Dict:
    """
    Calculate BUY/SELL signals with dynamic TP/SL adjustment logic.
    
    Args:
        symbol: Trading symbol
        price: Current price
        rsi: RSI value (14 period)
        atr14: ATR value (14 period)
        ma50: Moving average 50
        ema10: Exponential moving average 10
        ma10w: 10-week moving average
        volume: Current volume
        avg_volume: Average volume
        resistance_up: Upper resistance level
        buy_target: Buy target price
        last_buy_price: Last buy price (if position exists)
        position_size_usd: Position size in USD
    
    Returns:
        Dict with signals, TP, SL, and rationale
    """
    
    # Initialize result with defaults
    result = {
        "symbol": symbol,
        "buy_signal": False,
        "sell_signal": False,
        "tp": None,
        "sl": None,
        "tp_boosted": False,
        "exhaustion": False,
        "ma10w_break": False,
        "rationale": [],
        "position": {
            "last_buy_price": last_buy_price,
            "position_size_usd": position_size_usd
        }
    }
    
    # Check data completeness and log missing values
    missing_data = []
    if rsi is None:
        missing_data.append("RSI")
    if atr14 is None:
        missing_data.append("ATR14")
    
    if missing_data:
        result["rationale"].append(f"⚠️ Missing data: {', '.join(missing_data)}")
    
    # 1. BUY SIGNAL LOGIC
    if not last_buy_price:  # Only check buy if no position exists
        buy_conditions = []
        buy_reasons = []
        
        # RSI < rsi_buy_threshold
        if rsi is not None and rsi < rsi_buy_threshold:
            buy_conditions.append(True)
            buy_reasons.append(f"RSI={rsi:.1f} (<{rsi_buy_threshold})")
        elif rsi is not None:
            buy_conditions.append(False)
            buy_reasons.append(f"RSI={rsi:.1f} not oversold")
        else:
            buy_conditions.append(None)  # Missing RSI, don't block
        
        # Price <= buy_target (if exists)
        if buy_target is not None:
            if price <= buy_target:
                buy_conditions.append(True)
                buy_reasons.append(f"Price {price:.2f} <= buy target {buy_target:.2f}")
            else:
                buy_conditions.append(False)
                buy_reasons.append(f"Price {price:.2f} > buy target {buy_target:.2f}")
        else:
            buy_conditions.append(None)  # No buy target, don't block
        
        # MA50 > EMA10 (trend check)
        if ma50 is not None and ema10 is not None:
            if ma50 > ema10:
                buy_conditions.append(True)
                buy_reasons.append(f"MA50={ma50:.2f} > EMA10={ema10:.2f} (uptrend)")
            else:
                buy_conditions.append(False)
                buy_reasons.append(f"MA50={ma50:.2f} <= EMA10={ema10:.2f} (downtrend)")
        else:
            buy_conditions.append(None)  # Missing MAs, don't block
        
        # Determine buy signal: need at least one True and no False
        filtered_conditions = [c for c in buy_conditions if c is not None]
        if filtered_conditions and all(filtered_conditions):
            result["buy_signal"] = True
            result["rationale"].append(f"✅ BUY: {' | '.join(buy_reasons)}")
            
            # Set initial TP: +3% over entry price
            result["tp"] = round(price * 1.03, 4)
            
            # Set SL: entry - (1.5 × ATR)
            if atr14 is not None and atr14 > 0:
                result["sl"] = round(price - (1.5 * atr14), 4)
                result["rationale"].append(f"Initial SL: {result['sl']:.2f} (entry - 1.5×ATR)")
            else:
                result["sl"] = round(price * 0.97, 4)  # Default 3% stop loss
                result["rationale"].append("⚠️ ATR unavailable, using 3% default SL")
        else:
            result["rationale"].append(f"⏸️ No buy signal: {' | '.join(buy_reasons)}")
    
    # 2. TP BOOST LOGIC (only if position exists)
    if last_buy_price is not None:
        # Check for momentum conditions
        momentum_conditions = []
        
        # RSI between 65-75 with high volume
        if rsi is not None and 65 < rsi < 75:
            momentum_conditions.append("RSI_momentum")
        
        if volume is not None and avg_volume is not None:
            if volume > 1.2 * avg_volume:
                momentum_conditions.append("high_volume")
        
        # Apply TP boost if momentum detected
        if len(momentum_conditions) >= 1:
            base_tp = last_buy_price * 1.05  # +5% from entry
            
            # Use resistance_up if higher than +5%
            if resistance_up is not None and resistance_up > base_tp:
                new_tp = resistance_up
                result["rationale"].append(f"🚀 TP boosted to resistance: {new_tp:.2f}")
            else:
                new_tp = base_tp
                result["rationale"].append(f"🚀 TP boosted to +5%: {new_tp:.2f}")
            
            result["tp"] = round(new_tp, 4)
            result["tp_boosted"] = True
            result["rationale"].append(f"TP boost reason: {' | '.join(momentum_conditions)}")
        
        # Check for exhaustion (RSI high + low volume)
        if rsi is not None and rsi > 70:
            if volume is not None and avg_volume is not None:
                if volume < avg_volume:
                    result["exhaustion"] = True
                    result["rationale"].append(
                        f"⚠️ Exhaustion: RSI={rsi:.1f} > 70, volume {volume:.0f} < avg {avg_volume:.0f}"
                    )
    
    # 3. SELL SIGNAL LOGIC
    sell_conditions = []
    sell_reasons = []
    
    # RSI > rsi_sell_threshold (overbought)
    if rsi is not None and rsi > rsi_sell_threshold:
        sell_conditions.append(True)
        sell_reasons.append(f"RSI={rsi:.1f} > {rsi_sell_threshold} (overbought)")
    
    # Price breaks below MA10w with high volume
    if ma10w is not None and price < ma10w:
        if volume is not None and avg_volume is not None:
            if volume > 1.2 * avg_volume:
                sell_conditions.append(True)
                sell_reasons.append(
                    f"Break below MA10w: price {price:.2f} < MA10w {ma10w:.2f} with high volume"
                )
                result["ma10w_break"] = True
                result["rationale"].append("📉 Significant trend break detected")
    
    # If ANY sell condition is true
    if any(sell_conditions):
        result["sell_signal"] = True
        result["rationale"].append(f"🔴 SELL: {' | '.join(sell_reasons)}")
    
    # 4. Position summary
    if last_buy_price is not None:
        pnl_pct = ((price - last_buy_price) / last_buy_price) * 100
        result["position"]["current_price"] = price
        result["position"]["pnl_pct"] = round(pnl_pct, 2)
        result["position"]["pnl_usd"] = round(position_size_usd * (pnl_pct / 100), 2)
        
        if result["tp"] is None:
            result["tp"] = round(last_buy_price * 1.03, 4)  # Default TP if not set
        if result["sl"] is None:
            result["sl"] = round(last_buy_price * 0.97, 4)  # Default SL if not set
        
        result["rationale"].append(
            f"Position: entry {last_buy_price:.2f} → current {price:.2f} "
            f"({pnl_pct:+.2f}%)"
        )
    
    return result


def get_signal_state_transition(
    old_signals: Dict,
    new_signals: Dict
) -> Dict:
    """
    Detect signal state transitions for alerting.
    
    Returns:
        Dict with alert_type and message if transition detected
    """
    
    alerts = []
    
    # Buy signal transition
    if not old_signals.get("buy_signal", False) and new_signals.get("buy_signal", False):
        alerts.append({
            "alert_type": "BUY_SIGNAL",
            "message": f"{new_signals['symbol']} | BUY | TP={new_signals.get('tp', 'N/A')} | SL={new_signals.get('sl', 'N/A')}"
        })
    
    # Sell signal transition
    if not old_signals.get("sell_signal", False) and new_signals.get("sell_signal", False):
        alerts.append({
            "alert_type": "SELL_SIGNAL",
            "message": f"{new_signals['symbol']} | SELL | {', '.join(new_signals.get('rationale', [])[:2])}"
        })
    
    # TP boost transition
    if not old_signals.get("tp_boosted", False) and new_signals.get("tp_boosted", False):
        alerts.append({
            "alert_type": "TP_BOOSTED",
            "message": f"{new_signals['symbol']} | TP BOOSTED | New TP={new_signals.get('tp', 'N/A')} | Momentum detected"
        })
    
    return {"alerts": alerts, "count": len(alerts)}
