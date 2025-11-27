"""
Trading Signals Service
Implements advanced TP/SL logic with dynamic adjustments and momentum detection.
Extends existing signals calculation with position-aware trading logic.
"""

from dataclasses import dataclass
from typing import Dict, Optional, List
import logging

from app.services.strategy_profiles import StrategyType, RiskApproach

logger = logging.getLogger(__name__)


@dataclass
class IndicatorState:
    symbol: str
    price: float
    rsi: float
    ma200: Optional[float]
    ma50: Optional[float]
    ema10: float


@dataclass
class BuyDecision:
    should_buy: bool
    reasons: List[str]
    missing_indicators: List[str]

    @property
    def summary(self) -> str:
        return " | ".join(filter(None, self.reasons))


# Single entry point for BUY signal evaluation.
def should_trigger_buy_signal(
    *,
    symbol: str,
    price: float,
    rsi: Optional[float],
    ma200: Optional[float],
    ma50: Optional[float],
    ema10: Optional[float],
    strategy_type: StrategyType,
    risk_approach: RiskApproach,
) -> BuyDecision:
    """
    Determine if a BUY signal should trigger based on strategy rules from configuration.
    
    SOURCE OF TRUTH: This function reads from trading_config.json via get_strategy_rules().
    
    Flow:
    1. User configures preset in Signal Configuration tab (frontend)
    2. Frontend saves to backend via /api/config PUT endpoint
    3. Backend stores in trading_config.json under "strategy_rules" key
    4. This function reads from trading_config.json via get_strategy_rules()
    5. Uses same config values for RSI thresholds, MA checks, volume ratios, etc.
    
    This ensures backend alert logic always matches what user configured in UI.
    """
    from app.services.config_loader import get_strategy_rules
    
    # SOURCE OF TRUTH: Read rules from trading_config.json (same config used by Signal Configuration UI)
    preset_name = strategy_type.value.lower()  # e.g., "swing", "intraday", "scalp"
    risk_mode = risk_approach.value.capitalize()  # "Conservative" or "Aggressive"
    rules = get_strategy_rules(preset_name, risk_mode)
    
    # Extract configuration values
    rsi_buy_below = rules.get("rsi", {}).get("buyBelow")
    ma_checks = rules.get("maChecks", {})
    check_ema10 = ma_checks.get("ema10", False)
    check_ma50 = ma_checks.get("ma50", False)
    check_ma200 = ma_checks.get("ma200", False)
    profile_label = f"Strategy={strategy_type.value.title()} / Approach={risk_approach.value.title()} (Config-based)"
    reasons: List[str] = [profile_label]
    missing: List[str] = []

    def conclude(success: bool, extra_reason: Optional[str] = None) -> BuyDecision:
        local_reasons = list(reasons)
        if extra_reason:
            local_reasons.append(extra_reason)
        unique_missing = list(dict.fromkeys(missing))
        decision = BuyDecision(should_buy=success, reasons=local_reasons, missing_indicators=unique_missing)
        if unique_missing:
            logger.warning(
                "⚠️ %s: Missing indicators for %s/%s BUY check: %s",
                symbol,
                strategy_type.value.upper(),
                risk_approach.value.upper(),
                ", ".join(unique_missing),
            )
        return decision

    # Check RSI threshold from config
    if rsi is None:
        missing.append("RSI")
        return conclude(False, "RSI unavailable")
    
    if rsi_buy_below is not None and rsi >= rsi_buy_below:
        return conclude(False, f"RSI={rsi:.1f} ≥ {rsi_buy_below} (threshold from config)")
    reasons.append(f"RSI={rsi:.1f} < {rsi_buy_below or 'N/A'} (from config)")

    # Check required indicators based on maChecks config
    if check_ema10 and ema10 is None:
        missing.append("EMA10")
        return conclude(False, "EMA10 required by config but unavailable")
    
    if check_ma50 and ma50 is None:
        missing.append("MA50")
        return conclude(False, "MA50 required by config but unavailable")
    
    if check_ma200 and ma200 is None:
        missing.append("MA200")
        return conclude(False, "MA200 required by config but unavailable")

    state = IndicatorState(
        symbol=symbol,
        price=price,
        rsi=rsi,
        ma200=ma200,
        ma50=ma50,
        ema10=ema10,
    )

    def require_indicator(value: Optional[float], name: str, explanation: str) -> bool:
        if value is None:
            missing.append(name)
            reasons.append(explanation)
            return False
        return True

    # Apply MA checks based on configuration
    # MA50 check: Price > MA50 OR MA50 > EMA10 (depending on strategy)
    if check_ma50 and ma50 is not None:
        if check_ema10 and ema10 is not None:
            # Dashboard logic: when both ma50 and ema10 are checked, require MA50 > EMA10
            if ma50 <= ema10:
                return conclude(False, f"MA50 {ma50:.2f} ≤ EMA10 {ema10:.2f} (required by config)")
            reasons.append(f"MA50 {ma50:.2f} > EMA10 {ema10:.2f} (from config)")
        else:
            # Only MA50 checked: require Price > MA50
            if price <= ma50:
                return conclude(False, f"Price {price:.2f} ≤ MA50 {ma50:.2f} (required by config)")
            reasons.append(f"Price {price:.2f} > MA50 {ma50:.2f} (from config)")
    
    # MA200 check: Price > MA200
    if check_ma200 and ma200 is not None:
        if price <= ma200:
            return conclude(False, f"Price {price:.2f} ≤ MA200 {ma200:.2f} (required by config)")
        reasons.append(f"Price {price:.2f} > MA200 {ma200:.2f} (from config)")
    
    # EMA10 check: Price > EMA10 (if EMA10 is checked but MA50 is not)
    if check_ema10 and ema10 is not None and not check_ma50:
        if price <= ema10:
            return conclude(False, f"Price {price:.2f} ≤ EMA10 {ema10:.2f} (required by config)")
        reasons.append(f"Price {price:.2f} > EMA10 {ema10:.2f} (from config)")

    # All configured checks passed
    return conclude(True)


