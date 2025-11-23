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
    profile_label = f"Strategy={strategy_type.value.title()} / Approach={risk_approach.value.title()}"
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

    if rsi is None:
        missing.append("RSI")
        return conclude(False, "RSI unavailable")

    if ema10 is None:
        missing.append("EMA10")
        return conclude(False, "EMA10 unavailable")

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

    if strategy_type == StrategyType.SWING and risk_approach == RiskApproach.CONSERVATIVE:
        if not require_indicator(state.ma200, "MA200", "MA200 required for Swing + Conservative"):
            return conclude(False)
        if not require_indicator(state.ma50, "MA50", "MA50 required for Swing + Conservative"):
            return conclude(False)
        if state.rsi >= 35:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 35 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 35")
        if state.price <= state.ma200:
            return conclude(False, f"Price {state.price:.2f} ≤ MA200 {state.ma200:.2f}")
        reasons.append(f"Price {state.price:.2f} > MA200 {state.ma200:.2f}")
        if state.price <= state.ma50:
            return conclude(False, f"Price {state.price:.2f} ≤ MA50 {state.ma50:.2f}")
        reasons.append(f"Price {state.price:.2f} > MA50 {state.ma50:.2f}")
        if state.price <= state.ema10:
            return conclude(False, f"Price {state.price:.2f} ≤ EMA10 {state.ema10:.2f}")
        reasons.append(f"Price {state.price:.2f} > EMA10 {state.ema10:.2f}")
        stretch_cap = state.ma200 * 1.10
        if state.price > stretch_cap:
            return conclude(False, f"Price {state.price:.2f} > stretch cap {stretch_cap:.2f}")
        reasons.append(f"Price within +10% of MA200 ({stretch_cap:.2f})")
        return conclude(True)

    if strategy_type == StrategyType.SWING and risk_approach == RiskApproach.AGGRESSIVE:
        # Swing/Aggressive logic matches dashboard: RSI < 45, MA50 > EMA10 (ma50Check=true), Price > MA200 (ma200Check=true), volume >= 2.0x
        # Dashboard PRESET_CONFIG: maChecks.ma200=true, so Price > MA200 is REQUIRED
        if not require_indicator(state.ma50, "MA50", "MA50 required for Swing + Aggressive"):
            return conclude(False)
        if not require_indicator(state.ema10, "EMA10", "EMA10 required for Swing + Aggressive"):
            return conclude(False)
        if state.rsi >= 45:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 45 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 45")
        # Dashboard checks MA50 > EMA10 (not Price > MA50) when ma50Check=true for Swing-Aggressive
        if state.ma50 <= state.ema10:
            return conclude(False, f"MA50 {state.ma50:.2f} ≤ EMA10 {state.ema10:.2f}")
        reasons.append(f"MA50 {state.ma50:.2f} > EMA10 {state.ema10:.2f}")
        # Dashboard checks Price > MA200 when ma200Check=true for Swing-Aggressive (PRESET_CONFIG: maChecks.ma200=true)
        if state.ma200 is not None:
            if state.price <= state.ma200:
                return conclude(False, f"Price {state.price:.2f} ≤ MA200 {state.ma200:.2f}")
            reasons.append(f"Price {state.price:.2f} > MA200 {state.ma200:.2f}")
        return conclude(True)

    if strategy_type == StrategyType.INTRADAY and risk_approach == RiskApproach.CONSERVATIVE:
        if not require_indicator(state.ma50, "MA50", "MA50 required for Intraday + Conservative"):
            return conclude(False)
        if not require_indicator(state.ma200, "MA200", "MA200 required for Intraday + Conservative"):
            return conclude(False)
        if state.rsi >= 40:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 40 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 40")
        if state.price <= state.ma50:
            return conclude(False, f"Price {state.price:.2f} ≤ MA50 {state.ma50:.2f}")
        reasons.append(f"Price {state.price:.2f} > MA50 {state.ma50:.2f}")
        if state.price <= state.ema10:
            return conclude(False, f"Price {state.price:.2f} ≤ EMA10 {state.ema10:.2f}")
        reasons.append(f"Price {state.price:.2f} > EMA10 {state.ema10:.2f}")
        if state.price < state.ma200:
            return conclude(False, f"Price {state.price:.2f} < MA200 {state.ma200:.2f}")
        reasons.append(f"Price {state.price:.2f} ≥ MA200 {state.ma200:.2f}")
        return conclude(True)

    if strategy_type == StrategyType.INTRADAY and risk_approach == RiskApproach.AGGRESSIVE:
        if state.rsi >= 50:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 50 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 50")
        if state.price <= state.ema10:
            return conclude(False, f"Price {state.price:.2f} ≤ EMA10 {state.ema10:.2f}")
        reasons.append(f"Price {state.price:.2f} > EMA10 {state.ema10:.2f}")
        if state.ma50 is not None:
            relaxed_floor = state.ma50 * 0.97
            if state.price < relaxed_floor:
                return conclude(False, f"Price {state.price:.2f} < MA50 relaxed floor {relaxed_floor:.2f}")
            reasons.append(f"Price {state.price:.2f} ≥ MA50 relaxed floor {relaxed_floor:.2f}")
        if state.ma200 is not None:
            deep_bear_floor = state.ma200 * 0.90
            if state.price < deep_bear_floor:
                return conclude(False, f"Price {state.price:.2f} < MA200 fail-safe {deep_bear_floor:.2f}")
            reasons.append(f"Price {state.price:.2f} above MA200 fail-safe {deep_bear_floor:.2f}")
        return conclude(True)

    if strategy_type == StrategyType.SCALP and risk_approach == RiskApproach.CONSERVATIVE:
        if state.rsi >= 45:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 45 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 45")
        if state.price <= state.ema10:
            return conclude(False, f"Price {state.price:.2f} ≤ EMA10 {state.ema10:.2f}")
        reasons.append(f"Price {state.price:.2f} > EMA10 {state.ema10:.2f}")
        if state.ma50 is not None:
            allowed_dip = state.ma50 * 0.98
            if state.price < allowed_dip:
                return conclude(False, f"Price {state.price:.2f} < MA50 buffer {allowed_dip:.2f}")
            reasons.append(f"Price {state.price:.2f} ≥ MA50 buffer {allowed_dip:.2f}")
        else:
            missing.append("MA50")
            return conclude(False, "MA50 required for Scalp + Conservative")
        return conclude(True)

    if strategy_type == StrategyType.SCALP and risk_approach == RiskApproach.AGGRESSIVE:
        if state.rsi >= 55:
            return conclude(False, f"RSI={state.rsi:.1f} ≥ 55 ceiling")
        reasons.append(f"RSI={state.rsi:.1f} < 55")
        ema_floor = state.ema10 * 0.99
        if state.price < ema_floor:
            return conclude(False, f"Price {state.price:.2f} < EMA10 slack {ema_floor:.2f}")
        reasons.append(f"Price {state.price:.2f} ≥ EMA10 slack {ema_floor:.2f}")
        if state.ma200 is not None:
            knife_floor = state.ma200 * 0.85
            if state.price < knife_floor:
                return conclude(False, f"Price {state.price:.2f} < MA200 safeguard {knife_floor:.2f}")
            reasons.append(f"Price {state.price:.2f} ≥ MA200 safeguard {knife_floor:.2f}")
        return conclude(True)

    # Default fallback mimics swing conservative behavior
    return conclude(False, "Unknown strategy profile")


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

        if decision.should_buy and buy_target_allows:
            rationale_parts = [decision.summary]
            if target_reason:
                rationale_parts.append(target_reason)
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
