"""
Trading Signals Service
Implements advanced TP/SL logic with dynamic adjustments and momentum detection.
Extends existing signals calculation with position-aware trading logic.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
import logging

from app.services.strategy_profiles import StrategyType, RiskApproach
from app.services.config_loader import get_strategy_rules

logger = logging.getLogger(__name__)

# Volume average period: number of periods used to calculate avg_volume
# This matches the period used in calculate_volume_index() (default: 5)
VOLUME_AVG_PERIODS = 5


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
    condition_flags: Dict[str, Optional[bool]] = field(default_factory=dict)

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
    rules_override: Optional[Dict[str, Any]] = None,
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
    # SOURCE OF TRUTH: Read rules from trading_config.json (same config used by Signal Configuration UI)
    if rules_override is not None:
        rules = rules_override
    else:
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
    condition_flags: Dict[str, Optional[bool]] = {
        "rsi_ok": None,
        "ma_ok": None,
    }
    missing: List[str] = []

    def conclude(success: bool, extra_reason: Optional[str] = None) -> BuyDecision:
        local_reasons = list(reasons)
        if extra_reason:
            local_reasons.append(extra_reason)
        unique_missing = list(dict.fromkeys(missing))
        decision = BuyDecision(
            should_buy=success,
            reasons=local_reasons,
            missing_indicators=unique_missing,
            condition_flags=dict(condition_flags),
        )
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
        condition_flags["rsi_ok"] = False
        return conclude(False, "RSI unavailable")
    
    if rsi_buy_below is not None:
        rsi_ok = rsi < rsi_buy_below
        condition_flags["rsi_ok"] = rsi_ok
        if not rsi_ok:
            return conclude(False, f"RSI={rsi:.1f} ≥ {rsi_buy_below} (threshold from config)")
    else:
        condition_flags["rsi_ok"] = True
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

    ma_checks_passed = True
    # Apply MA checks based on configuration
    # FIXED: Allow < 0.5% tolerance and handle flat markets (equal MAs)
    MA_TOLERANCE_PCT = 0.5  # Allow price to be up to 0.5% below MA
    
    # MA50 check: Price > MA50 OR MA50 > EMA10 (depending on strategy)
    if check_ma50 and ma50 is not None:
        if check_ema10 and ema10 is not None:
            # Dashboard logic: when both ma50 and ema10 are checked, require MA50 > EMA10
            # FIXED: If MAs are equal (flat market), don't block BUY
            if abs(ma50 - ema10) < 0.0001:  # Essentially equal (flat market)
                condition_flags["ma_ok"] = True
                reasons.append(f"MA50 {ma50:.2f} ≈ EMA10 {ema10:.2f} (flat market, allowed)")
            elif ma50 <= ema10:
                condition_flags["ma_ok"] = False
                return conclude(False, f"MA50 {ma50:.2f} ≤ EMA10 {ema10:.2f} (required by config)")
            else:
                condition_flags["ma_ok"] = True
                reasons.append(f"MA50 {ma50:.2f} > EMA10 {ema10:.2f} (from config)")
        else:
            # Only MA50 checked: require Price > MA50 (with tolerance)
            price_diff_pct = ((price - ma50) / ma50) * 100 if ma50 > 0 else 0
            if price <= ma50 and price_diff_pct < -MA_TOLERANCE_PCT:
                condition_flags["ma_ok"] = False
                return conclude(False, f"Price {price:.2f} ≤ MA50 {ma50:.2f} (diff {price_diff_pct:.2f}% < -{MA_TOLERANCE_PCT}%)")
            condition_flags["ma_ok"] = True
            if price > ma50:
                reasons.append(f"Price {price:.2f} > MA50 {ma50:.2f} (from config)")
            else:
                reasons.append(f"Price {price:.2f} ≈ MA50 {ma50:.2f} (within {MA_TOLERANCE_PCT}% tolerance)")
    
    # MA200 check: Price > MA200 (with tolerance)
    if check_ma200 and ma200 is not None:
        price_diff_pct = ((price - ma200) / ma200) * 100 if ma200 > 0 else 0
        if price <= ma200 and price_diff_pct < -MA_TOLERANCE_PCT:
            condition_flags["ma_ok"] = False
            return conclude(False, f"Price {price:.2f} ≤ MA200 {ma200:.2f} (diff {price_diff_pct:.2f}% < -{MA_TOLERANCE_PCT}%)")
        condition_flags["ma_ok"] = True
        if price > ma200:
            reasons.append(f"Price {price:.2f} > MA200 {ma200:.2f} (from config)")
        else:
            reasons.append(f"Price {price:.2f} ≈ MA200 {ma200:.2f} (within {MA_TOLERANCE_PCT}% tolerance)")
    
    # EMA10 check: Price > EMA10 (if EMA10 is checked but MA50 is not) (with tolerance)
    # For scalp strategies, use a more lenient tolerance (5.0%) since they're more aggressive
    # This allows entries when RSI is very low (oversold) even if price is slightly below EMA10
    if check_ema10 and ema10 is not None and not check_ma50:
        # Use more lenient tolerance for scalp strategies (aggressive entries)
        # 5.0% allows buying when RSI is oversold even if price is below EMA10
        tolerance_pct = 5.0 if strategy_type == StrategyType.SCALP else MA_TOLERANCE_PCT
        price_diff_pct = ((price - ema10) / ema10) * 100 if ema10 > 0 else 0
        if price <= ema10 and price_diff_pct < -tolerance_pct:
            condition_flags["ma_ok"] = False
            return conclude(False, f"Price {price:.2f} ≤ EMA10 {ema10:.2f} (diff {price_diff_pct:.2f}% < -{tolerance_pct}%)")
        condition_flags["ma_ok"] = True
        if price > ema10:
            reasons.append(f"Price {price:.2f} > EMA10 {ema10:.2f} (from config)")
        else:
            reasons.append(f"Price {price:.2f} ≈ EMA10 {ema10:.2f} (within {tolerance_pct}% tolerance)")

    if condition_flags["ma_ok"] is None:
        # No MA checks were configured - set to True (not blocking)
        # This happens when all maChecks are False (strategy doesn't require MAs)
        condition_flags["ma_ok"] = True
        reasons.append("No MA checks required (maChecks all False)")

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
    
    CANONICAL RULES:
    - All BUY flags are computed independently of position state (last_buy_price)
    - Position checks belong ONLY in order placement layer, not signal calculation
    - Signals must reflect indicators, not positions
    
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
        last_buy_price: Last buy price (if position exists) - NOT used for signal calculation
        position_size_usd: Position size in USD
        rsi_buy_threshold: RSI buy threshold (legacy, overridden by strategy_rules)
        rsi_sell_threshold: RSI sell threshold (legacy, overridden by strategy_rules)
        strategy_type: Trading strategy archetype (swing/intraday/scalp)
        risk_approach: Risk tolerance (conservative/aggressive)
    
    Returns:
        Dict with signals, TP, SL, strategy_state (decision, index, reasons), and rationale
    """
    
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
    preset_name = strategy_type.value.lower()
    risk_mode = risk_approach.value.capitalize()
    
    # CANONICAL: Load strategy rules from trading_config.json (source of truth)
    try:
        strategy_rules = get_strategy_rules(preset_name, risk_mode)
        logger.debug(
            "[DEBUG_RESOLVED_PROFILE] symbol=%s | preset=%s-%s | rsi_buyBelow=%s | maChecks=%s",
            symbol,
            f"{preset_name}-{risk_mode}",
            strategy_rules.get("rsi", {}).get("buyBelow"),
            strategy_rules.get("maChecks", {})
        )
    except Exception as cfg_err:
        logger.warning(
            "⚠️ Failed to load strategy rules for %s (%s/%s): %s",
            symbol,
            strategy_type.value,
            risk_approach.value,
            cfg_err,
            exc_info=True,
        )
        strategy_rules = {}
    
    # CANONICAL: Get min_volume_ratio from strategy config (Signal Config source of truth)
    # Use get() with explicit None check to handle 0.0 as a valid value (0.0 is falsy but valid)
    min_volume_ratio_raw = strategy_rules.get("volumeMinRatio")
    if min_volume_ratio_raw is None:
        min_volume_ratio = 0.5
        logger.warning(
            "⚠️ Strategy %s/%s has no volumeMinRatio configured for %s, defaulting to 0.5",
            preset_name,
            risk_mode,
            symbol
        )
    else:
        # Ensure it's a float (handle string conversion if needed)
        try:
            min_volume_ratio = float(min_volume_ratio_raw)
        except (ValueError, TypeError):
            logger.warning(
                "⚠️ Invalid volumeMinRatio value '%s' for %s/%s, defaulting to 0.5",
                min_volume_ratio_raw,
                preset_name,
                risk_mode
            )
            min_volume_ratio = 0.5

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
        },
        "current_volume": volume,
        "avg_volume": avg_volume,
        "volume_ratio": None,
        "volume_avg_periods": VOLUME_AVG_PERIODS,  # Number of periods used for avg_volume calculation
        "min_volume_ratio": min_volume_ratio,  # CANONICAL: Include configured threshold for frontend display
    }
    strategy_state: Dict[str, Any] = {
        "decision": "WAIT",
        "summary": "",
        "reasons": {
            "buy_rsi_ok": None,
            "buy_ma_ok": None,
            "buy_volume_ok": None,
            "buy_target_ok": None,
            "sell_rsi_ok": None,
            "sell_trend_ok": None,
            "sell_volume_ok": None,
        },
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
    # ALWAYS evaluate BUY conditions to populate reasons, regardless of position state
    # Signals must reflect indicators, not positions. Position checks belong in order placement layer.
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
        rules_override=strategy_rules,
    )
    strategy_state["summary"] = decision.summary
    
    # Set all condition flags from should_trigger_buy_signal
    strategy_state["reasons"]["buy_rsi_ok"] = decision.condition_flags.get("rsi_ok")
    buy_ma_ok_from_decision = decision.condition_flags.get("ma_ok")
    
    # FIXED: For strategies that don't require MAs, set buy_ma_ok=True (not blocking)
    # Check if strategy requires MAs from config
    ma_checks = strategy_rules.get("maChecks", {})
    requires_ma = ma_checks.get("ema10", False) or ma_checks.get("ma50", False) or ma_checks.get("ma200", False)
    
    if not requires_ma:
        # Strategy doesn't require MAs - set to True so it doesn't block BUY
        strategy_state["reasons"]["buy_ma_ok"] = True
        logger.debug(f"[MA_CHECK] symbol={symbol} strategy doesn't require MAs, setting buy_ma_ok=True")
    else:
        # Strategy requires MAs - use the value from should_trigger_buy_signal
        strategy_state["reasons"]["buy_ma_ok"] = buy_ma_ok_from_decision
    
    if decision.missing_indicators:
        result["rationale"].append(f"⚠️ Missing indicators: {', '.join(decision.missing_indicators)}")

    # Always set buy_target_ok and buy_volume_ok reasons (regardless of position state)
    buy_target_allows = True
    target_reason = None
    if buy_target is not None:
        if price <= buy_target:
            target_reason = f"Price {price:.2f} <= buy target {buy_target:.2f}"
        else:
            buy_target_allows = False
            target_reason = f"Price {price:.2f} > buy target {buy_target:.2f}"
    strategy_state["reasons"]["buy_target_ok"] = buy_target_allows if buy_target is not None else True
    
    # Volume check: require minVolumeRatio (configurable from Signal Config, default 0.5x).
    # CANONICAL: If no volume data is available we assume it's OK (matches frontend behavior).
    # This ensures the canonical rule treats missing volume as "not blocking" (same as frontend)
    volume_ok = True  # Default to True if volume data not available (matches frontend)
    volume_ratio_val: Optional[float] = None
    if volume is not None and avg_volume is not None and avg_volume > 0:
        volume_ratio_val = volume / avg_volume
        # CANONICAL: Use configured min_volume_ratio from Signal Config (strategy_rules)
        # Ensure both values are floats for accurate comparison
        volume_ok = float(volume_ratio_val) >= float(min_volume_ratio)
        result["volume_ratio"] = volume_ratio_val
        
        strategy_state["reasons"]["buy_volume_ok"] = volume_ok
    else:
        # CANONICAL: Set to True (not None) when volume data unavailable to match frontend behavior
        # Frontend assumes volume is OK when data is missing, so backend should too
        strategy_state["reasons"]["buy_volume_ok"] = True
    
    # Price check: ensure price is valid (always True for valid price data)
    strategy_state["reasons"]["buy_price_ok"] = True if price and price > 0 else False
    
    # CANONICAL BUY RULE (PRIMARY): If ALL buy_* reasons are True, BUY must be triggered
    # This rule aligns backend with frontend tooltip logic exactly
    # Collect all buy_* flags - None values are treated as "not blocking" (optional checks)
    buy_flags = {
        "buy_rsi_ok": strategy_state["reasons"].get("buy_rsi_ok"),
        "buy_ma_ok": strategy_state["reasons"].get("buy_ma_ok"),
        "buy_volume_ok": strategy_state["reasons"].get("buy_volume_ok"),
        "buy_target_ok": strategy_state["reasons"].get("buy_target_ok"),
        "buy_price_ok": strategy_state["reasons"].get("buy_price_ok"),
    }
    
    # DEBUG_BUY_FLAGS: Log all buy flags before canonical rule evaluation
    # Calculate index preview for logging (same calculation as below)
    buy_flags_for_index_log = {k: v for k, v in buy_flags.items() if isinstance(v, bool)}
    index_preview = None
    if buy_flags_for_index_log:
        satisfied = sum(1 for v in buy_flags_for_index_log.values() if v is True)
        total = len(buy_flags_for_index_log)
        index_preview = round((satisfied / total) * 100) if total > 0 else 0
    
    logger.info(
        "[DEBUG_BUY_FLAGS] symbol=%s | rsi_ok=%s | ma_ok=%s | vol_ok=%s | target_ok=%s | price_ok=%s | index=%s",
        symbol,
        buy_flags.get("buy_rsi_ok"),
        buy_flags.get("buy_ma_ok"),
        buy_flags.get("buy_volume_ok"),
        buy_flags.get("buy_target_ok"),
        buy_flags.get("buy_price_ok"),
        index_preview,
    )
    
    # Filter to only boolean flags (exclude None) for canonical check
    # FIXED: For strategies without MA requirements, buy_ma_ok may be None or True
    # Only include flags that are actually required (boolean values)
    # None values mean "not applicable" and should not block BUY
    buy_flags_boolean = {k: v for k, v in buy_flags.items() if isinstance(v, bool)}
    
    # CANONICAL RULE: If all boolean buy_* flags are True, BUY is triggered
    # This is the PRIMARY rule - it overrides any other logic
    # FIXED: Ensure we check ALL boolean flags - if any are False, don't trigger BUY
    # Note: buy_ma_ok=None is excluded from this check (means MA not required)
    all_buy_flags_true = bool(buy_flags_boolean) and all(b is True for b in buy_flags_boolean.values())
    
    # CANONICAL BUY RULE: If all boolean buy_* flags are True, set decision=BUY
    # This is the PRIMARY rule and must align with frontend tooltip logic
    
    # CANONICAL: Calculate strategy index from buy_* flags (same logic as frontend computeStrategyIndex)
    # Index = percentage of boolean buy_* flags that are True
    # This must match the frontend logic exactly
    # NOTE: This calculation happens BEFORE the canonical rule, so index reflects current flag state
    buy_flags_for_index = {k: v for k, v in buy_flags.items() if isinstance(v, bool)}
    if buy_flags_for_index:
        satisfied_count = sum(1 for v in buy_flags_for_index.values() if v is True)
        total_count = len(buy_flags_for_index)
        strategy_index = round((satisfied_count / total_count) * 100) if total_count > 0 else 0
    else:
        strategy_index = None  # No boolean flags to evaluate
    
    strategy_state["index"] = strategy_index
    
    # Set BUY signal based on canonical rule (PRIMARY)
    if all_buy_flags_true:
        result["buy_signal"] = True
        strategy_state["decision"] = "BUY"
        
        # Build rationale from individual flags
        rationale_parts = []
        if buy_flags["buy_rsi_ok"] is True and decision.summary:
            rationale_parts.append(decision.summary)
        if buy_flags["buy_target_ok"] is True and target_reason:
            rationale_parts.append(target_reason)
        if buy_flags["buy_volume_ok"] is True:
            if volume is not None and avg_volume is not None and avg_volume > 0:
                rationale_parts.append(f"Volume {volume_ratio_val:.2f}x >= {min_volume_ratio}x")
            else:
                rationale_parts.append("Volume: assumed OK (no data available)")
        if buy_flags["buy_ma_ok"] is True:
            rationale_parts.append("MA conditions met")
        if buy_flags["buy_price_ok"] is True:
            rationale_parts.append("Price valid")
        
        clean_rationale = " | ".join(part for part in rationale_parts if part) or "All BUY conditions met"
        result["rationale"].append(f"✅ BUY ({profile_label}): {clean_rationale}")
        
        # Set initial TP/SL only if no position exists (position management is separate)
        if not last_buy_price:
            # Set initial TP: +3% over entry price
            result["tp"] = round(price * 1.03, 4)

            # Set SL: entry - (1.5 × ATR)
            if atr14 is not None and atr14 > 0:
                result["sl"] = round(price - (1.5 * atr14), 4)
                result["rationale"].append(f"Initial SL: {result['sl']:.2f} (entry - 1.5×ATR)")
            else:
                result["sl"] = round(price * 0.97, 4)  # Default 3% stop loss
                result["rationale"].append("⚠️ ATR unavailable, using 3% default SL")
        
        # Canonical rule triggered - decision=BUY, buy_signal=True
        # Logging happens at end of function via DEBUG_STRATEGY_FINAL
    else:
        # Not all buy flags are True - identify blocking conditions
        no_buy_reasons = []
        if buy_flags["buy_rsi_ok"] is False:
            no_buy_reasons.append(decision.summary or "RSI condition not met")
        if buy_flags["buy_ma_ok"] is False:
            no_buy_reasons.append("MA conditions not met")
        if buy_flags["buy_target_ok"] is False and target_reason:
            no_buy_reasons.append(target_reason)
        if buy_flags["buy_volume_ok"] is False:
            if volume is not None and avg_volume is not None and avg_volume > 0:
                no_buy_reasons.append(f"Volume {volume_ratio_val:.2f}x < {min_volume_ratio}x")
            else:
                no_buy_reasons.append("Volume: no data available")
        if buy_flags["buy_price_ok"] is False:
            no_buy_reasons.append("Price invalid")
        if not no_buy_reasons:
            no_buy_reasons.append("Conditions not met")
        result["rationale"].append(f"⏸️ No buy signal ({profile_label}): {' | '.join(no_buy_reasons)}")
        
        # Not all buy flags are True - canonical rule did not trigger
        # Logging happens at end of function via DEBUG_STRATEGY_FINAL
    
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
    ma_checks_cfg = strategy_rules.get("maChecks", {}) if isinstance(strategy_rules, dict) else {}
    requires_ma_reversal = bool(ma_checks_cfg.get("ma50", True))
    
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
    # 2. Trend reversal (only when strategy requires MA validation)
    # 3. Volume confirmation (if available)
    
    rsi_sell_met = False
    if rsi is not None and rsi > rsi_sell_threshold:
        rsi_sell_met = True
    strategy_state["reasons"]["sell_rsi_ok"] = rsi_sell_met
    
    # Check for price breaking below MA10w (trend reversal signal)
    price_below_ma10w = False
    if ma10w is not None and price < ma10w:
        price_below_ma10w = True
    
    # Volume check: require minVolumeRatio (configurable, default 0.5x). If volume data is missing
    # we assume it's OK (consistent with frontend behavior).
    sell_volume_ok = True  # Default to True if volume data not available (matches frontend)
    sell_volume_ratio = None
    if volume is not None and avg_volume is not None and avg_volume > 0:
        sell_volume_ratio = volume / avg_volume
        sell_volume_ok = sell_volume_ratio >= min_volume_ratio
        strategy_state["reasons"]["sell_volume_ok"] = sell_volume_ok
    else:
        strategy_state["reasons"]["sell_volume_ok"] = None
    
    # SELL conditions: Must have ALL of the following (matching frontend logic):
    # 1. RSI > strategy-specific threshold (rsi_sell_threshold)
    # 2. Trend reversal if strategy requires MA checks; otherwise optional context only.
    # 3. Volume >= minVolumeRatio (configurable) - or assumed OK if no volume data
    #
    # NOTE: Frontend checks if MA50 checks are active before requiring MA reversal.
    # For now, we use MA reversal OR price below MA10w as trend reversal signal.
    # This is more conservative than requiring only MA reversal.
    if requires_ma_reversal:
        trend_reversal = ma_reversal or price_below_ma10w
    else:
        trend_reversal = True  # Strategy doesn't require MA confirmation for SELL
    strategy_state["reasons"]["sell_trend_ok"] = trend_reversal
    
    # Debug logging for SELL signal calculation - ALWAYS log for UNI_USD
    if symbol == "UNI_USD":
        logger.info(
            f"🔍 {symbol} SELL check: rsi={rsi}, rsi_sell_threshold={rsi_sell_threshold}, "
            f"rsi_sell_met={rsi_sell_met}, ma50={ma50}, ema10={ema10}, ma_reversal={ma_reversal}, "
            f"price_below_ma10w={price_below_ma10w}, trend_reversal={trend_reversal}, volume_ok={sell_volume_ok}"
        )
    elif rsi is not None and rsi > rsi_sell_threshold:
        logger.info(
            f"🔍 {symbol} SELL check: rsi_sell_met={rsi_sell_met}, trend_reversal={trend_reversal} "
            f"(ma_reversal={ma_reversal}, price_below_ma10w={price_below_ma10w}, requires_ma_reversal={requires_ma_reversal}), "
            f"volume_ok={sell_volume_ok}"
        )
    
    # Only activate SELL when ALL conditions are met
    if rsi_sell_met and trend_reversal and sell_volume_ok:
        sell_conditions.append(True)
        if requires_ma_reversal:
            if ma_reversal:
                sell_reasons.append(f"MA trend reversal: MA50 {ma50:.2f} < EMA10 {ema10:.2f}")
            if price_below_ma10w:
                sell_reasons.append(f"Price {price:.2f} < MA10w {ma10w:.2f}")
        else:
            if ma_reversal:
                sell_reasons.append("Optional MA reversal observed")
            if price_below_ma10w:
                sell_reasons.append("Optional MA10w break observed")
        sell_reasons.append(f"RSI={rsi:.1f} > {rsi_sell_threshold} (overbought)")
        if sell_volume_ok and volume is not None and avg_volume is not None and avg_volume > 0:
            sell_reasons.append(f"Volume {sell_volume_ratio:.2f}x >= {min_volume_ratio}x")
        else:
            sell_reasons.append(f"Volume: assumed OK (no data available)")
        
        if price_below_ma10w:
            result["ma10w_break"] = True
            result["rationale"].append("📉 Significant trend break detected")
    else:
        # SELL conditions not met - logging happens at end via DEBUG_STRATEGY_FINAL
        pass
    
    # If SELL conditions are met (all must be true)
    # FIXED: SELL must NOT override a BUY decision set by the canonical rule
    # If canonical rule already set decision=BUY, keep it (BUY has priority)
    if any(sell_conditions) and strategy_state["decision"] != "BUY":
        result["sell_signal"] = True
        strategy_state["decision"] = "SELL"
        result["rationale"].append(f"🔴 SELL ({strategy_type.value.title()}/{risk_approach.value.title()}): {' | '.join(sell_reasons)}")
    elif any(sell_conditions) and strategy_state["decision"] == "BUY":
        # SELL conditions met but BUY was already set by canonical rule - keep BUY
        logger.debug(
            "[SELL_OVERRIDE_BLOCKED] symbol=%s | SELL conditions met but BUY decision already set by canonical rule, keeping BUY",
            symbol
        )
    # SELL signal set or not - logging happens at end via DEBUG_STRATEGY_FINAL
    
    # Set final decision based on signals (canonical rule already set BUY if applicable)
    # FIXED: SELL must NEVER override BUY in the same cycle - BUY takes precedence
    # Only set SELL if BUY was not triggered by canonical rule
    if result["sell_signal"] and strategy_state["decision"] != "BUY":
        strategy_state["decision"] = "SELL"
        # Only clear buy_signal if we're actually setting SELL (not if BUY is active)
        result["buy_signal"] = False
        # SELL decision set - logging happens at end via DEBUG_STRATEGY_FINAL
    elif strategy_state["decision"] != "BUY":
        # Only set WAIT if canonical rule didn't already set BUY
        strategy_state["decision"] = "WAIT"
        # Comprehensive logging for WAIT decisions showing all blocking conditions
        blocking_conditions = []
        if strategy_state["reasons"].get("buy_rsi_ok") is False:
            blocking_conditions.append(f"rsi_ok=False (RSI={rsi})")
        if strategy_state["reasons"].get("buy_ma_ok") is False:
            blocking_conditions.append("ma_ok=False")
        if strategy_state["reasons"].get("buy_volume_ok") is False:
            blocking_conditions.append(f"volume_ok=False (ratio={result.get('volume_ratio')})")
        if strategy_state["reasons"].get("buy_target_ok") is False:
            blocking_conditions.append("target_ok=False")
        # Note: last_buy_price is NOT a blocking condition for signals (signals ≠ orders)
        
        # WAIT decision set - logging happens at end via DEBUG_STRATEGY_FINAL
    result["strategy"] = strategy_state

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
    
    # Final debug log to confirm decision and reasons (placed at the very end before return)
    # ALWAYS logged at INFO level for visibility
    # Use the buy_flags dict we computed earlier for consistency
    # CANONICAL: Include volume_ratio and min_volume_ratio for debugging volume threshold issues
    logger.info(
        "[DEBUG_STRATEGY_FINAL] symbol=%s | decision=%s | buy_signal=%s | sell_signal=%s | index=%s | buy_rsi_ok=%s | buy_volume_ok=%s | buy_ma_ok=%s | buy_target_ok=%s | buy_price_ok=%s | volume_ratio=%.4f | min_volume_ratio=%.4f",
        symbol,
        strategy_state.get("decision"),
        result.get("buy_signal"),
        result.get("sell_signal"),
        strategy_state.get("index"),
        buy_flags.get("buy_rsi_ok"),
        buy_flags.get("buy_volume_ok"),
        buy_flags.get("buy_ma_ok"),
        buy_flags.get("buy_target_ok"),
        buy_flags.get("buy_price_ok"),
        volume_ratio_val if volume_ratio_val is not None else -1.0,
        min_volume_ratio,
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