def calculate_trading_signals(
    symbol: str,
    price: float,
    rsi: Optional[float] = None,
    atr14: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ema10: Optional[float] = None,
    ma10w: Optional[float] = None,
    volume: Optional[float] = None,
    avg_volume: Optional[float] = None,
    resistance_up: Optional[float] = None,
    buy_target: Optional[float] = None,
    last_buy_price: Optional[float] = None,
    position_size_usd: float = 1000.0,
    rsi_buy_threshold: int = 40,
    rsi_sell_threshold: int = 70,
    strategy_type: StrategyType = StrategyType.SWING,
    risk_approach: RiskApproach = RiskApproach.CONSERVATIVE,
) -> Dict:
    """
    Calculate BUY/SELL signals with dynamic TP/SL adjustment logic.
    
    Args:
        symbol: Trading symbol
        price: Current price
        rsi: RSI value (14 period)
        atr14: ATR value (14 period)
        ma50: Moving average 50
        ma200: Moving average 200
        ema10: Exponential moving average 10
        ma10w: 10-week moving average
        volume: Current volume
        avg_volume: Average volume
        resistance_up: Upper resistance level
        buy_target: Buy target price
        last_buy_price: Last buy price (if position exists)
        position_size_usd: Position size in USD
        strategy_type: Trading strategy archetype (swing/intraday/scalp)
        risk_approach: Risk tolerance (conservative/aggressive)
    
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
        profile_label = f"{strategy_type.value.title()} / {risk_approach.value.title()}"
        decision = should_trigger_buy_signal(
            symbol=symbol,
            price=price,
            rsi=rsi,
            ma200=ma200,
            ma50=ma50,
            ema10=ema10,
            strategy_type=strategy_type,
            risk_approach=risk_approach,
        )

        if decision.missing_indicators:
            result["rationale"].append(f"⚠️ Missing indicators: {', '.join(decision.missing_indicators)}")

        buy_target_allows = True
        target_reason = None
        if buy_target is not None:
            if price <= buy_target:
                target_reason = f"Price {price:.2f} <= buy target {buy_target:.2f}"
            else:
                buy_target_allows = False
                target_reason = f"Price {price:.2f} > buy target {buy_target:.2f}"
        
        # Volume check: require minVolumeRatio (2.0x by default, matching frontend logic)
        # If volume data is not available, assume volume is OK (don't block BUY signal)
        # This matches frontend behavior where volume check defaults to True if data unavailable
        min_volume_ratio = 2.0  # Default 2.0x as per frontend PRESET_CONFIG
        volume_ok = True  # Default to True if volume data not available (matches frontend)
        volume_ratio_val = 0.0
        if volume is not None and avg_volume is not None and avg_volume > 0:
            volume_ratio_val = volume / avg_volume
            volume_ok = volume_ratio_val >= min_volume_ratio  # Require at least 2.0x average volume
        
        # BUY conditions: Must have ALL of the following (matching frontend logic):
        # 1. Strategy-specific BUY conditions (from should_trigger_buy_signal)
        # 2. Buy target allows (if buy_target is set)
        # 3. Volume >= minVolumeRatio (2.0x) - or assumed OK if no volume data
        if decision.should_buy and buy_target_allows and volume_ok:
            rationale_parts = [decision.summary]
            if target_reason:
                rationale_parts.append(target_reason)
            if volume_ok and volume is not None and avg_volume is not None and avg_volume > 0:
                rationale_parts.append(f"Volume {volume_ratio_val:.2f}x >= {min_volume_ratio}x")
            else:
                rationale_parts.append(f"Volume: assumed OK (no data available)")
            clean_rationale = " | ".join(part for part in rationale_parts if part)
            result["buy_signal"] = True
            result["rationale"].append(f"✅ BUY ({profile_label}): {clean_rationale}")

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
            no_buy_reasons = []
            if not decision.should_buy and decision.summary:
                no_buy_reasons.append(decision.summary)
            if not buy_target_allows and target_reason:
                no_buy_reasons.append(target_reason)
            if not volume_ok and volume is not None and avg_volume is not None and avg_volume > 0:
                no_buy_reasons.append(f"Volume {volume_ratio_val:.2f}x < {min_volume_ratio}x")
            elif not volume_ok:
                no_buy_reasons.append(f"Volume: no data available")
            if not no_buy_reasons:
                no_buy_reasons.append("Conditions not met")
            result["rationale"].append(f"⏸️ No buy signal ({profile_label}): {' | '.join(no_buy_reasons)}")
    
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
    # SELL signals must respect the strategy configuration, just like BUY signals
    # Only trigger SELL when strategy-specific reversal conditions are met
    sell_conditions = []
    sell_reasons = []
    
    # SELL signals should respect strategy rules - check for trend reversal conditions
    # Based on frontend logic: RSI > sellAbove AND (MA reversal if MA checks active) AND volume
    
    # Check for MA trend reversal (MA50 < EMA10 with >= 0.5% difference)
    ma_reversal = False
    if ma50 is not None and ema10 is not None:
        if ma50 < ema10:
            price_diff = abs(ma50 - ema10)
            avg_price = (ma50 + ema10) / 2
            percent_diff = (price_diff / avg_price) * 100 if avg_price > 0 else 0
            if percent_diff >= 0.5:
                ma_reversal = True
    
    # Strategy-specific SELL conditions
    # For Swing/Intraday/Scalp, SELL requires:
    # 1. RSI > strategy-specific threshold (from rsi_sell_threshold, typically 70)
    # 2. Trend reversal: MA50 < EMA10 (with >= 0.5% diff) OR Price < MA10w
    # 3. Volume confirmation (if available)
    
    rsi_sell_met = False
    if rsi is not None and rsi > rsi_sell_threshold:
        rsi_sell_met = True
    
    # Check for price breaking below MA10w (trend reversal signal)
    price_below_ma10w = False
    if ma10w is not None and price < ma10w:
        price_below_ma10w = True
    
    # Volume check: require minVolumeRatio (2.0x by default, matching frontend logic)
    # If volume data is not available, assume volume is OK (don't block SELL signal)
    # This matches frontend behavior where volume check defaults to True if data unavailable
    min_volume_ratio = 2.0  # Default 2.0x as per frontend PRESET_CONFIG
    volume_ok = True  # Default to True if volume data not available (matches frontend)
    volume_ratio_val = 0.0
    if volume is not None and avg_volume is not None and avg_volume > 0:
        volume_ratio_val = volume / avg_volume
        volume_ok = volume_ratio_val >= min_volume_ratio  # Require at least 2.0x average volume
    
    # SELL conditions: Must have ALL of the following (matching frontend logic):
    # 1. RSI > strategy-specific threshold (rsi_sell_threshold)
    # 2. Trend reversal: MA50 < EMA10 (with >= 0.5% diff) - only if MA checks would be active
    #    OR Price < MA10w (alternative reversal signal)
    # 3. Volume >= minVolumeRatio (2.0x) - or assumed OK if no volume data
    #
    # NOTE: Frontend checks if MA50 checks are active before requiring MA reversal.
    # For now, we use MA reversal OR price below MA10w as trend reversal signal.
    # This is more conservative than requiring only MA reversal.
    trend_reversal = ma_reversal or price_below_ma10w
    
    # Debug logging for SELL signal calculation
    if symbol == "UNI_USD" or (rsi is not None and rsi > rsi_sell_threshold):
        logger.info(
            f"🔍 {symbol} SELL check: rsi_sell_met={rsi_sell_met}, trend_reversal={trend_reversal} "
            f"(ma_reversal={ma_reversal}, price_below_ma10w={price_below_ma10w}), volume_ok={volume_ok}"
        )
    
    # Only activate SELL when ALL conditions are met
    if rsi_sell_met and trend_reversal and volume_ok:
        sell_conditions.append(True)
        if ma_reversal:
            sell_reasons.append(f"MA trend reversal: MA50 {ma50:.2f} < EMA10 {ema10:.2f}")
        if price_below_ma10w:
            sell_reasons.append(f"Price {price:.2f} < MA10w {ma10w:.2f}")
        sell_reasons.append(f"RSI={rsi:.1f} > {rsi_sell_threshold} (overbought)")
        if volume_ok and volume is not None and avg_volume is not None and avg_volume > 0:
            sell_reasons.append(f"Volume {volume_ratio_val:.2f}x >= {min_volume_ratio}x")
        else:
            sell_reasons.append(f"Volume: assumed OK (no data available)")
        
        if price_below_ma10w:
            result["ma10w_break"] = True
            result["rationale"].append("📉 Significant trend break detected")
    else:
        # Log why SELL signal is not triggered
        missing_conditions = []
        if not rsi_sell_met:
            missing_conditions.append(f"RSI {rsi:.1f} <= {rsi_sell_threshold}")
        if not trend_reversal:
            missing_conditions.append(f"no trend reversal (ma_reversal={ma_reversal}, price_below_ma10w={price_below_ma10w})")
        if not volume_ok:
            missing_conditions.append(f"volume {volume_ratio_val:.2f}x < {min_volume_ratio}x")
        if symbol == "UNI_USD":
            logger.info(f"🔍 {symbol} SELL signal NOT triggered: {', '.join(missing_conditions)}")
    
    # If SELL conditions are met (all must be true)
    if any(sell_conditions):
        result["sell_signal"] = True
        result["rationale"].append(f"🔴 SELL ({strategy_type.value.title()}/{risk_approach.value.title()}): {' | '.join(sell_reasons)}")
    
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
